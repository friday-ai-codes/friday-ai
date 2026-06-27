"""standalone 澄清卡回调状态机（SLOT-02，Phase 92，92-03 Task 2）。

逐字镜像 ``plan_clarify_callback`` / ``chat_question_callback`` 范式：同步处理器（飞书回调需 3s
内响应）即时返回轻量确认卡，重活在 ``_run_in_thread`` 后台线程做（worker 入口
``bind_task_context`` re-bind 触发用户）。前缀 ``clarify_card_`` 唯一——与 91 的
``plan_clarify_`` / 工作流 GroupChatQuestion 的 ``chat_question_answer`` 物理不交叉
（``CardCallbackView`` 前缀 ``startswith`` 路由互不抢）。

**关键区别（per Open Questions 决议 #1 + Pitfall 4）：approve 本 ``clarification_card`` 节点，
不绑 PlanSession / 不 approve ``ai_plan_research``**——节点自洽闭环。

单一动作 ``clarify_card_answer``（群卡 form_submit，92-03 节点发卡侧产）：

- ``form_value``（``q{i}`` 选择值 / ``qt{i}`` 自由文本）经 ``CardCallbackView`` 合并进
  ``action_value``。据服务端权威 ``execution_id`` / ``node_id`` 定位本节点 ``NodeExecution``
  （T-92-03-SPOOF：绝不信回调直传可伪造字段）+ 校验 ``node_type=="clarification_card"``（防跨
  节点误 approve）+ WAITING_EVENT 幂等门（防重放/伪造）。
- 有 ``clarification_id``（persisted）→ 按 ``order`` 取整轮子题 → ``answer_round`` 落库
  （INV-6）；无 ``clarification_id``（transient）→ 据 ``output_data.questions_meta`` 透传、跳过
  落库。
- ``_build_answers`` 按 ``order`` 枚举映射 ``answers[{question_id, selected, freeform_text}]``
  （索引↔question_id 与发卡侧逐字一致，WARNING #3）。
- approve 本 card 节点（``approval_data`` 置 answers）→ SUSPENDED→RUNNING → ``approve_node``。

全程 fail-soft：异常记 ``clarify_card_answer``(failed) 不反噬飞书主响应；正文/异常脱敏；写入只经
``answer_round``（INV-6），本回调绝不旁路写 delivery 表；非 waiting 态幂等 no-op。
"""

from __future__ import annotations

import json
from time import perf_counter
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from common.log_context import bind_task_context
from common.logging import redact_secrets_in_text
from delivery.services.clarification_service import ClarificationService
from feishu.cards.chat_question_card import build_clarification_answered_card
from feishu.views import CardCallback, register_card_callback
from services.feishu_im import create_feishu_im_client_for_project
from workflows.engine.scheduler import WorkflowEngine, _run_in_thread
from workflows.models.execution import (
    ExecutionStatus,
    NodeExecution,
    NodeExecutionStatus,
)

logger = structlog.get_logger(__name__)

_COMPONENT = "workflow_node"
_NODE_TYPE = "clarification_card"


@register_card_callback("clarify_card_")
def handle_clarify_card_action(callback: CardCallback) -> dict[str, Any] | None:
    """澄清卡回调入口：收答 → 后台续推 + approve_node 本节点（同步即时返回确认卡）。"""
    data = _extract_callback_data(callback)
    if not data:
        return None

    action = data.get("action", "")
    if action != "clarify_card_answer":
        logger.warning(
            "clarify_card_callback_unknown_action",
            action=action,
            component=_COMPONENT,
            category="caller",
        )
        return None

    execution_id = data.get("execution_id", "")
    node_id = data.get("node_id", "")
    clarification_id = data.get("clarification_id", "")
    question_count = int(data.get("question_count", 0) or 0)

    # T-92-03-SPOOF：据服务端权威 execution_id/node_id 定位，缺失即拒（绝不信可伪造字段）。
    # 注意：clarification_id 非必需（transient 透传模式无轮可写）。
    if not execution_id or not node_id:
        logger.warning(
            "clarify_card_callback_missing_ids",
            action=action,
            has_clarification_id=bool(clarification_id),
            component=_COMPONENT,
            category="caller",
        )
        return None

    logger.info(
        "clarify_card_action",
        action=action,
        execution_id=execution_id,
        node_id=node_id,
        clarification_id=clarification_id,
        component=_COMPONENT,
        category="caller",
    )
    _run_in_thread(
        _do_clarify_card_async(
            execution_id=execution_id,
            node_id=node_id,
            clarification_id=clarification_id,
            question_count=question_count,
            data=data,
            responder_id=callback.user_open_id,
            chat_id=callback.chat_id,
        )
    )
    return _ack_card("已收到，正在记录澄清答复并继续…")


def _extract_callback_data(callback: CardCallback) -> dict[str, Any]:
    """从 callback 的 action_value 提取数据字典（dict 或 JSON 字符串）。"""
    action_value = callback.action_value
    if isinstance(action_value, dict):
        return action_value
    if isinstance(action_value, str):
        try:
            data = json.loads(action_value)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _ack_card(text: str) -> dict[str, Any]:
    """轻量即时确认卡（grey，3s 内同步返回，重活在后台）。"""
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "澄清卡"},
            "template": "grey",
        },
        "elements": [{"tag": "markdown", "content": f"_{text}_"}],
    }


async def _aget_waiting_node(execution_id: str, node_id: str) -> NodeExecution | None:
    """查处于 waiting_event 的 NodeExecution（非 waiting → None，幂等忽略）。"""
    return await (
        NodeExecution.objects.filter(
            workflow_execution_id=execution_id,
            node_id=node_id,
            status=NodeExecutionStatus.WAITING_EVENT,
        )
        .select_related("workflow_execution__workflow__space", "node")
        .afirst()
    )


@sync_to_async
def _aget_node_type(node_execution: NodeExecution) -> str:
    """安全取本节点 node_type（select_related 已预载 node，不裸 lazy-FK）。"""
    node = getattr(node_execution, "node", None)
    return str(getattr(node, "node_type", "") or "")


@sync_to_async
def _resolve_space(node_execution: NodeExecution) -> Any:
    """从 NodeExecution 安全解析空间（select_related 已预载 workflow__space）。"""
    we = node_execution.workflow_execution
    workflow = getattr(we, "workflow", None)
    return getattr(workflow, "space", None) if workflow else None


async def _acollect_round_questions(clarification_id: str) -> list[dict[str, Any]]:
    """据卡片权威 ``clarification_id`` 取该轮**整轮**子题（按 ``order``）。

    WARNING #3：按 ``order_by("order")`` 整轮取（不依赖部分已答 filter），与发卡侧枚举顺序逐字
    一致——索引 ``i`` ↔ 第 ``i`` 个子题 ``question_id`` 固定不漂移。绝不信回调直传 session_id。
    """
    from delivery.models import ClarificationQuestion

    rows: list[dict[str, Any]] = []
    async for q in (
        ClarificationQuestion.objects.filter(clarification_id=clarification_id)
        .order_by("order")
        .values("id", "order", "question", "qtype")
    ):
        rows.append(q)
    return rows


def _build_answers(questions: list[dict[str, Any]], data: dict[str, Any]) -> list[dict[str, Any]]:
    """按 ``order`` 枚举映射 ``q{i}``/``qt{i}`` → ``answers[]``（WARNING #3 索引↔question_id）。

    ``q{i}``：选择值（single=str / multi=list）；``qt{i}``：自由文本。selected 形态直接透传给
    ``answer_round``（其按 qtype 算采纳信号，调用方不预处理）。
    """
    answers: list[dict[str, Any]] = []
    for i, q in enumerate(questions):
        selected = data.get(f"q{i}")
        freeform = str(data.get(f"qt{i}", "") or "").strip()
        answers.append(
            {
                "question_id": str(q.get("id", "")),
                "selected": selected,
                "freeform_text": freeform,
            }
        )
    return answers


async def _do_clarify_card_async(
    *,
    execution_id: str,
    node_id: str,
    clarification_id: str,
    question_count: int,
    data: dict[str, Any],
    responder_id: str,
    chat_id: str,
) -> None:
    """后台：定位本节点 + 校验 node_type + 幂等门 → 收答（answer_round/透传）→ approve_node 本节点。"""
    started = perf_counter()
    with bind_task_context(
        user_id=responder_id or None,
        source="feishu",
        component=_COMPONENT,
    ):
        try:
            # ① 幂等门：非 waiting 节点（重复提交 / 重放 / 已恢复）→ no-op。
            node_execution = await _aget_waiting_node(execution_id, node_id)
            if node_execution is None:
                logger.info(
                    "clarify_card_answer_ignored_not_waiting",
                    execution_id=execution_id,
                    node_id=node_id,
                    clarification_id=clarification_id,
                    component=_COMPONENT,
                    category="caller",
                )
                return

            # T-92-03-SPOOF：校验本节点确为 clarification_card（防跨节点误 approve）。
            node_type = await _aget_node_type(node_execution)
            if node_type != _NODE_TYPE:
                logger.warning(
                    "clarify_card_answer_wrong_node_type",
                    execution_id=execution_id,
                    node_id=node_id,
                    node_type=node_type,
                    component=_COMPONENT,
                    category="caller",
                )
                return

            # ② 取子题：有 clarification_id → 取整轮（persisted）；否则据 questions_meta（transient）。
            if clarification_id:
                questions = await _acollect_round_questions(clarification_id)
            else:
                meta = (node_execution.output_data or {}).get("questions_meta") or []
                questions = [dict(m) for m in meta if isinstance(m, dict)]
            answers = _build_answers(questions, data)

            # ③ 落库（仅 persisted，INV-6）：写入只经 ClarificationService.answer_round。
            if clarification_id:
                await ClarificationService().answer_round(clarification_id, answers)

            # ④ approve 本 card 节点（answers 随 approve_node 进 output，供 clarification_answer 端口语义）。
            node_execution.approval_data = {
                "clarification_answered": True,
                "clarification_id": clarification_id,
                "answers": answers,
            }
            await node_execution.asave(update_fields=["approval_data"])

            workflow_execution = node_execution.workflow_execution
            if workflow_execution.status == ExecutionStatus.SUSPENDED:
                workflow_execution.status = ExecutionStatus.RUNNING
                await workflow_execution.asave(update_fields=["status"])

            responder = _FeishuResponder(responder_id)
            await WorkflowEngine().approve_node(node_execution, responder, "clarify_card_answer")

            # ⑤ 置灰卡（best-effort，发卡失败不阻断恢复）。
            if chat_id:
                await _send_answered_card_best_effort(
                    node_execution=node_execution,
                    chat_id=chat_id,
                    questions=questions,
                    answers=answers,
                    responder_id=responder_id,
                )

            logger.info(
                "clarify_card_answer",
                execution_id=execution_id,
                node_id=node_id,
                clarification_id=clarification_id,
                persisted=bool(clarification_id),
                answer_count=len(answers),
                duration_ms=round((perf_counter() - started) * 1000, 2),
                component=_COMPONENT,
                category="caller",
            )
        except Exception as exc:  # noqa: BLE001 — 回调重活 fail-soft，绝不反噬飞书主响应
            logger.error(
                "clarify_card_answer",
                status="failed",
                execution_id=execution_id,
                node_id=node_id,
                clarification_id=clarification_id,
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )


async def _send_answered_card_best_effort(
    *,
    node_execution: NodeExecution,
    chat_id: str,
    questions: list[dict[str, Any]],
    answers: list[dict[str, Any]],
    responder_id: str,
) -> None:
    """发澄清「已提交」置灰卡到原群（best-effort 不反噬恢复；正文脱敏）。"""
    try:
        space = await _resolve_space(node_execution)
        if space is None:
            return
        qa_pairs: list[dict[str, str]] = []
        for q, ans in zip(questions, answers):
            selected = ans.get("selected")
            if isinstance(selected, (list, tuple)):
                sel_text = "、".join(str(s) for s in selected if str(s).strip())
            else:
                sel_text = str(selected or "").strip()
            freeform = str(ans.get("freeform_text") or "").strip()
            answer_text = "；".join(part for part in (sel_text, freeform) if part)
            qa_pairs.append(
                {
                    "question": redact_secrets_in_text(str(q.get("question") or "")),
                    "answer": redact_secrets_in_text(answer_text),
                }
            )
        card = build_clarification_answered_card(
            qa_pairs,
            responder_name=f"feishu:{responder_id}" if responder_id else "",
        )
        im_client = await create_feishu_im_client_for_project(space)
        await im_client.send_card(receive_id=chat_id, receive_id_type="chat_id", card=card)
    except Exception:  # noqa: BLE001 — 发卡失败不阻断主流程
        logger.warning(
            "clarify_card_answered_card_send_failed",
            component=_COMPONENT,
            category="caller",
        )


class _FeishuResponder:
    """轻量回复者对象（approve_node 审计归因，镜像 plan_clarify_callback）。"""

    def __init__(self, open_id: str) -> None:
        self.id = open_id
        self.username = f"feishu:{open_id}"

    def __str__(self) -> str:
        return self.username
