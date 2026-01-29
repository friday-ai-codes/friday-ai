"""Workflow template loader.
This module provides utilities for loading workflow templates from JSON files
and creating Workflow instances from them.
"""
import json
from pathlib import Path
from typing import Any
import structlog
logger = structlog.get_logger
TEMPLATES_DIR = Path(__file__).parent
def list_templates -> list[dict]:
 """List all available workflow templates.
 Returns:
 List of template metadata dicts with id, name, description.
 """
 templates =
 for f in TEMPLATES_DIR.glob("*.json"):
 try:
 with open(f) as fp:
 data = json.load(fp)
 templates.append(
 {
 "template_id": data.get("template_id", f.stem),
 "name": data.get("name", f.stem),
 "description": data.get("description", ""),
 "version": data.get("version", "1.0"),
 }
 )
 except Exception as e:
 logger.warning("failed_to_load_template", file=str(f), error=str(e))
 return templates
def load_template(template_id: str) -> dict:
 """Load a template definition by ID.
 Args:
 template_id: The template identifier (filename without .json)
 Returns:
 Template definition dict
 Raises:
 ValueError: If template not found
 """
 template_path = TEMPLATES_DIR / f"{template_id}.json"
 if not template_path.exists:
 raise ValueError(f"Template not found: {template_id}")
 with open(template_path) as f:
 return json.load(f)
def create_workflow_from_template(
 project_id: str,
 template_id: str,
 name: str | None = None,
 description: str | None = None,
 created_by=None,
) -> Any:
 """Create a Workflow instance from a template.
 Args:
 project_id: The project to create the workflow in
 template_id: The template to use
 name: Optional custom name (defaults to template name)
 description: Optional custom description
 created_by: The user creating the workflow
 Returns:
 The created Workflow instance
 """
 from workflows.models import Workflow, WorkflowEdge, WorkflowNode
 template = load_template(template_id)
 # Create workflow
 workflow = Workflow.objects.create(
 name=name or template.get("name", template_id),
 description=description or template.get("description", ""),
 project_id=project_id,
 created_by=created_by,
 trigger_type="manual",
 metadata={
 "template_id": template_id,
 "template_version": template.get("version", "1.0"),
 },
 )
 # Create nodes
 node_id_map: dict[str, str] = {} # template_id -> db_id
 for node_data in template.get("nodes", ):
 position = node_data.get("position", {})
 node = WorkflowNode.objects.create(
 workflow=workflow,
 node_type=node_data["type"],
 name=node_data.get("name", node_data["type"]),
 description=node_data.get("description", ""),
 position_x=position.get("x", 0),
 position_y=position.get("y", 0),
 config=node_data.get("config", {}),
 )
 node_id_map[node_data["id"]] = str(node.id)
 # Create edges
 for edge_data in template.get("edges", ):
 source_id = node_id_map.get(edge_data["source"])
 target_id = node_id_map.get(edge_data["target"])
 if not source_id or not target_id:
 logger.warning(
 "edge_node_not_found",
 source=edge_data["source"],
 target=edge_data["target"],
 )
 continue
 WorkflowEdge.objects.create(
 workflow=workflow,
 source_node_id=source_id,
 target_node_id=target_id,
 source_handle=edge_data.get("source_handle", "default"),
 target_handle=edge_data.get("target_handle", "default"),
 label=edge_data.get("label", ""),
 )
 logger.info(
 "workflow_created_from_template",
 workflow_id=str(workflow.id),
 template_id=template_id,
 node_count=len(node_id_map),
 )
 return workflow
async def acreate_workflow_from_template(
 project_id: str,
 template_id: str,
 name: str | None = None,
 description: str | None = None,
 created_by=None,
) -> Any:
 """Async version of create_workflow_from_template."""
 from asgiref.sync import sync_to_async
 return await sync_to_async(create_workflow_from_template)(
 project_id=project_id,
 template_id=template_id,
 name=name,
 description=description,
 created_by=created_by,
 )
