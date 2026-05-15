"""Phase: CI 内 LSP server stub —— 纯 stdlib，不依赖项目模块（per / Pitfall P16）。
支持的 LSP method（per ）：
- 标准：``initialize`` / ``initialized`` / ``shutdown`` / ``exit``
- 抽取：``workspace/symbol``（空 query 返，非空返 1 个 stub symbol）
- 测试控制：``friday/crash``（os._exit(1) 模拟崩溃）/ ``friday/hang``（sleep 3600
 模拟超时）/ ``friday/echo``（返回 params 原样，用于通讯链路 sanity check）
设计严格约束：
- 仅 ``asyncio`` / ``json`` / ``os`` / ``sys`` 4 个 stdlib 依赖
- 严禁 import 任何 ``codegraph`` / ``friday`` / ``django`` / ``lsprotocol`` /
 ``pygls`` 模块（避免 DJANGO_SETTINGS_MODULE 等 side effect 污染 CI）
- 用 ``sys.executable echo_server.py`` 启动；stdin/stdout 走 Content-Length
 framed work item 协议
本模块在 LSP 测试 fixture 内由 supervisor.spawn subprocess 启动，是 CI 内零
外部 binary 依赖的 LSP server replacement。
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
from typing import Any
CONTENT_LENGTH_HEADER = b"Content-Length: "
_SERVER_STATE: dict[str, Any] = {"initialized": False, "shutdown_received": False}
async def _read_message(reader: asyncio.StreamReader) -> dict[str, Any] | None:
 """读一条 LSP 消息：解析 Content-Length header + 读 body + json.loads。
 返回 None 表示 EOF / 输入结束。
 """
 content_length: int | None = None
 while True:
 line = await reader.readline
 if not line:
 return None
 if line in (b"\r\n", b"\n"):
 break
 if line.startswith(CONTENT_LENGTH_HEADER):
 value = line[len(CONTENT_LENGTH_HEADER):].strip
 try:
 content_length = int(value)
 except ValueError:
 continue
 if content_length is None or content_length <= 0:
 return None
 body = await reader.readexactly(content_length)
 return json.loads(body.decode("utf-8"))
async def _write_message(writer: asyncio.StreamWriter, message: dict[str, Any]) -> None:
 """写一条 LSP 消息：Content-Length header + body + flush。"""
 body = json.dumps(message).encode("utf-8")
 header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
 writer.write(header)
 writer.write(body)
 await writer.drain
async def _handle_initialize(params: dict[str, Any] | None) -> dict[str, Any]:
 return {
 "capabilities": {
 "workspaceSymbolProvider": True,
 "documentSymbolProvider": True,
 "referencesProvider": True,
 "definitionProvider": True,
 },
 "serverInfo": {"name": "friday-echo-server", "version": "0.1.0"},
 }
async def _handle_initialized(params: dict[str, Any] | None) -> None:
 _SERVER_STATE["initialized"] = True
 return None
async def _handle_workspace_symbol(params: dict[str, Any] | None) -> list[dict[str, Any]]:
 query = (params or {}).get("query", "")
 if query == "":
 return
 return [
 {
 "name": f"stub_{query}",
 "kind": 12,
 "location": {
 "uri": "file:///x",
 "range": {
 "start": {"line": 0, "character": 0},
 "end": {"line": 0, "character": 0},
 },
 },
 }
 ]
async def _handle_friday_crash(params: dict[str, Any] | None) -> None:
 sys.stderr.write("crash requested by test\n")
 sys.stderr.flush
 os._exit(1)
async def _handle_friday_hang(params: dict[str, Any] | None) -> None:
 await asyncio.sleep(3600)
async def _handle_friday_echo(params: dict[str, Any] | None) -> dict[str, Any] | None:
 return params
async def _handle_shutdown(params: dict[str, Any] | None) -> None:
 _SERVER_STATE["shutdown_received"] = True
 return None
async def _handle_exit(params: dict[str, Any] | None) -> None:
 sys.exit(0)
_DISPATCH: dict[str, Any] = {
 "initialize": _handle_initialize,
 "initialized": _handle_initialized,
 "shutdown": _handle_shutdown,
 "exit": _handle_exit,
 "workspace/symbol": _handle_workspace_symbol,
 "friday/crash": _handle_friday_crash,
 "friday/hang": _handle_friday_hang,
 "friday/echo": _handle_friday_echo,
}
async def _main -> None:
 """主循环：connect stdin/stdout pipes → 读消息 → dispatch → 写 response。"""
 loop = asyncio.get_running_loop
 reader = asyncio.StreamReader
 protocol = asyncio.StreamReaderProtocol(reader)
 await loop.connect_read_pipe(lambda: protocol, sys.stdin)
 writer_transport, writer_protocol = await loop.connect_write_pipe(
 asyncio.streams.FlowControlMixin, sys.stdout
 )
 writer = asyncio.StreamWriter(writer_transport, writer_protocol, None, loop)
 while True:
 try:
 message = await _read_message(reader)
 except (asyncio.IncompleteReadError, ConnectionResetError):
 return
 if message is None:
 return
 method = message.get("method")
 msg_id = message.get("id")
 params = message.get("params")
 if not isinstance(method, str):
 continue
 handler = _DISPATCH.get(method)
 if handler is None:
 if msg_id is not None:
 await _write_message(
 writer,
 {
 "jsonrpc": "2.0",
 "id": msg_id,
 "error": {
 "code": -32601,
 "message": f"Method not found: {method}",
 },
 },
 )
 continue
 try:
 result = await handler(params)
 except SystemExit:
 return
 except Exception as exc: # noqa: BLE001
 if msg_id is not None:
 await _write_message(
 writer,
 {
 "jsonrpc": "2.0",
 "id": msg_id,
 "error": {"code": -32603, "message": str(exc)},
 },
 )
 continue
 if msg_id is not None:
 await _write_message(
 writer,
 {"jsonrpc": "2.0", "id": msg_id, "result": result},
 )
if __name__ == "__main__":
 try:
 asyncio.run(_main)
 except (KeyboardInterrupt, SystemExit):
 pass
