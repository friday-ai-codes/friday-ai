"""业务↔仓库关联卡片回调状态机（REPO-02，88-05）。

逐字镜像 ``board_split_callback`` 范式：同步处理器（飞书回调需 3s 内响应）即时返回轻量
确认卡，重活在 ``_run_in_thread`` 后台线程做（worker 入口 ``bind_task_context`` re-bind
触发用户）。前缀 ``repo_assoc_`` 唯一，不撞 ``board_split_`` / ``chat_question_`` 等既有
回调。

四个动作分支（D-03 交互回路）：

- ``repo_assoc_confirm``：用户点「确认这些仓库」→ ``confirm_repos`` 置 confirmed +
  ``dispatch_verify`` 派逐仓深验容器（透传本节点 ``node_execution_id`` 使容器完成回调经
  ``_schedule_workflow_resume`` 续驱本节点聚合）→ 发验证进行中卡 → **保持 waiting**
  （绝不 approve，更新 ``output_data`` stage="verifying"）。
- ``repo_assoc_refine``：用户输入补充澄清 → 带 ``extra_instruction`` 重 ``refine`` 多轮重
  route → 更新 ``output_data``（round+1）→ 重发候选流式卡 → 保持 waiting（不 approve）。
- ``repo_assoc_reconfirm``：深验发现不符后用户点「重新确认仓库」→ ``reopen_candidates``
  回置 proposed → ``output_data`` stage="clarify" → 重发候选卡 → 保持 waiting。
- ``repo_assoc_accept_mismatch``：用户点「接受并继续」→ ``accept_mismatch`` 置
  status=verified → 发最终确认卡 → ``approve_node`` 恢复工作流（携 verified 仓 + verdict）。

全程 fail-soft：异常记 ``repo_association_*``(failed) 不反噬主流程；正文/异常脱敏；归因
``callback.user_open_id``（bind_task_context re-bind）。``RepoAssociation`` 状态变更一律经
``RepoAssociationService``（INV-6），本回调绝不旁路写表。
"""

from __future__ import annotations

import json
from time import perf_counter
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from common.log_context import bind_task_context
from common.logging import redact_secrets_in_text
from feishu.cards.repo_association_card import (
    build_repo_assoc_card,
    build_repo_assoc_done_card,
    build_repo_assoc_verifying_card,
    render_candidates_markdown,
)
from feishu.views import CardCallback, register_card_callback
from initiatives.services.repo_association_service import RepoAssociationService
from services.feishu_im import create_feishu_im_client_for_project
from workflows.engine.scheduler import WorkflowEngine, _run_in_thread
from workflows.models.execution import (
    ExecutionStatus,
    NodeExecution,
    NodeExecutionStatus,
)

logger = structlog.get_logger(__name__)

_COMPONENT = "repo_association"
_STREAM_ELEMENT_ID = "repo_md"


@register_card_callback("repo_assoc_")
def handle_repo_assoc_action(callback: CardCallback) -> dict[str, Any] | None:
    """仓库关联卡片回调入口：确认 / 澄清 / 回退重确认 / 接受 mismatch（同步即时返回确认卡）。"""
    data = _extract_callback_data(callback)
    if not data:
        return None

    action = data.get("action", "")
    execution_id = data.get("execution_id", "")
    node_id = data.get("node_id", "")
    round_no = int(data.get("round", 1) or 1)
    # 输入框内容经 CardCallbackView 把 form_value 合并进 action_value。
    refine_input = str(data.get("refine_input", "") or "").strip()
    repo_ids = [str(r) for r in (data.get("repo_ids") or []) if r]

    if not execution_id or not node_id:
        logger.warning(
            "repo_association_callback_missing_ids",
            action=action,
            component=_COMPONENT,
            category="caller",
        )
        return None

    responder_id = callback.user_open_id

    if action == "repo_assoc_confirm":
        logger.info(
            "repo_association_card_action",
            action=action,
            execution_id=execution_id,
            node_id=node_id,
            round=round_no,
            component=_COMPONENT,
            category="caller",
        )
        _run_in_thread(
            _do_confirm_and_verify_async(
                execution_id=execution_id,
                node_id=node_id,
                repo_ids=repo_ids,
                responder_id=responder_id,
            )
        )
        return _ack_card("已收到，正在确认仓库并启动逐仓深度校验…")

    if action == "repo_assoc_refine":
        if not refine_input:
            logger.warning(
                "repo_association_refine_missing_input",
                execution_id=execution_id,
                node_id=node_id,
                component=_COMPONENT,
                category="caller",
            )
            return _ack_card("请输入补充澄清要求后再点发送。")
        logger.info(
            "repo_association_card_action",
            action=action,
            execution_id=execution_id,
            node_id=node_id,
            round=round_no,
            component=_COMPONENT,
            category="caller",
        )
        _run_in_thread(
            _do_refine_async(
                execution_id=execution_id,
                node_id=node_id,
                refine_input=refine_input,
                responder_id=responder_id,
            )
        )
        return _ack_card("已收到，正在按你的要求重新匹配候选仓库…")

    if action == "repo_assoc_reconfirm":
        logger.info(
            "repo_association_card_action",
            action=action,
            execution_id=execution_id,
            node_id=node_id,
            round=round_no,
            component=_COMPONENT,
            category="caller",
        )
        _run_in_thread(
            _do_reconfirm_async(
                execution_id=execution_id,
                node_id=node_id,
                responder_id=responder_id,
            )
        )
        return _ack_card("已收到，正在重新打开候选仓库供你确认…")

    if action == "repo_assoc_accept_mismatch":
        logger.info(
            "repo_association_card_action",
            action=action,
            execution_id=execution_id,
            node_id=node_id,
            round=round_no,
            component=_COMPONENT,
            category="caller",
        )
        _run_in_thread(
            _do_accept_async(
                execution_id=execution_id,
                node_id=node_id,
                responder_id=responder_id,
            )
        )
        return _ack_card("已收到你的确认，正在收尾仓库关联…")

    logger.warning(
        "repo_association_callback_unknown_action",
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
            "title": {"tag": "plain_text", "content": "业务关联仓库"},
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
def _aload_associations(project: Any, repo_ids: list[str]) -> list[Any]:
    """读取确认批次的 RepoAssociation（含仓名，供接受/回退；只读不写，INV-6 不涉及）。"""
    from initiatives.models import RepoAssociation

    ids = [str(r) for r in (repo_ids or []) if r]
    if not ids:
        return []
    return list(
        RepoAssociation.objects.filter(
            project=project, repository_id__in=ids
        ).select_related("repository")
    )


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


async def _do_confirm_and_verify_async(
    *,
    execution_id: str,
    node_id: str,
    repo_ids: list[str],
    responder_id: str,
) -> None:
    """后台：确认仓库 → confirm_repos + dispatch_verify 派逐仓深验 → 发卡 → 保持 waiting。

    绝不 approve——逐仓容器深验完成后经 ``_schedule_workflow_resume`` 重入节点续驱聚合
    （fail-soft + re-bind）。
    """
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
                    "repo_association_confirm_ignored_not_waiting",
                    execution_id=execution_id,
                    node_id=node_id,
                    component=_COMPONENT,
                    category="caller",
                )
                return

            output = node_execution.output_data or {}
            proposal = output.get("proposal") or {}
            chat_id = output.get("chat_id", "")

            # output_data 权威：confirm 集 = 候选交集（action_value 仅携路由 ID）。
            candidate_ids = _proposal_candidate_ids(proposal)
            confirm_ids = [r for r in repo_ids if r in candidate_ids] or candidate_ids
            if not confirm_ids:
                logger.info(
                    "repo_association_confirm_no_candidates",
                    execution_id=execution_id,
                    node_id=node_id,
                    component=_COMPONENT,
                    category="caller",
                )
                return

            space = await _resolve_space(node_execution)
            project = await _aresolve_project(space)
            if project is None:
                raise RuntimeError("no_project_for_space")

            service = RepoAssociationService()
            confirmed = await service.confirm_repos(
                project=project,
                repo_ids=confirm_ids,
                initiated_by_user_id=responder_id or "system",
            )
            dispatch_result = await service.dispatch_verify(
                project=project,
                confirmed=confirmed,
                node_execution_id=str(node_execution.id),
                initiated_by_user_id=responder_id or "system",
            )

            # 更新 output_data（stage=verifying，持久化 confirmed_repo_ids）——保持 waiting。
            node_execution.output_data = {
                **output,
                "stage": "verifying",
                "confirmed_repo_ids": [str(a.repository_id) for a in confirmed],
            }
            await node_execution.asave(update_fields=["output_data"])

            # 验证进行中卡（best-effort，发卡失败不阻断挂起）。
            if chat_id:
                await _send_card_best_effort(
                    space=space,
                    chat_id=chat_id,
                    card=build_repo_assoc_verifying_card(
                        [str(a.repository_id) for a in confirmed]
                    ),
                )

            logger.info(
                "repo_association_confirm",
                execution_id=execution_id,
                node_id=node_id,
                confirmed_count=len(confirmed),
                dispatched=len(dispatch_result.get("dispatched") or []),
                runner_offline=dispatch_result.get("runner_offline"),
                duration_ms=round((perf_counter() - started) * 1000, 2),
                component=_COMPONENT,
                category="caller",
            )
        except Exception as exc:  # noqa: BLE001 — 回调重活 fail-soft，绝不反噬飞书主响应
            logger.error(
                "repo_association_confirm",
                status="failed",
                execution_id=execution_id,
                node_id=node_id,
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )


async def _do_refine_async(
    *,
    execution_id: str,
    node_id: str,
    refine_input: str,
    responder_id: str,
) -> None:
    """后台：多轮重 route → 更新 output_data（round+1）→ 重发候选流式卡 → 保持 waiting。"""
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
                    "repo_association_refine_ignored_not_waiting",
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
            project = await _aresolve_project(space)

            proposal = await RepoAssociationService().refine(
                space=space,
                project=project,
                feature_list=sources.get("feature_list"),
                extra_instruction=refine_input,
                initiated_by_user_id=responder_id or "system",
                round_no=next_round,
            )

            # 更新 output_data（round+1，proposal=新，回 clarify）——保持 waiting，不 approve。
            node_execution.output_data = {
                **output,
                "round": next_round,
                "proposal": proposal,
                "stage": "clarify",
            }
            await node_execution.asave(update_fields=["output_data"])

            # 重发候选流式卡（新建实体，规避跨轮 sequence 状态丢失）。
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
                "repo_association_refine",
                execution_id=execution_id,
                node_id=node_id,
                round=next_round,
                candidate_count=len(proposal.get("candidates") or []),
                duration_ms=round((perf_counter() - started) * 1000, 2),
                component=_COMPONENT,
                category="caller",
            )
        except Exception as exc:  # noqa: BLE001 — 重 route fail-soft，绝不反噬飞书主响应
            logger.error(
                "repo_association_refine",
                status="failed",
                execution_id=execution_id,
                node_id=node_id,
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )


async def _do_reconfirm_async(
    *,
    execution_id: str,
    node_id: str,
    responder_id: str,
) -> None:
    """后台：回退重确认 → reopen_candidates 回 proposed → output_data stage=clarify → 重发候选卡。"""
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
                    "repo_association_reconfirm_ignored_not_waiting",
                    execution_id=execution_id,
                    node_id=node_id,
                    component=_COMPONENT,
                    category="caller",
                )
                return

            output = node_execution.output_data or {}
            proposal = output.get("proposal") or {}
            chat_id = output.get("chat_id", "")
            round_no = int(output.get("round", 1) or 1)
            repo_ids = [
                str(r) for r in (output.get("confirmed_repo_ids") or []) if r
            ]

            space = await _resolve_space(node_execution)
            project = await _aresolve_project(space)

            # 回退重确认：把已流转关联回置 proposed（经 service，INV-6）。
            reopened = 0
            if project is not None:
                service = RepoAssociationService()
                associations = await _aload_associations(project, repo_ids)
                for assoc in associations:
                    if await service.reopen_candidates(
                        assoc, initiated_by_user_id=responder_id or "system"
                    ):
                        reopened += 1

            # 回 clarify 阶段（重开候选选择）——保持 waiting，不 approve。
            node_execution.output_data = {
                **{k: v for k, v in output.items() if k != "confirmed_repo_ids"},
                "stage": "clarify",
            }
            await node_execution.asave(update_fields=["output_data"])

            # 重发候选卡供重新确认。
            if chat_id:
                await _resend_streaming_card(
                    space=space,
                    chat_id=chat_id,
                    proposal=proposal,
                    execution_id=execution_id,
                    node_id=node_id,
                    round_no=round_no,
                )

            logger.info(
                "repo_association_reconfirm",
                execution_id=execution_id,
                node_id=node_id,
                reopened_count=reopened,
                duration_ms=round((perf_counter() - started) * 1000, 2),
                component=_COMPONENT,
                category="caller",
            )
        except Exception as exc:  # noqa: BLE001 — 回退 fail-soft，绝不反噬飞书主响应
            logger.error(
                "repo_association_reconfirm",
                status="failed",
                execution_id=execution_id,
                node_id=node_id,
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )


async def _do_accept_async(
    *,
    execution_id: str,
    node_id: str,
    responder_id: str,
) -> None:
    """后台：接受 mismatch → accept_mismatch 置 verified → 发终态卡 → approve_node 恢复。"""
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
                    "repo_association_accept_ignored_not_waiting",
                    execution_id=execution_id,
                    node_id=node_id,
                    component=_COMPONENT,
                    category="caller",
                )
                return

            output = node_execution.output_data or {}
            chat_id = output.get("chat_id", "")
            verdicts = output.get("verdicts") or {}
            repo_ids = [
                str(r) for r in (output.get("confirmed_repo_ids") or []) if r
            ]

            space = await _resolve_space(node_execution)
            project = await _aresolve_project(space)
            associations = (
                await _aload_associations(project, repo_ids)
                if project is not None
                else []
            )

            # 接受 mismatch：批次内未终态关联一律置 verified（经 service，INV-6）。
            service = RepoAssociationService()
            accepted = 0
            for assoc in associations:
                if await service.accept_mismatch(
                    assoc, initiated_by_user_id=responder_id or "system"
                ):
                    accepted += 1

            verified_names = [
                getattr(getattr(a, "repository", None), "name", "")
                or str(a.repository_id)
                for a in associations
            ]

            # 最终确认终态卡（best-effort，发卡失败不阻断恢复）。
            if chat_id:
                await _send_card_best_effort(
                    space=space,
                    chat_id=chat_id,
                    card=build_repo_assoc_done_card(
                        {"verified_repos": verified_names, "verdicts": verdicts}
                    ),
                )

            # 恢复工作流（携 verified 仓 + verdict，next_handle verified）。
            node_execution.approval_data = {
                "verified_repos": verified_names,
                "verdicts": verdicts,
                "accepted_mismatch": True,
            }
            await node_execution.asave(update_fields=["approval_data"])

            workflow_execution = node_execution.workflow_execution
            if workflow_execution.status == ExecutionStatus.SUSPENDED:
                workflow_execution.status = ExecutionStatus.RUNNING
                await workflow_execution.asave(update_fields=["status"])

            responder = _FeishuResponder(responder_id)
            await WorkflowEngine().approve_node(
                node_execution, responder, "repo_assoc_accept_mismatch"
            )

            logger.info(
                "repo_association_accept_mismatch",
                execution_id=execution_id,
                node_id=node_id,
                accepted_count=accepted,
                verified_count=len(verified_names),
                duration_ms=round((perf_counter() - started) * 1000, 2),
                component=_COMPONENT,
                category="caller",
            )
        except Exception as exc:  # noqa: BLE001 — 接受 fail-soft，绝不反噬飞书主响应
            logger.error(
                "repo_association_accept_mismatch",
                status="failed",
                execution_id=execution_id,
                node_id=node_id,
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )


def _proposal_candidate_ids(proposal: dict[str, Any]) -> list[str]:
    """从提案抽候选仓 repo_id 集（output_data 权威，校验 action_value 携带的路由 ID）。"""
    ids: list[str] = []
    for cand in proposal.get("candidates") or []:
        repo_id = str((cand or {}).get("repo_id") or "").strip()
        if repo_id:
            ids.append(repo_id)
    return ids


async def _send_card_best_effort(
    *, space: Any, chat_id: str, card: dict[str, Any]
) -> None:
    """普通发卡（验证进行中 / 终态卡），best-effort 不反噬恢复/挂起。"""
    try:
        im_client = await create_feishu_im_client_for_project(space)
        await im_client.send_card(
            receive_id=chat_id, receive_id_type="chat_id", card=card
        )
    except Exception as exc:  # noqa: BLE001 — 发卡失败不阻断主流程
        logger.warning(
            "repo_association_card_send_failed",
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
    """重发 CardKit 流式候选卡（create→send→stream→settle，失败降级普通发卡）。"""
    card = build_repo_assoc_card(
        proposal,
        execution_id=execution_id,
        node_id=node_id,
        round=round_no,
        streamable_element_id=_STREAM_ELEMENT_ID,
    )
    content = render_candidates_markdown(proposal)
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
            "repo_association_resend_stream_fallback",
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
    """轻量回复者对象（approve_node 审计归因，镜像 board_split_callback）。"""

    def __init__(self, open_id: str) -> None:
        self.id = open_id
        self.username = f"feishu:{open_id}"

    def __str__(self) -> str:
        return self.username
