"""``services/code_graph/community.py`` Wave 0 验收桩（MOD-01 / MOD-02）。

覆盖 D-04/D-05/D-06/D-07/D-08 与 T-125-01。行为用例由 125-02（Louvain /
指纹 / 取图纪律）与 125-03（rebuild×2 LLM=0 / Jaccard / 空摘要重试）去 skip 填实。
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Wave 0 桩：由 125-02 落地")
def test_louvain_seed_stable() -> None:
    """同投影图两次 Louvain 划分一致；``LOUVAIN_SEED`` 常量存在。

    （Req: MOD-01, 决策: D-04/D-05）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 125-02 落地")
def test_project_undirected_sorted_nodes_edges() -> None:
    """无向投影节点/边按稳定序输出（确定性划分前置）。

    （Req: MOD-01, 决策: D-05）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 125-02 落地")
def test_fingerprint_deterministic_order_independent() -> None:
    """成员 fingerprint 与成员顺序无关、同集合结果稳定。

    （Req: MOD-02, 决策: D-06）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 125-03 落地")
def test_fingerprint_jaccard_skip() -> None:
    """指纹全等 short-circuit；Jaccard≥阈值复用既有 summary。

    （Req: MOD-02, 决策: D-06/D-07）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 125-03 落地")
def test_rebuild_twice_zero_llm() -> None:
    """无代码变更连续 rebuild 两次 → LLM 调用数 = 0（验收铁律）。

    （Req: MOD-02, 决策: D-07）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 125-03 落地")
def test_empty_summary_retries() -> None:
    """既有 summary 为空时允许重试生成（仍计 LLM）。

    （Req: MOD-02, 决策: D-08）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 125-03 落地")
def test_unclustered_or_small_skips_llm() -> None:
    """unclustered 或规模过小社区不调 LLM。

    （Req: MOD-02/MOD-03, 决策: D-08）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 125-02 落地")
def test_get_graph_only_no_loader_import() -> None:
    """源文件静态：``community.py`` 不 import loader/cache，只经 ``get_graph_service``。

    （Req: MOD-01, 威胁: T-125-01）
    """
    pytest.fail("Wave 0 桩")
