"""LSP 孤儿进程收割（D-14；T-127-04）。

索引 / pool / supervisor 异常退出后，用 psutil 匹配残留的
``gopls`` / ``vue-language-server`` / ``typescript-language-server``，
排除仍由 live supervisor 持有的 PID，best-effort terminate/kill。

观测：``lsp_process_reaped``（category=sampling, component=codegraph.lsp）。
永不反噬索引主路径。
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any

import psutil
import structlog

logger = structlog.get_logger(__name__)

_LSP_NAME_MARKERS: tuple[str, ...] = (
    "gopls",
    "vue-language-server",
    "typescript-language-server",
)


def _cmdline_matches(name: str | None, cmdline: list[str] | None) -> bool:
    """cmdline/name 是否像 LSP 语言服进程。"""
    haystack_parts: list[str] = []
    if name:
        haystack_parts.append(name.lower())
    if cmdline:
        haystack_parts.extend(str(part).lower() for part in cmdline)
    haystack = " ".join(haystack_parts)
    return any(marker in haystack for marker in _LSP_NAME_MARKERS)


def _proc_info(proc: Any) -> dict[str, Any]:
    """兼容 psutil.Process.info dict 与测试用 callable/SimpleNamespace。"""
    try:
        raw = getattr(proc, "info", None)
        if callable(raw):
            raw = raw()
        if isinstance(raw, dict):
            return raw
    except Exception:  # noqa: BLE001
        pass
    return {
        "pid": getattr(proc, "pid", None),
        "name": None,
        "cmdline": None,
        "ppid": None,
    }


def _is_orphan(proc_info: dict[str, Any], live_pids: set[int]) -> bool:
    """匹配 LSP、不在 live-set，且父进程已死或父为当前进程（丢跟踪子进程）。"""
    pid = proc_info.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return False
    if pid in live_pids:
        return False
    if not _cmdline_matches(proc_info.get("name"), proc_info.get("cmdline")):
        return False

    ppid = proc_info.get("ppid")
    if not isinstance(ppid, int):
        return True
    if ppid <= 1:
        # init/launchd 收养 → 视为孤儿
        return True
    if ppid == os.getpid():
        # 本进程仍活但 supervisor 已丢失对该子进程的跟踪
        return True
    try:
        return not psutil.pid_exists(ppid)
    except Exception:  # noqa: BLE001
        return True


def _terminate_proc(proc: Any) -> bool:
    """terminate → wait → kill；成功结束返回 True。"""
    try:
        proc.terminate()
    except Exception:  # noqa: BLE001
        return False
    try:
        proc.wait(timeout=2)
        return True
    except psutil.TimeoutExpired:
        try:
            proc.kill()
            try:
                proc.wait(timeout=1)
            except Exception:  # noqa: BLE001
                pass
            return True
        except Exception:  # noqa: BLE001
            return False
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
            return True
        except Exception:  # noqa: BLE001
            return False


def collect_live_supervisor_pids(supervisors: Iterable[Any] | None = None) -> set[int]:
    """从 supervisor 实例收集仍存活的 LSP 子进程 PID（best-effort）。"""
    live: set[int] = set()
    if not supervisors:
        return live
    for supervisor in supervisors:
        try:
            getter = getattr(supervisor, "live_pid", None)
            if callable(getter):
                pid = getter()
                if isinstance(pid, int) and pid > 0:
                    live.add(pid)
                    continue
            client = getattr(supervisor, "_client", None)
            if client is None:
                continue
            get_sub = getattr(type(supervisor), "_get_subprocess", None)
            if callable(get_sub):
                proc = get_sub(client)
            else:
                proc = getattr(client, "_server", None)
            if proc is not None and getattr(proc, "returncode", None) is None:
                pid = getattr(proc, "pid", None)
                if isinstance(pid, int) and pid > 0:
                    live.add(pid)
        except Exception:  # noqa: BLE001
            continue
    return live


def reap_orphan_lsp_processes(
    *,
    live_pids: set[int] | None = None,
    supervisors: Iterable[Any] | None = None,
) -> int:
    """收割孤儿 LSP 进程；返回成功 reaped 计数。异常 best-effort 不抛。"""
    reaped = 0
    try:
        protected = set(live_pids or ())
        protected |= collect_live_supervisor_pids(supervisors)
        for proc in psutil.process_iter(["pid", "name", "cmdline", "ppid"]):
            try:
                info = _proc_info(proc)
                if not _is_orphan(info, protected):
                    continue
                if _terminate_proc(proc):
                    reaped += 1
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass

    try:
        logger.info(
            "lsp_process_reaped",
            category="sampling",
            component="codegraph.lsp",
            count=reaped,
        )
    except Exception:  # noqa: BLE001
        pass
    return reaped


__all__ = [
    "collect_live_supervisor_pids",
    "reap_orphan_lsp_processes",
]
