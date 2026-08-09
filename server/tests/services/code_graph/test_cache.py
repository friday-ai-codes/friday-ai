"""``services/code_graph/cache.py`` 的缓存四件套用例（覆盖 GRAPH-02、GRAPH-03、GRAPH-04）。

本文件目前只有用例桩，由 **Plan 121-04**（in-flight 判定的两个回归）、
**Plan 121-07**（字节估算纯函数、LRU 逐出、单例重置）、**Plan 121-08**（命中/
single-flight/失败不毒化/降级/半新图闸门）与 **Plan 121-09**（invalidate 钩子）填充。

⚠️ 并发用例落地时必须用内存假 builder（全程不碰 SQLite 测试库），
参见 121-VALIDATION.md §Test Infrastructure。

桩的存在是 Wave 0 的 Nyquist 要求：121-VALIDATION.md 里每个 ``-k`` 选择器都必须
从第一个 task 起就能解析到真实用例名。
"""

from __future__ import annotations

import pytest


# 121-VALIDATION.md 121-08-T1：首次查询 build 一次、同键再查命中缓存
# （builder 调用计数 == 1）。
@pytest.mark.skip(reason="stub：由 Plan 121-08 实现")
def test_cache_hit_no_rebuild() -> None:
    pass


# 121-VALIDATION.md 121-08-T2：水位推进 + 轨 B 在途（Repository.graph_build_status
# =RUNNING 且有新鲜 RUNNING 的 GraphBuildHistory，双 mutation 缺一不可）
# ⇒ 拒用缓存 + partial_edges=True，绝不静默返回半新图。
@pytest.mark.skip(reason="stub：由 Plan 121-08 实现")
def test_partial_edges_when_edge_build_running() -> None:
    pass


# 121-VALIDATION.md 121-04-T3：graph_build_status=PENDING 但已终态 ⇒ 不判在途
# （模型默认值就是 PENDING，照字面判会让降级标记长鸣，D-03 回归）。
@pytest.mark.skip(reason="stub：由 Plan 121-04 实现")
def test_pending_not_inflight() -> None:
    pass


# 121-VALIDATION.md 121-04-T3：超时的 RUNNING 孤儿行 ⇒ 不判在途
# （复用 GRAPH_BUILD_ORPHAN_TIMEOUT_MINUTES 作超时判据）。
@pytest.mark.skip(reason="stub：由 Plan 121-04 实现")
def test_orphan_running_not_inflight() -> None:
    pass


# 121-VALIDATION.md 121-07-T1：字节估算为纯函数，给定 n/e 返回确定值
# （NODE_COST=640 / EDGE_COST=560，不用 sys.getsizeof 递归）。
@pytest.mark.skip(reason="stub：由 Plan 121-07 实现")
def test_estimate_bytes_is_pure() -> None:
    pass


# 121-VALIDATION.md 121-07-T2：超预算时按 LRU 顺序逐出至 ≤ 预算，
# 并发 code_graph_cache_evicted 事件。
@pytest.mark.skip(reason="stub：由 Plan 121-07 实现")
def test_evict_lru_until_within_budget() -> None:
    pass


# 121-VALIDATION.md 121-08-T3：N 个并发请求同一 key ⇒ builder 只被调用一次
# （内存假 builder + 零 DB 查询断言）。
@pytest.mark.skip(reason="stub：由 Plan 121-08 实现")
def test_single_flight_builds_once() -> None:
    pass


# 121-VALIDATION.md 121-08-T3：构建失败 ⇒ 所有等待者各自抛，
# 且失败不进缓存（不毒化后续请求）。
@pytest.mark.skip(reason="stub：由 Plan 121-08 实现")
def test_build_failure_not_cached() -> None:
    pass


# 121-VALIDATION.md 121-08-T2：单图估算 > CODE_GRAPH_MAX_GRAPH_BYTES ⇒ 不进缓存
# + degraded="on_demand_subgraph"，由上层工具透出。
@pytest.mark.skip(reason="stub：由 Plan 121-08 实现")
def test_degraded_on_demand_subgraph() -> None:
    pass


# 121-VALIDATION.md 121-09-T1：GraphService.invalidate 按仓驱逐全部分支条目
# 并连带清 matcher/指纹 memo；异常吞掉不反噬主流程。
@pytest.mark.skip(reason="stub：由 Plan 121-09 实现")
def test_invalidate_evicts_repo_entries() -> None:
    pass


# 121-VALIDATION.md 121-08-T1（planner 追加行）：一次调用只解析一次 exclusion；
# 连续两次 get_graph 的 _resolve_effective_specs 调用数 ≤ 1。
@pytest.mark.skip(reason="stub：由 Plan 121-08 实现")
def test_exclusion_resolved_once_per_call() -> None:
    pass
