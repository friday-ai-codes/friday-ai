"""Workflow template loader.

This module provides utilities for loading workflow templates from JSON files
and creating Workflow instances from them.
"""

import json
import re
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

TEMPLATES_DIR = Path(__file__).parent


def list_templates() -> list[dict]:
    """List all available workflow templates.

    Returns:
        List of template metadata dicts with id, name, description.
    """
    templates = []
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
    if not template_path.exists():
        raise ValueError(f"Template not found: {template_id}")

    with open(template_path) as f:
        return json.load(f)


def _validate_template_graph(template: dict, template_id: str) -> None:
    """建库前对模板图执行与保存同源的静态校验（TPL-03 / D-09）。

    把模板的 ``nodes``/``edges`` 转成 ``WorkflowGraphValidator`` 入参形态：
    - ``type`` → ``node_type``；模板节点 id 兼作 ``short_id``（与
      ``rewrite_template_refs(template_to_short)`` 同源的标识符空间），同时填入
      ``id`` 满足 edge 归属校验；
    - 边 ``source``/``target`` → ``source_node_id``/``target_node_id``，保留
      ``source_handle``/``target_handle``。
    若 validator 返回 ``errors`` 非空 → 抛 ``ValueError``（含结构化 errors），
    使 ``acreate`` 在落库前 fail-fast，不产生半残 workflow（view 层已 ValueError→400）。

    validator 为纯 CPU 无 ORM，可在 async 函数中直接同步调用。
    """
    # 延迟导入：避免与 workflows.engine/validation 包初始化形成循环依赖
    from workflows.validation.graph_validator import WorkflowGraphValidator

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

    result = WorkflowGraphValidator().validate(nodes, edges)
    if result["errors"]:
        raise ValueError(
            f"模板 '{template_id}' 图校验未通过，拒绝创建工作流: {result['errors']}"
        )


def _error_handling_fields(node_data: dict) -> dict[str, Any]:
    """从模板节点定义提取错误处理 / 执行控制字段（仅当模板显式声明才覆盖默认）。

    模板节点可选声明 ``on_error``（abort/retry/ignore）、``retry_times``、
    ``retry_delay``、``node_timeout_seconds``、``fallback_values``、``run_condition``。
    未声明的字段不传入，沿用 ``WorkflowNode`` 的模型默认值（向后兼容旧模板）。
    """
    fields: dict[str, Any] = {}
    for key in (
        "on_error",
        "retry_times",
        "retry_delay",
        "node_timeout_seconds",
        "fallback_values",
        "run_condition",
    ):
        if key in node_data and node_data[key] is not None:
            fields[key] = node_data[key]
    return fields


def rewrite_template_refs(config: dict, id_map: dict[str, str]) -> dict:
    """按 id_map 重写 config 中的节点引用标识符（公共重写引擎）。

    递归扫描 config（dict/list/str）中全部字符串值，把 ``{{nodes.<old>.xxx}}``
    与 ``{{$nodes.<old>.xxx}}`` / ``{{$.nodes.<old>.xxx}}`` JSONPath 形式中的
    ``<old>`` 按 id_map 替换为新标识符。id_map 的键经 re.escape 转义，
    恶意字符无法注入正则（T-17-10 双保险之一）。

    Args:
        config: Node config dict
        id_map: 旧标识符 → 新标识符 的映射（模板 ID→short_id，或旧 short_id→新 short_id）

    Returns:
        Config dict with rewritten references
    """
    if not id_map:
        return config

    # 尾断言接受 `.`（字段下钻）或 `[`（JSONPath 下标，如 {{$nodes.xY9[0].v}}），
    # 避免 short_id 重生成时漏写"标识符后直接跟下标"的引用形式（IN-04）
    pattern = re.compile(
        r"\{\{(\s*(?:\$\.?)?nodes\.)(" + "|".join(re.escape(k) for k in id_map) + r")([.\[])"
    )

    def _rewrite_value(value: Any) -> Any:
        if isinstance(value, str):
            return pattern.sub(
                lambda m: "{{" + m.group(1) + id_map[m.group(2)] + m.group(3),
                value,
            )
        if isinstance(value, dict):
            return {k: _rewrite_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_rewrite_value(item) for item in value]
        return value

    return _rewrite_value(config)


def create_workflow_from_template(
    space_id: str,
    template_id: str,
    name: str | None = None,
    description: str | None = None,
    created_by: Any = None,
) -> Any:
    """Create a Workflow instance from a template.

    Args:
        space_id: The space to create the workflow in
        template_id: The template to use
        name: Optional custom name (defaults to template name)
        description: Optional custom description
        created_by: The user creating the workflow

    Returns:
        The created Workflow instance
    """
    from workflows.models import Workflow, WorkflowEdge, WorkflowNode

    template = load_template(template_id)

    # 建库前同源图校验（TPL-03 / D-09）：非法模板拒绝创建，不产生半残 workflow
    _validate_template_graph(template, template_id)

    # Create workflow
    workflow = Workflow.objects.create(
        name=name or template.get("name", template_id),
        description=description or template.get("description", ""),
        project_id=space_id,
        created_by=created_by,
        trigger_type="manual",
        metadata={
            "template_id": template_id,
            "template_version": template.get("version", "1.0"),
        },
    )

    # Phase: Create nodes and build ID mappings
    node_id_map: dict[str, str] = {}  # template_id -> db_uuid
    template_to_short: dict[str, str] = {}  # template_id -> short_id
    created_nodes: list[Any] = []

    for node_data in template.get("nodes", []):
        position = node_data.get("position", {})
        node = WorkflowNode.objects.create(
            workflow=workflow,
            node_type=node_data["type"],
            name=node_data.get("name", node_data["type"]),
            description=node_data.get("description", ""),
            position_x=position.get("x", 0),
            position_y=position.get("y", 0),
            config=node_data.get("config", {}),
            **_error_handling_fields(node_data),
        )
        node_id_map[node_data["id"]] = str(node.id)
        template_to_short[node_data["id"]] = node.short_id
        created_nodes.append(node)

    # Phase: Rewrite template variable references in all node configs
    if template_to_short:
        for node in created_nodes:
            rewritten = rewrite_template_refs(node.config, template_to_short)
            if rewritten != node.config:
                node.config = rewritten
                node.save(update_fields=["config"])

    # Phase: Create edges
    for edge_data in template.get("edges", []):
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
    space_id: str,
    template_id: str,
    name: str | None = None,
    description: str | None = None,
    created_by: Any = None,
) -> Any:
    """Async version of create_workflow_from_template.

    Uses native async ORM calls instead of sync_to_async wrapper.
    """
    from workflows.models import Workflow, WorkflowEdge, WorkflowNode

    template = load_template(template_id)

    # 建库前同源图校验（TPL-03 / D-09）：非法模板拒绝创建，不产生半残 workflow
    _validate_template_graph(template, template_id)

    # Create workflow
    workflow = await Workflow.objects.acreate(
        name=name or template.get("name", template_id),
        description=description or template.get("description", ""),
        project_id=space_id,
        created_by=created_by,
        trigger_type="manual",
        metadata={
            "template_id": template_id,
            "template_version": template.get("version", "1.0"),
        },
    )

    # Phase: Create nodes and build ID mappings
    node_id_map: dict[str, str] = {}  # template_id -> db_uuid
    template_to_short: dict[str, str] = {}  # template_id -> short_id
    created_nodes: list[Any] = []

    for node_data in template.get("nodes", []):
        position = node_data.get("position", {})
        node = await WorkflowNode.objects.acreate(
            workflow=workflow,
            node_type=node_data["type"],
            name=node_data.get("name", node_data["type"]),
            description=node_data.get("description", ""),
            position_x=position.get("x", 0),
            position_y=position.get("y", 0),
            config=node_data.get("config", {}),
            **_error_handling_fields(node_data),
        )
        node_id_map[node_data["id"]] = str(node.id)
        template_to_short[node_data["id"]] = node.short_id
        created_nodes.append(node)

    # Phase: Rewrite template variable references in all node configs
    if template_to_short:
        for node in created_nodes:
            rewritten = rewrite_template_refs(node.config, template_to_short)
            if rewritten != node.config:
                node.config = rewritten
                await node.asave(update_fields=["config"])

    # Phase: Create edges
    for edge_data in template.get("edges", []):
        source_id = node_id_map.get(edge_data["source"])
        target_id = node_id_map.get(edge_data["target"])

        if not source_id or not target_id:
            logger.warning(
                "edge_node_not_found",
                source=edge_data["source"],
                target=edge_data["target"],
            )
            continue

        await WorkflowEdge.objects.acreate(
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
