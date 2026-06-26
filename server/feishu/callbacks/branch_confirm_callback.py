"""分支确认卡片回调状态机（Phase 89 PLAN-04，建分支绑项目 HITL）。

逐字镜像 ``repo_association_callback`` / ``board_split_callback`` 范式：同步处理器（飞书回调需
3s 内响应）即时返回轻量确认卡，重活在 ``_run_in_thread`` 后台线程做（worker 入口
``bind_task_context`` re-bind 触发用户）。前缀 ``branch_confirm_`` 唯一，不撞 ``board_split_`` /
``repo_assoc_`` / ``plan_revise_`` / ``chat_question_`` 等既有回调。

三个动作分支：

- ``branch_confirm_apply``：用户点「确认建分支」→ ``BranchProvisionService.provision_and_bind``
  逐仓建推 + 绑项目（source=plan）→ 发终态卡 → ``approve_node`` 恢复工作流（回接 IDE 闭环）。
- ``branch_confirm_edit``：用户输入新 type → 用 server 权威组件重拼分支名（round+1）→ 重发确认卡
  → **保持 waiting**（不 approve）。
- ``branch_confirm_cancel``：用户点「取消」→ 不建分支 → 发取消卡 → ``approve_node``（携 cancelled）。

全程 fail-soft：异常记 ``branch_provision_failed``(failed) 不反噬主流程；正文/异常脱敏；归因
``callback.user_open_id``（bind_task_context re-bind）。``ProjectBranch`` 写一律经
``BranchProvisionService`` → ``ProjectBranchService``（INV-6），本回调绝不旁路写表。
"""

from __future__ import annotations

import json
from time import perf_counter
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from common.log_context import bind_task_context
from common.logging import redact_secrets_in_text
from feishu.cards.branch_confirm_card import (
    build_branch_confirm_card,
    build_branch_done_card,
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

_COMPONENT = "initiatives"


@register_card_callback("branch_confirm_")
def handle_branch_confirm_action(callback: CardCallback) -> dict[str, Any] | None:
    """分支确认卡片回调入口：确认建分支 / 改 type 重生成 / 取消（同步即时返回确认卡）。"""
    data = _extract_callback_data(callback)
    if not data:
        return None

    action = data.get("action", "")
    execution_id = data.get("execution_id", "")
    node_id = data.get("node_id", "")
    round_no = int(data.get("round", 1) or 1)
    type_input = str(data.get("type_input", "") or "").strip()

    if not execution_id or not node_id:
        logger.warning(
            "branch_confirm_callback_missing_ids",
            action=action,
            component=_COMPONENT,
            category="caller",
        )
        return None

    responder_id = callback.user_open_id

    if action == "branch_confirm_apply":
        logger.info(
            "branch_confirm_card_action",
            action=action,
            execution_id=execution_id,
            node_id=node_id,
            round=round_no,
            component=_COMPONENT,
            category="caller",
        )
        _run_in_thread(
            _do_apply_async(
                execution_id=execution_id,
                node_id=node_id,
                responder_id=responder_id,
            )
        )
        return _ack_card("已收到，正在按方案逐仓建分支并绑定项目…")

    if action == "branch_confirm_edit":
        if not type_input:
            logger.warning(
                "branch_confirm_edit_missing_input",
                execution_id=execution_id,
                node_id=node_id,
                component=_COMPONENT,
                category="caller",
            )
            return _ack_card("请输入分支类型（如 feat/fix/chore）后再点发送。")
        logger.info(
            "branch_confirm_card_action",
            action=action,
            execution_id=execution_id,
            node_id=node_id,
            round=round_no,
            component=_COMPONENT,
            category="caller",
        )
        _run_in_thread(
            _do_edit_async(
                execution_id=execution_id,
                node_id=node_id,
                type_input=type_input,
                responder_id=responder_id,
            )
        )
        return _ack_card("已收到，正在按新类型重新生成分支名…")

    if action == "branch_confirm_cancel":
        logger.info(
            "branch_confirm_card_action",
            action=action,
            execution_id=execution_id,
            node_id=node_id,
            round=round_no,
            component=_COMPONENT,
            category="caller",
        )
        _run_in_thread(
            _do_cancel_async(
                execution_id=execution_id,
                node_id=node_id,
                responder_id=responder_id,
            )
        )
        return _ack_card("已收到，本次不建分支。")

    logger.warning(
        "branch_confirm_callback_unknown_action",
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
            "title": {"tag": "plain_text", "content": "建分支绑项目"},
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
def _aload_repositories(repo_ids: list[str]) -> list[Any]:
    """读取分支计划涉及的 Repository（只读，供逐仓建推；INV-6 不涉及）。"""
    from repositories.models import Repository

    ids = [str(r) for r in (repo_ids or []) if r]
    if not ids:
        return []
    return list(Repository.objects.filter(id__in=ids, is_deleted=False))


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


async def _do_apply_async(
    *,
    execution_id: str,
    node_id: str,
    responder_id: str,
) -> None:
    """后台：逐仓建推 + 绑项目（source=plan）→ 发终态卡 → approve_node（fail-soft + re-bind）。"""
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
                    "branch_confirm_apply_ignored_not_waiting",
                    execution_id=execution_id,
                    node_id=node_id,
                    component=_COMPONENT,
                    category="caller",
                )
                return

            output = node_execution.output_data or {}
            branch_plan = output.get("branch_plan") or []
            chat_id = output.get("chat_id", "")
            feishu_board_id = str(output.get("feishu_board_id", "") or "")

            space = await _resolve_space(node_execution)
            project = await _aresolve_project(space)
            if project is None:
                raise RuntimeError("no_project_for_space")

            repo_ids = [
                str((item or {}).get("repository_id") or "")
                for item in branch_plan
                if (item or {}).get("repository_id")
            ]
            repositories = await _aload_repositories(repo_ids)
            branch_names = {
                str((item or {}).get("repository_id") or ""): str(
                    (item or {}).get("branch_name") or ""
                )
                for item in branch_plan
            }

            from initiatives.services.branch_provision_service import (
                BranchProvisionService,
            )

            result = await BranchProvisionService().provision_and_bind(
                project=project,
                repositories=repositories,
                branch_names=branch_names,
                initiated_by_user_id=responder_id or "system",
                feishu_board_id=feishu_board_id,
            )

            # 发终态卡（best-effort，发卡失败不阻断恢复）。
            if chat_id:
                await _send_card_best_effort(
                    space=space,
                    chat_id=chat_id,
                    card=build_branch_done_card(result),
                )

            # 恢复工作流（携建推绑结果）。
            node_execution.approval_data = {
                "succeeded": result.get("succeeded", []),
                "failed": result.get("failed", []),
                "all_succeeded": result.get("all_succeeded", False),
            }
            await node_execution.asave(update_fields=["approval_data"])

            workflow_execution = node_execution.workflow_execution
            if workflow_execution.status == ExecutionStatus.SUSPENDED:
                workflow_execution.status = ExecutionStatus.RUNNING
                await workflow_execution.asave(update_fields=["status"])

            responder = _FeishuResponder(responder_id)
            await WorkflowEngine().approve_node(node_execution, responder, "branch_confirm_apply")

            logger.info(
                "branch_confirm_applied",
                execution_id=execution_id,
                node_id=node_id,
                succeeded_count=len(result.get("succeeded", [])),
                failed_count=len(result.get("failed", [])),
                duration_ms=round((perf_counter() - started) * 1000, 2),
                component=_COMPONENT,
                category="caller",
            )
        except Exception as exc:  # noqa: BLE001 — 回调重活 fail-soft，绝不反噬飞书主响应
            logger.error(
                "branch_provision_failed",
                action="branch_confirm_apply",
                execution_id=execution_id,
                node_id=node_id,
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )


async def _do_edit_async(
    *,
    execution_id: str,
    node_id: str,
    type_input: str,
    responder_id: str,
) -> None:
    """后台：按新 type 用 server 权威组件重拼分支名 → round+1 → 重发确认卡 → 保持 waiting。"""
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
                    "branch_confirm_edit_ignored_not_waiting",
                    execution_id=execution_id,
                    node_id=node_id,
                    component=_COMPONENT,
                    category="caller",
                )
                return

            output = node_execution.output_data or {}
            branch_plan = output.get("branch_plan") or []
            current_round = int(output.get("round", 1) or 1)
            next_round = current_round + 1
            chat_id = output.get("chat_id", "")

            new_plan = _rebuild_branch_plan(branch_plan, type_input)

            node_execution.output_data = {
                **output,
                "round": next_round,
                "branch_plan": new_plan,
            }
            await node_execution.asave(update_fields=["output_data"])

            if chat_id:
                space = await _resolve_space(node_execution)
                await _send_card_best_effort(
                    space=space,
                    chat_id=chat_id,
                    card=build_branch_confirm_card(
                        new_plan,
                        execution_id=execution_id,
                        node_id=node_id,
                        round=next_round,
                    ),
                )

            logger.info(
                "branch_confirm_edited",
                execution_id=execution_id,
                node_id=node_id,
                round=next_round,
                duration_ms=round((perf_counter() - started) * 1000, 2),
                component=_COMPONENT,
                category="caller",
            )
        except Exception as exc:  # noqa: BLE001 — 重生成 fail-soft，绝不反噬飞书主响应
            logger.error(
                "branch_provision_failed",
                action="branch_confirm_edit",
                execution_id=execution_id,
                node_id=node_id,
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )


async def _do_cancel_async(
    *,
    execution_id: str,
    node_id: str,
    responder_id: str,
) -> None:
    """后台：取消建分支 → 发取消卡 → approve_node（携 cancelled，回接闭环结束）。"""
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
                    "branch_confirm_cancel_ignored_not_waiting",
                    execution_id=execution_id,
                    node_id=node_id,
                    component=_COMPONENT,
                    category="caller",
                )
                return

            output = node_execution.output_data or {}
            chat_id = output.get("chat_id", "")
            space = await _resolve_space(node_execution)

            if chat_id:
                await _send_card_best_effort(
                    space=space,
                    chat_id=chat_id,
                    card=build_branch_done_card({"cancelled": True}),
                )

            node_execution.approval_data = {
                "cancelled": True,
                "succeeded": [],
                "failed": [],
            }
            await node_execution.asave(update_fields=["approval_data"])

            workflow_execution = node_execution.workflow_execution
            if workflow_execution.status == ExecutionStatus.SUSPENDED:
                workflow_execution.status = ExecutionStatus.RUNNING
                await workflow_execution.asave(update_fields=["status"])

            responder = _FeishuResponder(responder_id)
            await WorkflowEngine().approve_node(node_execution, responder, "branch_confirm_cancel")

            logger.info(
                "branch_confirm_cancelled",
                execution_id=execution_id,
                node_id=node_id,
                duration_ms=round((perf_counter() - started) * 1000, 2),
                component=_COMPONENT,
                category="caller",
            )
        except Exception as exc:  # noqa: BLE001 — 取消 fail-soft，绝不反噬飞书主响应
            logger.error(
                "branch_provision_failed",
                action="branch_confirm_cancel",
                execution_id=execution_id,
                node_id=node_id,
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )


def _rebuild_branch_plan(
    branch_plan: list[dict[str, Any]], change_type: str
) -> list[dict[str, Any]]:
    """用新 ``change_type`` + server 权威组件重拼逐仓分支名（确定性，无 LLM）。"""
    from initiatives.services.branch_naming import build_branch_name

    new_plan: list[dict[str, Any]] = []
    for item in branch_plan:
        item = dict(item or {})
        item["change_type"] = change_type
        item["branch_name"] = build_branch_name(
            change_type=change_type,
            yymmdd=str(item.get("yymmdd") or ""),
            tracking_id=str(item.get("tracking_id") or ""),
            project_name=str(item.get("project_name") or ""),
            version=str(item.get("version") or ""),
        )
        new_plan.append(item)
    return new_plan


async def _send_card_best_effort(*, space: Any, chat_id: str, card: dict[str, Any]) -> None:
    """普通发卡（确认卡 / 终态卡），best-effort 不反噬恢复/挂起。"""
    try:
        im_client = await create_feishu_im_client_for_project(space)
        await im_client.send_card(receive_id=chat_id, receive_id_type="chat_id", card=card)
    except Exception as exc:  # noqa: BLE001 — 发卡失败不阻断主流程
        logger.warning(
            "branch_confirm_card_send_failed",
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
