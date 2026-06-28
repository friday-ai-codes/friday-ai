"""内置 reaction 执行器（Chassis v2 · P4）。

为 P0 ``runtime`` 注册表补充两个 target 执行器，均**复用既有客户端/逻辑**：

- ``feishu_doc_create``：飞书云文档生成（复用 ``FeishuDocClient``，同 feishu_doc_create 节点）。
- ``writeback``：飞书工作项字段回写（复用 ``FeishuClient.update_field``）。

注册副作用经 import 触发（在 ``workflows.apps`` 的 ``ready()`` 顶部 import 本模块）。

约束（见 WORKFLOW-RUNTIME-SPEC §4/§7）：
- 执行体 best-effort，失败抛出由 runtime 记 ``ReactionExecution.failed``（non_blocking
  绝不反噬主交付链路）；幂等由 runtime 唯一键保证（重放不重复副作用）。
- 异步上下文不裸访问 lazy-FK：project 解析走 ``sync_to_async``。
- 凭证不入日志（仅记 reaction_id / signal / 结果布尔）。
"""

from __future__ import annotations

from typing import Any

import structlog
from asgiref.sync import sync_to_async

from workflows.models.reaction import WorkflowReaction
from workflows.reactions.runtime import register_executor
from workflows.reactions.signal import Signal

logger = structlog.get_logger(__name__)


@sync_to_async
def _resolve_project(execution: Any) -> Any:
    """从工作流执行解析所属项目（Space）。避免异步上下文裸访问 lazy-FK。"""
    from workflows.models import WorkflowExecution

    execution_id = getattr(execution, "id", None)
    if execution_id is not None:
        we = (
            WorkflowExecution.objects.select_related("workflow__space")
            .filter(id=execution_id)
            .first()
        )
        if we is not None and we.workflow is not None:
            return we.workflow.space
    return None


@register_executor("feishu_doc_create")
async def exec_feishu_doc_create(
    reaction: WorkflowReaction, execution: Any, signal: Signal
) -> dict:
    """飞书文档生成反应：复用 ``FeishuDocClient``（同 feishu_doc_create 节点逻辑）。"""
    config = reaction.config or {}
    title = str(config.get("title") or "").strip()
    content = config.get("content") or ""
    if not title or not content:
        raise ValueError("飞书文档反应缺少 title/content")

    project = await _resolve_project(execution)
    if project is None:
        raise ValueError("无法解析所属项目，无法创建飞书文档")

    folder_token = str(config.get("folder_token") or "").strip() or (
        getattr(project, "feishu_doc_folder_token", None) or ""
    )
    if not folder_token:
        raise ValueError("未配置飞书文档文件夹 Token（反应配置或项目设置）")

    from agents.tools.feishu_doc_tools import create_feishu_doc_client_for_project

    client = await create_feishu_doc_client_for_project(project)
    result = await client.create_document(
        title=title, folder_token=folder_token, content=content
    )
    logger.info(
        "reaction_feishu_doc_created",
        component="reaction_runtime",
        category="caller",
        reaction_id=str(reaction.id),
        signal=signal.name,
    )
    return {
        "document_id": result.get("document_id", ""),
        "document_url": result.get("url", ""),
        "title": title,
    }


@register_executor("writeback")
async def exec_writeback(
    reaction: WorkflowReaction, execution: Any, signal: Signal
) -> dict:
    """飞书工作项字段回写反应：复用 ``FeishuClient.update_field``。"""
    config = reaction.config or {}
    field_key = str(config.get("field_key") or "").strip()
    work_item_id_raw = config.get("work_item_id")
    if not field_key or work_item_id_raw in (None, ""):
        raise ValueError("回写反应缺少 field_key/work_item_id")
    try:
        work_item_id = int(work_item_id_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"工作项 ID 格式错误: {work_item_id_raw}") from exc

    work_item_type = str(config.get("work_item_type") or "story")
    field_value = config.get("field_value")

    project = await _resolve_project(execution)
    if project is None:
        raise ValueError("无法解析所属项目，无法回写字段")

    project_key = str(config.get("project_key") or "").strip() or (
        getattr(project, "feishu_project_key", None) or ""
    )
    if not project_key:
        raise ValueError("无法获取飞书项目 Key")

    from feishu.client import create_feishu_client_for_project

    client = create_feishu_client_for_project(project)
    ok = await client.update_field(
        project_key=project_key,
        work_item_id=work_item_id,
        work_item_type=work_item_type,
        field_key=field_key,
        field_value=field_value,
    )
    logger.info(
        "reaction_writeback_done",
        component="reaction_runtime",
        category="caller",
        reaction_id=str(reaction.id),
        signal=signal.name,
        updated=bool(ok),
    )
    return {"updated": bool(ok)}
