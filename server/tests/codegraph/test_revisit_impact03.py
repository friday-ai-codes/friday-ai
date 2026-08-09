"""IMPACT-03 复验 / 诚实延期验收（D-17；归属 127-05）。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


def test_revisit_impact03_zero_samples_honest_defer_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """样本 0 → 诚实延期路径（不得宣称跨仓已验证）。

    （决策: D-17）
    """
    from codegraph.management.commands import revisit_impact03_samples as mod

    monkeypatch.setattr(mod, "count_cross_repo_samples", lambda: {"cross_repo_api_call": 0, "api_call_site": 0, "api_wrapper": 0})
    run_four = MagicMock()
    monkeypatch.setattr(mod, "run_four_branch_revisit", run_four)

    out = tmp_path / "impact03-revisit.md"
    result = mod.revisit_impact03(output_md=out)
    assert result["status"] == "honest_defer"
    assert result["cross_repo_verified"] is False
    run_four.assert_not_called()
    text = out.read_text(encoding="utf-8")
    assert "IMPACT-03" in text
    assert "诚实" in text
    assert "已验证" not in text or "不可测" in text or "未验证" in text
    assert "不得宣称" in text or "不可测" in text


def test_revisit_impact03_positive_samples_invokes_four_branches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """样本 >0 → 四分支复验。

    （决策: D-17）
    """
    from codegraph.management.commands import revisit_impact03_samples as mod

    monkeypatch.setattr(
        mod,
        "count_cross_repo_samples",
        lambda: {"cross_repo_api_call": 3, "api_call_site": 2, "api_wrapper": 1},
    )
    run_four = MagicMock(
        return_value={
            "branches": {
                "success": True,
                "peer_permission_denied": True,
                "peer_not_indexed": True,
                "hop_limit": True,
            },
            "secondary_resolve_hit_rate": 0.5,
            "sampled": 3,
        }
    )
    monkeypatch.setattr(mod, "run_four_branch_revisit", run_four)

    out = tmp_path / "impact03-revisit.md"
    result = mod.revisit_impact03(output_md=out)
    assert result["status"] == "four_branch_revisit"
    run_four.assert_called_once()
    text = out.read_text(encoding="utf-8")
    assert "IMPACT-03" in text
    assert "四分支" in text
