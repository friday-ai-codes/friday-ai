"""LspSupervisor —— LSP 进程 lifecycle + 健康检查 + crash-loop 防护。

核心职责（per work item / work item / work item / work item / work item）：

1. **lifecycle 管理**：lazy 启动 / ensure_started / stop / restart；threading.Lock
   保护多线程入口的状态读 + 早返路径
2. **健康检查后台 task**：周期 ping（默认 30s 一次 ``workspace/symbol("")``）+
   双重检查（``proc.returncode`` + LSP ping）；累计 3 次失败转 UNHEALTHY 触发 restart
3. **crash-loop 防护**：``max_restart_attempts=3`` 硬阈值 + DISABLED 永久禁用
4. **同步桥接**：``call_async_in_loop`` 在 background loop 内跑 coro factory +
   ``Future.result(timeout)``；复用 ``services/background_runner.py`` 既有 loop
   （per work item 全局单例）
5. **did_* stub API**：``notify_did_open / change / close`` 仅维护
   ``_open_documents`` 字典 + log debug（per work item）；真实 LSP notification 由
   implementation / 267 子类 backend 实装
6. **可观测性**：12 事件名常量字典（per work item）+ structlog 字段化所有状态转换

设计约束：
- **不**用 ``async_to_sync`` / ``sync_to_async``（per Pitfall P11；implementation 踩坑）
- 测试 sleep 用 ``wait_until`` helper（per Pitfall P6 / P10）
- 健康检查 / restart 路径全部在 background loop 内 async 执行
"""

from __future__ import annotations

import asyncio
import dataclasses
import enum
import threading
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Any, TypeVar

import structlog
from django.conf import settings

import services.background_runner as _bg_runner
from codegraph.lsp.client import FridayLanguageClient
from codegraph.lsp.exceptions import (
    LspDisabledError,
    LspError,
    LspStartupError,
    LspTimeoutError,
    LspUnhealthyError,
)

logger = structlog.get_logger(__name__)

T = TypeVar("T")


# =============================================================================
# 12 structlog 事件名常量（per work item / V5）
# =============================================================================

_EVENT_SUPERVISOR_STARTED = "lsp_supervisor_started"
_EVENT_STATUS_CHANGED = "lsp_supervisor_status_changed"
_EVENT_HEALTH_PASSED = "lsp_health_check_passed"
_EVENT_HEALTH_FAILED = "lsp_health_check_failed"
_EVENT_REQUEST_TIMEOUT = "lsp_request_timeout"
_EVENT_CRASHED = "lsp_crashed"
_EVENT_RESTART_ATTEMPT = "lsp_restart_attempt"
_EVENT_DISABLED = "lsp_disabled"
_EVENT_EXTRACT_SYMBOLS_FALLBACK = "lsp_extract_symbols_fallback"
_EVENT_EXTRACT_IMPORTS_FALLBACK = "lsp_extract_imports_fallback"
_EVENT_EXTRACT_CALLS_FALLBACK = "lsp_extract_calls_fallback"
_EVENT_EXTRACT_ENDPOINTS_FALLBACK = "lsp_extract_endpoints_fallback"


class LspSupervisorStatus(str, enum.Enum):
    """LspSupervisor 8 状态枚举（per work item）。

    状态机：STARTING → READY → (UNHEALTHY ↔ READY) → RESTARTING → CRASHED →
    DISABLED；STOPPING → STOPPED 是优雅退出分支。
    """

    STARTING = "STARTING"
    READY = "READY"
    UNHEALTHY = "UNHEALTHY"
    RESTARTING = "RESTARTING"
    CRASHED = "CRASHED"
    DISABLED = "DISABLED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"


def _get_background_loop() -> asyncio.AbstractEventLoop | None:
    """读 ``services/background_runner.py`` 模块级 ``_loop``（测试 monkeypatch 入口）。

    本 helper 不主动调 ``_ensure_worker_loop()``，避免在守门检查时意外启动；
    实际同步桥接路径在 ``call_async_in_loop`` 内显式启动 loop。
    """
    return _bg_runner._loop


def _get_settings_int(name: str, default: int) -> int:
    """读 settings 整型常量；缺失时回退 default（用于 settings 尚未配置场景）。"""
    return getattr(settings, name, default)


def _get_settings_float(name: str, default: float) -> float:
    """读 settings 数值常量（允许 int / float），自动转 float。"""
    return float(getattr(settings, name, default))


@dataclasses.dataclass
class LspSupervisor:
    """LSP 进程 supervisor —— lifecycle + 健康检查 + crash-loop 防护。

    公开 init 字段：name / command / workspace_root / language_ids /
    initialization_options / max_restart_attempts；私有运行时状态全
    field(init=False) + 默认值。

    多线程入口（``call_async_in_loop`` / ``ensure_started`` / ``reset_disabled``）
    用 ``_lock`` 保护状态读 + 早返；await 路径在锁外执行（per Pattern F）。
    """

    name: str
    command: list[str]
    workspace_root: Path
    language_ids: list[str]
    initialization_options: dict[str, Any] | None = None
    max_restart_attempts: int = 3

    _client: FridayLanguageClient | None = dataclasses.field(default=None, init=False)
    _status: LspSupervisorStatus = dataclasses.field(
        default=LspSupervisorStatus.STOPPED, init=False
    )
    _restart_attempts: int = dataclasses.field(default=0, init=False)
    _consecutive_unhealthy_checks: int = dataclasses.field(default=0, init=False)
    _open_documents: dict[str, str] = dataclasses.field(default_factory=dict, init=False)
    _health_check_task: asyncio.Task[None] | None = dataclasses.field(
        default=None, init=False
    )
    _idle_timeout_task: asyncio.Task[None] | None = dataclasses.field(
        default=None, init=False
    )
    _last_used_at: float = dataclasses.field(default=0.0, init=False)
    _lock: threading.Lock = dataclasses.field(
        default_factory=threading.Lock, init=False, repr=False, compare=False
    )

    # =========================================================================
    # lifecycle
    # =========================================================================

    async def _transition(
        self, new_status: LspSupervisorStatus, *, reason: str
    ) -> None:
        """状态转换（含 structlog 事件 _EVENT_STATUS_CHANGED）。"""
        old = self._status
        self._status = new_status
        logger.info(
            _EVENT_STATUS_CHANGED,
            name=self.name,
            old_status=old.value,
            new_status=new_status.value,
            reason=reason,
        )

    async def _spawn_client(self) -> None:
        """启动一个新 LSP client；失败转 CRASHED 并 raise LspStartupError。"""
        await self._transition(LspSupervisorStatus.STARTING, reason="spawn")
        client = FridayLanguageClient()
        startup_timeout = _get_settings_float("LSP_STARTUP_TIMEOUT_SECONDS", 30.0)
        try:
            await client.start(
                command=self.command,
                workspace_root=self.workspace_root,
                language_ids=self.language_ids,
                initialization_options=self.initialization_options,
                startup_timeout=startup_timeout,
            )
        except LspStartupError as exc:
            await self._transition(
                LspSupervisorStatus.CRASHED, reason=f"startup_failed: {exc}"
            )
            self._client = None
            raise

        # subprocess alive check（per Pitfall P13 silent exit）
        proc = self._get_subprocess(client)
        if proc is not None and proc.returncode is not None:
            await self._transition(
                LspSupervisorStatus.CRASHED,
                reason=f"startup_failed: subprocess exited returncode={proc.returncode}",
            )
            self._client = None
            raise LspStartupError(
                f"subprocess 启动后立即 returncode={proc.returncode}（command={self.command}）"
            )

        self._client = client
        await self._transition(LspSupervisorStatus.READY, reason="started")

        pid = proc.pid if proc is not None else None
        logger.info(
            _EVENT_SUPERVISOR_STARTED,
            name=self.name,
            pid=pid,
            command=self.command,
            workspace_root=str(self.workspace_root),
            language_ids=self.language_ids,
        )
        self._last_used_at = time.monotonic()

        # 健康检查后台 task（per work item）
        if self._health_check_task is None or self._health_check_task.done():
            self._health_check_task = asyncio.create_task(self._health_check_loop())

    @staticmethod
    def _get_subprocess(client: FridayLanguageClient) -> Any | None:
        """读 pygls client 的 subprocess（per Pattern E）。

        pygls v2.x ``BaseLanguageClient`` 把 ``asyncio.subprocess.Process``
        实例存在 ``_server`` 私有属性；transport 路径仅在 mock 场景使用。
        """
        server = getattr(client, "_server", None)
        if server is not None:
            return server

        # 兼容 mock 测试场景：协议 transport 拿到 subprocess
        protocol = getattr(client, "protocol", None)
        if protocol is None:
            return None
        transport = getattr(protocol, "transport", None)
        if transport is None:
            return None
        get_extra_info = getattr(transport, "get_extra_info", None)
        if get_extra_info is None:
            return None
        return get_extra_info("subprocess")

    async def ensure_started(self) -> None:
        """确保 supervisor 已 READY；按当前状态分支处理。"""
        with self._lock:
            current = self._status
            if current == LspSupervisorStatus.READY:
                return
            if current == LspSupervisorStatus.DISABLED:
                raise LspDisabledError(
                    f"supervisor '{self.name}' 已 DISABLED；"
                    "需要调用 reset_disabled() 才解禁"
                )

        if current in (LspSupervisorStatus.STARTING, LspSupervisorStatus.RESTARTING):
            await self._wait_until_ready_or_failed()
            return

        # STOPPED / CRASHED / UNHEALTHY → 重新 spawn
        await self._spawn_client()

    def live_pid(self) -> int | None:
        """当前 LSP 子进程 PID（若仍存活）；供 orphan_reap 排除 live-set。"""
        if self._client is None:
            return None
        try:
            proc = self._get_subprocess(self._client)
        except Exception:  # noqa: BLE001
            return None
        if proc is None or getattr(proc, "returncode", None) is not None:
            return None
        pid = getattr(proc, "pid", None)
        return pid if isinstance(pid, int) and pid > 0 else None

    async def stop(self) -> None:
        """优雅停止 supervisor（cancel 后台 task + 停 client + 转 STOPPED）。"""
        if self._status == LspSupervisorStatus.STOPPED:
            return
        await self._transition(LspSupervisorStatus.STOPPING, reason="explicit_stop")

        for task in (self._health_check_task, self._idle_timeout_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
        self._health_check_task = None
        self._idle_timeout_task = None

        await self._stop_client_silently()
        await self._transition(LspSupervisorStatus.STOPPED, reason="stopped")

    async def restart(self, *, reason: str) -> None:
        """主动重启；累计达 max_restart_attempts 后转 DISABLED 永久禁用。"""
        self._restart_attempts += 1
        if self._restart_attempts > self.max_restart_attempts:
            await self._transition(
                LspSupervisorStatus.DISABLED,
                reason=f"crash_loop_after_{self._restart_attempts}_attempts",
            )
            logger.warning(
                _EVENT_DISABLED,
                name=self.name,
                total_attempts=self._restart_attempts,
                reason=reason,
            )
            return

        logger.warning(
            _EVENT_RESTART_ATTEMPT,
            name=self.name,
            attempt=self._restart_attempts,
            max_attempts=self.max_restart_attempts,
            reason=reason,
        )
        await self._transition(LspSupervisorStatus.RESTARTING, reason=reason)
        await self._stop_client_silently()

        try:
            await self._spawn_client()
        except LspStartupError as exc:
            await self._transition(
                LspSupervisorStatus.CRASHED, reason=f"restart_failed: {exc}"
            )
            await self.restart(reason="restart_failed_recursive")
            return

        await self._replay_open_documents()

    def reset_disabled(self) -> None:
        """显式解禁 DISABLED 状态（运维手动恢复入口）。"""
        if self._status == LspSupervisorStatus.DISABLED:
            self._restart_attempts = 0
            self._status = LspSupervisorStatus.STOPPED
            logger.info(
                _EVENT_STATUS_CHANGED,
                name=self.name,
                old_status=LspSupervisorStatus.DISABLED.value,
                new_status=LspSupervisorStatus.STOPPED.value,
                reason="reset_disabled",
            )

    async def _stop_client_silently(self) -> None:
        """安静地 stop 当前 client（吞所有异常 + log warning）。"""
        if self._client is None:
            return
        try:
            await self._client.stop(
                timeout=_get_settings_float("LSP_STARTUP_TIMEOUT_SECONDS", 30.0)
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "lsp_stop_client_silently_error",
                name=self.name,
                error_class=type(exc).__name__,
                error=str(exc),
            )
        self._client = None

    async def _replay_open_documents(self) -> None:
        """重启后批量 didOpen 复盘 stub（per work item）。

        本 phase 仅 log info；真实 LSP notification 由 implementation / 267 子类实装。
        """
        logger.info(
            "lsp_replay_open_documents_stub",
            supervisor=self.name,
            doc_count=len(self._open_documents),
        )

    async def _wait_until_ready_or_failed(self, timeout: float = 30.0) -> None:
        """轮询直到状态进入终态（READY / CRASHED / DISABLED）或超时。"""
        steps = max(1, int(timeout / 0.05))
        for _ in range(steps):
            if self._status in (
                LspSupervisorStatus.READY,
                LspSupervisorStatus.CRASHED,
                LspSupervisorStatus.DISABLED,
            ):
                return
            await asyncio.sleep(0.05)

    # =========================================================================
    # 健康检查（per work item / work item）
    # =========================================================================

    async def health_check_once(self) -> bool:
        """单次健康检查 = 进程存活 + LSP ping。

        Returns:
            True = healthy；False = unhealthy（已转 CRASHED 或 ping 失败）。
        """
        if self._client is None:
            return False

        proc = self._get_subprocess(self._client)
        if proc is not None and proc.returncode is not None:
            logger.error(
                _EVENT_CRASHED,
                name=self.name,
                returncode=proc.returncode,
                stderr_tail=None,
            )
            await self._transition(
                LspSupervisorStatus.CRASHED,
                reason=f"returncode={proc.returncode}",
            )
            return False

        start = time.monotonic()
        ping_timeout = _get_settings_float("LSP_HEALTH_CHECK_TIMEOUT_SECONDS", 5.0)
        try:
            await self._client.request_workspace_symbol("", timeout=ping_timeout)
        except (LspTimeoutError, LspError) as exc:
            elapsed = int((time.monotonic() - start) * 1000)
            logger.warning(
                _EVENT_HEALTH_FAILED,
                name=self.name,
                elapsed_ms=elapsed,
                error_class=type(exc).__name__,
                error=str(exc),
            )
            if isinstance(exc, LspTimeoutError):
                logger.warning(
                    _EVENT_REQUEST_TIMEOUT,
                    name=self.name,
                    method="workspace/symbol",
                    timeout_ms=int(ping_timeout * 1000),
                )
            return False

        elapsed = int((time.monotonic() - start) * 1000)
        logger.info(_EVENT_HEALTH_PASSED, name=self.name, elapsed_ms=elapsed)
        return True

    async def _health_check_loop(self) -> None:
        """周期 health check 后台 task；累计 3 次失败触发 restart。"""
        interval = _get_settings_float("LSP_HEALTH_CHECK_INTERVAL_SECONDS", 30.0)
        while self._status not in (
            LspSupervisorStatus.STOPPED,
            LspSupervisorStatus.DISABLED,
        ):
            try:
                await asyncio.sleep(interval)
                healthy = await self.health_check_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "lsp_health_check_loop_unexpected_error",
                    name=self.name,
                    error_class=type(exc).__name__,
                    error=str(exc),
                )
                continue

            if healthy:
                self._consecutive_unhealthy_checks = 0
                if self._status == LspSupervisorStatus.UNHEALTHY:
                    await self._transition(
                        LspSupervisorStatus.READY, reason="health_recovered"
                    )
                continue

            self._consecutive_unhealthy_checks += 1
            if self._consecutive_unhealthy_checks >= 3:
                await self._transition(
                    LspSupervisorStatus.UNHEALTHY,
                    reason="health_check_failed_3x",
                )
                await self.restart(reason="unhealthy_threshold")
                self._consecutive_unhealthy_checks = 0

    # =========================================================================
    # 同步桥接（per work item / work item / Pitfall P5）
    # =========================================================================

    def call_async_in_loop(
        self,
        coro_factory: Callable[[], Awaitable[T]],
        timeout: float,
    ) -> T:
        """在 background loop 内跑 coro factory；同步阻塞 Future.result(timeout)。

        Pitfall P5 守门：coro 必须由 factory 在 worker loop context 内构造，
        不能跨 loop 提交已 await 过的 coroutine。
        """
        loop = _get_background_loop()
        if loop is None or loop.is_closed():
            raise LspUnhealthyError(
                f"background loop 未运行；supervisor '{self.name}' 不可用"
            )

        async def _runner() -> T:
            return await coro_factory()

        future = asyncio.run_coroutine_threadsafe(_runner(), loop)
        try:
            result: T = future.result(timeout=timeout)
        except FutureTimeoutError as exc:
            future.cancel()
            raise LspTimeoutError(
                f"call_async_in_loop timeout after {timeout}s (supervisor={self.name})"
            ) from exc

        self._last_used_at = time.monotonic()
        return result

    # =========================================================================
    # did_* stub API（per work item / work item）
    # =========================================================================

    def notify_did_open(self, uri: str, content: str) -> None:
        """记录 didOpen 状态到 _open_documents（stub；不发真实 LSP notification）。"""
        self._open_documents[uri] = content
        logger.debug(
            "lsp_did_open_stub",
            supervisor=self.name,
            uri=uri,
            content_length=len(content),
        )

    def notify_did_change(self, uri: str, content: str) -> None:
        """更新 didChange 状态到 _open_documents（stub）。"""
        self._open_documents[uri] = content
        logger.debug(
            "lsp_did_change_stub",
            supervisor=self.name,
            uri=uri,
            content_length=len(content),
        )

    def notify_did_close(self, uri: str) -> None:
        """删除 didClose 状态（stub）。"""
        self._open_documents.pop(uri, None)
        logger.debug("lsp_did_close_stub", supervisor=self.name, uri=uri)


__all__ = ["LspSupervisor", "LspSupervisorStatus"]
