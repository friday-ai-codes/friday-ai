"""Tests for workflow template loader.

Covers template discovery, loading, instantiation, and variable rewriting.
"""

import json
from copy import deepcopy

import pytest

from workflows.models import Workflow
from workflows.nodes.registry import NodeRegistry
from workflows.templates.loader import (
    TEMPLATES_DIR,
    acreate_workflow_from_template,
    create_workflow_from_template,
    list_templates,
    load_template,
    rewrite_template_refs,
)
from workflows.validation.graph_validator import WorkflowGraphValidator

ALL_TEMPLATE_IDS = [
    "code_generation",
    "feishu_full_pipeline",
    "daily_summary",
]


def _template_to_validator_inputs(template: dict) -> tuple[list[dict], list[dict]]:
    """把模板 JSON 转成 WorkflowGraphValidator 入参（与 loader 同源口径）。

    ``type`` → ``node_type``；模板节点 id 兼作 ``short_id`` 与 ``id``；边
    ``source``/``target`` → ``source_node_id``/``target_node_id``，保留 handle。
    """
    nodes = [
        {
            "id": n["id"],
            "short_id": n["id"],
            "node_type": n.get("type"),
            "config": n.get("config", {}),
        }
        for n in template.get("nodes", [])
    ]
    edges = [
        {
            "source_node_id": e.get("source"),
            "target_node_id": e.get("target"),
            "source_handle": e.get("source_handle", "default"),
            "target_handle": e.get("target_handle", "default"),
        }
        for e in template.get("edges", [])
    ]
    return nodes, edges


class TestListTemplates:
    """Tests for list_templates()."""

    def test_list_templates_returns_3(self):
        """list_templates() should return all 3 template metadata records."""
        templates = list_templates()
        assert len(templates) == 3

        ids = {t["template_id"] for t in templates}
        expected = {
            "code_generation",
            "feishu_full_pipeline",
            "daily_summary",
        }
        assert ids == expected

    def test_list_templates_fields(self):
        """Each template metadata should contain required fields."""
        templates = list_templates()
        for t in templates:
            assert "template_id" in t
            assert "name" in t
            assert "description" in t
            assert "version" in t
            assert isinstance(t["name"], str)
            assert len(t["name"]) > 0


class TestLoadTemplate:
    """Tests for load_template()."""

    @pytest.mark.parametrize(
        "template_id",
        [
            "code_generation",
            "feishu_full_pipeline",
            "daily_summary",
        ],
    )
    def test_load_each_template(self, template_id):
        """load_template() should correctly parse each template JSON."""
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
            "daily_summary",
        ],
    )
    def test_node_types_are_registered(self, template_id):
        """Every node type in templates must exist in NodeRegistry."""
        template = load_template(template_id)
        registered = NodeRegistry.get_all_schemas()
        registered_types = {n["node_type"] for n in registered}

        for node in template["nodes"]:
            node_type = node["type"]
            assert node_type in registered_types, (
                f"Template '{template_id}' references unregistered node type: {node_type}"
            )


class TestCreateWorkflowFromTemplate:
    """Tests for create_workflow_from_template()."""

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

        nodes = list(workflow.nodes.all())
        edges = list(workflow.edges.all())

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
            template_id="code_generation",
            created_by=user,
        )

        assert isinstance(workflow, Workflow)
        assert workflow.metadata.get("template_id") == "code_generation"
        nodes = [n async for n in workflow.nodes.all()]
        # code_generation：trigger + generate_plan + plan_approval + ai_coding
        assert len(nodes) == 4


class TestRewriteTemplateRefs:
    """Tests for rewrite_template_refs()."""

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

        rewritten = rewrite_template_refs(config, id_map)

        assert rewritten["url"] == "{{nodes.n_abc123.output}}"
        assert rewritten["content"] == "Result: {{nodes.n_def456.result}}"
        assert rewritten["nested"]["ref"] == "{{nodes.n_abc123.input}}"
        assert rewritten["list"][0] == "{{nodes.n_def456.output}}"
        assert rewritten["list"][1] == "static_value"

    def test_rewrite_empty_map(self):
        """Empty id_map should return config unchanged."""
        config = {"url": "{{nodes.fetch_data.output}}"}
        rewritten = rewrite_template_refs(config, {})
        assert rewritten == config

    def test_rewrite_no_match(self):
        """Variables not in id_map should be left unchanged."""
        id_map = {"fetch_data": "n_abc123"}
        config = {"url": "{{nodes.unknown.output}}"}
        rewritten = rewrite_template_refs(config, id_map)
        assert rewritten["url"] == "{{nodes.unknown.output}}"

    def test_rewrite_subscript_form(self):
        """IN-04：标识符后直接跟 `[` 下标的 JSONPath 形式也要被重写。"""
        id_map = {"xY9": "Qw2"}
        config = {
            "a": "{{$nodes.xY9[0].v}}",
            "b": "{{nodes.xY9[2]}}",
            "c": "{{$.nodes.xY9[*].name}}",
            # 前缀部分匹配的标识符不受影响
            "d": "{{nodes.xY9z[0].v}}",
        }
        rewritten = rewrite_template_refs(config, id_map)
        assert rewritten["a"] == "{{$nodes.Qw2[0].v}}"
        assert rewritten["b"] == "{{nodes.Qw2[2]}}"
        assert rewritten["c"] == "{{$.nodes.Qw2[*].name}}"
        assert rewritten["d"] == "{{nodes.xY9z[0].v}}"


class TestTemplateFileIntegrity:
    """Verify template JSON files are valid and well-formed."""

    @pytest.mark.parametrize(
        "template_id",
        [
            "code_generation",
            "feishu_full_pipeline",
            "daily_summary",
        ],
    )
    def test_template_json_valid(self, template_id):
        """Each template file should be valid JSON with required fields."""
        template_path = TEMPLATES_DIR / f"{template_id}.json"
        assert template_path.exists()

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


class TestTemplateGraphValidation:
    """TPL-02：每个内置模板经 WorkflowGraphValidator 校验均零 error。"""

    @pytest.mark.parametrize("template_id", ALL_TEMPLATE_IDS)
    def test_template_validates_with_zero_errors(self, template_id):
        """每个内置模板转 validator 入参后 errors 必须为空（契约一致性守护）。"""
        template = load_template(template_id)
        nodes, edges = _template_to_validator_inputs(template)
        result = WorkflowGraphValidator().validate(nodes, edges)
        assert result["errors"] == [], (
            f"模板 '{template_id}' 不应有校验错误，实际: {result['errors']}"
        )


class TestTemplateBreakageInjection:
    """TPL-02：人为注入 schema 可判定的断裂 → validator errors 非空且 reason 命中。

    注入路径仅使用 ai_prompt（有输出 schema）与 ghost（不存在）节点，
    **禁止用 http 节点字段做坏变量注入**——http 无输出 schema，字段层会被跳过
    导致假绿（Pitfall 3）。
    """

    def test_inject_bad_node_type(self):
        """注入非法 node_type → unknown_node_type error。"""
        template = deepcopy(load_template("daily_summary"))
        template["nodes"][0]["type"] = "totally_not_a_real_node_type"
        nodes, edges = _template_to_validator_inputs(template)
        result = WorkflowGraphValidator().validate(nodes, edges)
        reasons = {e["reason"] for e in result["errors"]}
        assert "unknown_node_type" in reasons

    def test_inject_missing_required_config(self):
        """删除 ai_prompt 必填 config（user_prompt）→ config_schema_invalid error。"""
        template = deepcopy(load_template("daily_summary"))
        for node in template["nodes"]:
            if node["id"] == "summarize":  # ai_prompt，required: ["user_prompt"]
                node["config"].pop("user_prompt", None)
        nodes, edges = _template_to_validator_inputs(template)
        result = WorkflowGraphValidator().validate(nodes, edges)
        reasons = {e["reason"] for e in result["errors"]}
        assert "config_schema_invalid" in reasons

    def test_inject_nonexistent_field_on_schema_node(self):
        """{{nodes.summarize.nonexistent_field}}（ai_prompt 有 schema）→ field_not_found。"""
        template = deepcopy(load_template("daily_summary"))
        for node in template["nodes"]:
            if node["id"] == "summarize":  # ai_prompt 输出 schema 含 text/response 等
                node["config"]["user_prompt"] = "{{nodes.summarize.nonexistent_field}}"
        nodes, edges = _template_to_validator_inputs(template)
        result = WorkflowGraphValidator().validate(nodes, edges)
        reasons = {e["reason"] for e in result["errors"]}
        assert "field_not_found" in reasons

    def test_inject_ghost_node_reference(self):
        """{{nodes.ghost.x}}（节点不存在）→ node_not_found error。"""
        template = deepcopy(load_template("daily_summary"))
        for node in template["nodes"]:
            if node["id"] == "summarize":
                node["config"]["user_prompt"] = "汇总：{{nodes.ghost.x}}"
        nodes, edges = _template_to_validator_inputs(template)
        result = WorkflowGraphValidator().validate(nodes, edges)
        reasons = {e["reason"] for e in result["errors"]}
        assert "node_not_found" in reasons

    def test_inject_bad_source_handle(self):
        """坏 source_handle（不在 ai_prompt 输出端口）→ invalid_source_handle error。"""
        template = deepcopy(load_template("daily_summary"))
        for edge in template["edges"]:
            # summarize（ai_prompt，输出端口仅 default/error）→ notify
            if edge["source"] == "summarize" and edge["target"] == "notify":
                edge["source_handle"] = "nonexistent_output_port"
        nodes, edges = _template_to_validator_inputs(template)
        result = WorkflowGraphValidator().validate(nodes, edges)
        reasons = {e["reason"] for e in result["errors"]}
        assert "invalid_source_handle" in reasons


class TestLoaderPreCreateValidation:
    """TPL-03：loader 在建库前调同一 validator，非法模板拒绝且无 workflow 落库。"""

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_acreate_rejects_invalid_template(self, user, monkeypatch):
        """注入断裂模板经 acreate_workflow_from_template → ValueError 且 DB 无新 workflow。"""
        from projects.models import Project
        from workflows.templates import loader as loader_mod

        project = await Project.objects.acreate(name="Reject Test Project")

        broken = deepcopy(load_template("daily_summary"))
        # 注入 schema 可判定断裂：非法 node_type
        for node in broken["nodes"]:
            if node["id"] == "summarize":
                node["type"] = "totally_not_a_real_node_type"

        # acreate 内部以模块全局名调用 load_template，monkeypatch 即可注入断裂模板
        monkeypatch.setattr(loader_mod, "load_template", lambda tid: deepcopy(broken))

        before = await Workflow.objects.acount()
        with pytest.raises(ValueError, match="图校验未通过"):
            await acreate_workflow_from_template(
                space_id=str(project.id),
                template_id="daily_summary",
                created_by=user,
            )
        after = await Workflow.objects.acount()
        assert before == after, "非法模板不应产生半残 workflow"

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_acreate_accepts_valid_templates(self, user):
        """4 个合法内置模板经 acreate_workflow_from_template 均成功创建（回归不破）。"""
        from projects.models import Project

        project = await Project.objects.acreate(name="Valid Templates Project")
        for template_id in ALL_TEMPLATE_IDS:
            workflow = await acreate_workflow_from_template(
                space_id=str(project.id),
                template_id=template_id,
                created_by=user,
            )
            assert isinstance(workflow, Workflow)
            assert workflow.metadata.get("template_id") == template_id


class TestTemplateFieldAlignmentRegression:
    """TPL-01：守护 daily_summary 修复不回退到坏字段。"""

    def test_daily_summary_references_real_output_fields(self):
        """daily_summary 引用真实输出字段（body/text），不回退到 output 坏字段。"""
        template = load_template("daily_summary")
        blob = json.dumps(template, ensure_ascii=False)
        assert "{{nodes.fetch_data.body}}" in blob
        assert "{{nodes.summarize.text}}" in blob
        assert "{{nodes.fetch_data.output}}" not in blob
        assert "{{nodes.summarize.output}}" not in blob

        # validator 对修复后的字段引用零 error（不回退守护）
        nodes, edges = _template_to_validator_inputs(template)
        result = WorkflowGraphValidator().validate(nodes, edges)
        assert result["errors"] == []
