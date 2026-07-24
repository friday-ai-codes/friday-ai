"""评论事件→work_item 重投影触发 + 检索召回端到端守护（Plan 34-02 Task 2 / RREF-02）。

覆盖：

- ① 落库 WorkItem + 追加评论事件 → append_events best-effort 触发 aschedule_ingestion
  （断言被调用且 request.source_kind/source_id 正确）。
- ② 走 ingest 流程后 work_item KnowledgeEntityVersion.content 含评论文本（关联到该
  work_item 实体，验证 RREF-02 召回面：评论文本进入 work_item 实体投影，可被既有
  DeliveryKnowledgeSearchService 召回——以 content 含评论子串 + 实体 source_id==triple
  作召回关联断言）。
- ③ created_count==0（幂等重复摄取）→ 不触发重投影（幂等不打扰）。

best-effort：触发不阻塞评论落库。无真实网络/Qdrant：feishu client / embedding /
qdrant 全 monkeypatch，pytest-socket 第二保险。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import knowledge.ingestion as ingestion_module
from delivery.models import WorkItem, WorkItemOrigin
from delivery.services import CommentEventService
from knowledge.ingestion import IngestionRequest, ingest_events
from knowledge.models import KnowledgeEntity, KnowledgeEntityVersion, generate_entity_id
from knowledge.sources import feishu_work_item
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

PROJECT_KEY = "000000000000000000000001"
STORY_ID = 1000000002
SOURCE_ID = f"{PROJECT_KEY}:story:{STORY_ID}"


async def _make_project() -> Space:
    return await Space.objects.acreate(name="测试项目", feishu_project_key=PROJECT_KEY)


async def _make_work_item() -> WorkItem:
    return await WorkItem.objects.acreate(
        feishu_project_key=PROJECT_KEY,
        work_item_type="story",
        work_item_id=STORY_ID,
        origin=WorkItemOrigin.MANUAL,
        title="评论宿主工作项",
    )


def _comment(cid: str, content: str, *, parent: str = "", ms: int = 1700000000000) -> dict:
    return {
        "id": cid,
        "content": content,
        "created_at": ms,
        "author": "u1",
        "thread_parent_id": parent,
    }


# ============================================================================
# ① 评论新增触发 aschedule_ingestion（source_kind / source_id 正确）
# ============================================================================


async def test_append_events_triggers_reprojection(monkeypatch) -> None:
    """追加评论事件 → append_events 触发 aschedule_ingestion，request 形状正确。"""
    captured: list[IngestionRequest] = []

    async def _fake_schedule(request: IngestionRequest) -> None:
        captured.append(request)

    monkeypatch.setattr(ingestion_module, "aschedule_ingestion", _fake_schedule)

    work_item = await _make_work_item()
    created = await CommentEventService().append_events(work_item, [_comment("c1", "需要澄清")], "manual")

    assert created == 1
    assert len(captured) == 1
    req = captured[0]
    assert req.source_kind == "feishu_work_item"
    assert req.source_id == SOURCE_ID
    assert req.trigger == "comment_event_appended"


# ============================================================================
# ③ created_count==0（幂等重复摄取）→ 不触发重投影
# ============================================================================


async def test_idempotent_append_no_retrigger(monkeypatch) -> None:
    """同批评论二次 append（created_count==0）→ 不再触发 aschedule_ingestion。"""
    calls: list[IngestionRequest] = []

    async def _fake_schedule(request: IngestionRequest) -> None:
        calls.append(request)

    monkeypatch.setattr(ingestion_module, "aschedule_ingestion", _fake_schedule)

    work_item = await _make_work_item()
    service = CommentEventService()
    comments = [_comment("c1", "首次评论")]

    first = await service.append_events(work_item, comments, "manual")
    second = await service.append_events(work_item, comments, "manual")

    assert first == 1
    assert second == 0
    # 仅首次（有新增）触发，幂等重摄不打扰
    assert len(calls) == 1


# ============================================================================
# ② 端到端：重投影后 work_item 快照 content 含评论文本且关联 work_item 实体
# ============================================================================


@pytest.fixture
def mock_ensure(monkeypatch) -> AsyncMock:
    ensure = AsyncMock()
    monkeypatch.setattr("knowledge.ingestion.ensure_delivery_knowledge_collection", ensure)
    return ensure


@pytest.fixture
def mock_upsert(monkeypatch) -> list[list[str]]:
    from services.qdrant_service import QdrantService

    calls: list[list[str]] = []

    def _fake(cls, name, pts):
        calls.append([p["id"] for p in pts])
        return True

    monkeypatch.setattr(QdrantService, "upsert_vectors_by_name", classmethod(_fake))
    return calls


@pytest.fixture
def mock_feishu_client(monkeypatch):
    class _FakeFeishuClient:
        async def get_work_item(self, *, project_key, work_item_id, work_item_type):
            return SimpleNamespace(
                name="评论宿主工作项",
                description="需求描述",
                status="developing",
                fields={},
            )

        async def get_work_item_relations(self, *, project_key, work_item_id, work_item_type):
            return []

    monkeypatch.setattr(
        feishu_work_item, "create_feishu_client_for_project", lambda project: _FakeFeishuClient()
    )


async def test_end_to_end_comment_text_in_work_item_snapshot(
    mock_feishu_client, mock_ensure, mock_embedding, mock_qdrant_client, mock_upsert
) -> None:
    """落 WorkItem + 评论事件 → 重投影后 work_item KnowledgeEntityVersion.content 含评论文本。"""
    await _make_project()
    work_item = await _make_work_item()
    # 评论经唯一写入入口落库（不旁路写事件表）
    await CommentEventService().append_events(
        work_item,
        [_comment("c1", "评论召回测试文本ABC")],
        "manual",
    )

    # 走 ingest 流程（重投影体）：normalize → ingest_events
    request = IngestionRequest(
        source_kind="feishu_work_item",
        source_id=SOURCE_ID,
        trigger="comment_event_appended",
    )
    events = await feishu_work_item.normalize(request)
    await ingest_events(events)

    entity_id = generate_entity_id("work_item", "feishu_work_item", SOURCE_ID)
    entity = await KnowledgeEntity.objects.aget(id=entity_id)
    # 关联到该 work_item 实体（source_id==triple，召回天然挂在 work_item 上）
    assert entity.source_id == SOURCE_ID
    assert entity.kind == "work_item"

    latest = await KnowledgeEntityVersion.objects.filter(
        entity_id=entity_id, is_latest=True
    ).aget()
    assert "## 评论" in latest.content
    assert "评论召回测试文本ABC" in latest.content
