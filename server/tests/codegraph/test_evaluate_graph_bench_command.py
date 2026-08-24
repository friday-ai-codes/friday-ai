"""``evaluate_graph_bench`` command 默认套件（不跑真仓 OK 路径，无需 Qdrant）。

覆盖三类 fail-closed 行为：

1. **fixture 权威校验**：对 Plan 02 真实冻结 fixtures 跑 ``validate_gold_dataset``，
   断言通过（锁住 Plan 02 schema 不漂移）。
2. **水位 INVALID 短路**：测试库建 ``Repository`` + ``RepositoryBranchIndex``，三方水位
   互不一致 → command 抛 ``CommandError``、manifest 写出且 ``watermark=="INVALID"``、
   ``get_graph`` mock 未被调用（绝不跑任何 case / 被测能力）。
3. **schema 错误 fail-closed**：构造缺必填分桶维度的 gold → ``CommandError``。

ORM 访问跨线程（command 内 ``sync_to_async`` 读水位），故用 ``transaction=True``
让数据落库可见（文件测试库 + busy timeout，见 conftest）。
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from codegraph.services.graph_bench_eval import validate_gold_dataset

_FIXTURES = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "graph_bench"
)


def _write_gold_dir(root: Path, *, annotated_at_sha: str) -> Path:
    """在 ``root`` 下造一个 schema 合法但水位可控的最小 gold 目录。"""
    gold = root / "gold"
    gold.mkdir(parents=True, exist_ok=True)
    manifest = {
        "gold_version": "1",
        "annotated_at_sha": annotated_at_sha,
        "repository": "test-repo",
        "branch": "main",
        "splits": {
            "dev": "dev.json",
            "locked_test": "locked_test.json",
            "holdout": "holdout.json",
        },
    }
    case = {
        "case_id": "t-0001",
        "split": "dev",
        "query": "哪个函数处理登录？",
        "language": "python",
        "framework": "django",
        "entry_type": "http_endpoint",
        "expected_symbols": [{"uid": "py:app/auth.py::login"}],
        "expected_processes": [],
        "edge_golds": [],
        "trace_golds": [],
        "impact_golds": [],
        "protected": False,
    }
    (gold / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    for name in ("dev", "locked_test"):
        (gold / f"{name}.json").write_text(
            json.dumps({"cases": [case]}, ensure_ascii=False), encoding="utf-8"
        )
    (gold / "holdout.json").write_text(
        json.dumps({"cases": []}, ensure_ascii=False), encoding="utf-8"
    )
    return gold


def test_real_fixtures_validate_authoritative() -> None:
    """Plan 02 真实 fixtures 必须通过 validate_gold_dataset（锁 schema 不漂移）。"""
    manifest = json.loads((_FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    cases: list[dict] = []
    for split in ("dev", "locked_test"):
        rel = manifest["splits"][split]
        data = json.loads((_FIXTURES / rel).read_text(encoding="utf-8"))
        cases.extend(data.get("cases") or [])
    dataset = validate_gold_dataset(manifest, cases)
    assert dataset.gold_version
    assert len(dataset.cases) == len(cases) > 0


@pytest.mark.django_db(transaction=True)
def test_watermark_invalid_short_circuits(tmp_path: Path) -> None:
    """三方水位互不一致 → INVALID 短路、写 manifest、非零退出、get_graph 未被调用。"""
    from repositories.models import Repository, RepositoryBranchIndex

    repo = Repository.objects.create(
        name="bench-repo", git_url="https://example.com/bench.git"
    )
    RepositoryBranchIndex.objects.create(
        repository=repo,
        branch_name="main",
        is_base_branch=True,
        last_indexed_commit_sha="sha_index",
        head_sha="sha_head",
    )
    gold_dir = _write_gold_dir(tmp_path, annotated_at_sha="sha_gold")
    manifest_out = tmp_path / "manifest.json"

    mock_service = MagicMock(name="GraphService")
    with patch(
        "services.code_graph.cache.get_graph_service", return_value=mock_service
    ) as mock_factory:
        with pytest.raises(CommandError):
            call_command(
                "evaluate_graph_bench",
                repo=str(repo.id),
                branch="main",
                commit_sha="sha_src",
                gold=str(gold_dir),
                output_manifest=str(manifest_out),
            )

    # 水位闸 fail-closed：绝不调用 get_graph / 任何被测能力。
    mock_factory.assert_not_called()
    mock_service.get_graph.assert_not_called()

    payload = json.loads(manifest_out.read_text(encoding="utf-8"))
    assert payload["watermark"] == "INVALID"
    assert payload["invalid_reason"]
    assert payload["identity"]["repository"] == str(repo.id)
    assert payload["identity"]["index_key_source"] == "last_indexed_commit_sha"
    assert payload["run_id"]
    assert "evaluate_graph_bench" in payload["reproducible_command"]


def test_gold_schema_error_fail_closed(tmp_path: Path) -> None:
    """gold 缺必填分桶维度 → schema 校验失败 → CommandError。"""
    gold = tmp_path / "gold"
    gold.mkdir(parents=True, exist_ok=True)
    manifest = {
        "gold_version": "1",
        "annotated_at_sha": "sha",
        "splits": {"dev": "dev.json", "locked_test": "locked_test.json", "holdout": "h.json"},
    }
    bad_case = {
        "case_id": "bad-1",
        "split": "dev",
        "query": "缺 language/framework/entry_type 的 case",
    }
    (gold / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (gold / "dev.json").write_text(
        json.dumps({"cases": [bad_case]}), encoding="utf-8"
    )
    (gold / "locked_test.json").write_text(json.dumps({"cases": []}), encoding="utf-8")
    (gold / "h.json").write_text(json.dumps({"cases": []}), encoding="utf-8")

    with pytest.raises(CommandError):
        call_command(
            "evaluate_graph_bench",
            repo="00000000-0000-0000-0000-000000000000",
            commit_sha="sha",
            gold=str(gold),
            split="dev",
        )
