"""Tests for workflow template loader.
Covers template discovery, loading, instantiation, and variable rewriting.
"""
import json
from pathlib import Path
import pytest
from workflows.models import Workflow, WorkflowEdge, WorkflowNode
from workflows.nodes.registry import NodeRegistry
from workflows.templates.loader import (
 TEMPLATES_DIR,
 _rewrite_template_refs,
 acreate_workflow_from_template,
 create_workflow_from_template,
 list_templates,
 load_template,
)
class TestListTemplates:
 """Tests for list_templates."""
 def test_list_templates_returns_4(self):
 """list_templates should return all 4 template metadata records."""
 templates = list_templates
 assert len(templates) == 4
 ids = {t["template_id"] for t in templates}
 expected = {
 "code_generation",
 "feishu_full_pipeline",
 "code_review_pipeline",
 "daily_summary",
 }
 assert ids == expected
 def test_list_templates_fields(self):
 """Each template metadata should contain required fields."""
 templates = list_templates
 for t in templates:
 assert "template_id" in t
 assert "name" in t
 assert "description" in t
 assert "version" in t
 assert isinstance(t["name"], str)
 assert len(t["name"]) > 0
class TestLoadTemplate:
 """Tests for load_template."""
 @pytest.mark.parametrize(
 "template_id",
 [
 "code_generation",
 "feishu_full_pipeline",
 "code_review_pipeline",
 "daily_summary",
 ],
 )
 def test_load_each_template(self, template_id):
 """load_template should correctly parse each template JSON."""
 template = load_template(template_id)
 assert "nodes" in template
 assert "edges" in template
 assert isinstance(template["nodes"], list)
 assert isinstance(template["edges"], list)
 assert len(template["nodes"]) > 0
 def test_load_template_not_found(self):
 """Unknown template_id should raise ValueError."""
 with pytest.raises(ValueError, match="Template not found"):
 load_template("non_existent_template")
class TestNodeTypesRegistered:
 """Verify all template node types are registered."""
 @pytest.mark.parametrize(
 "template_id",
 [
 "code_generation",
 "feishu_full_pipeline",
 "code_review_pipeline",
 "daily_summary",
 ],
 )
 def test_node_types_are_registered(self, template_id):
 """Every node type in templates must exist in NodeRegistry."""
 template = load_template(template_id)
 registered = NodeRegistry.get_all_schemas
 registered_types = {n["node_type"] for n in registered}
 for node in template["nodes"]:
 node_type = node["type"]
 assert node_type in registered_types, (
 f"Template '{template_id}' references unregistered node type: {node_type}"
 )
class TestCreateWorkflowFromTemplate:
 """Tests for create_workflow_from_template."""
 def test_create_workflow_from_template(self, db, user):
 """Creating a workflow from template should preserve metadata."""
 from projects.models import Project
 project = Project.objects.create(name="Template Test Project")
 workflow = create_workflow_from_template(
 space_id=str(project.id),
 template_id="code_generation",
 created_by=user,
 )
 assert isinstance(workflow, Workflow)
 assert workflow.metadata.get("template_id") == "code_generation"
 assert workflow.metadata.get("template_version") == "2.0"
 assert workflow.name == "代码生成工作流"
 def test_create_workflow_nodes_and_edges(self, db, user):
 """Created workflow should have nodes and edges from template."""
 from projects.models import Project
 project = Project.objects.create(name="Template Test Project")
 workflow = create_workflow_from_template(
 space_id=str(project.id),
 template_id="daily_summary",
 created_by=user,
 )
 nodes = list(workflow.nodes.all)
 edges = list(workflow.edges.all)
 assert len(nodes) == 4
 assert len(edges) == 3
 node_types = {n.node_type for n in nodes}
 assert "webhook_trigger" in node_types
 assert "http_request" in node_types
 assert "ai_prompt" in node_types
 assert "notify_feishu" in node_types
 @pytest.mark.django_db(transaction=True)
 @pytest.mark.asyncio
 async def test_async_create_workflow_from_template(self, user):
 """Async version should work identically."""
 from projects.models import Project
 project = await Project.objects.acreate(name="Async Template Test")
 workflow = await acreate_workflow_from_template(
 space_id=str(project.id),
 template_id="code_review_pipeline",
 created_by=user,
 )
 assert isinstance(workflow, Workflow)
 assert workflow.metadata.get("template_id") == "code_review_pipeline"
 nodes = [n async for n in workflow.nodes.all]
 assert len(nodes) == 4
class TestRewriteTemplateRefs:
 """Tests for _rewrite_template_refs."""
 def test_rewrite_template_refs(self):
 """Template variables should be rewritten from template_id to short_id."""
 id_map = {"fetch_data": "n_abc123", "summarize": "n_def456"}
 config = {
 "url": "{{nodes.fetch_data.output}}",
 "content": "Result: {{nodes.summarize.result}}",
 "nested": {
 "ref": "{{nodes.fetch_data.input}}",
 },
 "list": [
 "{{nodes.summarize.output}}",
 "static_value",
 ],
 }
 rewritten = _rewrite_template_refs(config, id_map)
 assert rewritten["url"] == "{{nodes.n_abc123.output}}"
 assert rewritten["content"] == "Result: {{nodes.n_def456.result}}"
 assert rewritten["nested"]["ref"] == "{{nodes.n_abc123.input}}"
 assert rewritten["list"][0] == "{{nodes.n_def456.output}}"
 assert rewritten["list"][1] == "static_value"
 def test_rewrite_empty_map(self):
 """Empty id_map should return config unchanged."""
 config = {"url": "{{nodes.fetch_data.output}}"}
 rewritten = _rewrite_template_refs(config, {})
 assert rewritten == config
 def test_rewrite_no_match(self):
 """Variables not in id_map should be left unchanged."""
 id_map = {"fetch_data": "n_abc123"}
 config = {"url": "{{nodes.unknown.output}}"}
 rewritten = _rewrite_template_refs(config, id_map)
 assert rewritten["url"] == "{{nodes.unknown.output}}"
class TestTemplateFileIntegrity:
 """Verify template JSON files are valid and well-formed."""
 @pytest.mark.parametrize(
 "template_id",
 [
 "code_generation",
 "feishu_full_pipeline",
 "code_review_pipeline",
 "daily_summary",
 ],
 )
 def test_template_json_valid(self, template_id):
 """Each template file should be valid JSON with required fields."""
 template_path = TEMPLATES_DIR / f"{template_id}.json"
 assert template_path.exists
 with open(template_path) as f:
 data = json.load(f)
 assert "template_id" in data
 assert "version" in data
 assert "name" in data
 assert "description" in data
 assert "nodes" in data
 assert "edges" in data
 assert data["template_id"] == template_id
 # All nodes must have id, type, position
 for node in data["nodes"]:
 assert "id" in node
 assert "type" in node
 assert "position" in node
 assert "x" in node["position"]
 assert "y" in node["position"]
 # All edges must have source and target
 for edge in data["edges"]:
 assert "source" in edge
 assert "target" in edge
