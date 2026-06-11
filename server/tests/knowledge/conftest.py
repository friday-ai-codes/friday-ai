"""knowledge 测试包共享 fixture（Phase 12 Wave 0 测试基建）。

提供 test_models / test_graph_store / test_collection 共用的：
- ``entity_factory`` / ``version_factory`` / ``edge_factory``：返回闭包的模型工厂
  （仓库惯例：直接 ``objects.create``，参数 kw 可覆盖任意字段）。
- ``mock_qdrant_client``：QdrantService.get_client 的 MagicMock seam
  （test_collection.py 显式使用，非 autouse）。

datetime 一律 ``django.utils.timezone.now()``（aware，P2 时区漂移防线）。
"""

from __future__ import annotations

import hashlib
import uuid
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from knowledge.models import (
    EdgeRelation,
    EntityKind,
    EntityOrigin,
    KnowledgeEdge,
    KnowledgeEntity,
    KnowledgeEntityVersion,
    generate_entity_id,
)


@pytest.fixture
def entity_factory(db):
    """KnowledgeEntity 工厂闭包：``_make(**kw)`` 返回新实体。

    默认 source_id 每次唯一（uuid4 hex），id 经 ``generate_entity_id`` 派生
    （uuid5 唯一入口纪律）；kw 可覆盖任意字段（含 id）。
    """

    def _make(**kw) -> KnowledgeEntity:
        kind = kw.pop("kind", EntityKind.WORK_ITEM)
        source_kind = kw.pop("source_kind", "feishu_work_item")
        source_id = kw.pop("source_id", uuid.uuid4().hex)
        defaults = {
            "id": generate_entity_id(kind, source_kind, source_id),
            "origin": EntityOrigin.FEISHU,
            "title": "测试实体",
            "event_time": timezone.now(),
        }
        defaults.update(kw)
        return KnowledgeEntity.objects.create(
            kind=kind, source_kind=source_kind, source_id=source_id, **defaults
        )

    return _make


@pytest.fixture
def version_factory(db):
    """KnowledgeEntityVersion 工厂闭包：``_make(entity, **kw)`` 返回新版本。"""

    def _make(entity: KnowledgeEntity, **kw) -> KnowledgeEntityVersion:
        content = kw.pop("content", "测试内容")
        now = timezone.now()
        defaults = {
            "version": 1,
            "content_hash": hashlib.sha256(content.encode()).hexdigest(),
            "is_latest": True,
            "event_time": now,
            "valid_at": now,
        }
        defaults.update(kw)
        return KnowledgeEntityVersion.objects.create(entity=entity, content=content, **defaults)

    return _make


@pytest.fixture
def edge_factory(db):
    """KnowledgeEdge 工厂闭包：``_make(source_entity, target_entity=None, **kw)``。

    支持 ``target_chunk_id`` kw（XOR 约束测试用）；默认 relation=RELATES_TO。
    """

    def _make(
        source_entity: KnowledgeEntity,
        target_entity: KnowledgeEntity | None = None,
        **kw,
    ) -> KnowledgeEdge:
        defaults = {
            "relation": EdgeRelation.RELATES_TO,
            "valid_at": timezone.now(),
        }
        defaults.update(kw)
        return KnowledgeEdge.objects.create(
            source_entity=source_entity, target_entity=target_entity, **defaults
        )

    return _make


@pytest.fixture
def mock_qdrant_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """QdrantService.get_client 的 MagicMock seam（test_collection.py 显式使用）。

    mock 的 ``get_collections.return_value`` / ``get_collection.return_value``
    由用例自行配置。非 autouse——只有触碰 Qdrant 的用例才需要它；
    pytest 全局 ``--disable-socket`` 是第二道保险（漏 mock 的真实 HTTP 直接被拦截）。
    """
    client = MagicMock()
    from services.qdrant_service import QdrantService

    monkeypatch.setattr(QdrantService, "get_client", classmethod(lambda cls: client))
    return client
