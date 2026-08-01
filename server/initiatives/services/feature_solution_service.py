"""FeatureSolutionService —— feature list → 技术方案的三段式编排门面。

把 feature list 技术方案能力收成三个入口无关的动作，供 MCP 工具 / 对话 agent tool /
未来前端共用同一份逻辑（不造两套）：

- :meth:`start`：取 feature list → 建 ``ConvergenceSession``（``mode="feature_list"``）→
  续驱到**强制确认**挂起 → 返回分类结果 + 待确认题。
- :meth:`confirm`：提交确认答复 → 续驱（进调研 / 融合）→ 返回新状态。
- :meth:`get`：查状态；**并主动续驱一步**。

## 为什么 get 要主动续驱

调研阶段派容器后会话挂 ``waiting_event``。容器回调里的自动续驱（``_schedule_chat_plan_resume``）
以 ``entrypoint == CHAT`` 守门，MCP / tool_invoke 入口不在其列——容器完成后
``amaybe_complete_research`` 只把 stage 推到 ``merge`` 就停了，没有消费者驱动 merge handler，
会话会永久停在 merging。故非 chat 入口必须靠 :meth:`get` 轮询驱动补上这一段。
``adrive_convergence_session_to_pause_or_terminal`` 自带「在途调研 / 未答澄清」短路，
容器没跑完时轮询是安全的空转。

## 权限

有项目上下文时校验调用者可读该项目（Space viewer+ 或项目成员）；纯文本入口无项目归属，
按调用者自身身份编排。查询/确认已有会话时校验会话归属（创建者本人或该项目可读者），
杜绝跨用户拿他人方案。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

__all__ = [
    "FeatureSolutionError",
    "FeatureSolutionState",
    "FeatureSolutionService",
]

_COMPONENT = "feature_solution"

# 状态机对外口径（与 ConvergenceSessionStatus 解耦，调用方只认这四个）
STATUS_AWAITING_CONFIRMATION = "awaiting_confirmation"
STATUS_RESEARCHING = "researching"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


class FeatureSolutionError(Exception):
    """可恢复的编排前置错误（携机器可读 code 供 MCP 映射 HTTP 状态）。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass
class FeatureSolutionState:
    """一次 feature list 方案编排的对外状态快照。"""

    session_id: str = ""
    status: str = ""
    project_id: str = ""
    source: str = ""
    feature_count: int = 0
    truncated: bool = False
    classification: dict[str, Any] = field(default_factory=dict)
    routing: dict[str, Any] = field(default_factory=dict)
    questions: list[dict[str, Any]] = field(default_factory=list)
    clarification_id: str = ""
    plan: dict[str, Any] = field(default_factory=dict)
    markdown: str = ""
    artifact_version_id: str = ""
    error: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "project_id": self.project_id,
            "source": self.source,
            "feature_count": self.feature_count,
            "truncated": self.truncated,
            "classification": self.classification,
            "routing": self.routing,
            "questions": self.questions,
            "clarification_id": self.clarification_id,
            "plan": self.plan,
            "markdown": self.markdown,
            "artifact_version_id": self.artifact_version_id,
            "error": self.error,
        }


class FeatureSolutionService:
    """feature list 技术方案编排门面（入口无关，MCP / 对话 / 前端共用）。"""

    async def start(
        self,
        *,
        project_id: Any = None,
        branch_name: str = "",
        repository_id: Any = None,
        feature_list_text: str = "",
        repository_ids: list[str] | None = None,
        entrypoint: str = "mcp",
        actor: Any = None,
        initiated_by_user_id: Any = "",
        conversation_id: Any = None,
    ) -> FeatureSolutionState:
        """取 feature list → 建会话 → 续驱到强制确认挂起。

        ``conversation_id``（对话入口必传）：会话软引用。前端 plan 澄清卡由
        ``runtime.pending_plan_clarification`` 驱动，而 runtime 是**按 conversation_id 反查
        ConvergenceSession** 的；收答专路由同理。不传则对话里确认卡渲染不出来、也无法作答。
        """
        from initiatives.services.feature_source import (
            FeatureSourceError,
            aresolve_feature_source,
        )

        started = time.perf_counter()
        try:
            resolved = await aresolve_feature_source(
                project_id=project_id,
                branch_name=branch_name,
                repository_id=repository_id,
                feature_list_text=feature_list_text,
            )
        except FeatureSourceError as exc:
            raise FeatureSolutionError(exc.code, exc.detail) from exc

        if resolved.project is not None:
            await self._aassert_project_readable(resolved.project, actor)

        session = await self._acreate_session(
            resolved=resolved,
            repository_ids=repository_ids or [],
            entrypoint=entrypoint,
            actor=actor,
            initiated_by_user_id=initiated_by_user_id,
            conversation_id=conversation_id,
        )
        session = await self._adrive(session)
        state = await self._abuild_state(session, resolved=resolved)

        logger.info(
            "feature_solution_started",
            category="caller",
            component=_COMPONENT,
            session_id=state.session_id,
            source=resolved.source,
            feature_count=len(resolved.segments),
            status=state.status,
            question_count=len(state.questions),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return state

    async def confirm(
        self,
        *,
        session_id: Any,
        answers: list[dict[str, Any]],
        actor: Any = None,
    ) -> FeatureSolutionState:
        """提交确认答复并续驱编排。

        ``answers`` 形如 ``[{question_id, selected, freeform_text}]``。允许 answers 为空
        （表示「全部按推荐执行」）——此时用各题 recommended 自动作答，否则会话会一直挂着。
        """
        from delivery.models import Clarification
        from services.process_runtime import aanswer_round_and_resume

        started = time.perf_counter()
        session = await self._aload_session(session_id, actor)

        clar = (
            await Clarification.objects.filter(session_id=session.id, answered_at__isnull=True)
            .order_by("-created_at")
            .afirst()
        )
        if clar is None:
            # 没有待答轮：可能已确认过（幂等重试）或已在调研中 → 直接续驱返回当前状态。
            session = await self._adrive(session)
            return await self._abuild_state(session)

        resolved_answers = await self._aresolve_answers(clar, answers)
        engine, _adrive = self._build_engine(session)
        driven = await aanswer_round_and_resume(clar, resolved_answers, engine=engine)
        session = driven if driven is not None else await self._areload(session.id)
        state = await self._abuild_state(session)

        logger.info(
            "feature_solution_confirmed",
            category="caller",
            component=_COMPONENT,
            session_id=state.session_id,
            answer_count=len(resolved_answers),
            status=state.status,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return state

    async def get(self, *, session_id: Any, actor: Any = None) -> FeatureSolutionState:
        """查状态并主动续驱一步（非 chat 入口的唯一推进通路，见模块 docstring）。"""
        session = await self._aload_session(session_id, actor)
        session = await self._adrive(session)
        return await self._abuild_state(session)

    # ------------------------------------------------------------------ 内部

    @staticmethod
    def _build_engine(session: Any) -> Any:
        """按 ``session.process_type`` 取 ``(engine, driver)`` 二元组（116-03 分派器）。

        ``force_confirm=True`` 照原样传给分派器：它只在旧链分支透传给
        ``build_orchestration_engine``（注入确定性确认题组装器），蓝图链没有 ``clarify``
        dep ⇒ 分派器丢弃并落一条 ``blueprint_engine_ignored_legacy_flag``。⇒ 旧链行为逐字
        不变；蓝图链的「强制确认关联仓」由它自己的 ``repo_confirmation`` 硬门天然承担。
        """
        from services.process_runtime.entrypoint import build_engine_for_session

        return build_engine_for_session(session, force_confirm=True)

    async def _adrive(self, session: Any) -> Any:
        """续驱到重挂起短路点或终态；异常 fail-soft 返回当前会话（绝不让查询把方案打挂）。"""
        try:
            engine, adrive = self._build_engine(session)
            return await adrive(engine, session)
        except Exception as exc:  # noqa: BLE001 — 续驱失败不阻断查询，下次轮询再试
            logger.warning(
                "feature_solution_drive_failed",
                category="sampling",
                component=_COMPONENT,
                session_id=str(getattr(session, "id", "")),
                error=str(exc),
            )
            return await self._areload(session.id)

    async def _acreate_session(
        self,
        *,
        resolved: Any,
        repository_ids: list[str],
        entrypoint: str,
        actor: Any,
        initiated_by_user_id: Any,
        conversation_id: Any = None,
    ) -> Any:
        from services.process_runtime import start_orchestration

        requirement_text = _build_requirement_text(resolved)
        return await start_orchestration(
            entrypoint,
            requirement_text,
            created_by=actor if getattr(actor, "id", None) is not None else None,
            include_repos=[str(r) for r in repository_ids],
            initiated_by_user_id=str(initiated_by_user_id or ""),
            conversation_id=conversation_id or None,
            mode="feature_list",
            feature_segments=resolved.segments,
            feature_meta={
                "project_id": resolved.project_id,
                "source": resolved.source,
                "module_count": resolved.module_count,
                "truncated": resolved.truncated,
            },
        )

    async def _aload_session(self, session_id: Any, actor: Any) -> Any:
        """按 id 取会话 + 归属校验（fail-closed，杜绝跨用户读他人方案）。"""
        from delivery.models import ConvergenceSession

        session = await ConvergenceSession.objects.filter(id=session_id).afirst()
        if session is None:
            raise FeatureSolutionError("session_not_found", "方案会话不存在")
        if (session.decomposition or {}).get("mode") != "feature_list":
            raise FeatureSolutionError(
                "not_feature_solution_session",
                "该会话不是 feature list 方案会话",
            )
        await self._aassert_session_readable(session, actor)
        return session

    async def _areload(self, session_id: Any) -> Any:
        from delivery.models import ConvergenceSession

        return await ConvergenceSession.objects.aget(id=session_id)

    @staticmethod
    async def _aassert_project_readable(project: Any, actor: Any) -> None:
        """项目可读校验（Space viewer+ 或项目成员）；actor 为空视为不可读（fail-closed）。"""
        from initiatives.permissions import (
            auser_can_access_project,
            auser_is_project_member,
        )

        if actor is None or getattr(actor, "id", None) is None:
            raise FeatureSolutionError("forbidden", "需要已认证用户身份")
        if await auser_can_access_project(actor, project):
            return
        if await auser_is_project_member(actor, project.id):
            return
        raise FeatureSolutionError("forbidden", "无权访问此项目")

    async def _aassert_session_readable(self, session: Any, actor: Any) -> None:
        """会话可读校验：创建者本人放行；否则回落项目可读校验。"""
        if actor is None or getattr(actor, "id", None) is None:
            raise FeatureSolutionError("forbidden", "需要已认证用户身份")
        if getattr(actor, "is_superuser", False):
            return
        created_by_id = getattr(session, "created_by_id", None)
        if created_by_id is not None and str(created_by_id) == str(actor.id):
            return

        project = await self._aproject_of_session(session)
        if project is None:
            # 无项目归属（纯文本入口）且非创建者 → fail-closed。
            raise FeatureSolutionError("forbidden", "无权访问此方案会话")
        await self._aassert_project_readable(project, actor)

    @staticmethod
    async def _aproject_of_session(session: Any) -> Any:
        """会话 → 项目（经 decomposition.feature_meta.project_id 软引用；无则 None）。"""
        from initiatives.models import Project

        meta = (session.decomposition or {}).get("feature_meta") or {}
        project_id = meta.get("project_id")
        if not project_id:
            return None
        return await Project.objects.select_related("space").filter(pk=project_id).afirst()

    @staticmethod
    async def _aresolve_answers(clar: Any, answers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """把调用方答复对齐到本轮子题；未覆盖的题按 recommended 兜底作答。

        不兜底的话，调用方少答一题就会让会话永久挂起——对 MCP 这种无状态调用方尤其致命。
        """
        from delivery.models import ClarificationQuestion

        rows = [
            row
            async for row in ClarificationQuestion.objects.filter(
                clarification_id=clar.id
            ).order_by("order")
        ]
        by_id = {str(row.id): row for row in rows}
        supplied: dict[str, dict[str, Any]] = {}
        for ans in answers or []:
            if not isinstance(ans, dict):
                continue
            qid = str(ans.get("question_id") or "").strip()
            if qid in by_id:
                supplied[qid] = ans

        resolved: list[dict[str, Any]] = []
        for row in rows:
            qid = str(row.id)
            ans = supplied.get(qid)
            if ans is not None:
                resolved.append(
                    {
                        "question_id": qid,
                        "selected": ans.get("selected"),
                        "freeform_text": str(ans.get("freeform_text") or ""),
                    }
                )
                continue
            # 未作答 → 按推荐兜底（multi 用列表、single 取首项）。
            rec = row.recommended
            if row.qtype == "multi":
                selected: Any = rec if isinstance(rec, list) else ([rec] if rec else [])
            else:
                selected = rec[0] if isinstance(rec, list) and rec else (rec or "")
            resolved.append({"question_id": qid, "selected": selected, "freeform_text": ""})
        return resolved

    async def _abuild_state(self, session: Any, *, resolved: Any = None) -> FeatureSolutionState:
        """会话 → 对外状态快照（含待确认题 / 分类 / 方案产物）。"""
        from delivery.models import ConvergenceSessionStatus

        meta = (session.decomposition or {}).get("feature_meta") or {}
        state = FeatureSolutionState(
            session_id=str(session.id),
            project_id=str(meta.get("project_id") or ""),
            source=str(meta.get("source") or ""),
            truncated=bool(meta.get("truncated")),
            classification=session.classification or {},
            routing=session.routing or {},
        )
        if resolved is not None:
            state.source = resolved.source
            state.project_id = resolved.project_id
            state.feature_count = len(resolved.segments)
            state.truncated = resolved.truncated
        else:
            state.feature_count = len((session.decomposition or {}).get("feature_segments") or [])

        if session.status == ConvergenceSessionStatus.FAILED:
            state.status = STATUS_FAILED
            state.error = session.error or {}
            return state

        if session.status == ConvergenceSessionStatus.DONE:
            state.status = STATUS_COMPLETED
            await self._aattach_plan(session, state)
            return state

        questions, clarification_id = await self._acollect_pending_questions(session.id)
        if questions:
            state.status = STATUS_AWAITING_CONFIRMATION
            state.questions = questions
            state.clarification_id = clarification_id
            return state

        state.status = STATUS_RESEARCHING
        return state

    @staticmethod
    async def _acollect_pending_questions(session_id: Any) -> tuple[list[dict], str]:
        """取当前待答轮的子题（带 question_id 供 confirm 作答）。"""
        from delivery.models import ClarificationQuestion

        rows = [
            row
            async for row in ClarificationQuestion.objects.filter(
                clarification__session_id=session_id, answered_at__isnull=True
            )
            .select_related("clarification")
            .order_by("clarification__round_no", "order")
        ]
        if not rows:
            return [], ""
        questions = [
            {
                "question_id": str(row.id),
                "question": row.question,
                "type": row.qtype,
                "options": row.options or [],
                "recommended": row.recommended,
            }
            for row in rows
        ]
        return questions, str(rows[0].clarification_id)

    @staticmethod
    async def _aattach_plan(session: Any, state: FeatureSolutionState) -> None:
        """终态会话 → 取 ArtifactVersion content 作为方案，并渲染完整 markdown。"""
        from delivery.models import ArtifactVersion
        from initiatives.services.feature_solution_render import (
            render_feature_solution_markdown,
        )

        version_id = getattr(session, "current_artifact_version_id", None)
        if not version_id:
            return
        version = await ArtifactVersion.objects.filter(id=version_id).afirst()
        if version is None:
            return
        state.artifact_version_id = str(version.id)
        content = version.content if isinstance(version.content, dict) else {}
        state.plan = content
        state.markdown = render_feature_solution_markdown(
            content, classification=session.classification or {}
        )


def _build_requirement_text(resolved: Any) -> str:
    """展平的功能点 → 编排用需求文本（路由/召回/融合的检索与提示输入）。"""
    lines: list[str] = ["本次需求来自 feature list，包含以下功能点："]
    current_module = None
    for seg in resolved.segments:
        module = seg.get("module") or ""
        if module != current_module:
            current_module = module
            lines.append(f"\n## {module or '未分组'}")
        lines.append(f"- {seg.get('title', '')}")
        for item in (seg.get("acceptance") or [])[:3]:
            lines.append(f"  - 验收：{item}")
    return "\n".join(lines)
