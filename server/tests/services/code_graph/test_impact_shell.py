"""impact 壳层编排的异常与短路分支（覆盖 D-24 / D-03 / D-19）。

与 ``test_impact.py`` 的分工：内核是纯函数、零 DB；本文件测的是**壳层**——取图预算、
``GraphError`` 翻译、以及重名时在取图**之前**短路。这三件事都要库，所以单独成文件，
不污染内核用例的零 DB 纪律。

Wave 0（Plan 122-01）只落骨架，用例由 122-05 / 122-07 填实。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


@pytest.mark.skip(reason="Wave 0 桩：由 122-05 落地")
def test_over_budget_uses_seeded_subgraph() -> None:
    """超预算仓：壳层传了 ``seed_symbol_ids`` + ``depth``，不吃 ``GraphError``。

    ⚠️ ``get_graph`` 的缺省 ``depth`` 是 2，壳层**必须显式传 depth**，否则 d3 残缺。

    （Req: IMPACT-01, 决策: D-24）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 122-05 落地")
def test_graph_error_translated_not_swallowed() -> None:
    """内核不吞 ``GraphError``，由壳层逐类翻译成明确的工具错误文案（D-03）。

    ⛔ 未索引仓的 impact 必须是**错误响应**而不是 ``{"affected": []}``——空影响面会被 agent
    读成「改这里没影响」，是最危险的误导。⛔ 翻译时只取 ``exc.message``，不把 ``str(exc)``
    直出（``__str__`` 会拼上含 ``estimated_bytes`` 的内部 ``details``）。

    （Req: IMPACT-01, 决策: D-03）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 122-07 落地")
def test_ambiguous_symbol_short_circuits_before_graph_fetch() -> None:
    """重名时在**取图之前**短路成候选列表，不白建一张图（D-19）。

    （Req: IMPACT-05, 决策: D-19）
    """
    pytest.fail("Wave 0 桩")
