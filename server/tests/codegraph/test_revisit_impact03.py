"""IMPACT-03 复验 / 诚实延期验收（D-17；归属 127-05）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


def test_revisit_impact03_zero_samples_honest_defer_path(tmp_path: Path) -> None:
    """样本 0 → 诚实延期路径（不得宣称跨仓已验证）。

    （决策: D-17）
    """
    from codegraph.management.commands.revisit_impact03_samples import revisit_impact03

    out = tmp_path / "impact03-revisit.md"
    called: dict[str, Any] = {"four": False}

    def _count() -> dict[str, int]:
        return {"CrossRepoApiCall": 0, "ApiCallSite": 0, "ApiWrapper": 0}

    def _four(_samples: list[dict[str, str]]) -> dict[str, Any]:
        called["four"] = True
        return {"branches": {}, "four_branches": [], "file_path_name_resolve_hit_rate": 0.0}

    result = revisit_impact03(
        output_md=out,
        count_fn=_count,
        four_branch_fn=_four,
    )
    text = out.read_text(encoding="utf-8")
    assert result["disposition"] == "honest_defer"
    assert called["four"] is False
    assert result["claimed_verified"] is False
    assert "诚实延期" in text
    assert "仍为零" in text or "不可测" in text
    assert "不得" in text and "真实数据上验证" in text


def test_revisit_impact03_positive_samples_invokes_four_branches(tmp_path: Path) -> None:
    """样本 >0 → 四分支复验。

    （决策: D-17）
    """
    from codegraph.management.commands.revisit_impact03_samples import (
        FOUR_BRANCHES,
        revisit_impact03,
    )

    out = tmp_path / "impact03-revisit.md"
    called: dict[str, Any] = {"four": False, "samples": None}

    def _count() -> dict[str, int]:
        return {"CrossRepoApiCall": 3, "ApiCallSite": 5, "ApiWrapper": 2}

    def _samples(*, limit: int = 5) -> list[dict[str, str]]:
        return [
            {
                "repository_id": "11111111-1111-1111-1111-111111111111",
                "file_path": "api/handlers.py",
                "name": "create_order",
            }
        ][:limit]

    def _four(samples: list[dict[str, str]]) -> dict[str, Any]:
        called["four"] = True
        called["samples"] = samples
        return {
            "branches": {name: 1 for name in FOUR_BRANCHES},
            "four_branches": list(FOUR_BRANCHES),
            "file_path_name_resolve_hit_rate": 0.5,
            "resolve_hits": 1,
            "resolve_total": 2,
            "notes": ["四分支 stub"],
        }

    result = revisit_impact03(
        output_md=out,
        count_fn=_count,
        sample_fn=_samples,
        four_branch_fn=_four,
    )
    text = out.read_text(encoding="utf-8")
    assert result["disposition"] == "four_branch_revisit"
    assert called["four"] is True
    assert called["samples"]
    assert "四分支" in text
    for name in FOUR_BRANCHES:
        assert name in text
    assert result["claimed_verified"] is False
