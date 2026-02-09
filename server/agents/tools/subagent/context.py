"""Context builder for SubAgent tasks.
Builds rich context from AgentSession for SubAgent prompts.
"""
from typing import Any
import structlog
from asgiref.sync import sync_to_async
from agents.models import AgentSession
from common.encryption import decrypt_value
logger = structlog.get_logger(__name__)
async def build_subagent_context(
 session: AgentSession,
 focus_areas: list[str] | None = None,
) -> dict[str, Any]:
 """Build context for SubAgent task from session.
 Extracts project info, work item details, and user preferences
 to provide rich context for SubAgent execution.
 Args:
 session: Main Agent session
 focus_areas: Optional list of areas to focus on (e.g., ["authentication", "api"])
 Returns:
 Context dict with project, work_item, preferences, and focus_areas
 """
 log = logger.bind(session_id=session.session_id)
 context: dict[str, Any] = {
 "project": {},
 "work_item": None,
 "preferences": {
 "language": "zh-CN",
 "output_format": "detailed",
 },
 "focus_areas": focus_areas or,
 }
 # Extract project info
 # Note: Project model doesn't have metadata field, use basic info
 project = session.project
 context["project"] = {
 "name": project.name,
 "description": project.description or "",
 }
 # Get work item details if available
 if session.work_item_id:
 try:
 # Import here to avoid circular imports
 from feishu.project.client import FeishuProjectClient
 # Get repositories to find one with project credentials
 @sync_to_async
 def get_repos -> list[Any]:
 return list(project.repositories.all)
 repos = await get_repos
 if repos:
 repo = repos[0]
 repo_metadata = repo.metadata or {}
 space_id = repo_metadata.get("feishu_space_id")
 if space_id and project.feishu_plugin_secret_encrypted:
 plugin_secret = decrypt_value(project.feishu_plugin_secret_encrypted)
 client = FeishuProjectClient(
 plugin_id=project.feishu_plugin_id or "",
 plugin_secret=plugin_secret or "",
 user_key=project.feishu_user_key or "",
 )
 work_item = await client.get_work_item(
 space_id=space_id,
 work_item_id=session.work_item_id,
 )
 if work_item:
 context["work_item"] = {
 "id": session.work_item_id,
 "name": work_item.get("name", ""),
 "description": work_item.get("description", ""),
 "type": work_item.get("work_item_type_key", ""),
 "status": work_item.get("status", {}).get("name", ""),
 }
 except Exception as e:
 log.warning("failed_to_fetch_work_item", error=str(e))
 log.debug("subagent_context_built", has_work_item=context["work_item"] is not None)
 return context
