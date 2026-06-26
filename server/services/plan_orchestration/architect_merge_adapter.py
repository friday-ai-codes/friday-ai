"""ArchitectMergeAdapter —— reduce 段真实融合接线（Phase 40-02，MERGE-01/02/03）。

替换骨架 ``SkeletonMerge``，实现「架构师融合」：收齐 session 的 valid ``PartialPlan``，
调**可注入的 LLM 合成器**产结构化 §7 ``MergedPlan``，跑 ``PlanValidator``（40-01）；

- **通过** → 经 ``TechnicalPlanService.create_from(origin="orchestration")`` 落 canonical
  ``PlanVersion`` + 置 ``PlanSession.current_plan_version`` + ``ArchitectMerge(passed)``；
  ``_handle_pass`` 末尾在 ``EVENT_PLAN_MERGE_COMPLETED`` emit 之后 **best-effort** 调
  ``spec_generation_hook``（D-49-5，默认 ``agenerate_specs_for_plan``，可注入 stub）逐
  SDD 仓产 spec draft——整段 try/except 吞为 warning ``sdd_spec_generation_failed``，
  **绝不阻断融合返回**（fail-soft，merge 始终返回 passed）；
- **失败 / 合成异常** → ``ArchitectMerge(failed, report)`` + **不落 canonical**；返回带
  ``back_target`` 的失败结果（engine 据此 §14 回退）。

架构师 = **server 端可注入 LLM 合成**（reduce 单点收敛），区别于 Phase 39 容器（map 隔离）。
守 INV-6：canonical 经 ``TechnicalPlanService``、``ArchitectMerge`` 经**本 adapter 唯一写入**
（Task 3 grep 守护断言）；INV-2：``work_item`` 可空（chat）。

**async ORM 防裸 lazy-FK（规避 Phase 38 CR-01 bug 类）**：async 上下文一律用
``*_id`` 标量 / ``.values()`` / ``afirst`` / ``acount`` / ``aexists``，**绝不**裸访问
``partial.research_task.xxx`` 等同步 lazy-FK。
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

import structlog
from asgiref.sync import sync_to_async

from delivery.models import (
    ArchitectMerge,
    ArchitectMergeStatus,
    PlanSession,
)
from delivery.services import PlanSessionService, TechnicalPlanService
from delivery.services.event_taxonomy import (
    EVENT_CLARIFICATION_ASKED,
    EVENT_PLAN_MERGE_COMPLETED,
    EVENT_PLAN_MERGE_STARTED,
    EVENT_PLAN_VALIDATION_FAILED,
)
from services.plan_orchestration.merged_plan import validate_merged_plan
from services.plan_orchestration.plan_validator import validate_plan

logger = structlog.get_logger(__name__)

__all__ = [
    "MergedPlanSynthesizer",
    "LLMMergedPlanSynthesizer",
    "ArchitectMergeAdapter",
]


@runtime_checkable
class MergedPlanSynthesizer(Protocol):
    """架构师 LLM 合成器协议（可注入）：partials → §7 MergedPlan content dict。"""

    async def synthesize(self, session: PlanSession, partials: list[dict]) -> dict: ...


class LLMMergedPlanSynthesizer:
    """默认 LLM 合成器：provider_config 解析 + chat model + 健壮 JSON 解析。

    **真实 LLM 路径本 phase 仅构造 + 单测 mock 覆盖，E2E 真容器/真模型 deferred**
    （对齐 39-04 真实容器 E2E deferred）。合成/解析失败 → 抛异常（由 adapter 捕获降级）。
    """

    async def synthesize(self, session: PlanSession, partials: list[dict]) -> dict:
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
        # Phase 89：架构师融合产 overall 整体方案 + 跨仓上下文，call_source 细分为 plan_deepen
        # （既有 plan_merge 语义并入方案深化维度）。
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
    def _build_prompt(session: PlanSession, partials: list[dict]) -> str:
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
            "并补充 Phase 89 整体方案字段：\n"
            "- overall_plan：overall 整体方案叙述（跨仓如何协同实现需求，文本）\n"
            "- cross_repo_context：跨仓上下文（聚合各仓七要素 + 跨仓依赖/冲突提要，文本）\n"
        )


class ArchitectMergeAdapter:
    """架构师融合 stage 依赖真实实现（满足 MergeProtocol，MERGE-01/02/03）。"""

    # 限次回退上限（CONTEXT 决策：默认 1 次重试，超限落 failed 终态）。本 adapter 仅产
    # attempt 序号；engine 据 attempt + 本上限判限次（见 engine._merge）。
    MAX_MERGE_RETRIES = 1

    def __init__(
        self,
        *,
        synthesizer: MergedPlanSynthesizer | None = None,
        session_service: PlanSessionService | None = None,
        plan_service: TechnicalPlanService | None = None,
        clarification_service: Any = None,
        spec_generation_hook: Any = None,
    ) -> None:
        self.synthesizer = synthesizer or LLMMergedPlanSynthesizer()
        self.session_service = session_service or PlanSessionService()
        self.plan_service = plan_service or TechnicalPlanService()
        # WR-02：merge 校验失败回退 clarifying 时经此建「描述校验失败」的 Clarification
        # （INV-6 单一写入入口）。延迟默认构造避免 import 环（同 delivery app）。
        if clarification_service is None:
            from delivery.services import ClarificationService

            clarification_service = ClarificationService()
        self.clarification_service = clarification_service
        # D-49-5：融合通过后 best-effort 产 SDD spec 的挂接 hook（默认真实实现，可注入 stub）。
        # 延迟默认绑定避免 import 环（plan_orchestration.__init__ 加载期 re-export 本模块）。
        if spec_generation_hook is None:
            from services.plan_orchestration.spec_generation import agenerate_specs_for_plan

            spec_generation_hook = agenerate_specs_for_plan
        self.spec_generation_hook = spec_generation_hook

    async def merge(self, session: PlanSession) -> dict:
        """融合一次：pass → 落 canonical + ArchitectMerge(passed)；fail → ArchitectMerge(failed)。"""
        # 1. 收齐 valid PartialPlan（async ORM，禁裸 lazy-FK：只用 session_id 过滤 + .values 取 JSON）
        partials = await self._collect_valid_partials(session)
        has_stale = await self._has_stale_or_missing(session, partials)
        # 2. 本次 attempt 序号 = 已有融合次数
        attempt = await ArchitectMerge.objects.filter(session_id=session.id).acount()

        # 3. emit plan.merge.started（best-effort，不阻断）
        repo_ids = [str(p.get("repository_id", "")) for p in partials]
        await self._emit(session, EVENT_PLAN_MERGE_STARTED, {"partials": repo_ids})

        # 4. 合成（异常 → 降级失败分支）
        try:
            merged = await self.synthesizer.synthesize(session, partials)
        except Exception as exc:  # noqa: BLE001 — LLM 合成失败 graceful 降级，不崩编排
            logger.warning(
                "architect_synthesis_failed",
                session_id=str(session.id),
                error=str(exc),
            )
            report = {"reason": "synthesis_failed", "error": str(exc)}
            await self._record_merge(
                session, ArchitectMergeStatus.FAILED, None, report, attempt
            )
            await self._emit(
                session, EVENT_PLAN_VALIDATION_FAILED, {"reasons": ["synthesis_failed"]}
            )
            return {
                "validation_status": "failed",
                "report": report,
                "back_target": "researching",
                "attempt": attempt,
            }

        # 5. schema 闸口（§7，CR-01）—— 先过 validate_merged_plan，保证 schema 非法产物
        #    （如 execution_plan 项缺 repository_id）走与 PlanValidator 失败相同的优雅降级分支
        #    （ArchitectMerge(failed) + plan.validation.failed + §14 回退），而非在 _handle_pass
        #    的 create_from 内二次抛 PlanContentInvalid 冒泡到 engine 崩成 terminal failed。
        schema_ok, schema_err = validate_merged_plan(merged)
        if not schema_ok:
            report = {
                "valid": False,
                "errors": [
                    {"check": "schema", "message": schema_err or "MergedPlan schema 非法"}
                ],
            }
            return await self._handle_fail(session, report, attempt, has_stale)

        # 6. PlanValidator（40-01，跨仓语义）
        report = validate_plan(merged)
        if report.get("valid"):
            return await self._handle_pass(session, merged, report, attempt, has_stale)
        return await self._handle_fail(session, report, attempt, has_stale)

    async def _handle_pass(
        self,
        session: PlanSession,
        merged: dict,
        report: dict,
        attempt: int,
        has_stale: bool,
    ) -> dict:
        """通过分支：落 canonical（INV-6）+ ArchitectMerge(passed) + 置 current_plan_version。

        防御性（CR-01）：``create_from`` 内 ``validate_technical_plan`` 若因 schema 漂移
        二次失败抛 ``PlanContentInvalid``（理论上已被 §7 schema 闸口拦截），转成验证失败
        （failed report + §14 回退），绝不冒泡到 engine 通用 except 崩成 terminal failed。
        """
        from delivery.models import WorkItem
        from delivery.services.technical_plan_service import PlanContentInvalid

        # INV-2：work_item 可空（by id，不裸 lazy-FK）
        work_item = await WorkItem.objects.filter(id=session.work_item_id).afirst()
        try:
            plan = await self.plan_service.create_from(
                "orchestration", {"content": merged}, work_item=work_item
            )
        except PlanContentInvalid as exc:
            logger.warning(
                "merge_canonical_schema_invalid",
                session_id=str(session.id),
                error=str(exc),
            )
            report = {
                "valid": False,
                "errors": [{"check": "schema", "message": str(exc)}],
            }
            return await self._handle_fail(session, report, attempt, has_stale)

        version_id = plan.current_version_id  # async 安全标量
        # IN-02：先落 ArchitectMerge(passed) 记账（引用 version_id），再置 session 指针——
        # 后续步骤（指针/事件）失败也不致留「canonical 孤儿 + 无 ArchitectMerge 记录」。
        await self._record_merge(
            session, ArchitectMergeStatus.PASSED, version_id, report, attempt
        )
        await self.session_service.set_current_plan_version(session, version_id)
        await self._emit(
            session, EVENT_PLAN_MERGE_COMPLETED, {"plan_version_id": str(version_id)}
        )
        # D-49-5：融合通过后 best-effort 产 SDD spec（仅对 SDD 仓，逐仓隔离在 hook 内）。
        # 外层 try/except 是双保险——即便 hook 整体抛错（import/解析异常）也绝不冒泡阻断融合
        # 返回路径，吞为 warning sdd_spec_generation_failed（merge 始终返回 passed）。
        try:
            await self.spec_generation_hook(version_id)
        except Exception:  # noqa: BLE001 — spec 生成 best-effort，绝不阻断融合返回
            logger.warning(
                "sdd_spec_generation_failed",
                session_id=str(session.id),
                plan_version_id=str(version_id),
            )
        return {
            "validation_status": "passed",
            "plan_version_id": str(version_id),
            "attempt": attempt,
        }

    async def _handle_fail(
        self, session: PlanSession, report: dict, attempt: int, has_stale: bool
    ) -> dict:
        """失败分支：ArchitectMerge(failed, report) + 不落 canonical；定 back_target。"""
        await self._record_merge(
            session, ArchitectMergeStatus.FAILED, None, report, attempt
        )
        reasons = [e.get("check") for e in report.get("errors", []) if isinstance(e, dict)]
        await self._emit(session, EVENT_PLAN_VALIDATION_FAILED, {"reasons": reasons})
        # back_target：partial stale/缺 → researching；否则默认 clarifying
        back_target = "researching" if has_stale else "clarifying"
        # WR-02：回退 clarifying 时主动建一条「描述校验失败」的 pending Clarification，使回退
        # 真正落到一次 HITL 澄清——否则默认 policy 下 CR-01 单轮 guard 会因无 pending、无已答而
        # 重跑静态 policy（routing 有 high/medium、无 ambiguous → 不需澄清）直通 researching，
        # 同批 partial 立即再次 merging 失败、空转一圈后 fail，§14「按报告回退重跑」沦为空操作。
        # 仅在「仍可重试」（attempt < MAX）时建：attempt 已达上限时 engine 直接落 failed 终态
        # （见 engine._merge），不应留孤儿 pending。有界性由 merge attempt 计数保证（重 merge
        # 仍非法 → attempt>=MAX → failed 终态），不会无限循环。
        if back_target == "clarifying" and attempt < self.MAX_MERGE_RETRIES:
            await self._create_reclarify(session, report)
        return {
            "validation_status": "failed",
            "report": report,
            "back_target": back_target,
            "attempt": attempt,
        }

    async def _create_reclarify(self, session: PlanSession, report: dict) -> None:
        """WR-02：建「描述 merge 校验失败」的 pending Clarification（INV-6 经 service）+ emit asked。

        best-effort：建/emit 失败仅 warning，绝不阻断 merge 返回（回退仍由 engine 据 attempt
        有界）。无 affected_partials（不主动重跑 partial——有界：重 merge 用同批 partial，仍
        非法则在 attempt>=MAX 落 failed 终态；避免对正确 partial 误失效）。
        """
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
            clar = await self.clarification_service.create_clarification(
                session, question, []
            )
            await self._emit(
                session,
                EVENT_CLARIFICATION_ASKED,
                {"clarification_id": str(clar.id), "question": question},
            )
        except Exception:  # noqa: BLE001 — 回退澄清 best-effort，绝不阻断 merge 返回
            logger.warning("merge_reclarify_create_failed", session_id=str(session.id))

    async def _collect_valid_partials(self, session: PlanSession) -> list[dict]:
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
        self, session: PlanSession, partials: list[dict]
    ) -> bool:
        """探测是否有 stale 调研任务 / 无 valid partial（定 back_target=researching）。"""
        from delivery.models import RepoResearchTask, RepoResearchTaskStatus

        if not partials:
            return True
        return await RepoResearchTask.objects.filter(
            session_id=session.id, status=RepoResearchTaskStatus.STALE
        ).aexists()

    @sync_to_async
    def _record_merge(
        self,
        session: PlanSession,
        status: str,
        merged_plan_version: Any,
        report: dict,
        attempt: int,
    ) -> ArchitectMerge:
        """ArchitectMerge 落库（INV-6 融合 service 唯一写入入口；Task 3 grep 守护断言）。"""
        return ArchitectMerge.objects.create(
            session=session,
            validation_status=status,
            merged_plan_version=merged_plan_version,
            validation_report=report,
            attempt=attempt,
        )

    async def _emit(self, session: PlanSession, event: str, payload: dict) -> None:
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
    """健壮解析 §7 MergedPlan JSON：取首 { 到末 }，不 eval（半可信产物防御）。"""
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
