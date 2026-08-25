"""Phase 133–140 单仓图查询的跨消费面与外部证据收口门禁。"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import re
import runpy
from pathlib import Path

from codegraph.management.commands.evaluate_graph_bench import (
    _benchmark_environment_preflight,
)
from codegraph.services import graph_bench_compare
from services.code_graph import process_index, query_service
from services.code_graph.query_manifest import (
    graph_query_manifest,
    graph_query_manifest_hash,
)

_ROOT = Path(__file__).resolve().parents[3]
_CONTRACT = _ROOT / "server/contracts/graph-query.v1.json"
_FIXTURES = _ROOT / "server/tests/fixtures/graph_bench"
_POLICY = _ROOT / "server/codegraph/benchmark_policies/graph_query_threshold_policy.v1.json"


def test_canonical_manifest_hash_and_versions_match_all_generated_consumers() -> None:
    """canonical raw bytes、service、task 与 npm MCP 必须共享完整身份。"""
    raw = _CONTRACT.read_bytes()
    manifest = json.loads(raw)
    expected_hash = hashlib.sha256(raw).hexdigest()

    assert graph_query_manifest() == manifest
    assert graph_query_manifest_hash() == expected_hash
    assert manifest["contract_version"] == "graph-query-tool/v1"
    assert manifest["response_version"] == query_service.GRAPH_QUERY_RESPONSE_VERSION
    assert manifest["ranking_version"] == query_service.GRAPH_QUERY_RANKING_VERSION

    task_generated = runpy.run_path(str(_ROOT / "task/core/generated_graph_query_manifest.py"))
    assert task_generated["GRAPH_QUERY_MANIFEST_HASH"] == expected_hash
    assert task_generated["GRAPH_QUERY_MANIFEST"] == manifest
    assert task_generated["GRAPH_QUERY_TOOL_SCHEMA"]["input_schema"] == manifest["inputSchema"]

    npm_generated = (_ROOT / "mcp/src/generated/graphQueryManifest.ts").read_text(encoding="utf-8")
    npm_hash = re.search(r"GRAPH_QUERY_MANIFEST_HASH = '([a-f0-9]{64})'", npm_generated)
    assert npm_hash is not None
    assert npm_hash.group(1) == expected_hash
    for value in (
        manifest["contract_version"],
        manifest["response_version"],
        manifest["ranking_version"],
    ):
        assert value in npm_generated


def test_canonical_service_keeps_access_watermark_partial_and_impact_guards_connected() -> None:
    """组合层锁住既有行为测试所依赖的生产连接点，不复制子系统算法。"""
    source = inspect.getsource(query_service.GraphQueryService.query)
    for marker in (
        "get_graph_service().get_graph",
        "community_watermark_mismatch",
        "process_lane_failed",
        "no_observed_impact_not_safe",
        "anchor_stale_missing_or_excluded",
        '"partial": partial',
    ):
        assert marker in source


def test_background_process_rebinds_explicit_or_system_initiator() -> None:
    """后台重建必须保留触发用户，并对系统行为使用显式 system fallback。"""
    signature = inspect.signature(process_index.rebuild_process_index)
    assert "initiated_by_user_id" in signature.parameters

    source = inspect.getsource(process_index.rebuild_process_index)
    assert 'initiated_by_user_id or "system"' in source
    assert "bind_task_context" in source
    assert "initiated_by_user_id=user_id" in source


def test_default_repository_evidence_is_human_needed_without_fake_metrics() -> None:
    """缺真实仓、Qdrant、独立 gold、baseline/policy 时必须停在 HUMAN_NEEDED。"""
    fixture_manifest = json.loads((_FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    holdout = json.loads((_FIXTURES / "holdout.json").read_text(encoding="utf-8"))
    fixture_doc = (_FIXTURES / "README.md").read_text(encoding="utf-8")

    assert fixture_manifest["repository"].startswith("REPLACE_WITH_")
    assert fixture_manifest["annotated_at_sha"].startswith("REPLACE_WITH_")
    assert holdout["cases"] == []
    assert "最小 seed 集" in fixture_doc
    assert not _POLICY.exists(), "无真实 baseline 时不得提交占位 threshold policy"

    evidence = _benchmark_environment_preflight(
        repository_id="",
        commit_sha="",
        qdrant_url="",
        baseline_artifact="",
    )
    assert evidence["status"].upper() == "HUMAN_NEEDED"
    assert evidence["missing"] == [
        "target_repository",
        "target_commit_sha",
        "qdrant",
        "v0.22_baseline_artifact",
    ]
    assert evidence["reproduce_command"]
    assert "metrics" not in evidence


def test_policy_comparator_is_pure_and_holdout_requires_explicit_acceptance() -> None:
    """comparator 不写回 policy；holdout 只能由显式 final acceptance 开启。"""
    comparator_source = inspect.getsource(graph_bench_compare)
    for forbidden in ("write_text(", "write_bytes(", "auto_update", "write_back"):
        assert forbidden not in comparator_source

    evaluator_source = (
        _ROOT / "server/codegraph/management/commands/evaluate_graph_bench.py"
    ).read_text(encoding="utf-8")
    assert 'split == "holdout" and not options["final_acceptance"]' in evaluator_source
    assert '"opened": split == "holdout"' in evaluator_source


def test_closure_gate_contains_no_skip_or_xfail_escape_hatch() -> None:
    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    escape_calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "pytest"
        and node.func.attr in {"skip", "xfail"}
    }
    assert escape_calls == set()
