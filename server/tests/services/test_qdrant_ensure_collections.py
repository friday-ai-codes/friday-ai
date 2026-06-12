"""ensure_repo_summaries_collection / create_collection_by_name 维度自愈测试。

回归保护（历史 bug）：repo_summaries / repo_index_nodes 建集合时写死 1024 维，
而 EMBEDDING_DIMENSION 系统设置实际是 2560 → upsert 全部维度错误被静默吞掉，
collection 永远 0 条 → route_repositories 永远返回空列表。

修复后的契约：
1. ensure_* 缺省维度从 SystemSetting(EMBEDDING_DIMENSION) 解析，与 code_index 同源；
2. create_collection_by_name(recreate_on_mismatch=True) 在维度 / hybrid 模式漂移时
   删除重建（仅限可全量回填的派生 collection）；
3. 默认 recreate_on_mismatch=False 保持旧行为（已存在即返回，不碰数据）。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from services.qdrant_service import QdrantService
from system.models import SettingKeys, SystemSetting


def _mock_client(existing: dict[str, tuple[int, bool]] | None = None) -> MagicMock:
    """构造带既有 collection 的 Qdrant client mock。

    Args:
        existing: {collection_name: (dense_size, hybrid)}。
    """
    existing = existing or {}
    client = MagicMock()
    client.get_collections.return_value = SimpleNamespace(
        collections=[SimpleNamespace(name=name) for name in existing]
    )

    def _get_collection(name: str) -> SimpleNamespace:
        size, hybrid = existing[name]
        vectors = (
            {"dense": SimpleNamespace(size=size)}
            if hybrid
            else SimpleNamespace(size=size)
        )
        return SimpleNamespace(
            config=SimpleNamespace(params=SimpleNamespace(vectors=vectors))
        )

    client.get_collection.side_effect = _get_collection
    return client


@pytest.mark.django_db
class TestGetConfiguredEmbeddingDimension:
    def test_reads_system_setting(self):
        SystemSetting.objects.update_or_create(
            key=SettingKeys.EMBEDDING_DIMENSION, defaults={"value": "2560"}
        )
        assert QdrantService.get_configured_embedding_dimension() == 2560

    def test_falls_back_to_1024_when_missing(self):
        SystemSetting.objects.filter(key=SettingKeys.EMBEDDING_DIMENSION).delete()
        assert QdrantService.get_configured_embedding_dimension() == 1024

    def test_falls_back_to_1024_when_empty(self):
        SystemSetting.objects.update_or_create(
            key=SettingKeys.EMBEDDING_DIMENSION, defaults={"value": ""}
        )
        assert QdrantService.get_configured_embedding_dimension() == 1024


class TestCreateCollectionByNameRecreate:
    def test_default_keeps_existing_even_on_mismatch(self):
        """默认行为不变：已存在即返回 True，绝不删除（overlay 等调用方兼容）。"""
        client = _mock_client({"repo_summaries": (1024, True)})
        with patch.object(QdrantService, "get_client", return_value=client):
            ok = QdrantService.create_collection_by_name(
                "repo_summaries", vector_size=2560, hybrid=True
            )
        assert ok is True
        client.delete_collection.assert_not_called()
        client.create_collection.assert_not_called()

    def test_recreates_on_dimension_mismatch(self):
        client = _mock_client({"repo_summaries": (1024, True)})
        with patch.object(QdrantService, "get_client", return_value=client):
            ok = QdrantService.create_collection_by_name(
                "repo_summaries",
                vector_size=2560,
                hybrid=True,
                recreate_on_mismatch=True,
            )
        assert ok is True
        client.delete_collection.assert_called_once_with(collection_name="repo_summaries")
        client.create_collection.assert_called_once()
        # 重建后必须是新维度
        kwargs = client.create_collection.call_args.kwargs
        assert kwargs["vectors_config"]["dense"].size == 2560

    def test_recreates_on_hybrid_mode_mismatch(self):
        client = _mock_client({"repo_summaries": (2560, False)})
        with patch.object(QdrantService, "get_client", return_value=client):
            ok = QdrantService.create_collection_by_name(
                "repo_summaries",
                vector_size=2560,
                hybrid=True,
                recreate_on_mismatch=True,
            )
        assert ok is True
        client.delete_collection.assert_called_once()

    def test_no_recreate_when_config_matches(self):
        client = _mock_client({"repo_summaries": (2560, True)})
        with patch.object(QdrantService, "get_client", return_value=client):
            ok = QdrantService.create_collection_by_name(
                "repo_summaries",
                vector_size=2560,
                hybrid=True,
                recreate_on_mismatch=True,
            )
        assert ok is True
        client.delete_collection.assert_not_called()
        client.create_collection.assert_not_called()


@pytest.mark.django_db
class TestEnsureCollectionsUseConfiguredDimension:
    def test_repo_summaries_uses_setting_dimension(self):
        SystemSetting.objects.update_or_create(
            key=SettingKeys.EMBEDDING_DIMENSION, defaults={"value": "2560"}
        )
        with patch.object(
            QdrantService, "create_collection_by_name", return_value=True
        ) as mock_create:
            assert QdrantService.ensure_repo_summaries_collection() is True
        mock_create.assert_called_once_with(
            "repo_summaries", vector_size=2560, hybrid=True, recreate_on_mismatch=True
        )

    def test_repo_index_nodes_uses_setting_dimension(self):
        SystemSetting.objects.update_or_create(
            key=SettingKeys.EMBEDDING_DIMENSION, defaults={"value": "2560"}
        )
        with (
            patch.object(
                QdrantService, "create_collection_by_name", return_value=True
            ) as mock_create,
            patch.object(QdrantService, "get_client", return_value=MagicMock()),
        ):
            assert QdrantService.ensure_repo_index_nodes_collection() is True
        mock_create.assert_called_once_with(
            "repo_index_nodes", vector_size=2560, hybrid=True, recreate_on_mismatch=True
        )

    def test_explicit_vector_size_still_wins(self):
        with patch.object(
            QdrantService, "create_collection_by_name", return_value=True
        ) as mock_create:
            QdrantService.ensure_repo_summaries_collection(vector_size=768)
        mock_create.assert_called_once_with(
            "repo_summaries", vector_size=768, hybrid=True, recreate_on_mismatch=True
        )
