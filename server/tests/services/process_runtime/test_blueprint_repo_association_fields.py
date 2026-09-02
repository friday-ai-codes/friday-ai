"""仓库关联卡三字段的产出侧修复（quick 260807，用户实测反馈）。

用户在查看器里看到的两个问题，各守一组正反用例：

1. **「适配判定」正文恒空**：调研容器明明产出 ``fitness.reasons``，但确认门快照
   （``_build_snapshot_entry``）此前写死 ``"reasons": []`` ⇒ 锁定与蓝图投影全程为空。
   现快照必须携带 conclusion 里的 reasons（字符串截断、block 形状原样、非 list 收敛空）。
2. **「选仓理由」与「本仓职责」一字不差**：锁定产物从不产 ``rationale.text``，而
   ``blueprint_merge._project_rationale`` 此前拿 ``responsibility`` 兜底 ⇒ 必然重复。
   现无源 ``rationale.text`` 时留空数组（schema 合法、前端整块不渲染），citations
   并集（P-8 覆盖率分子）逐字保留。

纯函数直测，零 DB。
"""

from __future__ import annotations

from services.process_runtime.blueprint_confirm_gate import (
    _MAX_SUMMARY_CHARS,
    _build_snapshot_entry,
    build_locked_associations,
)
from services.process_runtime.blueprint_merge import project_repo_associations

_RID = "11111111-1111-1111-1111-111111111111"


def _conclusion(**overrides) -> dict:
    base = {
        "verdict": "partial",
        "reasons": ["复用 exam/single 组件即可承载", "缺 5 分钟倒计时组件需新增"],
        "citations": ["src/exam/single.vue", "src/timer/countdown.ts"],
        "role_suggestion": "direct",
        "responsibility": "承载真题检测做题页",
        "findings": [],
        "task_status": "done",
    }
    base.update(overrides)
    return base


# ── 1. 快照携带适配理由 ────────────────────────────────────────────────────


def test_snapshot_entry_carries_fitness_reasons() -> None:
    entry = _build_snapshot_entry(_RID, candidate={}, conclusion=_conclusion(), router_version="v1")
    assert entry["fitness"]["verdict"] == "partial"
    assert entry["fitness"]["reasons"] == [
        "复用 exam/single 组件即可承载",
        "缺 5 分钟倒计时组件需新增",
    ]
    assert entry["fitness"]["citations"] == [
        "src/exam/single.vue",
        "src/timer/countdown.ts",
    ]


def test_snapshot_entry_defaults_to_empty_citations() -> None:
    """反面：conclusion 无 citations / 非 list ⇒ 空数组（与 reasons 同一形状）。"""
    for citations in (None, "不是列表", {"k": 1}):
        entry = _build_snapshot_entry(
            _RID, candidate={}, conclusion=_conclusion(citations=citations), router_version="v1"
        )
        assert entry["fitness"]["citations"] == []


def test_snapshot_entry_truncates_and_keeps_block_reasons() -> None:
    """字符串理由截断防快照膨胀；block 形状条目原样保留（锁定时统一收敛）。"""
    block = {"block_id": "blk_x", "type": "paragraph", "text": "结构化理由"}
    entry = _build_snapshot_entry(
        _RID,
        candidate={},
        conclusion=_conclusion(reasons=["y" * (_MAX_SUMMARY_CHARS + 50), block, "", None]),
        router_version="v1",
    )
    reasons = entry["fitness"]["reasons"]
    assert reasons[0] == "y" * _MAX_SUMMARY_CHARS
    assert reasons[1] is block
    # 空串 / None 被丢弃
    assert len(reasons) == 2


def test_snapshot_entry_defaults_to_empty_reasons() -> None:
    """反面：conclusion 无 reasons / 非 list ⇒ 空数组（与既有形状一致，不上抛）。"""
    for reasons in (None, "不是列表", {"k": 1}):
        entry = _build_snapshot_entry(
            _RID, candidate={}, conclusion=_conclusion(reasons=reasons), router_version="v1"
        )
        assert entry["fitness"]["reasons"] == []


# ── 2. 快照 → 锁定 → 蓝图投影：理由贯通、选仓理由不再复读职责 ─────────────


def _locked_association() -> dict:
    """走真实 `build_locked_associations`（快照 → 锁定），不手拼中间形状。"""
    snapshot = [
        _build_snapshot_entry(
            _RID,
            candidate={"repository_name": "frontend/onion-practice"},
            conclusion=_conclusion(),
            router_version="v1",
        )
    ]
    locked = build_locked_associations(snapshot=snapshot, citation_pool=set())
    assert len(locked) == 1
    return locked[0]


def test_locked_association_reasons_become_blocks() -> None:
    fitness = _locked_association()["fitness"]
    assert fitness["verdict"] == "partial"
    texts = [block.get("text") for block in fitness["reasons"]]
    assert texts == ["复用 exam/single 组件即可承载", "缺 5 分钟倒计时组件需新增"]


def test_projected_association_keeps_reasons_and_leaves_rationale_empty() -> None:
    """⭐ 蓝图投影后：fitness.reasons 有正文；rationale.text 为空数组——⛔ 不再复读
    responsibility（此前兜底让「选仓理由」与「本仓职责」一字不差，用户实测反馈）。"""
    locked = _locked_association()
    projected = project_repo_associations([locked], {})
    entry = projected[0]

    reason_texts = [block.get("text") for block in entry["fitness"]["reasons"]]
    assert reason_texts == ["复用 exam/single 组件即可承载", "缺 5 分钟倒计时组件需新增"]

    assert entry["rationale"]["text"] == []
    assert entry["responsibility"], "职责本身仍在（前提断言，防空对空的假通过）"


def test_projected_rationale_still_honors_explicit_text_and_citations() -> None:
    """正面对照：源条目真带 rationale.text / citations 时逐字投影（P-8 citations 并集）。"""
    locked = _locked_association()
    locked["rationale"] = {"text": ["因为章程域命中学习工具"], "citations": ["cit_a"]}
    locked["fitness"]["citations"] = ["cit_b"]
    cite_map = {"cit_a": "cit_a", "cit_b": "cit_b"}

    entry = project_repo_associations([locked], cite_map)[0]
    assert [block.get("text") for block in entry["rationale"]["text"]] == ["因为章程域命中学习工具"]
    assert entry["rationale"]["citations"] == ["cit_a", "cit_b"]
