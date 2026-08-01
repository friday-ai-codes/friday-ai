"""per-entry 运行时开关：四个入口各自选 technical_plan / technical_blueprint（Phase 116-01）。

**用途**：`workflow` / `chat` / `mcp` / `feature_list` 四个入口的下游成熟度不同，切链不能是
一次全局硬切。本模块读 `blueprint.entry.switch` 设置键，让每个入口**各自独立**决定建哪条
process；回滚因此是「改一个设置值」而不是「回滚一次发布」。

⭐ **默认已翻至 `technical_blueprint`（同步点 2 收尾）**。116-01 落地时默认四键全
`technical_plan`，那是「三道消费方接缝（G1/G3/G4）与终态映射都还是错的」时期的安全默认；
接缝修好之后再留着它，等于让全部生产流量继续走一条**已退役**的链。翻默认之后：

- **回滚仍是改一个设置值**：把 `blueprint.entry.switch` 的某个键置成 `"technical_plan"`
  即可单入口回退，⛔ 不需要发布。开关机制本身一字未动。
- 旧 process **仍保留注册**（在途会话续驱依赖它），只是不再是任何入口的默认；
  退役标记见 `builtin_processes.py` 的 `TECHNICAL_PLAN_RETIREMENT`。

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

# ⭐ 默认四键全**蓝图链**（同步点 2 收尾翻的就是这四行）：不配置 = 走 technical_blueprint。
#
# 翻默认的前提条件在同步点 2 才具备：G1（workflow 每次澄清判死）/ G3（MCP 主载荷恒空）/
# G4（feature_list 永久 researching）三道消费方接缝与终态映射（未审蓝图不得进 ai_coding）
# 都修好了，翻开关才不会把它们直接暴露给第一次真实请求。
DEFAULT_ENTRY_SWITCH: dict[str, str] = {
    ENTRY_WORKFLOW: PROCESS_TECHNICAL_BLUEPRINT,
    ENTRY_CHAT: PROCESS_TECHNICAL_BLUEPRINT,
    ENTRY_MCP: PROCESS_TECHNICAL_BLUEPRINT,
    ENTRY_FEATURE_LIST: PROCESS_TECHNICAL_BLUEPRINT,
}


def _default_for(entry: str) -> str:
    """该入口的**声明默认值**（fail-soft 的统一落点）。

    ⭐ 三条 fail-soft 分支（读设置整段异常 / 外层非 dict / 内层值域外）此前**硬写**
    ``technical_plan``。那在默认值就是它的时候读起来一样，翻默认之后就不一样了：一次
    设置读取抖动、或运维把值敲错一个字母，都会静默把这一次请求送进**已退役**的旧链
    —— 「没有任何入口以它为默认」这条会在最不该出意外的降级路径上被悄悄破坏，
    而降级路径恰恰最少被人盯着。

    改为回落到 :data:`DEFAULT_ENTRY_SWITCH` 的该入口值：fail-soft 的语义本来就是
    「回落到默认」，只是当初默认与字面量恰好相同才被写死。

    ⚠️ **未知 entry 例外**（不在 :data:`ENTRY_KEYS` 内）：它不是入口，没有声明默认值，
    因此保留 ``technical_plan``。这类实参在生产不可达（``ast`` 扫描强制字面量常量），
    走到这里意味着调用方有 bug；把一个身份不明的调用方送进需要 ``project_id`` 的蓝图链
    只会换一种失败形态，而它**不构成「某个入口的默认」**，与退役这条不冲突。
    """
    return DEFAULT_ENTRY_SWITCH.get(entry, PROCESS_TECHNICAL_PLAN)


def _safe_log(event: str, **fields: Any) -> None:
    """best-effort 结构化埋点（观测失败吞掉，绝不反噬业务）。

    ⛔ 调用方不得传 ``error`` 实参（见模块 docstring 的观测段）。
    """
    try:
        logger.warning(event, **fields)
    except Exception:  # noqa: BLE001 — 观测 best-effort
        pass


async def aresolve_entry_process_type(entry: str) -> str:
    """按入口的**字面量**身份解析该建哪条 process（畸形/未配置一律回该入口的声明默认值）。

    ⛔ ``entry`` 绝不从 ``session.entrypoint`` 反推（见模块 docstring 纪律段）——调用方按
    自己的静态身份传 ``"workflow"`` / ``"chat"`` / ``"mcp"`` / ``"feature_list"`` 字面量。

    三层 fail-soft（形状照 ``blueprint_ambiguity_score.aload_spec_gate_config:239-268``），
    落点统一是 :func:`_default_for`（⛔ 不再硬写 ``technical_plan``，理由见那里）：

    1. ``entry`` 不在 :data:`ENTRY_KEYS` ⇒ 回旧链 + 一条 caller 事件（唯一的例外分支）。
    2. 读设置整段异常 ⇒ 回该入口默认 + 一条 sampling 事件（⛔ 不带异常文本）。
    3. ⚠️ ``aget_json_setting`` **只保证外层是 dict、内层不校验**
       （``system/settings_service.py:139-153``）⇒ 逐键 ``str()`` 强转，值不在
       ``{technical_plan, technical_blueprint}`` 内一律回落该入口默认。

    ⭐ **运维回滚面未变**：把设置里某个键置成合法字面量 ``"technical_plan"`` 仍然精确、
    单入口地回退（那条走的是正路第 4 步，不是 fail-soft）。
    """
    entry = str(entry or "")
    if entry not in ENTRY_KEYS:
        _safe_log(
            "blueprint_entry_switch_unknown_entry",
            category="caller",
            component="process_runtime",
            entry=entry,
        )
        return _default_for(entry)

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
        return _default_for(entry)

    if not isinstance(raw, dict):
        return _default_for(entry)

    # ⭐ **该键缺席 ≠ 配置非法**（翻默认后这条差别才显现出来）：``aget_json_setting`` 原样
    # 回落库的那个 dict，**不与默认值做合并** ⇒ 运维只写要 override 的那一两个键（正常做法）
    # 时，其余入口在这里读到的就是「没有这个键」。
    #
    # 两个后果，都必须在这一档处理掉：
    # 1. ⛔ 不能落 ``invalid_value`` 事件 —— 那会让每一次未配置入口的编排都刷一条 warning，
    #    把绝大多数正常请求渲染成异常；
    # 2. ⛔ 回落**必须**是该入口的默认，⛔ 不是硬写旧链 —— 否则写一个
    #    ``{"mcp": "technical_plan"}`` 就把另外三个入口一起拖回旧链，per-entry 独立性当场失效。
    #    这条由 ``test_per_entry_rollback_only_affects_the_configured_entry`` 反向锁死。
    if raw.get(entry) is None:
        return _default_for(entry)

    value = str(raw.get(entry) or "")
    if value not in _ALLOWED_PROCESS_TYPES:
        _safe_log(
            "blueprint_entry_switch_invalid_value",
            category="sampling",
            component="process_runtime",
            entry=entry,
            value=value,
        )
        return _default_for(entry)
    return value
