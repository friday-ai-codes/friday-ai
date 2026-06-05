"""implementation: FridayLanguageClient —— pygls BaseLanguageClient 子类（thin wrapper）。

设计要点（per work item / work item / work item / work item / work item）：
- 复用 pygls v2.x 的 ``BaseLanguageClient``，**不**手写 work item framing
  / subprocess 管理 / cattrs 转换；transport 层踩坑全由 pygls 兜底。
- 5 个公开方法（start / stop / request_workspace_symbol / request_document_symbol
  / send_request_async）一律包 ``asyncio.wait_for``，超时归一为 ``LspTimeoutError``；
  启动失败归一为 ``LspStartupError``。
- ``_build_client_capabilities()`` 声明本 phase 关注的 4 个 capability
  （document_symbol / workspace symbol / references / definition），
  其他 capability（diagnostic / completion / hover 等）一律不申请，
  避免 LSP server 主动 push 撑爆 client buffer（per work item / Pitfall P9）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import structlog
from lsprotocol import types as lsp
from pygls.lsp.client import BaseLanguageClient

from codegraph.lsp.exceptions import LspStartupError, LspTimeoutError
from codegraph.lsp.protocol import path_to_uri

logger = structlog.get_logger(__name__)


_DEFAULT_STARTUP_TIMEOUT_SECONDS = 30.0
_DEFAULT_REQUEST_TIMEOUT_SECONDS = 10.0
_DEFAULT_STOP_TIMEOUT_SECONDS = 5.0


def _build_client_capabilities() -> lsp.ClientCapabilities:
    """构造 LSP client capability（per work item + implementation 补 implementation）。

    声明 document_symbol / workspace symbol / references / definition / implementation；
    其他全部不申请，避免 LSP server 主动 push。
    """
    return lsp.ClientCapabilities(
        text_document=lsp.TextDocumentClientCapabilities(
            document_symbol=lsp.DocumentSymbolClientCapabilities(),
            references=lsp.ReferenceClientCapabilities(),
            definition=lsp.DefinitionClientCapabilities(),
            implementation=lsp.ImplementationClientCapabilities(),
        ),
        workspace=lsp.WorkspaceClientCapabilities(
            symbol=lsp.WorkspaceSymbolClientCapabilities(),
        ),
    )


class FridayLanguageClient(BaseLanguageClient):
    """Friday 项目 LSP client thin subclass。

    封装 pygls ``BaseLanguageClient`` 的 lifecycle（start / initialize / initialized /
    shutdown / exit）+ 单次请求超时（``asyncio.wait_for``）+ 异常归一化
    （``LspStartupError`` / ``LspTimeoutError``）。

    本类 **不**实现 send_request 泛化方法；直接消费 pygls 提供的 typed async API
    （如 ``workspace_symbol_async``）。
    """

    def __init__(self) -> None:
        super().__init__(name="friday-lsp-client", version="0.1.0")

    async def start(
        self,
        command: list[str],
        workspace_root: Path,
        language_ids: list[str],
        initialization_options: dict[str, Any] | None = None,
        startup_timeout: float = _DEFAULT_STARTUP_TIMEOUT_SECONDS,
    ) -> None:
        """启动 LSP subprocess + LSP lifecycle（initialize + initialized）。

        失败路径全部归一为 ``LspStartupError``：
        - 空 command
        - subprocess spawn 失败（pygls 内部包装的 OSError 等）
        - initialize 超时（``asyncio.wait_for`` TimeoutError）

        Args:
            command: subprocess 启动命令，由 ``settings.LSP_SERVERS[name].command``
                提供（implementation / 267 子类填具体值）。
            workspace_root: LSP workspace 根目录（用于 root_uri / workspace_folders）。
            language_ids: 客户端声明的语言 id 列表（如 ``["vue", "typescript"]``）。
            initialization_options: server-specific initialization 参数。
            startup_timeout: ``initialize`` 请求超时（默认 30s）。
        """
        if not command:
            raise LspStartupError("command 不能为空（至少需要可执行文件路径）")

        try:
            cmd, *args = command
            await asyncio.wait_for(
                self.start_io(cmd, *args),
                timeout=startup_timeout,
            )
        except asyncio.TimeoutError as exc:
            raise LspStartupError(
                f"start_io 启动 subprocess 超时（command={command}, timeout={startup_timeout}s）"
            ) from exc
        except OSError as exc:
            raise LspStartupError(
                f"start_io 启动 subprocess 失败（command={command}）: {exc}"
            ) from exc
        except RuntimeError as exc:
            # pygls 在 server 启动后立即退出时 raise RuntimeError
            # （"Server process X exited with return code Y"）
            raise LspStartupError(
                f"subprocess 启动后立即退出（command={command}）: {exc}"
            ) from exc

        root_uri = path_to_uri(workspace_root)
        init_params = lsp.InitializeParams(
            process_id=None,
            root_uri=root_uri,
            capabilities=_build_client_capabilities(),
            workspace_folders=[
                lsp.WorkspaceFolder(uri=root_uri, name=workspace_root.name)
            ],
            initialization_options=initialization_options,
        )

        try:
            await asyncio.wait_for(
                self.initialize_async(init_params),
                timeout=startup_timeout,
            )
        except asyncio.TimeoutError as exc:
            raise LspStartupError(
                f"initialize 请求超时（command={command}, timeout={startup_timeout}s）"
            ) from exc
        except RuntimeError as exc:
            # pygls 在 initialize 期间 server 退出时 raise RuntimeError
            raise LspStartupError(
                f"initialize 期间 subprocess 退出（command={command}）: {exc}"
            ) from exc

        self.initialized(lsp.InitializedParams())
        logger.info(
            "lsp_client_started",
            command=command,
            workspace_root=str(workspace_root),
            language_ids=language_ids,
        )

    async def stop(self, timeout: float = _DEFAULT_STOP_TIMEOUT_SECONDS) -> None:
        """优雅关闭 LSP server（shutdown + exit）。

        任何异常都吞掉只 log warning，避免 atexit / supervisor.stop 路径抛出。
        """
        try:
            await asyncio.wait_for(self.shutdown_async(None), timeout=timeout)
        except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
            logger.warning(
                "lsp_client_shutdown_error",
                error_class=type(exc).__name__,
                error=str(exc),
            )

        try:
            self.exit(None)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "lsp_client_exit_error",
                error_class=type(exc).__name__,
                error=str(exc),
            )

    async def request_workspace_symbol(
        self,
        query: str,
        timeout: float = _DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> Any:
        """发起 ``workspace/symbol`` 请求；超时归一为 ``LspTimeoutError``。

        Returns:
            ``list[WorkspaceSymbol] | list[SymbolInformation] | None``——
            原样透传 pygls 返回结构，由上层 backend 转换为 SymbolData。
        """
        params = lsp.WorkspaceSymbolParams(query=query)
        try:
            return await asyncio.wait_for(
                self.workspace_symbol_async(params),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            raise LspTimeoutError(
                f"workspace/symbol(query={query!r}) 超时 {timeout}s"
            ) from exc

    # =========================================================================
    # implementation: VolarBackend 消费的 3 个 capability 方法（per work item / work item）
    # =========================================================================

    async def request_document_symbol(
        self,
        uri: str,
        timeout: float = _DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> Any:
        """发起 ``textDocument/documentSymbol`` 请求；超时归一为 ``LspTimeoutError``。

        Returns:
            ``list[DocumentSymbol] | list[SymbolInformation] | None``——
            volar 通常返 nested ``DocumentSymbol``；上层 backend 递归展平转 SymbolData。
        """
        params = lsp.DocumentSymbolParams(
            text_document=lsp.TextDocumentIdentifier(uri=uri),
        )
        try:
            return await asyncio.wait_for(
                self.text_document_document_symbol_async(params),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            raise LspTimeoutError(
                f"textDocument/documentSymbol({uri!r}) 超时 {timeout}s"
            ) from exc

    async def request_references(
        self,
        uri: str,
        position: lsp.Position,
        *,
        include_declaration: bool = False,
        timeout: float = _DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> Any:
        """发起 ``textDocument/references`` 请求；超时归一为 ``LspTimeoutError``。

        ``include_declaration=False`` 默认与 work item 跨文件 references 需求对齐
        （不返自身定义；上层只关心 caller 调用点）。
        """
        params = lsp.ReferenceParams(
            text_document=lsp.TextDocumentIdentifier(uri=uri),
            position=position,
            context=lsp.ReferenceContext(include_declaration=include_declaration),
        )
        try:
            return await asyncio.wait_for(
                self.text_document_references_async(params),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            raise LspTimeoutError(
                f"textDocument/references({uri!r}, line={position.line}) 超时 {timeout}s"
            ) from exc

    async def request_definition(
        self,
        uri: str,
        position: lsp.Position,
        *,
        timeout: float = _DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> Any:
        """发起 ``textDocument/definition`` 请求；超时归一为 ``LspTimeoutError``。

        Returns:
            ``Location | list[Location] | list[LocationLink] | None``——
            上层 helper ``_extract_first_location_path`` 处理三种返回形态。
        """
        params = lsp.DefinitionParams(
            text_document=lsp.TextDocumentIdentifier(uri=uri),
            position=position,
        )
        try:
            return await asyncio.wait_for(
                self.text_document_definition_async(params),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            raise LspTimeoutError(
                f"textDocument/definition({uri!r}, line={position.line}) 超时 {timeout}s"
            ) from exc

    async def request_implementation(
        self,
        uri: str,
        position: lsp.Position,
        *,
        timeout: float = _DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> Any:
        """发起 ``textDocument/implementation`` 请求；超时归一为 ``LspTimeoutError``。

        gopls 使用此 capability 返回 Go interface 的所有实现类型位置。
        implementation 新增（per work item / work item）。

        Returns:
            ``Location | list[Location] | list[LocationLink] | None``——
            上层 GoplsInterfaceExtractor 处理多种返回形态。
        """
        params = lsp.ImplementationParams(
            text_document=lsp.TextDocumentIdentifier(uri=uri),
            position=position,
        )
        try:
            return await asyncio.wait_for(
                self.text_document_implementation_async(params),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            raise LspTimeoutError(
                f"textDocument/implementation({uri!r}, line={position.line}) 超时 {timeout}s"
            ) from exc


__all__ = ["FridayLanguageClient"]
