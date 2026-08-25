"""Phase 140：resolver edge-level 三态与 language × framework × call_shape cell。"""

from __future__ import annotations

from codegraph.resolver.base import ResolveResult
from codegraph.services.graph_bench_eval import (
    BUCKET_OK,
    CALL_SHAPES,
    INSUFFICIENT_DATA,
    NO_GOLD,
    NOT_APPLICABLE,
    ResolverCellKey,
    ResolverEdgeOutcome,
    aggregate_resolver_cells,
    resolver_cell_metrics,
)


def _result(
    *,
    status: str,
    language: str,
    call_shape: str,
    callee_symbol_id: str | None = None,
) -> ResolveResult:
    return ResolveResult(
        callee_symbol_id=callee_symbol_id,
        callee_file="target.py" if callee_symbol_id else None,
        is_cross_file=callee_symbol_id is not None,
        status=status,
        language=language,
        call_shape=call_shape,
    )


def _outcome(
    *,
    status: str,
    language: str = "python",
    framework: str = "django",
    call_shape: str = "direct",
    expected: str = "expected",
    predicted: str | None = None,
) -> ResolverEdgeOutcome:
    return ResolverEdgeOutcome.from_resolve_result(
        _result(
            status=status,
            language=language,
            call_shape=call_shape,
            callee_symbol_id=predicted,
        ),
        framework=framework,
        expected_callee_uid=expected,
    )


def test_canonical_taxonomy_includes_resolver_outputs() -> None:
    assert CALL_SHAPES == (
        "direct",
        "member",
        "import_alias",
        "receiver",
        "from_import",
        "re_export",
        "component",
    )


def test_edge_outcome_consumes_resolve_result_three_states_and_serializes() -> None:
    resolved = _outcome(status="resolved", predicted="expected", call_shape="re_export")
    ambiguous = _outcome(status="ambiguous", call_shape="component")
    unresolved = _outcome(status="unresolved", call_shape="from_import")

    assert resolved.correct is True
    assert ambiguous.correct is False
    assert unresolved.correct is False
    assert resolved.to_dict() == {
        "language": "python",
        "framework": "django",
        "call_shape": "re_export",
        "status": "resolved",
        "expected_callee_uid": "expected",
        "predicted_callee_uid": "expected",
        "correct": True,
    }


def test_cell_counts_precision_recall_and_stable_key() -> None:
    outcomes = [
        _outcome(status="resolved", predicted="expected"),
        _outcome(status="resolved", predicted="wrong"),
        _outcome(status="ambiguous"),
        _outcome(status="unresolved"),
    ]

    cell = resolver_cell_metrics(outcomes, gold_count=4, min_samples=3)

    assert cell == {
        "key": {
            "language": "python",
            "framework": "django",
            "call_shape": "direct",
        },
        "required": True,
        "gold_count": 4,
        "resolved_count": 2,
        "ambiguous_count": 1,
        "unresolved_count": 1,
        "correct_resolved_count": 1,
        "incorrect_resolved_count": 1,
        "precision": 0.5,
        "recall": 0.25,
        "status": BUCKET_OK,
    }


def test_denominator_mismatch_invalidates_cell_and_whole_report() -> None:
    key = ResolverCellKey("python", "django", "direct")
    outcomes = [_outcome(status="resolved", predicted="expected")]

    cell = resolver_cell_metrics(outcomes, gold_count=2)
    report = aggregate_resolver_cells(outcomes, gold_counts={key: 2})

    assert cell["status"] == "INVALID"
    assert report["status"] == "INVALID"
    assert report["invalid_cells"] == [cell]


def test_markers_are_not_coerced_to_numbers() -> None:
    no_resolved = resolver_cell_metrics(
        [_outcome(status="ambiguous"), _outcome(status="unresolved")],
        gold_count=2,
    )
    no_gold = resolver_cell_metrics(
        [],
        key=ResolverCellKey("python", "django", "direct"),
        gold_count=0,
    )

    assert no_resolved["precision"] == NOT_APPLICABLE
    assert no_resolved["recall"] == 0.0
    assert no_gold["precision"] == NOT_APPLICABLE
    assert no_gold["recall"] == NO_GOLD
    assert no_gold["status"] == INSUFFICIENT_DATA


def test_language_families_are_independent_and_go_is_report_only() -> None:
    outcomes = [
        _outcome(
            status="resolved",
            language="typescript",
            framework="vue",
            call_shape="component",
            predicted="expected",
        ),
        _outcome(
            status="resolved",
            language="javascript",
            framework="vue",
            call_shape="re_export",
            predicted="expected",
        ),
        _outcome(status="unresolved", language="python", framework="django"),
        _outcome(
            status="resolved",
            language="go",
            framework="gin",
            call_shape="receiver",
            predicted="expected",
        ),
    ]

    report = aggregate_resolver_cells(outcomes, min_samples=1)
    by_language = {cell["key"]["language"]: cell for cell in report["cells"]}

    assert by_language["typescript"]["required"] is True
    assert by_language["javascript"]["required"] is True
    assert by_language["python"]["required"] is True
    assert by_language["go"]["required"] is False
    assert [cell["key"] for cell in report["cells"]] == sorted(
        (cell["key"] for cell in report["cells"]),
        key=lambda key: (key["language"], key["framework"], key["call_shape"]),
    )
