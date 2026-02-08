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
 return self._tenant_token
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
 error_msg = data.get("msg", "Unknown error")
 if "rate limit" in error_msg.lower or data.get("code") == 99991400:
 raise RateLimitError(f"Rate limit hit: {error_msg}")
 raise FeishuDocAPIError(f"Failed to read document: {error_msg}")
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
 logger.warning(
 "feishu_write_blocks_failed",
 document_id=document_id,
 error=data,
 )
 # Don't raise - document was created, content write failed
 # This is a partial success
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
 # Common language code mappings
 lang_map: dict[int, str] = {
 1: "plaintext",
 2: "abap",
 3: "ada",
 4: "apache",
 5: "apex",
 22: "c",
 23: "cpp",
 24: "csharp",
 25: "css",
 26: "coffeescript",
 27: "d",
 28: "dart",
 43: "go",
 49: "html",
 50: "http",
 52: "java",
 53: "javascript",
 54: "json",
 59: "kotlin",
 60: "latex",
 69: "markdown",
 73: "objectivec",
 78: "php",
 79: "perl",
 80: "plaintext",
 81: "python",
 85: "ruby",
 86: "rust",
 88: "scala",
 90: "shell",
 91: "sql",
 92: "swift",
 97: "typescript",
 105: "xml",
 106: "yaml",
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
 """Convert a mistune token to Feishu blocks.
 Handles list tokens by extracting all list items.
 Args:
 token: Mistune parsed token
 Returns:
 List of Feishu block definitions
 """
 if not isinstance(token, dict):
 return
 token_type = token.get("type", "")
 # Handle list tokens specially - extract all items
 if token_type == "list":
 blocks: list[dict[str, Any]] =
 is_ordered = token.get("attrs", {}).get("ordered", False)
 children = token.get("children", )
 for child in children:
 if child.get("type") == "list_item":
 text = _extract_token_text(child)
 if text:
 if is_ordered:
 blocks.append(_create_ordered_block(text))
 else:
 blocks.append(_create_bullet_block(text))
 return blocks
 # For other tokens, convert single token
 block = _token_to_block(token)
 return [block] if block else
def _token_to_block(token: Any) -> dict[str, Any] | None:
 """Convert a mistune token to a Feishu block.
 Args:
 token: Mistune parsed token
 Returns:
 Feishu block definition or None
 """
 if not isinstance(token, dict):
 return None
 token_type = token.get("type", "")
 if token_type == "paragraph":
 text = _extract_token_text(token)
 return _create_text_block(text)
 elif token_type == "heading":
 level = token.get("attrs", {}).get("level", 1)
 text = _extract_token_text(token)
 return _create_heading_block(level, text)
 elif token_type == "list":
 # Lists are handled as individual items
 # Return None here, items are processed by caller
 return None
 elif token_type == "list_item":
 text = _extract_token_text(token)
 ordered = token.get("attrs", {}).get("ordered", False)
 if ordered:
 return _create_ordered_block(text)
 return _create_bullet_block(text)
 elif token_type == "block_code":
 code = token.get("raw", "")
 lang = token.get("attrs", {}).get("info", "") or ""
 return _create_code_block(code, lang)
 elif token_type == "block_quote":
 text = _extract_token_text(token)
 return _create_quote_block(text)
 return None
def _extract_token_text(token: dict[str, Any]) -> str:
 """Extract plain text from a token.
 Args:
 token: Mistune token
 Returns:
 Plain text content
 """
 # Direct text content
 if "raw" in token:
 return token["raw"]
 # Children tokens
 children = token.get("children", )
 if not children:
 return ""
 parts: list[str] =
 for child in children:
 if isinstance(child, dict):
 child_type = child.get("type", "")
 if child_type == "text":
 parts.append(child.get("raw", ""))
 elif child_type == "codespan":
 parts.append(f"`{child.get('raw', '')}`")
 elif child_type == "strong":
 inner = _extract_token_text(child)
 parts.append(f"**{inner}**")
 elif child_type == "emphasis":
 inner = _extract_token_text(child)
 parts.append(f"*{inner}*")
 elif child_type == "link":
 text = _extract_token_text(child)
 url = child.get("attrs", {}).get("url", "")
 parts.append(f"[{text}]({url})")
 elif child_type == "paragraph":
 parts.append(_extract_token_text(child))
 else:
 # Recursively extract from other types
 parts.append(_extract_token_text(child))
 elif isinstance(child, str):
 parts.append(child)
 return "".join(parts)
def _create_text_block(text: str) -> dict[str, Any]:
 """Create a text/paragraph block.
 Args:
 text: Block text content
 Returns:
 Feishu text block definition
 """
 return {
 "block_type": 2, # Text
 "text": {
 "elements": [
 {
 "text_run": {
 "content": text,
 }
 }
 ],
 "style": {},
 },
 }
def _create_heading_block(level: int, text: str) -> dict[str, Any]:
 """Create a heading block.
 Args:
 level: Heading level (1-9)
 text: Heading text
 Returns:
 Feishu heading block definition
 """
 # Feishu heading types: 3=H1, 4=H2, ..., 11=H9
 block_type = min(level + 2, 11) # Cap at heading 9
 return {
 "block_type": block_type,
 f"heading{level}": {
 "elements": [
 {
 "text_run": {
 "content": text,
 }
 }
 ],
 "style": {},
 },
 }
def _create_bullet_block(text: str) -> dict[str, Any]:
 """Create a bullet list item block.
 Args:
 text: List item text
 Returns:
 Feishu bullet block definition
 """
 return {
 "block_type": 12, # Bullet
 "bullet": {
 "elements": [
 {
 "text_run": {
 "content": text,
 }
 }
 ],
 "style": {},
 },
 }
def _create_ordered_block(text: str) -> dict[str, Any]:
 """Create an ordered list item block.
 Args:
 text: List item text
 Returns:
 Feishu ordered block definition
 """
 return {
 "block_type": 13, # Ordered
 "ordered": {
 "elements": [
 {
 "text_run": {
 "content": text,
 }
 }
 ],
 "style": {},
 },
 }
def _create_code_block(code: str, language: str = "") -> dict[str, Any]:
 """Create a code block.
 Args:
 code: Code content
 language: Programming language name
 Returns:
 Feishu code block definition
 """
 # Map language name to Feishu code
 lang_code = _get_language_code(language)
 return {
 "block_type": 14, # Code
 "code": {
 "elements": [
 {
 "text_run": {
 "content": code.rstrip("\n"),
 }
 }
 ],
 "style": {
 "language": lang_code,
 },
 },
 }
def _create_quote_block(text: str) -> dict[str, Any]:
 """Create a quote block.
 Args:
 text: Quote text content
 Returns:
 Feishu quote block definition
 """
 return {
 "block_type": 15, # Quote
 "quote": {
 "elements": [
 {
 "text_run": {
 "content": text,
 }
 }
 ],
 "style": {},
 },
 }
def _get_language_code(language: str) -> int:
 """Map language name to Feishu language code.
 Args:
 language: Programming language name
 Returns:
 Feishu language code (defaults to plaintext)
 """
 lang_map: dict[str, int] = {
 "": 1,
 "text": 1,
 "plaintext": 1,
 "c": 22,
 "cpp": 23,
 "c++": 23,
 "csharp": 24,
 "c#": 24,
 "css": 25,
 "go": 43,
 "golang": 43,
 "html": 49,
 "java": 52,
 "javascript": 53,
 "js": 53,
 "json": 54,
 "kotlin": 59,
 "markdown": 69,
 "md": 69,
 "objectivec": 73,
 "objc": 73,
 "php": 78,
 "python": 81,
 "py": 81,
 "ruby": 85,
 "rb": 85,
 "rust": 86,
 "rs": 86,
 "scala": 88,
 "shell": 90,
 "bash": 90,
 "sh": 90,
 "sql": 91,
 "swift": 92,
 "typescript": 97,
 "ts": 97,
 "xml": 105,
 "yaml": 106,
 "yml": 106,
 }
 return lang_map.get(language.lower, 1)
