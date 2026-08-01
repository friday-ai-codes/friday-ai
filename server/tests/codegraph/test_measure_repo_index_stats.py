"""measure_repo_index_stats management command 测试（105-02 Task 1 + 106-04 扩展）。

用 ``QdrantClient(":memory:")`` monkeypatch ``QdrantService.get_client``（先例
``test_milestone_e2e_learning_case.py``），灌 2 仓不同数量的点，断言：

- per-repo count 与灌入点数一致（top 表）
- JSON 输出含 p50/p90/p99/max/median 键
- ``--verify-cosine`` 在 hybrid collection 上可得 COSINE 分（自查询 top-1 ≈ 1.0）
- 单仓 count 异常不中断全量统计（best-effort）
- ``--activity``（106-04，O-5）：last_commit_at 覆盖率/新鲜度分位数结构正确、
  无 FileIndex 仓计入未覆盖；facets 五维覆盖率（「未分类」不算覆盖）
- ``--write-snapshot``（106-04，ROUTE-03）：写读闭环——``load_nr_snapshot()``
  读回 n_r_by_repo/n_bar 与写入一致；空库拒绝写入

本地内存 Qdrant 只验证**结构性正确**（统计口径 / 输出形状）；N_r 真实分布
须在生产实例执行（见 105/106-MEASUREMENTS.md）。
"""

from __future__ import annotations

import io
import json
import math
import statistics
import uuid
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.utils import timezone
from qdrant_client import QdrantClient, models

from codegraph.services.repo_router_config import load_nr_snapshot
from repositories.models import FileIndex, Repository
from services.qdrant_service import QdrantService
from system.models import SettingKeys, SystemSetting
from system.settings_service import _cache_key

DENSE_DIM = 8


@pytest.fixture(autouse=True)
def _clear_setting_cache():
    """settings_service 缓存跨用例共享（locmem 不随测试事务回滚），前后各清一次。"""
    cache.delete(_cache_key(SettingKeys.REPO_ROUTER_NR_SNAPSHOT))
    yield
    cache.delete(_cache_key(SettingKeys.REPO_ROUTER_NR_SNAPSHOT))


def _dense(seed: int) -> list[float]:
    """确定性单位向量（避免随机性，COSINE 自查询 top-1 恒为 1.0）。"""
    raw = [math.sin(seed * 31 + i) + 2.0 for i in range(DENSE_DIM)]
    norm = math.sqrt(sum(v * v for v in raw))
    return [v / norm for v in raw]


def _make_repo(name: str) -> Repository:
    return Repository.objects.create(
        name=name,
        git_url=f"https://example.com/{name}.git",
        default_branch="main",
    )


def _seed_points(client: QdrantClient, repository_id: str, count: int, seed_base: int) -> None:
    points = [
        models.PointStruct(
            id=str(uuid.uuid4()),
            vector={
                "dense": _dense(seed_base + i),
                "sparse": models.SparseVector(indices=[seed_base + i], values=[1.0]),
            },
            payload={"repository_id": repository_id, "node_id": f"n-{seed_base + i}"},
        )
        for i in range(count)
    ]
    client.upsert(collection_name="repo_index_nodes", points=points)


@pytest.fixture
def memory_qdrant(monkeypatch: pytest.MonkeyPatch) -> QdrantClient:
    """内存 Qdrant + hybrid repo_index_nodes collection（与生产同形：命名 dense/sparse）。"""
    local_client = QdrantClient(":memory:")
    monkeypatch.setattr(QdrantService, "get_client", classmethod(lambda cls: local_client))
    local_client.create_collection(
        collection_name="repo_index_nodes",
        vectors_config={
            "dense": models.VectorParams(size=DENSE_DIM, distance=models.Distance.COSINE),
        },
        sparse_vectors_config={"sparse": models.SparseVectorParams()},
    )
    return local_client


def _run_command(*args: str) -> str:
    out = io.StringIO()
    call_command("measure_repo_index_stats", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_json_output_per_repo_counts_and_quantile_keys(memory_qdrant: QdrantClient) -> None:
    """per-repo count 与灌入点数一致；JSON 含 p50/p90/p99/max/median 键。"""
    repo_small = _make_repo("small-repo")
    repo_big = _make_repo("big-repo")
    repo_empty = _make_repo("empty-repo")
    _seed_points(memory_qdrant, str(repo_small.id), count=3, seed_base=100)
    _seed_points(memory_qdrant, str(repo_big.id), count=7, seed_base=200)

    report = json.loads(_run_command("--json"))

    for key in ("p50", "p90", "p99", "max", "median", "mean"):
        assert key in report, f"缺少分位数键: {key}"

    by_id = {row["repository_id"]: row["node_count"] for row in report["per_repo"]}
    assert by_id[str(repo_small.id)] == 3
    assert by_id[str(repo_big.id)] == 7
    assert by_id[str(repo_empty.id)] == 0

    assert report["total_repos"] == 3
    assert report["counted_repos"] == 3
    assert report["indexed_repos"] == 2
    assert report["max"] == 7


@pytest.mark.django_db
def test_top_ordering_by_node_count(memory_qdrant: QdrantClient) -> None:
    """--top 按节点数降序（同分按 repository_id 稳定排序）。"""
    repo_a = _make_repo("repo-a")
    repo_b = _make_repo("repo-b")
    _seed_points(memory_qdrant, str(repo_a.id), count=2, seed_base=300)
    _seed_points(memory_qdrant, str(repo_b.id), count=5, seed_base=400)

    report = json.loads(_run_command("--json", "--top", "1"))

    assert len(report["top"]) == 1
    assert report["top"][0]["repository_id"] == str(repo_b.id)
    assert report["top"][0]["node_count"] == 5


@pytest.mark.django_db
def test_verify_cosine_returns_cosine_scores(memory_qdrant: QdrantClient) -> None:
    """--verify-cosine：dense-only 自查询 top-1 余弦 ≈ 1.0（O-3 结构性验证）。"""
    repo = _make_repo("cosine-repo")
    _seed_points(memory_qdrant, str(repo.id), count=4, seed_base=500)

    report = json.loads(_run_command("--json", "--verify-cosine"))

    probe = report["cosine_probe"]
    assert probe["status"] == "ok"
    assert probe["repository_id"] == str(repo.id)
    assert probe["scores"], "应返回 score 样例"
    assert probe["scores"][0] == pytest.approx(1.0, abs=1e-4)
    assert "duration_ms" in probe


@pytest.mark.django_db
def test_verify_cosine_skipped_when_no_indexed_repo(memory_qdrant: QdrantClient) -> None:
    """无任何有索引仓时 --verify-cosine 记 skipped，不报错。"""
    _make_repo("bare-repo")

    report = json.loads(_run_command("--json", "--verify-cosine"))

    assert report["cosine_probe"] == {"status": "skipped", "reason": "no_indexed_repo"}


@pytest.mark.django_db
def test_per_repo_count_failure_is_skipped_not_fatal(
    memory_qdrant: QdrantClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """单仓 count 异常 warning 跳过，其余仓照常统计（best-effort）。"""
    repo_ok = _make_repo("ok-repo")
    repo_bad = _make_repo("bad-repo")
    _seed_points(memory_qdrant, str(repo_ok.id), count=2, seed_base=600)

    original_count = memory_qdrant.count

    def _flaky_count(collection_name: str, count_filter: models.Filter, **kwargs):
        match = count_filter.must[0].match  # type: ignore[union-attr]
        if match.value == str(repo_bad.id):  # type: ignore[union-attr]
            raise RuntimeError("simulated qdrant failure")
        return original_count(collection_name=collection_name, count_filter=count_filter, **kwargs)

    monkeypatch.setattr(memory_qdrant, "count", _flaky_count)

    report = json.loads(_run_command("--json"))

    assert report["total_repos"] == 2
    assert report["counted_repos"] == 1
    counted_ids = {row["repository_id"] for row in report["per_repo"]}
    assert counted_ids == {str(repo_ok.id)}


@pytest.mark.django_db
def test_markdown_output_without_json_flag(memory_qdrant: QdrantClient) -> None:
    """默认输出 markdown 表（列：指标/值）。"""
    repo = _make_repo("md-repo")
    _seed_points(memory_qdrant, str(repo.id), count=1, seed_base=700)

    output = _run_command()

    assert "| 指标 | 值 |" in output
    assert "N_r 分布" in output


# ---------------------------------------------------------------------------
# 106-04：--activity（O-5）与 --write-snapshot（ROUTE-03）
# ---------------------------------------------------------------------------


def _add_file_index(repo: Repository, path: str, authored_days_ago: int | None) -> None:
    FileIndex.objects.create(
        repository=repo,
        file_path=path,
        file_hash="0" * 64,
        last_commit_authored_at=(
            timezone.now() - timedelta(days=authored_days_ago)
            if authored_days_ago is not None
            else None
        ),
    )


@pytest.mark.django_db
def test_activity_stats_coverage_and_freshness(memory_qdrant: QdrantClient) -> None:
    """--activity：覆盖率 = 有 last_commit_at 仓数/总仓数；无 FileIndex 仓计入未覆盖。

    每仓口径取 Max(last_commit_authored_at)：repo_a 有 20/10 天两行 → 取 10 天。
    ages=[10, 30] → p50=20、p90=28（线性插值，与 repo_router_eval 同口径）。
    """
    repo_a = _make_repo("act-a")
    repo_b = _make_repo("act-b")
    _make_repo("act-bare")  # 无 FileIndex 行 → 未覆盖
    _add_file_index(repo_a, "old.py", authored_days_ago=20)
    _add_file_index(repo_a, "new.py", authored_days_ago=10)
    _add_file_index(repo_b, "only.py", authored_days_ago=30)

    report = json.loads(_run_command("--json", "--activity"))

    stats = report["activity_stats"]
    assert stats["total_repos"] == 3
    assert stats["covered_repos"] == 2
    assert stats["coverage"] == pytest.approx(2 / 3, abs=1e-3)
    assert stats["freshness_days_p50"] == pytest.approx(20.0, abs=0.1)
    assert stats["freshness_days_p90"] == pytest.approx(28.0, abs=0.1)


@pytest.mark.django_db
def test_activity_null_authored_at_counts_uncovered(memory_qdrant: QdrantClient) -> None:
    """FileIndex 行存在但 last_commit_authored_at 全为 NULL → 该仓仍未覆盖。"""
    repo = _make_repo("act-null")
    _add_file_index(repo, "x.py", authored_days_ago=None)

    report = json.loads(_run_command("--json", "--activity"))

    stats = report["activity_stats"]
    assert stats["total_repos"] == 1
    assert stats["covered_repos"] == 0
    assert stats["freshness_days_p50"] is None
    assert stats["freshness_days_p90"] is None


@pytest.mark.django_db
def test_activity_facets_coverage_five_dims(memory_qdrant: QdrantClient) -> None:
    """facets 五维覆盖率：业务线/产品线的「未分类」计未覆盖，其余维度非空即覆盖。"""
    repo_full = _make_repo("facet-full")
    repo_full.facets = {
        "业务线/产品线": "在线教育",
        "技术栈": "Python/Vue",
        "关键程度": "核心",
    }
    repo_full.save(update_fields=["facets"])
    repo_thin = _make_repo("facet-thin")
    repo_thin.facets = {"业务线/产品线": "未分类", "活跃度": "维护中"}
    repo_thin.save(update_fields=["facets"])

    report = json.loads(_run_command("--json", "--activity"))

    coverage = report["facets_coverage"]
    assert set(coverage) == {"业务线/产品线", "技术栈", "团队归属", "关键程度", "活跃度"}
    assert coverage["业务线/产品线"]["covered"] == 1  # 「未分类」不算覆盖
    assert coverage["技术栈"]["covered"] == 1
    assert coverage["团队归属"]["covered"] == 0
    assert coverage["关键程度"]["covered"] == 1
    assert coverage["活跃度"]["covered"] == 1
    for row in coverage.values():
        assert row["total"] == 2
        assert row["ratio"] == pytest.approx(row["covered"] / 2, abs=1e-6)


@pytest.mark.django_db
def test_write_snapshot_roundtrip_with_loader(memory_qdrant: QdrantClient) -> None:
    """--write-snapshot 写读闭环：load_nr_snapshot() 读回与写入一致（ROUTE-03 契约）。

    n_bar = 有索引仓（node_count > 0）节点数的 statistics.median；
    n_r_by_repo **只收 node_count > 0 的仓**（MJ-04：写入 0 会被 scorer 当有效
    体量 → denom_size=1-b=0.4，未索引仓反拿最强的尺寸归一红利；缺失才是中性）。
    """
    repo_small = _make_repo("snap-small")
    repo_big = _make_repo("snap-big")
    repo_empty = _make_repo("snap-empty")
    _seed_points(memory_qdrant, str(repo_small.id), count=3, seed_base=800)
    _seed_points(memory_qdrant, str(repo_big.id), count=7, seed_base=900)

    report = json.loads(_run_command("--json", "--write-snapshot"))

    assert report["nr_snapshot"]["written"] is True
    assert report["nr_snapshot"]["n_bar"] == statistics.median([3, 7])
    assert report["nr_snapshot"]["repo_count"] == 2

    snapshot = load_nr_snapshot()
    assert snapshot["n_bar"] == statistics.median([3, 7])
    assert snapshot["n_r_by_repo"] == {
        str(repo_small.id): 3,
        str(repo_big.id): 7,
    }
    assert str(repo_empty.id) not in snapshot["n_r_by_repo"]
    assert snapshot["generated_at"]


@pytest.mark.django_db
def test_write_snapshot_refuses_empty_library(memory_qdrant: QdrantClient) -> None:
    """无任何已索引仓时拒绝写入（防空快照覆盖有效值，T-106-09）。"""
    _make_repo("bare-only")

    report = json.loads(_run_command("--json", "--write-snapshot"))

    assert report["nr_snapshot"] == {"written": False, "reason": "no_indexed_repo"}
    assert not SystemSetting.objects.filter(key=SettingKeys.REPO_ROUTER_NR_SNAPSHOT).exists()
    assert load_nr_snapshot()["n_bar"] is None


@pytest.mark.django_db
def test_markdown_output_includes_activity_and_snapshot_sections(
    memory_qdrant: QdrantClient,
) -> None:
    """markdown 输出含 O-5 统计节与快照写入回显（n_bar 与仓数）。"""
    repo = _make_repo("md-106")
    _seed_points(memory_qdrant, str(repo.id), count=2, seed_base=1000)
    _add_file_index(repo, "a.py", authored_days_ago=5)

    output = _run_command("--activity", "--write-snapshot")

    assert "last_commit_at 覆盖率与新鲜度" in output
    assert "facets 五维覆盖率" in output
    assert "N_r 快照写入" in output
    assert "n_bar（中位数）= 2.0" in output
    assert "仓数 1" in output
