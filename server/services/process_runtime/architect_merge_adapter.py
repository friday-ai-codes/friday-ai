"""ArchitectMergeAdapter —— reduce 段真实融合接线（Chassis v2 · P2，MERGE-01/02/03）。

实现「架构师融合」：收齐 session 的 valid ``PartialPlan``，调**可注入的 LLM 合成器**产
结构化 §7 ``MergedPlan``，跑 ``PlanValidator``；

- **通过** → 经 ``ArtifactService.create(artifact_type="technical_plan", content=...)`` 落
  ``ArtifactVersion``（取代旧 ``TechnicalPlanService`` 写 ``PlanVersion``）+ ``ArchitectMerge(passed)``；
  返回带 ``artifact_version_id`` 的结果（engine 据此经 transition 置
  ``ConvergenceSession.current_artifact_version``——adapter 不再自写指针）；末尾 best-effort
  调 ``spec_generation_hook`` 逐 SDD 仓产 spec draft（fail-soft）。
- **失败 / 合成异常** → ``ArchitectMerge(failed, report)`` + **不落 artifact**；返回带
  ``back_target`` 的失败结果（engine 据此回退）。

守 INV-6：artifact 经 ``ArtifactService``、``ArchitectMerge`` 经本 adapter 唯一写入。
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

import structlog
from asgiref.sync import sync_to_async

from delivery.artifacts.builtin_types import ARTIFACT_TYPE_TECHNICAL_PLAN
from delivery.models import (
    ArchitectMerge,
    ArchitectMergeStatus,
    ConvergenceSession,
)
from delivery.services import ArtifactContentInvalid, ArtifactService, ConvergenceSessionService
from delivery.services.event_taxonomy import (
    EVENT_CLARIFICATION_ASKED,
    EVENT_PLAN_MERGE_COMPLETED,
    EVENT_PLAN_MERGE_STARTED,
    EVENT_PLAN_VALIDATION_FAILED,
)
from services.process_runtime.merged_plan import validate_merged_plan
from services.process_runtime.plan_validator import validate_plan

logger = structlog.get_logger(__name__)

__all__ = [
    "MergedPlanSynthesizer",
    "LLMMergedPlanSynthesizer",
    "ArchitectMergeAdapter",
]


@runtime_checkable
class MergedPlanSynthesizer(Protocol):
    """架构师 LLM 合成器协议（可注入）：partials → §7 MergedPlan content dict。"""

    async def synthesize(self, session: ConvergenceSession, partials: list[dict]) -> dict: ...


class LLMMergedPlanSynthesizer:
    """默认 LLM 合成器：provider_config 解析 + chat model + 健壮 JSON 解析。"""

    async def synthesize(self, session: ConvergenceSession, partials: list[dict]) -> dict:
        from langchain_core.messages import HumanMessage, SystemMessage

        from agents.call_source import CallSource, use_call_source
        from agents.llm_factory import build_chat_model
        from services.provider_config import ProviderConfigService

        resolved = await ProviderConfigService.aresolve()
        model_name = (getattr(resolved, "extra", None) or {}).get("default_model", "")
        if not model_name:
            raise RuntimeError("no_default_model")
        model = build_chat_model(resolved, model_name, streaming=False)
        system = SystemMessage(content=self._system_prompt())
        human = HumanMessage(content=self._build_prompt(session, partials))
        with use_call_source(CallSource.PLAN_DEEPEN):
            response = await model.ainvoke([system, human])
        content = _content_to_text(response.content)
        merged = _parse_merged_json(content)
        if merged is None:
            raise ValueError("merged_plan_parse_failed")
        return merged

    @staticmethod
    def _system_prompt() -> str:
        return (
            "你是软件架构师，负责把多个单仓调研产物融合为一份跨仓主方案（MergedPlan）。"
            "只输出 JSON，不要任何解释。"
        )

    @staticmethod
    def _build_prompt(session: ConvergenceSession, partials: list[dict]) -> str:
        decomposition = session.decomposition or {}
        requirement = decomposition.get("requirement_text", "")
        partials_json = json.dumps(partials, ensure_ascii=False)
        return (
            f"需求：\n{requirement}\n\n"
            f"各仓调研产物（PartialPlan）：\n{partials_json}\n\n"
            "请融合为 §7 MergedPlan JSON，字段：\n"
            "- title / summary\n"
            "- api_contracts：跨仓契约汇总（[{name, repo}]）\n"
            "- dependency_dag：邻接表 {repo_id: [被依赖的 repo_id...]}\n"
            "- data_migrations：[{repository_id}]（按执行顺序）\n"
            "- compat_risks：兼容风险列表\n"
            "- release_order：[repo_id...]（被依赖仓先发）\n"
            "- rollback_plan：{repo_id: 回滚步骤}（覆盖各涉及仓）\n"
            "- execution_plan：[{id, name, repository_id, repository_name, "
            "branch_strategy, coding_instruction, dependencies, "
            "api_contracts_exposed, dependencies_on_other_repos}]\n"
            "并补充整体方案字段：\n"
            "- overall_plan：overall 整体方案叙述（文本）\n"
            "- cross_repo_context：跨仓上下文（文本）\n"
        )


class ArchitectMergeAdapter:
    """架构师融合 stage 依赖真实实现（MERGE-01/02/03）。"""

    MAX_MERGE_RETRIES = 1

    def __init__(
        self,
        *,
        synthesizer: MergedPlanSynthesizer | None = None,
        session_service: ConvergenceSessionService | None = None,
        artifact_service: ArtifactService | None = None,
        clarification_service: Any = None,
        spec_generation_hook: Any = None,
    ) -> None:
        self.synthesizer = synthesizer or LLMMergedPlanSynthesizer()
        self.session_service = session_service or ConvergenceSessionService()
        self.artifact_service = artifact_service or ArtifactService()
        if clarification_service is None:
            from delivery.services import ClarificationService

            clarification_service = ClarificationService()
        self.clarification_service = clarification_service
        if spec_generation_hook is None:
            from services.process_runtime.spec_generation import agenerate_specs_for_plan

            spec_generation_hook = agenerate_specs_for_plan
        self.spec_generation_hook = spec_generation_hook

    async def merge(self, session: ConvergenceSession) -> dict:
        """融合一次：pass → 落 ArtifactVersion + ArchitectMerge(passed)；fail → ArchitectMerge(failed)。"""
        partials = await self._collect_valid_partials(session)
        has_stale = await self._has_stale_or_missing(session, partials)
        attempt = await ArchitectMerge.objects.filter(session_id=session.id).acount()

        repo_ids = [str(p.get("repository_id", "")) for p in partials]
        await self._emit(session, EVENT_PLAN_MERGE_STARTED, {"partials": repo_ids})

        try:
            merged = await self.synthesizer.synthesize(session, partials)
        except Exception as exc:  # noqa: BLE001 — LLM 合成失败 graceful 降级
            logger.warning(
                "architect_synthesis_failed", session_id=str(session.id), error=str(exc)
            )
            report: dict[str, Any] = {"reason": "synthesis_failed", "error": str(exc)}
            await self._record_merge(session, ArchitectMergeStatus.FAILED, None, report, attempt)
            await self._emit(
                session, EVENT_PLAN_VALIDATION_FAILED, {"reasons": ["synthesis_failed"]}
            )
            return {
                "validation_status": "failed",
                "report": report,
                "back_target": "research",
                "attempt": attempt,
            }

        schema_ok, schema_err = validate_merged_plan(merged)
        if not schema_ok:
            report = {
                "valid": False,
                "errors": [{"check": "schema", "message": schema_err or "MergedPlan schema 非法"}],
            }
            return await self._handle_fail(session, report, attempt, has_stale)

        report = validate_plan(merged)
        if report.get("valid"):
            return await self._handle_pass(session, merged, report, attempt, has_stale)
        return await self._handle_fail(session, report, attempt, has_stale)

    async def _handle_pass(
        self,
        session: ConvergenceSession,
        merged: dict,
        report: dict,
        attempt: int,
        has_stale: bool,
    ) -> dict:
        """通过分支：经 ArtifactService 落 ArtifactVersion + ArchitectMerge(passed)。"""
        from delivery.models import WorkItem

        work_item = await WorkItem.objects.filter(id=session.work_item_id).afirst()
        try:
            artifact = await self.artifact_service.create(
                ARTIFACT_TYPE_TECHNICAL_PLAN,
                merged,
                title=str(merged.get("title") or ""),
                work_item=work_item,
                produced_by_session_id=str(session.id),
                produced_by_ref=EVENT_PLAN_MERGE_COMPLETED,
            )
        except ArtifactContentInvalid as exc:
            logger.warning(
                "merge_artifact_schema_invalid", session_id=str(session.id), error=str(exc)
            )
            report = {"valid": False, "errors": [{"check": "schema", "message": str(exc)}]}
            return await self._handle_fail(session, report, attempt, has_stale)

        version_id = artifact.current_version_id  # async 安全标量
        await self._record_merge(
            session, ArchitectMergeStatus.PASSED, version_id, report, attempt
        )
        await self._emit(
            session, EVENT_PLAN_MERGE_COMPLETED, {"artifact_version_id": str(version_id)}
        )
        try:
            await self.spec_generation_hook(version_id)
        except Exception:  # noqa: BLE001 — spec 生成 best-effort，绝不阻断融合返回
            logger.warning(
                "sdd_spec_generation_failed",
                session_id=str(session.id),
                artifact_version_id=str(version_id),
            )
        # #5 Part A：项目内 AI 对话产出的技术方案自动绑定到当前项目（镜像进 RESEARCH，best-effort）。
        await self._maybe_bind_plan_to_project(session, merged)
        return {
            "validation_status": "passed",
            "artifact_version_id": str(version_id),
            "attempt": attempt,
        }

    async def _maybe_bind_plan_to_project(
        self, session: ConvergenceSession, merged: dict
    ) -> None:
        """会话绑定了项目时，把生成的技术方案镜像进项目 RESEARCH 文档（绑定到当前项目）。

        反查链：``session.conversation_id`` → ``Conversation.bound_project_id`` /
        ``created_by``；经 ``ProjectDocService.append_research_note``（INV-6 写收口 + 脱敏 +
        非成员静默跳过）。整段 best-effort，任一步失败仅记 ``plan_bind_project_failed``，绝不反噬融合。
        """
        conversation_id = getattr(session, "conversation_id", None)
        if not conversation_id:
            return
        try:
            from chat.models import Conversation
            from initiatives.services.project_doc_service import ProjectDocService
            from services.process_runtime.render import render_merged_plan_markdown

            row = await Conversation.objects.filter(id=conversation_id).values(
                "bound_project_id", "created_by_id"
            ).afirst()
            if not row or not row.get("bound_project_id"):
                return
            project_id = row["bound_project_id"]
            contributor = await self._aget_user(row.get("created_by_id"))
            markdown = render_merged_plan_markdown(merged)
            if not markdown.strip():
                return
            await ProjectDocService().append_research_note(
                project_id=project_id,
                content=markdown,
                contributor=contributor,
                initiated_by_user_id=str(row.get("created_by_id") or "") or None,
            )
            logger.info(
                "plan_bound_to_project",
                session_id=str(session.id),
                project_id=str(project_id),
                component="process_runtime.architect_merge",
                category="caller",
            )
        except Exception:  # noqa: BLE001 — 绑定 best-effort，绝不反噬融合主链
            logger.warning(
                "plan_bind_project_failed",
                session_id=str(getattr(session, "id", "") or ""),
                component="process_runtime.architect_merge",
                category="caller",
            )

    @staticmethod
    async def _aget_user(user_id: Any) -> Any:
        if not user_id:
            return None
        from django.contrib.auth import get_user_model

        return await get_user_model().objects.filter(id=user_id).afirst()

    async def _handle_fail(
        self, session: ConvergenceSession, report: dict, attempt: int, has_stale: bool
    ) -> dict:
        """失败分支：ArchitectMerge(failed, report) + 不落 artifact；定 back_target。"""
        await self._record_merge(session, ArchitectMergeStatus.FAILED, None, report, attempt)
        reasons = [e.get("check") for e in report.get("errors", []) if isinstance(e, dict)]
        await self._emit(session, EVENT_PLAN_VALIDATION_FAILED, {"reasons": reasons})
        back_target = "research" if has_stale else "clarify"
        if back_target == "clarify" and attempt < self.MAX_MERGE_RETRIES:
            await self._create_reclarify(session, report)
        return {
            "validation_status": "failed",
            "report": report,
            "back_target": back_target,
            "attempt": attempt,
        }

    async def _create_reclarify(self, session: ConvergenceSession, report: dict) -> None:
        """建「描述 merge 校验失败」的 pending 澄清轮（INV-6 经 create_round）+ emit asked。"""
        reasons = [
            str(e.get("check"))
            for e in report.get("errors", [])
            if isinstance(e, dict) and e.get("check")
        ]
        reason_text = "、".join(reasons) if reasons else "方案校验未通过"
        question = (
            f"自动融合的跨仓方案未通过校验（{reason_text}）。"
            "请补充澄清以便重新融合（如跨仓契约、依赖顺序或受影响的仓库）。"
        )
        try:
            clar = await self.clarification_service.create_round(
                session,
                [{"question": question, "type": "single", "options": [], "recommended": []}],
            )
            if clar is None:
                return
            await self._emit(
                session,
                EVENT_CLARIFICATION_ASKED,
                {"clarification_id": str(clar.id), "question": question},
            )
        except Exception:  # noqa: BLE001 — 回退澄清 best-effort
            logger.warning("merge_reclarify_create_failed", session_id=str(session.id))

    async def _collect_valid_partials(self, session: ConvergenceSession) -> list[dict]:
        """async 取 valid PartialPlan 的 content（join 过滤 + .values，禁裸 lazy-FK）。"""
        from delivery.models import PartialPlan

        partials: list[dict] = []
        async for row in PartialPlan.objects.filter(
            research_task__session_id=session.id, valid=True
        ).values("content"):
            content = row.get("content")
            if isinstance(content, dict):
                partials.append(content)
        return partials

    async def _has_stale_or_missing(
        self, session: ConvergenceSession, partials: list[dict]
    ) -> bool:
        """探测是否有 stale 调研任务 / 无 valid partial（定 back_target=research）。"""
        from delivery.models import RepoResearchTask, RepoResearchTaskStatus

        if not partials:
            return True
        return await RepoResearchTask.objects.filter(
            session_id=session.id, status=RepoResearchTaskStatus.STALE
        ).aexists()

    @sync_to_async
    def _record_merge(
        self,
        session: ConvergenceSession,
        status: str,
        merged_artifact_version: Any,
        report: dict,
        attempt: int,
    ) -> ArchitectMerge:
        """ArchitectMerge 落库（INV-6 融合 service 唯一写入入口）。"""
        return ArchitectMerge.objects.create(
            session=session,
            validation_status=status,
            merged_artifact_version=merged_artifact_version,
            validation_report=report,
            attempt=attempt,
        )

    async def _emit(self, session: ConvergenceSession, event: str, payload: dict) -> None:
        """§15 事件 best-effort 发射（经 session_service 钩子，绝不阻断融合）。"""
        try:
            await self.session_service._emit_event(event, session, payload)
        except Exception:  # noqa: BLE001 — 事件 best-effort
            logger.warning("merge_event_emit_failed", event=event, session_id=str(session.id))


def _content_to_text(content: Any) -> str:
    """把 LLM response.content（str / list[block]）归一化为文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return str(content)


def _parse_merged_json(text: str) -> dict | None:
    """健壮解析 §7 MergedPlan JSON：取首 { 到末 }，不 eval。"""
    candidate = text.strip()
    if not candidate.startswith("{"):
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            return None
        candidate = candidate[start : end + 1]
    try:
        obj = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None
