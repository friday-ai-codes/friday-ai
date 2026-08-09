"""LSP 客户端 + Supervisor 子包入口。

本子包封装通用 LSP 客户端框架：

- ``exceptions``：5 类业务异常（LspError 基类 + 4 子类）
- ``protocol``：lsprotocol 类型重导出 + URI 双向转换 helper
- ``client``：FridayLanguageClient（pygls BaseLanguageClient 子类，封装超时与异常归一）
- ``supervisor``：LspSupervisor 状态机 + 健康检查 + crash-loop 防护
- ``backend``：LspBackend 抽象基类 + 模板方法 + tree-sitter fallback

工厂入口（per work item 单例 + Pattern 4 lifecycle）：

- :func:`get_or_create_supervisor`：per-name 单例工厂；threading.Lock 守门并发
- :func:`shutdown_all_supervisors`：进程退出 / Django shutdown 时批量优雅退出

本 phase 不在任何模块内调 ``register_backend`` 注册 ``lsp_*`` backend；
真实 backend 子类（``VolarBackend`` / ``GoplsBackend``）由 implementation / 267 落地。
"""

from __future__ import annotations

import atexit
import threading
from pathlib import Path

import structlog
from django.conf import settings

from codegraph.lsp.supervisor import LspSupervisor

logger = structlog.get_logger(__name__)


_SUPERVISORS: dict[str, LspSupervisor] = {}
_LOCK = threading.Lock()


def get_or_create_supervisor(
    name: str,
    *,
    workspace_root: Path | None = None,
) -> LspSupervisor:
    """获取或创建 ``name`` 对应的 supervisor 实例（单例工厂）。

    首次创建时从 ``settings.LSP_SERVERS[name]`` 读 command / language_ids /
    initialization_options；注册 ``atexit`` cleanup 钩子。后续调用返回同一实例。

    Args:
        name: supervisor 标识（与 ``settings.LSP_SERVERS`` key 对齐）。
        workspace_root: 可选 workspace 根目录；缺省时从 ``settings.LSP_SERVERS[name]``
            读 ``workspace_root`` 字段，再缺省回退到当前工作目录。

    Raises:
        KeyError: ``settings.LSP_SERVERS`` 内无 ``name`` 对应条目。
    """
    with _LOCK:
        existing = _SUPERVISORS.get(name)
        if existing is not None:
            return existing

        lsp_servers: dict[str, dict[str, object]] = getattr(
            settings, "LSP_SERVERS", {}
        )
        config = lsp_servers.get(name)
        if config is None:
            available = sorted(lsp_servers.keys())
            raise KeyError(
                f"settings.LSP_SERVERS 内无 '{name}' 对应配置；可用 keys={available}"
            )

        cmd_value = config["command"]
        if isinstance(cmd_value, list):
            command = [str(part) for part in cmd_value]
        else:
            raise KeyError(
                f"LSP_SERVERS['{name}'].command 必须为 list[str]，"
                f"实际类型={type(cmd_value).__name__}"
            )

        language_ids_value = config.get("language_ids", [])
        if isinstance(language_ids_value, list):
            language_ids = [str(part) for part in language_ids_value]
        else:
            language_ids = []

        init_options_value = config.get("initialization_options")
        initialization_options = (
            init_options_value if isinstance(init_options_value, dict) else None
        )

        if workspace_root is None:
            ws_value = config.get("workspace_root")
            workspace_root = (
                Path(str(ws_value)) if ws_value is not None else Path.cwd()
            )

        max_attempts = int(getattr(settings, "LSP_MAX_RESTART_ATTEMPTS", 3))

        supervisor = LspSupervisor(
            name=name,
            command=command,
            workspace_root=workspace_root,
            language_ids=language_ids,
            initialization_options=initialization_options,
            max_restart_attempts=max_attempts,
        )
        _SUPERVISORS[name] = supervisor
        atexit.register(_atexit_cleanup, supervisor)
        return supervisor


def shutdown_all_supervisors(timeout: float = 5.0) -> None:
    """批量优雅停止所有 supervisor（清理 _SUPERVISORS 缓存）+ 孤儿收割（D-14）。"""
    with _LOCK:
        snapshot = list(_SUPERVISORS.values())
        _SUPERVISORS.clear()

    for supervisor in snapshot:
        try:
            supervisor.call_async_in_loop(supervisor.stop, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "lsp_shutdown_all_supervisors_error",
                supervisor=supervisor.name,
                error_class=type(exc).__name__,
                error=str(exc),
            )
    try:
        from codegraph.lsp.orphan_reap import reap_orphan_lsp_processes

        reap_orphan_lsp_processes(live_pids=set())
    except Exception:  # noqa: BLE001
        pass


def _atexit_cleanup(supervisor: LspSupervisor) -> None:
    """atexit 钩子：进程退出时调 supervisor.stop + orphan reap（吞所有异常）。"""
    try:
        supervisor.call_async_in_loop(supervisor.stop, timeout=5.0)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "lsp_atexit_cleanup_error",
            supervisor=supervisor.name,
            error_class=type(exc).__name__,
            error=str(exc),
        )
    try:
        from codegraph.lsp.orphan_reap import reap_orphan_lsp_processes

        reap_orphan_lsp_processes(live_pids=set())
    except Exception:  # noqa: BLE001
        pass


__all__ = ["get_or_create_supervisor", "shutdown_all_supervisors"]
