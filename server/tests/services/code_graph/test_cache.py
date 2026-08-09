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

import threading
import time

import pytest


# 121-VALIDATION.md 121-08-T1：首次查询 build 一次、同键再查命中缓存
# （builder 调用计数 == 1）。
@pytest.mark.django_db(transaction=True)
async def test_cache_hit_no_rebuild(
    indexed_repo, symbols_factory, call_edges_factory
) -> None:
    """同键连查两次只装配一次；命中路径**不跳过**权限校验，也**不跳过** in-flight 闸。

    三条断言各自守一件不同的事，缺一不可：

    - ``load_graph`` 只调一次、两次返回**同一个对象** ⇒ 缓存真的生效（GRAPH-01）。
    - ``ensure_repository_readable`` 调了**两次** ⇒ 命中没有绕过唯一的权限防线。缓存键
      不带用户维度，一旦命中跳过校验，任何拿得到 ``repository_id`` 的调用方都能读到
      别人建好的图（威胁登记 T-121-串图）。
    - ``detect_edge_build_in_flight`` 调了**两次** ⇒ 闸门确实位于命中返回**之前**。若被
      挪进未命中分支，这里会是 1，而 GRAPH-02 的半新图防护就只在冷路径上生效了。
    """
    from unittest import mock

    from asgiref.sync import sync_to_async
    from structlog.testing import capture_logs

    from services.code_graph import access as access_module
    from services.code_graph import cache as cache_module
    from services.code_graph import loader as loader_module
    from services.code_graph import signature as signature_module

    def _seed() -> None:
        caller = symbols_factory("caller", "src/a.py")
        callee = symbols_factory("callee", "src/b.py")
        call_edges_factory(caller, callee)

    await sync_to_async(_seed)()

    svc = cache_module.get_graph_service()
    repo_id = str(indexed_repo.id)

    with (
        mock.patch.object(
            loader_module, "load_graph", wraps=loader_module.load_graph
        ) as load_spy,
        mock.patch.object(
            access_module,
            "ensure_repository_readable",
            wraps=access_module.ensure_repository_readable,
        ) as acl_spy,
        mock.patch.object(
            signature_module,
            "detect_edge_build_in_flight",
            wraps=signature_module.detect_edge_build_in_flight,
        ) as inflight_spy,
        mock.patch.object(
            signature_module,
            "compute_signature",
            wraps=signature_module.compute_signature,
        ) as sig_spy,
    ):
        first = await svc.get_graph(repo_id)
        assert load_spy.call_count == 1
        assert first.graph.number_of_nodes() == 2

        second = await svc.get_graph(repo_id)
        assert load_spy.call_count == 1, "同键第二次查询又装配了一遍——缓存没生效"
        assert second is first, "命中应当返回缓存里的同一个 CodeGraph 对象"

        assert acl_spy.call_count == 2, "命中路径跳过了 ensure_repository_readable"
        assert inflight_spy.call_count == 2, (
            "命中路径跳过了 in-flight 闸——闸门被挪到了命中返回之后"
        )

        # loader 收到的是 cache 解析好的 matcher/指纹（loader 自己不再解析），
        # 且该指纹与喂给 compute_signature 的是同一个值。
        load_kwargs = load_spy.call_args.kwargs
        assert "matcher" in load_kwargs and "exclusion_fingerprint" in load_kwargs
        assert (
            load_kwargs["exclusion_fingerprint"]
            == sig_spy.call_args.kwargs["exclusion_fingerprint"]
        )

        # 签名失效：水位一变，旧条目被丢弃并重建。
        from repositories.models import Repository

        await Repository.objects.filter(id=indexed_repo.id).aupdate(
            last_indexed_commit_sha="b" * 40
        )
        with capture_logs() as events:
            third = await svc.get_graph(repo_id)

        assert load_spy.call_count == 2, "签名已变却仍返回旧图"
        assert third is not first
        stale = [e for e in events if e["event"] == "code_graph_stale_watermark"]
        assert len(stale) == 1
        assert stale[0]["component"] == "code_graph"
        assert stale[0]["category"] == "sampling"
        assert stale[0]["reason"] == "signature_mismatch"
        # 只记签名前 12 位：全量签名的明文分量含水位 sha 与两条轨的行 id/状态。
        assert len(stale[0]["cached_signature"]) == 12
        assert len(stale[0]["current_signature"]) == 12

    # 记账没有随重建漂移：缓存里只剩一条，字节数等于该图的估算值。
    assert svc.stats()["entries"] == 1
    assert svc.stats()["total_bytes"] == third.meta.estimated_bytes


# 121-VALIDATION.md 121-08-T1（planner 追加行）：一次调用只解析一次 exclusion；
# 连续两次 get_graph 的 _resolve_effective_specs 调用数 ≤ 1。
@pytest.mark.django_db(transaction=True)
async def test_exclusion_resolved_once_across_two_calls(indexed_repo) -> None:
    """exclusion 规则**一次调用只解析编译一次**，跨调用还能吃到 access.py 的 TTL memo。

    两处浪费各有一条断言：

    - ``build_matcher_and_fingerprint`` 在单次 ``get_graph`` 内只调一次 ⇒ loader 没有
      自己再解析一遍（它内部会走 ``_resolve_effective_specs`` 的 DB 读，再把该仓全部
      glob/regex 重编译一遍，而这条同步路径吃不到 ``build_matcher_for_repo`` 的 60s
      ``_matcher_cache``，省不掉）。
    - 连调两次后 ``_resolve_effective_specs`` ≤ 1 ⇒ 跨调用命中了 ``access.py`` 自带的
      TTL memo。
    """
    from unittest import mock

    from services import exclusion as exclusion_module
    from services.code_graph import access as access_module
    from services.code_graph import cache as cache_module

    svc = cache_module.get_graph_service()
    repo_id = str(indexed_repo.id)

    with (
        mock.patch.object(
            exclusion_module,
            "_resolve_effective_specs",
            wraps=exclusion_module._resolve_effective_specs,
        ) as resolve_spy,
        mock.patch.object(
            access_module,
            "build_matcher_and_fingerprint",
            wraps=access_module.build_matcher_and_fingerprint,
        ) as matcher_spy,
    ):
        await svc.get_graph(repo_id)
        assert matcher_spy.call_count == 1, (
            "单次 get_graph 内解析了不止一次——多半是 loader 又自己解析了一遍"
        )
        assert resolve_spy.call_count == 1

        await svc.get_graph(repo_id)
        assert resolve_spy.call_count <= 1, (
            "第二次调用重新解析了规则集——access.py 的 TTL memo 没吃到"
        )


# 121-VALIDATION.md 121-08-T2：水位推进 + 轨 B 在途（Repository.graph_build_status
# =RUNNING 且有新鲜 RUNNING 的 GraphBuildHistory，双 mutation 缺一不可）
# ⇒ 拒用缓存 + partial_edges=True，绝不静默返回半新图。
@pytest.mark.django_db(transaction=True)
async def test_partial_edges_when_edge_build_running(
    indexed_repo, symbols_factory
) -> None:
    """轨 B 在途 ⇒ 打 ``partial_edges`` 且该次结果**不进缓存**。

    轨 B 的判据是**合取**（`121-04` Task 3）：``Repository.graph_build_status=RUNNING``
    **且**存在一条未超时的 ``GraphBuildHistory(status=RUNNING)``。只翻其中一处会得到
    ``(False, "")`` ——用例开头先把这条单独断言掉，免得后人以为原因短码写错了。

    半新图不进缓存这一条同样关键：缓存下来的话，后续每一次命中都会返回这张少了一半边
    的图，污染面比这一次大得多。
    """
    from asgiref.sync import sync_to_async
    from django.utils import timezone

    from services.code_graph import cache as cache_module

    def _seed() -> None:
        symbols_factory("a", "src/a.py")

    await sync_to_async(_seed)()

    svc = cache_module.get_graph_service()
    repo_id = str(indexed_repo.id)

    def _only_repo_flag() -> None:
        from repositories.models import Repository, RepositoryGraphStatus

        Repository.objects.filter(id=indexed_repo.id).update(
            graph_build_status=RepositoryGraphStatus.RUNNING
        )

    await sync_to_async(_only_repo_flag)()
    lone = await svc.get_graph(repo_id)
    assert lone.meta.partial_edges is False, (
        "只翻 Repository.graph_build_status 就判在途——轨 B 的合取判据被写成了析取"
    )
    cache_module._reset_for_tests()
    svc = cache_module.get_graph_service()

    def _start_build():
        from repositories.models import (
            GraphBuildHistory,
            GraphBuildHistoryStatus,
            GraphBuildHistoryTrigger,
        )

        return GraphBuildHistory.objects.create(
            repository=indexed_repo,
            trigger_type=GraphBuildHistoryTrigger.MANUAL,
            status=GraphBuildHistoryStatus.RUNNING,
            branch_name="",
            started_at=timezone.now(),
        )

    build = await sync_to_async(_start_build)()

    partial = await svc.get_graph(repo_id)
    assert partial.meta.partial_edges is True
    assert partial.meta.partial_reason == "symbol_extraction_running"
    assert svc.stats()["entries"] == 0, "半新图被写进了缓存，后续命中会一直返回它"

    def _finish_build() -> None:
        from repositories.models import (
            GraphBuildHistory,
            GraphBuildHistoryStatus,
            Repository,
            RepositoryGraphStatus,
        )

        GraphBuildHistory.objects.filter(pk=build.pk).update(
            status=GraphBuildHistoryStatus.COMPLETED, finished_at=timezone.now()
        )
        Repository.objects.filter(id=indexed_repo.id).update(
            graph_build_status=RepositoryGraphStatus.COMPLETED
        )

    await sync_to_async(_finish_build)()

    settled = await svc.get_graph(repo_id)
    assert settled.meta.partial_edges is False
    assert settled.meta.partial_reason == ""
    assert svc.stats()["entries"] == 1


# 121-VALIDATION.md 121-08-T2（闸门位置回归）：只推进轨 A 的 IndexHistory.started_at
# ——签名逐字节不变，但 in-flight 翻真 ⇒ 仍须拒用缓存。
@pytest.mark.django_db(transaction=True)
async def test_partial_edges_rejects_cache_even_when_signature_matches(
    indexed_repo, symbols_factory
) -> None:
    """**签名恰好一致**时仍拒用缓存——「in-flight 闸在命中返回之前」的唯一机械证据。

    为什么走轨 A 的 ``started_at``：`121-04` 的 ``ihA:`` 分量取的是
    ``(id, graph_build_status, status, finished_at, payload_synced_at, edge_count)``，
    **刻意不含 ``started_at``**；而轨 A 的在途判据第三条正是 ``started_at >= cutoff``。
    单改 ``started_at`` 因此会翻转 in-flight 而签名逐字节不变。

    ⛔ 轨 B 走不通：``ghB:`` 含 ``status``、``repoG:`` 含 ``graph_build_status``，两处
    mutation 都会改签名，「签名恰好一致」的前提根本造不出来。⛔ 也不能走
    ``index_status=INDEXING`` 绕——``ensure_repository_readable`` 会在
    ``_get_graph_sync`` 之前就抛 ``GraphNotIndexed``。

    ⛔ **本用例不得打桩 ``compute_signature`` / ``detect_edge_build_in_flight``**：它的
    全部价值在于「签名真的一致」这个前提**真实成立**；一旦打桩，断言的只是 stub 的行为，
    闸门挪位照样能过。（Task 3 并发用例的打桩是另一回事——那里打桩是为了消除 DB 竞态。）

    若把闸门挪到命中返回之后，最后一步会拿到第一次那个**同一个** ``CodeGraph`` 对象且
    ``partial_edges is False``，用例必然失败。
    """
    from datetime import timedelta

    from asgiref.sync import sync_to_async
    from django.conf import settings
    from django.utils import timezone

    from services.code_graph import access as access_module
    from services.code_graph import cache as cache_module
    from services.code_graph import signature as signature_module

    timeout_min = int(getattr(settings, "GRAPH_BUILD_ORPHAN_TIMEOUT_MINUTES", 30))

    def _seed():
        from repositories.models import (
            GraphBuildStatus,
            IndexHistory,
            IndexHistoryStatus,
            TriggerType,
        )

        symbols_factory("a", "src/a.py")
        # 前两条判据已满足，只差第三条超时 ⇒ 此刻是**孤儿，不在途**。
        # ⚠️ fixture 自洽性：仓库级 index_status=INDEXED（已完成过索引）与本行的
        # status=RUNNING（当前正在跑一次增量索引）在本仓语义上完全合法，不矛盾。
        return IndexHistory.objects.create(
            repository=indexed_repo,
            trigger_type=TriggerType.MANUAL,
            status=IndexHistoryStatus.RUNNING,
            graph_build_status=GraphBuildStatus.RUNNING,
            started_at=timezone.now() - timedelta(minutes=timeout_min + 5),
        )

    history = await sync_to_async(_seed)()

    svc = cache_module.get_graph_service()
    repo_id = str(indexed_repo.id)

    first = await svc.get_graph(repo_id)
    assert first.meta.partial_edges is False
    assert svc.stats()["entries"] == 1
    cached_signature = svc._cache[(repo_id, "")].built_signature

    # ④ 只改这一个字段。⛔ 不碰 last_indexed_commit_sha / Symbol 计数 / CallEdge 计数 /
    #    exclusion 规则 / 任何 GraphBuildHistory 或 Repository 字段。
    def _advance_started_at() -> str:
        from repositories.models import IndexHistory

        IndexHistory.objects.filter(pk=history.pk).update(started_at=timezone.now())
        _, fingerprint = access_module.build_matcher_and_fingerprint(repo_id)
        return signature_module.compute_signature(
            repo_id, "", exclusion_fingerprint=fingerprint
        )

    recomputed = await sync_to_async(_advance_started_at)()

    # ⑤ 把「签名恰好一致」固化成用例的显式前提，而不是假设。
    assert recomputed == cached_signature, (
        "推进 started_at 之后签名变了——ihA: 分量误纳入了 started_at，本用例的杠杆失效"
    )

    second = await svc.get_graph(repo_id)
    assert second.meta.partial_edges is True, (
        "签名一致就直接返回了缓存——in-flight 闸被挪到了命中返回之后（GRAPH-02 失效）"
    )
    assert second.meta.partial_reason == "chunk_edge_build_running"
    assert second is not first, "返回的是缓存里那张图，说明命中并未被拒"
    # 绕过 ≠ 驱逐：条目没被证伪，边构建完成后签名自然会推进并触发正常替换。
    assert svc.stats()["entries"] == 1


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
def test_estimate_bytes_is_pure() -> None:
    """字节估算是确定性纯函数：同参数任意次调用返回同一个值。

    「纯」在这里不是风格洁癖，而是准入判据成立的前提——装配**前**用 COUNT 估的那个
    数，必须与装配**后**按实际计数记进 LRU 的那个数出自同一套算术，否则准入放行的
    图会在缓存里被记成另一个数，字节预算形同虚设。
    """
    import inspect

    from services.code_graph.cache import (
        EDGE_COST_BYTES,
        NODE_COST_BYTES,
        estimate_graph_bytes,
    )

    # 2026-08-09 由 Plan 121-10 的生产库最大仓实测复校：640/560 → 800/680
    # （backend/teacher-ai-class 实测 733 B/节点、626 B/边，原值让估算低于实测常驻）。
    assert (NODE_COST_BYTES, EDGE_COST_BYTES) == (800, 680)

    expected = 100 * 800 + 300 * 680
    assert estimate_graph_bytes(100, 300) == expected
    # 连调三次结果逐字节相同（无内部状态、无随机、无时间依赖）。
    assert [estimate_graph_bytes(100, 300) for _ in range(3)] == [expected] * 3
    assert estimate_graph_bytes(0, 0) == 0

    for bad in ((-1, 0), (0, -1), (-1, -1)):
        with pytest.raises(ValueError):
            estimate_graph_bytes(*bad)

    # 签名恰为 (node_count, edge_count)：不收图对象、更不收 repository_id
    # ——收了就说明它在读外部状态，纯函数性质当场失效。
    params = list(inspect.signature(estimate_graph_bytes).parameters)
    assert params == ["node_count", "edge_count"], params


# 121-VALIDATION.md 121-07-T1（预算算术自洽性）：估算函数与 settings 默认值必须
# 讲同一套算术，否则 CODE_GRAPH_MAX_GRAPH_BYTES 的注释就是一句无人校验的散文。
def test_estimate_bytes_matches_budget_arithmetic() -> None:
    """锁死「单仓约 8.6 万符号触顶」这条容量结论。

    settings 注释写的是 ``n × (800 + 3.4×680) = n × 3112``、``256MB → 约 8.6 万符号``。
    这条断言让「有人改了常数却没改预算默认值（或反之）」当场变红——两者漂移的后果是
    准入判据放行的图比预算能装下的更大，OOM 保护静默失效。
    """
    from django.conf import settings

    from services.code_graph.cache import estimate_graph_bytes

    max_graph_bytes = int(settings.CODE_GRAPH_MAX_GRAPH_BYTES)
    # 2026-08-09 Plan 121-10 生产实测复校（假设 A2）：**准入口径**（``CallEdge`` 原始
    # 行数 / ``Symbol`` 行数，正是 ``_estimate_admission`` 用的那个口径）实测 3.40:1。
    # ⚠️ 入图口径只有 0.73:1（解析率低导致绝大多数边不入图），但准入判据看不到那个
    # 数，所以这里必须用准入口径——用入图口径会让这条断言去守一个准入判据根本不会
    # 算出来的数。触顶符号数随之从 11 万降到 8.6 万。
    ratio = estimate_graph_bytes(86_000, int(3.4 * 86_000)) / max_graph_bytes
    assert 0.9 <= ratio <= 1.1, (
        f"8.6 万符号的估算值与 CODE_GRAPH_MAX_GRAPH_BYTES 已漂移（比值 {ratio:.3f}）"
    )


# 121-VALIDATION.md 121-07-T1（标定前提留痕）：常数的标定条件必须写在代码里，
# 否则 121-10 复校时没人知道这两个数是在什么形态下测出来的。
def test_byte_constants_document_calibration() -> None:
    """常数注释含 tracemalloc / RSS / MultiDiGraph 三个关键词。

    - ``tracemalloc``：说明测量口径（不是 RSS，不含 arena 碎片）。
    - ``RSS``：说明 121-10 必须按哪个口径复校。
    - ``MultiDiGraph``：说明边成本按哪种图类型标定（``DiGraph`` 的边便宜 224 字节/条，
      照 DiGraph 标定会低估 44%）。
    """
    from pathlib import Path

    from services.code_graph import cache as cache_module

    source = Path(cache_module.__file__).read_text(encoding="utf-8")
    for keyword in ("tracemalloc", "RSS", "MultiDiGraph"):
        assert keyword in source, f"字节常数的标定条件未在代码内留痕：缺 {keyword}"


def _make_entry(node_count: int, edge_count: int):
    """造一条**真实载荷**的缓存条目（不是 Mock）。

    刻意装配真的 ``CodeGraph`` / ``GraphMeta`` 而不是塞个哑对象：``_Entry.graph`` 的
    类型契约因此有回归——将来 121-08 改动 ``GraphMeta`` 字段时，这里会一起红。
    """
    import networkx as nx
    from django.utils import timezone

    from services.code_graph.cache import _Entry, estimate_graph_bytes
    from services.code_graph.model import CodeGraph, GraphMeta

    estimated = estimate_graph_bytes(node_count, edge_count)
    graph = nx.MultiDiGraph()
    now = timezone.now()
    meta = GraphMeta(
        repository_id="repo",
        branch="",
        node_count=node_count,
        edge_count=edge_count,
        estimated_bytes=estimated,
        resolution_rate=1.0,
        low_resolution=False,
        partial_edges=False,
        partial_reason="",
        degraded="",
        cross_repo_unresolved_count=0,
        cross_repo_branch_unfiltered=False,
        excluded_file_count=0,
        built_signature="sig",
        built_at=now,
    )
    return _Entry(
        graph=CodeGraph(meta=meta, graph=graph),
        estimated_bytes=estimated,
        built_signature="sig",
        built_at=now,
    )


def _entry_bytes(node_count: int, edge_count: int) -> int:
    """``_make_entry(n, e)`` 那条条目的记账字节数。

    记账类断言一律经本函数取数，⛔ 不写死 ``1200`` / ``2400`` 这类字面量：那些数字是
    ``NODE_COST_BYTES`` / ``EDGE_COST_BYTES`` 的**派生值**，而两个常数按设计会被
    「最大仓实测」复校（2026-08-09 Plan 121-10 已复校过一次，640/560 → 760/720）。
    写死字面量会让每次复校都顺带打红一批与逐出逻辑毫无关系的用例——那不是回归，是耦合。
    """
    from services.code_graph.cache import estimate_graph_bytes

    return estimate_graph_bytes(node_count, edge_count)


# 121-VALIDATION.md 121-07-T2：超预算时按 LRU 顺序逐出至 ≤ 预算，
# 并发 code_graph_cache_evicted 事件。
def test_evict_lru_until_within_budget() -> None:
    """超预算时从 LRU 端**循环**逐出，直到总字节回到预算内，并发结构化逐出事件。

    这条是 GRAPH-03「进程不 OOM」的核心回归：逐出若是「一次一个」而非「逐到预算内」，
    缓存就会长期停在超预算状态——那正是 OOM 的形状。
    """
    from structlog.testing import capture_logs

    from services.code_graph.cache import GraphService

    unit = _entry_bytes(1, 1)
    # 预算刚好装得下 2 条、装不下 3 条 —— 用单条目字节数推算，⛔ 不写死字面量
    # （字节常数会被最大仓实测复校，见 :func:`_entry_bytes`）。
    budget = 2 * unit + unit // 2
    svc = GraphService(max_bytes=budget, max_graph_bytes=budget)
    # 载荷是真图，字节数必须真的被记进条目（121-05 的显式待办：estimated_bytes
    # 若恒为 0，LRU 会把每张图都记成 0 字节、永远逐不出东西）。
    assert _make_entry(1, 1).estimated_bytes == unit > 0

    with capture_logs() as events:
        for name in ("a", "b", "c"):
            svc._put((name, ""), _make_entry(1, 1))

    # 3 × unit > 预算 ⇒ 最早写入的 a 被逐出，剩 2 × unit ≤ 预算。
    stats = svc.stats()
    assert stats["total_bytes"] == 2 * unit
    assert stats["total_bytes"] <= budget
    assert stats["entries"] == 2
    assert list(svc._cache.keys()) == [("b", ""), ("c", "")]

    evicted = [e for e in events if e["event"] == "code_graph_cache_evicted"]
    assert len(evicted) == 1
    assert evicted[0]["component"] == "code_graph"
    assert evicted[0]["category"] == "sampling"
    assert evicted[0]["repository_id"] == "a"
    assert evicted[0]["evicted_bytes"] == unit
    assert evicted[0]["total_bytes"] == 2 * unit
    assert evicted[0]["reason"] == "budget_exceeded"


def test_evict_loop_drops_multiple_entries() -> None:
    """一个大条目要挤掉**两个**旧条目时，两个都得走——``while`` 而不是 ``if``。"""
    from services.code_graph.cache import GraphService

    unit = _entry_bytes(1, 1)
    budget = 2 * unit + unit // 2
    svc = GraphService(max_bytes=budget, max_graph_bytes=10 * unit)
    svc._put(("a", ""), _make_entry(1, 1))  # 1 × unit
    svc._put(("b", ""), _make_entry(1, 1))  # 2 × unit
    assert svc.stats()["entries"] == 2

    # 双倍大的条目挤进来 ⇒ 4 × unit > 预算，必须连逐两个才能回到预算内。
    svc._put(("big", ""), _make_entry(2, 2))

    assert list(svc._cache.keys()) == [("big", "")]
    assert svc.stats()["total_bytes"] == 2 * unit <= budget


def test_get_entry_moves_to_end_on_hit() -> None:
    """命中把条目推到 MRU 端（照 ``test_volar_pool.py::test_get_move_to_end_on_hit``）。

    没有这一步的话，``OrderedDict`` 退化成 FIFO：一张被反复使用的热图会仅仅因为「写入
    得早」而被逐出，缓存命中率随之塌掉。
    """
    from services.code_graph.cache import GraphService

    svc = GraphService(max_bytes=100_000, max_graph_bytes=100_000)
    for name in ("a", "b", "c"):
        svc._put((name, ""), _make_entry(1, 1))
    assert list(svc._cache.keys()) == [("a", ""), ("b", ""), ("c", "")]

    hit = svc._get_entry(("a", ""))
    assert hit is not None
    assert list(svc._cache.keys()) == [("b", ""), ("c", ""), ("a", "")]

    assert svc._get_entry(("missing", "")) is None


def test_put_overwrite_does_not_double_count() -> None:
    """同键覆盖写入不重复计账（威胁登记 T-121-记账漂移）。

    漏掉「先减旧条目」的话，同一个仓库反复重建会让 ``_total_bytes`` 单调虚增，最终把
    缓存逐空了还是「超预算」——一个空缓存永远在逐出，比不缓存更糟。
    """
    from services.code_graph.cache import GraphService

    svc = GraphService(max_bytes=100_000, max_graph_bytes=100_000)
    svc._put(("a", ""), _make_entry(1, 1))
    svc._put(("a", ""), _make_entry(1, 1))

    assert svc.stats() == {
        "entries": 1,
        "total_bytes": _entry_bytes(1, 1),
        "max_bytes": 100_000,
    }

    # 覆盖成一个更小的条目时同样要减对（不是只加不减）。
    svc._put(("a", ""), _make_entry(1, 0))
    assert svc.stats()["total_bytes"] == _entry_bytes(1, 0)


def test_graph_service_rejects_non_positive_budgets() -> None:
    """预算 ≤ 0 直接抛（照 ``volar_pool.VolarPool.__init__``）。

    ``max_bytes=0`` 若被放行，每次写入都会立刻把刚写进去的条目逐掉——缓存表面在工作、
    实际命中率恒为 0，是最难被发现的那种失效。
    """
    from services.code_graph.cache import GraphService

    for bad in ({"max_bytes": 0}, {"max_bytes": -1}, {"max_graph_bytes": 0}):
        kwargs = {"max_bytes": 1024, "max_graph_bytes": 1024} | bad
        with pytest.raises(ValueError):
            GraphService(**kwargs)


def test_lock_discipline_documented_and_no_await() -> None:
    """锁纪律有代码内留痕；``async``/``await`` 被限制在唯一的外壳里。

    「临界区零 await」不是洁癖：只要有一个 ``await`` 落在持锁区间内，多 event loop 下
    就会出现「A 持锁挂起、B 在另一个 loop 里等同一把锁」的死锁（D-04 / Pitfall 7）。
    把整段临界区做成同步函数、由**唯一一次** ``sync_to_async`` 包裹，让这件事在物理上
    不可能发生。本用例把这个形状锁死：

    - 模块里**恰好一个** ``async def``，名字必须是 ``get_graph``（外壳）。
    - 全部 ``await`` 都在那个外壳里；``_get_graph_sync`` 及其下游零 ``await``。
    - ``sync_to_async(`` 恰好出现一次——两次就意味着有第二个 async/sync 边界。
    - 无 ``AsyncWith`` / ``AsyncFor``，且未 import ``asyncio``。

    ⚠️ 判据走 **AST** 而不是 ``grep -c 'await'``：模块 docstring 里那条禁令本身就含
    「绝不 await」四个字（plan 明确要求写进去），字面 grep 与该要求自相矛盾。AST 断言
    比 grep 更严——它连字符串拼出来的都不放过。
    """
    import ast
    from pathlib import Path

    from services.code_graph import cache as cache_module

    source = Path(cache_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=cache_module.__file__)

    async_defs = [
        node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef)
    ]
    assert [node.name for node in async_defs] == ["get_graph"], (
        "本模块只允许 get_graph 一个 async 外壳，其余一律同步"
    )

    blocking = [
        f"{type(node).__name__}:{node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncWith, ast.AsyncFor))
    ]
    assert not blocking, f"发现不该存在的异步构造：{blocking}"

    # 全部 await 都必须落在外壳内部：临界区里出现一个就足以让持锁与挂起重叠。
    shell_awaits = {
        id(node) for node in ast.walk(async_defs[0]) if isinstance(node, ast.Await)
    }
    stray = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Await) and id(node) not in shell_awaits
    ]
    assert not stray, f"await 出现在 get_graph 之外（行 {stray}）"

    # 唯一的 async/sync 边界，且不显式传 thread_sensitive（取默认 True，与全仓 ORM 一致）。
    assert source.count("sync_to_async(") == 1
    boundary_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "sync_to_async"
    ]
    assert len(boundary_calls) == 1
    assert not [kw.arg for kw in boundary_calls[0].keywords], (
        "sync_to_async 不该显式传参——thread_sensitive 取默认 True，与全仓 ORM 调用一致"
    )

    # asyncio 同步原语同样禁用：它们绑定创建时的 loop，而 GraphService 是进程级单例、
    # 会被本仓三类 loop 共用，跨 loop 使用直接 RuntimeError（D-04 / Pitfall 8）。
    # 同样走 AST 而非 grep —— 模块 docstring 边界③ 那条禁令本身就写着
    # 「⛔ 不用 asyncio.Lock / asyncio.Event」，字面 grep 会命中禁令自己。
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "asyncio" not in imported, "本模块不得 import asyncio（锁原语一律 threading）"
    assert "threading" in imported
    # single-flight 的等待信号必须是 loop 无关的 threading.Event（D-04 / Pitfall 8）。
    assert "threading.Event" in source

    for method in (cache_module.GraphService._evict_until_within_budget,
                   cache_module.GraphService._get_entry,
                   cache_module.GraphService._put):
        assert "调用方必须已持锁" in (method.__doc__ or ""), method.__name__


# 121-VALIDATION.md 121-07-T3：模块级单例 + 测试重置钩子。
def test_get_graph_service_is_singleton() -> None:
    """连调两次拿到**同一个对象**——否则每个调用方各持一份缓存，预算立刻失去意义。"""
    from services.code_graph.cache import get_graph_service

    assert get_graph_service() is get_graph_service()


def test_get_graph_service_reads_settings_lazily() -> None:
    """预算在**首次调用时**才读 settings，不是 import 时固化。

    import 时求值会在 Django settings 完全就绪前拿到默认值并永久钉死，
    ``override_settings`` 从此改不动它——运维调了环境变量却不生效，且没有任何报错。
    """
    from django.test import override_settings

    from services.code_graph.cache import _reset_for_tests, get_graph_service

    with override_settings(CODE_GRAPH_CACHE_MAX_BYTES=4096):
        _reset_for_tests()
        assert get_graph_service()._max_bytes == 4096

    _reset_for_tests()
    assert get_graph_service()._max_bytes != 4096


def test_reset_for_tests_returns_fresh_service() -> None:
    """重置后拿到的是**新对象**且缓存为空。"""
    from services.code_graph.cache import _reset_for_tests, get_graph_service

    first = get_graph_service()
    first._put(("repo", ""), _make_entry(1, 1))
    assert first.stats()["entries"] == 1

    _reset_for_tests()

    second = get_graph_service()
    assert second is not first
    assert second.stats()["entries"] == 0
    # 旧引用也被清空：只换指针的话，先前已拿到 first 的调用方会继续带着旧条目跑。
    assert first.stats() == {"entries": 0, "total_bytes": 0, "max_bytes": first._max_bytes}


# 下面两条**成对**存在：单独看任一条都会通过，合起来才证明「用例间无污染」。
# 顺序无关——两条各自写入后都断言自己看到的是空缓存，谁先跑都一样。
def test_singleton_isolation_first_writer() -> None:
    from services.code_graph.cache import get_graph_service

    svc = get_graph_service()
    assert svc.stats()["entries"] == 0, "看到了上一个用例留下的条目——autouse 重置失效"
    svc._put(("isolation-a", ""), _make_entry(1, 1))
    assert svc.stats()["entries"] == 1


def test_singleton_isolation_second_writer() -> None:
    from services.code_graph.cache import get_graph_service

    svc = get_graph_service()
    assert svc.stats()["entries"] == 0, "看到了上一个用例留下的条目——autouse 重置失效"
    svc._put(("isolation-b", ""), _make_entry(1, 1))
    assert svc.stats()["entries"] == 1


def test_conftest_autouse_fixture_calls_reset() -> None:
    """autouse fixture 确实调了 ``_reset_for_tests``（隔离靠它，不靠自觉）。"""
    from pathlib import Path

    conftest = Path(__file__).with_name("conftest.py").read_text(encoding="utf-8")
    assert conftest.count("_reset_for_tests") >= 1
    assert "待 121-07" not in conftest and "Plan 121-07 交付" not in conftest


def _make_code_graph():
    """并发用例的**纯内存**图载荷（真 ``CodeGraph``，不碰数据库）。"""
    return _make_entry(1, 1).graph


class _NoopMatcher:
    """``ExclusionMatcher`` 的最小替身：什么都不排除，且不读 DB、不编译正则。"""

    def is_excluded(self, file_path: str) -> bool:
        return False


@pytest.fixture
def no_db_graph_build(monkeypatch):
    """把 ``_get_graph_sync`` 的**全部四个 DB 触点**一次性 patch 掉，并装上零 SQL 兜底。

    并发用例必须全程不碰数据库：测试库是文件/连接级共享资源，4 个线程同时打进去会重现
    ``121-VALIDATION.md`` 警告的那类 flaky（照 ``codegraph/lsp/tests/test_volar_pool.py``
    的范式，该用例同样不碰库）。清单恰好四项，少 patch 一项就会漏出去：

    1. ``access.build_matcher_and_fingerprint``（内部有 ``_resolve_effective_specs``
       的 DB 读 + 该仓全部 glob/regex 编译）
    2. ``signature.compute_signature``（水位 / 两条轨 / 两条 COUNT）
    3. ``signature.detect_edge_build_in_flight``（两条轨的状态读）
    4. ``GraphService._estimate_admission``（Task 2 建的单一接缝，覆盖两条准入 COUNT）

    ⚠️ ``access.ensure_repository_readable`` 不在清单内：它是 ``async``、只在 ``get_graph``
    外壳里调用，而并发线程直接进入的是 ``_get_graph_sync``，不经过它。

    **兜底为什么不用 ``CaptureQueriesContext``**：它抓的是**本线程**连接上的查询，而
    这里的查询恰恰发生在 worker 线程里——用它做断言会对本用例要防的那类回归**恒真**。
    改为在 ``CursorWrapper.execute`` 上装一个进程级计数器：它与线程、连接都无关，任何
    线程发出的任何一条 SQL 都会被记下。若将来 ``_get_graph_sync`` 新增 DB 触点，这条
    断言会立刻失败并逼迫补 patch —— ⛔ 不要为了让用例过而放宽它。
    """
    from django.db.backends.utils import CursorWrapper

    from services.code_graph import access as access_module
    from services.code_graph import cache as cache_module
    from services.code_graph import signature as signature_module

    monkeypatch.setattr(
        access_module,
        "build_matcher_and_fingerprint",
        lambda repository_id: (_NoopMatcher(), "fp-fixed"),
    )
    monkeypatch.setattr(
        signature_module,
        "compute_signature",
        lambda repository_id, branch, *, exclusion_fingerprint: "sig-fixed",
    )
    monkeypatch.setattr(
        signature_module,
        "detect_edge_build_in_flight",
        lambda repository_id, branch: (False, ""),
    )
    monkeypatch.setattr(
        cache_module.GraphService,
        "_estimate_admission",
        lambda self, repository_id, branch: (10, 20, 1024),
    )

    executed: list[str] = []
    real_execute = CursorWrapper.execute

    def _record(self, sql, params=None):
        executed.append(sql)
        return real_execute(self, sql, params)

    monkeypatch.setattr(CursorWrapper, "execute", _record)
    yield executed
    assert executed == [], f"并发取图路径打了数据库：{executed[:3]}"


def _run_concurrently(worker, count: int = 4) -> None:
    """``threading.Barrier`` 对齐起跑，全部 ``join(timeout=5.0)`` 兜底。

    对齐起跑是确定性的关键：不对齐的话线程可能串行跑完，「只建一次」会因为第二个线程
    命中缓存而**假绿**——那样连 single-flight 都不需要就能通过。
    """
    barrier = threading.Barrier(count)
    threads = [threading.Thread(target=worker, args=(barrier,)) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5.0)
    assert not [t for t in threads if t.is_alive()], "有线程没在 5 秒内结束（疑似永久挂起）"


# 121-VALIDATION.md 121-08-T3：N 个并发请求同一 key ⇒ builder 只被调用一次
# （内存假 builder + 零 DB 查询断言）。
def test_single_flight_builds_once(no_db_graph_build, monkeypatch) -> None:
    """4 个并发请求同一 key ⇒ 装配只发生一次，4 个返回值全是**同一个对象**。

    范式照 ``codegraph/lsp/tests/test_volar_pool.py::test_concurrent_get_no_double_build``。
    """
    from structlog.testing import capture_logs

    from services.code_graph import cache as cache_module
    from services.code_graph import loader as loader_module

    build_count = 0
    count_lock = threading.Lock()

    def _fake_load_graph(repository_id, branch="", **kwargs):
        nonlocal build_count
        with count_lock:
            build_count += 1
        # 装配窗口：让后来者确实撞进「领头正在建」的那一刻。
        time.sleep(0.05)
        return _make_code_graph()

    monkeypatch.setattr(loader_module, "load_graph", _fake_load_graph)

    svc = cache_module.get_graph_service()
    results: list[object] = []
    errors: list[BaseException] = []

    def _worker(barrier: threading.Barrier) -> None:
        barrier.wait(timeout=5.0)
        try:
            results.append(svc._get_graph_sync("repo", "", False, (), None, "system"))
        except BaseException as exc:  # noqa: BLE001 — 用例要把异常带回主线程断言
            errors.append(exc)

    with capture_logs():
        _run_concurrently(_worker)

    assert not errors, errors
    assert build_count == 1, f"同 key 并发装配了 {build_count} 次——single-flight 没生效"
    assert len(results) == 4
    assert all(item is results[0] for item in results)
    # 领头装配期间等待者能拿到占位（而不是被 map 锁卡在入口）：只有装配在锁外进行
    # 才可能出现「4 个线程都进到等待/返回阶段」这个结果。
    assert svc._inflight == {}


# 121-VALIDATION.md 121-08-T3：构建失败 ⇒ 所有等待者各自抛，
# 且失败不进缓存（不毒化后续请求）。
def test_build_failure_not_cached(no_db_graph_build, monkeypatch) -> None:
    """领头失败 ⇒ 4 个并发请求**各自**抛出；失败不进缓存、不留占位、下次可重试成功。"""
    from structlog.testing import capture_logs

    from services.code_graph import cache as cache_module
    from services.code_graph import loader as loader_module
    from services.code_graph.model import GraphBuildFailed

    def _failing_load_graph(repository_id, branch="", **kwargs):
        time.sleep(0.05)
        raise RuntimeError("装配炸了")

    monkeypatch.setattr(loader_module, "load_graph", _failing_load_graph)

    svc = cache_module.get_graph_service()
    errors: list[BaseException] = []
    results: list[object] = []

    def _worker(barrier: threading.Barrier) -> None:
        barrier.wait(timeout=5.0)
        try:
            results.append(svc._get_graph_sync("repo", "", False, (), None, "system"))
        except BaseException as exc:  # noqa: BLE001 — 用例要把异常带回主线程断言
            errors.append(exc)

    with capture_logs() as events:
        _run_concurrently(_worker)

    assert not results, "构建失败却有请求拿到了图"
    assert len(errors) == 4, "有请求既没拿到图也没抛异常（多半是永久挂起后被 join 放弃）"
    # 领头抛原异常，等待者抛 GraphBuildFailed（原异常挂在 __cause__ 上供排障）。
    assert any(isinstance(exc, RuntimeError) for exc in errors)
    waiter_errors = [exc for exc in errors if isinstance(exc, GraphBuildFailed)]
    assert len(waiter_errors) == 3
    assert all(isinstance(exc.__cause__, RuntimeError) for exc in waiter_errors)

    failed = [e for e in events if e["event"] == "code_graph_build_failed"]
    assert len(failed) == 1
    assert failed[0]["error_type"] == "RuntimeError"
    assert failed[0]["waiters"] == 3

    assert svc.stats()["entries"] == 0, "失败结果进了缓存"
    assert svc._inflight == {}, "失败占位没弹出——下一个请求会挂在一个永不 set 的 event 上"

    # 失败未毒化：换成成功实现后立刻能建出来。
    monkeypatch.setattr(
        loader_module,
        "load_graph",
        lambda repository_id, branch="", **kwargs: _make_code_graph(),
    )
    with capture_logs():
        retried = svc._get_graph_sync("repo", "", False, (), None, "system")
    assert retried is not None
    assert svc.stats()["entries"] == 1


def test_single_flight_waiter_times_out(no_db_graph_build, monkeypatch) -> None:
    """领头卡住时等待者**超时抛错**，而不是永久挂起。

    超时是必需的而非可选：领头请求随时可能被 kill（最典型的是 ASGI 断连取消），
    没有上界的话等待者会一直挂在一个永不 ``set`` 的 event 上，一个卡死的构建就能
    把该 key 的所有后续请求拖死。
    """
    from django.test import override_settings
    from structlog.testing import capture_logs

    from services.code_graph import cache as cache_module
    from services.code_graph import loader as loader_module
    from services.code_graph.model import GraphBuildTimeout

    release = threading.Event()

    def _blocking_load_graph(repository_id, branch="", **kwargs):
        release.wait(timeout=5.0)
        return _make_code_graph()

    monkeypatch.setattr(loader_module, "load_graph", _blocking_load_graph)

    svc = cache_module.get_graph_service()
    leader = threading.Thread(
        target=lambda: svc._get_graph_sync("repo", "", False, (), None, "system")
    )
    with capture_logs():
        leader.start()
        deadline = time.monotonic() + 5.0
        while not svc._inflight and time.monotonic() < deadline:
            time.sleep(0.01)
        assert svc._inflight, "领头没能在 5 秒内登记占位"

        with override_settings(CODE_GRAPH_BUILD_WAIT_TIMEOUT_SECONDS=0):
            with pytest.raises(GraphBuildTimeout):
                svc._get_graph_sync("repo", "", False, (), None, "system")

        release.set()
        leader.join(timeout=5.0)
    assert not leader.is_alive()


# 121-VALIDATION.md 121-08-T2：单图估算 > CODE_GRAPH_MAX_GRAPH_BYTES ⇒ 不进缓存
# + degraded="on_demand_subgraph"，由上层工具透出。
@pytest.mark.django_db(transaction=True)
async def test_degraded_on_demand_subgraph(indexed_repo, symbols_factory) -> None:
    """超单图预算 ⇒ 走按需子图、不进缓存；**无种子时显式抛错**，不返回空图或截断图。

    准入必须发生在**装配之前**：``load_graph`` 的 spy 全程 ``call_count == 0``，
    证明没有「先全量装配出来再判断多大」——那就是「先 OOM 再逐出」，OOM 之后逐出
    已经救不回来了。
    """
    from unittest import mock

    from asgiref.sync import sync_to_async
    from django.test import override_settings

    from services.code_graph import cache as cache_module
    from services.code_graph import loader as loader_module
    from services.code_graph.model import GraphError

    def _seed():
        return symbols_factory("a", "src/a.py")

    seed = await sync_to_async(_seed)()
    repo_id = str(indexed_repo.id)

    # 单图上限 1 字节：一个符号（640 字节）就已经触顶。
    with override_settings(CODE_GRAPH_MAX_GRAPH_BYTES=1):
        cache_module._reset_for_tests()
        svc = cache_module.get_graph_service()

        with mock.patch.object(
            loader_module, "load_graph", wraps=loader_module.load_graph
        ) as load_spy:
            degraded = await svc.get_graph(repo_id, seed_symbol_ids=[str(seed.id)])

            assert degraded.meta.degraded == "on_demand_subgraph"
            assert svc.stats()["entries"] == 0, (
                "子图进了缓存——它依赖种子与深度，而缓存键里没有这两维"
            )
            assert load_spy.call_count == 0, "先全量装配再判断大小 = 先 OOM 再逐出"

            with pytest.raises(GraphError) as excinfo:
                await svc.get_graph(repo_id)

            assert "seed_symbol_ids" in str(excinfo.value)
            assert load_spy.call_count == 0


@pytest.mark.django_db
def test_admission_seam_covers_both_counts(indexed_repo, symbols_factory) -> None:
    """``_estimate_admission`` 是准入 COUNT 的**唯一**接缝，可被整体 stub 掉。

    判据是「打桩前后 ``Symbol`` / ``CallEdge`` 的 COUNT 查询数正好差 2」：打桩后剩下的
    那 2 条来自 ``signature.compute_signature`` 的计数分量（它有自己的职责，不归本接缝
    管）。若有人把某一条 COUNT 内联回 ``_build_graph``，差值会变成 1，用例立刻红——
    而 Task 3 的并发用例正是靠「patch 掉这一个接缝就不再碰库」才能确定性通过。

    直接调同步主体而不是 ``get_graph``：``CaptureQueriesContext`` 抓的是**本线程**的
    连接，而 ``sync_to_async`` 会把主体派发到执行器线程上，隔着线程抓不到。
    """
    from unittest import mock

    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from services.code_graph import cache as cache_module

    symbols_factory("a", "src/a.py")
    svc = cache_module.get_graph_service()
    repo_id = str(indexed_repo.id)

    def _count_admission_queries(ctx) -> int:
        return sum(
            1
            for q in ctx.captured_queries
            if "COUNT" in q["sql"].upper()
            and ("codegraph_symbol" in q["sql"] or "codegraph_calledge" in q["sql"])
        )

    with CaptureQueriesContext(connection) as baseline:
        svc._get_graph_sync(repo_id, "", False, (), None, "system")
    cache_module._reset_for_tests()
    svc = cache_module.get_graph_service()

    with mock.patch.object(
        cache_module.GraphService, "_estimate_admission", return_value=(1, 1, 1024)
    ) as seam:
        with CaptureQueriesContext(connection) as stubbed:
            svc._get_graph_sync(repo_id, "", False, (), None, "system")

    assert seam.call_count == 1
    assert _count_admission_queries(baseline) - _count_admission_queries(stubbed) == 2, (
        "准入 COUNT 没有全部收进 _estimate_admission —— 并发用例的零查询断言会漏掉它"
    )


@pytest.mark.django_db
def test_build_completed_event_carries_required_kv(indexed_repo, symbols_factory) -> None:
    """``code_graph_build_completed`` 的 kv 覆盖规范要求的全部字段。

    ``duration_ms`` 是 ``.cursor/rules/observability-logging.mdc`` 对关键生命周期事件的
    硬要求；``partial_edges`` / ``degraded`` 则决定这张图能不能被上层全信——少一个，
    排障就得回头翻三个模块的 DEBUG 事件去拼。
    """
    from structlog.testing import capture_logs

    from services.code_graph import cache as cache_module

    symbols_factory("a", "src/a.py")
    svc = cache_module.get_graph_service()

    with capture_logs() as events:
        svc._get_graph_sync(str(indexed_repo.id), "", False, (), None, "system")

    completed = [e for e in events if e["event"] == "code_graph_build_completed"]
    assert len(completed) == 1
    required = {
        "component",
        "category",
        "duration_ms",
        "node_count",
        "edge_count",
        "estimated_bytes",
        "resolution_rate",
        "partial_edges",
        "degraded",
        "cross_repo_unresolved_count",
        "initiated_by_user_id",
    }
    assert required <= set(completed[0]), required - set(completed[0])
    assert completed[0]["component"] == "code_graph"
    assert completed[0]["category"] == "sampling"
    assert completed[0]["initiated_by_user_id"] == "system"


def test_cache_has_no_hand_rolled_inflight_judgement() -> None:
    """in-flight 判据只能来自 ``signature.detect_edge_build_in_flight``（D-03）。

    ``IndexHistory.graph_build_status`` 的**模型默认值就是 ``PENDING``**，照字面在
    cache.py 里另写一份「PENDING 即在途」会让从未触发过边构建的仓库永久带
    ``partial_edges: true``——降级标记长鸣就等于失效（威胁登记 T-121-长鸣）。
    """
    from pathlib import Path

    from services.code_graph import cache as cache_module

    source = Path(cache_module.__file__).read_text(encoding="utf-8")
    assert "detect_edge_build_in_flight" in source
    # ⚠️ 判据用「不引用状态字段名」而非 grep 禁令散文：注释里点名 ``graph_build_status``
    #    是 plan 明确要求写下的 D-03 说明，字面 grep 会命中那句说明自己。这里只禁**代码**
    #    引用——注释与 docstring 全部剥掉之后再看。
    import ast

    tree = ast.parse(source, filename=cache_module.__file__)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        )
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    code_strings = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]
    names = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    } | {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert "graph_build_status" not in names
    assert not [s for s in code_strings if "graph_build_status" in s]


# 121-VALIDATION.md 121-09-T1：GraphService.invalidate 按仓驱逐全部分支条目
# 并连带清 matcher/指纹 memo；异常吞掉不反噬主流程。
def test_invalidate_evicts_repo_entries() -> None:
    """``invalidate(A)`` 驱逐 A 的**所有分支**条目、放过 B，并连带清 A 的指纹 memo。

    三件事各守一条：

    - **按仓而非按键**驱逐：重索引影响该仓所有分支的图（overlay 语义下 feature 分支的
      图 = base 全量 + 分支增量），只驱逐 ``(repo, "")`` 会让 feature 分支继续命中旧图。
    - **只驱逐命中的那个仓**：钩子带的是单个 ``repository_id``，误清全表等于让本 worker
      上所有其它仓库的图一起冷建 2–4 秒。
    - **指纹 memo 一并清**：规则若刚变过而 ``access`` 的 60s memo 仍是旧指纹，签名复校
      算出的签名会与旧条目恰好一致——只清图不清指纹，下一次取图照样命中陈旧图。
    """
    from unittest import mock

    from structlog.testing import capture_logs

    from services.code_graph import access as access_module
    from services.code_graph.cache import GraphService

    svc = GraphService(max_bytes=100_000, max_graph_bytes=100_000)
    svc._put(("repo-a", ""), _make_entry(1, 1))
    svc._put(("repo-a", "feature/x"), _make_entry(1, 1))
    svc._put(("repo-b", ""), _make_entry(1, 1))
    unit = _entry_bytes(1, 1)
    assert svc.stats() == {
        "entries": 3,
        "total_bytes": 3 * unit,
        "max_bytes": 100_000,
    }

    with (
        mock.patch.object(
            access_module,
            "invalidate_matcher_fingerprint_cache",
            wraps=access_module.invalidate_matcher_fingerprint_cache,
        ) as memo_spy,
        capture_logs() as events,
    ):
        svc.invalidate("repo-a")

    assert list(svc._cache.keys()) == [("repo-b", "")], "repo-a 的分支条目没被清干净"
    assert svc.stats()["total_bytes"] == unit, "记账没跟着驱逐一起扣减"

    memo_spy.assert_called_once_with(repository_id="repo-a")

    invalidated = [e for e in events if e["event"] == "code_graph_cache_invalidated"]
    assert len(invalidated) == 1, "汇总事件应当只发一条（⛔ 不是每条目一条）"
    assert invalidated[0]["component"] == "code_graph"
    assert invalidated[0]["category"] == "sampling"
    assert invalidated[0]["repository_id"] == "repo-a"
    assert invalidated[0]["evicted_entries"] == 2
    assert invalidated[0]["evicted_bytes"] == 2 * unit
    assert invalidated[0]["total_bytes"] == unit
    # 钩子跑在后台任务上下文，无触发用户 ⇒ 显式记 system（LOGGING-SPEC §3 强制）。
    assert invalidated[0]["initiated_by_user_id"] == "system"

    # 幂等：同一个仓再失效一次不报错、不把记账做成负数。
    svc.invalidate("repo-a")
    assert svc.stats() == {"entries": 1, "total_bytes": unit, "max_bytes": 100_000}


def test_invalidate_swallows_errors_and_never_breaks_the_hook() -> None:
    """失效失败**不向调用方抛**，只留一条 warning —— 钩子绝不反噬构建主流程。

    两层都要吞：``GraphService.invalidate`` 内部（memo 清理抛异常）与模块级
    ``invalidate_repository``（拿单例或调用方法本身抛异常）。少吞一层，一次缓存维护
    故障就会把边构建 / 图谱构建的**成功出口**变成失败——而失效本来只是优化，正确性由
    取图时的签名复校兜住。
    """
    from unittest import mock

    from structlog.testing import capture_logs

    from services.code_graph import access as access_module
    from services.code_graph import cache as cache_module
    from services.code_graph.cache import GraphService, invalidate_repository

    # ① 方法内部失败（memo 清理抛）：条目照样被驱逐，异常不外泄。
    svc = GraphService(max_bytes=100_000, max_graph_bytes=100_000)
    svc._put(("repo-a", ""), _make_entry(1, 1))
    with (
        mock.patch.object(
            access_module,
            "invalidate_matcher_fingerprint_cache",
            side_effect=RuntimeError("memo boom"),
        ),
        capture_logs() as events,
    ):
        svc.invalidate("repo-a")  # ⛔ 不得抛

    failures = [e for e in events if e["event"] == "code_graph_cache_invalidate_failed"]
    assert len(failures) == 1
    assert failures[0]["component"] == "code_graph"
    assert failures[0]["category"] == "sampling"
    assert failures[0]["error_type"] == "RuntimeError"
    assert failures[0]["initiated_by_user_id"] == "system"

    # ② 模块级入口失败（单例/方法整体抛）：同样不外泄。
    with (
        mock.patch.object(
            cache_module,
            "get_graph_service",
            side_effect=RuntimeError("singleton boom"),
        ),
        capture_logs() as events,
    ):
        invalidate_repository("repo-a")  # ⛔ 不得抛

    failures = [e for e in events if e["event"] == "code_graph_cache_invalidate_failed"]
    assert len(failures) == 1
    assert failures[0]["error_type"] == "RuntimeError"


def test_invalidate_repository_delegates_to_the_singleton() -> None:
    """模块级 ``invalidate_repository`` 打的是**进程单例**，不是新实例。

    钩子只拿到一个 ``repository_id``，没有 service 句柄；若这里误建新实例，驱逐就会打在
    一个空缓存上、本 worker 的旧图一条都不掉，钩子表面成功、实际全空转。
    """
    from services.code_graph import invalidate_repository
    from services.code_graph.cache import get_graph_service

    svc = get_graph_service()
    svc._put(("repo-a", ""), _make_entry(1, 1))
    svc._put(("repo-b", ""), _make_entry(1, 1))

    invalidate_repository("repo-a")

    assert list(svc._cache.keys()) == [("repo-b", "")]


