"""统一摄取核心测试（Plan 13-02，INGEST-06/07/08）。

调度层（Task 1，A1 首验）：async 上下文经 ``sync_to_async`` 注册
``transaction.on_commit`` 的投递边界——autocommit 立即投递 / rollback 丢弃 /
异常永不上抛（"永不阻塞主流程"纪律）。

执行体（Task 2）：六步版本翻转事务序 + 四层幂等 + 边精细置位
（首摄 / 幂等三连发 / 版本翻转 / chaos 注入 / embedding abort / 边自愈）。

测试纪律（RESEARCH Pitfall 5/6）：执行体测试一律直接 ``await ingest_events(...)``
绕过调度层，不真跑 background worker 线程写库；Qdrant / embedding 全 mock，
``--disable-socket`` 是第二道保险。
"""

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import async_to_sync, sync_to_async
from django.db import transaction
from django.utils import timezone
from structlog.testing import capture_logs

from knowledge.collection import (
    KNOWLEDGE_PAYLOAD_INDEXED_FIELDS,
    KNOWLEDGE_PAYLOAD_REQUIRED_FIELDS,
)
from knowledge.exceptions import KnowledgeError
from knowledge.ingestion import (
    EdgeSpec,
    IngestionEvent,
    IngestionRequest,
    aschedule_ingestion,
    ingest,
    ingest_events,
    revectorize_version,
)
from knowledge.models import (
    KnowledgeEdge,
    KnowledgeEntity,
    KnowledgeEntityVersion,
    generate_entity_id,
)
from knowledge.sources import get_normalizer

# SQLite + async（sync_to_async 跨线程）需要 transaction=True；
# 同时 on_commit 边界用例（autocommit 立即执行语义）也依赖真实事务。
pytestmark = pytest.mark.django_db(transaction=True)


def make_event(**kw) -> IngestionEvent:
    """IngestionEvent 工厂：默认 tech_plan / coding_plan，event_time 取当下。"""
    defaults: dict = {
        "kind": "tech_plan",
        "origin": "chat",
        "source_kind": "coding_plan",
        "source_id": "plan-1",
        "title": "测试方案",
        "content": "## 背景\n\n方案正文",
        "payload": {"title": "测试方案"},
        "space_id": None,
        "repository_id": None,
        "event_time": timezone.now(),
        "edges": (),
    }
    defaults.update(kw)
    return IngestionEvent(**defaults)


@pytest.fixture
def mock_ensure(monkeypatch) -> AsyncMock:
    """ensure_delivery_knowledge_collection 的 AsyncMock seam（不触 Qdrant）。"""
    ensure = AsyncMock()
    monkeypatch.setattr("knowledge.ingestion.ensure_delivery_knowledge_collection", ensure)
    return ensure


@pytest.fixture
def mock_upsert(monkeypatch) -> list[list[str]]:
    """upsert_vectors_by_name 计数 seam：记录每批 point id 列表并返回 True。"""
    from services.qdrant_service import QdrantService

    calls: list[list[str]] = []

    def _fake(cls, name, pts):
        calls.append([p["id"] for p in pts])
        return True

    monkeypatch.setattr(QdrantService, "upsert_vectors_by_name", classmethod(_fake))
    return calls


# ============================================================================
# Task 1：调度层（aschedule_ingestion，A1 首验）
# ============================================================================


async def test_schedule_delivers_immediately_under_autocommit(monkeypatch) -> None:
    """A1 首验：autocommit 下 await 返回后 run_in_background 已被调用，name 含定位信息。"""
    submitted: list[str | None] = []
    monkeypatch.setattr(
        "knowledge.ingestion.run_in_background",
        lambda factory, *, name=None, initiated_by_user_id=None: submitted.append(name),
    )
    await aschedule_ingestion(IngestionRequest("coding_plan", "abc-123", "chat_plan_created"))
    assert len(submitted) == 1
    assert "coding_plan" in (submitted[0] or "")
    assert "abc-123" in (submitted[0] or "")


def test_schedule_not_delivered_on_rollback(monkeypatch) -> None:
    """A1 边界：atomic 块内注册、块内 raise 回滚后，run_in_background 未被调用。"""
    submitted: list[str | None] = []
    monkeypatch.setattr(
        "knowledge.ingestion.run_in_background",
        lambda factory, *, name=None, initiated_by_user_id=None: submitted.append(name),
    )
    with pytest.raises(RuntimeError, match="force rollback"):
        with transaction.atomic():
            async_to_sync(aschedule_ingestion)(
                IngestionRequest("coding_plan", "abc-123", "chat_plan_created")
            )
            raise RuntimeError("force rollback")
    assert submitted == []


async def test_schedule_swallows_exceptions(monkeypatch) -> None:
    """异常隔离：run_in_background 抛异常 → aschedule_ingestion 不上抛 + structlog warning。"""

    def _boom(factory, *, name=None, initiated_by_user_id=None):
        raise RuntimeError("runner down")

    monkeypatch.setattr("knowledge.ingestion.run_in_background", _boom)
    with capture_logs() as cap:
        await aschedule_ingestion(IngestionRequest("coding_plan", "abc", "chat_plan_created"))
    warnings = [e["event"] for e in cap if e.get("log_level") == "warning"]
    assert "knowledge_ingest_schedule_failed" in warnings


# ============================================================================
# Task 1：sources 注册表（get_normalizer 惰性 import）
# ============================================================================


def test_get_normalizer_unknown_kind_raises_keyerror() -> None:
    """未知 source_kind 直接 KeyError（响亮，配置错误不可静默）。"""
    with pytest.raises(KeyError):
        get_normalizer("unknown_kind")


def test_get_normalizer_lazy_imports_registered_module(monkeypatch) -> None:
    """注册表惰性 import：注入 fake 模块（13-03 才落地真实 normalizer）。"""
    fake = types.ModuleType("knowledge.sources.coding_plan")

    async def normalize(request):
        return []

    fake.normalize = normalize  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "knowledge.sources.coding_plan", fake)
    assert get_normalizer("coding_plan") is normalize


# ============================================================================
# Task 2：ingest 委派（normalize → ingest_events）
# ============================================================================


def _inject_fake_normalizer(monkeypatch, events: list[IngestionEvent]) -> None:
    fake = types.ModuleType("knowledge.sources.coding_plan")

    async def normalize(request):
        return events

    fake.normalize = normalize  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "knowledge.sources.coding_plan", fake)


async def test_ingest_empty_events_noop_with_warning(monkeypatch) -> None:
    """normalizer 产出空列表 → no-op + warning（不进 ingest_events）。"""
    _inject_fake_normalizer(monkeypatch, [])
    called = AsyncMock()
    monkeypatch.setattr("knowledge.ingestion.ingest_events", called)
    with capture_logs() as cap:
        await ingest(IngestionRequest("coding_plan", "plan-x", "chat_plan_created"))
    warnings = [e["event"] for e in cap if e.get("log_level") == "warning"]
    assert "knowledge_ingest_no_events" in warnings
    called.assert_not_awaited()


async def test_ingest_delegates_events_to_ingest_events(monkeypatch) -> None:
    """ingest = get_normalizer → normalize → ingest_events（trigger 透传）。"""
    event = make_event()
    _inject_fake_normalizer(monkeypatch, [event])
    called = AsyncMock()
    monkeypatch.setattr("knowledge.ingestion.ingest_events", called)
    await ingest(IngestionRequest("coding_plan", "plan-x", "chat_plan_created"))
    called.assert_awaited_once_with([event], trigger="chat_plan_created")


# ============================================================================
# Task 2 Test 1/2：首摄 + 幂等三连发（INGEST-07）
# ============================================================================


async def test_first_ingest_creates_entity_and_synced_version(
    mock_ensure, mock_embedding, mock_qdrant_client, mock_upsert
) -> None:
    """首摄：单实体（id 经 generate_entity_id）+ v1 latest + vector_synced=True。"""
    await ingest_events([make_event()])

    entity_id = generate_entity_id("tech_plan", "coding_plan", "plan-1")
    entity = await KnowledgeEntity.objects.aget(id=entity_id)
    version = await KnowledgeEntityVersion.objects.aget(entity=entity)
    assert version.version == 1
    assert version.is_latest is True
    assert version.vector_synced is True
    assert version.invalid_at is None
    assert entity.current_version == 1
    # upsert 收到的 point id 与版本行预写的 qdrant_point_ids 一致
    assert len(mock_upsert) == 1
    assert mock_upsert[0] == list(version.qdrant_point_ids)


async def test_upsert_payload_keys_superset_of_schema(
    mock_ensure, mock_embedding, mock_qdrant_client, monkeypatch
) -> None:
    """payload 契约（T-13-02）：upsert 收到的键集合 ⊇ 索引字段 ∪ 必带字段。"""
    from services.qdrant_service import QdrantService

    captured: list[dict] = []

    def _fake(cls, name, pts):
        captured.extend(pts)
        return True

    monkeypatch.setattr(QdrantService, "upsert_vectors_by_name", classmethod(_fake))
    await ingest_events([make_event()])

    required = set(KNOWLEDGE_PAYLOAD_INDEXED_FIELDS) | set(KNOWLEDGE_PAYLOAD_REQUIRED_FIELDS)
    assert captured
    for point in captured:
        assert required <= set(point["payload"].keys())
        assert point["payload"]["is_latest"] is True


async def test_ingest_idempotent_triple_fire(
    mock_ensure, mock_embedding, mock_qdrant_client, mock_upsert
) -> None:
    """幂等三连发：同 event 3 次 → 1 实体 1 版本，Qdrant upsert 仅 1 次。"""
    event = make_event()
    for _ in range(3):
        await ingest_events([event])
    assert await KnowledgeEntity.objects.acount() == 1
    assert await KnowledgeEntityVersion.objects.acount() == 1
    assert len(mock_upsert) == 1


async def test_preshortcircuit_repeated_trigger_zero_embedding_calls(
    mock_ensure, mock_embedding, mock_qdrant_client, mock_upsert
) -> None:
    """预短路（embed 前）：重复触发不白付远程 embedding（零新增调用）。"""
    from services.embedding import EmbeddingService

    event = make_event()
    await ingest_events([event])
    calls_after_first = EmbeddingService.generate_embeddings_batch.call_count
    await ingest_events([event])
    await ingest_events([event])
    assert EmbeddingService.generate_embeddings_batch.call_count == calls_after_first


# ============================================================================
# Task 2 Test 3：版本翻转（INGEST-06）
# ============================================================================


async def test_version_flip_on_content_change(
    mock_ensure, mock_embedding, mock_qdrant_client, monkeypatch
) -> None:
    """content 变更重摄：v2 latest supersedes v1；v1 翻转 + invalid_at；
    向量序为 upsert(新) → tombstone(旧 ids) → delete(旧 ids)。"""
    from services.qdrant_service import QdrantService

    order: list[tuple[str, list[str]]] = []

    def _fake_upsert(cls, name, pts):
        order.append(("upsert", [p["id"] for p in pts]))
        return True

    monkeypatch.setattr(QdrantService, "upsert_vectors_by_name", classmethod(_fake_upsert))
    mock_qdrant_client.set_payload.side_effect = lambda **kw: order.append(
        ("tombstone", list(kw["points"]))
    )
    mock_qdrant_client.delete.side_effect = lambda **kw: order.append(
        ("delete", list(kw["points_selector"].points))
    )

    await ingest_events([make_event(content="v1 内容")])
    v1 = await KnowledgeEntityVersion.objects.aget(version=1)
    old_ids = list(v1.qdrant_point_ids)

    await ingest_events([make_event(content="## v2\n\n全新内容")])

    v1 = await KnowledgeEntityVersion.objects.aget(version=1)
    v2 = await KnowledgeEntityVersion.objects.aget(version=2)
    assert v2.is_latest is True
    assert v2.supersedes_id == v1.id
    assert v2.vector_synced is True
    assert v1.is_latest is False
    assert v1.invalid_at is not None
    entity = await KnowledgeEntity.objects.aget(id=v2.entity_id)
    assert entity.current_version == 2
    # 第二次摄取的调用序（首摄只有一次 upsert，无旧点）
    assert [op for op, _ in order] == ["upsert", "upsert", "tombstone", "delete"]
    assert order[2][1] == old_ids
    assert order[3][1] == old_ids


# ============================================================================
# Task 2 Test 4：chaos 注入（INGEST-06 防线）
# ============================================================================


async def test_chaos_delete_failure_does_not_break_flip(
    mock_ensure, mock_embedding, mock_qdrant_client, mock_upsert
) -> None:
    """物理删点失败：ingest 不崩（vector_ops 内吞），DB 翻转仍生效。"""
    await ingest_events([make_event(content="v1 内容")])
    mock_qdrant_client.delete.side_effect = RuntimeError("qdrant down")
    await ingest_events([make_event(content="v2 内容")])  # 不应 raise
    v1 = await KnowledgeEntityVersion.objects.aget(version=1)
    v2 = await KnowledgeEntityVersion.objects.aget(version=2)
    assert v1.is_latest is False
    assert v2.is_latest is True


async def test_chaos_tombstone_failure_logs_error_flip_holds(
    mock_ensure, mock_embedding, mock_qdrant_client, mock_upsert
) -> None:
    """tombstone 失败：structlog error 响亮但不上抛，DB 翻转仍生效（第一道防线）。"""
    await ingest_events([make_event(content="v1 内容")])
    mock_qdrant_client.set_payload.side_effect = RuntimeError("qdrant down")
    with capture_logs() as cap:
        await ingest_events([make_event(content="v2 内容")])  # 不应 raise
    errors = [e["event"] for e in cap if e.get("log_level") == "error"]
    assert "knowledge_ingest_tombstone_failed" in errors
    v1 = await KnowledgeEntityVersion.objects.aget(version=1)
    v2 = await KnowledgeEntityVersion.objects.aget(version=2)
    assert v1.is_latest is False
    assert v2.is_latest is True


async def test_chaos_upsert_failure_leaves_version_unsynced(
    mock_ensure, mock_embedding, mock_qdrant_client, monkeypatch
) -> None:
    """upsert 失败：raise，但 v2 行已落库 vector_synced=False（重触发可补写）。"""
    from services.qdrant_service import QdrantService

    monkeypatch.setattr(
        QdrantService, "upsert_vectors_by_name", classmethod(lambda cls, n, p: True)
    )
    await ingest_events([make_event(content="v1 内容")])

    monkeypatch.setattr(
        QdrantService, "upsert_vectors_by_name", classmethod(lambda cls, n, p: False)
    )
    with pytest.raises(KnowledgeError):
        await ingest_events([make_event(content="v2 内容")])

    v1 = await KnowledgeEntityVersion.objects.aget(version=1)
    v2 = await KnowledgeEntityVersion.objects.aget(version=2)
    assert v1.is_latest is False  # DB 翻转已生效（第一道防线）
    assert v2.is_latest is True
    assert v2.vector_synced is False


# ============================================================================
# Task 2 Test 5：embedding None abort
# ============================================================================


async def test_embedding_none_aborts_with_zero_writes(
    mock_ensure, mock_qdrant_client, monkeypatch
) -> None:
    """embedding 批量结果含 None：整体 raise，DB / Qdrant 零写入。"""
    from services.embedding import EmbeddingService
    from services.qdrant_service import QdrantService

    monkeypatch.setattr(
        EmbeddingService,
        "generate_embeddings_batch",
        AsyncMock(side_effect=lambda texts, **kw: [None for _ in texts]),
    )
    upserts: list = []
    monkeypatch.setattr(
        QdrantService,
        "upsert_vectors_by_name",
        classmethod(lambda cls, n, p: upserts.append(p) or True),
    )
    with pytest.raises(KnowledgeError):
        await ingest_events([make_event()])
    assert await KnowledgeEntity.objects.acount() == 0
    assert await KnowledgeEntityVersion.objects.acount() == 0
    assert upserts == []
    mock_qdrant_client.set_payload.assert_not_called()
    mock_qdrant_client.delete.assert_not_called()


# ============================================================================
# Task 2 Test 6：边精细置位（exclusive EdgeSpec）
# ============================================================================


async def test_exclusive_edge_reuse_and_repoint(
    mock_ensure, mock_embedding, mock_qdrant_client, mock_upsert, entity_factory
) -> None:
    """目标不变重摄 → 复用既有活跃边；目标变化 → 旧边 invalid_at 置位 + 新边。"""
    target_a, target_b = await sync_to_async(lambda: (entity_factory(), entity_factory()))()

    await ingest_events(
        [make_event(content="v1 内容", edges=(EdgeSpec("HAS_PLAN", target_a.id, exclusive=True),))]
    )
    edge = await KnowledgeEdge.objects.aget()
    assert edge.target_entity_id == target_a.id
    assert edge.invalid_at is None

    # 目标不变（content 变化触发翻转，但边复用：无新边、无置位）
    await ingest_events(
        [make_event(content="v2 内容", edges=(EdgeSpec("HAS_PLAN", target_a.id, exclusive=True),))]
    )
    assert await KnowledgeEdge.objects.acount() == 1
    edge = await KnowledgeEdge.objects.aget()
    assert edge.invalid_at is None

    # 目标变化 → 旧边置位 + 新边建立
    await ingest_events(
        [make_event(content="v3 内容", edges=(EdgeSpec("HAS_PLAN", target_b.id, exclusive=True),))]
    )
    assert await KnowledgeEdge.objects.acount() == 2
    old_edge = await KnowledgeEdge.objects.aget(target_entity_id=target_a.id)
    new_edge = await KnowledgeEdge.objects.aget(target_entity_id=target_b.id)
    assert old_edge.invalid_at is not None
    assert new_edge.invalid_at is None


async def test_skipped_event_still_applies_missing_edges(
    mock_ensure, mock_embedding, mock_qdrant_client, mock_upsert, entity_factory
) -> None:
    """Test 9：预短路 skipped 事件仍走边阶段——活跃边缺失时补建（幂等自愈）。"""
    target = await sync_to_async(entity_factory)()
    await ingest_events([make_event()])  # 首摄（无边）
    assert await KnowledgeEdge.objects.acount() == 0

    # 同 content（hash 相同 + vector_synced=True → skipped）但带 EdgeSpec
    await ingest_events([make_event(edges=(EdgeSpec("REFERENCES", target.id),))])
    assert await KnowledgeEntityVersion.objects.acount() == 1  # 零新版本
    edge = await KnowledgeEdge.objects.aget()
    assert edge.target_entity_id == target.id
    assert len(mock_upsert) == 1  # 向量零重写


# ============================================================================
# Task 2 Test 7：crash 恢复幂等（INGEST-07 铁律）
# ============================================================================


async def test_crash_recovery_same_hash_unsynced_revectorizes(
    mock_ensure, mock_embedding, mock_qdrant_client, mock_upsert, monkeypatch
) -> None:
    """hash 相同 + vector_synced=False 重摄：零新版本、无 invalid_at 置位，
    revectorize 路径被调且 vector_synced 回 True（INGEST-07 blocker 闭环）。"""
    import knowledge.ingestion as ingestion_mod

    await ingest_events([make_event()])
    await KnowledgeEntityVersion.objects.aupdate(vector_synced=False)  # 模拟步 3 后 crash

    real = ingestion_mod.revectorize_version
    revector_calls: list = []

    async def _spy(version):
        revector_calls.append(version.id)
        await real(version)

    monkeypatch.setattr(ingestion_mod, "revectorize_version", _spy)
    await ingest_events([make_event()])  # 同 content 重摄

    assert await KnowledgeEntityVersion.objects.acount() == 1  # hash 相等绝不产生新版本
    version = await KnowledgeEntityVersion.objects.aget()
    assert version.invalid_at is None
    assert version.is_latest is True
    assert version.vector_synced is True
    assert revector_calls == [version.id]
    assert len(mock_upsert) == 2  # 首摄 1 次 + revectorize 补写 1 次


async def test_revectorize_version_backfills_point_ids_and_sync(
    mock_ensure, mock_embedding, mock_qdrant_client, mock_upsert, entity_factory, version_factory
) -> None:
    """revectorize_version 最小单测：空 point ids 时确定性派生回写 + 置 synced。"""

    def _setup():
        entity = entity_factory(title="标题")
        version = version_factory(entity, content="## 段落\n\n正文", vector_synced=False)
        return entity, version

    _entity, version = await sync_to_async(_setup)()
    assert list(version.qdrant_point_ids) == []

    await revectorize_version(version)

    await version.arefresh_from_db()
    assert version.vector_synced is True
    assert version.qdrant_point_ids  # derive 后回写
    assert len(mock_upsert) == 1
    assert mock_upsert[0] == list(version.qdrant_point_ids)


async def test_revectorize_shrink_tombstones_and_deletes_dropped_points(
    mock_ensure, mock_embedding, mock_qdrant_client, mock_upsert, entity_factory, version_factory
) -> None:
    """WR-01 锁定：chunk 数收缩时被丢弃的旧多余点先 tombstone 再物理删除。

    模拟旧版本曾切成 3 块（qdrant_point_ids 预存 3 个 id），当前 content
    只切出 1 块——index ≥ 1 的旧点必须在覆写前下线，否则以 is_latest=True
    残留且 reconcile 六检查项全部检测不到。
    """
    from knowledge.chunking import derive_point_ids

    def _setup():
        entity = entity_factory(title="标题")
        version = version_factory(entity, content="正文很短只有一块", vector_synced=False)
        version.qdrant_point_ids = derive_point_ids(version.id, 3)
        version.save(update_fields=["qdrant_point_ids"])
        return entity, version

    _entity, version = await sync_to_async(_setup)()
    old_ids = [str(pid) for pid in version.qdrant_point_ids]
    assert len(old_ids) == 3

    await revectorize_version(version)

    await version.arefresh_from_db()
    new_ids = list(version.qdrant_point_ids)
    assert new_ids == derive_point_ids(version.id, 1)  # 确定性派生回写
    assert version.vector_synced is True

    dropped = old_ids[1:]  # index 0 复用，index 1/2 被丢弃
    # tombstone：is_latest 翻 False（第一道防线）
    mock_qdrant_client.set_payload.assert_called_once()
    tomb_kw = mock_qdrant_client.set_payload.call_args.kwargs
    assert list(tomb_kw["points"]) == dropped
    assert tomb_kw["payload"] == {"is_latest": False}
    # 物理删点（纯优化层）
    mock_qdrant_client.delete.assert_called_once()
    del_kw = mock_qdrant_client.delete.call_args.kwargs
    assert list(del_kw["points_selector"].points) == dropped
    # 新点照常 upsert
    assert len(mock_upsert) == 1
    assert mock_upsert[0] == new_ids


async def test_revectorize_shrink_tombstone_failure_does_not_raise(
    mock_ensure, mock_embedding, mock_qdrant_client, mock_upsert, entity_factory, version_factory
) -> None:
    """WR-01 失败语义：收缩下线的 tombstone 失败响亮（error 日志）但不上抛。"""
    from knowledge.chunking import derive_point_ids

    def _setup():
        entity = entity_factory(title="标题")
        version = version_factory(entity, content="正文很短只有一块", vector_synced=False)
        version.qdrant_point_ids = derive_point_ids(version.id, 3)
        version.save(update_fields=["qdrant_point_ids"])
        return version

    version = await sync_to_async(_setup)()
    mock_qdrant_client.set_payload.side_effect = RuntimeError("qdrant down")

    with capture_logs() as cap:
        await revectorize_version(version)  # 不应 raise

    errors = [e["event"] for e in cap if e.get("log_level") == "error"]
    assert "knowledge_revectorize_tombstone_failed" in errors
    await version.arefresh_from_db()
    assert version.vector_synced is True  # 补写主流程不受影响
