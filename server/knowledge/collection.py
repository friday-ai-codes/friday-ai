"""delivery_knowledge Qdrant collection 显式生命周期管理（Phase 12 / ROADMAP SC#5）。

本模块是知识库 payload schema 的**单一事实源**：Phase 13 摄取与 Phase 15 检索
必须 import 本模块的 ``KNOWLEDGE_PAYLOAD_INDEXED_FIELDS`` / ``KNOWLEDGE_PAYLOAD_REQUIRED_FIELDS``
常量，禁止散落复刻字段名。

实现契约（与既有 indexer 语义**刻意相反**，P8 灾难防线）：
- collection 缺失 → 创建（hybrid dense+sparse + 全部 payload index），元信息写入
  SystemSetting ``knowledge_collection_meta``；
- collection 存在且维度/hybrid 结构匹配 → 通过（元信息缺失则补写）；
- 维度/结构不匹配 → raise :class:`KnowledgeCollectionMismatchError` 响亮拒绝，
  collection 原样保留——切换 embedding 模型不得静默清空知识库；重建唯一入口为
  ``manage.py rebuild_delivery_knowledge --yes``；
- 任何 Qdrant 异常一律重抛，禁止静默吞掉（写入错库比报错更危险）。

schema 边界（P6 / P10）：
- ``project_id`` / ``repository_id`` 为权限维度字段，第一天定型不许事后回填
  （Phase 15 RETR-07 强制 service 层过滤的前提，回填成本 HIGH）；
- ``is_latest`` 只服务召回面（默认检索过滤 latest）；版本链回溯等轨迹面查询
  一律走 PG ``KnowledgeEntityVersion`` 表，不依赖 Qdrant payload。
"""

from __future__ import annotations

import json

import structlog
from asgiref.sync import sync_to_async
from qdrant_client import models

from knowledge.exceptions import KnowledgeCollectionMismatchError
from services.qdrant_service import QdrantService
from system.models import SettingKeys, SystemSetting

logger = structlog.get_logger(__name__)

__all__ = [
    "DELIVERY_KNOWLEDGE_COLLECTION",
    "KNOWLEDGE_PAYLOAD_INDEXED_FIELDS",
    "KNOWLEDGE_PAYLOAD_REQUIRED_FIELDS",
    "KNOWLEDGE_SCHEMA_VERSION",
    "ensure_delivery_knowledge_collection",
    "get_embedding_model_name",
    "get_expected_dimension",
]

DELIVERY_KNOWLEDGE_COLLECTION = "delivery_knowledge"

# payload schema 版本号：任何索引字段增删/语义变更必须递增并显式过审（回归测试锁定）。
KNOWLEDGE_SCHEMA_VERSION = 1

# 建 payload index 的字段（字段名 → Qdrant 索引类型）。
# 8 字段第一天定型：entity_kind/entity_id（实体定位）、version/is_latest（召回面）、
# project_id/repository_id（权限维度，P6）、source_kind（来源过滤）、event_time（时间衰减输入）。
KNOWLEDGE_PAYLOAD_INDEXED_FIELDS: dict[str, models.PayloadSchemaType] = {
    "entity_kind": models.PayloadSchemaType.KEYWORD,
    "entity_id": models.PayloadSchemaType.KEYWORD,
    "version": models.PayloadSchemaType.INTEGER,
    "is_latest": models.PayloadSchemaType.BOOL,
    "project_id": models.PayloadSchemaType.KEYWORD,
    "repository_id": models.PayloadSchemaType.KEYWORD,
    "source_kind": models.PayloadSchemaType.KEYWORD,
    "event_time": models.PayloadSchemaType.DATETIME,
}

# 非索引但每个 point payload 必带的字段（Phase 13 摄取写入契约）：
# source_id（业务对象稳定 ID）、chunk_kind（切块类型）、file_path（来源路径，可空串）、
# text（切块原文）、embedding_model（向量来源模型）、version_id（KnowledgeEntityVersion PK）。
KNOWLEDGE_PAYLOAD_REQUIRED_FIELDS: tuple[str, ...] = (
    "source_id",
    "chunk_kind",
    "file_path",
    "text",
    "embedding_model",
    "version_id",
)


DEFAULT_EMBEDDING_DIMENSION = 1024


async def get_expected_dimension() -> int:
    """读取期望 embedding 维度（SystemSetting，indexer 同款 default 1024）。

    公开 API（rebuild 命令等跨模块调用方复用，IN-03）。

    边界值防线：``SystemSetting.value`` 可为 None/空串/非数字（TextField,
    blank=True, null=True）——本函数在启动路径上，绝不允许 ``int()`` 直接崩溃。
    空值视为未配置走默认；非法值回退默认并 structlog warning（响亮可观测）。
    """
    dimension_setting = await SystemSetting.objects.filter(
        key=SettingKeys.EMBEDDING_DIMENSION
    ).afirst()
    raw = dimension_setting.value if dimension_setting else None
    if raw is None or not str(raw).strip():
        return DEFAULT_EMBEDDING_DIMENSION
    try:
        return int(str(raw).strip())
    except ValueError:
        logger.warning(
            "knowledge_embedding_dimension_invalid",
            value=raw,
            fallback=DEFAULT_EMBEDDING_DIMENSION,
        )
        return DEFAULT_EMBEDDING_DIMENSION


async def get_embedding_model_name() -> str:
    """读取当前 embedding 模型名（可为空串）。

    公开 API：Phase 13 摄取写入 payload ``embedding_model`` 字段时复用，
    避免跨模块 import 私有函数。
    """
    model_setting = await SystemSetting.objects.filter(key=SettingKeys.EMBEDDING_MODEL).afirst()
    return model_setting.value if model_setting and model_setting.value else ""


async def _write_collection_meta(dimension: int) -> None:
    """将 collection 元信息（模型名 + 维度 + schema 版本）写入 SystemSetting。"""
    meta = {
        "model": await get_embedding_model_name(),
        "dimension": dimension,
        "schema_version": KNOWLEDGE_SCHEMA_VERSION,
    }
    await SystemSetting.objects.aupdate_or_create(
        key=SettingKeys.KNOWLEDGE_COLLECTION_META,
        defaults={
            "value": json.dumps(meta, ensure_ascii=False),
            "description": "delivery_knowledge collection 元信息（knowledge.collection 维护）",
        },
    )


async def ensure_delivery_knowledge_collection() -> None:
    """确保 delivery_knowledge collection 存在且配置匹配；不匹配则响亮拒绝。

    语义（与 ``QdrantService.create_collection`` 的自动重建**刻意相反**）：
    - 缺失 → 创建 hybrid（dense+sparse）+ 全部 payload index + 元信息落库；
    - 存在且匹配 → 通过（SystemSetting 元信息缺失则补写）；
    - 存在但维度/结构不匹配 → raise :class:`KnowledgeCollectionMismatchError`，
      collection 原样保留，重建只能经 ``manage.py rebuild_delivery_knowledge --yes``；
    - Qdrant 异常一律向上冒泡，不做任何静默降级。
    """
    expected_dimension = await get_expected_dimension()
    client = QdrantService.get_client()

    collections = await sync_to_async(client.get_collections)()
    existing_names = [c.name for c in collections.collections]

    if DELIVERY_KNOWLEDGE_COLLECTION not in existing_names:
        await sync_to_async(client.create_collection)(
            collection_name=DELIVERY_KNOWLEDGE_COLLECTION,
            vectors_config={
                "dense": models.VectorParams(
                    size=expected_dimension,
                    distance=models.Distance.COSINE,
                ),
            },
            sparse_vectors_config={
                "sparse": models.SparseVectorParams(),
            },
        )
        for field_name, field_schema in KNOWLEDGE_PAYLOAD_INDEXED_FIELDS.items():
            await sync_to_async(client.create_payload_index)(
                collection_name=DELIVERY_KNOWLEDGE_COLLECTION,
                field_name=field_name,
                field_schema=field_schema,
            )
        await _write_collection_meta(expected_dimension)
        logger.info(
            "knowledge_collection_created",
            collection=DELIVERY_KNOWLEDGE_COLLECTION,
            dimension=expected_dimension,
            indexed_fields=len(KNOWLEDGE_PAYLOAD_INDEXED_FIELDS),
        )
        return

    # collection 已存在 → 严格比对配置（绝不自动重建）
    collection_info = await sync_to_async(client.get_collection)(DELIVERY_KNOWLEDGE_COLLECTION)
    vectors_config = collection_info.config.params.vectors

    if not isinstance(vectors_config, dict):
        # 单向量模式 ⇒ 非 hybrid 结构，与期望（named dense+sparse）不符
        existing_size = getattr(vectors_config, "size", None)
        logger.error(
            "knowledge_collection_config_mismatch",
            collection=DELIVERY_KNOWLEDGE_COLLECTION,
            existing_size=existing_size,
            expected_size=expected_dimension,
            existing_hybrid=False,
        )
        raise KnowledgeCollectionMismatchError(
            f"delivery_knowledge collection 结构不匹配：现有为单向量（非 hybrid）模式"
            f"（现有 {existing_size} 维 / 期望 hybrid dense {expected_dimension} 维）。"
            "请确认 embedding 配置，或运行 `manage.py rebuild_delivery_knowledge --yes` 显式重建。",
            details={
                "existing_size": existing_size,
                "expected_size": expected_dimension,
                "existing_hybrid": False,
            },
        )

    dense_params = vectors_config.get(
        "dense", models.VectorParams(size=0, distance=models.Distance.COSINE)
    )
    existing_size = dense_params.size
    if existing_size != expected_dimension:
        logger.error(
            "knowledge_collection_config_mismatch",
            collection=DELIVERY_KNOWLEDGE_COLLECTION,
            existing_size=existing_size,
            expected_size=expected_dimension,
            existing_hybrid=True,
        )
        raise KnowledgeCollectionMismatchError(
            f"delivery_knowledge collection 维度不匹配（现有 {existing_size} 维 / "
            f"期望 {expected_dimension} 维）。"
            "请确认 embedding 配置，或运行 `manage.py rebuild_delivery_knowledge --yes` 显式重建。",
            details={
                "existing_size": existing_size,
                "expected_size": expected_dimension,
                "existing_hybrid": True,
            },
        )

    # hybrid 结构校验下半场：dense 维度匹配还不够，sparse named vector 必须存在——
    # 残缺 collection（只有 named dense）若静默通过，Phase 13 写 sparse 向量时才在
    # 摄取路径上失败（写入错库比报错更危险，P8 同源防线）。
    sparse_config = getattr(collection_info.config.params, "sparse_vectors", None)
    if not sparse_config or "sparse" not in sparse_config:
        logger.error(
            "knowledge_collection_config_mismatch",
            collection=DELIVERY_KNOWLEDGE_COLLECTION,
            existing_size=existing_size,
            expected_size=expected_dimension,
            existing_sparse=False,
        )
        raise KnowledgeCollectionMismatchError(
            "delivery_knowledge collection 缺少 sparse named vector（非完整 hybrid 结构）。"
            "请确认 collection 来源，或运行 `manage.py rebuild_delivery_knowledge --yes` 显式重建。",
            details={
                "existing_size": existing_size,
                "expected_size": expected_dimension,
                "existing_sparse": False,
            },
        )

    # 匹配通过 → 元信息缺失则补写（升级路径：collection 先于元信息存在）
    meta_setting = await SystemSetting.objects.filter(
        key=SettingKeys.KNOWLEDGE_COLLECTION_META
    ).afirst()
    if meta_setting is None or not meta_setting.value:
        await _write_collection_meta(expected_dimension)
    logger.debug(
        "knowledge_collection_verified",
        collection=DELIVERY_KNOWLEDGE_COLLECTION,
        dimension=expected_dimension,
    )
