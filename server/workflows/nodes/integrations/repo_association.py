"""业务↔仓库关联评审节点（REPO-01/02，88-04）。

``RepoAssociationNode``：把 88-02 选仓 + 88-03 逐仓深验能力包成「项目群多轮卡片确认」的
人机协同回路。与 ``BoardSplitReviewNode`` 同构（首发拉群 + 流式发卡 + ``waiting_event``），
并复用 ``AICodingNode`` 的容器续驱范式（``_resume_from_callback`` 重入聚合）。

``execute`` 三分支（据 ``node_execution.output_data`` 标记路由）：

① **首发**（无标记）：解析空间/项目/触发用户 → ``resolve_or_create_group`` 复用/建项目群 →
  ``RepoAssociationService.propose`` 选仓候选 → CardKit 流式候选卡 →
  ``WorkflowEventSubscription(RepoAssocCallback)`` 超时兜底 → ``waiting_event``
  （output_data 持久化 proposal/sources/chat_id/round=1/stage="clarify"）。

② **确认派发**（``output_data._confirmed_repo_ids``，由确认回调写入并重入）：
  ``confirm_repos`` 置 confirmed → ``dispatch_verify`` 逐仓 fan-out explore 容器深验
  （透传本节点 ``node_execution_id`` 使容器完成回调经 ``_schedule_workflow_resume`` 续驱本节点）
  → 发验证进行中卡 → 保持 ``waiting_event``（stage="verifying"，持久化 confirmed_repo_ids）。

③ **续驱聚合**（``output_data._resume_from_callback``，容器深验完成重入）：
  ``collect_verdicts`` 聚合各仓 verdict → 有 mismatch：发回退卡 + 保持 ``waiting_event``
  （stage="reconfirm"）；全 fit/可接受：发最终确认卡 → ``completed`` 走 verified handle。
  per-repo ``verified`` 状态在容器回调 ``record_verdict``（service）时已置（INV-6 唯一写口）。

观测：``initiated_by_user_id`` 取 ``WorkflowExecution.triggered_by_id``（缺 system）并透传
service/dispatch；发卡/续驱整段 best-effort try/except（异常 swallow+warning，绝不反噬挂起 /
回灌容器回调 5xx，mirror AICodingNode._resume_wave）。

自动注册：放在 ``workflows/nodes/integrations/`` 下且声明 ``node_type`` 即被发现。
"""

from __future__ import annotations

from datetime import timedelta
from time import perf_counter
from typing import Any, ClassVar

import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone

from feishu.cards.repo_association_card import (
    build_repo_assoc_card,
    build_repo_assoc_done_card,
    build_repo_assoc_mismatch_card,
    build_repo_assoc_verifying_card,
    render_candidates_markdown,
)
from initiatives.services.project_service import ProjectService
from initiatives.services.repo_association_service import RepoAssociationService
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

_COMPONENT = "repo_association"
_STREAM_ELEMENT_ID = "repo_md"


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


@sync_to_async
def _aload_associations(project: Any, repo_ids: list[str]) -> list[Any]:
    """读取确认批次的 RepoAssociation（含仓名，供续驱聚合 + 渲染；只读不写，INV-6 不涉及）。"""
    from initiatives.models import RepoAssociation

    ids = [str(r) for r in (repo_ids or []) if r]
    if not ids:
        return []
    return list(
        RepoAssociation.objects.filter(
            project=project, repository_id__in=ids
        ).select_related("repository")
    )


@register_node
class RepoAssociationNode(BaseNode):
    """业务↔仓库关联评审节点：选仓候选卡 + 逐仓深验续驱聚合（共用 RepoAssociationService）。"""

    node_type: ClassVar[str] = "repo_association"
    display_name: ClassVar[str] = "业务关联仓库"
    description: ClassVar[str] = (
        "基于拆分结果选候选仓，在项目群以流式卡片确认，逐仓容器深验后聚合判定 mismatch/fit"
    )
    icon: ClassVar[str] = "git-branch"
    category: ClassVar[NodeCategory] = NodeCategory.INTEGRATION
    execution_mode: ClassVar[str] = "server_local"
    is_blocking: ClassVar[bool] = True

    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "feature_list": {
                "type": "string",
                "title": "feature 来源",
                "description": "feature list / 拆分提案来源（支持模板变量，如 {{nodes.SPLIT.proposal}}）",
                "default": "",
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
            description="上游输出，可提供拆分提案 / feature list（含 features_flat）",
        ),
    ]

    outputs: ClassVar[list[NodePort]] = [
        NodePort(
            name="verified",
            label="已验证",
            port_type=PortType.OBJECT,
            description="逐仓深验全 fit / 接受 → 关联确认完成",
        ),
        NodePort(
            name="reconfirm",
            label="回退重确认",
            port_type=PortType.OBJECT,
            description="深验发现 mismatch，等用户接受 / 重新确认（保持等待）",
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
        """三分支路由：首发选仓候选卡 / 确认派发深验 / 续驱聚合判 mismatch-fit。"""
        output_data = self._node_output_data(context)

        # ③ 续驱聚合（容器深验完成经 _schedule_workflow_resume 重入）—— 整段 fail-soft。
        if output_data.get("_resume_from_callback") or output_data.get(
            "_all_containers_completed"
        ):
            return await self._resume_aggregate(context, output_data)

        # ② 确认派发（确认回调写入 _confirmed_repo_ids 并重入）。
        if output_data.get("_confirmed_repo_ids"):
            return await self._confirm_dispatch(context, output_data)

        # ① 首发：选仓候选卡 + waiting_event。
        return await self._first_dispatch(context)

    # ------------------------------------------------------------------
    # ① 首发：propose → 候选卡 → waiting_event
    # ------------------------------------------------------------------

    async def _first_dispatch(self, context: ExecutionContext) -> NodeResult:
        log = logger.bind(execution_id=context.execution_id, node_id=context.node_id)
        config = context.node_config
        member_ids = _parse_id_list(config.get("member_ids", ""), context)

        feature_list = self._resolve_feature_list(context)
        if not feature_list:
            return NodeResult(
                status="failed",
                error="未提供任何 feature list / 拆分提案输入源（上游 default 或 config）",
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

        # 复用/建项目群 + bot 入群（fail-soft：空 chat_id → 无法拉群）。
        chat_id = await ProjectService().resolve_or_create_group(
            project=project,
            member_ids=member_ids,
            initiated_by_user_id=initiated_by_user_id,
        )
        if not chat_id:
            log.warning("repo_association_no_chat", component=_COMPONENT, category="caller")
            return NodeResult(
                status="failed",
                error="无法复用或创建项目群（建群失败），候选卡无法下发",
                next_handle="error",
            )

        # 选仓候选提案（COMBINED 选仓，共用 service）。
        try:
            proposal = await RepoAssociationService().propose(
                space=space,
                feature_list=feature_list,
                project=project,
                initiated_by_user_id=initiated_by_user_id,
            )
        except Exception as exc:  # noqa: BLE001 — 选仓失败走 error handle
            error_msg = str(exc) or f"{type(exc).__name__}: 选仓失败"
            log.error(
                "repo_association_propose_failed",
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )
            return NodeResult(status="failed", error=error_msg, next_handle="error")

        # CardKit 流式候选卡（失败 fail-soft 降级普通发卡）。
        card = build_repo_assoc_card(
            proposal,
            execution_id=context.execution_id,
            node_id=context.node_id,
            round=1,
            streamable_element_id=_STREAM_ELEMENT_ID,
        )
        im_service = await FeishuIMService.create(space)
        card_id = await self._send_streaming_card(
            im_service, chat_id, card, render_candidates_markdown(proposal), log=log
        )

        log.info(
            "repo_association_card_sent",
            chat_id=chat_id,
            card_id=card_id,
            round=1,
            candidate_count=len(proposal.get("candidates") or []),
            initiated_by_user_id=initiated_by_user_id,
            component=_COMPONENT,
            category="caller",
        )

        # 事件订阅（超时兜底）。
        if context.workflow_execution and context.node_execution:
            await WorkflowEventSubscription.objects.acreate(
                workflow_execution=context.workflow_execution,
                node_execution=context.node_execution,
                event_type="RepoAssocCallback",
                project_key=context.workflow_context.get("project_key", ""),
                timeout_at=timezone.now() + timedelta(minutes=60),
                timeout_action="fail",
            )

        return NodeResult(
            status="waiting_event",
            output={
                "proposal": proposal,
                "sources": {"feature_list": feature_list},
                "chat_id": chat_id,
                "card_id": card_id,
                "round": 1,
                "stage": "clarify",
                "member_ids": member_ids,
            },
        )

    # ------------------------------------------------------------------
    # ② 确认派发：confirm_repos → dispatch_verify → 验证进行中卡 → waiting_event
    # ------------------------------------------------------------------

    async def _confirm_dispatch(
        self, context: ExecutionContext, output_data: dict[str, Any]
    ) -> NodeResult:
        log = logger.bind(execution_id=context.execution_id, node_id=context.node_id)
        repo_ids = [str(r) for r in (output_data.get("_confirmed_repo_ids") or []) if r]
        initiated_by_user_id = self._resolve_initiator(context)
        node_execution_id = (
            str(context.node_execution.id) if context.node_execution else ""
        )
        chat_id = str(output_data.get("chat_id") or "")

        try:
            space = await _resolve_space(context)
            project = await _aresolve_project(space) if space is not None else None
            if project is None:
                raise RuntimeError("no_project_for_space")

            service = RepoAssociationService()
            confirmed = await service.confirm_repos(
                project=project,
                repo_ids=repo_ids,
                initiated_by_user_id=initiated_by_user_id,
            )
            dispatch_result = await service.dispatch_verify(
                project=project,
                confirmed=confirmed,
                node_execution_id=node_execution_id,
                initiated_by_user_id=initiated_by_user_id,
            )

            # 验证进行中卡（best-effort，发卡失败不阻断挂起）。
            if chat_id and space is not None:
                await self._send_card_best_effort(
                    space,
                    chat_id,
                    build_repo_assoc_verifying_card(
                        [str(a.repository_id) for a in confirmed]
                    ),
                    log=log,
                )

            log.info(
                "repo_association_confirm_dispatched",
                confirmed_count=len(confirmed),
                dispatched=len(dispatch_result.get("dispatched") or []),
                runner_offline=dispatch_result.get("runner_offline"),
                initiated_by_user_id=initiated_by_user_id,
                component=_COMPONENT,
                category="caller",
            )
        except Exception as exc:  # noqa: BLE001 — 确认派发 fail-soft，不反噬挂起
            log.warning(
                "repo_association_confirm_dispatch_failed",
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )

        return NodeResult(
            status="waiting_event",
            output={
                **{k: v for k, v in output_data.items() if not k.startswith("_")},
                "confirmed_repo_ids": repo_ids,
                "stage": "verifying",
            },
        )

    # ------------------------------------------------------------------
    # ③ 续驱聚合：collect_verdicts → mismatch 回退卡 / done 终态卡
    # ------------------------------------------------------------------

    async def _resume_aggregate(
        self, context: ExecutionContext, output_data: dict[str, Any]
    ) -> NodeResult:
        started = perf_counter()
        log = logger.bind(execution_id=context.execution_id, node_id=context.node_id)
        chat_id = str(output_data.get("chat_id") or "")
        round_no = int(output_data.get("round", 1) or 1)
        repo_ids = [
            str(r) for r in (output_data.get("confirmed_repo_ids") or []) if r
        ]
        try:
            space = await _resolve_space(context)
            project = await _aresolve_project(space) if space is not None else None
            associations = (
                await _aload_associations(project, repo_ids)
                if project is not None
                else []
            )

            service = RepoAssociationService()
            verdicts = await service.collect_verdicts(associations)

            id_to_name = {
                str(a.repository_id): getattr(
                    getattr(a, "repository", None), "name", ""
                )
                or str(a.repository_id)
                for a in associations
            }
            named = {
                key: [id_to_name.get(rid, rid) for rid in verdicts.get(key) or []]
                for key in ("fit", "mismatch", "unknown")
            }

            duration_ms = round((perf_counter() - started) * 1000, 2)
            log.info(
                "repo_association_resume",
                mismatch_count=len(verdicts.get("mismatch") or []),
                fit_count=len(verdicts.get("fit") or []),
                unknown_count=len(verdicts.get("unknown") or []),
                duration_ms=duration_ms,
                initiated_by_user_id=self._resolve_initiator(context),
                component=_COMPONENT,
                category="caller",
            )

            # 有 mismatch → 发回退卡，保持 waiting（等用户接受 / 重新确认）。
            if verdicts.get("mismatch"):
                if chat_id and space is not None:
                    await self._send_card_best_effort(
                        space,
                        chat_id,
                        build_repo_assoc_mismatch_card(
                            named,
                            execution_id=context.execution_id,
                            node_id=context.node_id,
                            round=round_no,
                        ),
                        log=log,
                    )
                return NodeResult(
                    status="waiting_event",
                    output={
                        **{
                            k: v
                            for k, v in output_data.items()
                            if not k.startswith("_")
                        },
                        "stage": "reconfirm",
                        "verdicts": verdicts,
                    },
                )

            # 全 fit / 可接受 → 发最终确认卡 + completed（per-repo verified 已经 service 落地）。
            verified_repos = named.get("fit", []) + named.get("unknown", [])
            if chat_id and space is not None:
                await self._send_card_best_effort(
                    space,
                    chat_id,
                    build_repo_assoc_done_card(
                        {"verified_repos": verified_repos, "verdicts": named}
                    ),
                    log=log,
                )
            return NodeResult(
                status="completed",
                next_handle="verified",
                output={"verified_repos": verified_repos, "verdicts": verdicts},
            )
        except Exception as exc:  # noqa: BLE001 — 续驱整段 fail-soft，绝不回 5xx
            log.warning(
                "repo_association_resume_failed",
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )
            return NodeResult(
                status="completed",
                next_handle="verified",
                output={"verified_repos": [], "verdicts": {}, "degraded": True},
            )

    # ------------------------------------------------------------------
    # 发卡 helpers（CardKit 流式 + 普通 best-effort）
    # ------------------------------------------------------------------

    async def _send_streaming_card(
        self,
        im_service: Any,
        chat_id: str,
        card: dict[str, Any],
        content: str,
        *,
        log: Any,
    ) -> str:
        """CardKit 流式序列下发：create→send→stream→settle（sequence 单调递增）。

        任一步失败 fail-soft：降级为普通 ``send_card`` 一次发出，返回 ""（无 card_id）。
        """
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
                "repo_association_stream_fallback",
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )
            try:
                fallback = dict(card)
                fallback["config"] = {"wide_screen_mode": True}
                body = fallback.get("body", {})
                elements = list(body.get("elements") or [])
                if elements:
                    elements[0] = {"tag": "markdown", "content": content}
                fallback["body"] = {"elements": elements}
                await im_service.send_card(
                    receive_id=chat_id, receive_id_type="chat_id", card=fallback
                )
            except Exception:  # noqa: BLE001 — 降级发卡再失败也不反噬挂起
                log.warning("repo_association_card_send_failed_after_fallback")
            return ""

    async def _send_card_best_effort(
        self, space: Any, chat_id: str, card: dict[str, Any], *, log: Any
    ) -> None:
        """普通发卡（验证进行中 / 回退 / 终态卡），best-effort 不反噬主流程。"""
        try:
            im_service = await FeishuIMService.create(space)
            await im_service.send_card(
                receive_id=chat_id, receive_id_type="chat_id", card=card
            )
        except Exception as exc:  # noqa: BLE001 — 发卡失败不阻断续驱/挂起
            log.warning(
                "repo_association_card_send_failed",
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )

    # ------------------------------------------------------------------
    # 输入解析
    # ------------------------------------------------------------------

    @staticmethod
    def _node_output_data(context: ExecutionContext) -> dict[str, Any]:
        """取本节点 NodeExecution.output_data（续驱标记载体；缺则空 dict）。"""
        node_exec = context.node_execution
        if node_exec is None:
            return {}
        return getattr(node_exec, "output_data", None) or {}

    @staticmethod
    def _resolve_feature_list(context: ExecutionContext) -> Any:
        """解析 feature list / 拆分提案来源：config 模板 > input_data（proposal/features_flat）。"""
        config = context.node_config or {}
        raw = config.get("feature_list", "") or ""
        if isinstance(raw, str) and "{{" in raw:
            try:
                resolved = context.get_template_value(raw)
            except Exception:  # noqa: BLE001 — 模板解析失败回退 input
                resolved = None
            if resolved:
                return resolved
        elif raw and not isinstance(raw, str):
            return raw

        data = context.input_data or {}
        if isinstance(data, dict):
            if data.get("features_flat"):
                return {"features_flat": data["features_flat"]}
            proposal = data.get("proposal")
            if isinstance(proposal, dict) and proposal.get("features_flat"):
                return proposal
            if data.get("modules") or data.get("features_flat"):
                return data
        elif isinstance(data, list) and data:
            return data
        return None

    @staticmethod
    def _resolve_initiator(context: ExecutionContext) -> str:
        """取工作流触发用户 id（缺记 system）。"""
        execution = context.workflow_execution
        if execution is not None:
            triggered_by_id = getattr(execution, "triggered_by_id", None)
            if triggered_by_id:
                return str(triggered_by_id)
        return "system"
