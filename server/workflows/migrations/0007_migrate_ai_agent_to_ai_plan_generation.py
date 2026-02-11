"""Replace deprecated ai_agent node type with ai_plan_generation."""
from django.db import migrations
def migrate_ai_agent_forward(apps, schema_editor):
 WorkflowNode = apps.get_model("workflows", "WorkflowNode")
 WorkflowNode.objects.filter(node_type="ai_agent").update(
 node_type="ai_plan_generation"
 )
def migrate_ai_agent_reverse(apps, schema_editor):
 WorkflowNode = apps.get_model("workflows", "WorkflowNode")
 WorkflowNode.objects.filter(node_type="ai_plan_generation").update(
 node_type="ai_agent"
 )
class Migration(migrations.Migration):
 dependencies = [
 ("workflows", "0006_short_id_for_nodes_edges"),
 ]
 operations = [
 migrations.RunPython(
 migrate_ai_agent_forward,
 migrate_ai_agent_reverse,
 ),
 ]
