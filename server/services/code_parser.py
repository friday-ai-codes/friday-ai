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
 def parse_file(self, file_path: str, base_path: str = "") -> list[CodeChunk]:
 """Parse a file and return code chunks."""
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
 return self._parse_vue(content, relative_path, file_hash)
 elif language == "markdown":
 return self._parse_markdown(content, relative_path, file_hash)
 elif language in ("sass",):
 return self._parse_fallback(content, relative_path, file_hash, language)
 else:
 # Try Tree-sitter first, fallback to character-based
 chunks = self._parse_with_tree_sitter(content, relative_path, file_hash, language)
 if not chunks:
 chunks = self._parse_fallback(content, relative_path, file_hash, language)
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
