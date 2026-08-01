"""澄清回路卡片回调状态机（Phase 91，PLAN-03，91-03，CLARIFY-05/06）。

逐字镜像 ``plan_revision_callback`` 范式：同步处理器（飞书回调需 3s 内响应）即时返回轻量
确认卡，重活在 ``_run_in_thread`` 后台线程做（worker 入口 ``bind_task_context`` re-bind
触发用户）。前缀 ``plan_clarify_`` 唯一——与 ``plan_callback`` 既有 ``plan_revise`` /
``plan_revision_`` / 工作流 GroupChatQuestion 的 ``chat_question_answer`` 物理不交叉
（``CardCallbackView`` 前缀 ``startswith`` 路由互不抢）。

单一动作 ``plan_clarify_answer``（群卡 form_submit，91-02 发卡侧产）：

- ``form_value``（``q{i}`` 选择值 / ``qt{i}`` 「其他」自由文本）经 ``CardCallbackView`` 合并进
  ``action_value``，故同在回调 data 里。
- **据卡片权威 ``clarification_id`` 取该轮整轮子题**（按 ``order``，**绝不信回调直传的
  session_id**，T-91-03 防伪造）→ 按 ``order`` 枚举映射 ``q{i}``/``qt{i}`` 组
  ``answers[{question_id, selected, freeform_text}]``（索引↔question_id 与 91-02 发卡侧逐字
  一致，plan-checker WARNING #3）。
- 调同源 helper ``aanswer_round_and_resume``（91-01）写答案 + 续推 ``PlanSession``（工作流入口
  传带 ``node_execution_id`` 的 engine）→ ``approve_node`` 重调度挂起的 ``ai_plan_research``
  节点（节点重入据 ``output_data.session_id`` 续推）→ 回 ``build_clarification_answered_card``
  置灰卡（best-effort）。

全程 fail-soft：异常记 ``plan_clarify_answer``(failed) 不反噬飞书主响应；正文/异常脱敏；归因
``callback.user_open_id``（bind_task_context re-bind）；写入只经 ``answer_round``（INV-6），本
回调绝不旁路写 delivery 表；非 waiting 态幂等 no-op。
"""

from __future__ import annotations

import json
from time import perf_counter
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from common.log_context import bind_task_context
from common.logging import redact_secrets_in_text
from feishu.cards.chat_question_card import build_clarification_answered_card
from feishu.views import CardCallback, register_card_callback
from services.feishu_im import create_feishu_im_client_for_project
from services.process_runtime import aanswer_round_and_resume
from services.process_runtime.entrypoint import build_engine_for_session
from workflows.engine.scheduler import WorkflowEngine, _run_in_thread
from workflows.models.execution import (
    ExecutionStatus,
    NodeExecution,
    NodeExecutionStatus,
)

logger = structlog.get_logger(__name__)

_COMPONENT = "process_runtime"


@register_card_callback("plan_clarify_")
def handle_plan_clarify_action(callback: CardCallback) -> dict[str, Any] | None:
    """澄清卡片回调入口：收答 → 后台续推 + approve_node（同步即时返回确认卡）。"""
    data = _extract_callback_data(callback)
    if not data:
        return None

    action = data.get("action", "")
    if action != "plan_clarify_answer":
        logger.warning(
            "plan_clarify_callback_unknown_action",
            action=action,
            component=_COMPONENT,
            category="caller",
        )
        return None

    execution_id = data.get("execution_id", "")
    node_id = data.get("node_id", "")
    clarification_id = data.get("clarification_id", "")
    question_count = int(data.get("question_count", 0) or 0)

    # 防伪造：clarification_id 是定位轮 + 映射子题的权威锚，缺失即拒（绝不退化到信任 session_id）。
    if not clarification_id or not execution_id or not node_id:
        logger.warning(
            "plan_clarify_callback_missing_ids",
            action=action,
            has_clarification_id=bool(clarification_id),
            component=_COMPONENT,
            category="caller",
        )
        return None

    logger.info(
        "plan_clarify_card_action",
        action=action,
        execution_id=execution_id,
        node_id=node_id,
        clarification_id=clarification_id,
        component=_COMPONENT,
        category="caller",
    )
    _run_in_thread(
        _do_clarify_answer_async(
            execution_id=execution_id,
            node_id=node_id,
            clarification_id=clarification_id,
            question_count=question_count,
            data=data,
            responder_id=callback.user_open_id,
            chat_id=callback.chat_id,
        )
    )
    return _ack_card("已收到，正在记录澄清答复并继续生成方案…")


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
            "title": {"tag": "plain_text", "content": "技术方案澄清"},
            "template": "grey",
        },
        "elements": [{"tag": "markdown", "content": f"_{text}_"}],
    }


@sync_to_async
def _resolve_space(node_execution: NodeExecution) -> Any:
    """从 NodeExecution 安全解析空间（select_related 已预载 workflow__space）。"""
    we = node_execution.workflow_execution
    workflow = getattr(we, "workflow", None)
    return getattr(workflow, "space", None) if workflow else None


async def _aget_waiting_node(execution_id: str, node_id: str) -> NodeExecution | None:
    """查处于 waiting_event 的 NodeExecution（非 waiting → None，幂等忽略）。"""
    return await (
        NodeExecution.objects.filter(
            workflow_execution_id=execution_id,
            node_id=node_id,
            status=NodeExecutionStatus.WAITING_EVENT,
        )
        .select_related("workflow_execution__workflow__space")
        .afirst()
    )


async def _acollect_round_questions(clarification_id: str) -> list[dict[str, Any]]:
    """据卡片权威 ``clarification_id`` 取该轮**整轮**子题（按 ``order``）。

    plan-checker WARNING #3：按 ``order_by("order")`` 整轮取子题（**不依赖部分已答 filter**），
    与 91-02 发卡侧枚举顺序逐字一致——索引 ``i`` ↔ 第 ``i`` 个子题 ``question_id`` 固定不随
    部分已答漂移（防错位 / 防重放下索引偏移）。绝不信回调直传 session_id（防伪造）。
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


async def _aresolve_clarification_session(clarification_id: str) -> Any:
    """据卡片权威 ``clarification_id`` 反查其 ``ConvergenceSession``（116-03，engine 分派用）。

    只用来给 ``build_engine_for_session`` 判 ``process_type``；⛔ 绝不信回调直传的
    session_id（防伪造，与 :func:`_acollect_round_questions` 同口径）。取不到返 ``None``
    —— 分派器对 ``None`` 按空 ``process_type`` 回落旧链，与改动前逐字等价。
    """
    from delivery.models import Clarification, ConvergenceSession

    row = await Clarification.objects.filter(id=clarification_id).values("session_id").afirst()
    session_id = (row or {}).get("session_id")
    if not session_id:
        return None
    return await ConvergenceSession.objects.filter(id=session_id).afirst()


def _build_answers(questions: list[dict[str, Any]], data: dict[str, Any]) -> list[dict[str, Any]]:
    """按 ``order`` 枚举映射 ``q{i}``/``qt{i}`` → ``answers[]``（WARNING #3 索引↔question_id）。

    ``q{i}``：选择值（single=str / multi=list）；``qt{i}``：「其他」自由文本。selected 形态直接
    透传给 ``answer_round``（其按 qtype 算采纳信号，调用方不预处理）。
    """
    answers: list[dict[str, Any]] = []
    for i, q in enumerate(questions):
        selected = data.get(f"q{i}")
        freeform = str(data.get(f"qt{i}", "") or "").strip()
        answers.append(
            {
                "question_id": str(q["id"]),
                "selected": selected,
                "freeform_text": freeform,
            }
        )
    return answers


async def _do_clarify_answer_async(
    *,
    execution_id: str,
    node_id: str,
    clarification_id: str,
    question_count: int,
    data: dict[str, Any],
    responder_id: str,
    chat_id: str,
) -> None:
    """后台：据卡片 clarification_id 取轮 + 映射 answers → 同源 helper 续推 → approve_node 重调度。"""
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
                    "plan_clarify_answer_ignored_not_waiting",
                    execution_id=execution_id,
                    node_id=node_id,
                    clarification_id=clarification_id,
                    component=_COMPONENT,
                    category="caller",
                )
                return

            # ② 据卡片权威 clarification_id 取整轮子题（按 order），组 answers[]。
            questions = await _acollect_round_questions(clarification_id)
            if not questions:
                logger.info(
                    "plan_clarify_answer_no_questions",
                    clarification_id=clarification_id,
                    component=_COMPONENT,
                    category="caller",
                )
                return
            answers = _build_answers(questions, data)

            # ③ 续推（同源 helper，91-01）：写答案 + 续驱 PlanSession；工作流入口 engine 带
            #    node_execution_id（CR-02 调研容器回调 resume 钥匙）。
            #    ⭐ 116-03：engine 经分派器按会话的 process_type 取 —— 蓝图会话的澄清卡也走
            #    这条回调，用旧链 engine 会让 handler 取不到 deps 而把会话打成 FAILED。
            #    driver 由 aanswer_round_and_resume 内部同样经分派器选（两把锁一起换）。
            session = await _aresolve_clarification_session(clarification_id)
            engine, _adrive = build_engine_for_session(
                session, node_execution_id=str(node_execution.id)
            )
            await aanswer_round_and_resume(clarification_id, answers, engine=engine)

            # ④ 重调度挂起节点（approve_node，节点重入据 output_data.session_id 续推）。
            node_execution.approval_data = {
                "clarification_answered": True,
                "clarification_id": clarification_id,
            }
            await node_execution.asave(update_fields=["approval_data"])

            workflow_execution = node_execution.workflow_execution
            if workflow_execution.status == ExecutionStatus.SUSPENDED:
                workflow_execution.status = ExecutionStatus.RUNNING
                await workflow_execution.asave(update_fields=["status"])

            responder = _FeishuResponder(responder_id)
            await WorkflowEngine().approve_node(node_execution, responder, "plan_clarify_answer")

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
                "plan_clarify_answer",
                execution_id=execution_id,
                node_id=node_id,
                clarification_id=clarification_id,
                answer_count=len(answers),
                duration_ms=round((perf_counter() - started) * 1000, 2),
                component=_COMPONENT,
                category="caller",
            )
        except Exception as exc:  # noqa: BLE001 — 回调重活 fail-soft，绝不反噬飞书主响应
            logger.error(
                "plan_clarify_answer",
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
            "plan_clarify_answered_card_send_failed",
            component=_COMPONENT,
            category="caller",
        )


class _FeishuResponder:
    """轻量回复者对象（approve_node 审计归因，镜像 plan_revision_callback）。"""

    def __init__(self, open_id: str) -> None:
        self.id = open_id
        self.username = f"feishu:{open_id}"

    def __str__(self) -> str:
        return self.username
