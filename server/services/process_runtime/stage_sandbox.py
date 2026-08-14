"""stage_sandbox —— 蓝图编排环节的单跑层（headless stage runner）。

把 `technical_blueprint` 链里的三个环节拆成可独立触发的能力（MCP / skills 调用面）：

- **route**：三分量融合仓库路由（能力树 + 章程 + 历史），喂内存 stub session 零落库单跑；
  `ignore_pin=True` 可绕过项目手动绑定的固定路由短路（对比「人工绑定 vs 自动路由」）。
- **spec**：需求文本 → feature_points（LLM 拆分或直采）→ intent 补齐 → 四维歧义打分，
  零落库单跑，输出与 `requirement_spec` / `ambiguity_report` 同形。
- **research**：对显式仓库集发起沙箱调研 —— 建真实 `ConvergenceSession`
  （``process_type="blueprint_stage_sandbox"``），复用 `BlueprintResearchAdapter.dispatch`
  的完整派发链（direct 仓起容器深调研 / indirect 仓轻量合成 / 无 runner 自动降级）。

三条纪律：

1. **正式编排零扰动**：不改 stage 图与 handler；沙箱 process_type 独立注册，蓝图续驱
   （`adrive_blueprint_session_to_pause_or_terminal` 的 process_type 守门）与恢复扫描
   （只扫 `technical_blueprint`）都不会驱动沙箱会话——容器回调只负责把结论落
   `RepoResearchTask` / `PartialPlan`，结果由 :func:`aget_research_sandbox` 直接读表。
2. **单跑产物只是提案**：本模块零写 `ProjectBranch` / `RepoAssociation` / `Artifact`；
   是否把路由/调研结果写回「项目关联仓库」由用户显式调用 `apply_repo_association`
   （`ProjectBranchService`，成员 fail-closed + 审计）决定。
3. **观测**：runner 各记 caller 类 completed 事件（`component=process_runtime`、
   `initiated_by_user_id`、`duration_ms`）；需求正文不进日志，只记标量；LLM 调用点
   复用既有 call_source（`BLUEPRINT_DECOMPOSE` / `BLUEPRINT_SPEC_GATE` /
   `BLUEPRINT_REPO_RESEARCH`），零新增枚举。
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import structlog
from asgiref.sync import sync_to_async

logger = structlog.get_logger(__name__)

__all__ = [
    "SANDBOX_PROCESS_TYPE",
    "SandboxSession",
    "arun_route_stage",
    "arun_spec_stage",
    "astart_research_sandbox",
    "aget_research_sandbox",
]

_COMPONENT = "process_runtime"

# 沙箱会话的 process_type（独立注册：仅为通过 create_session 的注册校验；
# 蓝图续驱与恢复扫描都按 process_type 过滤，不会驱动它）。
SANDBOX_PROCESS_TYPE = "blueprint_stage_sandbox"

# 单次沙箱调研的仓库数上界（deep 调研起 30min 容器，防一把梭全库）。
_MAX_RESEARCH_REPOS = 10
_VALID_ROLES = ("direct", "indirect")

# 调研任务终态集（与 research_aggregation.TERMINAL_STATUSES 同值，字面量避免模块级重依赖）。
_TERMINAL_TASK_STATUSES = ("done", "failed")


# ── 沙箱 process 注册 ─────────────────────────────────────────────────────


def _register_sandbox_process() -> None:
    """幂等注册沙箱 ``ProcessDefinition``（单 stage；无任何驱动方会 advance 它）。

    handler 仅为满足 ``StageDef`` 形状而存在：沙箱会话不经 engine 推进（蓝图续驱对
    非 ``technical_blueprint`` 一律 no-op），结果读取直接查任务表。
    """
    from services.process_runtime.engine import StageOutcome
    from services.process_runtime.registry import (
        STAGE_DONE,
        ProcessDefinition,
        StageDef,
        get_process_definition,
        register_process_type,
    )

    if get_process_definition(SANDBOX_PROCESS_TYPE) is not None:
        return

    async def _h_sandbox_research(session: Any, engine: Any) -> StageOutcome:
        from services.process_runtime.research_aggregation import aall_research_tasks_terminal

        if await aall_research_tasks_terminal(session.id):
            return StageOutcome(event="research_complete")
        return StageOutcome(event="research_dispatched")

    register_process_type(
        ProcessDefinition(
            process_type=SANDBOX_PROCESS_TYPE,
            artifact_type="technical_plan",
            initial_stage="repo_research",
            stages={
                "repo_research": StageDef(
                    key="repo_research",
                    handler=_h_sandbox_research,
                    transitions={
                        "research_complete": STAGE_DONE,
                        "research_dispatched": "repo_research",
                    },
                    pausable=True,
                    wait_status="waiting_event",
                )
            },
        )
    )


_register_sandbox_process()


# ── 内存 stub session ─────────────────────────────────────────────────────


class SandboxSession:
    """内存 stub session：满足 route/spec adapter 的宽松读接口（`getattr` 面），零 ORM。

    adapter 内的事件 emit（`aemit_event`）对非 DB 行会抛 FK 异常，但那些调用点全部
    best-effort 吞异常 —— 单跑天然静默，不产生事件噪声。
    """

    def __init__(self, *, stage_state: dict | None = None, initiated_by_user_id: str = "") -> None:
        self.id = uuid.uuid4()
        self.stage_state: dict = stage_state or {}
        self.work_item_id = None
        self.current_artifact_version_id = None
        self.initiated_by_user_id = str(initiated_by_user_id or "")
        # 与 `created_by` 同源：多个 `_initiated_by` helper 在 `initiated_by_user_id`
        # 为空时回退读这个键，两者指向同一人才不会自相矛盾。
        self.created_by_id = self.initiated_by_user_id or None
        self._created_by_resolved = False
        self._created_by: Any = None

    @property
    def decomposition(self) -> dict:
        return (self.stage_state or {}).get("decomposition") or {}

    @property
    def created_by(self) -> Any:
        """发起用户实体——历史分量按它做 fail-closed 权限检索。

        单跑入口只收得到 `initiated_by_user_id`（字符串），而消费方读的是
        `session.created_by`。stub 不定义该属性时属性访问直接 AttributeError，
        被调用方的宽 `except` 吞成 `retrieval_error`——「压根没有发起用户」于是
        伪装成「检索出错」，把 `no_acting_user` 这个专门的降级取值架空了。

        解析不到一律返回 None（落 `no_acting_user`），绝不伪造 actor 提权。
        与真实模型的 lazy FK 同样是同步 ORM，调用方照旧经 `sync_to_async` 取。
        """
        if self._created_by_resolved:
            return self._created_by
        self._created_by_resolved = True
        if self.created_by_id:
            from django.contrib.auth import get_user_model

            self._created_by = get_user_model().objects.filter(id=self.created_by_id).first()
        return self._created_by


# ── 共用 helper ───────────────────────────────────────────────────────────


def _normalize_requirement_spec(requirement_spec: Any, requirement_text: str) -> dict:
    """归一单跑输入：显式 spec 优先，否则由需求文本组最小 spec（goal 直接放文本）。"""
    if isinstance(requirement_spec, dict) and requirement_spec:
        return requirement_spec
    text = str(requirement_text or "").strip()
    if not text:
        return {}
    return {"goal": text, "feature_points": []}


@sync_to_async
def _project_scope_repository_ids(project_id: str) -> list[str] | None:
    """project → 所属 space 的仓库集（取不到返 None = 全库；镜像 route 的 work_item 路径）。"""
    from initiatives.models import Project

    project = Project.objects.select_related("space").filter(id=project_id).first()
    if project is None or project.space is None:
        return None
    repo_ids = [str(r) for r in project.space.repositories.values_list("id", flat=True)]
    return repo_ids or None


@sync_to_async
def _repository_names(repository_ids: list[str]) -> dict[str, str]:
    from repositories.models import Repository

    return {
        str(row["id"]): str(row["name"] or "")
        for row in Repository.objects.filter(id__in=repository_ids).values("id", "name")
    }


def _initiated(initiated_by_user_id: str) -> str:
    return str(initiated_by_user_id or "") or "system"


# ── route 单跑 ────────────────────────────────────────────────────────────


async def arun_route_stage(
    *,
    requirement_spec: dict | None = None,
    requirement_text: str = "",
    project_id: str = "",
    space_id: str = "",
    team_id: str = "",
    primary_team: str = "",
    include_repository_ids: list[str] | None = None,
    exclude_repository_ids: list[str] | None = None,
    ignore_pin: bool = False,
    top_k: int = 5,
    initiated_by_user_id: str = "",
    route_adapter: Any = None,
) -> dict:
    """三分量融合路由单跑：返回与 `stage_state["routing"]` 逐键同形的契约摘要。

    候选范围：显式 ``include_repository_ids`` 与团队 ``team_core`` 求交。
    **漏斗 MCP 禁止**无团队时全库 primary（D1/D3）——无法识别团队 → clarify。
    裸 ``RepoRouterV2.route`` 无 grouping 的全局路径仍保留兼容，但不经本入口。
    """
    started = time.monotonic()
    spec = _normalize_requirement_spec(requirement_spec, requirement_text)

    resolved_team = str(team_id or primary_team or "").strip()
    resolved_space = str(space_id or "").strip()
    include = [str(r) for r in (include_repository_ids or []) if str(r or "")]
    if not include and str(project_id or ""):
        try:
            include = await _project_scope_repository_ids(str(project_id)) or []
        except Exception:  # noqa: BLE001 — 范围解析 best-effort
            include = []

    # 无任何团队上下文且无 project 挂载仓 → clarify（禁止静默全库 primary）
    if not str(project_id or "") and not resolved_space and not resolved_team and not include:
        offer_spaces = await _aenumerate_space_offer()
        duration_ms = round((time.monotonic() - started) * 1000, 2)
        logger.info(
            "blueprint_stage_route_sandbox_clarify",
            category="caller",
            component=_COMPONENT,
            initiated_by_user_id=_initiated(initiated_by_user_id),
            clarify_reason="missing_team",
            duration_ms=duration_ms,
        )
        return {
            "router_version": "clarify",
            "auto_selected": False,
            "intent": "",
            "weights_used": {},
            "charter_supplement_count": 0,
            "unjustified_boundary_hit_count": 0,
            "candidates": [],
            "citations": [],
            "status": "clarify",
            "clarify_reason": "missing_team",
            "team_core": [],
            "team_core_count": 0,
            "offer": {"bind_space": True, "spaces": offer_spaces},
        }

    stage_state: dict[str, Any] = {"requirement_spec": spec}
    if include:
        stage_state["include_repos"] = include
    decomposition: dict[str, Any] = {}
    if str(project_id or ""):
        decomposition["project_id"] = str(project_id)
    if resolved_space:
        decomposition["space_id"] = resolved_space
    if resolved_team:
        decomposition["team_id"] = resolved_team
        decomposition["primary_team"] = resolved_team
    if decomposition:
        stage_state["decomposition"] = decomposition
    session = SandboxSession(stage_state=stage_state, initiated_by_user_id=initiated_by_user_id)

    from services.process_runtime.blueprint_route import BlueprintRouteAdapter

    adapter = route_adapter or BlueprintRouteAdapter(top_k=int(top_k))
    summary = await adapter.route(
        session,
        exclude_repository_ids={str(r) for r in (exclude_repository_ids or []) if str(r or "")},
        ignore_pin=bool(ignore_pin),
    )
    # Phase 130：hard_scope 守卫——primary/候选不得逃出 shortlist ∪ reuse hosts
    try:
        hard_scope = {
            str(x)
            for x in (summary.get("hard_scope") or [])
            if str(x or "").strip()
        }
        if not hard_scope:
            hard_scope = {
                str(r.get("repository_id") or "")
                for r in (summary.get("shortlist") or [])
                if isinstance(r, dict) and r.get("repository_id")
            }
        if hard_scope:
            summary["candidates"] = [
                c
                for c in (summary.get("candidates") or [])
                if str(c.get("repository_id") or "") in hard_scope
            ]
            guarded_placements = []
            for p in summary.get("placements") or []:
                if not isinstance(p, dict):
                    continue
                primary = str(p.get("primary_repo") or "").strip()
                if primary and primary not in hard_scope:
                    p = {**p, "primary_repo": None, "open_questions": list(p.get("open_questions") or []) + ["sandbox_hard_scope_drop"]}
                supporting = [
                    s
                    for s in (p.get("supporting_repos") or [])
                    if str(s) in hard_scope
                ]
                guarded_placements.append({**p, "supporting_repos": supporting})
            if "placements" in summary:
                summary["placements"] = guarded_placements
            summary["hard_scope"] = sorted(hard_scope)
        # Phase 131：block / needs_human_review 禁止全库 primary 回填
        gate_status = str((summary.get("funnel_gates") or {}).get("status") or "")
        review_status = str(summary.get("review_status") or "")
        if (
            gate_status == "block"
            or review_status == "needs_human_review"
            or "needs_human_review"
            in list(((summary.get("reflection") or {}).get("reason_codes") or []))
        ):
            summary["auto_selected"] = False
            if hard_scope:
                summary["candidates"] = [
                    c
                    for c in (summary.get("candidates") or [])
                    if str(c.get("repository_id") or "") in hard_scope
                ]
            else:
                # 无 hard_scope 时清空候选，禁止静默全库
                summary["candidates"] = []
            if review_status == "needs_human_review" or "needs_human_review" in list(
                ((summary.get("reflection") or {}).get("reason_codes") or [])
            ):
                summary["status"] = "clarify"
                summary["clarify_reason"] = summary.get("clarify_reason") or "needs_human_review"
            elif gate_status == "block":
                summary["status"] = "block"
                summary["clarify_reason"] = summary.get("clarify_reason") or "funnel_gate_block"
    except Exception:  # noqa: BLE001 — 守卫 best-effort，不反噬路由
        pass
    logger.info(
        "blueprint_stage_route_sandbox_completed",
        category="caller",
        component=_COMPONENT,
        initiated_by_user_id=_initiated(initiated_by_user_id),
        candidate_count=len(summary.get("candidates") or []),
        router_version=str(summary.get("router_version") or ""),
        ignore_pin=bool(ignore_pin),
        scope_repository_count=len(include),
        status=str(summary.get("status") or ""),
        clarify_reason=str(summary.get("clarify_reason") or ""),
        placement_count=len(summary.get("placements") or []),
        hard_scope_count=len(summary.get("hard_scope") or []),
        duration_ms=round((time.monotonic() - started) * 1000, 2),
    )
    return summary


@sync_to_async
def _aenumerate_space_offer(limit: int = 20) -> list[dict[str, str]]:
    """可枚举 Spaces 时填 offer.spaces（id+name，无密钥）。"""
    try:
        from projects.models import Space

        rows = list(Space.objects.order_by("-updated_at").values("id", "name")[:limit])
        return [{"id": str(r["id"]), "name": str(r["name"] or "")} for r in rows]
    except Exception:  # noqa: BLE001
        return []


# ── spec 单跑 ─────────────────────────────────────────────────────────────


async def arun_spec_stage(
    *,
    requirement_text: str,
    feature_points: list[dict] | None = None,
    prior_context: str = "",
    assumptions_tier: str = "",
    classify_intents: bool = True,
    initiated_by_user_id: str = "",
    decomposer: Any = None,
    classifier: Any = None,
    scorer: Any = None,
) -> dict:
    """需求规格单跑：拆功能点 + intent 补齐 + 四维歧义打分，零落库。

    Returns:
        ``{"requirement_spec": {...}, "ambiguity": {...}, "source": "llm"|"provided"}``。
        ``ambiguity`` 与规格门的 ``ambiguity_report`` 同形（另带 ``questions`` 与
        ``above_threshold``——单跑没有澄清线程，问题直接返回给调用方）。
    """
    from services.process_runtime.blueprint_ambiguity_score import (
        ASSUMPTIONS_TIERS,
        aload_spec_gate_config,
        ascore_ambiguity,
        is_ambiguous,
        normalize_ambiguity_scores,
        weighted_total,
    )
    from services.process_runtime.blueprint_intake import (
        FEATURE_POINT_INTENTS,
        GOAL_BLOCK_ID,
        _allm_feature_points,
        _points_from_segments,
    )
    from services.process_runtime.blueprint_intent_classify import aclassify_intents

    started = time.monotonic()
    session = SandboxSession(initiated_by_user_id=initiated_by_user_id)
    tier = str(assumptions_tier or "")
    if tier not in ASSUMPTIONS_TIERS:
        tier = ""

    provided = [p for p in (feature_points or []) if isinstance(p, dict)]
    if provided:
        source = "provided"
        raw_items = provided
    else:
        source = "llm"
        decompose = decomposer or _allm_feature_points
        items = await decompose(session, str(requirement_text or ""))
        raw_items = [i for i in (items or []) if isinstance(i, dict)]
    points = _points_from_segments(raw_items)

    # intent 补齐：只对「输入里没给合法 intent」的功能点跑分类器（LLM 不可得保留
    # `_points_from_segments` 的缺省值，绝不阻断）。按 title 对齐输入与归一产物
    # （归一会丢空标题项，位序不再一一对应）。
    if classify_intents and points:
        titled_valid = {
            str(item.get("title") or "").strip()[:200]
            for item in raw_items
            if str(item.get("intent") or "").strip().lower() in FEATURE_POINT_INTENTS
        }
        pending = [p for p in points if p["title"] not in titled_valid]
        if pending:
            classify = classifier or aclassify_intents
            try:
                classified = await classify(feature_points=pending, session_id=str(session.id))
            except Exception:  # noqa: BLE001 — 分类 best-effort，失败保留缺省 intent
                classified = None
            if isinstance(classified, dict):
                pending_ids = {p["id"] for p in pending}
                for point in points:
                    candidate = str(classified.get(point["id"], "")).strip().lower()
                    if point["id"] in pending_ids and candidate in FEATURE_POINT_INTENTS:
                        point["intent"] = candidate

    # 四维歧义打分（fail-closed：不可得 → 全维保守值 1.0，与规格门同向）。
    score = scorer or ascore_ambiguity
    goal_text = str(requirement_text or "").strip()
    scores = await score(
        goal=goal_text,
        feature_points=points,
        constraints=[],
        prior_context=str(prior_context or ""),
        session_id=str(session.id),
        tier=tier,
    )
    scorer_unavailable = not isinstance(scores, dict)
    if scorer_unavailable:
        scores = normalize_ambiguity_scores(None)
    config = await aload_spec_gate_config(tier=tier)
    total = weighted_total(scores["dimensions"], config["weights"])

    ambiguity = {
        "dimensions": scores["dimensions"],
        "weighted_total": total,
        "threshold": config["threshold"],
        "weights": config["weights"],
        "above_threshold": is_ambiguous(total, config["threshold"]),
        "questions": list(scores.get("questions") or []),
        "scorer_unavailable": scorer_unavailable,
        "assumptions_tier": tier,
        "max_rounds": int(config.get("max_rounds") or 0),
    }
    requirement_spec = {
        "goal": [{"block_id": GOAL_BLOCK_ID, "type": "paragraph", "text": goal_text}],
        "feature_points": points,
    }
    logger.info(
        "blueprint_stage_spec_sandbox_completed",
        category="caller",
        component=_COMPONENT,
        initiated_by_user_id=_initiated(initiated_by_user_id),
        source=source,
        point_count=len(points),
        weighted_total=total,
        above_threshold=ambiguity["above_threshold"],
        scorer_unavailable=scorer_unavailable,
        assumptions_tier=tier,
        duration_ms=round((time.monotonic() - started) * 1000, 2),
    )
    return {"requirement_spec": requirement_spec, "ambiguity": ambiguity, "source": source}


# ── research 沙箱 ─────────────────────────────────────────────────────────


async def astart_research_sandbox(
    *,
    requirement_text: str,
    repositories: list[dict],
    requirement_spec: dict | None = None,
    project_id: str = "",
    created_by: Any = None,
    initiated_by_user_id: str = "",
    research_adapter: Any = None,
) -> dict:
    """对显式仓库集发起沙箱调研（建真实沙箱会话 + 复用蓝图调研派发链）。

    候选形状与 112-03 路由契约同形（`repository_id` / `role_suggestion` / `confidence`），
    ``role="direct"`` 起容器深调研、``"indirect"`` 服务端轻量合成；无在线 runner 时
    deep 自动降级 light（返回值 ``degraded=True`` 可见）。

    Raises:
        ValueError: ``repositories`` 归一后为空。
    """
    from delivery.models import ConvergenceSessionEntrypoint
    from delivery.services import ConvergenceSessionService
    from services.process_runtime.blueprint_research_adapter import (
        BlueprintResearchAdapter,
    )

    started = time.monotonic()
    _register_sandbox_process()
    spec = _normalize_requirement_spec(requirement_spec, requirement_text)

    candidates: list[dict] = []
    seen: set[str] = set()
    for item in repositories or []:
        if not isinstance(item, dict):
            continue
        repository_id = str(item.get("repository_id") or "")
        if not repository_id or repository_id in seen:
            continue
        seen.add(repository_id)
        role = str(item.get("role") or "direct").strip().lower()
        if role not in _VALID_ROLES:
            role = "direct"
        candidates.append(
            {
                "repository_id": repository_id,
                "repository_name": "",
                "role_suggestion": role,
                "confidence": str(item.get("confidence") or "").strip().lower(),
                "evidence": {},
            }
        )
        if len(candidates) >= _MAX_RESEARCH_REPOS:
            break
    if not candidates:
        raise ValueError("repositories 不能为空（每项须含 repository_id）")

    names = await _repository_names([c["repository_id"] for c in candidates])
    for candidate in candidates:
        candidate["repository_name"] = names.get(candidate["repository_id"], "")

    decomposition: dict[str, Any] = {"requirement_text": str(requirement_text or "")}
    if str(project_id or ""):
        decomposition["project_id"] = str(project_id)
    stage_state = {
        "decomposition": decomposition,
        "requirement_spec": spec,
        "routing": {
            "router_version": "stage_sandbox",
            "auto_selected": False,
            "intent": "",
            "weights_used": {},
            "charter_supplement_count": 0,
            "unjustified_boundary_hit_count": 0,
            "candidates": candidates,
            "citations": [],
        },
    }
    session = await ConvergenceSessionService().create_session(
        SANDBOX_PROCESS_TYPE,
        ConvergenceSessionEntrypoint.MCP,
        stage_state=stage_state,
        created_by=created_by,
        initiated_by_user_id=str(initiated_by_user_id or ""),
    )

    adapter = research_adapter or BlueprintResearchAdapter()
    result = await adapter.dispatch(session)
    result = result if isinstance(result, dict) else {}
    logger.info(
        "blueprint_stage_research_sandbox_started",
        category="caller",
        component=_COMPONENT,
        initiated_by_user_id=_initiated(initiated_by_user_id),
        session_id=str(session.id),
        repository_count=len(candidates),
        dispatched=int(result.get("dispatched") or 0),
        synthesized=int(result.get("synthesized") or 0),
        degraded=bool(result.get("degraded")),
        duration_ms=round((time.monotonic() - started) * 1000, 2),
    )
    return {
        "session_id": str(session.id),
        "dispatched": int(result.get("dispatched") or 0),
        "synthesized": int(result.get("synthesized") or 0),
        "degraded": bool(result.get("degraded")),
        "tasks": [str(t) for t in (result.get("tasks") or [])],
    }


async def aget_research_sandbox(*, session_id: str, user: Any) -> dict | None:
    """读沙箱调研结果（任务状态 + 最新 valid §7 调研结论）。

    仅限会话创建者；非沙箱会话 / 非本人 / 不存在一律返回 ``None``（调用方回中性 404，
    不泄露存在性）。
    """
    from delivery.models import ConvergenceSession

    session = await ConvergenceSession.objects.filter(id=session_id).afirst()
    if session is None or str(session.process_type) != SANDBOX_PROCESS_TYPE:
        return None
    user_id = getattr(user, "id", None)
    created_by_id = getattr(session, "created_by_id", None)
    if user_id is None or created_by_id is None or str(created_by_id) != str(user_id):
        return None

    tasks = await _collect_research_tasks(session.id)
    all_terminal = all(t["status"] in _TERMINAL_TASK_STATUSES for t in tasks)
    return {"session_id": str(session.id), "all_terminal": all_terminal, "tasks": tasks}


@sync_to_async
def _collect_research_tasks(session_id: Any) -> list[dict]:
    """该沙箱会话的调研任务 + 各自最新 valid PartialPlan content（只读）。"""
    from delivery.models import PartialPlan, RepoResearchTask

    rows = list(
        RepoResearchTask.objects.filter(session_id=session_id)
        .select_related("repository")
        .order_by("created_at")
    )
    partials: dict[str, dict] = {}
    for partial in PartialPlan.objects.filter(
        research_task_id__in=[row.id for row in rows], valid=True
    ).order_by("research_task_id", "-created_at"):
        key = str(partial.research_task_id)
        if key not in partials:
            partials[key] = partial.content if isinstance(partial.content, dict) else {}
    return [
        {
            "task_id": str(row.id),
            "repository_id": str(row.repository_id),
            "repository_name": str(getattr(row.repository, "name", "") or ""),
            "status": str(row.status),
            "attempt": int(row.attempt or 0),
            "error": row.error if isinstance(row.error, dict) else {},
            "research": partials.get(str(row.id)),
        }
        for row in rows
    ]
