"""节点生命周期相位投影（Chassis v2 · P5）。

把 ``NodeExecution.status`` + 经 ``node_execution_id`` 软关联的 ``ConvergenceSession``
（``status`` / ``current_stage`` / ``current_artifact_version``）+ 该 session 的
待答 ``Clarification.round_no`` **投影**为一个**对用户可见的 UI 生命周期相位**与
**收敛轮次**。

红线（WORKFLOW-RUNTIME-SPEC §7）：**不扩 ``NodeExecutionStatus``**——AI 内部态从
``ConvergenceSession`` / 澄清轮次投影而来，本模块为纯函数投影，不落第三套表、不写库。

相位词表（``LIFECYCLE_PHASES``，语义色见前端 ``lifecycleBadge.ts``）：

- ``idle``：待运行（pending/queued/skipped/cancelled）。
- ``running``：运行中（蓝）——首轮执行。
- ``waiting_clarification``：等待澄清（琥珀）。
- ``revising``：修订中（紫）——已答过澄清、正基于答复重跑。
- ``produced``：已产出（绿）——节点完成且产出 artifact 版本。
- ``waiting_approval``：等待审批（琥珀）——gate 闸门。
- ``done``：已完成（绿）——节点完成但无 artifact 产出语义。
- ``failed``：失败（红）。

设计：核心 ``project_node_lifecycle`` 为**纯函数**（只读属性、可脱机单测）；
``aproject_node_lifecycle`` 为 best-effort 异步收集器（查 session/澄清后调纯函数），
任何异常返回 ``None``，**绝不反噬主流程**（observability 红线）。
"""

from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ---- 相位词表 -----------------------------------------------------------------

PHASE_IDLE = "idle"
PHASE_RUNNING = "running"
PHASE_WAITING_CLARIFICATION = "waiting_clarification"
PHASE_REVISING = "revising"
PHASE_PRODUCED = "produced"
PHASE_WAITING_APPROVAL = "waiting_approval"
PHASE_DONE = "done"
PHASE_FAILED = "failed"

LIFECYCLE_PHASES: frozenset[str] = frozenset(
    {
        PHASE_IDLE,
        PHASE_RUNNING,
        PHASE_WAITING_CLARIFICATION,
        PHASE_REVISING,
        PHASE_PRODUCED,
        PHASE_WAITING_APPROVAL,
        PHASE_DONE,
        PHASE_FAILED,
    }
)

# 收敛轮次默认上限（仅用于「第 N/6 轮」展示文案；非硬约束）。
DEFAULT_MAX_ROUNDS = 6


@dataclass(frozen=True)
class LifecycleProjection:
    """节点生命周期投影结果（值对象，不持久化）。"""

    lifecycle: str
    round: int | None
    max_rounds: int


def project_node_lifecycle(
    node_execution: Any,
    *,
    session: Any | None = None,
    pending_round_no: int | None = None,
    answered_round_count: int = 0,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
) -> LifecycleProjection:
    """把一个 NodeExecution（+ 关联 ConvergenceSession + 待答澄清轮次）投影为相位。

    参数:
      node_execution: 读 ``.status``（NodeExecutionStatus 值）。
      session: 软关联的 ``ConvergenceSession``（读 ``.status`` / ``.current_artifact_version_id``）；
        无关联 AI 收敛会话时为 ``None``，相位退化为纯节点态映射。
      pending_round_no: 该 session 当前待答澄清的 ``round_no``（无待答为 ``None``）。
      answered_round_count: 该 session 已答澄清轮数（用于「修订中 · 第 N 轮」展示）。
      max_rounds: 轮次展示上限。

    纯函数：只读属性，不查库、不写库，可脱机单测。
    """
    node_status = str(getattr(node_execution, "status", "") or "")
    session_status = str(getattr(session, "status", "") or "") if session is not None else ""
    has_artifact = bool(getattr(session, "current_artifact_version_id", None)) if session else False

    # 1) 失败相位优先（节点失败/超时，或会话失败）。
    if node_status in ("failed", "timeout") or session_status == "failed":
        rnd = answered_round_count or pending_round_no
        return LifecycleProjection(PHASE_FAILED, rnd or None, max_rounds)

    # 2) 审批闸门（gate）。
    if node_status == "waiting_approval":
        return LifecycleProjection(PHASE_WAITING_APPROVAL, None, max_rounds)

    # 3) 等待澄清（会话态优先，回退节点 waiting_input）。
    if session_status == "waiting_clarification" or node_status == "waiting_input":
        rnd = pending_round_no if pending_round_no else (answered_round_count + 1)
        return LifecycleProjection(PHASE_WAITING_CLARIFICATION, rnd or None, max_rounds)

    # 4) 完成 → 已产出 / 已完成。
    if node_status == "completed":
        phase = PHASE_PRODUCED if (session_status == "done" or has_artifact) else PHASE_DONE
        return LifecycleProjection(phase, None, max_rounds)
    if session_status == "done":
        return LifecycleProjection(PHASE_PRODUCED, None, max_rounds)

    # 5) 运行族（running / 等待外部事件回调）→ 修订中 or 运行中。
    if node_status in ("running", "waiting_event"):
        if answered_round_count >= 1:
            return LifecycleProjection(PHASE_REVISING, answered_round_count, max_rounds)
        return LifecycleProjection(PHASE_RUNNING, None, max_rounds)

    # 6) 其余（pending/queued/skipped/cancelled/未知）→ 待运行。
    return LifecycleProjection(PHASE_IDLE, None, max_rounds)


async def aproject_node_lifecycle(
    node_execution: Any,
    *,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
) -> LifecycleProjection | None:
    """best-effort 异步收集器：查关联 session + 澄清轮次后调用纯函数投影。

    任何异常/缺依赖均返回 ``None``（调用方据此跳过 lifecycle 补字段）；
    **绝不反噬主流程**（observability 红线）。
    """
    try:
        ne_id = getattr(node_execution, "id", None)
        if ne_id is None:
            return None

        # 软关联：ConvergenceSession.node_execution_id == NodeExecution.id（UUID）。
        from delivery.models import ConvergenceSession

        session = (
            await ConvergenceSession.objects.filter(node_execution_id=ne_id)
            .order_by("-created_at")
            .afirst()
        )

        pending_round_no: int | None = None
        answered_round_count = 0
        if session is not None:
            from delivery.models import Clarification

            pending = (
                await Clarification.objects.filter(session=session, answered_at__isnull=True)
                .order_by("-round_no", "-created_at")
                .afirst()
            )
            if pending is not None:
                pending_round_no = pending.round_no
            answered_round_count = await Clarification.objects.filter(
                session=session, answered_at__isnull=False
            ).acount()

        return project_node_lifecycle(
            node_execution,
            session=session,
            pending_round_no=pending_round_no,
            answered_round_count=answered_round_count,
            max_rounds=max_rounds,
        )
    except Exception:  # noqa: BLE001 — 投影 best-effort，绝不反噬主流程
        logger.debug(
            "lifecycle_projection_failed",
            component="lifecycle_projection",
            category="sampling",
            exc_info=True,
        )
        return None
