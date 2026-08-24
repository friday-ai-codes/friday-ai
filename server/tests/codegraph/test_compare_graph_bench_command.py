"""BENCH-07：``compare_graph_bench`` 只读 I/O、审计报告与退出语义。"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from structlog.testing import capture_logs

from tests.codegraph.test_graph_bench_compare import _report
from tests.codegraph.test_graph_bench_policy import encoded, valid_policy


def _write_inputs(
    root: Path,
    *,
    candidate: dict | None = None,
    policy_mutator=None,
) -> tuple[Path, Path, Path, dict[str, bytes]]:
    baseline = _report()
    candidate = candidate or _report(symbol_recall=0.9, release="v0.24")
    baseline_raw = json.dumps(baseline, ensure_ascii=False, sort_keys=True).encode()
    candidate_raw = json.dumps(candidate, ensure_ascii=False, sort_keys=True).encode()
    policy = valid_policy()
    policy["baseline"]["report_sha256"] = hashlib.sha256(baseline_raw).hexdigest()
    if policy_mutator is not None:
        policy_mutator(policy)
    policy_raw = encoded(policy)

    paths = (
        root / "baseline.json",
        root / "candidate.json",
        root / "policy.json",
    )
    raws = (baseline_raw, candidate_raw, policy_raw)
    for path, raw in zip(paths, raws, strict=True):
        path.write_bytes(raw)
    return (*paths, {str(path): raw for path, raw in zip(paths, raws, strict=True)})


def _assert_unchanged(before: dict[str, bytes]) -> None:
    assert {path: Path(path).read_bytes() for path in before} == before


def test_pass_writes_complete_report_and_preserves_inputs(tmp_path: Path) -> None:
    baseline, candidate, policy, before = _write_inputs(tmp_path)
    output = tmp_path / "compare.json"

    call_command(
        "compare_graph_bench",
        baseline=str(baseline),
        candidate=str(candidate),
        policy=str(policy),
        output=str(output),
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["verdict"] == "PASS"
    assert set(payload["hashes"]) == {
        "policy_sha256",
        "baseline_sha256",
        "candidate_sha256",
        "baseline_manifest_sha256",
    }
    assert payload["comparison_identity"]["split"] == "locked_test"
    assert payload["baseline_system_identity"]["release_label"] == "v0.22"
    assert payload["candidate_system_identity"]["release_label"] == "v0.24"
    assert payload["reproducible_commands"]["baseline"]
    assert payload["reproducible_commands"]["candidate"]
    assert payload["reproducible_command"].startswith(
        "python manage.py compare_graph_bench"
    )
    assert payload["per_case"]
    assert payload["per_bucket"]
    assert payload["resolver_cells"]
    _assert_unchanged(before)


@pytest.mark.parametrize("expected", ["INVALID", "FAIL", "INSUFFICIENT_DATA"])
def test_non_pass_verdict_writes_report_then_exits_nonzero(
    tmp_path: Path,
    expected: str,
) -> None:
    candidate = _report(symbol_recall=0.9, release="v0.24")
    mutator = None
    if expected == "INVALID":
        candidate["comparison_identity"]["branch"] = "other"
    elif expected == "FAIL":
        candidate = _report(symbol_recall=0.8, release="v0.24")
    else:
        candidate["resolver"]["cells"][0].update(
            status="INSUFFICIENT_DATA",
            gold_count=1,
            precision="INSUFFICIENT_DATA",
        )

        def mutator(policy: dict) -> None:
            policy["gates"][1]["required"] = False
            policy["gates"][1]["protected"] = False

    baseline, candidate_path, policy, before = _write_inputs(
        tmp_path,
        candidate=candidate,
        policy_mutator=mutator,
    )
    output = tmp_path / "compare.json"

    with pytest.raises(CommandError, match=expected):
        call_command(
            "compare_graph_bench",
            baseline=str(baseline),
            candidate=str(candidate_path),
            policy=str(policy),
            output=str(output),
        )

    assert json.loads(output.read_text(encoding="utf-8"))["verdict"] == expected
    _assert_unchanged(before)


def test_raw_hash_mismatch_is_invalid_and_inputs_stay_unchanged(tmp_path: Path) -> None:
    baseline, candidate, policy, before = _write_inputs(
        tmp_path,
        policy_mutator=lambda payload: payload["baseline"].update(
            report_sha256="f" * 64
        ),
    )
    output = tmp_path / "compare.json"
    with pytest.raises(CommandError, match="INVALID"):
        call_command(
            "compare_graph_bench",
            baseline=str(baseline),
            candidate=str(candidate),
            policy=str(policy),
            output=str(output),
        )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert any("raw-byte hash" in reason for reason in payload["invalid_reasons"])
    _assert_unchanged(before)


def test_lifecycle_logs_have_required_fields_and_no_artifact_body(tmp_path: Path) -> None:
    baseline, candidate, policy, _before = _write_inputs(tmp_path)
    output = tmp_path / "compare.json"
    with capture_logs() as logs:
        call_command(
            "compare_graph_bench",
            baseline=str(baseline),
            candidate=str(candidate),
            policy=str(policy),
            output=str(output),
        )

    assert [event["event"] for event in logs] == [
        "graph_bench_compare_started",
        "graph_bench_compare_completed",
    ]
    for event in logs:
        assert event["category"] == "caller"
        assert event["component"] == "codegraph"
        assert event["initiated_by_user_id"] == "system"
        assert "baseline" not in event
        assert "candidate" not in event
        assert "policy" not in event
    assert logs[-1]["duration_ms"] >= 0
    assert "per_case" not in json.dumps(logs)


def test_logger_failure_does_not_change_pass_verdict(tmp_path: Path) -> None:
    baseline, candidate, policy, before = _write_inputs(tmp_path)
    output = tmp_path / "compare.json"
    broken = MagicMock()
    broken.info.side_effect = RuntimeError("Bearer " + "x" * 30)
    broken.error.side_effect = RuntimeError("Bearer " + "x" * 30)

    with patch(
        "codegraph.management.commands.compare_graph_bench.logger",
        broken,
    ):
        call_command(
            "compare_graph_bench",
            baseline=str(baseline),
            candidate=str(candidate),
            policy=str(policy),
            output=str(output),
        )
    assert json.loads(output.read_text(encoding="utf-8"))["verdict"] == "PASS"
    _assert_unchanged(before)


def test_command_has_no_update_accept_or_writeback_surface() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "codegraph"
        / "management"
        / "commands"
        / "compare_graph_bench.py"
    ).read_text(encoding="utf-8")
    forbidden = ("--update", "snapshot", "accept", "write-back", "write_back")
    assert all(token not in source for token in forbidden)
