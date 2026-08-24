"""BENCH-06：threshold policy schema、内容寻址与只读纪律。"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from codegraph.services.graph_bench_compare import (
    POLICY_SCHEMA_VERSION,
    load_threshold_policy,
    sha256_bytes,
)

HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64


def valid_policy() -> dict:
    comparison_identity = {
        "repository": "repo",
        "branch": "main",
        "commit_sha": "target-sha",
        "index_key_source": "last_indexed_commit_sha",
        "gold_version": "2",
        "split": "locked_test",
        "case_set_sha256": HEX_A,
        "evaluator_version": "graph-bench-evaluator/v2",
        "evaluator_sha256": HEX_B,
        "min_bucket_samples": 3,
    }
    baseline_system = {
        "release_label": "v0.22",
        "friday_revision": "baseline-revision",
        "ranking_version": "legacy-v1",
        "response_version": "graph-query/v0",
        "manifest_hash": HEX_C,
        "index_generation": "baseline-generation",
        "index_signature": "baseline-signature",
    }
    candidate_system = {
        "release_label": "v0.24",
        "friday_revision": "candidate-revision",
        "ranking_version": "rrf-v1",
        "response_version": "graph-query/v1",
        "manifest_hash": HEX_C,
        "index_generation": "candidate-generation",
        "index_signature": "candidate-signature",
    }
    overall_scope = {"kind": "overall"}
    return {
        "schema_version": POLICY_SCHEMA_VERSION,
        "policy_version": "1",
        "status": "locked",
        "baseline": {
            "report_sha256": HEX_A,
            "manifest_sha256": HEX_C,
            "comparison_identity": comparison_identity,
            "system_identity": baseline_system,
        },
        "candidate_expectation": candidate_system,
        "insufficient_data": {
            "min_samples": 3,
            "required_bucket_missing": "FAIL",
            "optional_bucket_sparse": "INSUFFICIENT_DATA",
        },
        "primary_quality_metrics": [
            {"scope": overall_scope, "metric": "symbol_recall"},
        ],
        "gates": [
            {
                "scope": overall_scope,
                "metric": "symbol_recall",
                "direction": "higher_is_better",
                "baseline_value": 0.8,
                "allowed_abs_regression": 0.0,
                "required": True,
                "protected": False,
            },
            {
                "scope": {
                    "kind": "resolver",
                    "language": "python",
                    "framework": "django",
                    "call_shape": "import_alias",
                },
                "metric": "precision",
                "direction": "higher_is_better",
                "baseline_value": 0.9,
                "allowed_abs_regression": 0.0,
                "required": True,
                "protected": True,
            },
        ],
    }


def encoded(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode()


def test_valid_policy_loads_and_hashes_raw_bytes() -> None:
    raw = encoded(valid_policy())
    loaded = load_threshold_policy(raw)
    assert loaded.schema_version == POLICY_SCHEMA_VERSION
    assert loaded.policy_sha256 == sha256_bytes(raw)
    assert len(loaded.gates) == 2


@pytest.mark.parametrize(
    "path",
    [
        ("schema_version",),
        ("policy_version",),
        ("status",),
        ("baseline", "report_sha256"),
        ("baseline", "manifest_sha256"),
        ("baseline", "comparison_identity"),
        ("baseline", "system_identity"),
        ("candidate_expectation",),
        ("insufficient_data", "min_samples"),
        ("insufficient_data", "required_bucket_missing"),
        ("insufficient_data", "optional_bucket_sparse"),
        ("primary_quality_metrics",),
        ("gates",),
    ],
)
def test_missing_required_field_fails_closed(path: tuple[str, ...]) -> None:
    payload = valid_policy()
    target = payload
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]
    with pytest.raises(ValueError, match="缺少|必填"):
        load_threshold_policy(encoded(payload))


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schema_version",), "graph-bench-threshold-policy/v999"),
        (("status",), "draft"),
        (("gates", 0, "direction"), "sideways"),
        (("insufficient_data", "required_bucket_missing"), "PASS"),
        (("insufficient_data", "optional_bucket_sparse"), "PASS"),
    ],
)
def test_unknown_closed_set_value_fails_closed(path: tuple[object, ...], value: object) -> None:
    payload = valid_policy()
    target: object = payload
    for key in path[:-1]:
        target = target[key]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]
    with pytest.raises(ValueError, match="闭集|必须"):
        load_threshold_policy(encoded(payload))


@pytest.mark.parametrize("bad_hash", ["", "abc", "g" * 64, "REPLACE_WITH_BASELINE"])
def test_invalid_or_placeholder_hash_fails_closed(bad_hash: str) -> None:
    payload = valid_policy()
    payload["baseline"]["report_sha256"] = bad_hash
    with pytest.raises(ValueError, match="SHA-256|占位"):
        load_threshold_policy(encoded(payload))


@pytest.mark.parametrize(
    "field",
    [
        "scope",
        "metric",
        "direction",
        "baseline_value",
        "allowed_abs_regression",
        "required",
        "protected",
    ],
)
def test_gate_has_no_implicit_defaults(field: str) -> None:
    payload = valid_policy()
    del payload["gates"][0][field]
    with pytest.raises(ValueError, match=field):
        load_threshold_policy(encoded(payload))


@pytest.mark.parametrize("value", ["N/A", "NO_GOLD", "SEED_MISSING", "INSUFFICIENT_DATA", True])
def test_marker_or_boolean_cannot_masquerade_as_baseline_number(value: object) -> None:
    payload = valid_policy()
    payload["gates"][0]["baseline_value"] = value
    with pytest.raises(ValueError, match="baseline_value"):
        load_threshold_policy(encoded(payload))


def test_duplicate_scope_and_metric_fails_closed() -> None:
    payload = valid_policy()
    payload["gates"].append(copy.deepcopy(payload["gates"][0]))
    with pytest.raises(ValueError, match="重复"):
        load_threshold_policy(encoded(payload))


def test_primary_metric_must_reference_a_declared_required_gate() -> None:
    payload = valid_policy()
    payload["primary_quality_metrics"][0]["metric"] = "process_recall"
    with pytest.raises(ValueError, match="primary"):
        load_threshold_policy(encoded(payload))


def test_no_formal_policy_exists_without_real_baseline() -> None:
    policy_path = (
        Path(__file__).resolve().parents[2]
        / "codegraph"
        / "benchmark_policies"
        / "graph_query_threshold_policy.v1.json"
    )
    assert not policy_path.exists()


def test_loader_does_not_mutate_caller_payload() -> None:
    payload = valid_policy()
    before = copy.deepcopy(payload)
    load_threshold_policy(encoded(payload))
    assert payload == before
