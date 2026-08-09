"""``services/code_graph/module_summary.py`` Wave 0 验收桩（MOD-03）。

覆盖 D-09/D-10/D-11 与 T-125-02/03。行为用例由 125-03 去 skip 填实。
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Wave 0 桩：由 125-03 落地")
def test_uses_call_source_module_summary() -> None:
    """``agenerate_module_summary`` 经 ``use_call_source(MODULE_SUMMARY)`` 包裹 LLM。

    （Req: MOD-03, 决策: D-09）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 125-03 落地")
def test_metadata_only_prompt_no_source_body() -> None:
    """prompt 仅含成员元数据，不含源码正文。

    （Req: MOD-03, 决策: D-10, 威胁: T-125-02）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 125-03 落地")
def test_failsoft_returns_none_on_llm_error() -> None:
    """LLM 失败 fail-soft 返回 None，不阻断社区落库。

    （Req: MOD-03, 决策: D-11, 威胁: T-125-03）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 125-03 落地")
def test_render_module_summary_helper() -> None:
    """``render_module_summary`` 将结构化摘要渲染为消费端文本。

    （Req: MOD-03, 决策: D-11）
    """
    pytest.fail("Wave 0 桩")
