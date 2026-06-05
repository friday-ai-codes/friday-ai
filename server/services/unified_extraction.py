"""一次 AST 解析，双供 RAG（chunks）与 Graph（ExtractionBundle）。

implementation 第二阶段核心：对单个文件只解析一次 AST，同时产出：

- RAG 用的 ``CodeChunk`` 列表（符号驱动精细切片）；
- Graph 用的 ``ExtractionBundle``（symbols / imports / calls / endpoints）。

二者来自**同一次** codegraph 抽取（含 gopls / volar LSP 增强 + Vue SFC 拆分），
因此 chunk 与 codegraph ``Symbol`` 在行号 / 命名上完全同源——chunk 通过
``symbol_key`` = (file_path, name, start_line) 直接绑定到 ``Symbol``，取代
``SymbolChunkResolver`` 的行号 bisect 软对齐。

与 ``CodeParser._ast_aware_chunk`` 的分工：

- ``CodeParser`` 走纯 tree-sitter（``TreeSitterBackend``），不依赖 LSP，作为通用
  切片器 / fallback（markdown 等非图谱语言、LSP 不可用场景）。
- 本模块走 ``get_extractor`` 完整语言抽取器（LSP 增强），用于 indexer 索引主路径，
  让 RAG 与 Graph 真正"一套 AST"同源。
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import structlog

from services.code_chunk import CodeChunk, SymbolSpan
from services.symbol_chunker import build_chunks_from_spans, normalize_kind

if TYPE_CHECKING:
    from codegraph.extractors.base import ExtractionBundle

logger = structlog.get_logger(__name__)

__all__ = ["extract_chunks_and_graph", "spans_from_symbols"]


def spans_from_symbols(symbols: list) -> list[SymbolSpan]:
    """codegraph ``SymbolData`` 列表 → ``SymbolSpan``（带 ``symbol_key`` 绑定）。

    ``symbol_key`` = (file_path, name, start_line) 与 codegraph ``Symbol`` 的
    ``unique_together`` 对齐，供索引时把 chunk_id 回填到对应 ``Symbol``。
    """
    return [
        SymbolSpan(
            name=s.name,
            kind=normalize_kind(symbol_type=s.symbol_type),
            start_line=s.start_line,
            end_line=s.end_line,
            node_type=s.symbol_type.lower(),
            symbol_key=(s.file_path, s.name, s.start_line),
        )
        for s in symbols
    ]


def extract_chunks_and_graph(
    file_path: str,
    source: str,
    language: str,
    repository_id: str,
    *,
    file_hash: str | None = None,
    max_chars: int = 2000,
) -> tuple[list[CodeChunk], "ExtractionBundle"]:
    """一次解析双供：返回 ``(chunks, bundle)``。

    Args:
        file_path: 文件相对路径（写入 chunk 与 FileContext）。
        source: 源文件完整文本。
        language: 语言标识（python / go / typescript / tsx / vue / ...）。
        repository_id: 仓库 UUID（FileContext 用）。
        file_hash: 内容 hash（写入 ``CodeChunk.file_hash``）；None 则按 sha256 现算。
        max_chars: 单 chunk 字符上限（透传 symbol_chunker）。

    Returns:
        ``(chunks, bundle)``：

        - ``chunks``：符号驱动精细切片，每个符号 chunk 的 ``symbol_key`` 绑定到
          ``bundle.symbols`` 中同名同行的 ``SymbolData``。
        - ``bundle``：codegraph ``ExtractionBundle``（图谱四维）。

        语言无抽取器 / 抽取异常时：chunks 退回整文件 module 切分（不丢内容），
        bundle 为空（symbols/imports/calls/endpoints 均空），保证调用方鲁棒。
    """
    from codegraph.extractors.base import ExtractionBundle, FileContext

    resolved_hash = file_hash if file_hash is not None else hashlib.sha256(
        source.encode("utf-8")
    ).hexdigest()

    def _module_only() -> tuple[list[CodeChunk], "ExtractionBundle"]:
        fallback_chunks = build_chunks_from_spans(
            [], source, file_path=file_path, file_hash=resolved_hash,
            language=language, max_chars=max_chars,
        )
        return fallback_chunks, ExtractionBundle(file_path=file_path, language=language)

    try:
        from codegraph.extractors.registry import get_extractor
    except ImportError:
        return _module_only()

    extractor = get_extractor(language)
    if extractor is None:
        return _module_only()

    module_path = file_path.replace("/", ".").rsplit(".", 1)[0]
    ctx = FileContext(
        file_path=file_path,
        language=language,
        repository_id=repository_id,
        module_path=module_path,
    )
    try:
        bundle = extractor.extract(file_path, source, ctx)
    except Exception as exc:
        logger.warning(
            "unified_extract_failed",
            file_path=file_path,
            language=language,
            error=str(exc),
        )
        return _module_only()

    spans = spans_from_symbols(bundle.symbols)
    chunks = build_chunks_from_spans(
        spans,
        source,
        file_path=file_path,
        file_hash=resolved_hash,
        language=language,
        max_chars=max_chars,
    )
    return chunks, bundle
