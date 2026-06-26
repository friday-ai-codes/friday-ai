"""统一知识摄取核心（Phase 13 / INGEST-06、INGEST-07、INGEST-08）。

触发点唯一入口 ``aschedule_ingestion``（``transaction.on_commit`` +
background runner 投递，异常全吞永不阻塞主流程）+ 后台执行体
``ingest`` / ``ingest_events``（六步版本翻转事务序 + 四层幂等 + 边精细置位）。

规划定案（13-02-PLAN.md"规划定案"节，供 verify-work 对照）：

1. **OQ-1 措辞映射**：REQUIREMENTS/ROADMAP"旧边写 ``expired_at``"按 Phase 12
   bi-temporal 已定型语义实现为 ``graph_store.invalidate_edge``（置位
   ``invalid_at``，业务时间线失效）——版本替代是业务失效而非记录纠错
   （``expired_at`` 是系统时间线纠错语义）。
2. **边写入位置**：边操作在 ``ingest_events`` 内、``sync_to_async(_persist_sync)``
   完成之后经 graph_store 原语异步执行（**非**严格同事务）。恢复保障三层：
   ① ``uniq_kedge_active`` 约束 + 置位原语幂等使边阶段可重入；
   ② skipped/needs_revector 短路事件仍执行边阶段（任意重触发即自愈）；
   ③ 13-04 reconcile 检查项 6 终极兜底。边阶段为公开函数 ``apply_edge_specs``。
3. **边精细置位**：重摄取**不调**实体作废级联原语（graph_store 的实体级联
   失效函数会失效全部出入边）；只在关系目标变化时置位旧边 + 建新边
   （exclusive EdgeSpec），目标未变时复用既有活跃边。
4. **EdgeSpec 方向语义**：``IngestionEvent.edges`` 表示以本事件实体为 source 的
   出边；多事件批内先持久化全部实体/版本，再统一处理边（两端实体保证已存在）。
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime

import structlog
from asgiref.sync import sync_to_async
from django.db import IntegrityError, transaction

from knowledge.chunking import KnowledgeChunk, chunk_knowledge_text, derive_point_ids
from knowledge.toc_tree import build_toc_tree
from knowledge.collection import ensure_delivery_knowledge_collection, get_embedding_model_name
from knowledge.exceptions import KnowledgeError
from knowledge.graph_store import graph_store, require_aware
from knowledge.models import KnowledgeEntity, KnowledgeEntityVersion, generate_entity_id
from knowledge.sources import get_normalizer
from knowledge.vector_ops import (
    build_knowledge_points,
    delete_points,
    tombstone_points,
    upsert_knowledge_points,
)
from services.background_runner import run_in_background
from services.embedding import EmbeddingService
from services.sparse_encoder import SparseEncoderService

logger = structlog.get_logger(__name__)

__all__ = [
    "EdgeSpec",
    "IngestionEvent",
    "IngestionRequest",
    "apply_edge_specs",
    "aschedule_ingestion",
    "ingest",
    "ingest_events",
    "revectorize_version",
]


@dataclass(frozen=True)
class IngestionRequest:
    """触发点传入的最小定位信息（hook 唯一构造的对象，RESEARCH Pattern 1）。"""

    source_kind: str  # natural key 规则表字面值：coding_plan / mcp_technical_plan / ...
    source_id: str  # 业务对象稳定 ID（CodingPlan UUID str / 飞书三元组拼接 ...）
    trigger: str  # 结构化日志用："chat_plan_created" / "mcp_plan_created" / ...


@dataclass(frozen=True)
class EdgeSpec:
    """出边规格：以本事件实体为 source 的出边（规划定案 4）。

    ``exclusive=True``（如 HAS_PLAN）表示同 relation 同时只允许指向一个 target：
    重摄取时指向其他 target 的活跃边被逐条 ``invalidate_edge``，再建新边。

    target XOR 语义（Phase 14 chunk 边扩展）：``target_entity_id``（实体边）与
    ``target_chunk_id``（MODIFIES_CHUNK 边，弱引用 ChunkRegistry）二选一；
    两者同填或同空的 spec 在 ``apply_edge_specs`` 中 warning 跳过（不 raise 整批）。
    chunk 边不支持 exclusive（语义不适用，``exclusive`` 对 chunk 边忽略）；
    ``metadata`` 落 ``KnowledgeEdge.metadata``（懒解析载体：file_path/symbol/
    commit_sha/resolution 等）。
    """

    relation: str  # EdgeRelation 字面值
    target_entity_id: uuid.UUID | None = None  # 已派生目标实体 id（generate_entity_id 产物）
    exclusive: bool = False
    target_chunk_id: uuid.UUID | None = None  # MODIFIES_CHUNK 边目标（Phase 14）
    metadata: dict | None = None  # 边 metadata（chunk 边懒解析载体）


@dataclass(frozen=True)
class IngestionEvent:
    """normalizer 产出的统一事件（ingest 核心唯一消费的形态）。"""

    kind: str  # EntityKind 字面值
    origin: str  # EntityOrigin 字面值
    source_kind: str
    source_id: str
    title: str
    content: str  # 提炼后全文（embedding 输入；对话原文禁止出现在此）
    payload: dict  # 结构化原文快照（落 KnowledgeEntityVersion.payload）
    space_id: str | None
    repository_id: str | None
    event_time: datetime  # aware（naive 进 GraphStore / 模型层会被拒）
    edges: tuple[EdgeSpec, ...] = ()


async def aschedule_ingestion(
    request: IngestionRequest, *, initiated_by_user_id: str | None = None
) -> None:
    """触发点唯一入口：注册 on_commit → run_in_background 投递后台摄取。

    A1 写法（RESEARCH Pattern 2，全仓唯一正确写法）：``transaction.on_commit``
    操作 per-thread connection 状态，必须经 ``sync_to_async``（thread_sensitive
    默认 True，与 ORM 写同线程）在 sync 线程内注册——autocommit 下回调立即执行，
    atomic 块内延迟到 commit，rollback 时被丢弃。

    ``initiated_by_user_id``（CTX-02）：非空时透传给 ``run_in_background``，由其在
    worker 干净 context 内 ``bind_task_context(source="background")`` 重新绑定发起用户，
    使后台摄取日志可归因；默认 ``None`` 保既有 5 个调用点零回归（无触发用户记 system）。

    任何异常 log warning 不上抛（"永不阻塞主流程"纪律，signals.py 同款）。
    """

    def _register() -> None:
        task_name = f"knowledge-ingest-{request.source_kind}-{request.source_id}"
        transaction.on_commit(
            lambda: run_in_background(
                lambda: ingest(request),
                name=task_name,
                initiated_by_user_id=initiated_by_user_id,
            )
        )

    try:
        await sync_to_async(_register)()
    except Exception as exc:
        logger.warning(
            "knowledge_ingest_schedule_failed",
            trigger=request.trigger,
            source_kind=request.source_kind,
            source_id=request.source_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )


async def ingest(request: IngestionRequest) -> int:
    """background worker 内执行的完整摄取（normalizer → ingest_events）。

    失败 raise（由 background_runner 的 ``background_task_failed`` 日志兜底）。

    Returns:
        normalizer 产出并交付 ``ingest_events`` 的事件数；normalizer 零产出
        （如 Space 不存在 / 无可摄取文档）返回 ``0``。调用方据此区分「真正摄取」
        与「静默零产出」（WR-01：避免零产出被误判为成功）。
    """
    normalize = get_normalizer(request.source_kind)
    events = await normalize(request)
    if not events:
        logger.warning(
            "knowledge_ingest_no_events",
            trigger=request.trigger,
            source_kind=request.source_kind,
            source_id=request.source_id,
        )
        return 0
    await ingest_events(events, trigger=request.trigger)
    return len(events)


@dataclass(frozen=True)
class _PersistResult:
    """``_persist_sync`` 三态结果（skipped / needs_revector / 翻转互斥）。

    ``version`` 仅在并发撞约束的病理 skipped 路径下可能为 None
    （对方刚写入、latest 读取竞态）；三个正常分支均非 None。
    """

    entity: KnowledgeEntity
    version: KnowledgeEntityVersion | None
    point_ids: list[str]
    old_point_ids: list[str]
    skipped: bool = False
    needs_revector: bool = False


async def ingest_events(events: list[IngestionEvent], *, trigger: str = "") -> None:
    """六步版本翻转事务序核心（INGEST-06/07/08）。

    两阶段编排（规划定案 2/4）：
    - 阶段 A（每 event）：步 0 ensure → 预短路判定 → 步 1 chunk/embed →
      步 2 单事务持久化（``_persist_sync``，权威三态判定在锁内）；
    - 阶段 B（全部 event 持久化后）：统一边阶段 ``apply_edge_specs``——
      skipped/needs_revector 短路事件**仍执行**（上次边写失败任意重触发自愈）；
    - 阶段 C（向量序）：步 3 upsert 新点 → 步 4 tombstone 旧点 → 步 5 物理删点；
      needs_revector 走 ``revectorize_version`` 补写（无旧版本可下线）。
    """
    staged: list[tuple[IngestionEvent, _PersistResult, tuple | None]] = []

    # ---- 阶段 A：每 event 预检 / 向量化 / 单事务持久化 ----
    for event in events:
        require_aware(event.event_time, "event_time")
        # 步 0：collection 自检（mismatch raise → 整次摄取响亮 abort）
        await ensure_delivery_knowledge_collection()

        content_hash = hashlib.sha256(event.content.encode("utf-8")).hexdigest()
        entity_id = generate_entity_id(event.kind, event.source_kind, event.source_id)

        # 预短路（embed 前，无锁预读）：常态重复触发不白付远程 embedding；
        # 权威判定仍在 _persist_sync 锁内，本处只是优化短路。
        latest = (
            await KnowledgeEntityVersion.objects.select_related("entity")
            .filter(entity_id=entity_id, is_latest=True)
            .afirst()
        )
        if latest is not None and latest.content_hash == content_hash and latest.vector_synced:
            logger.info(
                "knowledge_ingest_skipped",
                entity_id=str(entity_id),
                trigger=trigger,
                stage="pre_embed",
            )
            staged.append(
                (
                    event,
                    _PersistResult(
                        entity=latest.entity,
                        version=latest,
                        point_ids=[str(p) for p in latest.qdrant_point_ids],
                        old_point_ids=[],
                        skipped=True,
                    ),
                    None,
                )
            )
            continue

        # 步 1：确定性切块 + dense/sparse 向量化（任一 None → 整体 abort，零写入）
        chunks = chunk_knowledge_text(event.title, event.content)
        texts = [c.text for c in chunks]
        dense = await EmbeddingService.generate_embeddings_batch(texts)
        failed = [i for i, vec in enumerate(dense) if vec is None]
        if failed:
            raise KnowledgeError(
                "embedding 批量结果含 None，整体 abort（禁止写入残缺向量）",
                details={"entity_id": str(entity_id), "failed_chunk_indexes": failed},
            )
        sparse = await sync_to_async(SparseEncoderService.encode_batch)(texts)

        # 步 2：单事务持久化（权威三态判定在 select_for_update 锁内）
        result = await sync_to_async(_persist_sync)(event, chunks)
        if result.skipped:
            logger.info(
                "knowledge_ingest_skipped",
                entity_id=str(entity_id),
                trigger=trigger,
                stage="locked",
            )
        staged.append((event, result, (chunks, dense, sparse)))

    # ---- 阶段 B：全部实体/版本持久化后统一处理边（含短路事件，幂等自愈）----
    for event, result, _vectors in staged:
        await apply_edge_specs(result.entity.id, event.edges, event_time=event.event_time)

    # ---- 阶段 C：向量序（步 3 → 步 4 → 步 5）----
    for event, result, vectors in staged:
        if result.skipped:
            continue
        if result.needs_revector:
            # hash 相同但向量缺失（上次 crash 于向量步骤）：只补写向量，
            # 无 tombstone / 删点——没有被替代的旧版本（INGEST-07 铁律）。
            await revectorize_version(result.version)  # type: ignore[arg-type]
            continue
        chunks, dense, sparse = vectors  # type: ignore[misc]  # 翻转事件必经步 1
        model_name = await get_embedding_model_name()
        points = build_knowledge_points(
            entity=result.entity,
            version=result.version,  # type: ignore[arg-type]
            chunks=chunks,
            dense_vectors=dense,
            sparse_vectors=sparse,
            point_ids=result.point_ids,
            embedding_model=model_name,
        )
        # 步 3：失败直接 raise——新版本已落库 vector_synced=False，
        # 重触发走 needs_revector 路径补写，或 13-04 reconcile 兜底。
        await upsert_knowledge_points(points)
        await KnowledgeEntityVersion.objects.filter(id=result.version.id).aupdate(  # type: ignore[union-attr]
            vector_synced=True
        )
        # 步 4：tombstone 失败必须响亮但不再上抛——DB is_latest 翻转已是
        # 第一道防线，旧点残留由 13-04 reconcile 检查项 2 修复。
        try:
            await tombstone_points(result.old_point_ids)
        except Exception as exc:
            logger.error(
                "knowledge_ingest_tombstone_failed",
                entity_id=str(result.entity.id),
                point_count=len(result.old_point_ids),
                error=str(exc),
                error_type=type(exc).__name__,
            )
        # 步 5：物理删点纯优化层（vector_ops 内已吞 + error 日志）
        await delete_points(result.old_point_ids)
        logger.info(
            "knowledge_ingest_version_committed",
            entity_id=str(result.entity.id),
            version=result.version.version,  # type: ignore[union-attr]
            point_count=len(result.point_ids),
            old_point_count=len(result.old_point_ids),
            trigger=trigger,
        )


async def apply_edge_specs(
    entity_id: uuid.UUID, edges: tuple[EdgeSpec, ...], *, event_time: datetime
) -> None:
    """边阶段公开函数（幂等可重入；13-04 reconcile 检查项 6 --fix 复用）。

    对每个 EdgeSpec（规划定案 3，OQ-1 定案：业务失效置位 ``invalid_at``，
    不写 ``expired_at``——那是系统时间线纠错语义）：

    - target XOR 不满足（双填/双空）→ warning 跳过该 spec（不 raise 整批）；
    - 已有指向同 target 的活跃出边 → 跳过（复用，无新边无置位）；
    - ``exclusive=True`` 时指向其他 target 的活跃边逐条
      ``graph_store.invalidate_edge``（仅实体边；chunk 边语义不适用，忽略）；
    - 随后 ``graph_store.add_edge`` 建新边，IntegrityError 视为并发已建
      （``uniq_kedge_active`` / ``uniq_kedge_chunk_active`` 撞约束），
      幂等放弃 + warning。

    chunk 边（Phase 14）：按 ``edge.target_chunk_id`` 比对既有活跃出边去重，
    metadata 落 ``KnowledgeEdge.metadata``——chunk 边写入只走本函数唯一通路
    （RESEARCH 选项 A 定案），normalizer 不得直接调 graph_store。
    """
    for spec in edges:
        if (spec.target_entity_id is None) == (spec.target_chunk_id is None):
            logger.warning(
                "knowledge_ingest_edge_spec_invalid",
                source_id=str(entity_id),
                relation=spec.relation,
                target_entity_id=str(spec.target_entity_id) if spec.target_entity_id else None,
                target_chunk_id=str(spec.target_chunk_id) if spec.target_chunk_id else None,
                reason="target_entity_id 与 target_chunk_id 必须二选一（XOR）",
            )
            continue
        existing = await graph_store.neighbors(
            entity_id, relations=[spec.relation], direction="out"
        )
        if spec.target_chunk_id is not None:
            # chunk 边分支：按 target_chunk_id 去重，不支持 exclusive
            if any(edge.target_chunk_id == spec.target_chunk_id for edge in existing):
                continue
            try:
                await graph_store.add_edge(
                    source_id=entity_id,
                    target_chunk_id=spec.target_chunk_id,
                    relation=spec.relation,
                    valid_at=event_time,
                    metadata=spec.metadata,
                )
            except IntegrityError as exc:
                logger.warning(
                    "knowledge_ingest_edge_conflict",
                    source_id=str(entity_id),
                    target_chunk_id=str(spec.target_chunk_id),
                    relation=spec.relation,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
            continue
        if any(edge.target_id == spec.target_entity_id for edge in existing):
            continue
        if spec.exclusive:
            for edge in existing:
                if edge.target_id is not None and edge.target_id != spec.target_entity_id:
                    await graph_store.invalidate_edge(edge.edge_id, invalid_at=event_time)
        try:
            await graph_store.add_edge(
                source_id=entity_id,
                target_id=spec.target_entity_id,
                relation=spec.relation,
                valid_at=event_time,
            )
        except IntegrityError as exc:
            logger.warning(
                "knowledge_ingest_edge_conflict",
                source_id=str(entity_id),
                target_id=str(spec.target_entity_id),
                relation=spec.relation,
                error=str(exc),
                error_type=type(exc).__name__,
            )


async def revectorize_version(version: KnowledgeEntityVersion) -> None:
    """对既有版本补写向量并置 ``vector_synced=True``。

    needs_revector 路径 / 13-04 reconcile --fix / rebuild 全量重嵌入复用：
    从已存 ``version.content`` 重走 chunk → embed → build → upsert；
    point ids 复用已存 ``qdrant_point_ids``（为空或数量不符时按确定性
    派生回写）。无版本级 tombstone / 删点——本路径没有被替代的旧版本；
    但 chunk 数**收缩**时被覆写丢弃的旧多余点必须先下线（见函数体注释）。
    """
    entity = await KnowledgeEntity.objects.aget(id=version.entity_id)
    chunks = chunk_knowledge_text(entity.title, version.content)
    texts = [c.text for c in chunks]
    dense = await EmbeddingService.generate_embeddings_batch(texts)
    failed = [i for i, vec in enumerate(dense) if vec is None]
    if failed:
        raise KnowledgeError(
            "revectorize embedding 批量结果含 None，整体 abort",
            details={"version_id": str(version.id), "failed_chunk_indexes": failed},
        )
    sparse = await sync_to_async(SparseEncoderService.encode_batch)(texts)

    point_ids = [str(pid) for pid in version.qdrant_point_ids]
    if len(point_ids) != len(chunks):
        new_ids = derive_point_ids(version.id, len(chunks))
        # WR-01 防线：chunk 数收缩时（如调大 MAX_CHUNK_CHARS 后 rebuild），
        # index ≥ 新数量的旧点若被直接覆写丢弃，会以 is_latest=True 残留
        # 且对 reconcile 六检查项全部免疫（version_id 在 PG 存在、所属版本
        # 仍是 latest、检查项 1 只核对覆写后的新 ids）——覆写前必须先下线。
        dropped = [pid for pid in point_ids if pid not in set(new_ids)]
        if dropped:
            # 失败语义与六步序一致：tombstone 失败响亮（error 日志）但不上抛，
            # 物理删点纯优化（vector_ops 内已吞 + error 日志）。
            try:
                await tombstone_points(dropped)
            except Exception as exc:
                logger.error(
                    "knowledge_revectorize_tombstone_failed",
                    version_id=str(version.id),
                    point_count=len(dropped),
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
            await delete_points(dropped)
        point_ids = new_ids
        version.qdrant_point_ids = point_ids
        await version.asave(update_fields=["qdrant_point_ids"])

    model_name = await get_embedding_model_name()
    points = build_knowledge_points(
        entity=entity,
        version=version,
        chunks=chunks,
        dense_vectors=dense,
        sparse_vectors=sparse,
        point_ids=point_ids,
        embedding_model=model_name,
    )
    await upsert_knowledge_points(points)
    version.vector_synced = True
    await version.asave(update_fields=["vector_synced"])
    logger.info(
        "knowledge_ingest_revectorized",
        version_id=str(version.id),
        point_count=len(point_ids),
    )


def _persist_sync(event: IngestionEvent, chunks: list[KnowledgeChunk]) -> _PersistResult:
    """步 2 单事务持久化：``select_for_update`` 串行化 + 权威三态幂等判定。

    三态判定（INGEST-07 铁律：hash 相等绝不产生新版本）：

    ① hash 相同 AND ``vector_synced=True`` → skipped（完整幂等短路）；
    ② hash 相同 AND ``vector_synced=False`` → needs_revector
      （上次 crash 于向量步骤：不建新版本行、不置 ``invalid_at``，
      返回既有 latest，向量补写交给阶段 C）；
    ③ hash 不同 → 版本翻转：旧 latest ``is_latest=False`` + ``invalid_at``
      置位（业务失效）；新版本行 ``supersedes`` 链 + 确定性 point ids 预写
      （``vector_synced=False``，步 3 成功后才置 True）。

    并发撞 ``uniq_kversion_one_latest``（Pitfall 3）：对方已写入更新内容，
    捕获 IntegrityError → skipped + warning（重触发会 hash 短路）。
    """
    content_hash = hashlib.sha256(event.content.encode("utf-8")).hexdigest()
    entity_id = generate_entity_id(event.kind, event.source_kind, event.source_id)
    try:
        with transaction.atomic():
            entity, _created = KnowledgeEntity.objects.select_for_update().get_or_create(
                id=entity_id,
                defaults={
                    "kind": event.kind,
                    "origin": event.origin,
                    "source_kind": event.source_kind,
                    "source_id": event.source_id,
                    "title": event.title[:500],
                    "space_id": event.space_id,
                    "repository_id": event.repository_id,
                    "event_time": event.event_time,
                },
            )
            latest = entity.versions.filter(is_latest=True).first()
            if latest is not None and latest.content_hash == content_hash:
                point_ids = [str(p) for p in latest.qdrant_point_ids]
                if latest.vector_synced:
                    return _PersistResult(
                        entity=entity,
                        version=latest,
                        point_ids=point_ids,
                        old_point_ids=[],
                        skipped=True,
                    )
                return _PersistResult(
                    entity=entity,
                    version=latest,
                    point_ids=point_ids,
                    old_point_ids=[],
                    needs_revector=True,
                )

            old_point_ids = [str(p) for p in latest.qdrant_point_ids] if latest else []
            if latest is not None:
                latest.is_latest = False
                latest.invalid_at = event.event_time
                latest.save(update_fields=["is_latest", "invalid_at"])

            new_version_id = uuid.uuid4()
            point_ids = derive_point_ids(new_version_id, len(chunks))
            # PageIndex 章节树：确定性纯函数，与 chunks 同源生成（标题层级优先）
            toc_tree = build_toc_tree(
                event.title, event.content, [c.text for c in chunks]
            )
            new_version = KnowledgeEntityVersion.objects.create(
                id=new_version_id,
                entity=entity,
                version=(latest.version + 1 if latest else 1),
                supersedes=latest,
                content=event.content,
                content_hash=content_hash,
                payload=event.payload,
                qdrant_point_ids=point_ids,
                toc_tree=toc_tree,
                is_latest=True,
                vector_synced=False,
                event_time=event.event_time,
                valid_at=event.event_time,
            )
            entity.current_version = new_version.version
            entity.title = event.title[:500]
            entity.event_time = event.event_time
            entity.save(update_fields=["current_version", "title", "event_time", "updated_at"])
            return _PersistResult(
                entity=entity,
                version=new_version,
                point_ids=point_ids,
                old_point_ids=old_point_ids,
            )
    except IntegrityError as exc:
        logger.warning(
            "knowledge_ingest_concurrent_conflict",
            entity_id=str(entity_id),
            error=str(exc),
            error_type=type(exc).__name__,
        )
        entity = KnowledgeEntity.objects.get(id=entity_id)
        latest = entity.versions.filter(is_latest=True).first()
        return _PersistResult(
            entity=entity,
            version=latest,
            point_ids=[str(p) for p in latest.qdrant_point_ids] if latest else [],
            old_point_ids=[],
            skipped=True,
        )
