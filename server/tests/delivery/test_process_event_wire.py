"""编排事件出网净化筛子与失败原因闭集单测（Phase 110-01，OBS-01）。

覆盖：
- 逐事件净化形状（`repo.routing` / `clarification.asked` / `repo.research.failed`）；
- 🔴 同名不同义对照：classify 的**结构化** `summary`（dict）保留 / research 的**自由文本**
  `summary`（str）剥离——这一对是 `_DROP_IF_STR` 不能并进 `_ALWAYS_DROP` 的回归锁；
- 全事件守护：遍历 `event_taxonomy.ALL_EVENTS`，任何事件都不得把禁词键带出网；
- 未知事件的凭据兜底（剥离表没同步时的最后一道）；
- `compress_failure_reason` 的闭集性 —— 六种 error 形状都不得泄漏原始文本。
"""

from __future__ import annotations

import pytest

from delivery.services.event_taxonomy import (
    ALL_EVENTS,
    EVENT_CLARIFICATION_ASKED,
    EVENT_FEATURE_CLASSIFIED,
    EVENT_REPO_RESEARCH_COMPLETED,
    EVENT_REPO_RESEARCH_FAILED,
    EVENT_REPO_ROUTING,
)
from delivery.services.process_event_wire import (
    FAILURE_REASON_CODES,
    compress_failure_reason,
    sanitize_process_event_payload,
)

# 禁词键全集（守护测试用；与实现里的 `_ALWAYS_DROP` 逐字对齐，故意在测试侧重写一份，
# 让「实现改表」这个动作必须同时改测试，不能悄悄放行）。
FORBIDDEN_KEYS = frozenset(
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

# ≥20 字符，命中 common.logging.SENSITIVE_VALUE_PATTERN 的 `sk-` 分支
FAKE_CREDENTIAL = "sk-live-abcdefghijklmnopqrstuvwxyz0123456789"


# ============================ 逐事件净化形状 ============================


def test_repo_routing_snapshot_keeps_only_progress_fields() -> None:
    """`repo.routing` 完整快照净化后只剩进度字段；候选内的 breakdown 结构不被打散。"""
    payload = {
        "candidates": [
            {
                "repo_id": "r1",
                "confidence": "high",
                "score": 0.91,
                "breakdown": {"path": 0.4, "keyword": 0.3, "vector": 0.21},
            }
        ],
        "router_version": "v2",
        "degraded": False,
        "auto_selected": True,
        "versions": {"router": "v2", "weights": "w3"},
        # ↓ 排查材料，一律不出网
        "stage0": {"query": "原始需求文本"},
        "stage1": {"node_hits": [{"path": "a.py"}]},
        "weight_config": {"path": 0.4},
        "repo_meta": {"r1": {"lang": "python"}},
    }

    out = sanitize_process_event_payload(payload)

    assert set(out) == {
        "candidates",
        "router_version",
        "degraded",
        "auto_selected",
        "versions",
    }
    assert out["candidates"][0]["breakdown"] == {
        "path": 0.4,
        "keyword": 0.3,
        "vector": 0.21,
    }
    assert out["candidates"][0]["repo_id"] == "r1"


def test_classified_structured_summary_is_kept() -> None:
    """🔴 同名不同义（其一）：classify 的 `summary` 是 dict ⇒ **保留**。

    它是「功能点分类」那一步摘要的唯一来源；按键名一刀切会把它一并删掉。
    """
    out = sanitize_process_event_payload(
        {"summary": {"new": 1, "modify": 2, "unclear": 0}, "evidence_hits": 7}
    )

    assert out["summary"] == {"new": 1, "modify": 2, "unclear": 0}
    assert isinstance(out["summary"], dict)
    assert out["evidence_hits"] == 7


def test_research_freetext_summary_is_stripped() -> None:
    """🔴 同名不同义（其二）：research 的 `summary` 是自由文本 str ⇒ **剥离**，其余键保留。"""
    out = sanitize_process_event_payload(
        {"summary": "这里是容器产出的自由文本方案摘要", "repo_id": "r1", "task_id": "t1"}
    )

    assert "summary" not in out
    assert out["repo_id"] == "r1"
    assert out["task_id"] == "t1"


def test_clarification_asked_question_is_stripped() -> None:
    """`clarification.asked` 的 `question`（LLM 自由文本）剥离，`clarification_id` 保留。"""
    out = sanitize_process_event_payload(
        {"clarification_id": "c1", "question": "你希望改造哪个模块？"}
    )

    assert "question" not in out
    assert out["clarification_id"] == "c1"


def test_research_failed_error_stripped_but_dedup_keys_kept() -> None:
    """`repo.research.failed` 的 `error`（str）剥离；`repo_id` / `task_id` 保留。

    后两者是前端去重与「{done}/{total} 个仓库完成」计数的依据，不能一起删掉。
    """
    out = sanitize_process_event_payload(
        {"repo_id": "r1", "task_id": "t1", "error": "Traceback: ConnectionError(...)"}
    )

    assert "error" not in out
    assert out["repo_id"] == "r1"
    assert out["task_id"] == "t1"


# ============================ 全事件守护 ============================


@pytest.mark.parametrize("event_name", sorted(ALL_EVENTS))
def test_all_events_never_leak_forbidden_keys(event_name: str) -> None:
    """遍历 taxonomy 全集：塞满禁词键的 payload 净化后，禁词键一个都不剩。"""
    payload: dict = {key: f"{event_name}-{key}-自由文本" for key in FORBIDDEN_KEYS}
    payload.update({"summary": "自由文本摘要", "error": "异常原文", "detail": "细节原文"})
    payload["repo_id"] = "r1"

    out = sanitize_process_event_payload(payload)

    assert FORBIDDEN_KEYS.isdisjoint(out), f"{event_name} 泄漏了禁词键：{FORBIDDEN_KEYS & set(out)}"
    for key in ("summary", "error", "detail"):
        assert not isinstance(out.get(key), str), f"{event_name} 的 str 型 {key} 未被剥离"
    # 净化不是「清空」：非禁词键必须原样活下来
    assert out["repo_id"] == "r1"


def test_unknown_event_credential_falls_back_to_redaction() -> None:
    """未知事件（剥离表未同步）里的凭据仍不出网 —— 第三层兜底生效。"""
    out = sanitize_process_event_payload({"note": f"token={FAKE_CREDENTIAL} 请勿外泄"})

    assert FAKE_CREDENTIAL not in out["note"]
    assert "***REDACTED***" in out["note"]


def test_long_string_is_truncated() -> None:
    """残留字符串截断到 200 字符（含省略号），防单事件撑爆 SSE 帧。"""
    out = sanitize_process_event_payload({"note": "长" * 500})

    assert len(out["note"]) == 200
    assert out["note"].endswith("…")


def test_non_dict_payload_returns_empty_dict() -> None:
    """输入非 dict / None ⇒ 返回 `{}`，不抛（本函数在 best-effort 出网路径上）。"""
    assert sanitize_process_event_payload(None) == {}
    assert sanitize_process_event_payload("不是 dict") == {}  # type: ignore[arg-type]
    assert sanitize_process_event_payload([1, 2, 3]) == {}  # type: ignore[arg-type]


def test_taxonomy_event_names_are_untouched_by_sanitizer() -> None:
    """净化只作用于 payload，事件名（`event_taxonomy` 常量）不参与——形状确认。"""
    assert EVENT_REPO_ROUTING in ALL_EVENTS
    assert EVENT_FEATURE_CLASSIFIED in ALL_EVENTS
    assert EVENT_CLARIFICATION_ASKED in ALL_EVENTS
    assert EVENT_REPO_RESEARCH_COMPLETED in ALL_EVENTS
    assert EVENT_REPO_RESEARCH_FAILED in ALL_EVENTS


# ============================ 失败原因闭集 ============================

# UI-SPEC §落点 D 实读的六种 error 落点形状（第 5 行拆成两条注册缺失分支）
_LEAKY_TEXT = "ConnectionError: 上游 500 body=<html>secret</html>"

_ERROR_SHAPES: list[tuple[dict | str | None, str]] = [
    # engine.py:94-101 —— stage 内未捕获异常，最常见；无 reason 键
    ({"stage": "route", "exception": "ConnectionError", "message": _LEAKY_TEXT}, "stage_exception"),
    # builtin_processes.py:253-261 —— 融合限次耗尽
    (
        {
            "stage": "merge",
            "reason": "merge_validation_exhausted",
            "report": {"errors": [{"message": _LEAKY_TEXT}]},
        },
        "merge_validation_exhausted",
    ),
    # expire_pending_clarifications.py —— 澄清超时无人答
    (
        {"stage": "clarify", "reason": "clarification_timeout_no_answer", "clarification_id": "c1"},
        "clarification_timeout_no_answer",
    ),
    # resume.py:47-49 —— advance 步数超限
    ({"reason": "advance_step_limit", "steps": 64}, "advance_step_limit"),
    # engine.py:74-77 / :84-87 —— 注册缺失
    ({"reason": "unknown_process_type", "process_type": "nope"}, "unknown_process_type"),
    ({"reason": "unknown_stage", "stage": "nope"}, "unknown_stage"),
    # _fail 收到非 dict —— 只有 message
    ({"message": _LEAKY_TEXT}, "unknown"),
]


@pytest.mark.parametrize(("error", "expected"), _ERROR_SHAPES)
def test_compress_failure_reason_shapes(error: dict, expected: str) -> None:
    """六种 error 落点形状各自压成预期闭集值。"""
    assert compress_failure_reason(error) == expected


@pytest.mark.parametrize(("error", "_expected"), _ERROR_SHAPES)
def test_compress_failure_reason_never_leaks_raw_text(error: dict, _expected: str) -> None:
    """🔴 闭集性：任何一条结果都不得包含输入里的原始文本片段。"""
    result = compress_failure_reason(error)

    assert result in FAILURE_REASON_CODES
    assert "ConnectionError" not in result
    assert "secret" not in result
    assert _LEAKY_TEXT not in result


@pytest.mark.parametrize(
    "error",
    ["就是个字符串", None, 42, ["list"], {"reason": "weird"}, {"reason": 123}, {}],
)
def test_compress_failure_reason_falls_back_to_unknown(error: object) -> None:
    """非 dict / 未受控 reason 取值 / 空 dict ⇒ 一律 `unknown`，绝不回显。"""
    assert compress_failure_reason(error) == "unknown"


def test_failure_reason_codes_is_the_seven_value_closed_set() -> None:
    """闭集恰为 UI-SPEC §B.2 的 7 值（前端文案表按这 7 值 + 兜底写）。"""
    assert FAILURE_REASON_CODES == frozenset(
        {
            "stage_exception",
            "merge_validation_exhausted",
            "clarification_timeout_no_answer",
            "advance_step_limit",
            "unknown_process_type",
            "unknown_stage",
            "unknown",
        }
    )
