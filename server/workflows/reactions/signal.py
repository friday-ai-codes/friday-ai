"""Lifecycle Signal 投影层（Chassis v2 · P0）。

``Signal`` 是对既有事实源（workflow lifecycle hook、process event、artifact
transition）的**归一化投影**——稳定、对用户可见的语义。它不是新的事件表，
不持久化；reaction matcher 消费投影后的 Signal。

设计见 `.planning/WORKFLOW-RUNTIME-SPEC.md` §Signal。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from django.utils import timezone

# ---- 稳定信号词表（普通用户只接触这几类语义） -------------------------------

# 节点生命周期
SIG_NODE_STARTED = "node.started"
SIG_NODE_COMPLETED = "node.completed"
SIG_NODE_FAILED = "node.failed"
SIG_NODE_WAITING = "node.waiting"

# 流程（AI 收敛过程）
SIG_PROCESS_STAGE_CHANGED = "process.stage_changed"
SIG_PROCESS_FAILED = "process.failed"
SIG_CLARIFICATION_ASKED = "clarification.asked"
SIG_CLARIFICATION_ANSWERED = "clarification.answered"

# artifact
SIG_ARTIFACT_PRODUCED = "artifact.produced"
SIG_ARTIFACT_SUPERSEDED = "artifact.superseded"
SIG_ARTIFACT_APPROVED = "artifact.approved"

# 审批
SIG_APPROVAL_REQUESTED = "approval.requested"
SIG_APPROVAL_GRANTED = "approval.granted"
SIG_APPROVAL_REJECTED = "approval.rejected"

SIGNAL_NAMES: frozenset[str] = frozenset(
    {
        SIG_NODE_STARTED,
        SIG_NODE_COMPLETED,
        SIG_NODE_FAILED,
        SIG_NODE_WAITING,
        SIG_PROCESS_STAGE_CHANGED,
        SIG_PROCESS_FAILED,
        SIG_CLARIFICATION_ASKED,
        SIG_CLARIFICATION_ANSWERED,
        SIG_ARTIFACT_PRODUCED,
        SIG_ARTIFACT_SUPERSEDED,
        SIG_ARTIFACT_APPROVED,
        SIG_APPROVAL_REQUESTED,
        SIG_APPROVAL_GRANTED,
        SIG_APPROVAL_REJECTED,
    }
)

# Signal scope（主体类型）
SCOPE_WORKFLOW_EXECUTION = "workflow_execution"
SCOPE_NODE_EXECUTION = "node_execution"
SCOPE_PROCESS_SESSION = "process_session"
SCOPE_ARTIFACT = "artifact"

# Signal source（投影来源）
SOURCE_WORKFLOW_HOOK = "workflow_hook"
SOURCE_PROCESS_EVENT = "process_event"
SOURCE_ARTIFACT_TRANSITION = "artifact_transition"


@dataclass(frozen=True)
class Signal:
    """归一化生命周期信号（值对象，不持久化）。"""

    name: str
    scope: str
    subject_id: str
    source: str
    payload: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=timezone.now)


# workflow lifecycle hook 事件名 → 信号名（一个 hook 事件可投影出多个信号）。
_HOOK_EVENT_TO_SIGNALS: dict[str, tuple[str, ...]] = {
    "node_started": (SIG_NODE_STARTED,),
    "node_completed": (SIG_NODE_COMPLETED,),
    "node_failed": (SIG_NODE_FAILED,),
    "node_skipped": (),  # skip 不产生信号（语义上不是失败也不是完成）
    "node_waiting_approval": (SIG_NODE_WAITING, SIG_APPROVAL_REQUESTED),
    "node_waiting_event": (SIG_NODE_WAITING,),
    "node_approved": (SIG_APPROVAL_GRANTED,),
    "node_rejected": (SIG_APPROVAL_REJECTED,),
}


def project_from_hook(
    event_name: str,
    *,
    execution: Any | None = None,
    node_execution: Any | None = None,
) -> list[Signal]:
    """把一次 workflow lifecycle hook 事件投影成 0..N 个 Signal（纯函数）。

    - 节点类信号 scope=node_execution，subject_id=宿主 WorkflowNode id（便于
      按 host_node 匹配 reaction）。
    - payload 仅含受控、非敏感字段（execution_id / node_status / error_code）。
    """
    names = _HOOK_EVENT_TO_SIGNALS.get(event_name)
    if not names:
        return []

    execution_id = str(getattr(execution, "id", "")) if execution is not None else ""
    occurred = timezone.now()

    signals: list[Signal] = []
    if node_execution is not None:
        node_id = str(getattr(node_execution, "node_id", "") or "")
        node_status = getattr(node_execution, "status", "") or ""
        payload: dict[str, Any] = {
            "execution_id": execution_id,
            "node_execution_id": str(getattr(node_execution, "id", "") or ""),
            "node_id": node_id,
            "node_status": node_status,
        }
        # 失败态附带错误码（受控字段；error_message 不进 payload 防泄漏）。
        error_code = getattr(node_execution, "error_code", None)
        if error_code:
            payload["error_code"] = error_code
        for name in names:
            scope = (
                SCOPE_NODE_EXECUTION
                if name.startswith("node.") or name.startswith("approval.")
                else SCOPE_WORKFLOW_EXECUTION
            )
            subject = node_id if scope == SCOPE_NODE_EXECUTION else execution_id
            signals.append(
                Signal(
                    name=name,
                    scope=scope,
                    subject_id=subject,
                    source=SOURCE_WORKFLOW_HOOK,
                    payload=payload,
                    occurred_at=occurred,
                )
            )
    else:
        # 无 node_execution 的事件（execution_*）暂不投影为信号（P0 范围）。
        return []

    return signals
