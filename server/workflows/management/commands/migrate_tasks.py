"""Migrate Task data to WorkflowExecution.
This management command migrates historical Task records to the new
WorkflowExecution model, preserving data and enabling gradual transition.
"""
import structlog
from django.core.management.base import BaseCommand
from django.db import transaction
logger = structlog.get_logger
class Command(BaseCommand):
 """Migrate historical Task data to WorkflowExecution."""
 help = "Migrate historical Task data to WorkflowExecution"
 def add_arguments(self, parser):
 parser.add_argument(
 "--dry-run",
 action="store_true",
 help="Simulate migration without making changes",
 )
 parser.add_argument(
 "--project-id",
 type=str,
 help="Only migrate Tasks from specified project",
 )
 parser.add_argument(
 "--limit",
 type=int,
 default=0,
 help="Limit number of tasks to migrate (0=unlimited)",
 )
 parser.add_argument(
 "--rollback",
 action="store_true",
 help="Rollback migrated data (delete WorkflowExecutions with legacy_task_id)",
 )
 def handle(self, *args, **options):
 dry_run = options["dry_run"]
 project_id = options.get("project_id")
 limit = options.get("limit", 0)
 rollback = options.get("rollback", False)
 if rollback:
 self._handle_rollback(dry_run)
 return
 # Import here to avoid circular imports
 from tasks.models import Task
 # Build query
 queryset = Task.objects.all.order_by("created_at")
 if project_id:
 queryset = queryset.filter(project_id=project_id)
 if limit > 0:
 queryset = queryset[:limit]
 total = queryset.count
 self.stdout.write(f"Found {total} tasks to migrate")
 if dry_run:
 self.stdout.write(self.style.WARNING("DRY RUN - No changes will be made"))
 success = 0
 failed = 0
 skipped = 0
 for task in queryset:
 try:
 if self._is_already_migrated(task):
 skipped += 1
 continue
 if not dry_run:
 self._migrate_task(task)
 success += 1
 self.stdout.write(f"✓ Migrated: {task.id} ({task.title[:30]}...)")
 except Exception as e:
 failed += 1
 self.stdout.write(self.style.ERROR(f"✗ Failed: {task.id} - {e}"))
 logger.exception("task_migration_failed", task_id=str(task.id))
 self.stdout.write(
 self.style.SUCCESS(
 f"\nCompleted: {success} migrated, {skipped} skipped, {failed} failed"
 )
 )
 def _is_already_migrated(self, task) -> bool:
 """Check if task has already been migrated."""
 from workflows.models import WorkflowExecution
 return WorkflowExecution.objects.filter(context__legacy_task_id=str(task.id)).exists
 @transaction.atomic
 def _migrate_task(self, task):
 """Migrate a single Task to WorkflowExecution."""
 from workflows.models import (
 WorkflowExecution,
 )
 from workflows.templates.loader import create_workflow_from_template
 # 1. Create Workflow from template
 workflow = create_workflow_from_template(
 project_id=str(task.project_id),
 template_id="code_generation",
 name=task.title,
 description=task.description or "",
 )
 # 2. Create WorkflowExecution
 execution = WorkflowExecution.objects.create(
 workflow=workflow,
 trigger_type="migration",
 status=self._map_task_status(task.status),
 input_data={
 "title": task.title,
 "description": task.description or "",
 },
 context={
 "legacy_task_id": str(task.id),
 "work_item_id": getattr(task, "work_item_id", None),
 "branch_name": getattr(task, "branch_name", None),
 "commit_sha": getattr(task, "commit_sha", None),
 "pr_url": getattr(task, "pr_url", None),
 },
 error_message=getattr(task, "error_message", "") or "",
 )
 # Update timestamps to match original
 WorkflowExecution.objects.filter(id=execution.id).update(created_at=task.created_at)
 # 3. Create NodeExecution records based on task status
 self._create_node_executions(execution, task, workflow)
 logger.info(
 "task_migrated",
 task_id=str(task.id),
 execution_id=str(execution.id),
 )
 return execution
 def _map_task_status(self, task_status: str) -> str:
 """Map Task status to WorkflowExecution status."""
 from workflows.models import WorkflowExecutionStatus
 # Import task status if available
 try:
 from tasks.models import TaskStatus
 mapping = {
 TaskStatus.PENDING: WorkflowExecutionStatus.PENDING,
 TaskStatus.PLANNING: WorkflowExecutionStatus.RUNNING,
 TaskStatus.PLAN_REVIEW: WorkflowExecutionStatus.RUNNING,
 TaskStatus.EXECUTING: WorkflowExecutionStatus.RUNNING,
 TaskStatus.CODE_REVIEW: WorkflowExecutionStatus.RUNNING,
 TaskStatus.MERGED: WorkflowExecutionStatus.COMPLETED,
 TaskStatus.FAILED: WorkflowExecutionStatus.FAILED,
 }
 return mapping.get(task_status, WorkflowExecutionStatus.PENDING)
 except ImportError:
 # Fallback for string-based status
 status_map = {
 "pending": WorkflowExecutionStatus.PENDING,
 "planning": WorkflowExecutionStatus.RUNNING,
 "plan_review": WorkflowExecutionStatus.RUNNING,
 "executing": WorkflowExecutionStatus.RUNNING,
 "code_review": WorkflowExecutionStatus.RUNNING,
 "merged": WorkflowExecutionStatus.COMPLETED,
 "failed": WorkflowExecutionStatus.FAILED,
 }
 return status_map.get(task_status.lower, WorkflowExecutionStatus.PENDING)
 def _create_node_executions(self, execution, task, workflow):
 """Create NodeExecution records based on Task status."""
 from workflows.models import NodeExecution, NodeExecutionStatus
 # Get nodes by type
 nodes = {n.node_type: n for n in workflow.nodes.all}
 # Status progression mapping
 status_progression = [
 ("planning", "generate_plan"),
 ("plan_review", "human_approval"), # First approval
 ("executing", "code_implement"),
 ("code_review", "human_approval"), # Second approval (handled specially)
 ("merged", "create_pr"),
 ]
 task_status = (
 task.status.lower if hasattr(task.status, "lower") else str(task.status).lower
 )
 # Find current position in progression
 current_index = -1
 for i, (status, _) in enumerate(status_progression):
 if status in task_status:
 current_index = i
 break
 # Create node executions for trigger
 if "manual_trigger" in nodes:
 NodeExecution.objects.create(
 workflow_execution=execution,
 node=nodes["manual_trigger"],
 status=NodeExecutionStatus.COMPLETED,
 output_data={"migrated": True},
 )
 # Create node executions based on progress
 approval_count = 0
 for i, (_, node_type) in enumerate(status_progression):
 # Handle multiple approval nodes
 if node_type == "human_approval":
 approval_count += 1
 # Find the right approval node
 approval_nodes = [
 n for n in workflow.nodes.all if n.node_type == "human_approval"
 ]
 if approval_count <= len(approval_nodes):
 node = approval_nodes[approval_count - 1]
 else:
 continue
 elif node_type in nodes:
 node = nodes[node_type]
 else:
 continue
 if i < current_index:
 # Completed nodes
 NodeExecution.objects.create(
 workflow_execution=execution,
 node=node,
 status=NodeExecutionStatus.COMPLETED,
 output_data={"migrated": True},
 )
 elif i == current_index:
 # Current node
 if "approval" in node_type or "review" in task_status:
 status = NodeExecutionStatus.WAITING_APPROVAL
 else:
 status = NodeExecutionStatus.RUNNING
 NodeExecution.objects.create(
 workflow_execution=execution,
 node=node,
 status=status,
 )
 def _handle_rollback(self, dry_run: bool):
 """Rollback migrated data."""
 from workflows.models import WorkflowExecution
 migrated = WorkflowExecution.objects.filter(context__has_key="legacy_task_id")
 count = migrated.count
 self.stdout.write(f"Found {count} migrated executions to rollback")
 if dry_run:
 self.stdout.write(self.style.WARNING("DRY RUN - No changes will be made"))
 return
 # Delete workflows (cascades to executions and nodes)
 workflow_ids = list(migrated.values_list("workflow_id", flat=True))
 from workflows.models import Workflow
 deleted = Workflow.objects.filter(id__in=workflow_ids).delete
 self.stdout.write(self.style.SUCCESS(f"Rollback complete: {deleted[0]} objects deleted"))
