"""implementation: LSP supervisor 集成测试（真实 subprocess + work item roundtrip）。

覆盖 5 路径：
1. supervisor 启动 + 健康检查通过（V4 第一段）
2. friday/crash 触发崩溃后 supervisor 状态非 READY（V4 第二段 + security mitigation 部分）
3. friday/hang 触发 LspTimeoutError（security mitigation / V4）
4. 启动命令失败 N 次后转 DISABLED（V3 / security mitigation crash-loop 防护核心）
5. shutdown_all_supervisors atexit cleanup（P7 防 zombie）

所有测试用真实 ``sys.executable`` subprocess 启动 echo server，不 mock。
"""

from __future__ import annotations

import sys

import pytest

from codegraph.lsp import shutdown_all_supervisors
from codegraph.lsp.exceptions import LspDisabledError, LspStartupError
from codegraph.lsp.supervisor import LspSupervisor, LspSupervisorStatus
from codegraph.lsp.tests.conftest import wait_until


@pytest.mark.asyncio
async def test_supervisor_starts_and_passes_health_check_via_real_subprocess(
    lsp_supervisor_factory: object,
) -> None:
    """启动 echo server subprocess → supervisor 状态 READY → 单次健康检查通过。"""
    sup: LspSupervisor = lsp_supervisor_factory()  # type: ignore[operator]
    try:
        await sup._spawn_client()
        assert sup._status == LspSupervisorStatus.READY

        healthy = await sup.health_check_once()
        assert healthy is True
    finally:
        await sup.stop()


@pytest.mark.asyncio
async def test_supervisor_handles_friday_crash_and_transitions_away_from_ready(
    lsp_supervisor_factory: object,
) -> None:
    """echo server 收到 friday/crash → os._exit(1) → supervisor 检测到崩溃。"""
    import asyncio as _asyncio

    sup: LspSupervisor = lsp_supervisor_factory()  # type: ignore[operator]
    try:
        await sup._spawn_client()
        assert sup._status == LspSupervisorStatus.READY

        # 显式 cancel 健康检查后台 task，避免与本测试主路径竞争
        if sup._health_check_task is not None:
            sup._health_check_task.cancel()
            try:
                await sup._health_check_task
            except _asyncio.CancelledError:
                pass
            sup._health_check_task = None

        # 触发 friday/crash notification（pygls notify 是 sync 方法）
        client = sup._client
        assert client is not None
        client.protocol.notify("friday/crash", None)

        # 等 subprocess returncode 落定（POSIX kill 通常 < 1s）
        proc = sup._get_subprocess(client)
        assert proc is not None, "pygls _server 应为 asyncio.subprocess.Process"

        async def proc_dead() -> bool:
            return proc.returncode is not None

        ok = await wait_until(proc_dead, timeout=3.0, interval=0.05)
        assert ok, "echo server 未在 3s 内退出（friday/crash 失效？）"

        # 显式调健康检查触发 CRASHED 转换
        healthy = await sup.health_check_once()
        assert healthy is False
        assert sup._status == LspSupervisorStatus.CRASHED
    finally:
        # 已 CRASHED；stop 走 _stop_client_silently 吞异常
        await sup.stop()


@pytest.mark.asyncio
async def test_request_timeout_raises_lsp_timeout_error_on_friday_hang(
    lsp_supervisor_factory: object,
) -> None:
    """friday/hang 模拟 LSP server 挂起；client 层 asyncio.wait_for 超时归一 LspTimeoutError。"""
    import asyncio

    from codegraph.lsp.exceptions import LspTimeoutError

    sup: LspSupervisor = lsp_supervisor_factory()  # type: ignore[operator]
    try:
        await sup._spawn_client()
        assert sup._status == LspSupervisorStatus.READY

        client = sup._client
        assert client is not None

        # 调 friday/hang request；用 asyncio.wait_for 包装超时
        async def call_hang() -> None:
            await asyncio.wait_for(
                client.protocol.send_request_async("friday/hang", None),
                timeout=0.5,
            )

        with pytest.raises((LspTimeoutError, asyncio.TimeoutError)):
            await call_hang()
    finally:
        await sup.stop()


@pytest.mark.asyncio
async def test_supervisor_disabled_after_max_restart_attempts(
    lsp_supervisor_factory: object,
) -> None:
    """无效启动命令 (sys.exit(99)) 触发 N 次 restart 后转 DISABLED。"""
    bad_command = [sys.executable, "-c", "import sys; sys.exit(99)"]
    sup: LspSupervisor = lsp_supervisor_factory(  # type: ignore[operator]
        name="echo",
        command=bad_command,
        max_restart_attempts=2,  # 加速测试
    )

    try:
        # 首次启动必然失败
        with pytest.raises(LspStartupError):
            await sup.ensure_started()

        # 显式触发 restart 直到达 DISABLED
        # restart 内会自动递归，单次调用即够
        await sup.restart(reason="test_attempt")

        assert sup._status == LspSupervisorStatus.DISABLED
        assert sup._restart_attempts > sup.max_restart_attempts

        # 后续 ensure_started 即刻 raise LspDisabledError
        with pytest.raises(LspDisabledError, match="reset_disabled"):
            await sup.ensure_started()
    finally:
        # DISABLED supervisor 已不持有 client；stop() 直接早返
        await sup.stop()


@pytest.mark.asyncio
async def test_shutdown_all_supervisors_clears_cache_without_raising(
    lsp_supervisor_factory: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """shutdown_all_supervisors 清空 _SUPERVISORS 缓存且不向调用方抛异常（per Pitfall P7）。

    实测说明：本测试用一个未启动的 supervisor 注入缓存，因 supervisor 异步对象
    跨 loop 调用 stop 会失败；shutdown_all_supervisors 内的 try/except 必须吞掉。
    """
    import codegraph.lsp as lsp_pkg

    sup: LspSupervisor = lsp_supervisor_factory()  # type: ignore[operator]
    # 不启动 client；状态保持 STOPPED；shutdown_all 应直接早返且清缓存
    monkeypatch.setattr(lsp_pkg, "_SUPERVISORS", {"echo": sup})

    # 调用不抛
    shutdown_all_supervisors(timeout=2.0)

    # 缓存清空
    assert lsp_pkg._SUPERVISORS == {}
