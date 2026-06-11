"""delivery_knowledge collection 生命周期测试（Phase 12 Plan 03，Qdrant 全 mock）。

用例清单：
- ensure：collection 缺失 → 创建 hybrid + 8 个 payload index + SystemSetting 元信息落库
- ensure：collection 存在且维度/hybrid 匹配 → 不创建、不 raise、正常返回
- ensure：维度不匹配（768 vs 1024）→ raise KnowledgeCollectionMismatchError，
  绝不调用 delete_collection（P8 核心断言），message 含 768/1024/--yes 指引
- ensure：非 hybrid 结构（vectors_config 非 dict）→ 同样 raise 且不删库
- ensure：Qdrant UnexpectedResponse → 异常向上冒泡（不被吞为 False/None）
- ensure：EMBEDDING_DIMENSION SystemSetting=768 时按设置值创建（size=768）
- rebuild 命令：无 --yes → 仅打印 WARNING 横幅，零 Qdrant 副作用
- rebuild 命令：带 --yes → delete_collection_by_name 一次 + ensure 创建路径执行
- schema 常量回归：KNOWLEDGE_PAYLOAD_INDEXED_FIELDS 键集合恰为 8 字段（Phase 13/15 契约锁）

Qdrant 经 conftest ``mock_qdrant_client`` seam 全程 mock；pytest 全局
``--disable-socket`` 是第二道保险（漏 mock 的真实 HTTP 直接被拦截）。
"""

from __future__ import annotations

import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.core.management import call_command
from qdrant_client import models
from qdrant_client.http.exceptions import UnexpectedResponse

from knowledge.collection import (
    DELIVERY_KNOWLEDGE_COLLECTION,
    KNOWLEDGE_PAYLOAD_INDEXED_FIELDS,
    ensure_delivery_knowledge_collection,
)
from knowledge.exceptions import KnowledgeCollectionMismatchError
from system.models import SettingKeys, SystemSetting

# SQLite 内存数据库 + async（sync_to_async 跨线程）需要 transaction=True
pytestmark = pytest.mark.django_db(transaction=True)


def _collections_response(*names: str) -> SimpleNamespace:
    """构造 get_collections 假返回（MagicMock 的 name kwarg 有特殊语义，用 SimpleNamespace）。"""
    return SimpleNamespace(collections=[SimpleNamespace(name=n) for n in names])


_VALID_SPARSE = {"sparse": models.SparseVectorParams()}


def _collection_info(vectors, sparse_vectors=_VALID_SPARSE) -> SimpleNamespace:
    """构造 get_collection 假返回：info.config.params.vectors / .sparse_vectors。

    sparse_vectors 默认完整 hybrid 配置；传 None/空 dict 模拟残缺 collection。
    """
    return SimpleNamespace(
        config=SimpleNamespace(
            params=SimpleNamespace(vectors=vectors, sparse_vectors=sparse_vectors)
        )
    )


def _hybrid_vectors(size: int) -> dict[str, models.VectorParams]:
    return {"dense": models.VectorParams(size=size, distance=models.Distance.COSINE)}


# ---------------------------------------------------------------------------
# ensure_delivery_knowledge_collection
# ---------------------------------------------------------------------------


async def test_ensure_creates_collection_when_missing(mock_qdrant_client: MagicMock) -> None:
    """collection 缺失 → 创建 hybrid + 8 个 payload index + 元信息落库（含 dimension）。"""
    mock_qdrant_client.get_collections.return_value = _collections_response()

    await ensure_delivery_knowledge_collection()

    mock_qdrant_client.create_collection.assert_called_once()
    create_kwargs = mock_qdrant_client.create_collection.call_args.kwargs
    assert create_kwargs["collection_name"] == DELIVERY_KNOWLEDGE_COLLECTION
    assert create_kwargs["vectors_config"]["dense"].size == 1024
    assert "sparse" in create_kwargs["sparse_vectors_config"]

    assert mock_qdrant_client.create_payload_index.call_count == len(
        KNOWLEDGE_PAYLOAD_INDEXED_FIELDS
    )
    assert mock_qdrant_client.create_payload_index.call_count == 8
    indexed_fields = {
        call.kwargs["field_name"] for call in mock_qdrant_client.create_payload_index.call_args_list
    }
    assert indexed_fields == set(KNOWLEDGE_PAYLOAD_INDEXED_FIELDS)

    meta_setting = await SystemSetting.objects.aget(key=SettingKeys.KNOWLEDGE_COLLECTION_META)
    meta = json.loads(meta_setting.value)
    assert meta["dimension"] == 1024
    assert meta["schema_version"] == 1


async def test_ensure_passes_when_config_matches(mock_qdrant_client: MagicMock) -> None:
    """collection 存在且维度/hybrid 匹配 → 不创建、不 raise、正常返回。"""
    mock_qdrant_client.get_collections.return_value = _collections_response(
        DELIVERY_KNOWLEDGE_COLLECTION
    )
    mock_qdrant_client.get_collection.return_value = _collection_info(_hybrid_vectors(1024))

    await ensure_delivery_knowledge_collection()

    mock_qdrant_client.create_collection.assert_not_called()
    mock_qdrant_client.delete_collection.assert_not_called()


async def test_ensure_raises_on_dimension_mismatch_and_never_deletes(
    mock_qdrant_client: MagicMock,
) -> None:
    """维度不匹配（768 vs 1024）→ raise 且绝不删库（P8 核心断言），message 含可操作指引。"""
    mock_qdrant_client.get_collections.return_value = _collections_response(
        DELIVERY_KNOWLEDGE_COLLECTION
    )
    mock_qdrant_client.get_collection.return_value = _collection_info(_hybrid_vectors(768))

    with pytest.raises(KnowledgeCollectionMismatchError) as exc_info:
        await ensure_delivery_knowledge_collection()

    mock_qdrant_client.delete_collection.assert_not_called()
    mock_qdrant_client.create_collection.assert_not_called()
    message = str(exc_info.value)
    assert "768" in message
    assert "1024" in message
    assert "rebuild_delivery_knowledge --yes" in message


async def test_ensure_raises_on_non_hybrid_structure_and_never_deletes(
    mock_qdrant_client: MagicMock,
) -> None:
    """非 hybrid 结构（vectors_config 非 dict）→ 同样 raise 且不删库。"""
    mock_qdrant_client.get_collections.return_value = _collections_response(
        DELIVERY_KNOWLEDGE_COLLECTION
    )
    mock_qdrant_client.get_collection.return_value = _collection_info(
        models.VectorParams(size=1024, distance=models.Distance.COSINE)
    )

    with pytest.raises(KnowledgeCollectionMismatchError) as exc_info:
        await ensure_delivery_knowledge_collection()

    mock_qdrant_client.delete_collection.assert_not_called()
    assert "rebuild_delivery_knowledge --yes" in str(exc_info.value)


async def test_ensure_raises_when_sparse_vector_missing(
    mock_qdrant_client: MagicMock,
) -> None:
    """dense 维度匹配但缺 sparse named vector（残缺 hybrid）→ raise 且不删库（WR-02）。"""
    mock_qdrant_client.get_collections.return_value = _collections_response(
        DELIVERY_KNOWLEDGE_COLLECTION
    )
    mock_qdrant_client.get_collection.return_value = _collection_info(
        _hybrid_vectors(1024), sparse_vectors=None
    )

    with pytest.raises(KnowledgeCollectionMismatchError) as exc_info:
        await ensure_delivery_knowledge_collection()

    mock_qdrant_client.delete_collection.assert_not_called()
    mock_qdrant_client.create_collection.assert_not_called()
    message = str(exc_info.value)
    assert "sparse" in message
    assert "rebuild_delivery_knowledge --yes" in message


async def test_ensure_raises_when_sparse_dict_lacks_sparse_key(
    mock_qdrant_client: MagicMock,
) -> None:
    """sparse_vectors 存在但无 "sparse" 命名向量 → 同样 raise 且不删库（WR-02）。"""
    mock_qdrant_client.get_collections.return_value = _collections_response(
        DELIVERY_KNOWLEDGE_COLLECTION
    )
    mock_qdrant_client.get_collection.return_value = _collection_info(
        _hybrid_vectors(1024), sparse_vectors={"other": models.SparseVectorParams()}
    )

    with pytest.raises(KnowledgeCollectionMismatchError):
        await ensure_delivery_knowledge_collection()

    mock_qdrant_client.delete_collection.assert_not_called()


async def test_ensure_propagates_qdrant_errors(mock_qdrant_client: MagicMock) -> None:
    """Qdrant client 抛 UnexpectedResponse → 异常向上冒泡，不被吞为 False/None。"""
    mock_qdrant_client.get_collections.side_effect = UnexpectedResponse(
        status_code=500, reason_phrase="Internal Server Error", content=b"", headers=None
    )

    with pytest.raises(UnexpectedResponse):
        await ensure_delivery_knowledge_collection()


async def test_ensure_respects_embedding_dimension_setting(
    mock_qdrant_client: MagicMock,
) -> None:
    """EMBEDDING_DIMENSION SystemSetting 存在（768）时按设置值创建。"""
    await SystemSetting.objects.acreate(key=SettingKeys.EMBEDDING_DIMENSION, value="768")
    mock_qdrant_client.get_collections.return_value = _collections_response()

    await ensure_delivery_knowledge_collection()

    create_kwargs = mock_qdrant_client.create_collection.call_args.kwargs
    assert create_kwargs["vectors_config"]["dense"].size == 768
    meta_setting = await SystemSetting.objects.aget(key=SettingKeys.KNOWLEDGE_COLLECTION_META)
    assert json.loads(meta_setting.value)["dimension"] == 768


@pytest.mark.parametrize("raw_value", [None, "", "   "], ids=["none", "empty", "blank"])
async def test_ensure_falls_back_when_dimension_setting_empty(
    mock_qdrant_client: MagicMock, raw_value: str | None
) -> None:
    """EMBEDDING_DIMENSION setting 存在但 value 为 None/空串/空白 → 不崩溃，回退默认 1024。"""
    await SystemSetting.objects.acreate(key=SettingKeys.EMBEDDING_DIMENSION, value=raw_value)
    mock_qdrant_client.get_collections.return_value = _collections_response()

    await ensure_delivery_knowledge_collection()

    create_kwargs = mock_qdrant_client.create_collection.call_args.kwargs
    assert create_kwargs["vectors_config"]["dense"].size == 1024


async def test_ensure_falls_back_when_dimension_setting_invalid(
    mock_qdrant_client: MagicMock,
) -> None:
    """EMBEDDING_DIMENSION value 非数字（"abc"）→ 不崩溃，回退默认 1024（启动路径防线）。"""
    await SystemSetting.objects.acreate(key=SettingKeys.EMBEDDING_DIMENSION, value="abc")
    mock_qdrant_client.get_collections.return_value = _collections_response()

    await ensure_delivery_knowledge_collection()

    create_kwargs = mock_qdrant_client.create_collection.call_args.kwargs
    assert create_kwargs["vectors_config"]["dense"].size == 1024


# ---------------------------------------------------------------------------
# rebuild_delivery_knowledge 命令
# ---------------------------------------------------------------------------


def test_rebuild_command_without_yes_is_noop(
    mock_qdrant_client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """无 --yes → 仅打印 WARNING 横幅说明将发生什么，零 Qdrant 副作用。"""
    from services.qdrant_service import QdrantService

    delete_by_name = MagicMock(return_value=True)
    monkeypatch.setattr(QdrantService, "delete_collection_by_name", delete_by_name)

    out = io.StringIO()
    call_command("rebuild_delivery_knowledge", stdout=out)

    output = out.getvalue()
    assert "危险操作" in output
    assert "--yes" in output
    delete_by_name.assert_not_called()
    mock_qdrant_client.create_collection.assert_not_called()
    mock_qdrant_client.delete_collection.assert_not_called()


def test_rebuild_command_with_yes_deletes_then_recreates(
    mock_qdrant_client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """带 --yes → delete_collection_by_name 一次，随后 ensure 创建路径执行。"""
    from services.qdrant_service import QdrantService

    delete_by_name = MagicMock(return_value=True)
    monkeypatch.setattr(QdrantService, "delete_collection_by_name", delete_by_name)
    mock_qdrant_client.get_collections.return_value = _collections_response()

    out = io.StringIO()
    call_command("rebuild_delivery_knowledge", "--yes", stdout=out)

    delete_by_name.assert_called_once_with(DELIVERY_KNOWLEDGE_COLLECTION)
    mock_qdrant_client.create_collection.assert_called_once()
    assert "已重建" in out.getvalue()


# ---------------------------------------------------------------------------
# schema 常量回归（Phase 13/15 契约锁）
# ---------------------------------------------------------------------------


def test_payload_schema_fields_locked() -> None:
    """KNOWLEDGE_PAYLOAD_INDEXED_FIELDS 键集合恰为 8 字段——任何增删必须显式过审。"""
    assert set(KNOWLEDGE_PAYLOAD_INDEXED_FIELDS) == {
        "entity_kind",
        "entity_id",
        "version",
        "is_latest",
        "project_id",
        "repository_id",
        "source_kind",
        "event_time",
    }
