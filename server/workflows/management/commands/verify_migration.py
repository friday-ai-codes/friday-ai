"""Verify Task to WorkflowExecution migration results."""
from django.core.management.base import BaseCommand
class Command(BaseCommand):
 """Verify Task migration results."""
 help = "Verify Task to WorkflowExecution migration results"
 def handle(self, *args, **options):
 from tasks.models import Task
 from workflows.models import WorkflowExecution
 task_count = Task.objects.count
 migrated_count = WorkflowExecution.objects.filter(
 context__has_key="legacy_task_id"
 ).count
 self.stdout.write(f"Total Tasks: {task_count}")
 self.stdout.write(f"Migrated: {migrated_count}")
 self.stdout.write(f"Remaining: {task_count - migrated_count}")
 # Check for issues
 issues =
 # Check for duplicate migrations
 from django.db.models import Count
 duplicates = (
 WorkflowExecution.objects.filter(context__has_key="legacy_task_id")
 .values("context__legacy_task_id")
 .annotate(count=Count("id"))
 .filter(count__gt=1)
 )
 if duplicates.exists:
 issues.append(f"Found {duplicates.count} duplicate migrations")
 # Check for orphaned executions
 orphaned = WorkflowExecution.objects.filter(
 context__has_key="legacy_task_id",
 workflow__isnull=True,
 ).count
 if orphaned > 0:
 issues.append(f"Found {orphaned} orphaned executions")
 if issues:
 for issue in issues:
 self.stdout.write(self.style.WARNING(f"⚠ {issue}"))
 elif task_count == migrated_count:
 self.stdout.write(self.style.SUCCESS("✓ All tasks migrated successfully!"))
 else:
 self.stdout.write(
 self.style.WARNING(
 f"⚠ Migration incomplete: {task_count - migrated_count} tasks remaining"
 )
 )
