"""§15 emit 点常量引用 + 38/39/40 漂移对齐守护测试（EVENT-01，41-01 Task 3）。

守护三件事：
1. **无裸字面量**：各 emit 点（``_emit_event(`` / architect ``self._emit(``）首事件参数
   不再是裸字符串字面量——应为 ``EVENT_*`` 常量引用（消除字符串漂移）。
2. **对齐 §15**：所有被引用的 ``EVENT_*`` 常量值 ∈ ``ALL_EVENTS``。
3. **覆盖性反查**：``ALL_EVENTS`` 中每个 v0.7 编排事件名在其 producer 文件中至少被一个
   emit 点产出（producer 文件按 phase 渐次落地——文件不存在时跳过，保子计划顺序安全）。
"""

from __future__ import annotations

import re
from pathlib import Path

import delivery.services.event_taxonomy as taxonomy
from delivery.services import ALL_EVENTS

_SERVER_ROOT = Path(__file__).resolve().parents[2]

# emit 点源文件（38/39/40/41 实际产出 §15 事件的位置）
_ENGINE = _SERVER_ROOT / "services" / "process_runtime" / "engine.py"
_RESEARCH_ADAPTER = _SERVER_ROOT / "services" / "process_runtime" / "research_adapter.py"
_ARCHITECT_ADAPTER = _SERVER_ROOT / "services" / "process_runtime" / "architect_merge_adapter.py"
_CALLBACKS = _SERVER_ROOT / "subagent" / "api" / "callbacks.py"
_SESSION_SERVICE = _SERVER_ROOT / "delivery" / "services" / "convergence_session_service.py"
# 41-02 落地后存在（顺序安全：缺失时覆盖检查跳过对应事件）
_CLARIFY_ADAPTER = _SERVER_ROOT / "services" / "process_runtime" / "clarify_adapter.py"
_CLARIFICATION_SERVICE = _SERVER_ROOT / "delivery" / "services" / "clarification_service.py"
# Phase 49 落地后存在（spec.drafted producer）
_SPEC_GENERATION = _SERVER_ROOT / "services" / "process_runtime" / "spec_generation.py"
# Chassis v2：generic ProcessEngine 不再直接 emit stage 事件，recall/route 落到 stage 处理器
_BUILTIN_PROCESSES = _SERVER_ROOT / "services" / "process_runtime" / "builtin_processes.py"

_EMIT_FILES = [
    _ENGINE,
    _RESEARCH_ADAPTER,
    _ARCHITECT_ADAPTER,
    _CALLBACKS,
    _SESSION_SERVICE,
    _CLARIFY_ADAPTER,
    _CLARIFICATION_SERVICE,
    _SPEC_GENERATION,
]

# 事件 → 其 producer 源文件（覆盖性反查；文件不存在 → 跳过该事件，顺序安全）
_EVENT_PRODUCERS: dict[str, Path] = {
    "knowledge.recalling": _BUILTIN_PROCESSES,
    "repo.routing": _BUILTIN_PROCESSES,
    "technical_plan.feature.classified": _BUILTIN_PROCESSES,
    "repo.research.started": _RESEARCH_ADAPTER,
    "repo.research.failed": _RESEARCH_ADAPTER,
    "repo.research.completed": _CALLBACKS,
    "technical_plan.merge.started": _ARCHITECT_ADAPTER,
    "technical_plan.merge.completed": _ARCHITECT_ADAPTER,
    "technical_plan.validation.failed": _ARCHITECT_ADAPTER,
    "process.session.failed": _SESSION_SERVICE,
    "clarification.asked": _CLARIFY_ADAPTER,
    "clarification.answered": _CLARIFICATION_SERVICE,
    "spec.drafted": _SPEC_GENERATION,
}

# emit 调用：捕获事件参数（_emit_event 首参 / architect _emit 第二参）
_EMIT_EVENT_CALL = re.compile(r"_emit_event\(\s*([^,\s]+)")
_EMIT_WRAPPER_CALL = re.compile(r"self\._emit\(\s*session\s*,\s*([^,\s]+)")


def _scrubbed_source(text: str) -> str:
    """剔除注释行与 ``def _emit_event`` 定义行后拼回（支持跨行 emit 调用匹配）。"""
    kept = [
        ln
        for ln in text.splitlines()
        if not ln.lstrip().startswith("#") and "def _emit_event" not in ln
    ]
    return "\n".join(kept)


def _emit_arg_tokens(path: Path) -> list[str]:
    """提取该文件所有 emit 调用的事件参数 token（排除 def 定义行与注释行；支持跨行调用）。"""
    source = _scrubbed_source(path.read_text(encoding="utf-8"))
    tokens: list[str] = []
    for m in _EMIT_EVENT_CALL.finditer(source):
        tokens.append(m.group(1))
    for m in _EMIT_WRAPPER_CALL.finditer(source):
        tokens.append(m.group(1))
    return tokens


def test_no_bare_string_literal_at_emit_sites() -> None:
    """所有 emit 点事件参数不是裸字符串字面量（应为 EVENT_* 常量或 event/event_name 变量）。"""
    allowed_vars = {"event", "event_name"}
    for path in _EMIT_FILES:
        if not path.exists():
            continue
        for token in _emit_arg_tokens(path):
            assert not (token.startswith('"') or token.startswith("'")), (
                f"{path.name} 的 emit 点出现裸字符串字面量 {token!r}，应引用 EVENT_* 常量"
            )
            assert token.startswith("EVENT_") or token in allowed_vars, (
                f"{path.name} 的 emit 点事件参数 {token!r} 非 EVENT_* 常量/合法变量"
            )


def test_referenced_constants_in_all_events() -> None:
    """所有 emit 点引用的 EVENT_* 常量值 ∈ ALL_EVENTS（§15 对齐，无漂移）。"""
    referenced: set[str] = set()
    for path in _EMIT_FILES:
        if not path.exists():
            continue
        for token in _emit_arg_tokens(path):
            if token.startswith("EVENT_"):
                value = getattr(taxonomy, token, None)
                assert value is not None, f"{path.name} 引用未定义常量 {token}"
                referenced.add(value)
    assert referenced, "未扫描到任何 EVENT_* 引用"
    assert referenced <= set(ALL_EVENTS), (
        f"emit 点引用了 ALL_EVENTS 之外的事件：{referenced - set(ALL_EVENTS)}"
    )


def test_all_events_each_emitted_by_producer() -> None:
    """覆盖性反查：ALL_EVENTS 每个事件在其 producer 文件中至少被一个 emit 点产出。

    producer 文件按 phase 渐次落地——文件不存在时跳过该事件（子计划顺序安全）。
    """
    # 值 → 常量名（便于在源码里查引用）
    value_to_const = {
        getattr(taxonomy, name): name
        for name in dir(taxonomy)
        if name.startswith("EVENT_")
    }
    for event in ALL_EVENTS:
        producer = _EVENT_PRODUCERS.get(event)
        assert producer is not None, f"ALL_EVENTS 事件 {event} 未登记 producer"
        if not producer.exists():
            continue  # 顺序安全：producer 尚未落地（如 41-02 clarify）
        const_name = value_to_const[event]
        tokens = _emit_arg_tokens(producer)
        assert const_name in tokens, (
            f"§15 事件 {event}（{const_name}）未在 producer {producer.name} 的 emit 点产出"
        )
