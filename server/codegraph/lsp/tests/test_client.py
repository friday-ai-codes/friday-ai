"""Phase: FridayLanguageClient 单元测试。
测试策略（per ）：用 ``unittest.mock.AsyncMock`` 替换 pygls 的 4 个 async
方法（start_io / initialize_async / shutdown_async / workspace_symbol_async），
验证 lifecycle 顺序、超时归一、异常归一路径。
"""
from __future__ import annotations
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from lsprotocol import types as lsp
from codegraph.lsp.client import FridayLanguageClient, _build_client_capabilities
from codegraph.lsp.exceptions import LspStartupError, LspTimeoutError
def test_client_construct_default -> None:
 """默认构造成功，name / version 字段正确。"""
 client = FridayLanguageClient
 assert client.name == "friday-lsp-client"
 assert client.version == "0.1.0"
@pytest.mark.asyncio
async def test_start_calls_lifecycle_in_order -> None:
 """start 串行调 start_io → initialize_async → initialized。"""
 client = FridayLanguageClient
 call_order: list[str] =
 async def fake_start_io(cmd: str, *args: str, **kwargs: object) -> None:
 call_order.append("start_io")
 async def fake_initialize_async(params: lsp.InitializeParams) -> object:
 call_order.append("initialize_async")
 return MagicMock
 def fake_initialized(params: lsp.InitializedParams) -> None:
 call_order.append("initialized")
 with (
 patch.object(client, "start_io", side_effect=fake_start_io),
 patch.object(client, "initialize_async", side_effect=fake_initialize_async),
 patch.object(client, "initialized", side_effect=fake_initialized),
 ):
 await client.start(
 command=["echo-server", "--stdio"],
 workspace_root=Path("/tmp"),
 language_ids=["plaintext"],
 )
 assert call_order == ["start_io", "initialize_async", "initialized"]
@pytest.mark.asyncio
async def test_start_empty_command_raises_startup_error -> None:
 """空 command 立即 raise LspStartupError 含'不能为空'。"""
 client = FridayLanguageClient
 with pytest.raises(LspStartupError, match="不能为空"):
 await client.start(
 command=,
 workspace_root=Path("/tmp"),
 language_ids=["plaintext"],
 )
@pytest.mark.asyncio
async def test_start_timeout_raises_startup_error -> None:
 """start_io 超时归一为 LspStartupError，__cause__ 保留 TimeoutError。"""
 client = FridayLanguageClient
 async def hang(cmd: str, *args: str, **kwargs: object) -> None:
 await asyncio.sleep(10)
 with patch.object(client, "start_io", side_effect=hang):
 with pytest.raises(LspStartupError) as excinfo:
 await client.start(
 command=["echo-server"],
 workspace_root=Path("/tmp"),
 language_ids=["plaintext"],
 startup_timeout=0.05,
 )
 assert isinstance(excinfo.value.__cause__, asyncio.TimeoutError)
@pytest.mark.asyncio
async def test_request_workspace_symbol_timeout_raises_lsp_timeout_error -> None:
 """workspace/symbol 超时归一为 LspTimeoutError 含 query / timeout。"""
 client = FridayLanguageClient
 async def hang(params: lsp.WorkspaceSymbolParams) -> object:
 await asyncio.sleep(10)
 raise AssertionError("unreachable") # 走不到，仅满足 mypy 返回类型分析
 with patch.object(client, "workspace_symbol_async", side_effect=hang):
 with pytest.raises(LspTimeoutError) as excinfo:
 await client.request_workspace_symbol("foo", timeout=0.05)
 assert "foo" in str(excinfo.value)
 assert "0.05" in str(excinfo.value)
@pytest.mark.asyncio
async def test_stop_swallows_timeout -> None:
 """stop 即便 shutdown_async 超时也不 raise（log warning 即可）。"""
 client = FridayLanguageClient
 async def hang(params: object) -> None:
 await asyncio.sleep(10)
 with (
 patch.object(client, "shutdown_async", side_effect=hang),
 patch.object(client, "exit", new=MagicMock),
 ):
 # 不应抛任何异常
 await client.stop(timeout=0.05)
def test_build_client_capabilities_has_4_capabilities -> None:
 """_build_client_capabilities 返 ClientCapabilities，4 项 capability 非 None。"""
 caps = _build_client_capabilities
 assert isinstance(caps, lsp.ClientCapabilities)
 assert caps.text_document is not None
 assert caps.text_document.document_symbol is not None
 assert caps.text_document.references is not None
 assert caps.text_document.definition is not None
 assert caps.workspace is not None
 assert caps.workspace.symbol is not None
@pytest.mark.asyncio
async def test_start_oserror_raises_startup_error -> None:
 """subprocess spawn 触发 OSError 归一为 LspStartupError。"""
 client = FridayLanguageClient
 async def boom(cmd: str, *args: str, **kwargs: object) -> None:
 raise FileNotFoundError("no such file: echo-server")
 with patch.object(client, "start_io", side_effect=boom):
 with pytest.raises(LspStartupError) as excinfo:
 await client.start(
 command=["echo-server"],
 workspace_root=Path("/tmp"),
 language_ids=["plaintext"],
 )
 assert isinstance(excinfo.value.__cause__, FileNotFoundError)
# 显式让 mypy 知道 AsyncMock 用法
_ = AsyncMock
