"""initial implementation V5：12 structlog 事件名契约测试（grep + capture_logs 双重断言）。

12 事件名（per work item）：
- supervisor 层 8 个：started / status_changed / health_passed / health_failed /
  request_timeout / crashed / restart_attempt / disabled
- backend 层 4 个 fallback：extract_symbols/imports/calls/endpoints_fallback
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from structlog.testing import capture_logs

from codegraph.extractors.base import CallData, EndpointData, FileContext, ImportData, SymbolData
from codegraph.lsp.backend import LspBackend
from codegraph.lsp.exceptions import (
    LspDisabledError,
    LspError,
    LspStartupError,
    LspTimeoutError,
    LspUnhealthyError,
)
from codegraph.lsp.supervisor import LspSupervisor, LspSupervisorStatus


_EXPECTED_EVENTS = [
    "lsp_supervisor_started",
    "lsp_supervisor_status_changed",
    "lsp_health_check_passed",
    "lsp_health_check_failed",
    "lsp_request_timeout",
    "lsp_crashed",
    "lsp_restart_attempt",
    "lsp_disabled",
    "lsp_extract_symbols_fallback",
    "lsp_extract_imports_fallback",
    "lsp_extract_calls_fallback",
    "lsp_extract_endpoints_fallback",
]


def test_12_structlog_events_grep_completeness_in_source() -> None:
    """V5 字面 grep：12 事件名都在 supervisor.py / backend.py 源码内。"""
    supervisor_src = (
        Path(__file__).parent.parent / "supervisor.py"
    ).read_text(encoding="utf-8")
    backend_src = (Path(__file__).parent.parent / "backend.py").read_text(
        encoding="utf-8"
    )
    combined = supervisor_src + "\n" + backend_src

    missing = [evt for evt in _EXPECTED_EVENTS if evt not in combined]
    assert not missing, f"以下 structlog 事件名缺失: {missing}"


@pytest.mark.asyncio
async def test_supervisor_events_fire_via_lifecycle() -> None:
    """触发 supervisor 完整 lifecycle 链路：started / status_changed / restart_attempt /
    disabled / health_passed / health_failed / crashed 全部命中。
    """
    from pathlib import Path as _Path

    sup = LspSupervisor(
        name="event_test",
        command=["echo"],
        workspace_root=_Path("/tmp"),
        language_ids=["plaintext"],
        max_restart_attempts=1,  # 加速
    )

    fake_client = MagicMock()
    fake_client._server = None
    fake_proc = MagicMock()
    fake_proc.returncode = None
    fake_proc.pid = 99999
    transport = MagicMock()
    transport.get_extra_info = MagicMock(return_value=fake_proc)
    protocol = MagicMock()
    protocol.transport = transport
    fake_client.protocol = protocol
    fake_client.start = AsyncMock()
    fake_client.stop = AsyncMock()
    fake_client.request_workspace_symbol = AsyncMock(return_value=[])

    import codegraph.lsp.supervisor as mod
    from unittest.mock import patch

    with capture_logs() as cap:
        with patch.object(mod, "FridayLanguageClient", MagicMock(return_value=fake_client)):
            await sup._spawn_client()
            # 健康检查：触发 _EVENT_HEALTH_PASSED
            await sup.health_check_once()

            # 制造 ping 失败：触发 _EVENT_HEALTH_FAILED 与 _EVENT_REQUEST_TIMEOUT
            fake_client.request_workspace_symbol = AsyncMock(
                side_effect=LspTimeoutError("ping timeout")
            )
            await sup.health_check_once()

            # 制造进程崩溃：触发 _EVENT_CRASHED
            fake_proc.returncode = 137
            await sup.health_check_once()

            # 触发 restart_attempt + disabled（max=1，restart 后必然 DISABLED）
            sup._restart_attempts = 0
            await sup.restart(reason="trigger_attempt")
            # 第二次 restart 跨阈值 → DISABLED
            await sup.restart(reason="trigger_disabled")

    events = {log.get("event") for log in cap}

    # supervisor 层 8 个事件应该全触发（健康检查含 passed + failed + crashed +
    # request_timeout，lifecycle 含 started / status_changed / restart_attempt /
    # disabled）
    for expected in (
        "lsp_supervisor_started",
        "lsp_supervisor_status_changed",
        "lsp_health_check_passed",
        "lsp_health_check_failed",
        "lsp_request_timeout",
        "lsp_crashed",
        "lsp_restart_attempt",
        "lsp_disabled",
    ):
        assert expected in events, f"事件未触发: {expected}; 实际事件={events}"


class _StubFallbackBackend(LspBackend):
    name = "fallback_event_stub"
    language_ids = ["python"]
    command = []

    def _lsp_extract_symbols(
        self, tree: Any, source: str, ctx: FileContext
    ) -> list[SymbolData]:
        raise LspError("e1")

    def _lsp_extract_imports(
        self, tree: Any, ctx: FileContext
    ) -> list[ImportData]:
        raise LspTimeoutError("e2")

    def _lsp_extract_calls(self, tree: Any, ctx: FileContext) -> list[CallData]:
        raise LspUnhealthyError("e3")

    def _lsp_extract_endpoints(
        self, tree: Any, source: str, ctx: FileContext
    ) -> list[EndpointData]:
        raise LspDisabledError("e4")


def test_extract_fallback_events_actually_fire() -> None:
    """4 维 extract_* fallback 事件各触发一次，含 language / file_path / error_class。"""
    from codegraph.backends.protocols import ExtractorBackend

    sup = MagicMock(spec=LspSupervisor)
    fallback = MagicMock(spec=ExtractorBackend)
    fallback.parse_file = MagicMock(return_value="ts_tree_stub")
    fallback.extract_symbols = MagicMock(return_value=[])
    fallback.extract_imports = MagicMock(return_value=[])
    fallback.extract_calls = MagicMock(return_value=[])
    fallback.extract_endpoints = MagicMock(return_value=[])

    backend = _StubFallbackBackend(language="python", supervisor=sup, fallback=fallback)
    ctx = FileContext(file_path="x.py", language="python", repository_id="r1")

    with capture_logs() as cap:
        backend.extract_symbols(tree=None, source="src", ctx=ctx)
        backend.extract_imports(tree=None, ctx=ctx)
        backend.extract_calls(tree=None, ctx=ctx)
        backend.extract_endpoints(tree=None, source="src", ctx=ctx)

    for expected in (
        "lsp_extract_symbols_fallback",
        "lsp_extract_imports_fallback",
        "lsp_extract_calls_fallback",
        "lsp_extract_endpoints_fallback",
    ):
        matched = [log for log in cap if log.get("event") == expected]
        assert matched, f"事件未触发: {expected}"
        assert "language" in matched[0]
        assert "file_path" in matched[0]
        assert "error_class" in matched[0]


# 也显式列举常量字面，作 grep gate 入口
_EVENT_PREFIX = "_EVENT_"
