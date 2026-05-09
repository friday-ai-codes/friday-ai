"""Code parser service using Tree-sitter for AST-based code splitting."""
import hashlib
import os
import re
from dataclasses import dataclass
from typing import Any
import structlog
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
@dataclass
class CodeChunk:
 """Represents a chunk of code for indexing."""
 content: str
 file_path: str
 file_hash: str
 language: str
 start_line: int
 end_line: int
 node_type: str # function, class, rule, etc.
 context_header: str # For embedding enrichment
 # 上下文增强字段（用于提升 embedding 质量，不存入 Qdrant payload）
 imports: str = "" # 文件级 import 语句
 module_docstring: str = "" # 模块级 docstring/注释
 sibling_signatures: str = "" # 同文件其他函数/类签名
 parent_symbol: str | None = None # AST-aware 模式下标记 chunk 所属的父符号名
def compute_file_hash(file_path: str) -> str:
 """Compute MD5 hash of a file."""
 hash_md5 = hashlib.md5
 with open(file_path, "rb") as f:
 for chunk in iter(lambda: f.read(4096), b""):
 hash_md5.update(chunk)
 return hash_md5.hexdigest
def get_language_from_extension(file_path: str) -> str | None:
 """Get language from file extension."""
 ext = os.path.splitext(file_path)[1].lower
 return EXTENSION_TO_LANGUAGE.get(ext)
class CodeParser:
 """Parser for extracting code chunks from source files."""
 def __init__(self, chunk_lines: int = 40, chunk_overlap: int = 10, max_chars: int = 2000):
 self.chunk_lines = chunk_lines
 self.chunk_overlap = chunk_overlap
 self.max_chars = max_chars
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
 "typescript": tree_sitter_javascript, # Use JS parser for TS
 "css": tree_sitter_css,
 "html": tree_sitter_html,
 "json": tree_sitter_json,
 }
 if language not in lang_modules:
 return None
 lang_module = lang_modules[language]
 ts_language = Language(lang_module.language)
 parser = Parser(ts_language)
 self._parsers[language] = parser
 return parser
 except ImportError as e:
 logger.warning("tree_sitter_import_failed", language=language, error=str(e))
 return None
 def parse_file(self, file_path: str, base_path: str = "", chunking_mode: str = "fixed") -> list[CodeChunk]:
 """Parse a file and return code chunks.
 Args:
 file_path: 源文件绝对路径。
 base_path: 基础路径（用于生成 relative_path）。
 chunking_mode: 切分策略。"fixed"（默认，固定行数）或 "ast_aware"（AST 边界切分，）。
 """
 language = get_language_from_extension(file_path)
 if not language:
 return
 try:
 with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
 content = f.read
 except Exception as e:
 logger.error("file_read_failed", file_path=file_path, error=str(e))
 return
 if not content.strip:
 return
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
 if chunking_mode == "ast_aware" and language in TREESITTER_LANGUAGES:
 chunks = self._ast_aware_chunk(content, relative_path, file_hash, language)
 else:
 if chunking_mode == "ast_aware":
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
 def _parse_with_tree_sitter(
 self, content: str, file_path: str, file_hash: str, language: str
 ) -> list[CodeChunk]:
 """Parse using Tree-sitter AST."""
 parser = self._get_tree_sitter_parser(language)
 if not parser:
 return
 try:
 tree = parser.parse(bytes(content, "utf-8"))
 root_node = tree.root_node
 chunks =
 self._extract_nodes(root_node, content, file_path, file_hash, language, chunks)
 return chunks
 except Exception as e:
 logger.warning("tree_sitter_parse_failed", file_path=file_path, error=str(e))
 return
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
 target_types = significant_types.get(language, )
 if node.type in target_types:
 start_line = node.start_point[0] + 1
 end_line = node.end_point[0] + 1
 node_content = content[node.start_byte: node.end_byte]
 # Skip if too small
 if len(node_content.strip) < 20:
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
 """AST-aware chunking: 按函数/类定义边界切分，替代固定行数策略。
 算法四阶段：
 1. 符号提取 —— 收集所有顶级函数/类定义
 2. 小符号合并 —— 连续 < min_lines 行的小定义合并为一个 chunk
 3. 大符号截断 —— > max_chars 的符号在内部子块边界二次切分
 4. 模块级收尾 —— 未被符号覆盖的代码作为 module-level chunk
 """
 parser = self._get_tree_sitter_parser(language)
 if not parser:
 return
 try:
 tree = parser.parse(bytes(content, "utf-8"))
 except Exception as e:
 logger.warning("ast_aware_parse_failed", file_path=file_path, error=str(e))
 return
 root_node = tree.root_node
 # === 阶段 1: 收集顶层符号 ===
 # 只用 significant_types 中定义的语言节点类型
 significant_types = {
 "go": ["function_declaration", "method_declaration", "type_declaration"],
 "python": ["function_definition", "class_definition"],
 "javascript": ["function_declaration", "class_declaration", "arrow_function"],
 "typescript": ["function_declaration", "class_declaration", "arrow_function"],
 "css": ["rule_set", "media_statement"],
 "html": ["element"],
 "json": ["object", "array"],
 }
 target_types = significant_types.get(language, )
 if not target_types:
 return
 # 收集所有匹配的顶层符号（仅 direct children of root_node，不递归到嵌套符号）
 symbols: list[dict[str, Any]] =
 for child in root_node.children:
 if child.type in target_types:
 node_content = content[child.start_byte:child.end_byte]
 node_text = node_content.strip
 # 跳过极小节点（空函数体等）
 if len(node_text) < 20:
 continue
 symbols.append({
 "node": child,
 "content": node_content,
 "start_line": child.start_point[0] + 1,
 "end_line": child.end_point[0] + 1,
 "node_type": child.type,
 "name": self._extract_symbol_name(child),
 })
 # === 阶段 2: 小符号合并（: 连续 < 10 行的相邻定义并入同一 chunk）===
 MIN_LINES = 10
 merged: list[dict[str, Any]] =
 i = 0
 while i < len(symbols):
 current = symbols[i]
 group = [current]
 j = i + 1
 # 向前聚合：后续符号如果与当前组最后一个在行号上相邻且 < MIN_LINES 行
 while j < len(symbols):
 next_sym = symbols[j]
 # 相邻：下一个符号的起始行 == 当前组最后一个符号的结束行 + 1（或更近，处理空行）
 last_end = group[-1]["end_line"]
 if next_sym["start_line"] <= last_end + 1:
 group.append(next_sym)
 j += 1
 continue
 # 小符号合并条件：当前组最后一个符号 < MIN_LINES 行，且与下一个符号紧邻
 symbol_text = content[group[-1]["node"].start_byte:group[-1]["node"].end_byte]
 symbol_line_count = group[-1]["end_line"] - group[-1]["start_line"] + 1
 gap = next_sym["start_line"] - last_end
 if symbol_line_count < MIN_LINES and gap <= 2:
 group.append(next_sym)
 j += 1
 else:
 break
 if len(group) == 1:
 # 单符号：保持独立
 merged.append(current)
 else:
 # 合并组：创建一个合并的 chunk
 first = group[0]
 last = group[-1]
 merged_content = content[first["node"].start_byte:last["node"].end_byte]
 names = [g["name"] for g in group if g["name"]]
 merged.append({
 "content": merged_content,
 "start_line": first["start_line"],
 "end_line": last["end_line"],
 "node_type": "merged_group",
 "name": "; ".join(names) if names else None,
 "is_merged": True,
 "sub_names": names,
 })
 i = j
 # === 阶段 3: 大符号截断（: > max_chars 在内部子块边界二次切分）===
 SUB_BLOCK_TYPES = {"if_statement", "for_statement", "while_statement",
 "try_statement", "with_statement", "except_clause", "elif_clause"}
 raw_chunks: list[CodeChunk] =
 for sym in merged:
 sym_content = sym["content"]
 if len(sym_content) <= self.max_chars:
 # 无截断
 context_header = (
 f"File: {file_path} | Language: {language} | Type: {sym['node_type']}"
 )
 raw_chunks.append(CodeChunk(
 content=sym_content,
 file_path=file_path,
 file_hash=file_hash,
 language=language,
 start_line=sym["start_line"],
 end_line=sym["end_line"],
 node_type=sym["node_type"],
 context_header=context_header,
 parent_symbol=sym.get("name"),
 ))
 else:
 # 大符号需要二次切分
 node = sym.get("node")
 if node and not sym.get("is_merged"):
 sub_chunks = self._split_large_symbol(
 content, node, file_path, file_hash, language,
 sym["name"], SUB_BLOCK_TYPES
 )
 raw_chunks.extend(sub_chunks)
 else:
 # 合并组或无法获取 node 的大符号：简单截断
 truncated = sym_content[:self.max_chars] + "\n... (truncated)"
 context_header = (
 f"File: {file_path} | Language: {language} | Type: {sym['node_type']}"
 )
 raw_chunks.append(CodeChunk(
 content=truncated,
 file_path=file_path,
 file_hash=file_hash,
 language=language,
 start_line=sym["start_line"],
 end_line=sym["end_line"],
 node_type=sym["node_type"],
 context_header=context_header,
 parent_symbol=sym.get("name"),
 ))
 # === 阶段 4: module-level chunk（ 收尾）===
 module_chunk = self._extract_module_level_chunk(
 content, symbols, file_path, file_hash, language
 )
 if module_chunk:
 raw_chunks.append(module_chunk)
 return raw_chunks
 def _extract_symbol_name(self, node: Any) -> str | None:
 """从 tree-sitter 函数/类节点提取符号名。"""
 name_node = node.child_by_field_name("name")
 if name_node is not None:
 text = name_node.text
 if isinstance(text, bytes):
 return text.decode("utf-8")
 return text
 return None
 def _split_large_symbol(
 self,
 content: str,
 node: Any,
 file_path: str,
 file_hash: str,
 language: str,
 parent_name: str | None,
 sub_block_types: set[str],
 ) -> list[CodeChunk]:
 """大符号二次切分：在内部子块（if/for/while/try/with）边界切分。
 策略：
 1. 收集 node 的直接子节点中的子块
 2. 每个子块成为一个独立 chunk（内容为子块函数）
 3. 子块之间的代码 + 符号开头（签名/docstring）作为 'preamble' chunk
 4. 如果子块之后还有尾代码，作为 'trailing' chunk
 """
 chunks: list[CodeChunk] =
 # 符号的完整函数
 full_start_line = node.start_point[0] + 1
 full_content = content[node.start_byte:node.end_byte]
 # 收集子块
 sub_blocks: list[dict[str, Any]] =
 self._collect_sub_blocks(node, content, sub_block_types, sub_blocks)
 if not sub_blocks or len(sub_blocks) <= 1:
 # 无足够子块可切分：返回截断的整个符号
 truncated = full_content[:self.max_chars] + "\n... (truncated)"
 context_header = (
 f"File: {file_path} | Language: {language} | "
 f"Type: {node.type} | Symbol: {parent_name or 'unknown'}"
 )
 chunks.append(CodeChunk(
 content=truncated,
 file_path=file_path,
 file_hash=file_hash,
 language=language,
 start_line=full_start_line,
 end_line=node.end_point[0] + 1,
 node_type=node.type,
 context_header=context_header,
 parent_symbol=parent_name,
 ))
 return chunks
 # Preamble: 从符号开头到第一个子块之前
 first_block = sub_blocks[0]
 preamble_end_byte = first_block["node"].start_byte
 if preamble_end_byte > node.start_byte:
 preamble = content[node.start_byte:preamble_end_byte].rstrip
 if len(preamble.strip) >= 20:
 context_header = (
 f"File: {file_path} | Language: {language} | "
 f"Type: {node.type} | Symbol: {parent_name or 'unknown'} | Part: preamble"
 )
 chunks.append(CodeChunk(
 content=preamble,
 file_path=file_path,
 file_hash=file_hash,
 language=language,
 start_line=node.start_point[0] + 1,
 end_line=first_block["node"].start_point[0] + 1,
 node_type=node.type,
 context_header=context_header,
 parent_symbol=parent_name,
 ))
 # 每个子块作为一个 chunk
 for i, block in enumerate(sub_blocks):
 block_content = content[block["node"].start_byte:block["node"].end_byte]
 block_start_line = block["node"].start_point[0] + 1
 block_end_line = block["node"].end_point[0] + 1
 block_type = block["node"].type
 # 子块也可能很大——递归截断
 if len(block_content) > self.max_chars:
 block_content = block_content[:self.max_chars] + "\n... (truncated)"
 context_header = (
 f"File: {file_path} | Language: {language} | "
 f"Type: {node.type} | Symbol: {parent_name or 'unknown'} | "
 f"Sub: {block_type}"
 )
 chunks.append(CodeChunk(
 content=block_content,
 file_path=file_path,
 file_hash=file_hash,
 language=language,
 start_line=block_start_line,
 end_line=block_end_line,
 node_type=f"{node.type}:{block_type}",
 context_header=context_header,
 parent_symbol=parent_name,
 ))
 # Trailing: 最后一个子块之后的代码
 last_block = sub_blocks[-1]
 trailing_start_byte = last_block["node"].end_byte
 if trailing_start_byte < node.end_byte:
 trailing = content[trailing_start_byte:node.end_byte].rstrip
 if len(trailing.strip) >= 20:
 context_header = (
 f"File: {file_path} | Language: {language} | "
 f"Type: {node.type} | Symbol: {parent_name or 'unknown'} | Part: trailing"
 )
 chunks.append(CodeChunk(
 content=trailing,
 file_path=file_path,
 file_hash=file_hash,
 language=language,
 start_line=last_block["node"].end_point[0] + 1,
 end_line=node.end_point[0] + 1,
 node_type=node.type,
 context_header=context_header,
 parent_symbol=parent_name,
 ))
 return chunks
 def _collect_sub_blocks(
 self,
 node: Any,
 content: str,
 sub_block_types: set[str],
 result: list[dict[str, Any]],
 ) -> None:
 """递归收集 node 的直接子节点中的子块（if/for/while/try/with）。"""
 for child in node.children:
 if child.type in sub_block_types:
 result.append({"node": child})
 # 递归子节点（不递归到嵌套函数/类定义内——它们有独立 chunk）
 if child.type not in {"function_definition", "class_definition",
 "function_declaration", "method_declaration",
 "type_declaration", "class_declaration"}:
 self._collect_sub_blocks(child, content, sub_block_types, result)
 def _extract_module_level_chunk(
 self,
 content: str,
 symbols: list[dict[str, Any]],
 file_path: str,
 file_hash: str,
 language: str,
 ) -> CodeChunk | None:
 """提取未被任何符号覆盖的模块级代码（imports + 常量 + module docstring）。
 策略：收集所有符号的字节/行号范围，取未被覆盖的行段，
 合并为 module-level chunk。
 """
 if not symbols:
 # 无符号：整个文件作为 module-level chunk
 truncated = content[:self.max_chars]
 context_header = f"File: {file_path} | Language: {language} | Type: module"
 return CodeChunk(
 content=truncated if len(content) > self.max_chars else content,
 file_path=file_path,
 file_hash=file_hash,
 language=language,
 start_line=1,
 end_line=content.count("\n") + 1,
 node_type="module",
 context_header=context_header,
 parent_symbol=None,
 )
 # 计算符号覆盖的行段
 covered_lines: set[int] = set
 for sym in symbols:
 for line in range(sym["start_line"], sym["end_line"] + 1):
 covered_lines.add(line)
 total_lines = content.count("\n") + 1
 uncovered_ranges: list[tuple[int, int]] =
 start = 1
 while start <= total_lines:
 if start not in covered_lines:
 end = start
 while end + 1 <= total_lines and (end + 1) not in covered_lines:
 end += 1
 uncovered_ranges.append((start, end))
 start = end + 1
 else:
 start += 1
 if not uncovered_ranges:
 return None
 # 拼接未覆盖的行
 lines = content.split("\n")
 module_parts: list[str] =
 for range_start, range_end in uncovered_ranges:
 for line_idx in range(range_start - 1, range_end):
 if line_idx < len(lines):
 module_parts.append(lines[line_idx])
 module_content = "\n".join(module_parts)
 # 跳过纯空白/注释的 module level
 stripped = "\n".join(
 line for line in module_content.split("\n")
 if line.strip and not line.strip.startswith(("#", "//"))
 ).strip
 if not stripped or len(stripped) < 20:
 return None
 # 截断超大 module-level chunk
 if len(module_content) > self.max_chars:
 module_content = module_content[:self.max_chars] + "\n... (truncated)"
 context_header = f"File: {file_path} | Language: {language} | Type: module"
 return CodeChunk(
 content=module_content,
 file_path=file_path,
 file_hash=file_hash,
 language=language,
 start_line=uncovered_ranges[0][0] if uncovered_ranges else 1,
 end_line=uncovered_ranges[-1][1] if uncovered_ranges else total_lines,
 node_type="module",
 context_header=context_header,
 parent_symbol=None,
 )
 def _parse_vue(self, content: str, file_path: str, file_hash: str) -> list[CodeChunk]:
 """Parse Vue SFC files by separating script and template."""
 chunks =
 # Extract script content
 script_match = re.search(r"<script[^>]*>(.*?)</script>", content, re.DOTALL | re.IGNORECASE)
 if script_match:
 script_content = script_match.group(1).strip
 if script_content:
 # Parse as TypeScript/JavaScript
 script_chunks = self._parse_with_tree_sitter(
 script_content, file_path, file_hash, "typescript"
 )
 if script_chunks:
 for chunk in script_chunks:
 chunk.language = "vue"
 chunk.context_header = f"File: {file_path} | Language: vue (script)"
 chunks.extend(script_chunks)
 else:
 # Fallback: treat entire script as one chunk
 chunks.append(
 CodeChunk(
 content=script_content[: self.max_chars],
 file_path=file_path,
 file_hash=file_hash,
 language="vue",
 start_line=1,
 end_line=script_content.count("\n") + 1,
 node_type="script",
 context_header=f"File: {file_path} | Language: vue (script)",
 )
 )
 # Extract template content
 template_match = re.search(
 r"<template[^>]*>(.*?)</template>", content, re.DOTALL | re.IGNORECASE
 )
 if template_match:
 template_content = template_match.group(1).strip
 if template_content and len(template_content) > 50:
 chunks.append(
 CodeChunk(
 content=template_content[: self.max_chars],
 file_path=file_path,
 file_hash=file_hash,
 language="vue",
 start_line=1,
 end_line=template_content.count("\n") + 1,
 node_type="template",
 context_header=f"File: {file_path} | Language: vue (template)",
 )
 )
 return chunks
 def _parse_markdown(self, content: str, file_path: str, file_hash: str) -> list[CodeChunk]:
 """Parse Markdown by splitting on headers."""
 chunks =
 lines = content.split("\n")
 current_section =
 current_header = ""
 start_line = 1
 for i, line in enumerate(lines, 1):
 if line.startswith("#"):
 # Save previous section
 if current_section:
 section_content = "\n".join(current_section)
 if len(section_content.strip) > 30:
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
 current_header = line.lstrip("#").strip
 current_section = [line]
 start_line = i
 else:
 current_section.append(line)
 # Don't forget the last section
 if current_section:
 section_content = "\n".join(current_section)
 if len(section_content.strip) > 30:
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
 chunks =
 lines = content.split("\n")
 total_lines = len(lines)
 i = 0
 while i < total_lines:
 end_idx = min(i + self.chunk_lines, total_lines)
 chunk_lines = lines[i:end_idx]
 chunk_content = "\n".join(chunk_lines)
 if len(chunk_content.strip) > 20:
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
 import_lines: list[str] =
 if language == "python":
 for line in lines:
 stripped = line.strip
 if stripped.startswith(("import ", "from ")):
 import_lines.append(stripped)
 elif stripped and not stripped.startswith(("#", '"""', "'''", '"', "'")):
 # 跳过空行和注释，遇到非 import 代码停止
 if import_lines:
 break
 elif language in ("typescript", "javascript", "vue"):
 for line in lines:
 stripped = line.strip
 if stripped.startswith("import ") or "require(" in stripped:
 import_lines.append(stripped)
 elif stripped and not stripped.startswith(("//", "/*", "*", "'")):
 if import_lines:
 break
 elif language == "go":
 in_import_block = False
 for line in lines:
 stripped = line.strip
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
 docstring = match.group(1).strip("\"'").strip
 return docstring[:200]
 return ""
 def _extract_file_header_comment(self, content: str) -> str:
 """提取 JS/TS 文件头部的多行注释或 JSDoc，最多 200 字符。"""
 match = re.match(r"^\s*/\*\*?([\s\S]*?)\*/", content)
 if match:
 comment = match.group(1).strip
 # 清理每行开头的 * 号
 cleaned = "\n".join(
 line.lstrip(" *") for line in comment.split("\n")
 ).strip
 return cleaned[:200]
 return ""
 def _inject_sibling_signatures(self, chunks: list[CodeChunk]) -> None:
 """为同文件的 chunks 注入相邻函数/类签名列表。"""
 # 按 file_path 分组
 file_chunks: dict[str, list[CodeChunk]] = {}
 for chunk in chunks:
 file_chunks.setdefault(chunk.file_path, ).append(chunk)
 for file_path, group in file_chunks.items:
 if len(group) <= 1:
 continue
 # 提取每个 chunk 的签名（第一行）
 signatures: list[str] =
 for chunk in group:
 first_line = chunk.content.split("\n", 1)[0].strip
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
) -> list[str]:
 """Scan directory for supported source files."""
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
 files =
 for root, dirs, filenames in os.walk(directory):
 # Filter out excluded directories
 dirs[:] = [d for d in dirs if d not in exclude_patterns]
 for filename in filenames:
 file_path = os.path.join(root, filename)
 language = get_language_from_extension(file_path)
 if language:
 files.append(file_path)
 return files
