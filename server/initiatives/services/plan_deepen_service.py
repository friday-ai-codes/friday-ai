"""PlanDeepenService —— Phase 89 PLAN-01 技术方案深化编排收口（INV-6）。

把 Phase 88 确认仓（``RepoAssociationService.get_verified_associations``）喂入 **v0.7
同一编排引擎**（``build_orchestration_engine`` + ``adrive_plan_session_to_pause_or_terminal``，
**绝不新建第二个 engine 工厂**），深化出 per-repo 七要素 + overall 整体方案 + 跨仓上下文，
落 canonical ``TechnicalPlan``/``PlanVersion``（复用不新建），终态再把方案文本**镜像进项目
RESEARCH**（经 ``ProjectDocService.append_research_note`` → 触发 Phase 83 双向同步飞书，
never-clobber）。

设计要点（CONTEXT/RESEARCH 锁定）：

- **复用 v0.7，不造两套**：方案产出全经既有编排引擎；本 service 只做「消费 88 → 起会话 →
  续驱 → 终态镜像」的薄编排收口，不旁路写 ``TechnicalPlan``/``PlanVersion``/``ProjectDoc``。
- **观测强制**：结构化事件 ``plan_deepen_started/_completed/_failed/_mirror_failed``
  （``category="caller"``，``component="plan_deepen"``，带 ``duration_ms``）；归因
  ``initiated_by_user_id``；镜像前正文经 ``redact_secrets_in_text`` 脱敏；观测/镜像
  best-effort，绝不反噬主链。
- **async ORM**：一律经既有 service 异步方法 / ``afirst``，无裸 lazy-FK。
"""

from __future__ import annotations

from time import perf_counter
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

__all__ = ["PlanDeepenService"]

_COMPONENT = "plan_deepen"


class PlanDeepenService:
    """技术方案深化编排收口（消费 88 verified → v0.7 引擎深化 → RESEARCH 镜像，INV-6）。"""

    async def deepen(
        self,
        *,
        project: Any,
        work_item: Any = None,
        requirement_text: str,
        node_execution_id: str = "",
        initiated_by_user_id: str = "system",
    ) -> Any:
        """消费 88 确认仓 → v0.7 引擎深化 → 终态镜像 RESEARCH，返回续驱后的 ``PlanSession``。

        ① ``get_verified_associations(project, work_item)`` → ``include_repos``（仅 verified，
        无 verified 仍可走自然语言需求，``include_repos=[]`` 引擎自路由，不抛）；
        ② ``start_orchestration("workflow", requirement_text, work_item, include_repos)`` 建会话；
        ③ ``build_orchestration_engine(node_execution_id=...)``（v0.7 同一工厂）；
        ④ ``adrive_plan_session_to_pause_or_terminal`` 续驱到「重挂起短路或终态」；
        ⑤ 终态 ``DONE`` → ``_mirror_to_research``（best-effort，失败不反噬）。
        """
        from initiatives.services.repo_association_service import RepoAssociationService
        from services.plan_orchestration import (
            adrive_plan_session_to_pause_or_terminal,
            build_orchestration_engine,
            start_orchestration,
        )

        started = perf_counter()
        log = logger.bind(
            component=_COMPONENT,
            category="caller",
            initiated_by_user_id=initiated_by_user_id,
            project_id=str(getattr(project, "id", "") or ""),
        )

        # ① 消费 Phase 88 verified 关联（只读契约），透传 include_repos。
        verified = await RepoAssociationService().get_verified_associations(
            project=project, work_item=work_item
        )
        include_repos = [str(v["repository_id"]) for v in verified if v.get("repository_id")]
        if not include_repos:
            log.info("plan_deepen_no_verified_repos")

        log.info("plan_deepen_started", verified_count=len(include_repos))

        try:
            # ②③④ v0.7 同一引擎工厂 + 入口无关续驱（绝不新建第二个 engine）。
            session = await start_orchestration(
                "workflow",
                requirement_text,
                work_item=work_item,
                include_repos=include_repos,
            )
            engine = build_orchestration_engine(node_execution_id=node_execution_id)
            session = await adrive_plan_session_to_pause_or_terminal(engine, session)
        except Exception as exc:  # noqa: BLE001 — 深化失败结构化记账，向上抛由入口节点映射 error
            log.error(
                "plan_deepen_failed",
                error_type=type(exc).__name__,
                duration_ms=round((perf_counter() - started) * 1000, 2),
            )
            raise

        # ⑤ 终态 DONE → 镜像方案进 RESEARCH（best-effort）。
        from delivery.models import PlanSessionStatus

        if session.status == PlanSessionStatus.DONE:
            await self._mirror_to_research(project, session, initiated_by_user_id)

        log.info(
            "plan_deepen_completed",
            session_id=str(session.id),
            status=session.status,
            duration_ms=round((perf_counter() - started) * 1000, 2),
        )
        return session

    async def _mirror_to_research(
        self, project: Any, session: Any, initiated_by_user_id: str
    ) -> None:
        """取终态 canonical 方案（overall + per-repo 七要素）渲染 markdown → 镜像进 RESEARCH。

        经 ``ProjectDocService.append_research_note``（INV-6 写收口 → 触发 Phase 83 block 级
        增量双向镜像飞书，never-clobber）。整段 best-effort：取版本/渲染/写入任一失败仅记
        ``plan_deepen_mirror_failed``，绝不反噬深化主链。
        """
        try:
            from common.logging import redact_secrets_in_text
            from initiatives.services.project_doc_service import ProjectDocService

            overall = await self._aget_current_plan_content(session)
            partials = await self._acollect_partials(session)
            markdown = self._render_plan_markdown(overall, partials)
            if not markdown.strip():
                return
            contributor = await self._aresolve_contributor(initiated_by_user_id)
            await ProjectDocService().append_research_note(
                project_id=getattr(project, "id", None),
                content=redact_secrets_in_text(markdown),
                contributor=contributor,
                initiated_by_user_id=initiated_by_user_id,
            )
        except Exception:  # noqa: BLE001 — 镜像 best-effort，绝不反噬深化主链
            logger.warning(
                "plan_deepen_mirror_failed",
                session_id=str(getattr(session, "id", "") or ""),
                component=_COMPONENT,
                category="caller",
            )

    @staticmethod
    async def _aget_current_plan_content(session: Any) -> dict:
        """取终态 canonical ``PlanVersion.content``（overall §7 MergedPlan，含 overall 扩段）。"""
        from delivery.models import PlanVersion

        version_id = getattr(session, "current_plan_version", None)
        if not version_id:
            return {}
        pv = await PlanVersion.objects.filter(id=version_id).afirst()
        content = getattr(pv, "content", None) if pv is not None else None
        return content if isinstance(content, dict) else {}

    @staticmethod
    async def _acollect_partials(session: Any) -> list[dict]:
        """取本会话 valid PartialPlan content（per-repo 七要素，async 禁裸 lazy-FK）。"""
        from delivery.models import PartialPlan

        out: list[dict] = []
        async for row in PartialPlan.objects.filter(
            research_task__session_id=session.id, valid=True
        ).values("content"):
            content = row.get("content")
            if isinstance(content, dict):
                out.append(content)
        return out

    @staticmethod
    async def _aresolve_contributor(initiated_by_user_id: str) -> Any:
        """从 ``initiated_by_user_id`` 解析 contributor User（非数字/system → None）。

        ``append_research_note`` 写恒守项目成员闸：非成员静默跳过（返回 not_member 不抛）。
        """
        if not initiated_by_user_id or initiated_by_user_id == "system":
            return None
        if not str(initiated_by_user_id).isdigit():
            return None
        from django.contrib.auth import get_user_model

        return await get_user_model().objects.filter(id=initiated_by_user_id).afirst()

    @staticmethod
    def _render_plan_markdown(overall: dict, partials: list[dict]) -> str:
        """把 overall §7 方案 + per-repo 七要素渲染为 RESEARCH 镜像 markdown（纯函数）。"""
        lines: list[str] = ["# 技术方案（自动深化）"]

        title = str(overall.get("title") or "").strip()
        summary = str(overall.get("summary") or "").strip()
        if title:
            lines.append(f"\n**{title}**")
        if summary:
            lines.append(f"\n{summary}")

        # overall 整体方案 + 跨仓上下文（merge schema 扩段，缺省静默跳过）。
        overall_plan = overall.get("overall_plan")
        if isinstance(overall_plan, str) and overall_plan.strip():
            lines.append("\n## 整体方案\n")
            lines.append(overall_plan.strip())
        cross = overall.get("cross_repo_context")
        if isinstance(cross, str) and cross.strip():
            lines.append("\n## 跨仓上下文\n")
            lines.append(cross.strip())

        # per-repo 七要素。
        _ELEMENTS = (
            ("responsibilities", "负责事项"),
            ("proposed_changes", "代码预改动"),
            ("impacted_modules", "影响业务模块"),
            ("estimated_tests", "预计 e2e·单测 + 覆盖项"),
            ("risks", "风险"),
            ("unclear_features", "feature list 不清处"),
            ("conflicts_with_existing", "与现功能冲突"),
        )
        if partials:
            lines.append("\n## 各仓方案（七要素）\n")
        for p in partials:
            repo = str(p.get("repository_id") or p.get("repo_name") or "未知仓").strip()
            lines.append(f"\n### 仓库 {repo}")
            rsummary = str(p.get("research_summary") or "").strip()
            if rsummary:
                lines.append(f"\n{rsummary}")
            for key, label in _ELEMENTS:
                val = p.get(key)
                rendered = PlanDeepenService._render_element(val)
                if rendered:
                    lines.append(f"\n- **{label}**：{rendered}")
        return "\n".join(lines).strip()

    @staticmethod
    def _render_element(val: Any) -> str:
        """把七要素单字段（str/list/dict）渲染为单行文本（空值返回 ""）。"""
        if val is None:
            return ""
        if isinstance(val, str):
            return val.strip()
        if isinstance(val, list):
            items = [str(x).strip() for x in val if str(x).strip()]
            return "；".join(items)
        if isinstance(val, dict):
            items = [f"{k}={v}" for k, v in val.items()]
            return "；".join(items)
        return str(val).strip()
