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
@pytest.mark.django_db
def test_pending_not_inflight(indexed_repo) -> None:
    """轨 A：``PENDING`` 是模型默认值，单看它会让降级标记长鸣（121-CONTEXT D-03）。

    四段合起来把轨 A 的三条件判据锁死——前三段证明「不误报」，第四段是**反证**，
    证明这个判据不是恒假的（把整个函数改成 ``return False, ""`` 也能让前三段通过，
    那样降级保护就静默消失了）。
    """
    from django.utils import timezone

    from repositories.models import (
        GraphBuildStatus,
        IndexHistory,
        IndexHistoryStatus,
        Repository,
        TriggerType,
    )
    from services.code_graph.signature import detect_edge_build_in_flight

    repo_id = str(indexed_repo.id)

    # ① 完全没有 IndexHistory 行的仓库：从未触发过边构建 ≠ 边构建在途。
    assert detect_edge_build_in_flight(repo_id, "") == (False, "")

    # ② graph_build_status 停在默认的 PENDING，但索引本身已经跑完了。
    history = IndexHistory.objects.create(
        repository=indexed_repo,
        trigger_type=TriggerType.MANUAL,
        status=IndexHistoryStatus.COMPLETED,
        graph_build_status=GraphBuildStatus.PENDING,
        started_at=timezone.now(),
        finished_at=timezone.now(),
    )
    assert history.graph_build_status == GraphBuildStatus.PENDING  # 就是模型默认值
    assert detect_edge_build_in_flight(repo_id, "") == (False, ""), (
        "PENDING + 已终态被判成在途——降级标记会对每个从未触发过边构建的仓库长鸣"
    )

    # ③ SKIPPED（空 dirty 集）是正常终态，即便 IndexHistory 自身还在跑也不算在途。
    history.graph_build_status = GraphBuildStatus.SKIPPED
    history.status = IndexHistoryStatus.RUNNING
    history.save(update_fields=["graph_build_status", "status"])
    assert detect_edge_build_in_flight(repo_id, "") == (False, "")

    # ④ 反证：真在途（三条件同时成立）必须被判出来，否则前三段毫无意义。
    history.graph_build_status = GraphBuildStatus.RUNNING
    history.status = IndexHistoryStatus.RUNNING
    history.started_at = timezone.now()
    history.save(update_fields=["graph_build_status", "status", "started_at"])
    assert detect_edge_build_in_flight(repo_id, "") == (
        True,
        "chunk_edge_build_running",
    )

    # ⑤ 同为在途态的 PENDING（真有在途任务时）同样要判出，短码带状态便于排障。
    history.graph_build_status = GraphBuildStatus.PENDING
    history.save(update_fields=["graph_build_status"])
    assert detect_edge_build_in_flight(repo_id, "") == (
        True,
        "chunk_edge_build_pending",
    )

    # 轨 B 全程静止（未被上面任何一段带跑），确认结论确实来自轨 A。
    assert Repository.objects.filter(id=indexed_repo.id).values_list(
        "graph_build_status", flat=True
    ).first() == "idle"


# 121-VALIDATION.md 121-04-T3：超时的 RUNNING 孤儿行 ⇒ 不判在途
# （复用 GRAPH_BUILD_ORPHAN_TIMEOUT_MINUTES 作超时判据）。
@pytest.mark.django_db
def test_orphan_running_not_inflight(indexed_repo) -> None:
    """轨 B：超时的 RUNNING 孤儿行不算在途（RESEARCH Pitfall 5 回归）。

    没有超时兜底的话，一个卡住的 RUNNING 行会让该仓**永久**拒用缓存、每次查询都
    重建 2–4 秒的大图——这是拒绝服务，不是保护。超时阈值复用既有的
    ``GRAPH_BUILD_ORPHAN_TIMEOUT_MINUTES``（``codegraph.apps`` 的孤儿回收用的
    同一个），两处对齐才不会出现「孤儿已被回收但图服务仍判在途」。
    """
    from datetime import timedelta

    from django.conf import settings
    from django.utils import timezone

    from repositories.models import (
        GraphBuildHistory,
        GraphBuildHistoryStatus,
        GraphBuildHistoryTrigger,
        RepositoryGraphStatus,
    )
    from services.code_graph.signature import detect_edge_build_in_flight

    repo_id = str(indexed_repo.id)
    timeout_min = int(getattr(settings, "GRAPH_BUILD_ORPHAN_TIMEOUT_MINUTES", 30))

    indexed_repo.graph_build_status = RepositoryGraphStatus.RUNNING
    indexed_repo.save(update_fields=["graph_build_status"])

    build = GraphBuildHistory.objects.create(
        repository=indexed_repo,
        trigger_type=GraphBuildHistoryTrigger.MANUAL,
        status=GraphBuildHistoryStatus.RUNNING,
        branch_name="",
        started_at=timezone.now() - timedelta(minutes=timeout_min + 5),
    )
    assert detect_edge_build_in_flight(repo_id, "") == (False, ""), (
        "超时的 RUNNING 孤儿被判成在途——该仓会永久拒用缓存、每次查询重建大图"
    )

    # 反证：同一行改成新鲜的 started_at 就必须判在途。
    build.started_at = timezone.now() - timedelta(minutes=1)
    build.save(update_fields=["started_at"])
    assert detect_edge_build_in_flight(repo_id, "") == (
        True,
        "symbol_extraction_running",
    )


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
