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
from asgiref.sync import sync_to_async

logger = structlog.get_logger(__name__)

__all__ = ["PlanDeepenService"]

_COMPONENT = "plan_deepen"
# detect_revision 观测文本字符预算（防超大观测塞爆 LLM 上下文，T-89-02-DOS）。
_OBSERVED_CHAR_BUDGET = 4000
# 补充修订 delta 折进 summary 的分隔标记（content 变更即翻版本，相等则 service 幂等不翻）。
_SUPPLEMENT_MARKER = "\n\n【补充修订】"

_REVISION_SYSTEM_PROMPT = (
    "你是资深软件架构师，负责在编码执行过程中根据『调研问题发现』判断技术方案是否需要"
    "增加 / 删除 / 调整涉及的代码仓库，并给出方案修订要点。只输出 JSON，不要任何解释。"
)


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

    # ------------------------------------------------------------------
    # PLAN-02 方案修订回路：detect_revision + apply_supplement_revision
    # ------------------------------------------------------------------

    async def detect_revision(
        self,
        *,
        observed_change_text: str,
        session_or_plan: Any = None,
        initiated_by_user_id: str = "system",
    ) -> dict[str, Any]:
        """『调研问题发现』检测：执行中观测 → 判定要改/增/删哪些仓 + 方案修订要点。

        经 ``use_call_source(CallSource.PLAN_REVISION)`` LLM（89-01 已注册）判定结构化结果
        ``{add_repos[], remove_repos[], change_repos[], plan_delta_summary}``；``observed_
        change_text``（来自编码容器问答 / 人工）入 prompt 前经 ``redact_secrets_in_text``
        脱敏 + 截断；LLM 用量经 ``arecord_llm_usage`` 留痕。整段 best-effort——解析/调用/
        provider 任一失败返回空结构（不改/增/删），绝不反噬主链。
        """
        from common.logging import redact_secrets_in_text

        started = perf_counter()
        log = logger.bind(
            component=_COMPONENT,
            category="caller",
            initiated_by_user_id=initiated_by_user_id,
        )
        empty: dict[str, Any] = {
            "add_repos": [],
            "remove_repos": [],
            "change_repos": [],
            "plan_delta_summary": "",
        }
        safe_text = redact_secrets_in_text(str(observed_change_text or ""))[:_OBSERVED_CHAR_BUDGET]
        if not safe_text.strip():
            return empty

        try:
            detection = await self._ainvoke_revision_llm(safe_text, initiated_by_user_id)
        except Exception as exc:  # noqa: BLE001 — 检测 best-effort，失败回空结构不反噬
            log.warning(
                "plan_revision_detect_failed",
                error_type=type(exc).__name__,
                reason=redact_secrets_in_text(str(exc)),
                duration_ms=round((perf_counter() - started) * 1000, 2),
            )
            return empty

        log.info(
            "plan_revision_detected",
            add_count=len(detection.get("add_repos") or []),
            remove_count=len(detection.get("remove_repos") or []),
            change_count=len(detection.get("change_repos") or []),
            has_delta=bool(str(detection.get("plan_delta_summary") or "").strip()),
            duration_ms=round((perf_counter() - started) * 1000, 2),
        )
        return detection

    async def _ainvoke_revision_llm(
        self, observed_text: str, initiated_by_user_id: str
    ) -> dict[str, Any]:
        """调 plan_revision LLM 判定修订结构（镜像 ``LLMMergedPlanSynthesizer`` 取模/调用范式）。"""
        from langchain_core.messages import HumanMessage, SystemMessage

        from agents.call_source import CallSource, use_call_source
        from agents.llm_factory import build_chat_model
        from interactions.ledger import arecord_llm_usage
        from services.provider_config import ProviderConfigService

        resolved = await ProviderConfigService.aresolve()
        model_name = (getattr(resolved, "extra", None) or {}).get("default_model", "")
        if not model_name:
            raise RuntimeError("no_default_model")
        model = build_chat_model(resolved, model_name, streaming=False)
        system = SystemMessage(content=_REVISION_SYSTEM_PROMPT)
        human = HumanMessage(content=self._build_revision_prompt(observed_text))

        llm_started = perf_counter()
        with use_call_source(CallSource.PLAN_REVISION):
            response = await model.ainvoke([system, human])
        duration_ms = int((perf_counter() - llm_started) * 1000)

        # LLM 用量留痕（best-effort，观测失败绝不反噬检测）。
        try:
            await arecord_llm_usage(
                call_source=CallSource.PLAN_REVISION.value,
                provider=str(getattr(resolved, "provider_type", "") or "unknown"),
                model=str(model_name),
                duration_ms=duration_ms,
                user_id=str(initiated_by_user_id or "system"),
                source=_COMPONENT,
            )
        except Exception:  # noqa: BLE001 — 留痕 best-effort
            logger.debug(
                "plan_revision_usage_record_failed",
                component=_COMPONENT,
                category="sampling",
            )

        parsed = _parse_revision_json(_content_to_text(response.content))
        return self._normalize_revision(parsed)

    @staticmethod
    def _build_revision_prompt(observed_text: str) -> str:
        return (
            "执行过程中的『调研问题发现』（已脱敏）：\n"
            f"{observed_text}\n\n"
            "请判断技术方案是否需要调整涉及的代码仓库，只输出如下 JSON：\n"
            "{\n"
            '  "add_repos": [需新增关联的 repository_id 字符串...],\n'
            '  "remove_repos": [需移除关联的 repository_id 字符串...],\n'
            '  "change_repos": [需重新深度校验的 repository_id 字符串...],\n'
            '  "plan_delta_summary": "方案修订要点（中文，简述本次补充修订改了什么）"\n'
            "}\n"
            "若无需任何仓库变更，对应数组留空、plan_delta_summary 给出方案补充说明即可。"
        )

    @staticmethod
    def _normalize_revision(parsed: dict | None) -> dict[str, Any]:
        """归一化 LLM 修订产物为受控结构（仓库 id 去空 str 化，摘要截断）。"""
        raw = parsed if isinstance(parsed, dict) else {}

        def _ids(key: str) -> list[str]:
            val = raw.get(key)
            if not isinstance(val, list):
                return []
            return [str(x).strip() for x in val if str(x).strip()]

        return {
            "add_repos": _ids("add_repos"),
            "remove_repos": _ids("remove_repos"),
            "change_repos": _ids("change_repos"),
            "plan_delta_summary": str(raw.get("plan_delta_summary") or "").strip()[:4000],
        }

    async def apply_supplement_revision(
        self,
        *,
        plan: Any,
        revision: dict[str, Any],
        project: Any = None,
        actor: Any = None,
        initiated_by_user_id: str = "system",
    ) -> Any:
        """补充修订：① 经 ``TechnicalPlanService`` 加 ``PlanVersion(supersedes)`` ② 同步改仓库关联。

        ① 取当前 canonical content，把 ``plan_delta_summary`` 折进 ``summary``（content 变更即
        翻版本；delta 为空 → content 不变 → ``add_version`` content_hash 相等不翻版本，幂等，
        v0.3/v0.6 铁律由 service 处理，本回路复用既有版本链**绝不**新建 ``PlanRevision`` 模型）。
        ② 按 add/remove/change 经 88 ``RepoAssociationService`` 写收口同步仓库关联（INV-6）。

        Returns: 新建（或幂等复用的）``PlanVersion``。association 同步 best-effort 不反噬版本。
        """
        from delivery.services import TechnicalPlanService

        started = perf_counter()
        revision = revision or {}
        delta = str(revision.get("plan_delta_summary") or "").strip()
        log = logger.bind(
            component=_COMPONENT,
            category="caller",
            initiated_by_user_id=initiated_by_user_id,
            plan_id=str(getattr(plan, "id", "") or ""),
        )
        log.info(
            "plan_revision_proposed",
            add_count=len(revision.get("add_repos") or []),
            remove_count=len(revision.get("remove_repos") or []),
            change_count=len(revision.get("change_repos") or []),
            has_delta=bool(delta),
        )

        # ① 补充修订版本（PlanVersion.supersedes；写经 service，INV-6）。
        content = await self._aget_plan_content(plan)
        new_content = self._merge_delta_into_content(content, delta)
        version = await TechnicalPlanService().add_version(plan, new_content)

        # ② 同步改/增/删仓库关联（经 88 service 写收口，best-effort 不反噬版本）。
        await self._sync_repo_associations(
            project=project,
            revision=revision,
            initiated_by_user_id=initiated_by_user_id,
        )

        log.info(
            "plan_revision_applied",
            version=getattr(version, "version", None),
            version_id=str(getattr(version, "id", "") or ""),
            duration_ms=round((perf_counter() - started) * 1000, 2),
        )
        return version

    @staticmethod
    async def _aget_plan_content(plan: Any) -> dict:
        """取 canonical ``plan.current_version.content``（async 禁裸 lazy-FK，by id）。"""
        from delivery.models import PlanVersion

        version_id = getattr(plan, "current_version_id", None)
        if not version_id:
            return {}
        pv = await PlanVersion.objects.filter(id=version_id).afirst()
        content = getattr(pv, "content", None) if pv is not None else None
        return dict(content) if isinstance(content, dict) else {}

    @staticmethod
    def _merge_delta_into_content(content: dict, delta: str) -> dict:
        """把修订要点折进 ``summary``（纯函数）：delta 为空原样返回（content_hash 相等幂等）。"""
        base = dict(content) if isinstance(content, dict) else {}
        if not delta:
            return base
        summary = str(base.get("summary") or "")
        base["summary"] = f"{summary}{_SUPPLEMENT_MARKER}{delta}"
        return base

    async def _sync_repo_associations(
        self, *, project: Any, revision: dict[str, Any], initiated_by_user_id: str
    ) -> None:
        """按 add/remove/change 经 88 ``RepoAssociationService`` 同步仓库关联（INV-6，best-effort）。

        - ``add_repos`` → ``confirm_repos``（确认/关联新仓）；
        - ``remove_repos`` → ``reopen_candidates``（回退 proposed，移出已确认/已验集）；
        - ``change_repos`` → ``dispatch_verify``（重新逐仓深度校验）。

        无 project → 跳过（仅记日志）；任一同步失败吞为 warning，绝不反噬补充修订版本。
        """
        from common.logging import redact_secrets_in_text

        if project is None:
            logger.info(
                "plan_revision_assoc_sync_skipped",
                reason="no_project",
                component=_COMPONENT,
                category="caller",
            )
            return

        from initiatives.services.repo_association_service import RepoAssociationService

        service = RepoAssociationService()
        add_repos = [str(r) for r in (revision.get("add_repos") or []) if r]
        remove_repos = [str(r) for r in (revision.get("remove_repos") or []) if r]
        change_repos = [str(r) for r in (revision.get("change_repos") or []) if r]

        try:
            if add_repos:
                await service.confirm_repos(
                    project=project,
                    repo_ids=add_repos,
                    initiated_by_user_id=initiated_by_user_id,
                )
            if remove_repos:
                for assoc in await self._aload_associations(project, remove_repos):
                    await service.reopen_candidates(
                        assoc, initiated_by_user_id=initiated_by_user_id
                    )
            if change_repos:
                assocs = await self._aload_associations(project, change_repos)
                if assocs:
                    await service.dispatch_verify(
                        project=project,
                        confirmed=assocs,
                        initiated_by_user_id=initiated_by_user_id,
                    )
            logger.info(
                "plan_revision_assoc_synced",
                add_count=len(add_repos),
                remove_count=len(remove_repos),
                change_count=len(change_repos),
                component=_COMPONENT,
                category="caller",
            )
        except Exception as exc:  # noqa: BLE001 — 关联同步 best-effort，绝不反噬补充修订版本
            logger.warning(
                "plan_revision_assoc_sync_failed",
                error_type=type(exc).__name__,
                reason=redact_secrets_in_text(str(exc)),
                component=_COMPONENT,
                category="caller",
            )

    @staticmethod
    @sync_to_async
    def _aload_associations(project: Any, repo_ids: list[str]) -> list[Any]:
        """读确认批次的 ``RepoAssociation``（含仓名；只读不写，INV-6 不涉及）。"""
        from initiatives.models import RepoAssociation

        ids = [str(r) for r in (repo_ids or []) if r]
        if not ids:
            return []
        return list(
            RepoAssociation.objects.filter(
                project=project, repository_id__in=ids
            ).select_related("repository")
        )

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


def _content_to_text(content: Any) -> str:
    """把 LLM response.content（str / list[block]）归一化为文本（镜像 architect adapter）。"""
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


def _parse_revision_json(text: str) -> dict | None:
    """健壮解析修订 JSON：取首 ``{`` 到末 ``}``，不 eval（半可信产物防御）。"""
    import json

    candidate = (text or "").strip()
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
