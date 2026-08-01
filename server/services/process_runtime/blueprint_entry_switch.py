"""per-entry 运行时开关：四个入口各自选 technical_plan / technical_blueprint（Phase 116-01）。

**用途**：`workflow` / `chat` / `mcp` / `feature_list` 四个入口的下游成熟度不同，切链不能是
一次全局硬切。本模块读 `blueprint.entry.switch` 设置键，让每个入口**各自独立**决定建哪条
process；回滚因此是「改一个设置值」而不是「回滚一次发布」。默认四键全 `technical_plan`
（安全默认：不配置 = 行为与切换前逐字一致）。

**纪律（本模块存在的首要理由）**：``entry`` 必须由调用方按自己的**静态身份**传字面量常量，
⛔ **绝不从 ``session.entrypoint`` 反推**。MCP 入口给 ``start_orchestration`` 传的
``entrypoint`` 实测是 ``"workflow"``（``mcp_tools/orchestration_delegate.py:171-178``，该文件
``:4`` / ``:131`` 的 docstring 逐字写明这是既有约定而不是笔误）⇒ 写成
``switch[session.entrypoint]`` 会让「只打开 workflow 键」把 MCP 一起切走，正是 per-entry
想避免的相反面。该纪律由
``tests/services/process_runtime/test_blueprint_entry_switch.py`` 的 ``ast`` 源码扫描强制
（实参必须是 ``ast.Constant``），并配一条「守护的守护」证明扫描器非平凡。

同理，四个 ``ENTRY_*`` 常量**只作 :data:`ENTRY_KEYS` 的构成与测试参数化用**；调用点一律
写字面量（``ast.Name`` 会被扫描器判违规），⛔ 不要在任何调用点 import 它们。

**观测**：⛔ 本模块不出现任何 ``error`` 实参（连字面形态都不出现，扫描是正则）—— 它刻意**不**进
``tests/delivery/test_blueprint_log_redaction_guard.py`` 的 ``_SCANNED_MODULES``（与 analog
``blueprint_ambiguity_score.py`` 同口径），代价就是异常文本一律不进日志：兜底分支只记事件名
与 ``entry`` / ``reason`` / ``value`` 三个标量。埋点全经 :func:`_safe_log`，观测 best-effort，
绝不反噬编排主流程。
"""

from __future__ import annotations

import copy
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

__all__ = [
    "DEFAULT_ENTRY_SWITCH",
    "ENTRY_CHAT",
    "ENTRY_FEATURE_LIST",
    "ENTRY_KEYS",
    "ENTRY_MCP",
    "ENTRY_WORKFLOW",
    "PROCESS_TECHNICAL_BLUEPRINT",
    "PROCESS_TECHNICAL_PLAN",
    "aresolve_entry_process_type",
]

# 四个入口的静态身份（⚠️ 只作 ENTRY_KEYS 的构成与测试参数化用，见模块 docstring 纪律段）。
ENTRY_WORKFLOW = "workflow"
ENTRY_CHAT = "chat"
ENTRY_MCP = "mcp"
ENTRY_FEATURE_LIST = "feature_list"
ENTRY_KEYS: tuple[str, ...] = (ENTRY_WORKFLOW, ENTRY_CHAT, ENTRY_MCP, ENTRY_FEATURE_LIST)

PROCESS_TECHNICAL_PLAN = "technical_plan"
PROCESS_TECHNICAL_BLUEPRINT = "technical_blueprint"
_ALLOWED_PROCESS_TYPES = frozenset({PROCESS_TECHNICAL_PLAN, PROCESS_TECHNICAL_BLUEPRINT})

# ⭐ 默认四键全旧链：不配置 = 与切换前逐字等价（安全默认）。
DEFAULT_ENTRY_SWITCH: dict[str, str] = {
    ENTRY_WORKFLOW: PROCESS_TECHNICAL_PLAN,
    ENTRY_CHAT: PROCESS_TECHNICAL_PLAN,
    ENTRY_MCP: PROCESS_TECHNICAL_PLAN,
    ENTRY_FEATURE_LIST: PROCESS_TECHNICAL_PLAN,
}


def _safe_log(event: str, **fields: Any) -> None:
    """best-effort 结构化埋点（观测失败吞掉，绝不反噬业务）。

    ⛔ 调用方不得传 ``error`` 实参（见模块 docstring 的观测段）。
    """
    try:
        logger.warning(event, **fields)
    except Exception:  # noqa: BLE001 — 观测 best-effort
        pass


async def aresolve_entry_process_type(entry: str) -> str:
    """按入口的**字面量**身份解析该建哪条 process（畸形/未配置一律回旧链）。

    ⛔ ``entry`` 绝不从 ``session.entrypoint`` 反推（见模块 docstring 纪律段）——调用方按
    自己的静态身份传 ``"workflow"`` / ``"chat"`` / ``"mcp"`` / ``"feature_list"`` 字面量。

    三层 fail-soft（形状照 ``blueprint_ambiguity_score.aload_spec_gate_config:239-268``）：

    1. ``entry`` 不在 :data:`ENTRY_KEYS` ⇒ 回 ``technical_plan`` + 一条 caller 事件。
    2. 读设置整段异常 ⇒ 回 ``technical_plan`` + 一条 sampling 事件（⛔ 不带异常文本）。
    3. ⚠️ ``aget_json_setting`` **只保证外层是 dict、内层不校验**
       （``system/settings_service.py:139-153``）⇒ 逐键 ``str()`` 强转，值不在
       ``{technical_plan, technical_blueprint}`` 内一律回落 ``technical_plan``。
    """
    entry = str(entry or "")
    if entry not in ENTRY_KEYS:
        _safe_log(
            "blueprint_entry_switch_unknown_entry",
            category="caller",
            component="process_runtime",
            entry=entry,
        )
        return PROCESS_TECHNICAL_PLAN

    fallback = copy.deepcopy(DEFAULT_ENTRY_SWITCH)
    try:
        # 懒 import：process_runtime 不在模块级依赖 system（与 analog 同口径）。
        from system.models import SettingKeys
        from system.settings_service import aget_json_setting

        raw = await aget_json_setting(SettingKeys.BLUEPRINT_ENTRY_SWITCH, fallback)
    except Exception:  # noqa: BLE001 — 配置读取绝不反噬编排主流程
        _safe_log(
            "blueprint_entry_switch_load_failed",
            category="sampling",
            component="process_runtime",
            entry=entry,
            reason="load_failed",
        )
        return PROCESS_TECHNICAL_PLAN

    if not isinstance(raw, dict):
        return PROCESS_TECHNICAL_PLAN
    value = str(raw.get(entry) or "")
    if value not in _ALLOWED_PROCESS_TYPES:
        _safe_log(
            "blueprint_entry_switch_invalid_value",
            category="sampling",
            component="process_runtime",
            entry=entry,
            value=value,
        )
        return PROCESS_TECHNICAL_PLAN
    return value
