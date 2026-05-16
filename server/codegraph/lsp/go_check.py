"""Phase: gopls v0.14+ + Go SDK ≥ 1.20 二进制检测层 + 进程缓存。
per：启动时一次性 subprocess 检测 + 进程级缓存（不过期；服务重启即重检）。
per：检测失败不 raise；返 GoCheckResult.available=False，让 _GoplsLazyBackend
 调用方决定是否走 fallback（per Phase fallback 兜底原则）。
per：shutil.which 跨平台 PATH 检测兼容 macOS / Linux / Windows。
公开 API
========
- ``check_go_runtime(*, force_refresh=False) -> GoCheckResult``
- ``GoCheckResult`` frozen dataclass
设计约束
========
- 检测失败 **不** raise；返 ``GoCheckResult.available=False``
- subprocess 超时上限 10s（探针仅跑一次启动，cold path 容忍）
- 不抛异常，不入库；纯 stdlib + structlog
"""
from __future__ import annotations
import dataclasses
import re
import shutil
import subprocess
import threading
from typing import Final
import structlog
logger = structlog.get_logger(__name__)
# structlog 事件名常量（per / ）
_EVENT_GOPLS_CHECK_PASSED: Final[str] = "gopls_check_passed"
_EVENT_GOPLS_CHECK_FAILED: Final[str] = "gopls_check_failed"
# 版本下界（per ）
_MIN_GO_MAJOR: Final[int] = 1
_MIN_GO_MINOR: Final[int] = 20
_MIN_GOPLS_MINOR: Final[int] = 14 # gopls v0.14+（per ）
# subprocess 探针超时（10s 是 cold path 容忍上限）
_PROBE_TIMEOUT_SECONDS: Final[float] = 10.0
@dataclasses.dataclass(frozen=True)
class GoCheckResult:
 """gopls + Go SDK 联合检测结果。
 ``available`` 仅在 gopls ≥ v0.14 AND go ≥ 1.20 时为 True；
 ``reason`` 在 ``available=False`` 时含安装建议，``available=True`` 时为 ``"ok"``。
 """
 available: bool
 gopls_version: str | None
 go_version: str | None
 reason: str
_CACHE_LOCK: Final[threading.Lock] = threading.Lock
_CACHE: GoCheckResult | None = None
def check_go_runtime(*, force_refresh: bool = False) -> GoCheckResult:
 """启动时一次性检测；缓存进程存活期（per ）。
 策略：
 1. 调 _probe_gopls 检测 gopls 二进制 + 版本
 2. gopls 不可用 → 立即返 available=False（不继续探 go）
 3. 调 _probe_go 检测 go 二进制 + 版本
 4. 两者均可用 → available=True
 Args:
 force_refresh: 测试用入口；正常路径走缓存（per Pitfall P-）。
 Returns:
 ``GoCheckResult``：失败时 ``available=False`` + ``reason`` 含安装建议。
 """
 global _CACHE
 with _CACHE_LOCK:
 if _CACHE is not None and not force_refresh:
 return _CACHE
 gopls_version, gopls_ok, gopls_reason = _probe_gopls
 if not gopls_ok:
 _CACHE = GoCheckResult(
 available=False,
 gopls_version=gopls_version,
 go_version=None,
 reason=gopls_reason,
 )
 logger.warning(
 _EVENT_GOPLS_CHECK_FAILED,
 reason=gopls_reason,
 gopls_version=gopls_version,
 )
 return _CACHE
 go_version, go_ok, go_reason = _probe_go
 if not go_ok:
 _CACHE = GoCheckResult(
 available=False,
 gopls_version=gopls_version,
 go_version=go_version,
 reason=go_reason,
 )
 logger.warning(
 _EVENT_GOPLS_CHECK_FAILED,
 reason=go_reason,
 gopls_version=gopls_version,
 go_version=go_version,
 )
 return _CACHE
 _CACHE = GoCheckResult(
 available=True,
 gopls_version=gopls_version,
 go_version=go_version,
 reason="ok",
 )
 logger.info(
 _EVENT_GOPLS_CHECK_PASSED,
 gopls_version=gopls_version,
 go_version=go_version,
 )
 return _CACHE
def _probe_gopls -> tuple[str | None, bool, str]:
 """``gopls version`` 探针 → ``(version_str, ok, reason)``。
 per Pitfall P-：gopls version 输出格式不稳定，使用宽松正则。
 失败时 ok=False + reason 含安装建议；不抛异常。
 """
 gopls_bin = shutil.which("gopls")
 if gopls_bin is None:
 return (
 None,
 False,
 "gopls binary 未在 PATH（建议 go install golang.org/x/tools/gopls@latest）",
 )
 try:
 result = subprocess.run(
 ["gopls", "version"],
 check=False,
 capture_output=True,
 text=True,
 timeout=_PROBE_TIMEOUT_SECONDS,
 )
 except (OSError, subprocess.TimeoutExpired) as exc:
 return None, False, f"gopls version 调用失败: {exc}"
 output = (result.stdout + result.stderr).strip
 # 宽松正则匹配 gopls version（per Pitfall P-）
 m = re.search(r"gopls\s+v?(\d+)\.(\d+)", output, re.IGNORECASE)
 if m is None:
 # 尝试匹配 "v0.15.3" 格式（golang.org/x/tools/gopls v0.15.3）
 m2 = re.search(r"v?(\d+)\.(\d+)\.\d+", output)
 if m2 is None:
 return output or None, False, f"无法解析 gopls 版本输出: {output!r}"
 major, minor = int(m2.group(1)), int(m2.group(2))
 version_str = m2.group(0)
 else:
 major, minor = int(m.group(1)), int(m.group(2))
 # 提取完整版本字符串
 vm = re.search(r"v?(\d+\.\d+(?:\.\d+)?)", output)
 version_str = vm.group(0) if vm else f"{major}.{minor}"
 # gopls 目前保持 v0.x 版本号（截至 2026 年）；
 # major > 0 视为向前兼容（v1.0 必然 ≥ v0.14），无条件通过。
 if major == 0 and minor < _MIN_GOPLS_MINOR:
 return (
 version_str,
 False,
 f"gopls {version_str} < v0.{_MIN_GOPLS_MINOR}（需 gopls ≥ v0.14；建议 go install golang.org/x/tools/gopls@latest）",
 )
 return version_str, True, "ok"
def _probe_go -> tuple[str | None, bool, str]:
 """``go version`` 探针 → ``(version_str, ok, reason)``。
 失败时 ok=False + reason 含安装建议；不抛异常。
 """
 go_bin = shutil.which("go")
 if go_bin is None:
 return (
 None,
 False,
 "go binary 未在 PATH（建议安装 Go SDK ≥ 1.20：https://go.dev/dl/）",
 )
 try:
 result = subprocess.run(
 ["go", "version"],
 check=False,
 capture_output=True,
 text=True,
 timeout=_PROBE_TIMEOUT_SECONDS / 2,
 )
 except (OSError, subprocess.TimeoutExpired) as exc:
 return None, False, f"go version 调用失败: {exc}"
 output = (result.stdout + result.stderr).strip
 m = re.search(r"go(\d+)\.(\d+)", output)
 if m is None:
 return output or None, False, f"无法解析 go 版本输出: {output!r}"
 major, minor = int(m.group(1)), int(m.group(2))
 version_str = f"{major}.{minor}"
 # 提取完整版本
 vm = re.search(r"go(\d+\.\d+(?:\.\d+)?)", output)
 if vm:
 version_str = vm.group(1)
 if (major, minor) < (_MIN_GO_MAJOR, _MIN_GO_MINOR):
 return (
 version_str,
 False,
 f"Go {version_str} < {_MIN_GO_MAJOR}.{_MIN_GO_MINOR}（需 Go ≥ 1.20；建议升级 Go SDK）",
 )
 return version_str, True, "ok"
__all__ = ["GoCheckResult", "check_go_runtime"]
