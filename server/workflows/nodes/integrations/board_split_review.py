"""看板拆分评审节点（BOARD-02，87-04）。

``BoardSplitReviewNode``：把 87-03 的拆分能力包成「拉群 + bot 入群 + 流式结果卡片 +
人机协同多轮重拆」的交互回路。

execute 流程：
  ① 解析空间 + 项目 + member_ids；
  ② ``ProjectService.resolve_or_create_group`` 复用/建项目群 + bot 入群（空 → failed）；
  ③ ``BoardSplitService.propose_split`` 拿拆分提案；
  ④ CardKit 流式下发（create_card_entity → send_card_entity → stream_card_content →
     settle_card_stream，sequence 严格递增），流式失败 fail-soft 降级普通 send_card；
  ⑤ 建 ``WorkflowEventSubscription``（event_type=BoardSplitCallback，超时兜底）；
  ⑥ 返回 ``waiting_event``，``output_data`` 持久化提案/来源/轮次（供回调重拆/建看板复用）。

回调由 ``feishu.callbacks.board_split_callback`` 处理（开始创建 / 多轮重拆）。
自动注册：放在 ``workflows/nodes/integrations/`` 下且声明 ``node_type`` 即被发现。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, ClassVar

import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone

from feishu.cards.board_split_card import build_board_split_card, render_proposal_markdown
from initiatives.services.board_split_service import BoardSplitService
from initiatives.services.project_service import ProjectService
from services.feishu_im import FeishuIMService
from workflows.models.execution import WorkflowEventSubscription
from workflows.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeCategory,
    NodePort,
    NodeResult,
    PortType,
)
from workflows.nodes.integrations.feishu_chat import _parse_id_list
from workflows.nodes.registry import register_node

logger = structlog.get_logger(__name__)

_COMPONENT = "board_split"
_STREAM_ELEMENT_ID = "split_md"


async def _resolve_space(context: ExecutionContext):
    """异步安全解析工作流关联空间（规避同步 ORM 懒加载）。"""
    execution = context.workflow_execution
    if execution is None:
        return None
    return await sync_to_async(lambda: execution.workflow.space)()


@sync_to_async
def _aresolve_project(space: Any):
    """解析 space 对应的 Project（优先 feishu_project_key 命中，否则首个；预载 space）。"""
    from initiatives.models import Project

    qs = Project.objects.filter(space=space).select_related("space")
    project_key = getattr(space, "feishu_project_key", "") or ""
    if project_key:
        matched = qs.filter(feishu_project_key=project_key).first()
        if matched is not None:
            return matched
    return qs.first()


@register_node
class BoardSplitReviewNode(BaseNode):
    """看板拆分评审节点：拉群 + 流式发卡 + waiting_event（委托 87-03 服务 + v0.11 CardKit）。"""

    node_type: ClassVar[str] = "board_split_review"
    display_name: ClassVar[str] = "看板拆分评审"
    description: ClassVar[str] = "拆分 feature list 并在项目群以流式卡片确认（开始创建/多轮重拆）"
    icon: ClassVar[str] = "layout-grid"
    category: ClassVar[NodeCategory] = NodeCategory.INTEGRATION
    execution_mode: ClassVar[str] = "server_local"
    is_blocking: ClassVar[bool] = True

    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "feature_list_url": {
                "type": "string",
                "title": "飞书文档链接",
                "description": "feature list 飞书文档链接/ID，支持模板变量",
                "default": "",
            },
            "feature_list_text": {
                "type": "string",
                "title": "粘贴文本",
                "description": "粘贴的 feature list 文本，支持模板变量",
                "default": "",
            },
            "uploaded_text": {
                "type": "string",
                "title": "上传文件正文",
                "description": "上传文件（md）正文，支持模板变量",
                "default": "",
            },
            "work_item_type": {
                "type": "string",
                "title": "工作项类型",
                "description": "子看板工作项类型",
                "default": "story",
            },
            "member_ids": {
                "type": "string",
                "title": "成员 ID",
                "description": "无群时建新群拉入的成员 open_id（逗号/JSON/模板变量），复用群时忽略",
                "default": "",
            },
        },
        "required": [],
    }

    inputs: ClassVar[list[NodePort]] = [
        NodePort(
            name="default",
            label="输入",
            port_type=PortType.OBJECT,
            required=False,
            description="上游输出，可提供 feature list 来源",
        ),
    ]

    outputs: ClassVar[list[NodePort]] = [
        NodePort(
            name="created",
            label="已建看板",
            port_type=PortType.OBJECT,
            description="用户点开始创建 → 建看板后恢复",
        ),
        NodePort(
            name="refining",
            label="重拆中",
            port_type=PortType.OBJECT,
            description="用户输入信息触发多轮重拆（保持等待）",
        ),
        NodePort(
            name="timeout",
            label="超时",
            port_type=PortType.OBJECT,
            description="等待确认超时",
        ),
        NodePort(
            name="error",
            label="失败",
            port_type=PortType.OBJECT,
            description="无输入源 / 无法拉群 / 服务异常",
        ),
    ]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        """拉群 + 拆分 + 流式发卡 + waiting_event（持久化提案/轮次）。"""
        config = context.node_config
        log = logger.bind(execution_id=context.execution_id, node_id=context.node_id)

        feishu_url = context.render_template(config.get("feature_list_url", "") or "")
        pasted_text = context.render_template(config.get("feature_list_text", "") or "")
        uploaded_text = context.render_template(config.get("uploaded_text", "") or "")
        work_item_type = config.get("work_item_type", "") or "story"
        member_ids = _parse_id_list(config.get("member_ids", ""), context)

        if not (feishu_url.strip() or pasted_text.strip() or uploaded_text.strip()):
            return NodeResult(
                status="failed",
                error="未提供任何 feature list 输入源（飞书链接 / 粘贴文本 / 上传文件）",
                next_handle="error",
            )

        space = await _resolve_space(context)
        if space is None:
            return NodeResult(
                status="failed",
                error="无法获取空间信息，请确保工作流关联了空间",
                next_handle="error",
            )

        project = await _aresolve_project(space)
        if project is None:
            return NodeResult(
                status="failed",
                error="未找到空间对应的项目，无法解析项目群",
                next_handle="error",
            )

        initiated_by_user_id = self._resolve_initiator(context)

        # ② 复用/建项目群 + bot 入群（fail-soft：空 chat_id → 无法拉群）。
        chat_id = await ProjectService().resolve_or_create_group(
            project=project,
            member_ids=member_ids,
            initiated_by_user_id=initiated_by_user_id,
        )
        if not chat_id:
            log.warning("board_split_review_no_chat")
            return NodeResult(
                status="failed",
                error="无法复用或创建项目群（建群失败），拆分结果无法下发",
                next_handle="error",
            )

        # ③ 拆分提案。
        try:
            service = BoardSplitService()
            proposal = await service.propose_split(
                space=space,
                uploaded_text=uploaded_text or None,
                feishu_url=feishu_url or None,
                pasted_text=pasted_text or None,
                initiated_by_user_id=initiated_by_user_id,
            )
        except Exception as exc:  # noqa: BLE001 — 拆分失败走 error handle
            error_msg = str(exc) or f"{type(exc).__name__}: 看板拆分失败"
            log.error(
                "board_split_review_propose_failed",
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )
            return NodeResult(status="failed", error=error_msg, next_handle="error")

        # ④ CardKit 流式下发（失败 fail-soft 降级普通发卡）。
        card = build_board_split_card(
            proposal,
            execution_id=context.execution_id,
            node_id=context.node_id,
            round=1,
            streamable_element_id=_STREAM_ELEMENT_ID,
        )
        im_service = await FeishuIMService.create(space)
        card_id = await self._send_streaming_card(
            im_service, chat_id, card, proposal, log=log
        )

        log.info(
            "board_split_card_sent",
            chat_id=chat_id,
            card_id=card_id,
            round=1,
            feature_count=len(proposal.get("features_flat") or []),
            initiated_by_user_id=initiated_by_user_id,
            component=_COMPONENT,
            category="caller",
        )

        # ⑤ 事件订阅（超时兜底）。
        if context.workflow_execution and context.node_execution:
            await WorkflowEventSubscription.objects.acreate(
                workflow_execution=context.workflow_execution,
                node_execution=context.node_execution,
                event_type="BoardSplitCallback",
                project_key=context.workflow_context.get("project_key", ""),
                timeout_at=timezone.now() + timedelta(minutes=60),
                timeout_action="fail",
            )

        # ⑥ 挂起等待回调（持久化提案/来源/轮次供回调复用）。
        return NodeResult(
            status="waiting_event",
            output={
                "proposal": proposal,
                "sources": {
                    "feishu_url": feishu_url,
                    "pasted_text": pasted_text,
                    "uploaded_text": uploaded_text,
                },
                "work_item_type": work_item_type,
                "chat_id": chat_id,
                "card_id": card_id,
                "round": 1,
                "member_ids": member_ids,
            },
        )

    async def _send_streaming_card(
        self,
        im_service: Any,
        chat_id: str,
        card: dict[str, Any],
        proposal: dict[str, Any],
        *,
        log: Any,
    ) -> str:
        """CardKit 流式序列下发：create→send→stream→settle（sequence 单调递增）。

        任一步失败 fail-soft：降级为普通 ``send_card`` 把渲染好的结果一次发出，返回 ""（无
        card_id，回调侧重拆将新发卡而非续灌）。
        """
        content = render_proposal_markdown(proposal)
        try:
            card_id = await im_service.create_card_entity(card)
            await im_service.send_card_entity(
                receive_id=chat_id, receive_id_type="chat_id", card_id=card_id
            )
            await im_service.stream_card_content(
                card_id, _STREAM_ELEMENT_ID, content, sequence=1
            )
            await im_service.settle_card_stream(card_id, sequence=2)
            return card_id
        except Exception as exc:  # noqa: BLE001 — 流式失败降级普通发卡，不阻断挂起
            log.warning(
                "board_split_stream_fallback",
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )
            try:
                fallback = dict(card)
                fallback["config"] = {"wide_screen_mode": True}
                # 普通发卡直接把结果文本塞进首个可流式元素。
                body = fallback.get("body", {})
                elements = list(body.get("elements") or [])
                if elements:
                    elements[0] = {"tag": "markdown", "content": content}
                fallback["body"] = {"elements": elements}
                await im_service.send_card(
                    receive_id=chat_id, receive_id_type="chat_id", card=fallback
                )
            except Exception:  # noqa: BLE001 — 降级发卡再失败也不反噬挂起
                log.warning("board_split_card_send_failed_after_fallback")
            return ""

    @staticmethod
    def _resolve_initiator(context: ExecutionContext) -> str:
        """取工作流触发用户 id（缺记 system）。"""
        execution = context.workflow_execution
        if execution is not None:
            triggered_by_id = getattr(execution, "triggered_by_id", None)
            if triggered_by_id:
                return str(triggered_by_id)
        return "system"
