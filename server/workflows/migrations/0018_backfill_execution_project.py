"""Step 2: RunPython 回填 WorkflowExecution.project（从 workflow.project 复制）。"""
from django.db import migrations
def backfill_execution_project(apps, schema_editor):
 """回填 WorkflowExecution.project_id = workflow.project_id。"""
 WorkflowExecution = apps.get_model("workflows", "WorkflowExecution")
 queryset = WorkflowExecution.objects.filter(project__isnull=True).select_related(
 "workflow"
 )
 count = 0
 for execution in queryset.iterator:
 execution.project_id = execution.workflow.project_id
 execution.save(update_fields=["project_id"])
 count += 1
 if count:
 print(f" 已回填 {count} 条 WorkflowExecution.project")
 # 断言零 NULL 残留
 remaining = WorkflowExecution.objects.filter(project__isnull=True).count
 assert remaining == 0, f"回填后仍有 {remaining} 条 NULL project"
def reverse_backfill(apps, schema_editor):
 """反向操作：将所有 project 设为 NULL。"""
 WorkflowExecution = apps.get_model("workflows", "WorkflowExecution")
 WorkflowExecution.objects.all.update(project=None)
class Migration(migrations.Migration):
 dependencies = [
 ("workflows", "0017_workflowexecution_project_nullable"),
 ]
 operations = [
 migrations.RunPython(backfill_execution_project, reverse_backfill),
 ]
