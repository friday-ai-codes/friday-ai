"""VolarPool —— 多 sub-project volar 实例池 + LRU 调度。

``max_concurrent=4`` + ``OrderedDict`` LRU 驱逐最久未用
模块级单例 ``get_volar_pool()`` + ``threading.Lock`` 守门并发 init
VolarPool 内部 ``_pool: OrderedDict[Path, LspSupervisor]`` 自管实例
            （**不**复用 implementation ``_SUPERVISORS`` 模块级 cache，避免多实例 collide）
所有 supervisor 共享 ``services/background_runner.py`` 全局 loop（同 implementation）

公开 API
========

- ``VolarPool`` 类：``get(sub_project_path, *, vue_version)`` /
  ``shutdown_all(timeout)``
- ``get_volar_pool() -> VolarPool`` 模块级单例工厂

4 个新 structlog 事件（per work item / work item）
==========================================

- ``volar_pool_get``（fields: sub_project_path, result=hit|miss）
- ``volar_pool_evicted``（fields: evicted_sub_project, new_sub_project, pool_size_after）
- ``volar_pool_shutdown``（fields: count）
- ``volar_backend_fallback_vue26``（fields: sub_project_path, vue_version）
"""

from __future__ import annotations

import copy
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Final

import structlog
from django.conf import settings

from codegraph.lsp.exceptions import LspUnhealthyError
from codegraph.lsp.node_check import check_node_runtime, discover_tsdk
from codegraph.lsp.supervisor import LspSupervisor

logger = structlog.get_logger(__name__)

_EVENT_POOL_GET: Final[str] = "volar_pool_get"
_EVENT_POOL_EVICTED: Final[str] = "volar_pool_evicted"
_EVENT_POOL_SHUTDOWN: Final[str] = "volar_pool_shutdown"
_EVENT_FALLBACK_VUE26: Final[str] = "volar_backend_fallback_vue26"
_EVENT_POOL_EVICT_STOP_ERROR: Final[str] = "volar_pool_evict_stop_error"
_EVENT_POOL_SHUTDOWN_ERROR: Final[str] = "volar_pool_shutdown_error"


class VolarPool:
    """volar 多实例池 + LRU 调度（per-sub-project 一个 ``LspSupervisor``）。

    线程安全：所有写状态路径用 ``self._lock``；驱逐时 ``stop`` 调用在锁内（接受
    ≤ 5s 阻塞，per Pitfall P-checkpoint 工作集 > 4 时偶发）。
    """

    def __init__(self, max_concurrent: int = 4) -> None:
        if max_concurrent <= 0:
            raise ValueError(
                f"max_concurrent 必须 > 0，收到 {max_concurrent}"
            )
        self._max_concurrent = max_concurrent
        self._pool: OrderedDict[Path, LspSupervisor] = OrderedDict()
        self._lock = threading.Lock()

    def get(
        self,
        sub_project_path: Path,
        *,
        vue_version: str | None = None,
    ) -> LspSupervisor:
        """获取 sub-project 对应 supervisor；池满时 LRU 驱逐最久未用。

        Args:
            sub_project_path: sub-project 绝对路径（内部 ``.resolve()`` 归一）
            vue_version: package.json::dependencies.vue 解析的 semver；
                None / vue<2.7 时 raise（防御性 fallback per work item / work item）

        Returns:
            ``LspSupervisor`` 实例（lazy 启动；首次 ``call_async_in_loop`` 才 spawn）

        Raises:
            LspUnhealthyError: vue<2.7 / Node 不可达 / vue-language-server 缺失
        """
        # 避免循环 import，inline 引入
        from codegraph.lsp.workspace_discovery import is_vue_27_or_newer

        if not is_vue_27_or_newer(vue_version):
            logger.warning(
                _EVENT_FALLBACK_VUE26,
                sub_project_path=str(sub_project_path),
                vue_version=vue_version,
            )
            raise LspUnhealthyError(
                f"vue<2.7（实际 {vue_version!r}）不支持 volar；走 tree-sitter fallback"
            )

        node = check_node_runtime()
        if not node.available:
            raise LspUnhealthyError(f"volar 不可用: {node.reason}")

        normalized = sub_project_path.resolve()
        with self._lock:
            existing = self._pool.get(normalized)
            if existing is not None:
                self._pool.move_to_end(normalized)
                logger.debug(
                    _EVENT_POOL_GET,
                    sub_project_path=str(normalized),
                    result="hit",
                    pool_size=len(self._pool),
                )
                return existing

            if len(self._pool) >= self._max_concurrent:
                evicted_path, evicted_sup = self._pool.popitem(last=False)
                logger.info(
                    _EVENT_POOL_EVICTED,
                    evicted_sub_project=str(evicted_path),
                    new_sub_project=str(normalized),
                    pool_size_after=len(self._pool) + 1,
                )
                try:
                    evicted_sup.call_async_in_loop(evicted_sup.stop, timeout=5.0)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        _EVENT_POOL_EVICT_STOP_ERROR,
                        sub_project_path=str(evicted_path),
                        error_class=type(exc).__name__,
                        error=str(exc),
                    )

            sup = self._build_supervisor(normalized)
            self._pool[normalized] = sup
            logger.info(
                _EVENT_POOL_GET,
                sub_project_path=str(normalized),
                result="miss",
                pool_size=len(self._pool),
            )
            return sup

    def _build_supervisor(self, sub_project_path: Path) -> LspSupervisor:
        """实例化 per-sub-project ``LspSupervisor`` + 注入 tsdk + workspace_root。

        ``settings.LSP_SERVERS["volar"]["initialization_options"]`` 是模块级共享
        dict，必须 deepcopy 后再注入 tsdk，防 mutation 影响其他 sub-project。
        """
        volar_cfg: dict[str, Any] = settings.LSP_SERVERS["volar"]
        init_options_src: dict[str, Any] = volar_cfg.get("initialization_options") or {}
        init_options: dict[str, Any] = copy.deepcopy(init_options_src)
        tsdk = discover_tsdk()
        ts_block = init_options.setdefault("typescript", {})
        if isinstance(ts_block, dict):
            ts_block["tsdk"] = str(tsdk) if tsdk else None

        return LspSupervisor(
            name=f"volar:{sub_project_path.name}",
            command=list(volar_cfg["command"]),
            workspace_root=sub_project_path,
            language_ids=list(volar_cfg["language_ids"]),
            initialization_options=init_options,
            max_restart_attempts=int(getattr(settings, "LSP_MAX_RESTART_ATTEMPTS", 3)),
        )

    def shutdown_all(self, timeout: float = 5.0) -> None:
        """串行 stop 全部 supervisor + 清池 + 孤儿收割；吞所有异常防 atexit cascade。

        per Pitfall P-checkpoint：atexit 阶段 background loop 可能已停，
        每 supervisor.stop 单独 try/except + log warning。
        D-14：finally 路径 best-effort 调 ``reap_orphan_lsp_processes``。
        """
        with self._lock:
            snapshot = list(self._pool.items())
            self._pool.clear()
        for path, sup in snapshot:
            try:
                sup.call_async_in_loop(sup.stop, timeout=timeout)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    _EVENT_POOL_SHUTDOWN_ERROR,
                    sub_project_path=str(path),
                    error_class=type(exc).__name__,
                    error=str(exc),
                )
        logger.info(_EVENT_POOL_SHUTDOWN, count=len(snapshot))
        try:
            from codegraph.lsp.orphan_reap import reap_orphan_lsp_processes

            reap_orphan_lsp_processes(live_pids=set())
        except Exception:  # noqa: BLE001
            pass


# =============================================================================
# 模块级单例（per work item）
# =============================================================================

_VOLAR_POOL: VolarPool | None = None
_SINGLETON_LOCK: Final[threading.Lock] = threading.Lock()


def get_volar_pool() -> VolarPool:
    """模块级单例（per work item）；lazy 实例化让 settings 加载顺序安全。"""
    global _VOLAR_POOL
    with _SINGLETON_LOCK:
        if _VOLAR_POOL is None:
            _VOLAR_POOL = VolarPool(
                max_concurrent=int(getattr(settings, "VOLAR_POOL_MAX_CONCURRENT", 4))
            )
        return _VOLAR_POOL


__all__ = ["VolarPool", "get_volar_pool"]
