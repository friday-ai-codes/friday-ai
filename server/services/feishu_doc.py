"""Feishu Document API client for reading and creating cloud documents.
Provides FeishuDocClient for document operations with Markdown conversion support.
Uses tenant_access_token authentication (same as IM API, different from Project API).
"""
import time
from typing import Any
import httpx
import mistune
import structlog
from tenacity import (
 retry,
 retry_if_exception_type,
 stop_after_attempt,
 wait_exponential,
)
logger = structlog.get_logger(__name__)
class FeishuDocAPIError(Exception):
 """Error from Feishu Document API."""
 pass
class RateLimitError(FeishuDocAPIError):
 """Rate limit error, should retry with backoff."""
 pass
class PermissionDeniedError(FeishuDocAPIError):
 """用户无权限访问文档。"""
 pass
class DocumentNotFoundError(FeishuDocAPIError):
 """文档不存在或已删除。"""
 pass
# 飞书 API 错误码分类集合
PERMISSION_CODES: frozenset[int] = frozenset({91003, 91004, 91204, 95008, 95009, 99991672})
NOT_FOUND_CODES: frozenset[int] = frozenset({1002, 18066, 91402, 95006, 95007})
MAX_DOC_CHARS: int = 30_000
def truncate_doc_content(markdown: str) -> tuple[str, bool]:
 """截断过长文档内容。返回 (内容, 是否截断)。"""
 if len(markdown) <= MAX_DOC_CHARS:
 return markdown, False
 return markdown[:MAX_DOC_CHARS], True
class FeishuDocClient:
 """Feishu Document API client using tenant_access_token authentication.
 Provides methods to read and create Feishu cloud documents with
 automatic Markdown conversion.
 Authentication uses tenant_access_token (2-hour validity, auto-refresh).
 This is different from FeishuClient which uses plugin_token for Project API.
 """
 OPEN_API_BASE = "https://open.feishu.cn/open-apis"
 def __init__(self, app_id: str, app_secret: str):
 """Initialize Feishu Document client.
 Args:
 app_id: Feishu application ID
 app_secret: Feishu application secret
 """
 self.app_id = app_id
 self.app_secret = app_secret
 self._tenant_token: str | None = None
 self._token_expires_at: float = 0
 async def get_tenant_access_token(self) -> str:
 """Get tenant_access_token with caching (2-hour validity).
 Returns:
 Valid tenant_access_token
 Raises:
 FeishuDocAPIError: Failed to get token
 """
 now = time.time
 if self._tenant_token and now < self._token_expires_at:
 return self._tenant_token
 async with httpx.AsyncClient as client:
 response = await client.post(
 f"{self.OPEN_API_BASE}/auth/v3/tenant_access_token/internal",
 json={
 "app_id": self.app_id,
 "app_secret": self.app_secret,
 },
 )
 data = response.json
 if data.get("code") != 0:
 raise FeishuDocAPIError(f"Failed to get tenant token: {data}")
 self._tenant_token = data["tenant_access_token"]
 # Token valid for 2 hours, refresh 5 minutes early
 self._token_expires_at = now + data.get("expire", 7200) - 300
 logger.debug("feishu_doc_token_refreshed", expires_in=data.get("expire"))
 token = self._tenant_token
 assert token is not None
 return token
 @retry(
 stop=stop_after_attempt(3),
 wait=wait_exponential(multiplier=1, min=4, max=60),
 retry=retry_if_exception_type(RateLimitError),
 reraise=True,
 )
 async def get_document_content(
 self,
 document_id: str,
 ) -> tuple[str, list[dict[str, Any]]]:
 """Read Feishu cloud document content.
 Args:
 document_id: Document ID (extracted from URL, e.g., doxcnXXXX)
 Returns:
 Tuple of (markdown_content, raw_blocks)
 Raises:
 FeishuDocAPIError: API call failed
 RateLimitError: Rate limit hit (will retry automatically)
 """
 token = await self.get_tenant_access_token
 async with httpx.AsyncClient as client:
 # Get document blocks
 response = await client.get(
 f"{self.OPEN_API_BASE}/docx/v1/documents/{document_id}/blocks",
 headers={"Authorization": f"Bearer {token}"},
 params={"page_size": 500},
 )
 data = response.json
 if data.get("code") != 0:
 error_code = data.get("code", 0)
 error_msg = data.get("msg", "Unknown error")
 if error_code == 99991400 or "rate limit" in error_msg.lower:
 raise RateLimitError(f"Rate limit hit: {error_msg}")
 if error_code in PERMISSION_CODES:
 raise PermissionDeniedError(f"无权限访问文档: {error_msg}")
 if error_code in NOT_FOUND_CODES:
 raise DocumentNotFoundError(f"文档不存在: {error_msg}")
 raise FeishuDocAPIError(f"读取文档失败: {error_msg}")
 blocks = data.get("data", {}).get("items", )
 markdown = blocks_to_markdown(blocks)
 logger.info(
 "feishu_document_read",
 document_id=document_id,
 block_count=len(blocks),
 content_length=len(markdown),
 )
 return markdown, blocks
 @retry(
 stop=stop_after_attempt(3),
 wait=wait_exponential(multiplier=1, min=4, max=60),
 retry=retry_if_exception_type(RateLimitError),
 reraise=True,
 )
 async def create_document(
 self,
 title: str,
 folder_token: str,
 content: str,
 ) -> dict[str, str]:
 """Create a Feishu cloud document.
 Args:
 title: Document title
 folder_token: Parent folder token (from project document space)
 content: Document content in Markdown format
 Returns:
 Dict with document_id and url
 Raises:
 FeishuDocAPIError: API call failed
 RateLimitError: Rate limit hit (will retry automatically)
 """
 token = await self.get_tenant_access_token
 async with httpx.AsyncClient as client:
 # 1. Create empty document
 response = await client.post(
 f"{self.OPEN_API_BASE}/docx/v1/documents",
 headers={
 "Authorization": f"Bearer {token}",
 "Content-Type": "application/json",
 },
 json={
 "title": title,
 "folder_token": folder_token,
 },
 )
 data = response.json
 if data.get("code") != 0:
 error_msg = data.get("msg", "Unknown error")
 if "rate limit" in error_msg.lower or data.get("code") == 99991400:
 raise RateLimitError(f"Rate limit hit: {error_msg}")
 raise FeishuDocAPIError(f"Failed to create document: {error_msg}")
 document = data.get("data", {}).get("document", {})
 document_id = document.get("document_id", "")
 if not document_id:
 raise FeishuDocAPIError("No document_id in response")
 # 2. Write content blocks
 blocks = markdown_to_blocks(content)
 if blocks:
 await self._write_blocks(document_id, blocks, token)
 # Construct document URL
 doc_url = f"https://feishu.cn/docx/{document_id}"
 logger.info(
 "feishu_document_created",
 document_id=document_id,
 title=title,
 block_count=len(blocks),
 )
 return {
 "document_id": document_id,
 "url": doc_url,
 }
 async def _write_blocks(
 self,
 document_id: str,
 blocks: list[dict[str, Any]],
 token: str,
 ) -> None:
 """Write blocks to a document.
 Args:
 document_id: Target document ID
 blocks: List of block definitions
 token: Authorization token
 """
 async with httpx.AsyncClient as client:
 # Get the document's root block ID first
 response = await client.get(
 f"{self.OPEN_API_BASE}/docx/v1/documents/{document_id}",
 headers={"Authorization": f"Bearer {token}"},
 )
 data = response.json
 if data.get("code") != 0:
 raise FeishuDocAPIError(f"Failed to get document info: {data}")
 # The document itself is the root block
 # We need to add children to the page block
 response = await client.post(
 f"{self.OPEN_API_BASE}/docx/v1/documents/{document_id}/blocks/{document_id}/children",
 headers={
 "Authorization": f"Bearer {token}",
 "Content-Type": "application/json",
 },
 json={
 "children": blocks,
 "index": 0,
 },
 )
 data = response.json
 if data.get("code") != 0:
 logger.error(
 "feishu_write_blocks_failed",
 document_id=document_id,
 error_code=data.get("code"),
 error_msg=data.get("msg"),
 error_data=data,
 )
 raise FeishuDocAPIError(
 f"文档已创建但内容写入失败: {data.get('msg', 'Unknown error')} (code={data.get('code')})"
 )
def blocks_to_markdown(blocks: list[dict[str, Any]]) -> str:
 """Convert Feishu document blocks to Markdown.
 Supports:
 - text/paragraph blocks
 - heading1-9 blocks
 - bullet/ordered list blocks
 - code blocks
 - quote blocks
 - image blocks (converted to [Image: url])
 Args:
 blocks: List of Feishu document blocks
 Returns:
 Markdown formatted string
 """
 result: list[str] =
 for block in blocks:
 block_type = block.get("block_type", 0)
 # Block type mapping (Feishu uses numeric types):
 # 1: Page, 2: Text, 3: Heading1, 4: Heading2, ...
 # 9: Heading7, 10: Heading8, 11: Heading9
 # 12: Bullet, 13: Ordered, 14: Code, 15: Quote
 # 27: Image
 if block_type == 2: # Text/Paragraph
 text = _extract_text_content(block)
 if text:
 result.append(text)
 elif 3 <= block_type <= 11: # Heading 1-9
 level = block_type - 2 # heading1 = type 3, so level = 1
 text = _extract_text_content(block)
 if text:
 result.append(f"{'#' * level} {text}")
 elif block_type == 12: # Bullet list
 text = _extract_text_content(block)
 if text:
 result.append(f"- {text}")
 elif block_type == 13: # Ordered list
 text = _extract_text_content(block)
 if text:
 # Note: Feishu doesn't provide list index, we use generic numbering
 result.append(f"1. {text}")
 elif block_type == 14: # Code block
 code_block = block.get("code", {})
 elements = code_block.get("elements", )
 code_text = "".join(
 elem.get("text_run", {}).get("content", "") for elem in elements
 )
 language = code_block.get("style", {}).get("language", "")
 # Map language code to name (Feishu uses numeric codes)
 lang_name = _get_language_name(language)
 result.append(f"```{lang_name}\n{code_text}\n```")
 elif block_type == 15: # Quote
 text = _extract_text_content(block)
 if text:
 result.append(f"> {text}")
 elif block_type == 27: # Image
 image_block = block.get("image", {})
 token = image_block.get("token", "")
 result.append(f"[Image: {token}]")
 # Skip other block types (page, divider, etc.)
 return "\n\n".join(result)
def _extract_text_content(block: dict[str, Any]) -> str:
 """Extract text content from a block.
 Args:
 block: Feishu document block
 Returns:
 Plain text content with inline formatting
 """
 # Different block types store text differently
 text_block = block.get("text", {})
 if not text_block:
 # Try heading block format
 for i in range(1, 10):
 text_block = block.get(f"heading{i}", {})
 if text_block:
 break
 if not text_block:
 # Try bullet/ordered format
 text_block = block.get("bullet", {}) or block.get("ordered", {})
 if not text_block:
 # Try quote format
 text_block = block.get("quote", {})
 elements = text_block.get("elements", )
 parts: list[str] =
 for elem in elements:
 text_run = elem.get("text_run", {})
 content = text_run.get("content", "")
 if not content:
 continue
 # Apply inline styles
 style = text_run.get("text_element_style", {})
 if style.get("bold"):
 content = f"**{content}**"
 if style.get("italic"):
 content = f"*{content}*"
 if style.get("inline_code"):
 content = f"`{content}`"
 if style.get("link", {}).get("url"):
 url = style["link"]["url"]
 content = f"[{content}]({url})"
 parts.append(content)
 return "".join(parts)
def _get_language_name(language_code: int | str) -> str:
 """Map Feishu language code to language name.
 Args:
 language_code: Feishu language code (numeric or string)
 Returns:
 Language name for code fence
 """
 # 飞书 API 代码块语言码 (1-75) 反向映射
 lang_map: dict[int, str] = {
 1: "plaintext",
 2: "bash",
 4: "c",
 5: "cpp",
 6: "csharp",
 7: "css",
 9: "go",
 12: "html",
 13: "java",
 14: "javascript",
 16: "json",
 18: "kotlin",
 20: "markdown",
 24: "objectivec",
 25: "php",
 28: "python",
 31: "ruby",
 32: "rust",
 33: "scala",
 36: "sql",
 37: "swift",
 39: "typescript",
 44: "xml",
 45: "yaml",
 }
 if isinstance(language_code, int):
 return lang_map.get(language_code, "")
 return str(language_code) if language_code else ""
def markdown_to_blocks(content: str) -> list[dict[str, Any]]:
 """Convert Markdown to Feishu document blocks.
 Uses mistune to parse Markdown AST and converts to Feishu block format.
 Args:
 content: Markdown formatted content
 Returns:
 List of Feishu document block definitions
 """
 if not content.strip:
 return
 blocks: list[dict[str, Any]] =
 # Parse Markdown using mistune
 md = mistune.create_markdown(renderer=None)
 tokens = md(content)
 if tokens is None:
 return blocks
 # tokens is a list of token dicts when renderer=None
 for token in tokens:
 token_blocks = _token_to_blocks(token)
 blocks.extend(token_blocks)
 return blocks
def _token_to_blocks(token: Any) -> list[dict[str, Any]]:
 """Convert a mistune token to Feishu blocks."""
 if not isinstance(token, dict):
 return
 token_type = token.get("type", "")
 if token_type == "list":
 blocks: list[dict[str, Any]] =
 is_ordered = token.get("attrs", {}).get("ordered", False)
 for child in token.get("children", ):
 if child.get("type") == "list_item":
 elements = _extract_token_elements(child)
 if elements:
 blocks.append(_create_block_with_elements(
 13 if is_ordered else 12,
 "ordered" if is_ordered else "bullet",
 elements,
 ))
 return blocks
 if token_type == "table":
 return _table_to_blocks(token)
 block = _token_to_block(token)
 return [block] if block else
def _token_to_block(token: Any) -> dict[str, Any] | None:
 """Convert a mistune token to a Feishu block."""
 if not isinstance(token, dict):
 return None
 token_type = token.get("type", "")
 if token_type == "paragraph":
 elements = _extract_token_elements(token)
 return _create_block_with_elements(2, "text", elements)
 elif token_type == "heading":
 level = token.get("attrs", {}).get("level", 1)
 elements = _extract_token_elements(token)
 block_type = min(level + 2, 11)
 return _create_block_with_elements(block_type, f"heading{level}", elements)
 elif token_type == "block_code":
 code = token.get("raw", "")
 lang = token.get("attrs", {}).get("info", "") or ""
 return _create_code_block(code, lang)
 elif token_type == "block_quote":
 elements = _extract_token_elements(token)
 return _create_block_with_elements(15, "quote", elements)
 elif token_type == "thematic_break":
 return {"block_type": 22} # Divider
 return None
def _extract_token_elements(
 token: dict[str, Any],
 style: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
 """Extract structured elements (with inline styles) from a mistune token.
 Returns a list of text_run dicts for use in Feishu block elements.
 """
 if style is None:
 style = {}
 # Direct text content
 if token.get("type") == "text" or (
 "raw" in token and token.get("type") not in ("block_code", "codespan", "paragraph", "list_item", "strong", "emphasis", "link")
 ):
 raw = token.get("raw", "")
 if not raw:
 return
 element: dict[str, Any] = {"text_run": {"content": raw}}
 if style:
 element["text_run"]["text_element_style"] = style
 return [element]
 # Inline code
 if token.get("type") == "codespan":
 raw = token.get("raw", token.get("children", ""))
 if isinstance(raw, list):
 raw = "".join(c.get("raw", "") if isinstance(c, dict) else str(c) for c in raw)
 return [{"text_run": {"content": str(raw), "text_element_style": {**style, "inline_code": True}}}]
 # Bold
 if token.get("type") == "strong":
 return _extract_children_elements(token, {**style, "bold": True})
 # Italic
 if token.get("type") == "emphasis":
 return _extract_children_elements(token, {**style, "italic": True})
 # Link
 if token.get("type") == "link":
 url = token.get("attrs", {}).get("url", "")
 link_style = {**style, "link": {"url": url}} if url else style
 return _extract_children_elements(token, link_style)
 # Strikethrough
 if token.get("type") == "strikethrough":
 return _extract_children_elements(token, {**style, "strikethrough": True})
 # Container types (paragraph, list_item, etc.) — recurse into children
 return _extract_children_elements(token, style)
def _extract_children_elements(
 token: dict[str, Any],
 style: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
 """Recurse into children and collect elements."""
 children = token.get("children", )
 if not children:
 return
 elements: list[dict[str, Any]] =
 for child in children:
 if isinstance(child, dict):
 elements.extend(_extract_token_elements(child, style))
 elif isinstance(child, str) and child:
 element: dict[str, Any] = {"text_run": {"content": child}}
 if style:
 element["text_run"]["text_element_style"] = style
 elements.append(element)
 return elements
def _table_to_blocks(token: dict[str, Any]) -> list[dict[str, Any]]:
 """Convert a Markdown table to text blocks (飞书表格需要 descendants API，这里用文本模拟)."""
 blocks: list[dict[str, Any]] =
 # Header
 headers = token.get("children", )
 if not headers:
 return blocks
 head = None
 body_rows: list[Any] =
 for child in headers:
 if isinstance(child, dict):
 if child.get("type") == "table_head":
 head = child
 elif child.get("type") == "table_body":
 body_rows = child.get("children", )
 # Build header row
 if head:
 head_cells = head.get("children", )
 if head_cells:
 row = head_cells[0] if head_cells else None
 if row:
 cells = row.get("children", )
 header_texts =
 for cell in cells:
 elements = _extract_token_elements(cell)
 text = "".join(e.get("text_run", {}).get("content", "") for e in elements)
 header_texts.append(text)
 # Header as bold text block
 header_elements: list[dict[str, Any]] =
 for i, ht in enumerate(header_texts):
 if i > 0:
 header_elements.append({"text_run": {"content": " | "}})
 header_elements.append({"text_run": {"content": ht, "text_element_style": {"bold": True}}})
 blocks.append(_create_block_with_elements(2, "text", header_elements))
 # Divider
 blocks.append({"block_type": 22})
 # Body rows
 for row in body_rows:
 if not isinstance(row, dict):
 continue
 cells = row.get("children", )
 row_elements: list[dict[str, Any]] =
 for i, cell in enumerate(cells):
 if i > 0:
 row_elements.append({"text_run": {"content": " | "}})
 cell_elems = _extract_token_elements(cell)
 row_elements.extend(cell_elems)
 if row_elements:
 blocks.append(_create_block_with_elements(2, "text", row_elements))
 return blocks
def _create_block_with_elements(
 block_type: int,
 block_key: str,
 elements: list[dict[str, Any]],
) -> dict[str, Any]:
 """Create a Feishu block with pre-built elements."""
 if not elements:
 elements = [{"text_run": {"content": ""}}]
 return {
 "block_type": block_type,
 block_key: {
 "elements": elements,
 "style": {},
 },
 }
def _create_code_block(code: str, language: str = "") -> dict[str, Any]:
 """Create a code block."""
 lang_code = _get_language_code(language)
 return {
 "block_type": 14,
 "code": {
 "elements": [
 {"text_run": {"content": code.rstrip("\n")}}
 ],
 "style": {"language": lang_code},
 },
 }
def _create_quote_block(text: str) -> dict[str, Any]:
 """Create a quote block (plain text version, used by blocks_to_markdown)."""
 return _create_block_with_elements(15, "quote", [{"text_run": {"content": text}}])
def _get_language_code(language: str) -> int:
 """Map language name to Feishu language code.
 Args:
 language: Programming language name
 Returns:
 Feishu language code (defaults to plaintext)
 """
 # 飞书 API 代码块语言码范围为 1-75
 # 参考: https://open.feishu.cn/document/client-docs/docs-add-on/06-code-block
 lang_map: dict[str, int] = {
 "": 1,
 "text": 1,
 "plaintext": 1,
 "bash": 2,
 "sh": 2,
 "shell": 2,
 "c": 4,
 "cpp": 5,
 "c++": 5,
 "csharp": 6,
 "c#": 6,
 "css": 7,
 "go": 9,
 "golang": 9,
 "html": 12,
 "java": 13,
 "javascript": 14,
 "js": 14,
 "json": 16,
 "kotlin": 18,
 "markdown": 20,
 "md": 20,
 "objectivec": 24,
 "objc": 24,
 "php": 25,
 "python": 28,
 "py": 28,
 "ruby": 31,
 "rb": 31,
 "rust": 32,
 "rs": 32,
 "scala": 33,
 "sql": 36,
 "swift": 37,
 "typescript": 39,
 "ts": 39,
 "xml": 44,
 "yaml": 45,
 "yml": 45,
 }
 code = lang_map.get(language.lower, 1)
 # 安全兜底：确保不超出 API 允许范围
 if code < 1 or code > 75:
 return 1
 return code
