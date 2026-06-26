"""看板拆分卡片回调处理器（BOARD-02，87-04）。

镜像 ``chat_question_callback`` 范式：同步处理器（飞书回调需 3s 内响应）即时返回轻量确认卡，
重活在 ``_run_in_thread`` 后台线程做（worker 入口 ``bind_task_context`` re-bind 触发用户）。

两个动作分支：
- ``board_split_start``：用户点「开始创建」→ ``BoardSplitService.create_boards`` 直接建看板 +
  发结果终态卡 + ``engine.approve_node`` 恢复工作流（节点走 default/created）。
- ``board_split_refine``：用户输入信息 → 带 ``extra_instruction`` 重新 ``propose_split`` 多轮重拆
  → 更新 ``output_data``（round+1）→ 重发流式卡片 → 保持 ``waiting_event``（不 approve）。

全程 fail-soft：异常记 ``board_split_card_action``(failed) 不反噬主流程；正文/异常脱敏。
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from common.log_context import bind_task_context
from common.logging import redact_secrets_in_text
from feishu.cards.board_split_card import (
    build_board_split_card,
    build_board_split_done_card,
    render_proposal_markdown,
)
from feishu.views import CardCallback, register_card_callback
from services.feishu_im import create_feishu_im_client_for_project
from workflows.engine.scheduler import WorkflowEngine, _run_in_thread
from workflows.models.execution import (
    ExecutionStatus,
    NodeExecution,
    NodeExecutionStatus,
)

logger = structlog.get_logger(__name__)

_COMPONENT = "board_split"
_STREAM_ELEMENT_ID = "split_md"


@register_card_callback("board_split_")
def handle_board_split_action(callback: CardCallback) -> dict[str, Any] | None:
    """看板拆分卡片回调入口：开始创建 / 多轮重拆（同步即时返回确认卡）。"""
    data = _extract_callback_data(callback)
    if not data:
        return None

    action = data.get("action", "")
    execution_id = data.get("execution_id", "")
    node_id = data.get("node_id", "")
    round_no = int(data.get("round", 1) or 1)
    # 输入框内容经 CardCallbackView 把 form_value 合并进 action_value。
    refine_input = str(data.get("refine_input", "") or "").strip()

    if not execution_id or not node_id:
        logger.warning(
            "board_split_callback_missing_ids",
            action=action,
            component=_COMPONENT,
            category="caller",
        )
        return None

    responder_id = callback.user_open_id

    if action == "board_split_start":
        logger.info(
            "board_split_card_action",
            action=action,
            execution_id=execution_id,
            node_id=node_id,
            round=round_no,
            component=_COMPONENT,
            category="caller",
        )
        _run_in_thread(
            _do_board_split_start_async(
                execution_id=execution_id,
                node_id=node_id,
                responder_id=responder_id,
            )
        )
        return _ack_card("已收到，正在创建子看板…")

    if action == "board_split_refine":
        if not refine_input:
            logger.warning(
                "board_split_refine_missing_input",
                execution_id=execution_id,
                node_id=node_id,
                component=_COMPONENT,
                category="caller",
            )
            return _ack_card("请输入补充拆分要求后再点发送。")
        logger.info(
            "board_split_card_action",
            action=action,
            execution_id=execution_id,
            node_id=node_id,
            round=round_no,
            component=_COMPONENT,
            category="caller",
        )
        _run_in_thread(
            _do_board_split_refine_async(
                execution_id=execution_id,
                node_id=node_id,
                refine_input=refine_input,
                responder_id=responder_id,
            )
        )
        return _ack_card("已收到，正在按你的要求重新拆分…")

    logger.warning(
        "board_split_callback_unknown_action",
        action=action,
        component=_COMPONENT,
        category="caller",
    )
    return None


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
            "title": {"tag": "plain_text", "content": "看板拆分"},
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


async def _do_board_split_start_async(
    *,
    execution_id: str,
    node_id: str,
    responder_id: str,
) -> None:
    """后台：开始创建 → create_boards → 发结果卡 → approve_node 恢复（fail-soft + re-bind）。"""
    with bind_task_context(
        user_id=responder_id or None,
        source="feishu",
        component=_COMPONENT,
    ):
        try:
            node_execution = await _aget_waiting_node(execution_id, node_id)
            if node_execution is None:
                logger.info(
                    "board_split_start_ignored_not_waiting",
                    execution_id=execution_id,
                    node_id=node_id,
                    component=_COMPONENT,
                    category="caller",
                )
                return

            output = node_execution.output_data or {}
            proposal = output.get("proposal") or {}
            work_item_type = output.get("work_item_type") or "story"
            chat_id = output.get("chat_id", "")

            space = await _resolve_space(node_execution)

            from initiatives.services.board_split_service import BoardSplitService

            result = await BoardSplitService().create_boards(
                space=space,
                proposal=proposal,
                work_item_type=work_item_type,
                initiated_by_user_id=responder_id or "system",
            )

            # 发建看板结果终态卡（best-effort，发卡失败不阻断恢复）。
            if chat_id:
                try:
                    im_client = await create_feishu_im_client_for_project(space)
                    await im_client.send_card(
                        receive_id=chat_id,
                        receive_id_type="chat_id",
                        card=build_board_split_done_card(result),
                    )
                except Exception as exc:  # noqa: BLE001 — 发卡失败不反噬恢复
                    logger.warning(
                        "board_split_done_card_send_failed",
                        error_type=type(exc).__name__,
                        component=_COMPONENT,
                        category="caller",
                    )

            # 恢复工作流（携 created 结果）。
            node_execution.approval_data = {
                "created": result.get("created", []),
                "failures": result.get("failures", []),
                "degraded_parent_child": result.get("degraded_parent_child", False),
                "feature_count": result.get("feature_count", 0),
            }
            await node_execution.asave(update_fields=["approval_data"])

            workflow_execution = node_execution.workflow_execution
            if workflow_execution.status == ExecutionStatus.SUSPENDED:
                workflow_execution.status = ExecutionStatus.RUNNING
                await workflow_execution.asave(update_fields=["status"])

            responder = _FeishuResponder(responder_id)
            await WorkflowEngine().approve_node(
                node_execution, responder, "board_split_start"
            )

            logger.info(
                "board_split_card_create_done",
                execution_id=execution_id,
                node_id=node_id,
                created_count=len(result.get("created", [])),
                failed_count=len(result.get("failures", [])),
                component=_COMPONENT,
                category="caller",
            )
        except Exception as exc:  # noqa: BLE001 — 回调重活 fail-soft，绝不反噬飞书主响应
            logger.error(
                "board_split_card_action",
                action="board_split_start",
                status="failed",
                execution_id=execution_id,
                node_id=node_id,
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )


async def _do_board_split_refine_async(
    *,
    execution_id: str,
    node_id: str,
    refine_input: str,
    responder_id: str,
) -> None:
    """后台：多轮重拆 → 更新 output_data（round+1）→ 重发流式卡 → 保持 waiting（fail-soft）。"""
    with bind_task_context(
        user_id=responder_id or None,
        source="feishu",
        component=_COMPONENT,
    ):
        try:
            node_execution = await _aget_waiting_node(execution_id, node_id)
            if node_execution is None:
                logger.info(
                    "board_split_refine_ignored_not_waiting",
                    execution_id=execution_id,
                    node_id=node_id,
                    component=_COMPONENT,
                    category="caller",
                )
                return

            output = node_execution.output_data or {}
            sources = output.get("sources") or {}
            current_round = int(output.get("round", 1) or 1)
            next_round = current_round + 1
            chat_id = output.get("chat_id", "")

            space = await _resolve_space(node_execution)

            from initiatives.services.board_split_service import BoardSplitService

            proposal = await BoardSplitService().propose_split(
                space=space,
                uploaded_text=sources.get("uploaded_text") or None,
                feishu_url=sources.get("feishu_url") or None,
                pasted_text=sources.get("pasted_text") or None,
                extra_instruction=refine_input,
                initiated_by_user_id=responder_id or "system",
            )

            # 更新 output_data（round+1，proposal=新）——保持 waiting，不 approve。
            node_execution.output_data = {
                **output,
                "round": next_round,
                "proposal": proposal,
            }
            await node_execution.asave(update_fields=["output_data"])

            # 重发流式卡片（新建实体，规避跨轮 sequence 状态丢失）。
            if chat_id:
                await _resend_streaming_card(
                    space=space,
                    chat_id=chat_id,
                    proposal=proposal,
                    execution_id=execution_id,
                    node_id=node_id,
                    round_no=next_round,
                )

            logger.info(
                "board_split_refine",
                execution_id=execution_id,
                node_id=node_id,
                round=next_round,
                component=_COMPONENT,
                category="caller",
            )
        except Exception as exc:  # noqa: BLE001 — 重拆 fail-soft，绝不反噬飞书主响应
            logger.error(
                "board_split_card_action",
                action="board_split_refine",
                status="failed",
                execution_id=execution_id,
                node_id=node_id,
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )


async def _resend_streaming_card(
    *,
    space: Any,
    chat_id: str,
    proposal: dict[str, Any],
    execution_id: str,
    node_id: str,
    round_no: int,
) -> None:
    """重发 CardKit 流式卡片（create→send→stream→settle，失败降级普通发卡）。"""
    card = build_board_split_card(
        proposal,
        execution_id=execution_id,
        node_id=node_id,
        round=round_no,
        streamable_element_id=_STREAM_ELEMENT_ID,
    )
    content = render_proposal_markdown(proposal)
    im_client = await create_feishu_im_client_for_project(space)
    try:
        card_id = await im_client.create_card_entity(card)
        await im_client.send_card_entity(
            receive_id=chat_id, receive_id_type="chat_id", card_id=card_id
        )
        await im_client.stream_card_content(
            card_id, _STREAM_ELEMENT_ID, content, sequence=1
        )
        await im_client.settle_card_stream(card_id, sequence=2)
    except Exception as exc:  # noqa: BLE001 — 流式失败降级普通发卡
        logger.warning(
            "board_split_resend_stream_fallback",
            error_type=type(exc).__name__,
            component=_COMPONENT,
            category="caller",
        )
        fallback = dict(card)
        fallback["config"] = {"wide_screen_mode": True}
        body = fallback.get("body", {})
        elements = list(body.get("elements") or [])
        if elements:
            elements[0] = {"tag": "markdown", "content": content}
        fallback["body"] = {"elements": elements}
        await im_client.send_card(
            receive_id=chat_id, receive_id_type="chat_id", card=fallback
        )


class _FeishuResponder:
    """轻量回复者对象（approve_node 审计归因，镜像 chat_question_callback）。"""

    def __init__(self, open_id: str) -> None:
        self.id = open_id
        self.username = f"feishu:{open_id}"

    def __str__(self) -> str:
        return self.username
