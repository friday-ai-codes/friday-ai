"""Data migration: convert ai_technical_plan nodes to ai_plan_generation.
Migrates WorkflowNode records with node_type='ai_technical_plan' to
'ai_plan_generation', resetting config to default values since the two
node types have different config schemas.
This migration is intentionally irreversible (per design decision).
NodeExecution history records are preserved as-is.
"""
from django.db import migrations
# Default config for ai_plan_generation node (matches frontend schema defaults)
DEFAULT_PLAN_GENERATION_CONFIG: dict = {
 "system_prompt": "",
 "user_prompt": "",
 "include_repos":,
 "exclude_repos":,
 "max_iterations": 50,
 "enabled_tools":,
 "chat_id": "",
 "use_custom_api": False,
 "api_base_url": "",
 "api_key": "",
 "model": "",
}
def migrate_technical_plan_nodes(apps, schema_editor):
 """Convert ai_technical_plan nodes to ai_plan_generation."""
 WorkflowNode = apps.get_model("workflows", "WorkflowNode")
 nodes = WorkflowNode.objects.filter(node_type="ai_technical_plan")
 count = nodes.count
 for node in nodes:
 node.node_type = "ai_plan_generation"
 node.config = DEFAULT_PLAN_GENERATION_CONFIG.copy
 node.save(update_fields=["node_type", "config"])
 if count > 0:
 print(f"\n Migrated {count} ai_technical_plan node(s) to ai_plan_generation")
class Migration(migrations.Migration):
 dependencies = [
 ("workflows", "0010_rename_node_types"),
 ]
 operations = [
 migrations.RunPython(
 migrate_technical_plan_nodes,
 migrations.RunPython.noop,
 ),
 ]
