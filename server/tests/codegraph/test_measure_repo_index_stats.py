"""measure_repo_index_stats management command 测试（105-02 Task 1）。

用 ``QdrantClient(":memory:")`` monkeypatch ``QdrantService.get_client``（先例
``test_milestone_e2e_learning_case.py``），灌 2 仓不同数量的点，断言：

- per-repo count 与灌入点数一致（top 表）
- JSON 输出含 p50/p90/p99/max/median 键
- ``--verify-cosine`` 在 hybrid collection 上可得 COSINE 分（自查询 top-1 ≈ 1.0）
- 单仓 count 异常不中断全量统计（best-effort）

本地内存 Qdrant 只验证**结构性正确**（统计口径 / 输出形状）；N_r 真实分布
须在生产实例执行（见 105-MEASUREMENTS.md）。
"""

from __future__ import annotations

import io
import json
import math
import uuid

import pytest
from django.core.management import call_command
from qdrant_client import QdrantClient, models

from repositories.models import Repository
from services.qdrant_service import QdrantService

DENSE_DIM = 8


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
