"""群聊提问卡片回调处理器。

处理群聊提问卡片的按钮点击和表单提交回调。
严格参考 approval_callback.py 的模式：
- 同步处理器（飞书回调需 3 秒内响应）
- _schedule_chat_answer_completion 在后台线程异步恢复工作流

支持多轮追问：current_round < max_rounds 时发新卡片继续追问，
最后一轮汇总所有回复调用 approve_node 完成节点。
"""

import json
from typing import Any

import structlog

from feishu.cards.chat_question_card import (
    build_chat_answered_card,
    build_chat_question_card,
)
from feishu.views import CardCallback, register_card_callback
from services.feishu_im import FeishuIMClient, create_feishu_im_client_for_project
from workflows.engine.scheduler import WorkflowEngine, _run_in_thread
from workflows.models.execution import (
    ExecutionStatus,
    NodeExecution,
    NodeExecutionStatus,
)

logger = structlog.get_logger(__name__)


@register_card_callback("chat_question_answer")
def handle_chat_question_answer(callback: CardCallback) -> dict[str, Any] | None:
    """处理群聊提问卡片的回答回调。

    支持两种回答方式：
    1. 按钮点击：answer 在 action_value.answer
    2. 表单提交：answer 在 action_value.custom_answer（CardCallbackView 已合并 form_value）

    Args:
        callback: 卡片回调数据

    Returns:
        已回复状态卡片 JSON，或 None（参数缺失时）
    """
    data = _extract_callback_data(callback)
    if not data:
        return None

    execution_id = data.get("execution_id", "")
    node_id = data.get("node_id", "")
    # 按钮点击：answer 字段；表单提交：custom_answer 字段
    answer = data.get("answer", "") or data.get("custom_answer", "")

    if not execution_id or not node_id:
        logger.warning("chat_question_callback_missing_ids", data=data)
        return None

    if not answer:
        logger.warning("chat_question_callback_missing_answer", data=data)
        return None

    logger.info(
        "chat_question_answered",
        execution_id=execution_id,
        node_id=node_id,
        answer_preview=answer[:50],
    )

    _schedule_chat_answer_completion(
        execution_id=execution_id,
        node_id=node_id,
        answer=answer,
        responder_id=callback.user_open_id,
    )

    # 获取问题信息用于更新卡片
    question = _get_question_from_node(execution_id, node_id)

    return build_chat_answered_card(
        question=question,
        answer=answer,
        responder_name="群成员",
    )


def _extract_callback_data(callback: CardCallback) -> dict[str, Any]:
    """从 callback 的 action_value 提取数据字典。

    action_value 可能是 dict（CardCallbackView 已解析）或 JSON 字符串。

    Args:
        callback: 卡片回调数据

    Returns:
        解析后的数据字典，或空字典
    """
    action_value = callback.action_value
    if isinstance(action_value, dict):
        return action_value
    elif isinstance(action_value, str):
        try:
            data = json.loads(action_value)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _get_question_from_node(execution_id: str, node_id: str) -> str:
    """从 NodeExecution 的 output_data 获取当前问题文本。

    Args:
        execution_id: 工作流执行 ID
        node_id: 节点 ID

    Returns:
        问题文本，获取失败时返回默认值
    """
    try:
        node_execution = NodeExecution.objects.filter(
            workflow_execution_id=execution_id,
            node_id=node_id,
        ).first()

        if not node_execution:
            return "提问"

        output_data = node_execution.output_data or {}
        question: str = output_data.get("question", "提问")
        return question
    except Exception as e:
        logger.warning("get_question_from_node_failed", error=str(e))
        return "提问"


def _schedule_chat_answer_completion(
    execution_id: str,
    node_id: str,
    answer: str,
    responder_id: str,
) -> None:
    """在后台线程异步完成群聊回答处理。

    复用 approval_callback 的 _run_in_thread 模式，
    避免阻塞飞书回调（必须 3 秒内响应）。

    Args:
        execution_id: 工作流执行 ID
        node_id: 节点 ID
        answer: 用户回答内容
        responder_id: 回复者的飞书 open_id
    """
    _run_in_thread(
        _do_chat_answer_async(
            execution_id=execution_id,
            node_id=node_id,
            answer=answer,
            responder_id=responder_id,
        )
    )


async def _do_chat_answer_async(
    execution_id: str,
    node_id: str,
    answer: str,
    responder_id: str,
) -> None:
    """异步处理群聊回答，支持多轮追问。

    根据 output_data 中的 max_rounds 和 current_round 决定：
    - 非最后一轮：记录回复，发新追问卡片，保持 waiting_event
    - 最后一轮：汇总所有轮次回复，调用 approve_node 完成节点

    Args:
        execution_id: 工作流执行 ID
        node_id: 节点 ID
        answer: 用户回答内容
        responder_id: 回复者的飞书 open_id
    """
    try:
        # 查找处于等待状态的 NodeExecution
        node_execution = await NodeExecution.objects.filter(
            workflow_execution_id=execution_id,
            node_id=node_id,
            status=NodeExecutionStatus.WAITING_EVENT,
        ).select_related("workflow_execution").afirst()

        if not node_execution:
            logger.info(
                "chat_answer_ignored_not_waiting",
                execution_id=execution_id,
                node_id=node_id,
            )
            return

        output = node_execution.output_data or {}
        max_rounds = output.get("max_rounds", 1)
        current_round = output.get("current_round", 1)
        rounds: list[dict[str, Any]] = output.get("rounds", [])

        # 记录本轮回复
        rounds.append({
            "question": output.get("question", ""),
            "answer": answer,
            "round": current_round,
        })

        if current_round < max_rounds:
            # 还有追问轮次：更新 output_data，发新卡片，保持 waiting_event
            next_round = current_round + 1
            next_question = f"根据您的回复「{answer}」，请补充更多信息："

            node_execution.output_data = {
                **output,
                "current_round": next_round,
                "rounds": rounds,
                "question": next_question,
            }
            await node_execution.asave(update_fields=["output_data"])

            # 构建历史
            history = [{"question": r["question"], "answer": r["answer"]} for r in rounds]

            # 发新卡片
            card = build_chat_question_card(
                question=next_question,
                execution_id=str(node_execution.workflow_execution_id),
                node_id=str(node_execution.node_id),
                work_item_name=output.get("work_item_name", ""),
                history=history,
                mention_user_id=output.get("mention_user_id") or None,
            )

            # 获取 FeishuIMClient 发卡片
            try:
                project = None
                we = node_execution.workflow_execution
                if we and hasattr(we, "workflow"):
                    project = getattr(we.workflow, "space", None)
                im_client = await create_feishu_im_client_for_project(project)
            except Exception:
                # 回退到直接构造（无凭证时无法发送）
                logger.warning("chat_multi_round_im_client_fallback")
                im_client = FeishuIMClient(app_id="", app_secret="")

            await im_client.send_card(
                receive_id=output.get("chat_id", ""),
                receive_id_type="chat_id",
                card=card,
            )

            logger.info(
                "chat_multi_round_next_sent",
                execution_id=execution_id,
                node_id=node_id,
                round=next_round,
            )

        else:
            # 最后一轮：汇总结果，调用 approve_node 完成节点
            node_execution.approval_data = {
                "rounds": rounds,
                "total_rounds": current_round,
            }
            await node_execution.asave(update_fields=["approval_data"])

            # 恢复工作流
            workflow_execution = node_execution.workflow_execution
            if workflow_execution.status == ExecutionStatus.SUSPENDED:
                workflow_execution.status = ExecutionStatus.RUNNING
                await workflow_execution.asave(update_fields=["status"])

            # 构造简单的回复者对象
            class _FeishuResponder:
                def __init__(self, open_id: str) -> None:
                    self.id = open_id
                    self.username = f"feishu:{open_id}"

                def __str__(self) -> str:
                    return self.username

            responder = _FeishuResponder(responder_id)
            engine = WorkflowEngine()

            # 汇总所有回复作为 answer
            all_answers = "\n".join(
                f"[轮次 {r['round']}] Q: {r['question']}\nA: {r['answer']}"
                for r in rounds
            )
            await engine.approve_node(node_execution, responder, all_answers)

            logger.info(
                "chat_answer_completion_done",
                execution_id=execution_id,
                node_id=node_id,
                total_rounds=current_round,
            )

    except Exception as e:
        logger.exception(
            "chat_answer_completion_error",
            execution_id=execution_id,
            node_id=node_id,
            error=str(e),
        )
