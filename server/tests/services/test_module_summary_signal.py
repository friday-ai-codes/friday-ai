"""``services/module_summary_signal.py`` —— 对话/MCP 链的模块摘要 evidence（MOD-04 / D-15）。

守三条语义：

1. 任意异常 → 原样返回 router 排序（fail-soft）；
2. 有摘要 → evidence 追加，**不改** router_base / blended 分数；
3. 无摘要 → 零扰动（恒等返回）。
"""

from __future__ import annotations

import pytest

from services.module_summary_signal import aapply_module_summary_signal

pytestmark = pytest.mark.asyncio

_REPO_A = "11111111-1111-1111-1111-111111111111"
_REPO_B = "22222222-2222-2222-2222-222222222222"


def _patch_load(monkeypatch, *, by_repo: dict | None = None, boom: bool = False) -> None:
    import services.module_summary_signal as module

    async def _load(repository_ids, **_kwargs):
        if boom:
            raise RuntimeError("module summary store down")
        src = by_repo or {}
        return {str(rid): list(src.get(str(rid), [])) for rid in repository_ids}

    monkeypatch.setattr(module, "aload_module_summaries_for_repos", _load)


async def test_apply_signal_failsoft_on_error(monkeypatch) -> None:
    """signal 侧任意异常 → 原样返回 router 排序（fail-soft）。

    （Req: MOD-04, 决策: D-15）
    """
    _patch_load(monkeypatch, boom=True)

    items = await aapply_module_summary_signal(
        query="改造错题本导出",
        candidates=[(_REPO_A, "study-app", 0.8), (_REPO_B, "exam-service", 0.3)],
    )

    assert [i.repository_id for i in items] == [_REPO_A, _REPO_B]
    assert [i.router_score for i in items] == [0.8, 0.3]
    assert all(not i.evidence for i in items)


async def test_apply_signal_appends_evidence_without_changing_router_base(
    monkeypatch,
) -> None:
    """evidence / reason 文本追加；默认不改 router_base 分数。

    （Req: MOD-04, 决策: D-15）
    """
    _patch_load(
        monkeypatch,
        by_repo={
            _REPO_A: [
                {
                    "community_key": "auth-mod",
                    "text": "## 模块摘要\n### 职责\n错题本导出与鉴权",
                    "responsibility": "错题本导出与鉴权",
                    "relevance": 0.9,
                }
            ]
        },
    )

    items = await aapply_module_summary_signal(
        query="改造错题本导出",
        candidates=[(_REPO_A, "study-app", 0.55)],
    )

    assert len(items) == 1
    assert items[0].router_score == 0.55
    assert items[0].blended_score == 0.55
    assert items[0].evidence
    assert "错题本" in items[0].evidence or "模块摘要" in items[0].evidence


async def test_empty_summaries_noop(monkeypatch) -> None:
    """无模块摘要时零扰动（恒等返回）。

    （Req: MOD-04, 决策: D-15）
    """
    _patch_load(monkeypatch, by_repo={})

    items = await aapply_module_summary_signal(
        query="改造错题本导出",
        candidates=[(_REPO_A, "study-app", 0.8)],
    )

    assert len(items) == 1
    assert items[0].router_score == 0.8
    assert items[0].blended_score == 0.8
    assert items[0].evidence == ""
