"""Node 22 LTS + vue-language-server + typescript SDK 检测层。

启动时一次性 subprocess 检测 + 进程级缓存（不过期；服务重启即重检）。
tsdk 三探针顺序（npm root -g / which tsc / monorepo node_modules）+ None fallback。
``shutil.which`` 跨平台 PATH 检测兼容 macOS / Linux / Windows。

公开 API
========

- ``check_node_runtime(*, force_refresh=False) -> NodeCheckResult``
- ``discover_tsdk() -> Path | None``
- ``NodeCheckResult`` frozen dataclass

设计约束
========

- 检测失败 **不** raise；返 ``NodeCheckResult.available=False``，让 VolarPool
  调用方决定是否走 fallback（per implementation fallback 兜底原则；per work item）。
- 5-10s subprocess 超时（探针只跑一次启动，长超时容忍 cold path）。
- 不抛异常，不入库；纯 stdlib + structlog。
"""

from __future__ import annotations

import dataclasses
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Final

import structlog

logger = structlog.get_logger(__name__)

# 3 个 structlog 事件名常量（per work item / work item）
_EVENT_NODE_CHECK_PASSED: Final[str] = "volar_node_check_passed"
_EVENT_NODE_CHECK_FAILED: Final[str] = "volar_node_check_failed"
_EVENT_TSDK_DISCOVERED: Final[str] = "volar_tsdk_discovered"

# Node 版本下界：@vue/language-server v3.x peerDep
_MIN_NODE_MAJOR: Final[int] = 18
# subprocess 探针超时（10s 是 cold path 容忍上限）
_PROBE_TIMEOUT_SECONDS: Final[float] = 10.0


@dataclasses.dataclass(frozen=True)
class NodeCheckResult:
    """Node + vue-language-server + tsdk 联合检测结果。

    ``available`` 仅在 node ≥ 18 AND vue-language-server 可达时为 True；
    ``reason`` 在 ``available=False`` 时含安装建议，``available=True`` 时为 ``"ok"``。
    """

    available: bool
    node_version: str | None
    vue_language_server_available: bool
    tsdk_path: Path | None
    reason: str


_CACHE_LOCK: Final[threading.Lock] = threading.Lock()
_CACHE: NodeCheckResult | None = None


def check_node_runtime(*, force_refresh: bool = False) -> NodeCheckResult:
    """启动时一次性检测；缓存进程存活期（per work item）。

    Args:
        force_refresh: 测试用入口；正常路径走缓存。

    Returns:
        ``NodeCheckResult``：失败时 ``available=False`` + ``reason`` 含安装建议。
    """
    global _CACHE
    with _CACHE_LOCK:
        if _CACHE is not None and not force_refresh:
            return _CACHE

        node_version, node_ok, node_reason = _probe_node()
        if not node_ok:
            _CACHE = NodeCheckResult(
                available=False,
                node_version=node_version,
                vue_language_server_available=False,
                tsdk_path=None,
                reason=node_reason,
            )
            logger.warning(
                _EVENT_NODE_CHECK_FAILED,
                reason=node_reason,
                node_version=node_version,
            )
            return _CACHE

        vls_ok, vls_reason = _probe_vue_language_server()
        tsdk = discover_tsdk()

        if vls_ok:
            _CACHE = NodeCheckResult(
                available=True,
                node_version=node_version,
                vue_language_server_available=True,
                tsdk_path=tsdk,
                reason="ok",
            )
            logger.info(
                _EVENT_NODE_CHECK_PASSED,
                node_version=node_version,
                tsdk_path=str(tsdk) if tsdk else None,
            )
        else:
            _CACHE = NodeCheckResult(
                available=False,
                node_version=node_version,
                vue_language_server_available=False,
                tsdk_path=tsdk,
                reason=vls_reason,
            )
            logger.warning(
                _EVENT_NODE_CHECK_FAILED,
                reason=vls_reason,
                node_version=node_version,
            )
        return _CACHE


def _probe_node() -> tuple[str | None, bool, str]:
    """``node --version`` 探针 → ``(version_str, ok, reason)``。

    失败时 ok=False + reason 含安装建议；不抛异常。
    """
    node_bin = shutil.which("node")
    if node_bin is None:
        return (
            None,
            False,
            "node 未在 PATH（建议 brew install node@22 或 nvm install 22）",
        )
    try:
        result = subprocess.run(
            ["node", "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS / 2,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, False, f"node --version 调用失败: {exc}"

    output = result.stdout.strip()
    if not output.startswith("v"):
        return output, False, f"node --version 返回异常输出: {output!r}"

    try:
        major = int(output[1:].split(".", 1)[0])
    except ValueError:
        return output, False, f"无法解析 node major 版本: {output!r}"

    if major < _MIN_NODE_MAJOR:
        return (
            output,
            False,
            (
                f"node {output} < v{_MIN_NODE_MAJOR}"
                f"（@vue/language-server v3.x 需 Node ≥ v{_MIN_NODE_MAJOR}，建议 22 LTS）"
            ),
        )
    return output, True, "ok"


def _probe_vue_language_server() -> tuple[bool, str]:
    """``vue-language-server --version`` 可达性探针。"""
    vls_bin = shutil.which("vue-language-server")
    if vls_bin is None:
        return (
            False,
            "vue-language-server 未在 PATH（建议 npm i -g @vue/language-server）",
        )
    try:
        subprocess.run(
            ["vue-language-server", "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"vue-language-server --version 调用失败: {exc}"
    return True, "ok"


def discover_tsdk() -> Path | None:
    """typescript SDK lib 路径动态发现（三探针 + None fallback，per work item）。

    探针顺序：
        1. ``npm root -g`` + ``/typescript/lib``
        2. ``which tsc`` 反推 → ``<which_tsc>/../lib``
        3. monorepo 根 ``node_modules/typescript/lib``

    全部失败返 None；让 volar 走其内部 bundled typescript SDK fallback。
    """
    for probe_fn in (
        _probe_tsdk_npm_root_global,
        _probe_tsdk_which_tsc,
        _probe_tsdk_monorepo_root,
    ):
        result = probe_fn()
        if result is not None:
            logger.info(
                _EVENT_TSDK_DISCOVERED,
                tsdk_path=str(result),
                probe=probe_fn.__name__,
            )
            return result
    return None


def _probe_tsdk_npm_root_global() -> Path | None:
    """探针 1：``npm root -g`` + ``/typescript/lib``。"""
    npm_bin = shutil.which("npm")
    if npm_bin is None:
        return None
    try:
        result = subprocess.run(
            ["npm", "root", "-g"],
            check=False,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS / 2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    npm_root = result.stdout.strip()
    if not npm_root:
        return None
    candidate = Path(npm_root) / "typescript" / "lib"
    return candidate if candidate.exists() else None


def _probe_tsdk_which_tsc() -> Path | None:
    """探针 2：``which tsc`` 反推 ``<which_tsc>/../lib``。"""
    tsc = shutil.which("tsc")
    if tsc is None:
        return None
    try:
        candidate = Path(tsc).resolve().parent.parent / "lib"
    except OSError:
        return None
    return candidate if candidate.exists() else None


def _probe_tsdk_monorepo_root() -> Path | None:
    """探针 3：cwd ``node_modules/typescript/lib``（pnpm/npm 本地装）。"""
    candidate = Path.cwd() / "node_modules" / "typescript" / "lib"
    return candidate if candidate.exists() else None


__all__ = ["NodeCheckResult", "check_node_runtime", "discover_tsdk"]
