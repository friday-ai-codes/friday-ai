"""``services/code_graph/impact_report`` formatter / stub / 观测用例（DIFF-04）。

归属 Plan 124-02：mock ``run_detect_changes`` 边界，不重测 diff/BFS。
覆盖 D-05/D-07/D-08/D-09/D-10/D-11/D-12/D-15 与 T-124-02/03/04/05。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest
from structlog.testing import capture_logs

from services.code_graph.model import GraphAccessDenied


def _repo(*, repo_id: str = "11111111-1111-1111-1111-111111111111") -> SimpleNamespace:
    return SimpleNamespace(id=repo_id)


def _user(*, user_id: int = 42) -> SimpleNamespace:
    return SimpleNamespace(id=user_id)


def _ok_envelope(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "ok": True,
        "tool": "detect_changes",
        "repository_id": "11111111-1111-1111-1111-111111111111",
        "diff_base_sha": "a" * 40,
        "diff_head_sha": "b" * 40,
        "files": [
            {
                "path": "src/svc.py",
                "file_summary": {"changeType": "modified"},
                "symbols": [
                    {
                        "uid": "uid-1",
                        "name": "handle",
                        "changeType": "modified",
                        "lines_changed": 3,
                        "file_line": "src/svc.py:10",
                        "impact_seed": True,
                    }
                ],
            }
        ],
        "impacts": [
            {
                "uid": "uid-1",
                "impact": {
                    "risk_level": "high",
                    "groups": [
                        {
                            "depth": 1,
                            "items": [
                                {"name": "caller_a", "file_path": "src/a.py"},
                                {"name": "caller_b", "file_path": "src/b.py"},
                            ],
                        }
                    ],
                    "summary": {
                        "total_found": 2,
                        "returned": 2,
                        "truncated_by_depth": False,
                        "truncated_by_nodes": False,
                    },
                },
            }
        ],
        "summary": {
            "affected_symbol_count": 1,
            "impact_seed_count": 1,
            "truncated": False,
            "not_expanded": False,
            "file_count": 1,
            "file_level_only": False,
        },
        "affected_processes": [],
        "staleness": {
            "as_of": "a" * 40,
            "behind_commits": 0,
            "declaration": "索引水位与 last_indexed_commit_sha 对齐",
        },
        "graph": {"degraded": False},
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_build_impact_report_four_sections() -> None:
    """fixture 信封 → ``## 影响面`` + Changes/Affected/Risk/Recommendations 四段（D-07）。"""
    from services.code_graph.impact_report import IMPACT_SECTION_MARKER, build_impact_report_section

    envelope = _ok_envelope()
    with mock.patch(
        "services.code_graph.impact_report.run_detect_changes",
        new=mock.AsyncMock(return_value=envelope),
    ):
        section = await build_impact_report_section(
            repository=_repo(),
            user=_user(),
            compare="feature/x",
            base_ref="main",
        )

    assert IMPACT_SECTION_MARKER in section
    assert "### Changes" in section
    assert "### Affected" in section
    assert "### Risk" in section
    assert "### Recommendations" in section
    assert "src/svc.py" in section
    assert "HIGH" in section


@pytest.mark.asyncio
async def test_ok_false_yields_stub_error_code() -> None:
    """``ok=False`` → 短 stub 含稳定 ``error_code``，不抛（D-11）。"""
    from services.code_graph.impact_report import build_impact_report_section

    envelope = {
        "ok": False,
        "error_code": "repository_not_indexed",
        "error": "仓库尚未建立索引",
        "tool": "detect_changes",
        "repository_id": "11111111-1111-1111-1111-111111111111",
    }
    with mock.patch(
        "services.code_graph.impact_report.run_detect_changes",
        new=mock.AsyncMock(return_value=envelope),
    ):
        section = await build_impact_report_section(
            repository=_repo(),
            user=_user(),
            compare="feature/x",
        )

    assert "## 影响面" in section
    assert "`not_indexed`" in section
    assert "### Changes" not in section
    assert "Traceback" not in section


@pytest.mark.asyncio
async def test_timeout_yields_stub_timeout() -> None:
    """超时 → stub ``timeout``；不向上抛（D-10 / T-124-04）。"""
    from services.code_graph.impact_report import build_impact_report_section

    async def _slow(*_a: Any, **_k: Any) -> dict[str, Any]:
        await asyncio.sleep(3600)
        return _ok_envelope()

    with (
        mock.patch(
            "services.code_graph.impact_report.run_detect_changes",
            new=_slow,
        ),
        mock.patch(
            "services.code_graph.impact_report.settings.CODE_GRAPH_IMPACT_REPORT_TIMEOUT_SECONDS",
            0.01,
        ),
    ):
        section = await build_impact_report_section(
            repository=_repo(),
            user=_user(),
            compare="feature/x",
        )

    assert "`timeout`" in section
    assert "### Changes" not in section


@pytest.mark.asyncio
async def test_graph_access_denied_yields_stub_unavailable() -> None:
    """ACL / GraphAccessDenied → stub ``unavailable``，禁止空成功四段（T-124-05）。"""
    from services.code_graph.impact_report import build_impact_report_section

    with mock.patch(
        "services.code_graph.impact_report.run_detect_changes",
        new=mock.AsyncMock(side_effect=GraphAccessDenied("denied")),
    ):
        section = await build_impact_report_section(
            repository=_repo(),
            user=_user(),
            compare="feature/x",
        )

    assert "`unavailable`" in section
    assert "### Changes" not in section
    assert "### Risk" not in section


@pytest.mark.asyncio
async def test_partial_success_still_four_sections() -> None:
    """``ok=True`` + staleness/degradation 仍渲染完整四段（D-12）。"""
    from services.code_graph.impact_report import build_impact_report_section

    envelope = _ok_envelope(
        staleness={
            "as_of": "a" * 40,
            "behind_commits": 25,
            "declaration": "索引明显落后（25 commits）",
        },
        graph={"degraded": True},
        impacts=[
            {
                "uid": "uid-1",
                "impact_error": {"error_code": "symbol_not_found", "error": "missing"},
            }
        ],
    )
    with mock.patch(
        "services.code_graph.impact_report.run_detect_changes",
        new=mock.AsyncMock(return_value=envelope),
    ):
        section = await build_impact_report_section(
            repository=_repo(),
            user=_user(),
            compare="feature/x",
        )

    assert "### Changes" in section
    assert "### Affected" in section
    assert "### Risk" in section
    assert "### Recommendations" in section
    assert "降级" in section or "stale" in section.lower() or "落后" in section


@pytest.mark.asyncio
async def test_max_chars_truncation_note() -> None:
    """超软上限截断并注明 truncated（D-08）。"""
    from services.code_graph.impact_report import build_impact_report_section

    files = [
        {
            "path": f"src/file_{i}.py",
            "file_summary": {"changeType": "modified"},
            "symbols": [
                {
                    "uid": f"uid-{i}-{j}",
                    "name": f"fn_{i}_{j}",
                    "changeType": "modified",
                    "lines_changed": 2,
                    "file_line": f"src/file_{i}.py:{j}",
                    "impact_seed": True,
                }
                for j in range(8)
            ],
        }
        for i in range(20)
    ]
    impacts = [
        {
            "uid": f"uid-{i}-0",
            "impact": {
                "risk_level": "medium",
                "groups": [
                    {
                        "depth": 1,
                        "items": [
                            {"name": f"caller_{i}_{k}", "file_path": f"src/c_{i}_{k}.py"}
                            for k in range(12)
                        ],
                    }
                ],
                "summary": {"total_found": 12, "returned": 12},
            },
        }
        for i in range(15)
    ]
    envelope = _ok_envelope(files=files, impacts=impacts)
    with (
        mock.patch(
            "services.code_graph.impact_report.run_detect_changes",
            new=mock.AsyncMock(return_value=envelope),
        ),
        mock.patch(
            "services.code_graph.impact_report.settings.CODE_GRAPH_IMPACT_REPORT_MAX_CHARS",
            800,
        ),
    ):
        section = await build_impact_report_section(
            repository=_repo(),
            user=_user(),
            compare="feature/x",
        )

    assert "truncated" in section.lower()
    assert len(section) <= 800 + 64  # soft bound with truncation note room


@pytest.mark.asyncio
async def test_no_source_body_in_section() -> None:
    """段内无源码正文（T-124-03 / D-08）。"""
    from services.code_graph.impact_report import build_impact_report_section

    secret_body = "def secret_impl():\n    return 'SOURCE_BODY_MARKER_XYZ'\n"
    envelope = _ok_envelope(
        files=[
            {
                "path": "src/svc.py",
                "file_summary": {"changeType": "modified"},
                "content": secret_body,
                "symbols": [
                    {
                        "uid": "uid-1",
                        "name": "handle",
                        "changeType": "modified",
                        "lines_changed": 3,
                        "file_line": "src/svc.py:10",
                        "content": secret_body,
                        "impact_seed": True,
                    }
                ],
            }
        ]
    )
    with mock.patch(
        "services.code_graph.impact_report.run_detect_changes",
        new=mock.AsyncMock(return_value=envelope),
    ):
        section = await build_impact_report_section(
            repository=_repo(),
            user=_user(),
            compare="feature/x",
        )

    assert "SOURCE_BODY_MARKER_XYZ" not in section
    assert "def secret_impl" not in section
    assert "```" not in section


def test_append_impact_report_idempotent() -> None:
    """已含影响面标记头则不重复 append。"""
    from services.code_graph.impact_report import append_impact_report

    section = "## 影响面\n\n_stub_"
    base = "hello\n\n## 影响面\n\nold"
    assert append_impact_report(base, section) == base
    assert append_impact_report("", section) == section
    assert append_impact_report("desc", "") == "desc"
    out = append_impact_report("desc", section)
    assert out.startswith("desc")
    assert out.count("## 影响面") == 1


@pytest.mark.asyncio
async def test_stub_omits_stack_and_secrets() -> None:
    """stub/日志无堆栈、token、绝对路径、凭证（T-124-02）。"""
    from services.code_graph.impact_report import build_impact_report_section

    secret = "sk-live-ABCDEFG1234567890"
    abs_path = "/Users/zaneliu/Projects/secret/repo/src/a.py"
    with capture_logs() as events:
        with mock.patch(
            "services.code_graph.impact_report.run_detect_changes",
            new=mock.AsyncMock(
                side_effect=RuntimeError(
                    f"boom token={secret} path={abs_path}\nTraceback (most recent call last):\n  File ..."
                )
            ),
        ):
            section = await build_impact_report_section(
                repository=_repo(),
                user=_user(),
                compare="feature/x",
            )

    assert "`unavailable`" in section
    assert secret not in section
    assert abs_path not in section
    assert "Traceback" not in section
    blob = " ".join(str(e) for e in events)
    assert secret not in blob
    assert "Traceback" not in blob


@pytest.mark.asyncio
async def test_observability_events_static_names() -> None:
    """started/completed/failed 静态字面量；``initiated_by_user_id`` 有 user→str(id) / 无→system（D-15）。"""
    from services.code_graph.impact_report import build_impact_report_section

    with capture_logs() as events:
        with mock.patch(
            "services.code_graph.impact_report.run_detect_changes",
            new=mock.AsyncMock(return_value=_ok_envelope()),
        ):
            await build_impact_report_section(
                repository=_repo(),
                user=_user(user_id=7),
                compare="feature/x",
            )

    names = {e["event"] for e in events}
    assert "impact_report_started" in names
    assert "impact_report_completed" in names
    started = next(e for e in events if e["event"] == "impact_report_started")
    completed = next(e for e in events if e["event"] == "impact_report_completed")
    assert started["component"] == "code_graph"
    assert started["category"] == "caller"
    assert started["initiated_by_user_id"] == "7"
    assert completed["initiated_by_user_id"] == "7"
    assert "duration_ms" in completed
    assert "section_chars" in completed

    with capture_logs() as events_none:
        section = await build_impact_report_section(
            repository=_repo(),
            user=None,
            compare="feature/x",
        )
    assert "`user_missing`" in section
    none_events = [e for e in events_none if e["event"].startswith("impact_report_")]
    assert none_events
    for e in none_events:
        assert e.get("initiated_by_user_id") == "system"
    assert any(e["event"] == "impact_report_started" for e in none_events)
    assert any(e["event"] == "impact_report_failed" for e in none_events)
    failed = next(e for e in none_events if e["event"] == "impact_report_failed")
    assert failed.get("error_code") == "user_missing"
