"""`services/charter_route_signal.py` —— 对话/MCP 链的章程分量。

守的是四条**语义**不变量，而不是具体分值：

1. 无章程 → 逐字节零扰动（「没写章程」是无证据，不是负分——这条一旦破了，
   全库没写章程的仓会被系统性降权）；
2. `owned_domains` 命中 → 加分；
3. `boundaries` 禁区命中 → 扣分（章程分为负）；
4. 章程侧任何异常 → 原样返回 router 排序（best-effort，绝不阻断路由）。
"""

from __future__ import annotations

import pytest
from django.test import override_settings

from services import charter_route_signal
from services.charter_route_signal import aapply_charter_signal

pytestmark = pytest.mark.asyncio

_REPO_A = "11111111-1111-1111-1111-111111111111"
_REPO_B = "22222222-2222-2222-2222-222222222222"


def _patch_charter(monkeypatch, *, charters: dict, supplements: list | None = None) -> None:
    """替换 blueprint_charter_match 的两个 IO 入口，保留纯函数打分不变。"""
    from services.process_runtime import blueprint_charter_match as module

    async def _load(repository_ids):
        return {rid: charters[rid] for rid in repository_ids if rid in charters}

    async def _collect(**_kwargs):
        return list(supplements or [])

    monkeypatch.setattr(module, "aload_charters", _load)
    monkeypatch.setattr(module, "acollect_charter_candidates", _collect)


async def test_no_charter_leaves_score_untouched(monkeypatch) -> None:
    _patch_charter(monkeypatch, charters={})

    items = await aapply_charter_signal(
        query="改造错题本导出", candidates=[(_REPO_A, "study-app", 0.8)]
    )

    assert len(items) == 1
    # 恒等而非近似：无章程绝不能让候选掉分
    assert items[0].blended_score == 0.8
    assert items[0].charter_score == 0.0


async def test_owned_domain_hit_boosts_score(monkeypatch) -> None:
    _patch_charter(
        monkeypatch,
        charters={
            _REPO_A: {
                "repository_id": _REPO_A,
                "owned_domains": [{"domain": "错题本", "status": "implemented"}],
                "boundaries": [],
                "evolution": "active",
                "source": "ai_draft",
                "version": 1,
            }
        },
    )

    items = await aapply_charter_signal(
        query="改造错题本导出", candidates=[(_REPO_A, "study-app", 0.5)]
    )

    assert items[0].charter_score > 0
    assert items[0].blended_score > 0.5
    assert "错题本" in items[0].matched_domains
    # ai_draft 必须在证据里标注，避免被当成人工确认过的结论
    assert "未经人工确认" in items[0].evidence


async def test_boundary_hit_penalizes_score(monkeypatch) -> None:
    _patch_charter(
        monkeypatch,
        charters={
            _REPO_A: {
                "repository_id": _REPO_A,
                "owned_domains": [],
                "boundaries": [{"rule": "不承接课程权益鉴权"}],
                "evolution": "active",
                "source": "human_confirmed",
                "version": 2,
            }
        },
    )

    items = await aapply_charter_signal(
        query="展示课程内容与权益鉴权状态", candidates=[(_REPO_A, "study-app", 0.9)]
    )

    assert items[0].charter_score < 0
    assert items[0].blended_score < 0.9
    assert items[0].violated_boundaries


async def test_supplement_candidate_is_appended_with_zero_router_score(monkeypatch) -> None:
    _patch_charter(
        monkeypatch,
        charters={},
        supplements=[
            {
                "repository_id": _REPO_B,
                "repository_name": "exam-service",
                "charter_match_raw": 0.6,
                "matched_domains": ["错题本"],
            }
        ],
    )

    items = await aapply_charter_signal(
        query="改造错题本导出", candidates=[(_REPO_A, "study-app", 0.8)]
    )

    supplement = next(i for i in items if i.repository_id == _REPO_B)
    # 能力树未召回 → router 分恒 0，排序差异完全归因章程
    assert supplement.router_score == 0.0
    assert supplement.is_supplement is True
    assert supplement.blended_score > 0


async def test_charter_failure_degrades_to_router_order(monkeypatch) -> None:
    from services.process_runtime import blueprint_charter_match as module

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("charter store down")

    monkeypatch.setattr(module, "aload_charters", _boom)

    items = await aapply_charter_signal(
        query="改造错题本导出",
        candidates=[(_REPO_A, "study-app", 0.8), (_REPO_B, "exam-service", 0.3)],
    )

    assert [i.repository_id for i in items] == [_REPO_A, _REPO_B]
    assert [i.blended_score for i in items] == [0.8, 0.3]


@override_settings(REPO_ROUTE_CHARTER_WEIGHT=0.0)
async def test_weight_zero_disables_signal(monkeypatch) -> None:
    """权重可经 settings 关停（上线后若发现章程质量不够，改配置即回滚行为）。"""
    _patch_charter(
        monkeypatch,
        charters={
            _REPO_A: {
                "repository_id": _REPO_A,
                "owned_domains": [{"domain": "错题本", "status": "implemented"}],
                "boundaries": [],
                "evolution": "active",
                "source": "ai_draft",
                "version": 1,
            }
        },
    )

    assert charter_route_signal.resolve_charter_weight() == 0.0
    items = await aapply_charter_signal(
        query="改造错题本导出", candidates=[(_REPO_A, "study-app", 0.5)]
    )
    assert items[0].blended_score == 0.5
