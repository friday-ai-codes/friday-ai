"""ReactionDispatchHook（Chassis v2 · P0）。

把 workflow lifecycle hook 事件投影成 ``Signal``，再交给 ``ReactionRuntime``
幂等分发横切反应。挂在既有 HookManager 上，与 Logging/WebSocket/AlertRule 等
横切观察者并列；执行用 ``create_task`` 后台运行，**绝不阻塞主交付链路**。
"""

import asyncio
from typing import Any

import structlog

from workflows.hooks.base import BaseHook
from workflows.reactions import runtime as reaction_runtime
from workflows.reactions.signal import project_from_hook

logger = structlog.get_logger(__name__)


class ReactionDispatchHook(BaseHook):
    """生命周期事件 → Signal 投影 → 幂等 Reaction 分发。"""

    priority = 40  # 在 AlertRuleHook(30) 之后、Notification(50) 之前

    async def execute(self, event: str, **kwargs: Any) -> None:
        execution = kwargs.get("execution")
        if execution is None:
            return
        if getattr(execution, "is_debug", False):
            return

        try:
            signals = project_from_hook(
                event,
                execution=execution,
                node_execution=kwargs.get("node_execution"),
            )
        except Exception:  # noqa: BLE001 — 投影失败不反噬主流程
            logger.warning(
                "reaction_projection_failed",
                component="reaction_runtime",
                category="caller",
                workflow_event=event,
                exc_info=True,
            )
            return

        for signal in signals:
            # 后台分发，避免横切副作用阻塞 hook 链 / 主交付（non_blocking）。
            asyncio.create_task(self._safe_dispatch(signal, execution))

    @staticmethod
    async def _safe_dispatch(signal: Any, execution: Any) -> None:
        try:
            await reaction_runtime.dispatch(signal, execution)
        except Exception:  # noqa: BLE001 — best-effort
            logger.warning(
                "reaction_dispatch_failed",
                component="reaction_runtime",
                category="caller",
                signal=getattr(signal, "name", ""),
                exc_info=True,
            )
