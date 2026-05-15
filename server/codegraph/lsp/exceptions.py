"""Phase: LSP 子包业务异常体系（per ）。
5 类异常，``LspError`` 是兜底基类；调用方 ``try / except LspError`` 一行覆盖全部 4 子类。
- ``LspError``：所有 LSP 操作的基础异常。其他 4 个具体异常都继承自它，
 让 supervisor / backend 等上层调用方能用单一 except 子句兜底。
- ``LspStartupError``：subprocess 启动失败 / ``initialize`` 请求超时 / spawn 错误。
- ``LspTimeoutError``：单次 LSP 请求超时（``asyncio.wait_for`` 超时归一化）。
- ``LspUnhealthyError``：LSP 进程或 transport 不健康（stdio EOF / proc dead /
 background loop 未运行）。supervisor 据此转 UNHEALTHY 状态。
- ``LspDisabledError``：supervisor 已转 DISABLED（crash-loop 防护命中），后续
 调用全部立即返回，由 backend 走 tree-sitter fallback。
"""
from __future__ import annotations
class LspError(Exception):
 """LSP 操作的基础异常类。
 所有 ``Lsp*Error`` 都继承自此类；用 ``try / except LspError`` 即可
 一并捕获。LSP server 返回 error response（非超时、非崩溃）也归此类。
 """
class LspStartupError(LspError):
 """LSP server 启动失败。
 触发路径：
 - subprocess spawn 失败（命令不存在 / 权限错）
 - ``initialize`` 请求超时（``LSP_STARTUP_TIMEOUT_SECONDS`` 默认 30s）
 - subprocess 启动后 ``returncode`` 立即非 None（如 echo server 自杀）
 """
class LspTimeoutError(LspError):
 """LSP 单次请求超时。
 触发路径：``asyncio.wait_for`` 超时（per 三层超时）。
 """
class LspUnhealthyError(LspError):
 """LSP 进程或 transport 不健康。
 触发路径：
 - subprocess 已 dead（``returncode != None``）
 - stdio EOF / Content-Length 解析失败
 - ``services/background_runner.py`` 内 ``_BACKGROUND_LOOP`` 未运行
 （per / Pitfall P5）
 """
class LspDisabledError(LspError):
 """LSP supervisor 已转 DISABLED 状态。
 触发路径：crash-loop 防护命中（连续 ``max_restart_attempts=3`` 次重启失败，
 per ）。需要调用方显式调 ``supervisor.reset_disabled`` 才解禁。
 """
__all__ = [
 "LspError",
 "LspStartupError",
 "LspTimeoutError",
 "LspUnhealthyError",
 "LspDisabledError",
]
