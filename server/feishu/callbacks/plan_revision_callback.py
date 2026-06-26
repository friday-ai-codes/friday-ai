"""方案修订回路卡片回调状态机（Phase 89，PLAN-02，89-02）。

逐字镜像 ``repo_association_callback`` 范式：同步处理器（飞书回调需 3s 内响应）即时返回轻量
确认卡，重活在 ``_run_in_thread`` 后台线程做（worker 入口 ``bind_task_context`` re-bind
触发用户）。前缀 ``plan_revision_`` 唯一——刻意区别于 ``plan_callback`` 既有 ``plan_revise``
（``"plan_revision_*".startswith("plan_revise")`` 为 False，两者不互相抢路由）。

三个动作分支（修订回路 HITL）：

- ``plan_revision_confirm``：用户点「确认补充修订」→ ``apply_supplement_revision``（加
  ``PlanVersion(supersedes)`` + 经 88 ``RepoAssociationService`` 同步改/增/删仓关联）→ 发
  修订完成卡 → ``approve_node`` 恢复工作流（携补充修订版本）。
- ``plan_revision_adjust``：用户输入调整要求 → 把调整并进观测重 ``detect_revision`` 研判 →
  ``output_data`` round+1 + 新 revision → 重发「调研问题发现」卡 → **保持 waiting**（不 approve）。
- ``plan_revision_cancel``：用户点「取消修订」→ 不修订，保持原方案 → 发取消卡 → ``approve_node``。

全程 fail-soft：异常记 ``plan_revision_*``(failed) 不反噬飞书主响应；正文/异常脱敏；归因
``callback.user_open_id``（bind_task_context re-bind）。``PlanVersion``/``RepoAssociation`` 写
一律经各自 service（INV-6），本回调绝不旁路写表；非 waiting 态幂等 no-op。
"""

from __future__ import annotations

import json
from time import perf_counter
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from common.log_context import bind_task_context
from common.logging import redact_secrets_in_text
from feishu.cards.plan_revision_card import (
    build_plan_revision_card,
    build_plan_revision_done_card,
)
from feishu.views import CardCallback, register_card_callback
from initiatives.services.plan_deepen_service import PlanDeepenService
from services.feishu_im import create_feishu_im_client_for_project
from workflows.engine.scheduler import WorkflowEngine, _run_in_thread
from workflows.models.execution import (
    ExecutionStatus,
    NodeExecution,
    NodeExecutionStatus,
)

logger = structlog.get_logger(__name__)

_COMPONENT = "plan_deepen"


@register_card_callback("plan_revision_")
def handle_plan_revision_action(callback: CardCallback) -> dict[str, Any] | None:
    """方案修订卡片回调入口：确认补充修订 / 调整重研判 / 取消（同步即时返回确认卡）。"""
    data = _extract_callback_data(callback)
    if not data:
        return None

    action = data.get("action", "")
    execution_id = data.get("execution_id", "")
    node_id = data.get("node_id", "")
    round_no = int(data.get("round", 1) or 1)
    # 输入框内容经 CardCallbackView 把 form_value 合并进 action_value。
    adjust_input = str(data.get("adjust_input", "") or "").strip()

    if not execution_id or not node_id:
        logger.warning(
            "plan_revision_callback_missing_ids",
            action=action,
            component=_COMPONENT,
            category="caller",
        )
        return None

    responder_id = callback.user_open_id

    if action == "plan_revision_confirm":
        logger.info(
            "plan_revision_card_action",
            action=action,
            execution_id=execution_id,
            node_id=node_id,
            round=round_no,
            component=_COMPONENT,
            category="caller",
        )
        _run_in_thread(
            _do_revise_confirm_async(
                execution_id=execution_id,
                node_id=node_id,
                responder_id=responder_id,
            )
        )
        return _ack_card("已收到，正在创建补充修订并同步仓库关联…")

    if action == "plan_revision_adjust":
        if not adjust_input:
            logger.warning(
                "plan_revision_adjust_missing_input",
                execution_id=execution_id,
                node_id=node_id,
                component=_COMPONENT,
                category="caller",
            )
            return _ack_card("请输入调整要求后再点发送。")
        logger.info(
            "plan_revision_card_action",
            action=action,
            execution_id=execution_id,
            node_id=node_id,
            round=round_no,
            component=_COMPONENT,
            category="caller",
        )
        _run_in_thread(
            _do_revise_adjust_async(
                execution_id=execution_id,
                node_id=node_id,
                adjust_input=adjust_input,
                responder_id=responder_id,
            )
        )
        return _ack_card("已收到，正在按你的要求重新研判方案修订…")

    if action == "plan_revision_cancel":
        logger.info(
            "plan_revision_card_action",
            action=action,
            execution_id=execution_id,
            node_id=node_id,
            round=round_no,
            component=_COMPONENT,
            category="caller",
        )
        _run_in_thread(
            _do_revise_cancel_async(
                execution_id=execution_id,
                node_id=node_id,
                responder_id=responder_id,
            )
        )
        return _ack_card("已收到，将保持原方案继续执行…")

    logger.warning(
        "plan_revision_callback_unknown_action",
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
            "title": {"tag": "plain_text", "content": "技术方案修订"},
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


@sync_to_async
def _aresolve_project(space: Any) -> Any:
    """解析 space 对应的 Project（优先 feishu_project_key 命中，否则首个；只读）。"""
    if space is None:
        return None
    from initiatives.models import Project

    qs = Project.objects.filter(space=space).select_related("space")
    project_key = getattr(space, "feishu_project_key", "") or ""
    if project_key:
        matched = qs.filter(feishu_project_key=project_key).first()
        if matched is not None:
            return matched
    return qs.first()


@sync_to_async
def _aresolve_plan(node_execution: NodeExecution) -> Any:
    """解析本节点对应的 canonical ``TechnicalPlan``（由 output_data.plan_id 定位；只读）。"""
    output = node_execution.output_data or {}
    plan_id = str(output.get("plan_id") or "").strip()
    if not plan_id:
        return None
    from delivery.models import TechnicalPlan

    return TechnicalPlan.objects.filter(id=plan_id).first()


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


async def _do_revise_confirm_async(
    *,
    execution_id: str,
    node_id: str,
    responder_id: str,
) -> None:
    """后台：确认补充修订 → apply_supplement_revision（加版本 + 关联同步）→ 终态卡 → approve_node。"""
    started = perf_counter()
    with bind_task_context(
        user_id=responder_id or None,
        source="feishu",
        component=_COMPONENT,
    ):
        try:
            node_execution = await _aget_waiting_node(execution_id, node_id)
            if node_execution is None:
                logger.info(
                    "plan_revision_confirm_ignored_not_waiting",
                    execution_id=execution_id,
                    node_id=node_id,
                    component=_COMPONENT,
                    category="caller",
                )
                return

            output = node_execution.output_data or {}
            revision = output.get("revision") or {}
            chat_id = output.get("chat_id", "")

            space = await _resolve_space(node_execution)
            project = await _aresolve_project(space)
            plan = await _aresolve_plan(node_execution)
            if plan is None:
                raise RuntimeError("no_canonical_plan_for_node")

            version = await PlanDeepenService().apply_supplement_revision(
                plan=plan,
                revision=revision,
                project=project,
                actor=_FeishuResponder(responder_id),
                initiated_by_user_id=responder_id or "system",
            )
            version_no = getattr(version, "version", None)

            # 修订完成终态卡（best-effort，发卡失败不阻断恢复）。
            if chat_id:
                await _send_card_best_effort(
                    space=space,
                    chat_id=chat_id,
                    card=build_plan_revision_done_card(
                        {
                            "version": version_no,
                            "add_count": len(revision.get("add_repos") or []),
                            "remove_count": len(revision.get("remove_repos") or []),
                            "change_count": len(revision.get("change_repos") or []),
                        }
                    ),
                )

            # 恢复工作流（携补充修订版本号，approve）。
            node_execution.approval_data = {
                "revision_applied": True,
                "plan_version": version_no,
            }
            await node_execution.asave(update_fields=["approval_data"])

            workflow_execution = node_execution.workflow_execution
            if workflow_execution.status == ExecutionStatus.SUSPENDED:
                workflow_execution.status = ExecutionStatus.RUNNING
                await workflow_execution.asave(update_fields=["status"])

            responder = _FeishuResponder(responder_id)
            await WorkflowEngine().approve_node(
                node_execution, responder, "plan_revision_confirm"
            )

            logger.info(
                "plan_revision_confirm",
                execution_id=execution_id,
                node_id=node_id,
                plan_version=version_no,
                duration_ms=round((perf_counter() - started) * 1000, 2),
                component=_COMPONENT,
                category="caller",
            )
        except Exception as exc:  # noqa: BLE001 — 回调重活 fail-soft，绝不反噬飞书主响应
            logger.error(
                "plan_revision_confirm",
                status="failed",
                execution_id=execution_id,
                node_id=node_id,
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )


async def _do_revise_adjust_async(
    *,
    execution_id: str,
    node_id: str,
    adjust_input: str,
    responder_id: str,
) -> None:
    """后台：带调整重 detect_revision → 更新 output_data（round+1, 新 revision）→ 重发卡 → 保持 waiting。"""
    started = perf_counter()
    with bind_task_context(
        user_id=responder_id or None,
        source="feishu",
        component=_COMPONENT,
    ):
        try:
            node_execution = await _aget_waiting_node(execution_id, node_id)
            if node_execution is None:
                logger.info(
                    "plan_revision_adjust_ignored_not_waiting",
                    execution_id=execution_id,
                    node_id=node_id,
                    component=_COMPONENT,
                    category="caller",
                )
                return

            output = node_execution.output_data or {}
            current_round = int(output.get("round", 1) or 1)
            next_round = current_round + 1
            chat_id = output.get("chat_id", "")
            observed = str(output.get("observed_change_text", "") or "")
            # 把用户调整要求并进观测重研判（仅作筛选/补充约束，不构造执行指令，V5）。
            combined_observed = f"{observed}\n\n用户调整要求：{adjust_input}".strip()

            revision = await PlanDeepenService().detect_revision(
                observed_change_text=combined_observed,
                initiated_by_user_id=responder_id or "system",
            )

            # 更新 output_data（round+1，新 revision，回 revising）——保持 waiting，不 approve。
            node_execution.output_data = {
                **output,
                "round": next_round,
                "revision": revision,
                "observed_change_text": combined_observed,
                "stage": "revising",
            }
            await node_execution.asave(update_fields=["output_data"])

            # 重发「调研问题发现」卡（新研判结果）。
            if chat_id:
                await _send_card_best_effort(
                    space=await _resolve_space(node_execution),
                    chat_id=chat_id,
                    card=build_plan_revision_card(
                        revision,
                        execution_id=execution_id,
                        node_id=node_id,
                        round=next_round,
                    ),
                )

            logger.info(
                "plan_revision_adjust",
                execution_id=execution_id,
                node_id=node_id,
                round=next_round,
                add_count=len(revision.get("add_repos") or []),
                remove_count=len(revision.get("remove_repos") or []),
                change_count=len(revision.get("change_repos") or []),
                duration_ms=round((perf_counter() - started) * 1000, 2),
                component=_COMPONENT,
                category="caller",
            )
        except Exception as exc:  # noqa: BLE001 — 重研判 fail-soft，绝不反噬飞书主响应
            logger.error(
                "plan_revision_adjust",
                status="failed",
                execution_id=execution_id,
                node_id=node_id,
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )


async def _do_revise_cancel_async(
    *,
    execution_id: str,
    node_id: str,
    responder_id: str,
) -> None:
    """后台：取消修订 → 不改方案 → 发取消卡 → approve_node 恢复（保持原方案）。"""
    started = perf_counter()
    with bind_task_context(
        user_id=responder_id or None,
        source="feishu",
        component=_COMPONENT,
    ):
        try:
            node_execution = await _aget_waiting_node(execution_id, node_id)
            if node_execution is None:
                logger.info(
                    "plan_revision_cancel_ignored_not_waiting",
                    execution_id=execution_id,
                    node_id=node_id,
                    component=_COMPONENT,
                    category="caller",
                )
                return

            output = node_execution.output_data or {}
            chat_id = output.get("chat_id", "")

            # 取消卡（best-effort）。
            if chat_id:
                await _send_card_best_effort(
                    space=await _resolve_space(node_execution),
                    chat_id=chat_id,
                    card=build_plan_revision_done_card({"cancelled": True}),
                )

            # 恢复工作流（保持原方案，不修订）。
            node_execution.approval_data = {"revision_applied": False, "cancelled": True}
            await node_execution.asave(update_fields=["approval_data"])

            workflow_execution = node_execution.workflow_execution
            if workflow_execution.status == ExecutionStatus.SUSPENDED:
                workflow_execution.status = ExecutionStatus.RUNNING
                await workflow_execution.asave(update_fields=["status"])

            responder = _FeishuResponder(responder_id)
            await WorkflowEngine().approve_node(
                node_execution, responder, "plan_revision_cancel"
            )

            logger.info(
                "plan_revision_cancel",
                execution_id=execution_id,
                node_id=node_id,
                duration_ms=round((perf_counter() - started) * 1000, 2),
                component=_COMPONENT,
                category="caller",
            )
        except Exception as exc:  # noqa: BLE001 — 取消 fail-soft，绝不反噬飞书主响应
            logger.error(
                "plan_revision_cancel",
                status="failed",
                execution_id=execution_id,
                node_id=node_id,
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )


async def _send_card_best_effort(
    *, space: Any, chat_id: str, card: dict[str, Any]
) -> None:
    """普通发卡（问询卡 / 终态卡），best-effort 不反噬恢复/挂起。"""
    try:
        im_client = await create_feishu_im_client_for_project(space)
        await im_client.send_card(
            receive_id=chat_id, receive_id_type="chat_id", card=card
        )
    except Exception as exc:  # noqa: BLE001 — 发卡失败不阻断主流程
        logger.warning(
            "plan_revision_card_send_failed",
            error_type=type(exc).__name__,
            component=_COMPONENT,
            category="caller",
        )


class _FeishuResponder:
    """轻量回复者对象（approve_node 审计归因，镜像 repo_association_callback）。"""

    def __init__(self, open_id: str) -> None:
        self.id = open_id
        self.username = f"feishu:{open_id}"

    def __str__(self) -> str:
        return self.username
