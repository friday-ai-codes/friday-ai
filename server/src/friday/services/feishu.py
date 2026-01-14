"""Feishu (Lark) integration service."""
import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Any, Optional
import httpx
from ..config import get_settings
settings = get_settings
@dataclass
class WorkItemInfo:
 """Work item information from Feishu Project."""
 id: str
 name: str
 description: str
 status: str
 project_key: str
 work_item_type: str
class FeishuClient:
 """Feishu API client for Project (Meego) integration."""
 def __init__(
 self,
 app_id: Optional[str] = None,
 app_secret: Optional[str] = None,
 ):
 self.app_id = app_id or settings.FEISHU_APP_ID
 self.app_secret = app_secret or settings.FEISHU_APP_SECRET
 self._tenant_token: Optional[str] = None
 self._token_expires_at: float = 0
 async def get_tenant_token(self) -> str:
 """Get tenant access token (with caching)."""
 now = time.time
 if self._tenant_token and now < self._token_expires_at:
 return self._tenant_token
 # Request new token
 async with httpx.AsyncClient as client:
 response = await client.post(
 "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
 json={
 "app_id": self.app_id,
 "app_secret": self.app_secret,
 },
 )
 data = response.json
 if data.get("code") != 0:
 raise Exception(f"Failed to get tenant token: {data}")
 self._tenant_token = data["tenant_access_token"]
 # Token expires in 2 hours, refresh 5 minutes early
 self._token_expires_at = now + data.get("expire", 7200) - 300
 return self._tenant_token
 async def get_work_item(
 self,
 project_key: str,
 work_item_id: str,
 work_item_type: str = "story",
 ) -> WorkItemInfo:
 """Get work item details from Feishu Project.
 Args:
 project_key: Project key in Feishu Project
 work_item_id: Work item ID
 work_item_type: Work item type (story, task, bug, etc.)
 Returns:
 WorkItemInfo with parsed details
 """
 token = await self.get_tenant_token
 async with httpx.AsyncClient as client:
 response = await client.post(
 f"https://project.feishu.cn/open_api/{project_key}/work_item/{work_item_type}/{work_item_id}",
 headers={
 "Authorization": f"Bearer {token}",
 "Content-Type": "application/json",
 },
 json={
 "fields": ["name", "description", "status", "priority"],
 },
 )
 data = response.json
 if data.get("err_code") != 0:
 raise Exception(f"Failed to get work item: {data}")
 item = data.get("data", {})
 return WorkItemInfo(
 id=work_item_id,
 name=item.get("name", ""),
 description=self._parse_rich_text(item.get("description", {})),
 status=item.get("status", {}).get("name", ""),
 project_key=project_key,
 work_item_type=work_item_type,
 )
 async def add_comment(
 self,
 project_key: str,
 work_item_id: str,
 work_item_type: str,
 content: str,
 ) -> bool:
 """Add a comment to a work item.
 Args:
 project_key: Project key
 work_item_id: Work item ID
 work_item_type: Work item type
 content: Comment content (Markdown)
 Returns:
 True if successful
 """
 token = await self.get_tenant_token
 # Convert markdown to Feishu rich text format
 rich_content = self._markdown_to_rich_text(content)
 async with httpx.AsyncClient as client:
 response = await client.post(
 f"https://project.feishu.cn/open_api/{project_key}/work_item/{work_item_type}/{work_item_id}/comment/create",
 headers={
 "Authorization": f"Bearer {token}",
 "Content-Type": "application/json",
 },
 json={
 "content": rich_content,
 },
 )
 data = response.json
 return data.get("err_code") == 0
 async def get_comments(
 self,
 project_key: str,
 work_item_id: str,
 work_item_type: str,
 limit: int = 50,
 ) -> list[dict]:
 """Get comments from a work item.
 Args:
 project_key: Project key
 work_item_id: Work item ID
 work_item_type: Work item type
 limit: Maximum number of comments
 Returns:
 List of comments with content and author
 """
 token = await self.get_tenant_token
 async with httpx.AsyncClient as client:
 response = await client.get(
 f"https://project.feishu.cn/open_api/{project_key}/work_item/{work_item_type}/{work_item_id}/comment/list",
 headers={
 "Authorization": f"Bearer {token}",
 },
 params={
 "page_size": limit,
 },
 )
 data = response.json
 if data.get("err_code") != 0:
 return
 comments =
 for item in data.get("data", {}).get("comments", ):
 comments.append(
 {
 "id": item.get("id"),
 "content": self._parse_rich_text(item.get("content", {})),
 "created_at": item.get("created_at"),
 "author": item.get("author", {}).get("name", "Unknown"),
 }
 )
 return comments
 async def transition_status(
 self,
 project_key: str,
 work_item_id: str,
 work_item_type: str,
 target_status_name: str,
 ) -> bool:
 """Transition work item to a new status.
 Args:
 project_key: Project key
 work_item_id: Work item ID
 work_item_type: Work item type
 target_status_name: Target status name (e.g., "待Review")
 Returns:
 True if successful
 """
 token = await self.get_tenant_token
 # First, get available transitions
 async with httpx.AsyncClient as client:
 # Get current work item to find available transitions
 response = await client.get(
 f"https://project.feishu.cn/open_api/{project_key}/work_item/{work_item_type}/{work_item_id}/workflow/transition",
 headers={
 "Authorization": f"Bearer {token}",
 },
 )
 data = response.json
 if data.get("err_code") != 0:
 raise Exception(f"Failed to get transitions: {data}")
 transitions = data.get("data", {}).get("transitions", )
 # Find matching transition
 target_transition = None
 for t in transitions:
 if (
 target_status_name.lower
 in t.get("to_status", {}).get("name", "").lower
 ):
 target_transition = t
 break
 if not target_transition:
 available = [t.get("to_status", {}).get("name") for t in transitions]
 raise Exception(
 f"Cannot transition to '{target_status_name}'. Available: {available}"
 )
 # Execute transition
 response = await client.post(
 f"https://project.feishu.cn/open_api/{project_key}/work_item/{work_item_type}/{work_item_id}/workflow/transition",
 headers={
 "Authorization": f"Bearer {token}",
 "Content-Type": "application/json",
 },
 json={
 "transition_id": target_transition["id"],
 },
 )
 return response.json.get("err_code") == 0
 def _parse_rich_text(self, rich_text: Any) -> str:
 """Parse Feishu rich text to Markdown.
 Args:
 rich_text: Rich text object from Feishu API
 Returns:
 Markdown string
 """
 if isinstance(rich_text, str):
 return rich_text
 if not isinstance(rich_text, dict):
 return str(rich_text) if rich_text else ""
 # Handle document structure
 content = rich_text.get("content", )
 if not content:
 return ""
 result =
 for block in content:
 block_type = block.get("type", "")
 if block_type == "paragraph":
 text = self._parse_paragraph(block)
 result.append(text)
 elif block_type == "heading":
 level = block.get("attrs", {}).get("level", 1)
 text = self._parse_paragraph(block)
 result.append(f"{'#' * level} {text}")
 elif block_type == "bullet_list":
 items = block.get("content", )
 for item in items:
 text = self._parse_paragraph(item)
 result.append(f"- {text}")
 elif block_type == "ordered_list":
 items = block.get("content", )
 for i, item in enumerate(items, 1):
 text = self._parse_paragraph(item)
 result.append(f"{i}. {text}")
 elif block_type == "code_block":
 code = self._parse_paragraph(block)
 lang = block.get("attrs", {}).get("language", "")
 result.append(f"```{lang}\n{code}\n```")
 elif block_type == "image":
 # Images are tricky - just add a placeholder
 result.append("[Image]")
 return "\n".join(result)
 def _parse_paragraph(self, block: dict) -> str:
 """Parse paragraph content to text."""
 content = block.get("content", )
 texts =
 for node in content:
 if node.get("type") == "text":
 text = node.get("text", "")
 marks = node.get("marks", )
 for mark in marks:
 mark_type = mark.get("type")
 if mark_type == "bold":
 text = f"**{text}**"
 elif mark_type == "italic":
 text = f"*{text}*"
 elif mark_type == "code":
 text = f"`{text}`"
 elif mark_type == "link":
 href = mark.get("attrs", {}).get("href", "")
 text = f"[{text}]({href})"
 texts.append(text)
 return "".join(texts)
 def _markdown_to_rich_text(self, markdown: str) -> dict:
 """Convert Markdown to Feishu rich text format.
 This is a simplified conversion - complex Markdown may not convert perfectly.
 """
 # For now, just wrap in a simple paragraph
 # A full implementation would parse Markdown AST
 return {
 "content": [
 {
 "type": "paragraph",
 "content": [
 {
 "type": "text",
 "text": markdown,
 }
 ],
 }
 ]
 }
def verify_webhook_signature(
 timestamp: str,
 nonce: str,
 body: bytes,
 signature: str,
) -> bool:
 """Verify Feishu webhook signature.
 Args:
 timestamp: Request timestamp header
 nonce: Request nonce header
 body: Raw request body
 signature: Request signature header
 Returns:
 True if signature is valid
 """
 secret = settings.FEISHU_WEBHOOK_SECRET
 if not secret:
 # No secret configured, skip verification
 return True
 # Construct string to sign
 string_to_sign = f"{timestamp}\n{nonce}\n{body.decode}"
 # Calculate work item
 hmac_code = hmac.new(
 secret.encode,
 string_to_sign.encode,
 hashlib.sha256,
 ).hexdigest
 return hmac.compare_digest(hmac_code, signature)
# Singleton client instance
_feishu_client: Optional[FeishuClient] = None
def get_feishu_client -> FeishuClient:
 """Get Feishu client singleton."""
 global _feishu_client
 if _feishu_client is None:
 _feishu_client = FeishuClient
 return _feishu_client
