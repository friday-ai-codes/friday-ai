"""澄清卡原子节点（SLOT-02，Phase 92，92-03）。

``ClarificationCardNode``：吃澄清请求（``clarification_request``）→ 发飞书交互卡（群/会话）→
挂起等回答（``waiting_event``）→ 由 standalone 回调 ``clarify_card_callback``（Task 2）经
``approve_node`` 续推本节点。逐行 mirror ``GroupChatQuestionNode``（发卡 try/except best-effort
+ ``WorkflowEventSubscription.acreate`` + waiting_event），区别：

- 复用 ``build_clarification_card(action="clarify_card_answer")``——前缀 ``clarify_card_`` 经
  ``CardCallbackView`` ``startswith`` 路由与 91 的 ``plan_clarify_answer`` 物理隔离、互不抢占。
- 订阅事件键 ``ClarifyCardCallback``（独立于 91 的 ``PlanClarifyCallback``）。
- **不绑 PlanSession / 不 approve ai_plan_research**——节点自洽闭环（per Open Questions 决议 #1）。

观测：structlog snake_case（``clarification_card_started`` / ``clarification_card_sent`` /
``clarification_card_send_failed``）带 ``category="caller"`` / ``component="workflow_node"`` /
``duration_ms``；触发用户经 context 解析（缺记 ``system``）。发卡正文自由文本（reason/title）经
``redact_secrets_in_text`` 脱敏。
"""

from __future__ import annotations

from datetime import timedelta
from time import perf_counter
from typing import Any, ClassVar

import structlog
from django.utils import timezone

from common.logging import redact_secrets_in_text
from feishu.cards.chat_question_card import build_clarification_card
from services.feishu_im import FeishuIMClient
from workflows.models.execution import WorkflowEventSubscription
from workflows.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeCategory,
    NodePort,
    NodeResult,
    PortType,
)
from workflows.nodes.integrations.chat_question import _get_feishu_credentials
from workflows.nodes.registry import register_node

logger = structlog.get_logger(__name__)

_COMPONENT = "workflow_node"


@register_node
class ClarificationCardNode(BaseNode):
    """澄清卡节点：吃澄清请求 → 发飞书交互卡 → 收答 → 吐结构化答案。

    Flow:
    1. 解析 ``clarification_request`` 输入（clarification_id / questions / chat_id / title / reason）。
    2. 有 clarification_id → 按 order 取整轮子题（persisted）；否则用 raw questions（transient）。
    3. 二者皆空 或 缺 chat_id → failed + next_handle="error"。
    4. build_clarification_card(action="clarify_card_answer") → 发卡（best-effort）。
    5. 建 WorkflowEventSubscription(ClarifyCardCallback) → waiting_event。
    6. 回调（clarify_card_callback）收答后 approve_node 续推本节点。
    """

    node_type: ClassVar[str] = "clarification_card"
    display_name: ClassVar[str] = "澄清卡"
    description: ClassVar[str] = "吃澄清请求 → 发飞书交互卡 → 收答 → 吐结构化答案"
    icon: ClassVar[str] = "help-circle"
    category: ClassVar[NodeCategory] = NodeCategory.INTEGRATION
    execution_mode: ClassVar[str] = "server_local"
    is_blocking: ClassVar[bool] = True

    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "chat_id": {
                "type": "string",
                "title": "群聊 ID",
                "description": "目标群聊 ID（支持模板变量；clarification_request 未带 chat_id 时兜底）",
            },
            "title": {
                "type": "string",
                "title": "卡片标题",
                "description": "澄清卡标题（可选）",
            },
            "reason": {
                "type": "string",
                "title": "澄清原因",
                "description": "需要澄清的原因，展示在卡片顶部（可选）",
            },
        },
        "required": [],
    }

    inputs: ClassVar[list[NodePort]] = [
        NodePort(
            name="clarification_request",
            label="澄清请求",
            port_type=PortType.OBJECT,
            required=True,
            description="澄清请求 {clarification_id?, questions?, chat_id?, title?, reason?}",
            shape="clarification_request",
        ),
    ]

    outputs: ClassVar[list[NodePort]] = [
        NodePort(
            name="clarification_answer",
            label="澄清答复",
            port_type=PortType.OBJECT,
            description="用户回答后的结构化答复",
            shape="clarification_answer",
        ),
        NodePort(
            name="feishu_message",
            label="飞书消息",
            port_type=PortType.OBJECT,
            description="发出的澄清卡消息引用",
            shape="feishu_message",
        ),
        NodePort(
            name="error",
            label="失败",
            port_type=PortType.OBJECT,
            description="缺少澄清内容或群聊时的失败输出",
        ),
    ]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        """执行澄清卡节点：解析请求 → 发卡（best-effort）→ 订阅 → waiting_event。"""
        started = perf_counter()
        initiated_by_user_id = self._resolve_initiator(context)
        log = logger.bind(
            execution_id=context.execution_id,
            node_id=context.node_id,
            component=_COMPONENT,
            category="caller",
            initiated_by_user_id=initiated_by_user_id,
        )

        config = context.node_config or {}
        req = context.get_input("clarification_request")
        if not isinstance(req, dict):
            req = {}

        clarification_id = str(req.get("clarification_id") or "").strip()
        chat_id = str(req.get("chat_id") or "").strip()
        if not chat_id:
            chat_id = context.render_template(str(config.get("chat_id", "") or "")).strip()
        title = str(req.get("title") or config.get("title") or "").strip()
        reason = str(req.get("reason") or config.get("reason") or "").strip()

        log.info(
            "clarification_card_started", clarification_id=clarification_id, has_chat=bool(chat_id)
        )

        # 取问题：有 clarification_id → 取整轮子题（persisted）；否则 raw questions（transient）。
        if clarification_id:
            questions = await self._acollect_round_questions(clarification_id)
            persisted = True
        else:
            raw = req.get("questions")
            questions = list(raw) if isinstance(raw, list) else []
            persisted = False

        # 缺澄清内容 或 缺群聊 → 无意义，failed + error（D-4 范式）。
        if not questions or not chat_id:
            log.warning(
                "clarification_card_missing_content",
                has_questions=bool(questions),
                has_chat=bool(chat_id),
            )
            return NodeResult(
                status="failed",
                error="缺少澄清内容或群聊",
                next_handle="error",
            )

        # 发卡用 questions（card 形态）+ questions_meta（回调透传据 order 映射）。
        card_questions = [
            {
                "question": str(q.get("question", "")),
                "type": q.get("type") or q.get("qtype") or "single",
                "options": q.get("options") or [],
                "recommended": q.get("recommended") or [],
            }
            for q in questions
        ]
        questions_meta = [
            {
                "id": str(q.get("id", "")),
                "order": q.get("order", idx),
                "qtype": q.get("type") or q.get("qtype") or "single",
            }
            for idx, q in enumerate(questions)
        ]

        card = build_clarification_card(
            card_questions,
            execution_id=context.execution_id,
            node_id=context.node_id,
            clarification_id=clarification_id,
            action="clarify_card_answer",
            title=redact_secrets_in_text(title),
            reason=redact_secrets_in_text(reason),
        )

        # 发卡：整段 best-effort try/except（失败仍挂起，绝不反噬，T-92-03-DOS）。
        card_sent = False
        message_id = ""
        try:
            app_id, app_secret = await _get_feishu_credentials(context)
            im_client = FeishuIMClient(app_id=app_id, app_secret=app_secret)
            message_id = await im_client.send_card(
                receive_id=chat_id,
                receive_id_type="chat_id",
                card=card,
            )
            card_sent = True
            log.info("clarification_card_sent", chat_id=chat_id, message_id=message_id)
        except Exception as exc:  # noqa: BLE001 — 发卡 best-effort，绝不反噬挂起
            log.warning(
                "clarification_card_send_failed",
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
            )

        # 建订阅（超时兜底是可靠性机制，不包 try/except；guard 已确保 FK 有效）。
        if context.workflow_execution and context.node_execution:
            await WorkflowEventSubscription.objects.acreate(
                workflow_execution=context.workflow_execution,
                node_execution=context.node_execution,
                event_type="ClarifyCardCallback",
                project_key=context.workflow_context.get("project_key", ""),
                timeout_at=timezone.now() + timedelta(minutes=60),
                timeout_action="fail",
            )

        log.info(
            "clarification_card_suspended",
            clarification_id=clarification_id,
            question_count=len(questions),
            persisted=persisted,
            card_sent=card_sent,
            duration_ms=round((perf_counter() - started) * 1000, 2),
        )

        return NodeResult(
            status="waiting_event",
            output={
                "clarification_id": clarification_id,
                "chat_id": chat_id,
                "message_id": message_id,
                "question_count": len(questions),
                "persisted": persisted,
                "card_sent": card_sent,
                "questions_meta": questions_meta,
            },
        )

    @staticmethod
    async def _acollect_round_questions(clarification_id: str) -> list[dict[str, Any]]:
        """据卡片权威 ``clarification_id`` 取该轮**整轮**子题（按 ``order``）。

        WARNING #3 不变量：按 ``order_by("order")`` 整轮取（不依赖部分已答 filter），与回调侧
        枚举顺序逐字一致——索引 ``i`` ↔ 第 ``i`` 个子题固定不漂移。绝不信回调直传 session_id。
        """
        from delivery.models import ClarificationQuestion

        rows: list[dict[str, Any]] = []
        async for q in (
            ClarificationQuestion.objects.filter(clarification_id=clarification_id)
            .order_by("order")
            .values("id", "order", "question", "qtype", "options", "recommended")
        ):
            rows.append(q)
        return rows

    @staticmethod
    def _resolve_initiator(context: ExecutionContext) -> str:
        """取工作流触发用户 id（缺记 system，观测约束：后台/外部触发带 initiated_by_user_id）。"""
        execution = context.workflow_execution
        if execution is not None:
            triggered_by_id = getattr(execution, "triggered_by_id", None)
            if triggered_by_id:
                return str(triggered_by_id)
        return "system"
