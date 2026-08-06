"""蓝图节点重跑（quick 260806）：任意 stage 带操作员指令回卷重跑 + 版本谱系标签。

三件事（单一入口 :func:`arerun_blueprint_stage`）：

1. **谱系标签**：按「整篇重新生成 = major 递增（``decompose``）、节点级重跑 = 追加子段」
   计算新 ``run_label``（``"2"`` / ``"2.1"`` / ``"2.2.1"``），写进会话
   ``stage_state["stage_rerun"]``；此后该会话产出的每个 ``ArtifactVersion`` 都由
   ``ArtifactService`` 盖上这条谱系标签（历史版本全部保留，用户可在版本树里回看）。
2. **回卷会话**：经 ``ConvergenceSessionService.arewind_to_stage``（CAS，绝不盲写）把
   会话从任意状态拉回目标 stage 并置 ``running``；按 stage 失效下游产物
   （``ResearchService.mark_stale``，只动终态 task——在途容器自然跑完）。
3. **续驱**：与确认门动作端点同款「只入队不驱动」（``durable_blueprint_resume``），
   ``engine`` 形参仅供测试注入直驱路径。

操作员指令的消费面（各 adapter 读 ``stage_state["stage_rerun"]["instruction"]``）：

- ``summarize_requirement_context``（调研容器 / 拟方案容器 / indirect 合成）
- ``BlueprintRouteAdapter.route``（拼进路由 query）
- ``blueprint_spec_gate``（拼进歧义打分 prior_context）
- ``blueprint_intake`` LLM 拆分 prompt
- ``blueprint_merge`` 起草 feedback 段
- ``blueprint_review`` 审查 prompt

观测：``blueprint_stage_rerun_requested`` caller 事件 + ``blueprint.stage.rerun_requested``
会话事件；**指令正文不进日志与事件 payload**，只记长度。
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from django.utils import timezone

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)

__all__ = [
    "RERUNNABLE_STAGES",
    "STAGE_RERUN_KEY",
    "STAGE_RERUN_HISTORY_KEY",
    "arerun_blueprint_stage",
    "operator_instruction",
    "operator_instruction_section",
]

_COMPONENT = "process_runtime"

# 会话 stage_state 上的重跑标记键（ArtifactService._session_run_label 读同一键）。
STAGE_RERUN_KEY = "stage_rerun"
STAGE_RERUN_HISTORY_KEY = "stage_rerun_history"

# 可重跑的 stage 全集（technical_blueprint 图里真实存在；intake 不开放——它只建产物骨架，
# 重跑等价于 decompose；reroute 是 repo_research 的内部判定步，单独重跑无语义）。
RERUNNABLE_STAGES: frozenset[str] = frozenset(
    {
        "decompose",
        "route",
        "repo_research",
        "repo_confirmation",
        "spec_gate",
        "repo_plan",
        "merge",
        "ai_review",
    }
)

# 整篇重新生成的 stage（major 递增）；其余节点级重跑追加子段。
_MAJOR_RERUN_STAGES = frozenset({"decompose"})

# 需要把既有调研/分仓产物置失效的 stage → 失效语义。
# - decompose：整篇重做，全部调研与分仓产物重来；
# - repo_research：用户明确要求重调研 ⇒ 全部仓重跑；
# - repo_plan：全部仓的分仓方案重拟（mark_stale 让 aall_repo_plans_ready 变假、dispatch 重派）；
# - route / spec_gate / repo_confirmation / merge / ai_review：不失效——路由重跑沿用
#   「已完成仓不重跑」的增量语义，merge / ai_review 本就是读现有产物重算。
_INVALIDATE_RESEARCH_STAGES = frozenset({"decompose", "repo_research", "repo_plan"})

_MAX_INSTRUCTION_CHARS = 4000
_MAX_HISTORY_ITEMS = 20
_MAX_DETAIL_CHARS = 500

# 重跑前需要先拉回 drafting 的「人审/下游拥有」状态（blueprint_resume._HUMAN_OWNED_STATUSES
# 的可迭代子集；implemented / superseded 不支持重跑——前者归实施链，后者已被新蓝图取代）。
_PULL_BACK_STATUSES = frozenset({"pending_review", "confirmed", "implementing", "archived"})


def _detail(text: Any) -> str:
    return redact_secrets_in_text(str(text or ""))[:_MAX_DETAIL_CHARS]


# ---------------------------------------------------------------------------
# 谱系标签（纯函数 + 一次 DB 读）
# ---------------------------------------------------------------------------


def next_run_label(existing_labels: list[str], *, base_label: str, major: bool) -> str:
    """由既有标签集算下一个谱系标签（**纯函数**，供单测穷举）。

    - ``major=True``：取全部标签首段的最大整数 + 1（``["1", "2.1"] → "3"``）。
    - ``major=False``：在 ``base_label`` 下追加子段，序号 = 既有直接子标签的最大序号 + 1
      （``base="2"``、既有 ``["2.1", "2.3"]`` → ``"2.4"``；无子标签 → ``"2.1"``）。

    非法标签（段非整数）一律跳过，绝不抛。
    """
    labels = [str(label or "").strip() for label in existing_labels or []]
    labels = [label for label in labels if label]
    if major:
        majors = []
        for label in labels:
            head = label.split(".", 1)[0]
            try:
                majors.append(int(head))
            except ValueError:
                continue
        return str((max(majors) if majors else 1) + 1)

    base = str(base_label or "").strip() or "1"
    prefix = f"{base}."
    children = []
    for label in labels:
        if not label.startswith(prefix):
            continue
        suffix = label[len(prefix) :]
        if "." in suffix:
            continue
        try:
            children.append(int(suffix))
        except ValueError:
            continue
    return f"{base}.{(max(children) if children else 0) + 1}"


async def _acompute_run_label(artifact: Any, *, stage: str) -> str:
    """读该 artifact 全部版本标签，算本次重跑的新谱系标签。

    基线 = **最新版本**的标签（空串回落 ``"1"``——旧数据未盖章时视作首条谱系）。
    """
    from delivery.models import ArtifactVersion

    rows = [
        (str(label or ""), int(no or 0))
        async for label, no in ArtifactVersion.objects.filter(artifact_id=artifact.id)
        .order_by("-version_no")
        .values_list("version_label", "version_no")
    ]
    labels = [label for label, _ in rows if label]
    base_label = (rows[0][0] if rows else "") or "1"
    return next_run_label(labels, base_label=base_label, major=stage in _MAJOR_RERUN_STAGES)


# ---------------------------------------------------------------------------
# 操作员指令读取面（各 adapter 的唯一读口）
# ---------------------------------------------------------------------------


def operator_instruction(session: Any) -> str:
    """会话当前生效的操作员补充指令（无重跑标记返回空串，恒不抛）。"""
    try:
        stage_state = getattr(session, "stage_state", None) or {}
        marker = stage_state.get(STAGE_RERUN_KEY) if isinstance(stage_state, dict) else None
        if not isinstance(marker, dict):
            return ""
        return str(marker.get("instruction") or "").strip()[:_MAX_INSTRUCTION_CHARS]
    except Exception:  # noqa: BLE001 — 指令读取 best-effort，绝不反噬 prompt 组装
        return ""


def operator_instruction_section(session: Any) -> str:
    """指令 → prompt 分节（无指令返回空串，调用方整段省略——prompt 零扰动）。"""
    instruction = operator_instruction(session)
    if not instruction:
        return ""
    return f"## 操作员补充指令（本次重跑必须遵循，优先级高于早前的自动推断）\n{instruction}"


# ---------------------------------------------------------------------------
# 失效与续驱（best-effort helper）
# ---------------------------------------------------------------------------


async def _ainvalidate_research(session: Any, *, initiated_by_user_id: str) -> int:
    """把该会话全部**已终态**调研 task 置 stale（走既有 ``ResearchService.mark_stale``）。"""
    try:
        from delivery.models import RepoResearchTask
        from delivery.services import ResearchService

        task_ids = [
            str(tid)
            async for tid in RepoResearchTask.objects.filter(
                session_id=getattr(session, "id", None)
            ).values_list("id", flat=True)
        ]
        if not task_ids:
            return 0
        invalidated = await ResearchService().mark_stale(task_ids)
        logger.info(
            "blueprint_stage_rerun_research_invalidated",
            category="caller",
            component=_COMPONENT,
            session_id=str(getattr(session, "id", "")),
            task_count=len(task_ids),
            invalidated_partial_count=int(invalidated or 0),
            initiated_by_user_id=initiated_by_user_id or "system",
        )
        return int(invalidated or 0)
    except Exception as exc:  # noqa: BLE001 — 失效失败绝不反噬已落库的回卷
        logger.warning(
            "blueprint_stage_rerun_invalidate_failed",
            category="caller",
            component=_COMPONENT,
            session_id=str(getattr(session, "id", "")),
            error=_detail(exc),
        )
        return 0


async def _apull_back_blueprint_status(
    artifact: Any, session: Any, *, initiated_by_user_id: str
) -> None:
    """人审/归档态先拉回 ``drafting``（best-effort）：不拉回则状态映射被人审态短路，
    查看器上「归档」与「重新生成中」两个事实互相矛盾。"""
    from delivery.models import BlueprintStatus
    from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService

    current = str(getattr(artifact, "blueprint_status", "") or "")
    if current not in _PULL_BACK_STATUSES:
        return
    try:
        await BlueprintLifecycleService().transition(
            artifact,
            BlueprintStatus.DRAFTING,
            initiated_by_user_id=initiated_by_user_id or "system",
            session=session,
        )
    except Exception as exc:  # noqa: BLE001 — 状态映射是展示面，绝不阻断重跑
        logger.warning(
            "blueprint_stage_rerun_status_pull_back_failed",
            category="caller",
            component=_COMPONENT,
            artifact_id=str(getattr(artifact, "id", "")),
            from_status=current,
            error=_detail(exc),
        )


async def _aenqueue_resume(session: Any, *, initiated_by_user_id: str) -> None:
    """只入队不驱动（与 ``aresume_after_gate_action`` 同款；入队失败恢复扫描兜底）。"""
    session_id = str(getattr(session, "id", "") or "")
    try:
        from durable.queues import QUEUE_BLUEPRINT
        from durable.service import DurableTaskService

        await DurableTaskService.defer(
            "durable_blueprint_resume",
            {"session_id": session_id},
            queue=QUEUE_BLUEPRINT,
            lock=f"blueprint-resume-{session_id}",
            initiated_by_user_id=initiated_by_user_id or "system",
        )
    except Exception as exc:  # noqa: BLE001 — 入队失败绝不反噬已落库的回卷
        logger.warning(
            "blueprint_stage_rerun_enqueue_failed",
            category="caller",
            component=_COMPONENT,
            session_id=session_id,
            error=_detail(exc),
        )


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


async def arerun_blueprint_stage(
    artifact: Any,
    session: Any,
    *,
    stage: str,
    instruction: str = "",
    user: Any = None,
    initiated_by_user_id: str = "system",
    engine: Any = None,
) -> dict:
    """带操作员指令重跑蓝图的某个 stage。恒定五键
    ``{status, run_label, stage, detail, session_status}``，
    ``status ∈ {accepted, invalid, conflict}``。

    步骤（顺序固定）：

    1. 校验 stage ∈ :data:`RERUNNABLE_STAGES`；指令截断 4000 字符（可空 = 纯重跑）。
    2. 由版本标签集算新 ``run_label``（``decompose`` = major 递增，其余追加子段）。
    3. 按 stage 失效下游产物（:data:`_INVALIDATE_RESEARCH_STAGES`）。
    4. ``arewind_to_stage``（CAS）：回卷 + 原子写入 ``stage_rerun`` 标记与历史。
       CAS 失败 → ``conflict``（并发驱动者刚推进了会话），DB 不写。
    5. 人审/归档态拉回 ``drafting``（best-effort）。
    6. emit ``blueprint.stage.rerun_requested`` 会话事件（best-effort）。
    7. 入队续驱（``engine`` 非 None 时测试直驱）。
    """
    started = time.monotonic()
    initiated = str(getattr(user, "id", "") or "") or (initiated_by_user_id or "system")
    stage = str(stage or "").strip()
    text = str(instruction or "").strip()[:_MAX_INSTRUCTION_CHARS]
    result = {
        "status": "",
        "run_label": "",
        "stage": stage,
        "detail": "",
        "session_status": str(getattr(session, "status", "") or ""),
    }

    if stage not in RERUNNABLE_STAGES:
        result["status"] = "invalid"
        result["detail"] = f"不支持重跑的 stage={stage!r}；可选 {sorted(RERUNNABLE_STAGES)}"
        return result
    if session is None:
        result["status"] = "invalid"
        result["detail"] = "该蓝图尚无编排会话，无法重跑"
        return result

    from delivery.services.convergence_session_service import ConvergenceSessionService

    run_label = await _acompute_run_label(artifact, stage=stage)

    # 3. 失效在回卷之前：回卷成功即刻可被续驱，晚失效会让第一轮 advance 读到旧产物。
    if stage in _INVALIDATE_RESEARCH_STAGES:
        await _ainvalidate_research(session, initiated_by_user_id=initiated)

    # 4. 原子回卷 + 写标记（历史封顶 _MAX_HISTORY_ITEMS，防 stage_state 无界膨胀）。
    history = []
    try:
        stage_state = getattr(session, "stage_state", None) or {}
        raw = stage_state.get(STAGE_RERUN_HISTORY_KEY) if isinstance(stage_state, dict) else None
        history = [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
    except Exception:  # noqa: BLE001 — 历史读取 best-effort
        history = []
    marker = {
        "stage": stage,
        "instruction": text,
        "run_label": run_label,
        "requested_by": initiated,
        "requested_at": timezone.now().isoformat(),
    }
    history = ([*history, marker])[-_MAX_HISTORY_ITEMS:]

    try:
        applied = await ConvergenceSessionService().arewind_to_stage(
            session,
            stage=stage,
            stage_state_update={
                STAGE_RERUN_KEY: marker,
                STAGE_RERUN_HISTORY_KEY: history,
            },
            reason="stage_rerun",
        )
    except ValueError as exc:
        result["status"] = "invalid"
        result["detail"] = _detail(exc)
        return result
    if not applied:
        result["status"] = "conflict"
        result["detail"] = "会话状态已被并发推进，请刷新后重试"
        result["session_status"] = str(getattr(session, "status", "") or "")
        return result

    result["status"] = "accepted"
    result["run_label"] = run_label
    result["session_status"] = str(getattr(session, "status", "") or "")

    # 5-6. 状态拉回 + 会话事件（均 best-effort，绝不反噬已落库的回卷）。
    await _apull_back_blueprint_status(artifact, session, initiated_by_user_id=initiated)
    try:
        from delivery.services import ConvergenceSessionService as _Service
        from delivery.services.event_taxonomy import EVENT_BLUEPRINT_STAGE_RERUN_REQUESTED

        await _Service().aemit_event(
            EVENT_BLUEPRINT_STAGE_RERUN_REQUESTED,
            session,
            {
                "stage": stage,
                "run_label": run_label,
                "instruction_len": len(text),
                "initiated_by_user_id": initiated,
            },
        )
    except Exception:  # noqa: BLE001 — 事件 best-effort
        pass

    # 7. 续驱：测试直驱 / 生产入队。
    if engine is not None:
        try:
            from services.process_runtime.blueprint_resume import (
                adrive_blueprint_session_to_pause_or_terminal,
            )

            fresh = await adrive_blueprint_session_to_pause_or_terminal(engine, session)
            result["session_status"] = str(getattr(fresh, "status", "") or "")
        except Exception as exc:  # noqa: BLE001 — 直驱失败不反噬已受理的重跑
            logger.warning(
                "blueprint_stage_rerun_drive_failed",
                category="caller",
                component=_COMPONENT,
                session_id=str(getattr(session, "id", "")),
                error=_detail(exc),
            )
    else:
        await _aenqueue_resume(session, initiated_by_user_id=initiated)

    logger.info(
        "blueprint_stage_rerun_requested",
        category="caller",
        component=_COMPONENT,
        artifact_id=str(getattr(artifact, "id", "")),
        session_id=str(getattr(session, "id", "")),
        stage=stage,
        run_label=run_label,
        instruction_len=len(text),
        initiated_by_user_id=initiated,
        duration_ms=round((time.monotonic() - started) * 1000, 2),
    )
    return result
