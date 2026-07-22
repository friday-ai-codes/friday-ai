"""Skill executor: sequentially executes a list of tool steps.

步级 trace（LOOP-04 / 101-04）：

- 每步产结构化事件三态 ``skill_step_started`` / ``skill_step_completed`` /
  ``skill_step_failed``（kv 含 skill/step/step_tool/ok/duration_ms，
  ``category="caller"``——skill 是用户显式调用链）；
- ``run`` 非 None 时每步写一条 ``ToolCallRecord``（``arecord_tool_call``，
  tool_name = ``{skill}#{i}:{step}``，入库前 ledger 自带 redact_for_ledger 脱敏）；
  整段 try/except 吞——观测绝不反噬主流程。

步骤参数（CONTEXT 最小实现）：**顶层 arguments 透传合并进每步、步内静态
arguments 优先**（``{**arguments, **step_args}``）。首败中断语义与返回形状
``list[dict]`` 不变（零回归）。
"""

import time
from typing import TYPE_CHECKING, Any

import structlog

from tools.models import RemoteTool

if TYPE_CHECKING:
    from interactions.models import InteractionRun

logger = structlog.get_logger(__name__)


async def execute_skill(
    tool: RemoteTool,
    arguments: dict[str, Any],
    run: "InteractionRun | None" = None,
) -> list[dict[str, Any]]:
    """Execute skill steps sequentially. Aborts on first failure.

    Args:
        tool: skill 类型的 RemoteTool（``config["steps"]`` 为步骤列表）。
        arguments: 顶层入参，透传合并进每步（步内静态 arguments 优先）。
        run: 顶层 InteractionRun（/api/tools/execute/ 链路传入）；非 None 时
            每步写步级 ToolCallRecord，None（内部调用）时只产结构化事件。
    """
    # Import here to avoid circular import (executor -> skill -> executor)
    from tools.executor import execute_tool

    steps: list[dict[str, Any]] = tool.config.get("steps", [])
    results: list[dict[str, Any]] = []

    for i, step in enumerate(steps):
        step_name: str = step["tool_name"]
        step_args: dict[str, Any] = step.get("arguments", {})
        # 顶层输入透传：步内静态 arguments 优先（migration 0005 docstring 同款语义）。
        effective_args: dict[str, Any] = {**arguments, **step_args}
        logger.info(
            "skill_step_started",
            skill=tool.name,
            step=i,
            step_tool=step_name,
            category="caller",
            component="tools",
        )
        started = time.perf_counter()

        result = await execute_tool(step_name, effective_args)
        duration_ms = max(int((time.perf_counter() - started) * 1000), 0)
        ok = bool(result.get("ok"))
        results.append(result)

        if ok:
            logger.info(
                "skill_step_completed",
                skill=tool.name,
                step=i,
                step_tool=step_name,
                ok=True,
                duration_ms=duration_ms,
                category="caller",
                component="tools",
            )
        else:
            logger.warning(
                "skill_step_failed",
                skill=tool.name,
                step=i,
                step_tool=step_name,
                ok=False,
                duration_ms=duration_ms,
                category="caller",
                component="tools",
            )

        # 步级 ledger（run 可用时）：arecord_tool_call 入库前自带 redact_for_ledger
        # 脱敏；整段吞异常——观测 best-effort，绝不反噬 skill 主流程。
        if run is not None:
            try:
                from interactions.ledger import arecord_tool_call

                await arecord_tool_call(
                    run,
                    tool_name=f"{tool.name}#{i}:{step_name}",
                    input=effective_args,
                    output=result,
                    status="ok" if ok else "error",
                    duration_ms=duration_ms,
                    error="" if ok else str(result.get("error") or {}),
                )
            except Exception:  # noqa: BLE001, S110 — 步级留痕绝不反噬主流程
                pass

        if not ok:
            break

    return results
