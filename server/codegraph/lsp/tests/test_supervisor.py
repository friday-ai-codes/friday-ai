"""LspSupervisor 单元测试。

覆盖：枚举与初始字段 / lifecycle / crash-loop 防护 / 健康检查 /
同步桥接 / stub did_* API / structlog 事件契约。

测试策略（per work item / Pitfall P6 / P10 / P12）：
- mock 内部 _spawn_client / FridayLanguageClient / 内部 subprocess；
- wait_until helper 避免裸 sleep；
- monkeypatch settings 加速 health check interval / timeout；
- structlog.testing.capture_logs 验证事件名 + 关键字段。
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from structlog.testing import capture_logs

import codegraph.lsp.supervisor as supervisor_mod
from codegraph.lsp.exceptions import (
    LspDisabledError,
    LspStartupError,
    LspTimeoutError,
    LspUnhealthyError,
)
from codegraph.lsp.supervisor import (
    LspSupervisor,
    LspSupervisorStatus,
    _EVENT_CRASHED,
    _EVENT_DISABLED,
    _EVENT_HEALTH_FAILED,
    _EVENT_HEALTH_PASSED,
    _EVENT_RESTART_ATTEMPT,
    _EVENT_STATUS_CHANGED,
    _EVENT_SUPERVISOR_STARTED,
)


# =============================================================================
# 局部 wait_until helper（per Pitfall P6；conftest 在 plan 落地，本 plan 内嵌）
# =============================================================================


async def wait_until(
    predicate: object,
    *,
    timeout: float = 2.0,
    interval: float = 0.02,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():  # type: ignore[operator]
            return True
        await asyncio.sleep(interval)
    return predicate()  # type: ignore[operator]


# =============================================================================
# fixtures
# =============================================================================


@pytest.fixture
def fast_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """加速健康检查 / 重启 / 超时（per Pitfall P10）。"""
    from django.conf import settings as dj_settings

    monkeypatch.setattr(dj_settings, "LSP_HEALTH_CHECK_INTERVAL_SECONDS", 0.05, raising=False)
    monkeypatch.setattr(dj_settings, "LSP_HEALTH_CHECK_TIMEOUT_SECONDS", 0.2, raising=False)
    monkeypatch.setattr(dj_settings, "LSP_REQUEST_TIMEOUT_SECONDS", 1.0, raising=False)
    monkeypatch.setattr(dj_settings, "LSP_STARTUP_TIMEOUT_SECONDS", 2.0, raising=False)


@pytest.fixture
def supervisor(fast_settings: None) -> LspSupervisor:
    return LspSupervisor(
        name="stub",
        command=["echo", "stub"],
        workspace_root=Path("/tmp"),
        language_ids=["plaintext"],
    )


# =============================================================================
# 【枚举与初始字段】
# =============================================================================


def test_lsp_supervisor_status_has_8_values() -> None:
    """8 个状态 value 字面对齐 work item。"""
    assert len(LspSupervisorStatus) == 8
    values = {s.value for s in LspSupervisorStatus}
    assert values == {
        "STARTING",
        "READY",
        "UNHEALTHY",
        "RESTARTING",
        "CRASHED",
        "DISABLED",
        "STOPPING",
        "STOPPED",
    }


def test_lsp_supervisor_initial_state(supervisor: LspSupervisor) -> None:
    """构造完成后初始字段值正确。"""
    assert supervisor._status == LspSupervisorStatus.STOPPED
    assert supervisor._restart_attempts == 0
    assert supervisor._consecutive_unhealthy_checks == 0
    assert supervisor._open_documents == {}
    assert supervisor._client is None


# =============================================================================
# 【ensure_started lifecycle】
# =============================================================================


@pytest.mark.asyncio
async def test_ensure_started_from_stopped_calls_spawn(
    supervisor: LspSupervisor,
) -> None:
    """初始 STOPPED 触发 _spawn_client。"""
    spawn = AsyncMock()
    supervisor._spawn_client = spawn  # type: ignore[method-assign]
    await supervisor.ensure_started()
    assert spawn.await_count == 1


@pytest.mark.asyncio
async def test_ensure_started_from_ready_returns_immediately(
    supervisor: LspSupervisor,
) -> None:
    """已 READY 早返；_spawn_client 不调用。"""
    supervisor._status = LspSupervisorStatus.READY
    spawn = AsyncMock()
    supervisor._spawn_client = spawn  # type: ignore[method-assign]
    await supervisor.ensure_started()
    assert spawn.await_count == 0


@pytest.mark.asyncio
async def test_ensure_started_from_disabled_raises_lsp_disabled_error(
    supervisor: LspSupervisor,
) -> None:
    """DISABLED 触发 LspDisabledError 含 reset_disabled 字面。"""
    supervisor._status = LspSupervisorStatus.DISABLED
    with pytest.raises(LspDisabledError, match="reset_disabled"):
        await supervisor.ensure_started()


@pytest.mark.asyncio
async def test_ensure_started_concurrent_calls_only_spawn_once(
    supervisor: LspSupervisor,
) -> None:
    """5 并发 ensure_started；spawn 只调一次（lock 守门）。"""
    call_count = 0
    started_event = asyncio.Event()

    async def fake_spawn() -> None:
        nonlocal call_count
        call_count += 1
        supervisor._status = LspSupervisorStatus.STARTING
        await asyncio.sleep(0.05)
        supervisor._status = LspSupervisorStatus.READY
        started_event.set()

    supervisor._spawn_client = fake_spawn  # type: ignore[method-assign]

    # 启动 5 个并发；首个 ensure_started 触发 spawn 期间其余进 STARTING 路径
    # 走 _wait_until_ready_or_failed 不再 spawn
    await asyncio.gather(*(supervisor.ensure_started() for _ in range(5)))
    assert call_count == 1


# =============================================================================
# 【crash-loop 防护 V3 / security mitigation】
# =============================================================================


@pytest.mark.asyncio
async def test_restart_increments_attempts(supervisor: LspSupervisor) -> None:
    """单次 restart 后 _restart_attempts == 1。"""
    supervisor._spawn_client = AsyncMock()  # type: ignore[method-assign]
    supervisor._stop_client_silently = AsyncMock()  # type: ignore[method-assign]
    await supervisor.restart(reason="test")
    assert supervisor._restart_attempts == 1


@pytest.mark.asyncio
async def test_restart_at_max_attempts_transitions_to_disabled(
    supervisor: LspSupervisor,
) -> None:
    """已达 max 后下次 restart 转 DISABLED 并触发 _EVENT_DISABLED。"""
    supervisor._restart_attempts = supervisor.max_restart_attempts  # 设至阈值
    supervisor._spawn_client = AsyncMock()  # type: ignore[method-assign]
    supervisor._stop_client_silently = AsyncMock()  # type: ignore[method-assign]

    with capture_logs() as cap:
        await supervisor.restart(reason="boundary_attempt")

    assert supervisor._status == LspSupervisorStatus.DISABLED
    assert any(log.get("event") == _EVENT_DISABLED for log in cap)


@pytest.mark.asyncio
async def test_supervisor_disabled_after_consecutive_spawn_failures(
    supervisor: LspSupervisor,
) -> None:
    """连续 spawn 失败 4 次（含递归路径）后转 DISABLED；后续 ensure_started raise LspDisabledError。"""

    async def fail_spawn() -> None:
        raise LspStartupError("simulated startup failure")

    supervisor._spawn_client = fail_spawn  # type: ignore[method-assign]
    supervisor._stop_client_silently = AsyncMock()  # type: ignore[method-assign]
    supervisor._replay_open_documents = AsyncMock()  # type: ignore[method-assign]

    await supervisor.restart(reason="first")
    # restart 内自动递归直到 DISABLED
    assert supervisor._status == LspSupervisorStatus.DISABLED
    assert supervisor._restart_attempts > supervisor.max_restart_attempts

    with pytest.raises(LspDisabledError):
        await supervisor.ensure_started()


# =============================================================================
# 【健康检查 V4】
# =============================================================================


@pytest.mark.asyncio
async def test_health_check_returns_false_when_proc_dead(
    supervisor: LspSupervisor,
) -> None:
    """proc.returncode 非 None → False + 转 CRASHED + _EVENT_CRASHED 触发。"""
    client = MagicMock()
    client._server = None  # 强制走 transport 分支
    fake_proc = MagicMock()
    fake_proc.returncode = 1
    transport = MagicMock()
    transport.get_extra_info = MagicMock(return_value=fake_proc)
    protocol = MagicMock()
    protocol.transport = transport
    client.protocol = protocol
    supervisor._client = client
    supervisor._status = LspSupervisorStatus.READY

    with capture_logs() as cap:
        healthy = await supervisor.health_check_once()

    assert healthy is False
    assert supervisor._status == LspSupervisorStatus.CRASHED
    assert any(log.get("event") == _EVENT_CRASHED for log in cap)


@pytest.mark.asyncio
async def test_health_check_returns_true_on_successful_ping(
    supervisor: LspSupervisor,
) -> None:
    """proc 活 + ping 成功 → True + _EVENT_HEALTH_PASSED 触发含 elapsed_ms。"""
    client = MagicMock()
    client._server = None  # 强制走 transport 分支
    fake_proc = MagicMock()
    fake_proc.returncode = None
    transport = MagicMock()
    transport.get_extra_info = MagicMock(return_value=fake_proc)
    protocol = MagicMock()
    protocol.transport = transport
    client.protocol = protocol
    client.request_workspace_symbol = AsyncMock(return_value=[])
    supervisor._client = client
    supervisor._status = LspSupervisorStatus.READY

    # capture_logs 不捕获 debug 级别（默认）；为简化，用临时 patch logger.debug 验证
    with capture_logs() as cap:
        structlog.contextvars.clear_contextvars()
        # 切到 info level 让 _EVENT_HEALTH_PASSED debug 可被 capture_logs 拦
        healthy = await supervisor.health_check_once()

    assert healthy is True
    # capture_logs 拦截全级别（debug 含），有 elapsed_ms 字段
    health_logs = [log for log in cap if log.get("event") == _EVENT_HEALTH_PASSED]
    assert health_logs
    assert "elapsed_ms" in health_logs[0]


@pytest.mark.asyncio
async def test_health_check_failure_logged(supervisor: LspSupervisor) -> None:
    """ping 失败 → False + _EVENT_HEALTH_FAILED 触发含 error_class。"""
    client = MagicMock()
    client._server = None  # 强制走 transport 分支
    fake_proc = MagicMock()
    fake_proc.returncode = None
    transport = MagicMock()
    transport.get_extra_info = MagicMock(return_value=fake_proc)
    protocol = MagicMock()
    protocol.transport = transport
    client.protocol = protocol
    client.request_workspace_symbol = AsyncMock(
        side_effect=LspTimeoutError("ping timeout 5s")
    )
    supervisor._client = client
    supervisor._status = LspSupervisorStatus.READY

    with capture_logs() as cap:
        healthy = await supervisor.health_check_once()

    assert healthy is False
    failed_logs = [log for log in cap if log.get("event") == _EVENT_HEALTH_FAILED]
    assert failed_logs
    assert failed_logs[0]["error_class"] == "LspTimeoutError"


# =============================================================================
# 【同步桥接 call_async_in_loop —— Pitfall P5】
# =============================================================================


@pytest.mark.asyncio
async def test_call_async_in_loop_succeeds_when_loop_running(
    supervisor: LspSupervisor,
) -> None:
    """background loop 运行时 call_async_in_loop 正常返回。"""
    from services.background_runner import _ensure_worker_loop

    _ensure_worker_loop()  # 启动 background loop

    async def factory() -> int:
        return 42

    result = supervisor.call_async_in_loop(factory, timeout=2.0)
    assert result == 42


@pytest.mark.asyncio
async def test_call_async_in_loop_raises_unhealthy_when_loop_unavailable(
    supervisor: LspSupervisor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """模拟 _loop 为 None → LspUnhealthyError 含'background loop 未运行'。"""
    monkeypatch.setattr(supervisor_mod._bg_runner, "_loop", None)

    async def factory() -> int:
        return 1

    with pytest.raises(LspUnhealthyError, match="background loop 未运行"):
        supervisor.call_async_in_loop(factory, timeout=1.0)


@pytest.mark.asyncio
async def test_call_async_in_loop_raises_timeout_after_deadline(
    supervisor: LspSupervisor,
) -> None:
    """coro 内挂起；timeout 后 raise LspTimeoutError 含 'timeout after'。"""
    from services.background_runner import _ensure_worker_loop

    _ensure_worker_loop()

    async def factory() -> int:
        await asyncio.sleep(10)
        return 0

    with pytest.raises(LspTimeoutError, match="timeout after"):
        supervisor.call_async_in_loop(factory, timeout=0.1)


# =============================================================================
# 【stub did_* API —— work item】
# =============================================================================


def test_notify_did_open_change_close_stub_only_updates_dict(
    supervisor: LspSupervisor,
) -> None:
    """3 个 did_* API 仅更新 _open_documents；不接触真实 LSP notification。"""
    supervisor.notify_did_open("file:///x.vue", "src v1")
    assert supervisor._open_documents == {"file:///x.vue": "src v1"}

    supervisor.notify_did_change("file:///x.vue", "src v2")
    assert supervisor._open_documents == {"file:///x.vue": "src v2"}

    supervisor.notify_did_close("file:///x.vue")
    assert supervisor._open_documents == {}


# =============================================================================
# 【structlog 事件名常量 sanity check】
# =============================================================================


def test_event_constants_have_expected_values() -> None:
    """12 个事件常量字面值与契约对齐。"""
    assert _EVENT_SUPERVISOR_STARTED == "lsp_supervisor_started"
    assert _EVENT_STATUS_CHANGED == "lsp_supervisor_status_changed"
    assert _EVENT_HEALTH_PASSED == "lsp_health_check_passed"
    assert _EVENT_HEALTH_FAILED == "lsp_health_check_failed"
    assert _EVENT_CRASHED == "lsp_crashed"
    assert _EVENT_RESTART_ATTEMPT == "lsp_restart_attempt"
    assert _EVENT_DISABLED == "lsp_disabled"


@pytest.mark.asyncio
async def test_restart_emits_restart_attempt_and_status_changed(
    supervisor: LspSupervisor,
) -> None:
    """restart() 内触发 _EVENT_RESTART_ATTEMPT + _EVENT_STATUS_CHANGED。"""
    supervisor._spawn_client = AsyncMock()  # type: ignore[method-assign]
    supervisor._stop_client_silently = AsyncMock()  # type: ignore[method-assign]
    supervisor._replay_open_documents = AsyncMock()  # type: ignore[method-assign]

    with capture_logs() as cap:
        await supervisor.restart(reason="test_emit")

    events = {log.get("event") for log in cap}
    assert _EVENT_RESTART_ATTEMPT in events
    assert _EVENT_STATUS_CHANGED in events


@pytest.mark.asyncio
async def test_spawn_client_emits_supervisor_started_on_success(
    supervisor: LspSupervisor,
) -> None:
    """_spawn_client 成功路径触发 _EVENT_SUPERVISOR_STARTED 含 command / workspace_root。"""
    fake_client = MagicMock()
    fake_client._server = None  # 强制走 transport 分支
    fake_proc = MagicMock()
    fake_proc.returncode = None
    fake_proc.pid = 12345
    transport = MagicMock()
    transport.get_extra_info = MagicMock(return_value=fake_proc)
    protocol = MagicMock()
    protocol.transport = transport
    fake_client.protocol = protocol
    fake_client.start = AsyncMock()

    # patch FridayLanguageClient 构造返回 fake_client
    import codegraph.lsp.supervisor as mod

    original = mod.FridayLanguageClient
    setattr(mod, "FridayLanguageClient", MagicMock(return_value=fake_client))
    try:
        with capture_logs() as cap:
            await supervisor._spawn_client()
    finally:
        setattr(mod, "FridayLanguageClient", original)

    started_logs = [log for log in cap if log.get("event") == _EVENT_SUPERVISOR_STARTED]
    assert started_logs
    assert started_logs[0]["pid"] == 12345
    assert started_logs[0]["command"] == ["echo", "stub"]
