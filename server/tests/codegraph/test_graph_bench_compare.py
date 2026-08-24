"""BENCH-06/07、EDGE-06：严格 paired 四态 comparator。"""

from __future__ import annotations

import json

import pytest

from codegraph.services.graph_bench_compare import compare_graph_bench, load_threshold_policy
from tests.codegraph.test_graph_bench_policy import HEX_A, HEX_B, HEX_C, encoded, valid_policy


def _report(
    *,
    symbol_recall: float = 0.8,
    resolver_precision: float | str = 0.9,
    resolver_status: str = "OK",
    resolver_samples: int = 3,
    release: str = "v0.22",
) -> dict:
    policy = valid_policy()
    system_key = "system_identity" if release == "v0.22" else None
    system = policy["baseline"][system_key] if system_key else policy["candidate_expectation"]
    return {
        "watermark": "OK",
        "comparison_identity": policy["baseline"]["comparison_identity"],
        "system_identity": system,
        "reproducible_command": f"evaluate {release}",
        "total_cases": 3,
        "per_case": [
            {
                "case_id": case_id,
                "language": "python",
                "framework": "django",
                "entry_type": "http_endpoint",
                "symbol_recall": value,
            }
            for case_id, value in (
                ("c1", symbol_recall),
                ("c2", symbol_recall),
                ("c3", symbol_recall),
            )
        ],
        "overall": {"symbol_recall": symbol_recall},
        "per_bucket": [
            {
                "key": {
                    "language": "python",
                    "framework": "django",
                    "entry_type": "http_endpoint",
                },
                "n": 3,
                "status": "OK",
                "has_protected": False,
                "metrics": {"symbol_recall": symbol_recall},
            }
        ],
        "resolver": {
            "status": "OK",
            "cells": [
                {
                    "key": {
                        "language": "python",
                        "framework": "django",
                        "call_shape": "import_alias",
                    },
                    "required": True,
                    "gold_count": resolver_samples,
                    "status": resolver_status,
                    "precision": resolver_precision,
                    "recall": resolver_precision,
                }
            ],
        },
    }


def _raw(report: dict) -> bytes:
    return json.dumps(report, ensure_ascii=False, sort_keys=True).encode()


def _compare(
    baseline: dict | None = None,
    candidate: dict | None = None,
    *,
    policy_payload: dict | None = None,
):
    baseline = baseline or _report()
    candidate = candidate or _report(symbol_recall=0.9, release="v0.24")
    policy_payload = policy_payload or valid_policy()
    baseline_raw = _raw(baseline)
    policy_payload["baseline"]["report_sha256"] = (
        __import__("hashlib").sha256(baseline_raw).hexdigest()
    )
    policy = load_threshold_policy(encoded(policy_payload))
    return compare_graph_bench(
        baseline_report=baseline,
        candidate_report=candidate,
        policy=policy,
        baseline_sha256=policy_payload["baseline"]["report_sha256"],
        candidate_sha256=__import__("hashlib").sha256(_raw(candidate)).hexdigest(),
        baseline_manifest_sha256=HEX_C,
    )


def test_pass_requires_all_required_gates_and_strict_primary_improvement() -> None:
    result = _compare()
    assert result.verdict == "PASS"
    assert result.to_dict()["hashes"] == {
        "policy_sha256": result.policy_sha256,
        "baseline_sha256": result.baseline_sha256,
        "candidate_sha256": result.candidate_sha256,
        "baseline_manifest_sha256": HEX_C,
    }
    assert len(result.gates) == 2
    assert result.improvement_evidence
    assert len(result.per_case) == 3
    assert len(result.per_bucket) == 1
    assert len(result.resolver_cells) == 1


@pytest.mark.parametrize(
    "mutate",
    [
        lambda baseline, candidate, policy: candidate.update(watermark="INVALID"),
        lambda baseline, candidate, policy: candidate["comparison_identity"].update(branch="other"),
        lambda baseline, candidate, policy: candidate["comparison_identity"].update(
            evaluator_sha256=HEX_A
        ),
        lambda baseline, candidate, policy: candidate["comparison_identity"].update(
            case_set_sha256=HEX_B
        ),
        lambda baseline, candidate, policy: candidate["system_identity"].update(
            ranking_version="other"
        ),
        lambda baseline, candidate, policy: baseline["system_identity"].update(
            friday_revision="wrong"
        ),
        lambda baseline, candidate, policy: baseline["overall"].update(symbol_recall=0.7),
    ],
)
def test_identity_hash_evaluator_ranking_or_baseline_pin_mismatch_is_invalid(mutate) -> None:
    baseline = _report()
    candidate = _report(symbol_recall=0.9, release="v0.24")
    policy = valid_policy()
    mutate(baseline, candidate, policy)
    assert _compare(baseline, candidate, policy_payload=policy).verdict == "INVALID"


@pytest.mark.parametrize("mode", ["missing", "extra", "duplicate"])
def test_case_pairing_is_strict(mode: str) -> None:
    baseline = _report()
    candidate = _report(symbol_recall=0.9, release="v0.24")
    if mode == "missing":
        candidate["per_case"].pop()
    elif mode == "extra":
        candidate["per_case"].append({**candidate["per_case"][0], "case_id": "extra"})
    else:
        candidate["per_case"].append(dict(candidate["per_case"][0]))
    result = _compare(baseline, candidate)
    assert result.verdict == "INVALID"
    assert result.gates == []


@pytest.mark.parametrize("section", ["per_bucket", "resolver"])
def test_bucket_and_resolver_cell_pairing_is_strict(section: str) -> None:
    candidate = _report(symbol_recall=0.9, release="v0.24")
    if section == "per_bucket":
        candidate["per_bucket"] = []
    else:
        candidate["resolver"]["cells"] = []
    assert _compare(candidate=candidate).verdict == "INVALID"


@pytest.mark.parametrize(
    ("direction", "baseline_value", "candidate_value", "tolerance", "expected"),
    [
        ("higher_is_better", 0.8, 0.8, 0.0, "FAIL"),
        ("higher_is_better", 0.8, 0.79, 0.01, "FAIL"),
        ("lower_is_better", 0.2, 0.19, 0.01, "PASS"),
        ("lower_is_better", 0.2, 0.22, 0.01, "FAIL"),
    ],
)
def test_direction_aware_boundaries(
    direction: str,
    baseline_value: float,
    candidate_value: float,
    tolerance: float,
    expected: str,
) -> None:
    policy = valid_policy()
    policy["gates"] = [
        {
            "scope": {"kind": "overall"},
            "metric": "symbol_recall",
            "direction": direction,
            "baseline_value": baseline_value,
            "allowed_abs_regression": tolerance,
            "required": True,
            "protected": False,
        }
    ]
    policy["primary_quality_metrics"] = [{"scope": {"kind": "overall"}, "metric": "symbol_recall"}]
    baseline = _report(symbol_recall=baseline_value)
    candidate = _report(symbol_recall=candidate_value, release="v0.24")
    assert _compare(baseline, candidate, policy_payload=policy).verdict == expected


@pytest.mark.parametrize("marker", ["NO_GOLD", "N/A", "SEED_MISSING", "INSUFFICIENT_DATA"])
def test_required_marker_never_participates_in_arithmetic(marker: str) -> None:
    candidate = _report(
        symbol_recall=0.9,
        resolver_precision=marker,
        release="v0.24",
    )
    result = _compare(candidate=candidate)
    assert result.verdict == "FAIL"
    assert any(g.status == "FAIL" and g.candidate_value == marker for g in result.gates)


def test_required_or_protected_sparse_is_fail() -> None:
    candidate = _report(
        symbol_recall=0.9,
        resolver_status="INSUFFICIENT_DATA",
        resolver_samples=1,
        release="v0.24",
    )
    assert _compare(candidate=candidate).verdict == "FAIL"


def test_optional_sparse_is_insufficient_data() -> None:
    policy = valid_policy()
    policy["gates"][1]["required"] = False
    policy["gates"][1]["protected"] = False
    candidate = _report(
        symbol_recall=0.9,
        resolver_status="INSUFFICIENT_DATA",
        resolver_samples=1,
        release="v0.24",
    )
    assert _compare(candidate=candidate, policy_payload=policy).verdict == "INSUFFICIENT_DATA"


def test_aggregate_improvement_cannot_hide_protected_regression() -> None:
    candidate = _report(
        symbol_recall=0.9,
        resolver_precision=0.8,
        release="v0.24",
    )
    assert _compare(candidate=candidate).verdict == "FAIL"


def test_all_equal_required_metrics_do_not_prove_improvement() -> None:
    assert _compare(candidate=_report(release="v0.24")).verdict == "FAIL"


def test_invalidity_has_priority_and_suppresses_partial_gate_results() -> None:
    candidate = _report(
        symbol_recall=0.1,
        resolver_precision="INSUFFICIENT_DATA",
        release="v0.24",
    )
    candidate["comparison_identity"]["repository"] = "other"
    result = _compare(candidate=candidate)
    assert result.verdict == "INVALID"
    assert result.gates == []
