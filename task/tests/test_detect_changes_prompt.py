"""``_get_system_prompt`` detect_changes 条件追加守护桩（DIFF-03 / D-01/D-03/D-04）。

照抄 ``test_openspec_prompt.py``：MagicMock config + ``ClaudeRunner._get_system_prompt``。
归属 Plan 124-01。

Wave 0（Plan 124-00）只登记 pytest 节点名；实现由 Plan 124-01 填实。
"""

from __future__ import annotations

import pytest

_WAVE0 = "Wave 0 桩：由 124-01 落地"


@pytest.mark.skip(reason=_WAVE0)
def test_prompt_appends_detect_changes_when_knowledge_plan() -> None:
    """knowledge_endpoint+user_token+task_mode=plan → 含 detect_changes/自查关键词（D-01/D-03）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_prompt_appends_detect_changes_when_execute() -> None:
    """task_mode=execute 且 knowledge 挂载 → 追加自查指引。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_prompt_skips_when_explore_mode() -> None:
    """explore 模式不追加 detect_changes 指引。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_prompt_skips_when_knowledge_missing() -> None:
    """缺 knowledge_endpoint 或 user_token 不追加。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_detect_changes_guidance_helper_independent() -> None:
    """独立 helper 非空静态文本（T-124-01）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_guidance_non_blocking_language() -> None:
    """文案含「继续交付」/「不要因为」类非阻断语义（D-04）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_openspec_and_detect_changes_can_coexist() -> None:
    """follow_openspec=True 且 knowledge 挂载 → openspec 与 detect_changes 两段都在。"""
    pytest.fail("Wave 0 桩")
