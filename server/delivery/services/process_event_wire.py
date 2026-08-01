"""编排事件**出网净化的唯一面**（Phase 110-01，OBS-01）。

SSE fan-out（`ConvergenceSessionService._fanout_process_event`）与运行时快照
（110-02 的 `orchestration` 节）两条出网链共用本模块这一把筛子。

**为什么必须共用**：前端按 `(event, ts, repo_id/task_id)` 去重，SSE 推来的那条与
快照补来的那条必须是**同一个对象**。若两条链各自净化，同一事件在两条链上会呈现出
不同的键集合，去重键算出来不一致，同一件事会被数成两件。

**留痕面与出网面是两个面**：`ConvergenceSessionEvent.payload` 落库的仍是**未净化**
的原文（供 superuser 排障），本模块只管「往渲染路径上送什么」。这与 107-UI-SPEC
Unresolved #4 是同一条裁定。
"""

from __future__ import annotations

from typing import Any, Final

from common.logging import redact_secrets_in_text

__all__ = [
    "FAILURE_REASON_CODES",
    "FAILURE_REASON_STAGE_EXCEPTION",
    "FAILURE_REASON_UNKNOWN",
    "compress_failure_reason",
    "sanitize_process_event_payload",
]


# ---- 第一层：恒剥离（与值类型无关） ----
#
# 前四个是自由文本：`question` 是 LLM 产出的澄清问题、`message` 是 `str(exc)` 原文、
# `exception` 是异常类名、`report` 内含融合校验 `errors[].message`。
# 其余几个是排查材料或方案内容，都不是「进度」：
# - `reasons` 是校验 check 名（非受控取值），UI-SPEC §A.4 定的是「只计数不回显」，而融合
#   轮次实际由 `technical_plan.merge.started` 的**出现次数**数得 ⇒ 整键剥离不损失摘要能力；
# - `candidate_files` / `api_contracts_exposed` 是方案内容；
# - `stage0` / `stage1` / `weight_config` / `repo_meta` 是路由快照的回放材料；
# - `unclarified_points` 是澄清超时那条事件里的未答子题正文。
_ALWAYS_DROP: Final[frozenset[str]] = frozenset(
    {
        "question",
        "message",
        "exception",
        "report",
        "reasons",
        "candidate_files",
        "api_contracts_exposed",
        "stage0",
        "stage1",
        "weight_config",
        "repo_meta",
        "unclarified_points",
    }
)

# ---- 第二层：按值类型剥离 ----
#
# 🔴 这一层**不能**并进第一层。`technical_plan.feature.classified` 的 `summary` 是结构化
# dict `{new, modify, unclear}`，是「功能点分类」那一步摘要的**唯一**来源；而
# `repo.research.completed` 的 `summary` 是容器产出的自由文本。同名不同义 ⇒ 按值类型
# 区分是唯一不误伤的判据。`error` 同理（`repo.research.failed.error` 是字符串异常文本，
# 而 session 级 `error` 是结构化 dict）。
_DROP_IF_STR: Final[frozenset[str]] = frozenset({"summary", "error", "detail"})

# ---- 第三层：残留字符串兜底 ----
#
# 保留下来的 str 一律过 `redact_secrets_in_text` 并截断。这一层保护的是**未知事件**——
# 后端将来新增事件而上面两张表没同步时，凭据仍不会出网。
_MAX_STR_LEN: Final[int] = 200

# 走多深：顶层键 + `list[dict]` 型值内的一层（覆盖 `repo.routing.candidates[]`）。
# 不做无限递归——payload 是受控结构，无限递归只带来性能与栈深度的不确定性。
_MAX_WALK_DEPTH: Final[int] = 2


# ---- 失败原因闭集（UI-SPEC §B.2 的 7 值表，前端那份中文文案表是另一侧） ----

FAILURE_REASON_STAGE_EXCEPTION: Final[str] = "stage_exception"
FAILURE_REASON_UNKNOWN: Final[str] = "unknown"

FAILURE_REASON_CODES: Final[frozenset[str]] = frozenset(
    {
        FAILURE_REASON_STAGE_EXCEPTION,
        "merge_validation_exhausted",
        "clarification_timeout_no_answer",
        "advance_step_limit",
        "unknown_process_type",
        "unknown_stage",
        FAILURE_REASON_UNKNOWN,
    }
)


def sanitize_process_event_payload(payload: dict | None) -> dict:
    """把编排事件 payload 净化成**可出网**的形状（自由文本在服务端即消失）。

    非 dict / None ⇒ 返回 ``{}``（不抛：本函数在 best-effort 出网路径上）。
    """
    if not isinstance(payload, dict):
        return {}
    return _strip_and_walk(payload, depth=0)


def _strip_and_walk(mapping: dict, *, depth: int) -> dict:
    """本层做键剥离（两张表）+ 逐值下探。"""
    out: dict[str, Any] = {}
    for key, value in mapping.items():
        if key in _ALWAYS_DROP:
            continue
        if key in _DROP_IF_STR and isinstance(value, str):
            continue
        out[key] = _walk_value(value, depth=depth)
    return out


def _walk_value(value: Any, *, depth: int) -> Any:
    """字符串兜底 + 有界下探（键剥离只发生在顶层与 ``list[dict]`` 元素上）。"""
    if isinstance(value, str):
        return _redact_and_truncate(value)
    if depth >= _MAX_WALK_DEPTH:
        return value
    if isinstance(value, list):
        return [
            _strip_and_walk(item, depth=depth + 1)
            if isinstance(item, dict)
            else _walk_value(item, depth=depth + 1)
            for item in value
        ]
    if isinstance(value, dict):
        # dict 型值只做字符串兜底、**不做键剥离**——否则 classify 的结构化 `summary`
        # 与路由候选的 `breakdown` 这类受控结构会被表里的同名键误伤。
        return {k: _walk_value(v, depth=depth + 1) for k, v in value.items()}
    return value


def _redact_and_truncate(text: str) -> str:
    redacted = redact_secrets_in_text(text)
    if len(redacted) > _MAX_STR_LEN:
        return redacted[: _MAX_STR_LEN - 1] + "…"
    return redacted


def compress_failure_reason(error: Any) -> str:
    """把 ``ConvergenceSession.error`` 压成闭集 ``reason_code``（UI-SPEC 后端契约要求 #4）。

    返回值恒 ∈ :data:`FAILURE_REASON_CODES`。🔴 本函数**只返回枚举值**——绝不返回、
    拼接或透出 ``error`` 里的任何原始字符串（`message` / `exception` / `report` 是
    异常原文与校验报告，回显即泄漏面）。

    压制规则（落点实读见 UI-SPEC §落点 D 的六种形状表）：

    - 非 dict ⇒ ``unknown``；
    - ``reason`` 在闭集内 ⇒ 直取；在闭集外 ⇒ ``unknown``（绝不回显未受控取值）；
    - 无 ``reason`` 但有 ``exception`` 键 ⇒ ``stage_exception``（``engine.py`` 的
      stage 内未捕获异常，是最常见的一条路径，它不写 ``reason``）；
    - 其余 ⇒ ``unknown``。
    """
    if not isinstance(error, dict):
        return FAILURE_REASON_UNKNOWN
    reason = error.get("reason")
    if isinstance(reason, str) and reason in FAILURE_REASON_CODES:
        return reason
    if reason is not None:
        return FAILURE_REASON_UNKNOWN
    if "exception" in error:
        return FAILURE_REASON_STAGE_EXCEPTION
    return FAILURE_REASON_UNKNOWN
