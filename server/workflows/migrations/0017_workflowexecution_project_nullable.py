"""Step 1: 添加 nullable project FK 到 WorkflowExecution。"""
import django.db.models.deletion
from django.db import migrations, models
class Migration(migrations.Migration):
 dependencies = [
 ("workflows", "0016_add_sub_step_progress_to_node_execution"),
 ("projects", "0004_project_default_model_project_default_provider_type"),
 ]
 operations = [
 migrations.AddField(
 model_name="workflowexecution",
 name="project",
 field=models.ForeignKey(
 null=True,
 on_delete=django.db.models.deletion.CASCADE,
 related_name="workflow_executions",
 to="projects.project",
 verbose_name="所属项目",
 ),
 ),
 ]
