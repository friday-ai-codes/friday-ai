"""Feishu webhook handler routes."""
import json
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import select
from ..database import get_session
from ..models import Project, Task, TaskStatus
from ..services.feishu import get_feishu_client, verify_webhook_signature
router = APIRouter(prefix="/api/webhook", tags=["webhook"])
class FeishuChallenge(BaseModel):
 """Feishu URL verification challenge."""
 challenge: str
 token: str
 type: str
class FeishuEvent(BaseModel):
 """Feishu event structure."""
 schema_: Optional[str] = None
 header: Optional[dict] = None
 event: Optional[dict] = None
 class Config:
 # Allow 'schema' field from JSON
 populate_by_name = True
 def __init__(self, **data):
 # Handle 'schema' -> 'schema_' mapping
 if "schema" in data:
 data["schema_"] = data.pop("schema")
 super.__init__(**data)
@router.post("/feishu")
async def handle_feishu_webhook(
 request: Request,
 background_tasks: BackgroundTasks,
 x_lark_request_timestamp: Optional[str] = Header(None),
 x_lark_request_nonce: Optional[str] = Header(None),
 x_lark_signature: Optional[str] = Header(None),
):
 """Handle Feishu/Lark webhook events.
 Supports:
 - URL verification challenge
 - Work item status change events
 - Comment events
 """
 body = await request.body
 # Verify signature if headers are present
 if x_lark_signature:
 if not verify_webhook_signature(
 timestamp=x_lark_request_timestamp or "",
 nonce=x_lark_request_nonce or "",
 body=body,
 signature=x_lark_signature,
 ):
 raise HTTPException(status_code=401, detail="Invalid signature")
 # Parse body
 try:
 data = json.loads(body)
 except json.JSONDecodeError:
 raise HTTPException(status_code=400, detail="Invalid JSON")
 # Handle URL verification challenge
 if data.get("type") == "url_verification":
 challenge = FeishuChallenge(**data)
 return {"challenge": challenge.challenge}
 # Handle event
 event = FeishuEvent(**data)
 if not event.event:
 return {"status": "ignored", "reason": "no event data"}
 # Route to appropriate handler
 event_type = event.header.get("event_type", "") if event.header else ""
 if "work_item" in event_type.lower:
 background_tasks.add_task(
 handle_work_item_event,
 event.event,
 )
 return {"status": "accepted", "event_type": event_type}
 if "comment" in event_type.lower:
 background_tasks.add_task(
 handle_comment_event,
 event.event,
 )
 return {"status": "accepted", "event_type": event_type}
 return {"status": "ignored", "event_type": event_type}
async def handle_work_item_event(event_data: dict):
 """Handle work item status change event.
 Creates a new task or updates existing task status.
 """
 work_item = event_data.get("work_item", {})
 work_item_id = str(work_item.get("id", ""))
 project_key = event_data.get("project_key", "")
 action = event_data.get("action", "")
 if not work_item_id or not project_key:
 return
 async with get_session as db:
 # Find project by feishu_project_key
 result = await db.execute(
 select(Project).where(Project.feishu_project_key == project_key)
 )
 project = result.scalar_one_or_none
 if not project:
 # Project not configured, ignore
 return
 # Check if task exists
 result = await db.execute(select(Task).where(Task.work_item_id == work_item_id))
 task = result.scalar_one_or_none
 if action == "create" and not task:
 # Create new task
 feishu = get_feishu_client
 try:
 work_item_info = await feishu.get_work_item(
 project_key=project_key,
 work_item_id=work_item_id,
 work_item_type=work_item.get("type", "story"),
 )
 new_task = Task(
 project_id=project.id,
 work_item_id=work_item_id,
 feature_id=work_item_id, # Use work_item_id as feature_id
 title=work_item_info.name,
 description=work_item_info.description,
 status=TaskStatus.PENDING,
 )
 db.add(new_task)
 await db.commit
 except Exception as e:
 print(f"Failed to create task: {e}")
 elif action == "update" and task:
 # Check if status changed to trigger planning
 new_status = work_item.get("status", {}).get("name", "")
 # Map Feishu status to our status
 if "规划" in new_status.lower or "planning" in new_status.lower:
 if task.status == TaskStatus.PENDING:
 task.status = TaskStatus.PLANNING
 await db.commit
 # TODO: Trigger plan container
 elif "review" in new_status.lower or "评审" in new_status.lower:
 if task.status == TaskStatus.EXECUTING:
 task.status = TaskStatus.CODE_REVIEW
 await db.commit
async def handle_comment_event(event_data: dict):
 """Handle comment event for human review feedback.
 Checks for approval/rejection comments to trigger next phase.
 """
 comment = event_data.get("comment", {})
 work_item_id = str(event_data.get("work_item_id", ""))
 content = comment.get("content", "")
 if not work_item_id:
 return
 # Parse content to check for approval/rejection
 content_text = content.lower if isinstance(content, str) else ""
 # Check for approval keywords
 approval_keywords = ["通过", "批准", "approved", "lgtm", "ok"]
 rejection_keywords = ["驳回", "拒绝", "rejected", "需要修改", "不通过"]
 is_approved = any(kw in content_text for kw in approval_keywords)
 is_rejected = any(kw in content_text for kw in rejection_keywords)
 if not is_approved and not is_rejected:
 return
 async with get_session as db:
 result = await db.execute(select(Task).where(Task.work_item_id == work_item_id))
 task = result.scalar_one_or_none
 if not task:
 return
 # Handle based on current status
 if task.status == TaskStatus.PLAN_REVIEW:
 if is_approved:
 task.status = TaskStatus.EXECUTING
 task.human_feedback = None
 await db.commit
 # TODO: Trigger execute container
 elif is_rejected:
 # Store feedback and re-plan
 task.human_feedback = (
 content if isinstance(content, str) else str(content)
 )
 task.status = TaskStatus.PLANNING
 await db.commit
 # TODO: Trigger plan container with feedback
 elif task.status == TaskStatus.CODE_REVIEW:
 if is_approved:
 # Wait for PR merge (handled by Git webhook)
 pass
 elif is_rejected:
 task.human_feedback = (
 content if isinstance(content, str) else str(content)
 )
 task.status = TaskStatus.EXECUTING
 await db.commit
 # TODO: Trigger execute container with feedback
@router.post("/github")
async def handle_github_webhook(
 request: Request,
 background_tasks: BackgroundTasks,
):
 """Handle GitHub webhook events (PR merge)."""
 body = await request.body
 try:
 data = json.loads(body)
 except json.JSONDecodeError:
 raise HTTPException(status_code=400, detail="Invalid JSON")
 action = data.get("action", "")
 pull_request = data.get("pull_request", {})
 if action == "closed" and pull_request.get("merged"):
 # PR was merged
 branch = pull_request.get("head", {}).get("ref", "")
 background_tasks.add_task(
 handle_pr_merged,
 branch=branch,
 pr_url=pull_request.get("html_url", ""),
 )
 return {"status": "accepted"}
async def handle_pr_merged(branch: str, pr_url: str):
 """Handle PR merged event - update task to MERGED status."""
 async with get_session as db:
 # Find task by branch name
 result = await db.execute(select(Task).where(Task.branch_name == branch))
 task = result.scalar_one_or_none
 if task and task.status == TaskStatus.CODE_REVIEW:
 task.status = TaskStatus.MERGED
 task.pr_url = pr_url
 await db.commit
 # Update Feishu status
 project = await db.get(Project, task.project_id)
 if project and project.feishu_project_key:
 try:
 feishu = get_feishu_client
 await feishu.transition_status(
 project_key=project.feishu_project_key,
 work_item_id=task.work_item_id,
 work_item_type="story",
 target_status_name="已完成",
 )
 except Exception as e:
 print(f"Failed to update Feishu status: {e}")
