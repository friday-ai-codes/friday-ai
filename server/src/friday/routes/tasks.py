"""Task management API routes."""
from datetime import datetime
from typing import Any, List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from ..database import get_db
from ..models import (
 GitCredential,
 Project,
 Task,
 TaskCreate,
 TaskRead,
 TaskStatus,
 TaskUpdate,
)
from ..services.crypto import decrypt_value
from ..services.scheduler import get_scheduler
router = APIRouter(prefix="/api/tasks", tags=["tasks"])
class TaskExecuteRequest(BaseModel):
 """Request model for task execution."""
 mode: str = "plan" # "plan" or "execute"
class TaskExecuteResponse(BaseModel):
 """Response model for task execution."""
 task_id: str
 container_id: str
 mode: str
 message: str
class TaskStatusUpdate(BaseModel):
 """Status update from task container."""
 task_id: str
 status: str
 message: str | None = None
 details: dict[str, Any] | None = None
 timestamp: str | None = None
@router.get("/", response_model=List[TaskRead])
async def list_tasks(
 project_id: Optional[str] = Query(None, description="Filter by project ID"),
 status: Optional[TaskStatus] = Query(None, description="Filter by status"),
 limit: int = Query(50, ge=1, le=100),
 offset: int = Query(0, ge=0),
 db: AsyncSession = Depends(get_db),
):
 """List tasks with optional filters."""
 query = select(Task)
 if project_id:
 query = query.where(Task.project_id == project_id)
 if status:
 query = query.where(Task.status == status)
 query = query.order_by(Task.created_at.desc).offset(offset).limit(limit)
 result = await db.execute(query)
 tasks = result.scalars.all
 return [TaskRead(**t.model_dump) for t in tasks]
@router.post("/", response_model=TaskRead, status_code=201)
async def create_task(
 task: TaskCreate,
 db: AsyncSession = Depends(get_db),
):
 """Create a new task."""
 # Verify project exists
 result = await db.execute(select(Project).where(Project.id == task.project_id))
 project = result.scalar_one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="Project not found")
 # Check for duplicate work_item_id
 existing = await db.execute(
 select(Task).where(Task.work_item_id == task.work_item_id)
 )
 if existing.scalar_one_or_none:
 raise HTTPException(
 status_code=400,
 detail=f"Task with work_item_id {task.work_item_id} already exists",
 )
 db_task = Task.model_validate(task)
 db.add(db_task)
 await db.commit
 await db.refresh(db_task)
 return TaskRead(**db_task.model_dump)
@router.get("/{task_id}", response_model=TaskRead)
async def get_task(
 task_id: str,
 db: AsyncSession = Depends(get_db),
):
 """Get a task by ID."""
 result = await db.execute(select(Task).where(Task.id == task_id))
 task = result.scalar_one_or_none
 if not task:
 raise HTTPException(status_code=404, detail="Task not found")
 return TaskRead(**task.model_dump)
@router.get("/work-item/{work_item_id}", response_model=TaskRead)
async def get_task_by_work_item(
 work_item_id: str,
 db: AsyncSession = Depends(get_db),
):
 """Get a task by Feishu work item ID."""
 result = await db.execute(select(Task).where(Task.work_item_id == work_item_id))
 task = result.scalar_one_or_none
 if not task:
 raise HTTPException(status_code=404, detail="Task not found")
 return TaskRead(**task.model_dump)
@router.patch("/{task_id}", response_model=TaskRead)
async def update_task(
 task_id: str,
 task_update: TaskUpdate,
 db: AsyncSession = Depends(get_db),
):
 """Update a task."""
 result = await db.execute(select(Task).where(Task.id == task_id))
 task = result.scalar_one_or_none
 if not task:
 raise HTTPException(status_code=404, detail="Task not found")
 update_data = task_update.model_dump(exclude_unset=True)
 for key, value in update_data.items:
 setattr(task, key, value)
 task.updated_at = datetime.utcnow
 await db.commit
 await db.refresh(task)
 return TaskRead(**task.model_dump)
@router.post("/{task_id}/transition/{new_status}", response_model=TaskRead)
async def transition_task(
 task_id: str,
 new_status: TaskStatus,
 db: AsyncSession = Depends(get_db),
):
 """Transition task to a new status with validation."""
 result = await db.execute(select(Task).where(Task.id == task_id))
 task = result.scalar_one_or_none
 if not task:
 raise HTTPException(status_code=404, detail="Task not found")
 # Define valid transitions
 valid_transitions = {
 TaskStatus.PENDING: [TaskStatus.PLANNING, TaskStatus.FAILED],
 TaskStatus.PLANNING: [TaskStatus.PLAN_REVIEW, TaskStatus.FAILED],
 TaskStatus.PLAN_REVIEW: [TaskStatus.PLANNING, TaskStatus.EXECUTING],
 TaskStatus.EXECUTING: [TaskStatus.CODE_REVIEW, TaskStatus.FAILED],
 TaskStatus.CODE_REVIEW: [TaskStatus.EXECUTING, TaskStatus.MERGED],
 TaskStatus.FAILED: [TaskStatus.PENDING],
 TaskStatus.MERGED:, # Terminal state
 }
 allowed = valid_transitions.get(task.status, )
 if new_status not in allowed:
 raise HTTPException(
 status_code=400,
 detail=f"Cannot transition from {task.status} to {new_status}. Allowed: {allowed}",
 )
 # Update timestamps based on transition
 now = datetime.utcnow
 if new_status == TaskStatus.PLANNING and task.plan_started_at is None:
 task.plan_started_at = now
 elif new_status == TaskStatus.PLAN_REVIEW:
 task.plan_completed_at = now
 elif new_status == TaskStatus.EXECUTING and task.execute_started_at is None:
 task.execute_started_at = now
 elif new_status == TaskStatus.CODE_REVIEW:
 task.execute_completed_at = now
 elif new_status == TaskStatus.FAILED:
 task.retry_count += 1
 task.status = new_status
 task.updated_at = now
 await db.commit
 await db.refresh(task)
 return TaskRead(**task.model_dump)
@router.delete("/{task_id}", status_code=204)
async def delete_task(
 task_id: str,
 db: AsyncSession = Depends(get_db),
):
 """Delete a task."""
 result = await db.execute(select(Task).where(Task.id == task_id))
 task = result.scalar_one_or_none
 if not task:
 raise HTTPException(status_code=404, detail="Task not found")
 await db.delete(task)
 await db.commit
 return None
@router.post("/{task_id}/execute", response_model=TaskExecuteResponse)
async def execute_task(
 task_id: str,
 request: TaskExecuteRequest,
 background_tasks: BackgroundTasks,
 db: AsyncSession = Depends(get_db),
):
 """Start task execution in a container.
 This endpoint starts a Docker container to execute the task.
 The container will run Claude Code to either generate a plan or implement changes.
 """
 # Get task
 result = await db.execute(select(Task).where(Task.id == task_id))
 task = result.scalar_one_or_none
 if not task:
 raise HTTPException(status_code=404, detail="Task not found")
 # Get project
 result = await db.execute(select(Project).where(Project.id == task.project_id))
 project = result.scalar_one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="Project not found")
 # Check if task can be executed
 if request.mode == "plan" and task.status != TaskStatus.PENDING:
 raise HTTPException(
 status_code=400,
 detail=f"Cannot start planning: task is in {task.status} status",
 )
 elif request.mode == "execute" and task.status != TaskStatus.PLAN_REVIEW:
 raise HTTPException(
 status_code=400,
 detail="Cannot start execution: task must be in PLAN_REVIEW status",
 )
 # Get git credentials
 git_credentials = {}
 if project.git_credential_id:
 result = await db.execute(
 select(GitCredential).where(GitCredential.id == project.git_credential_id)
 )
 credential = result.scalar_one_or_none
 if credential:
 if credential.ssh_private_key_encrypted:
 git_credentials["ssh_key"] = decrypt_value(
 credential.ssh_private_key_encrypted
 )
 elif credential.access_token_encrypted:
 git_credentials["access_token"] = decrypt_value(
 credential.access_token_encrypted
 )
 # Set git info on task if not already set
 if not task.git_repo_url:
 task.git_repo_url = project.git_repo_url
 if not task.git_branch:
 task.git_branch = project.default_branch or "main"
 # Start container
 scheduler = get_scheduler
 try:
 container_id = await scheduler.start_task(
 task=task,
 git_credentials=git_credentials,
 mode=request.mode,
 )
 except RuntimeError as e:
 raise HTTPException(status_code=500, detail=str(e))
 # Update task status
 now = datetime.utcnow
 if request.mode == "plan":
 task.status = TaskStatus.PLANNING
 task.plan_started_at = now
 else:
 task.status = TaskStatus.EXECUTING
 task.execute_started_at = now
 task.updated_at = now
 await db.commit
 await db.refresh(task)
 return TaskExecuteResponse(
 task_id=str(task.id),
 container_id=container_id[:12],
 mode=request.mode,
 message=f"Task execution started in {request.mode} mode",
 )
@router.post("/{task_id}/status")
async def update_task_status_from_container(
 task_id: str,
 update: TaskStatusUpdate,
 db: AsyncSession = Depends(get_db),
):
 """Receive status update from task container.
 This endpoint is called by the task container to report progress.
 """
 result = await db.execute(select(Task).where(Task.id == task_id))
 task = result.scalar_one_or_none
 if not task:
 raise HTTPException(status_code=404, detail="Task not found")
 now = datetime.utcnow
 details = update.details or {}
 # Handle different status updates
 if update.status == "plan_ready":
 task.status = TaskStatus.PLAN_REVIEW
 task.plan_completed_at = now
 task.plan_output = details.get("plan", "")
 elif update.status == "execution_complete":
 task.status = TaskStatus.CODE_REVIEW
 task.execute_completed_at = now
 task.branch_name = details.get("branch_name")
 task.commit_sha = details.get("commit_sha")
 elif update.status == "error":
 task.status = TaskStatus.FAILED
 task.error_message = update.message
 task.retry_count += 1
 elif update.status in ("started", "git_ready", "no_changes"):
 # Log only, no state change
 pass
 task.updated_at = now
 await db.commit
 return {"status": "ok", "task_status": task.status}
@router.post("/{task_id}/stop")
async def stop_task(
 task_id: str,
 force: bool = Query(False, description="Force kill the container"),
 db: AsyncSession = Depends(get_db),
):
 """Stop a running task container."""
 result = await db.execute(select(Task).where(Task.id == task_id))
 task = result.scalar_one_or_none
 if not task:
 raise HTTPException(status_code=404, detail="Task not found")
 scheduler = get_scheduler
 stopped = await scheduler.stop_task(task_id, force=force)
 if stopped:
 task.status = TaskStatus.FAILED
 task.error_message = "Task stopped by user"
 task.updated_at = datetime.utcnow
 await db.commit
 return {"status": "stopped", "message": "Task container stopped"}
 else:
 return {"status": "not_found", "message": "No running container found for task"}
@router.get("/{task_id}/logs")
async def get_task_logs(
 task_id: str,
 tail: int = Query(100, ge=1, le=1000),
 db: AsyncSession = Depends(get_db),
):
 """Get logs from task container."""
 result = await db.execute(select(Task).where(Task.id == task_id))
 task = result.scalar_one_or_none
 if not task:
 raise HTTPException(status_code=404, detail="Task not found")
 scheduler = get_scheduler
 logs = await scheduler.get_task_logs(task_id, tail=tail)
 if logs is None:
 raise HTTPException(status_code=404, detail="No container found for task")
 return {"task_id": task_id, "logs": logs}
@router.get("/{task_id}/container-status")
async def get_container_status(
 task_id: str,
 db: AsyncSession = Depends(get_db),
):
 """Get container status for a task."""
 result = await db.execute(select(Task).where(Task.id == task_id))
 task = result.scalar_one_or_none
 if not task:
 raise HTTPException(status_code=404, detail="Task not found")
 scheduler = get_scheduler
 status = await scheduler.get_task_status(task_id)
 if status is None:
 return {"task_id": task_id, "container": None}
 return {"task_id": task_id, "container": status}
