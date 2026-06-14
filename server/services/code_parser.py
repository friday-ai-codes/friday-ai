"""Code parser service using Tree-sitter for AST-based code splitting."""

import hashlib
import os
import re
from collections.abc import Callable
from typing import Any

import structlog

from services.code_chunk import CodeChunk, SymbolSpan

logger = structlog.get_logger(__name__)

# File extension to language mapping
EXTENSION_TO_LANGUAGE = {
    ".go": "go",
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".vue": "vue",
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".html": "html",
    ".htm": "html",
    ".json": "json",
    ".md": "markdown",
    ".markdown": "markdown",
}

# Languages that support Tree-sitter parsing
TREESITTER_LANGUAGES = {"go", "python", "typescript", "javascript", "css", "html", "json"}

# CodeChunk / SymbolSpan 已抽到 services.code_chunk（避免与 symbol_chunker 循环导入），
# 由顶部 import 重新导出，保持 `from services.code_parser import CodeChunk` 既有调用方零改动。


def compute_file_hash(file_path: str) -> str:
    """Compute MD5 hash of a file."""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def get_language_from_extension(file_path: str) -> str | None:
    """Get language from file extension."""
    ext = os.path.splitext(file_path)[1].lower()
    return EXTENSION_TO_LANGUAGE.get(ext)


class CodeParser:
    """Parser for extracting code chunks from source files."""

    def __init__(
        self,
        chunk_lines: int = 40,
        chunk_overlap: int = 10,
        max_chars: int = 2000,
        chunking_mode: str = "fixed",
    ):
        self.chunk_lines = chunk_lines
        self.chunk_overlap = chunk_overlap
        self.max_chars = max_chars
        # 切分模式："ast_aware"（符号驱动精细切片，implementation）或 "fixed"（tree-sitter
        # 节点直取，向后兼容）。parse_file 未显式传 chunking_mode 时用此实例默认。
        self.chunking_mode = chunking_mode
        self._parsers: dict[str, Any] = {}

    def _get_tree_sitter_parser(self, language: str) -> Any | None:
        """Get or create Tree-sitter parser for language."""
        if language not in TREESITTER_LANGUAGES:
            return None

        if language in self._parsers:
            return self._parsers[language]

        try:
            import tree_sitter_css
            import tree_sitter_go
            import tree_sitter_html
            import tree_sitter_javascript
            import tree_sitter_json
            import tree_sitter_python
            from tree_sitter import Language, Parser

            lang_modules = {
                "go": tree_sitter_go,
                "python": tree_sitter_python,
                "javascript": tree_sitter_javascript,
                "typescript": tree_sitter_javascript,  # Use JS parser for TS
                "css": tree_sitter_css,
                "html": tree_sitter_html,
                "json": tree_sitter_json,
            }

            if language not in lang_modules:
                return None

            lang_module = lang_modules[language]
            ts_language = Language(lang_module.language())
            parser = Parser(ts_language)
            self._parsers[language] = parser
            return parser

        except ImportError as e:
            logger.warning("tree_sitter_import_failed", language=language, error=str(e))
            return None

    def parse_file(
        self, file_path: str, base_path: str = "", chunking_mode: str | None = None
    ) -> list[CodeChunk]:
        """Parse a file and return code chunks.

        Args:
            file_path: 源文件绝对路径。
            base_path: 基础路径（用于生成 relative_path）。
            chunking_mode: 切分策略。``None``（默认）→ 用实例 ``self.chunking_mode``；
                显式传 ``"fixed"`` / ``"ast_aware"`` 覆盖。"ast_aware" 为符号驱动精细
                切片（implementation），"fixed" 为 tree-sitter 节点直取（向后兼容）。
        """
        mode = chunking_mode if chunking_mode is not None else self.chunking_mode
        language = get_language_from_extension(file_path)
        if not language:
            return []

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            logger.error("file_read_failed", file_path=file_path, error=str(e))
            return []

        if not content.strip():
            return []

        file_hash = compute_file_hash(file_path)
        relative_path = os.path.relpath(file_path, base_path) if base_path else file_path

        # Route to appropriate parser
        if language == "vue":
            chunks = self._parse_vue(content, relative_path, file_hash)
        elif language == "markdown":
            chunks = self._parse_markdown(content, relative_path, file_hash)
        elif language in ("sass",):
            chunks = self._parse_fallback(content, relative_path, file_hash, language)
        else:
            # AST-aware chunking: 仅在 tree-sitter 语言中生效
            if mode == "ast_aware" and language in TREESITTER_LANGUAGES:
                chunks = self._ast_aware_chunk(content, relative_path, file_hash, language)
            else:
                if mode == "ast_aware":
                    logger.warning(
                        "ast_aware_unsupported_language",
                        file_path=relative_path,
                        language=language,
                        fallback="fixed",
                    )
                # Try Tree-sitter first, fallback to character-based
                chunks = self._parse_with_tree_sitter(content, relative_path, file_hash, language)
                if not chunks:
                    chunks = self._parse_fallback(content, relative_path, file_hash, language)

        # 注入文件级上下文增强信息
        if chunks:
            file_context = self._extract_file_context(content, language)
            for chunk in chunks:
                chunk.imports = file_context.get("imports", "")
                chunk.module_docstring = file_context.get("docstring", "")
            self._inject_sibling_signatures(chunks)

        return chunks

    def parse_file_dual(
        self, file_path: str, base_path: str = "", *, repository_id: str = ""
    ) -> tuple[list[CodeChunk], "Any | None"]:
        """一次解析双供：返回 ``(chunks, bundle)``（implementation single-parse）。

        对图谱支持的**非 Vue** 语言（python/go/typescript/tsx/javascript/html/css）走
        ``unified_extraction``——同一次 codegraph 抽取同时产 RAG ``chunks`` 与 Graph
        ``ExtractionBundle``，供 indexer 缓存给图谱轨复用，消除"每文件解析两次"。

        Vue / Markdown / 非图谱语言 / 非 ast_aware 模式：退回 ``parse_file``，``bundle=None``
        （图谱轨自行解析，保持既有行为）。chunks 注入文件级上下文与 ``parse_file`` 一致。
        """
        if self.chunking_mode != "ast_aware":
            return self.parse_file(file_path, base_path), None

        language = get_language_from_extension(file_path)
        if not language or language in ("vue", "markdown"):
            return self.parse_file(file_path, base_path), None

        try:
            from codegraph.extractors.registry import EXTRACTOR_REGISTRY
        except ImportError:
            return self.parse_file(file_path, base_path), None
        if language not in EXTRACTOR_REGISTRY:
            return self.parse_file(file_path, base_path), None

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            logger.error("file_read_failed", file_path=file_path, error=str(e))
            return [], None
        if not content.strip():
            return [], None

        file_hash = compute_file_hash(file_path)
        relative_path = os.path.relpath(file_path, base_path) if base_path else file_path

        from services.unified_extraction import extract_chunks_and_graph

        chunks, bundle = extract_chunks_and_graph(
            relative_path, content, language, repository_id, file_hash=file_hash
        )

        # 注入文件级上下文（imports/docstring/sibling）与 parse_file 一致，提升 embedding 质量
        if chunks:
            file_context = self._extract_file_context(content, language)
            for chunk in chunks:
                chunk.imports = file_context.get("imports", "")
                chunk.module_docstring = file_context.get("docstring", "")
            self._inject_sibling_signatures(chunks)

        return chunks, bundle

    def _parse_with_tree_sitter(
        self, content: str, file_path: str, file_hash: str, language: str
    ) -> list[CodeChunk]:
        """Parse using Tree-sitter AST."""
        parser = self._get_tree_sitter_parser(language)
        if not parser:
            return []

        try:
            tree = parser.parse(bytes(content, "utf-8"))
            root_node = tree.root_node

            chunks = []
            self._extract_nodes(root_node, content, file_path, file_hash, language, chunks)
            return chunks

        except Exception as e:
            logger.warning("tree_sitter_parse_failed", file_path=file_path, error=str(e))
            return []

    def _extract_nodes(
        self,
        node: Any,
        content: str,
        file_path: str,
        file_hash: str,
        language: str,
        chunks: list[CodeChunk],
    ) -> None:
        """Recursively extract significant AST nodes."""
        # Node types we want to extract as chunks
        significant_types = {
            "go": ["function_declaration", "method_declaration", "type_declaration"],
            "python": ["function_definition", "class_definition"],
            "javascript": ["function_declaration", "class_declaration", "arrow_function"],
            "typescript": ["function_declaration", "class_declaration", "arrow_function"],
            "css": ["rule_set", "media_statement"],
            "html": ["element"],
            "json": ["object", "array"],
        }

        target_types = significant_types.get(language, [])

        if node.type in target_types:
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            node_content = content[node.start_byte : node.end_byte]

            # Skip if too small
            if len(node_content.strip()) < 20:
                return

            # Truncate if too large
            if len(node_content) > self.max_chars:
                node_content = node_content[: self.max_chars] + "\n... (truncated)"

            context_header = f"File: {file_path} | Language: {language} | Type: {node.type}"

            chunks.append(
                CodeChunk(
                    content=node_content,
                    file_path=file_path,
                    file_hash=file_hash,
                    language=language,
                    start_line=start_line,
                    end_line=end_line,
                    node_type=node.type,
                    context_header=context_header,
                )
            )
        else:
            # Recurse into children
            for child in node.children:
                self._extract_nodes(child, content, file_path, file_hash, language, chunks)

    def _ast_aware_chunk(
        self, content: str, file_path: str, file_hash: str, language: str
    ) -> list[CodeChunk]:
        """AST-aware chunking：按符号边界切分（work item；implementation 重写）。

        复用 codegraph 的 tree-sitter 符号抽取（专用多语言 parser，含 TS
        interface/type、export/decorated 解包、递归遍历）得到符号边界 ``SymbolSpan``，
        再交给语言无关的 ``symbol_chunker.build_chunks_from_spans`` 统一切分
        （收敛合并 / 大符号按行不丢尾 / 模块级收尾）。

        替代旧实现的三处缺陷：① 只看 root 直接子节点（漏 export 包裹符号）；
        ② 借 JS parser 解析 TS（丢 interface/type）；③ 小符号合并过激（类被揉进函数组）。
        """
        from services.symbol_chunker import build_chunks_from_spans

        spans = self._extract_symbol_spans(content, file_path, language)
        return build_chunks_from_spans(
            spans,
            content,
            file_path=file_path,
            file_hash=file_hash,
            language=language,
            max_chars=self.max_chars,
        )

    def _extract_symbol_spans(
        self, content: str, file_path: str, language: str
    ) -> list[SymbolSpan]:
        """用 codegraph TreeSitterBackend 抽符号边界 → ``SymbolSpan``（纯 tree-sitter）。

        - ``.tsx`` 文件用 tsx grammar（JSX 语法）；其余 typescript 用 language_typescript。
        - 复用 codegraph 的 ``extract_symbols``：name / 类型 / 行号语义与图谱轨完全一致，
          为第二阶段 chunk ↔ Symbol 同源绑定打基础。
        - parser 不可用 / 语言不支持 / 解析失败 → 返回 ``[]``，由 symbol_chunker
          兜底为整文件 module 切分（不丢内容）。
        """
        from services.symbol_chunker import normalize_kind

        try:
            from codegraph.backends.protocols import TreeSitterBackend
            from codegraph.extractors.base import FileContext
        except ImportError:
            return []

        ts_lang = language
        if language == "typescript" and file_path.endswith(".tsx"):
            ts_lang = "tsx"

        try:
            backend = TreeSitterBackend(ts_lang)
            tree = backend.parse_file(file_path, content)
            ctx = FileContext(file_path=file_path, language=ts_lang, repository_id="")
            symbols = backend.extract_symbols(tree, content, ctx)
        except Exception as exc:
            logger.warning(
                "ast_aware_symbol_extract_failed",
                file_path=file_path,
                language=ts_lang,
                error=str(exc),
            )
            return []

        return [
            SymbolSpan(
                name=s.name,
                kind=normalize_kind(symbol_type=s.symbol_type),
                start_line=s.start_line,
                end_line=s.end_line,
                node_type=s.symbol_type.lower(),
            )
            for s in symbols
        ]

    def _parse_vue(self, content: str, file_path: str, file_hash: str) -> list[CodeChunk]:
        """解析 Vue SFC：``<script>`` 走精细符号切片，``<template>`` 整块。

        ``<script>`` 用 TypeScript 精细切片（与 ``.ts`` 同路径，符号级 chunk，含
        interface/type/export 解包），并把 chunk 行号按 script 块在 SFC 中的起始行
        偏移修正回真实行号；切不出符号时由 symbol_chunker 兜底整块。``<template>``
        作为单个 chunk（HTML 无函数语义，符号切分意义不大），同样修正行号偏移。
        """
        from services.symbol_chunker import build_chunks_from_spans

        chunks: list[CodeChunk] = []

        script_match = re.search(r"<script[^>]*>(.*?)</script>", content, re.DOTALL | re.IGNORECASE)
        if script_match:
            raw_script = script_match.group(1)
            script_content = raw_script.strip()
            if script_content:
                # script 块在 SFC 中的起始行偏移：块前完整行数 + 块内被 strip 掉的前导空行，
                # 保证符号 chunk 的行号映射回 SFC 真实行（供 Galaxy 定位 / 调用关系对齐）。
                base_offset = content[: script_match.start(1)].count("\n")
                lead_blank = len(raw_script) - len(raw_script.lstrip("\n"))
                line_offset = base_offset + lead_blank

                spans = self._extract_symbol_spans(script_content, file_path, "typescript")
                script_chunks = build_chunks_from_spans(
                    spans,
                    script_content,
                    file_path=file_path,
                    file_hash=file_hash,
                    language="vue",
                    max_chars=self.max_chars,
                )
                for c in script_chunks:
                    c.start_line += line_offset
                    c.end_line += line_offset
                    symbol_suffix = f" | Symbol: {c.parent_symbol}" if c.parent_symbol else ""
                    c.context_header = (
                        f"File: {file_path} | Language: vue (script) | "
                        f"Type: {c.node_type}{symbol_suffix}"
                    )
                chunks.extend(script_chunks)

        template_match = re.search(
            r"<template[^>]*>(.*?)</template>", content, re.DOTALL | re.IGNORECASE
        )
        if template_match:
            raw_template = template_match.group(1)
            template_content = raw_template.strip()
            if template_content and len(template_content) > 50:
                t_base = content[: template_match.start(1)].count("\n")
                t_lead = len(raw_template) - len(raw_template.lstrip("\n"))
                t_start = t_base + t_lead + 1
                chunks.append(
                    CodeChunk(
                        content=template_content[: self.max_chars],
                        file_path=file_path,
                        file_hash=file_hash,
                        language="vue",
                        start_line=t_start,
                        end_line=t_start + template_content.count("\n"),
                        node_type="template",
                        context_header=f"File: {file_path} | Language: vue (template)",
                    )
                )

        return chunks

    def _parse_markdown(self, content: str, file_path: str, file_hash: str) -> list[CodeChunk]:
        """Parse Markdown by splitting on headers."""
        chunks = []
        lines = content.split("\n")

        current_section = []
        current_header = ""
        start_line = 1

        for i, line in enumerate(lines, 1):
            if line.startswith("#"):
                # Save previous section
                if current_section:
                    section_content = "\n".join(current_section)
                    if len(section_content.strip()) > 30:
                        chunks.append(
                            CodeChunk(
                                content=section_content[: self.max_chars],
                                file_path=file_path,
                                file_hash=file_hash,
                                language="markdown",
                                start_line=start_line,
                                end_line=i - 1,
                                node_type="section",
                                context_header=f"File: {file_path} | Section: {current_header}",
                            )
                        )

                current_header = line.lstrip("#").strip()
                current_section = [line]
                start_line = i
            else:
                current_section.append(line)

        # Don't forget the last section
        if current_section:
            section_content = "\n".join(current_section)
            if len(section_content.strip()) > 30:
                chunks.append(
                    CodeChunk(
                        content=section_content[: self.max_chars],
                        file_path=file_path,
                        file_hash=file_hash,
                        language="markdown",
                        start_line=start_line,
                        end_line=len(lines),
                        node_type="section",
                        context_header=f"File: {file_path} | Section: {current_header}",
                    )
                )

        return chunks

    def _parse_fallback(
        self, content: str, file_path: str, file_hash: str, language: str
    ) -> list[CodeChunk]:
        """Fallback character-based splitting."""
        chunks = []
        lines = content.split("\n")
        total_lines = len(lines)

        i = 0
        while i < total_lines:
            end_idx = min(i + self.chunk_lines, total_lines)
            chunk_lines = lines[i:end_idx]
            chunk_content = "\n".join(chunk_lines)

            if len(chunk_content.strip()) > 20:
                chunks.append(
                    CodeChunk(
                        content=chunk_content[: self.max_chars],
                        file_path=file_path,
                        file_hash=file_hash,
                        language=language,
                        start_line=i + 1,
                        end_line=end_idx,
                        node_type="block",
                        context_header=f"File: {file_path} | Language: {language}",
                    )
                )

            i += self.chunk_lines - self.chunk_overlap

        return chunks

    def _extract_file_context(self, content: str, language: str) -> dict[str, str]:
        """提取文件级上下文信息，用于增强 embedding 质量。"""
        result: dict[str, str] = {}

        if language in ("python", "typescript", "javascript", "go", "vue"):
            imports = self._extract_imports(content, language)
            if imports:
                result["imports"] = imports

        if language == "python":
            docstring = self._extract_module_docstring(content)
            if docstring:
                result["docstring"] = docstring
        elif language in ("typescript", "javascript", "vue"):
            comment = self._extract_file_header_comment(content)
            if comment:
                result["docstring"] = comment

        return result

    def _extract_imports(self, content: str, language: str) -> str:
        """提取文件的 import 语句，最多 500 字符。"""
        lines = content.split("\n")
        import_lines: list[str] = []

        if language == "python":
            for line in lines:
                stripped = line.strip()
                if stripped.startswith(("import ", "from ")):
                    import_lines.append(stripped)
                elif stripped and not stripped.startswith(("#", '"""', "'''", '"', "'")):
                    # 跳过空行和注释，遇到非 import 代码停止
                    if import_lines:
                        break
        elif language in ("typescript", "javascript", "vue"):
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("import ") or "require(" in stripped:
                    import_lines.append(stripped)
                elif stripped and not stripped.startswith(("//", "/*", "*", "'")):
                    if import_lines:
                        break
        elif language == "go":
            in_import_block = False
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("import ("):
                    in_import_block = True
                    import_lines.append(stripped)
                elif in_import_block:
                    import_lines.append(stripped)
                    if stripped == ")":
                        in_import_block = False
                        break
                elif stripped.startswith("import "):
                    import_lines.append(stripped)

        result = "\n".join(import_lines)
        return result[:500]

    def _extract_module_docstring(self, content: str) -> str:
        """提取 Python 模块级 docstring，最多 200 字符。"""
        # 匹配文件开头（跳过注释和空行后）的三引号字符串
        match = re.match(
            r'^(?:\s*#[^\n]*\n)*\s*("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\')',
            content,
        )
        if match:
            docstring = match.group(1).strip("\"'").strip()
            return docstring[:200]
        return ""

    def _extract_file_header_comment(self, content: str) -> str:
        """提取 JS/TS 文件头部的多行注释或 JSDoc，最多 200 字符。"""
        match = re.match(r"^\s*/\*\*?([\s\S]*?)\*/", content)
        if match:
            comment = match.group(1).strip()
            # 清理每行开头的 * 号
            cleaned = "\n".join(line.lstrip(" *") for line in comment.split("\n")).strip()
            return cleaned[:200]
        return ""

    def _inject_sibling_signatures(self, chunks: list[CodeChunk]) -> None:
        """为同文件的 chunks 注入相邻函数/类签名列表。"""
        # 按 file_path 分组
        file_chunks: dict[str, list[CodeChunk]] = {}
        for chunk in chunks:
            file_chunks.setdefault(chunk.file_path, []).append(chunk)

        for file_path, group in file_chunks.items():
            if len(group) <= 1:
                continue

            # 提取每个 chunk 的签名（第一行）
            signatures: list[str] = []
            for chunk in group:
                first_line = chunk.content.split("\n", 1)[0].strip()
                if first_line:
                    signatures.append(first_line)

            # 为每个 chunk 注入其他 chunk 的签名
            for i, chunk in enumerate(group):
                siblings = [s for j, s in enumerate(signatures) if j != i]
                if siblings:
                    chunk.sibling_signatures = "; ".join(siblings)[:300]


def scan_directory(
    directory: str,
    exclude_patterns: list[str] | None = None,
    is_excluded_rel: Callable[[str], bool] | None = None,
) -> list[str]:
    """扫描目录，返回受支持源文件的绝对路径列表。

    过滤口径（如实描述，**不应用 .gitignore**，PF-04 修正）：
    1. ``exclude_patterns``：按**目录名**粗粒度裁剪（默认 node_modules/.git/... 等）。
    2. 扩展名白名单：仅保留 ``EXTENSION_TO_LANGUAGE`` 识别的源文件。
    3. ``is_excluded_rel``（可选）：相对 ``directory`` 根的 **POSIX 路径**级排除判定，
       由调用方注入（通常为 ``services.exclusion`` 单一匹配器的 ``is_excluded``，
       保持纯函数 + 注入以避免循环导入）。命中即跳过；同时用于目录级提前剪枝。

    fail-closed：``is_excluded_rel`` 判定抛异常时，视为命中（跳过该文件 / 剪掉该目录），
    绝不因匹配器异常而把可能敏感的内容放进索引（T-22-07）。

    Args:
        directory: 待扫描目录（仓库根）。
        exclude_patterns: 目录名黑名单；``None`` 时用内置默认。
        is_excluded_rel: 可选相对路径排除回调；``None`` 时与历史行为字节等价（向后兼容）。
    """
    if exclude_patterns is None:
        exclude_patterns = [
            "node_modules",
            ".git",
            "__pycache__",
            ".venv",
            "venv",
            "dist",
            "build",
            ".next",
            ".nuxt",
        ]

    def _rel_posix(abs_path: str) -> str:
        return os.path.relpath(abs_path, directory).replace(os.sep, "/")

    files = []
    for root, dirs, filenames in os.walk(directory):
        # 目录名粗粒度裁剪（现状）+ 可选相对路径级排除提前剪枝（fail-closed）
        kept_dirs: list[str] = []
        for d in dirs:
            if d in exclude_patterns:
                continue
            if is_excluded_rel is not None:
                rel_dir = _rel_posix(os.path.join(root, d))
                try:
                    if is_excluded_rel(rel_dir):
                        continue
                except Exception:  # noqa: BLE001 — 判定异常 fail-closed：剪掉该子树
                    continue
            kept_dirs.append(d)
        dirs[:] = kept_dirs

        for filename in filenames:
            file_path = os.path.join(root, filename)
            language = get_language_from_extension(file_path)
            if not language:
                continue
            if is_excluded_rel is not None:
                try:
                    if is_excluded_rel(_rel_posix(file_path)):
                        continue
                except Exception:  # noqa: BLE001 — 判定异常 fail-closed：跳过该文件
                    continue
            files.append(file_path)

    return files
