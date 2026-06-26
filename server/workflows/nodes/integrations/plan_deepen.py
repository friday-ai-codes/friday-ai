"""技术方案深化节点（Phase 89，PLAN-01，89-01）。

``PlanDeepenNode``：把 ``PlanDeepenService`` 包成「消费 88 确认仓 → v0.7 引擎深化 →
卡片多轮校验澄清（waiting_event HITL）→ 终态」的工作流交互节点。

execute 流程：
  ① 解析空间 + 项目 + 触发用户（mirror ``BoardSplitReviewNode``）；
  ② ``PlanDeepenService().deepen(node_execution_id=...)`` 经 **v0.7 同一引擎**续驱到重挂起
     短路点或终态（绝不新建第二个 engine 工厂）；
  ③ 终态 ``DONE`` → 发终态方案概览卡 → ``completed``（output 携 plan_version 锚）；
  ④ ``CLARIFYING`` 有未答澄清 → 发澄清卡 + ``WorkflowEventSubscription`` 超时兜底 →
     ``waiting_event``（复用既有 ``ClarifyAdapter`` clarification HITL，多轮保持等待）；
  ⑤ ``RESEARCHING`` 在途 → ``waiting_event``（等容器回调经 node_execution_id 续驱）；
  ⑥ ``FAILED`` / 异常 → ``error`` 分支。

自动注册：放在 ``workflows/nodes/integrations/`` 下且声明 ``node_type`` 即被发现。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, ClassVar

import structlog
from django.utils import timezone

from feishu.cards.plan_deepen_card import build_plan_deepen_card
from initiatives.services.plan_deepen_service import PlanDeepenService
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
from workflows.nodes.integrations.board_split_review import (
    _aresolve_project,
    _resolve_space,
)
from workflows.nodes.registry import register_node

logger = structlog.get_logger(__name__)

_COMPONENT = "plan_deepen"


@register_node
class PlanDeepenNode(BaseNode):
    """技术方案深化节点：消费 88 + v0.7 引擎深化 + 卡片多轮校验澄清（waiting_event）。"""

    node_type: ClassVar[str] = "plan_deepen"
    display_name: ClassVar[str] = "技术方案深化"
    description: ClassVar[str] = "消费确认仓经 v0.7 引擎深化 per-repo 七要素 + overall 方案，卡片多轮校验澄清"
    icon: ClassVar[str] = "file-text"
    category: ClassVar[NodeCategory] = NodeCategory.INTEGRATION
    execution_mode: ClassVar[str] = "server_local"
    is_blocking: ClassVar[bool] = True

    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "requirement_text": {
                "type": "string",
                "title": "需求文本",
                "description": "技术方案深化的需求描述，支持模板变量",
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
            description="上游输出，可提供需求文本",
        ),
    ]

    outputs: ClassVar[list[NodePort]] = [
        NodePort(
            name="default",
            label="已深化",
            port_type=PortType.OBJECT,
            description="方案深化完成（终态 DONE）",
        ),
        NodePort(
            name="clarifying",
            label="待澄清",
            port_type=PortType.OBJECT,
            description="深化需多轮校验澄清（保持等待）",
        ),
        NodePort(
            name="error",
            label="失败",
            port_type=PortType.OBJECT,
            description="无需求 / 无空间项目 / 深化失败",
        ),
    ]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        """消费 88 → v0.7 引擎深化 → 终态 / 澄清 waiting_event 映射。"""
        config = context.node_config
        log = logger.bind(
            execution_id=context.execution_id,
            node_id=context.node_id,
            component=_COMPONENT,
            category="caller",
        )

        requirement_text = context.render_template(config.get("requirement_text", "") or "")
        if not requirement_text.strip():
            # 兜底从上游 default 输入取
            upstream = context.input_data or {}
            requirement_text = str(upstream.get("requirement_text", "") or "").strip()
        if not requirement_text.strip():
            return NodeResult(
                status="failed",
                error="未提供技术方案深化的需求文本",
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
                error="未找到空间对应的项目，无法消费确认仓",
                next_handle="error",
            )

        initiated_by_user_id = self._resolve_initiator(context)
        node_execution_id = (
            str(context.node_execution.id) if context.node_execution else ""
        )

        # v0.7 同一引擎深化续驱（绝不新建第二个 engine 工厂）。
        try:
            session = await PlanDeepenService().deepen(
                project=project,
                work_item=None,
                requirement_text=requirement_text,
                node_execution_id=node_execution_id,
                initiated_by_user_id=initiated_by_user_id,
            )
        except Exception as exc:  # noqa: BLE001 — 深化失败走 error 分支（结构化事件已由 service 记账）
            log.error("plan_deepen_node_failed", error_type=type(exc).__name__)
            return NodeResult(
                status="failed",
                error=str(exc) or "技术方案深化失败",
                next_handle="error",
            )

        from delivery.models import PlanSessionStatus

        if session.status == PlanSessionStatus.DONE:
            await self._send_done_card(space, project, session, initiated_by_user_id, log=log)
            return NodeResult(
                status="completed",
                output={
                    "session_id": str(session.id),
                    "plan_version_id": str(session.current_plan_version or ""),
                },
                next_handle="default",
            )

        if session.status == PlanSessionStatus.FAILED:
            return NodeResult(
                status="failed",
                error="技术方案深化未达终态（融合失败）",
                next_handle="error",
            )

        # CLARIFYING（未答）/ RESEARCHING（在途）→ 挂起等待（多轮校验澄清 HITL）。
        question = await self._apending_clarification_question(session)
        await self._send_clarify_card(
            space, project, context, question, initiated_by_user_id, log=log
        )
        if context.workflow_execution and context.node_execution:
            await WorkflowEventSubscription.objects.acreate(
                workflow_execution=context.workflow_execution,
                node_execution=context.node_execution,
                event_type="PlanDeepenCallback",
                project_key=context.workflow_context.get("project_key", ""),
                timeout_at=timezone.now() + timedelta(minutes=60),
                timeout_action="fail",
            )
        return NodeResult(
            status="waiting_event",
            output={
                "session_id": str(session.id),
                "status": session.status,
                "round": 1,
            },
        )

    @staticmethod
    async def _apending_clarification_question(session: Any) -> str:
        """取最新未答 Clarification 问题（无则空串）。"""
        from delivery.models import Clarification

        clar = (
            await Clarification.objects.filter(
                session_id=session.id, answered_at__isnull=True
            )
            .order_by("-created_at")
            .afirst()
        )
        return getattr(clar, "question", "") or "" if clar is not None else ""

    async def _send_done_card(
        self, space: Any, project: Any, session: Any, initiated_by_user_id: str, *, log: Any
    ) -> None:
        """发终态方案概览卡（best-effort，绝不反噬节点完成）。"""
        try:
            content = await PlanDeepenService()._aget_current_plan_content(session)
            partials = await PlanDeepenService()._acollect_partials(session)
            card = build_plan_deepen_card(
                stage="done",
                execution_id="",
                node_id="",
                title=str(content.get("title") or ""),
                summary=str(content.get("summary") or ""),
                repo_count=len(partials),
            )
            await self._asend_card(space, project, card, initiated_by_user_id)
        except Exception:  # noqa: BLE001 — 发卡 best-effort
            log.warning("plan_deepen_done_card_failed")

    async def _send_clarify_card(
        self,
        space: Any,
        project: Any,
        context: ExecutionContext,
        question: str,
        initiated_by_user_id: str,
        *,
        log: Any,
    ) -> None:
        """发澄清卡（best-effort，绝不反噬挂起）。"""
        try:
            from common.logging import redact_secrets_in_text

            card = build_plan_deepen_card(
                stage="clarify",
                execution_id=context.execution_id,
                node_id=context.node_id,
                round=1,
                clarify_question=redact_secrets_in_text(question or ""),
            )
            await self._asend_card(space, project, card, initiated_by_user_id)
        except Exception:  # noqa: BLE001 — 发卡 best-effort
            log.warning("plan_deepen_clarify_card_failed")

    async def _asend_card(
        self, space: Any, project: Any, card: dict[str, Any], initiated_by_user_id: str
    ) -> None:
        """复用/建项目群 + 下发卡片（best-effort）。"""
        chat_id = await ProjectService().resolve_or_create_group(
            project=project,
            member_ids=[],
            initiated_by_user_id=initiated_by_user_id,
        )
        if not chat_id:
            return
        im_service = await FeishuIMService.create(space)
        await im_service.send_card(
            receive_id=chat_id, receive_id_type="chat_id", card=card
        )

    @staticmethod
    def _resolve_initiator(context: ExecutionContext) -> str:
        """取工作流触发用户 id（缺记 system）。"""
        execution = context.workflow_execution
        if execution is not None:
            triggered_by_id = getattr(execution, "triggered_by_id", None)
            if triggered_by_id:
                return str(triggered_by_id)
        return "system"
