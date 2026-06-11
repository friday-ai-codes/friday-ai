"""`reconcile_delivery_knowledge` 管理命令：DB ↔ Qdrant 漂移对账（Plan 13-04，INGEST-06/07）。

is_latest 翻转是版本下线的第一道防线，本命令是兜底防线——六步摄取序中
步 3（upsert 新点）/ 步 4（tombstone 旧点）/ 步 5（物理删点）的全部失败后果
（RESEARCH 失败恢复矩阵"恢复方式"列）都由本命令检测并经 ``--fix`` 闭环修复，
含"content_hash 短路掩盖向量缺失"（Pitfall 2）与 tombstone 失败残留。

六检查项（1–5 为 DB↔Qdrant 漂移，6 为边一致性兜底——13-02 定案
"边非严格同事务"的终极恢复层）：

1. latest 版本向量完整性：point 缺失 / payload ``is_latest``、``version`` 不符
   → 计 missing；--fix 经 ``revectorize_version`` 重嵌入（不重走版本翻转）。
2. 非 latest 残留：旧版本的点 payload 仍 ``is_latest=true``（tombstone 失败，
   唯一影响检索正确性的 commit 后失败）→ 计 stale_latest；--fix
   tombstone + 物理删除。
3. 多版本 latest：Qdrant 召回面同 entity 多 version 命中 ``is_latest=true``
   → 计 multi_latest；--fix 按 DB 真值 tombstone 非 latest 的点。
4. 孤儿点：payload ``version_id`` 不在 PG → 计 orphan；--fix 物理删除。
5. DB 不变量抽检（report-only，恒不 fix）：单实体多 latest（约束兜底理论恒 0）、
   ``invalid_at <= valid_at``、``vector_synced=False`` 的 latest 计数。
6. 边一致性：``origin=mcp`` 且 ``kind=tech_plan`` 的 latest 实体应有活跃
   HAS_PLAN 入边 → 缺失计 missing_edges；--fix 经 normalizer 重建事件取
   EdgeSpec 后调 ``apply_edge_specs`` 补建。

纪律（``verify_payload_consistency`` 同款形态）：
- 默认 dry-run 零写副作用，``--fix`` 显式 opt-in（防误操作，T-13-03）；
- 单 entity/version 检查异常 → skip 计数 + warning，不崩整命令（残缺数据
  下命令仍完整跑完并报告）；
- 修复删点只按 point id 列表（``delete_points``），绝不按业务 filter 删（P1）；
- 对账以 DB 为真值单向修复，禁止按 Qdrant 反向改 DB。

**用法：**

    python manage.py reconcile_delivery_knowledge            # dry-run 全量
    python manage.py reconcile_delivery_knowledge --limit 50 # dry-run 抽检
    python manage.py reconcile_delivery_knowledge --fix      # 检出并修复
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import Count, F
from qdrant_client import models

from knowledge import ingestion, vector_ops
from knowledge.collection import DELIVERY_KNOWLEDGE_COLLECTION
from knowledge.graph_store import graph_store
from knowledge.models import (
    EdgeRelation,
    EntityKind,
    EntityOrigin,
    KnowledgeEntity,
    KnowledgeEntityVersion,
    generate_entity_id,
)
from services.qdrant_service import QdrantService

logger = structlog.get_logger(__name__)

# scroll 分页批大小（遍历召回面用；与 vector_ops 批量编排同量级）
_SCROLL_BATCH_SIZE = 256


class Command(BaseCommand):
    """对账 delivery_knowledge：六检查项检测 DB↔Qdrant 漂移，--fix 修复。"""

    help = (
        "对账 PG 知识版本链与 Qdrant delivery_knowledge 召回面：检测 latest 向量缺失、"
        "非 latest 残留、多版本 latest、孤儿点、DB 不变量与 HAS_PLAN 边一致性；"
        "--fix 显式 opt-in 修复（默认 dry-run 零写）"
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--fix",
            action="store_true",
            help="检出漂移时执行修复（重嵌入 / tombstone+删点 / 边补建）；默认 dry-run",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="DB 侧迭代检查（检查项 1/2/6）的抽检上限；0=全量（default 0）",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        fix_mode: bool = options["fix"]
        limit: int = options["limit"]
        if limit < 0:
            raise CommandError("--limit 不能为负数")

        logger.info("knowledge_reconcile_started", fix=fix_mode, limit=limit)
        counters = asyncio.run(self._run(fix_mode, limit))
        self.stdout.write("-" * 78)
        self.stdout.write(
            "Summary: "
            f"checked={counters['checked']} "
            f"missing={counters['missing']} "
            f"stale_latest={counters['stale_latest']} "
            f"multi_latest={counters['multi_latest']} "
            f"orphans={counters['orphans']} "
            f"db_anomalies={counters['db_anomalies']} "
            f"missing_edges={counters['missing_edges']} "
            f"skipped={counters['skipped']} "
            f"fixed={counters['fixed']}"
        )
        logger.info("knowledge_reconcile_finished", **counters)

    async def _run(self, fix_mode: bool, limit: int) -> dict[str, int]:
        """顺序执行六检查项；任一检查项整体失败也只 skip 计数，不崩命令。"""
        client = QdrantService.get_client()
        counters = {
            "checked": 0,
            "missing": 0,
            "stale_latest": 0,
            "multi_latest": 0,
            "orphans": 0,
            "db_anomalies": 0,
            "missing_edges": 0,
            "skipped": 0,
            "fixed": 0,
        }
        checks = [
            ("latest_vectors", self._check_latest_versions),
            ("stale_latest", self._check_non_latest_versions),
            ("multi_latest", self._check_multi_latest),
            ("orphans", self._check_orphans),
            ("db_invariants", self._check_db_invariants),
            ("missing_edges", self._check_missing_edges),
        ]
        for name, check in checks:
            try:
                await check(client, fix_mode, limit, counters)
            except Exception as exc:
                # 检查项级隔离：scroll/批量查询整体失败也不崩，记 skip + warning
                counters["skipped"] += 1
                logger.warning(
                    "knowledge_reconcile_item_skipped",
                    check=name,
                    scope="check",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
        return counters

    # ------------------------------------------------------------------
    # 检查项 1：latest 版本向量完整性（missing；--fix 重嵌入）
    # ------------------------------------------------------------------
    async def _check_latest_versions(
        self, client: Any, fix_mode: bool, limit: int, counters: dict[str, int]
    ) -> None:
        qs = (
            KnowledgeEntityVersion.objects.filter(is_latest=True)
            .select_related("entity")
            .order_by("created_at")
        )
        if limit:
            qs = qs[:limit]
        async for version in qs:
            counters["checked"] += 1
            try:
                if await self._latest_version_drifted(client, version):
                    counters["missing"] += 1
                    if fix_mode:
                        # 重嵌入 upsert（不重走版本翻转——没有被替代的旧版本）
                        await ingestion.revectorize_version(version)
                        counters["fixed"] += 1
            except Exception as exc:
                counters["skipped"] += 1
                logger.warning(
                    "knowledge_reconcile_item_skipped",
                    check="latest_vectors",
                    version_id=str(version.id),
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
        self.stdout.write(
            f"检查项 1（latest 向量完整性）: checked={counters['checked']} "
            f"missing={counters['missing']}"
        )

    @staticmethod
    async def _latest_version_drifted(client: Any, version: KnowledgeEntityVersion) -> bool:
        """latest 版本漂移判定：点缺失 / payload is_latest 非 true / version 不符。"""
        point_ids = [str(pid) for pid in version.qdrant_point_ids]
        if not point_ids:
            # 无 point ids 的 latest 版本（步 3 前 crash 的残骸）也视为缺失
            return True
        records = await sync_to_async(client.retrieve)(
            collection_name=DELIVERY_KNOWLEDGE_COLLECTION,
            ids=point_ids,
            with_payload=["is_latest", "version"],
        )
        by_id = {str(record.id): record for record in records}
        for pid in point_ids:
            record = by_id.get(pid)
            if record is None:
                return True
            payload = record.payload or {}
            if payload.get("is_latest") is not True:
                return True
            if payload.get("version") != version.version:
                return True
        return False

    # ------------------------------------------------------------------
    # 检查项 2：非 latest 残留（stale_latest；--fix tombstone + 删点）
    # ------------------------------------------------------------------
    async def _check_non_latest_versions(
        self, client: Any, fix_mode: bool, limit: int, counters: dict[str, int]
    ) -> None:
        qs = KnowledgeEntityVersion.objects.filter(is_latest=False).order_by("created_at")
        if limit:
            qs = qs[:limit]
        async for version in qs:
            point_ids = [str(pid) for pid in version.qdrant_point_ids]
            if not point_ids:
                continue
            try:
                records = await sync_to_async(client.retrieve)(
                    collection_name=DELIVERY_KNOWLEDGE_COLLECTION,
                    ids=point_ids,
                    with_payload=["is_latest"],
                )
                stale_ids = [
                    str(record.id)
                    for record in records
                    if (record.payload or {}).get("is_latest") is True
                ]
                if stale_ids:
                    counters["stale_latest"] += 1
                    if fix_mode:
                        await vector_ops.tombstone_points(stale_ids)
                        await vector_ops.delete_points(stale_ids)
                        counters["fixed"] += 1
            except Exception as exc:
                counters["skipped"] += 1
                logger.warning(
                    "knowledge_reconcile_item_skipped",
                    check="stale_latest",
                    version_id=str(version.id),
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
        self.stdout.write(f"检查项 2（非 latest 残留）: stale_latest={counters['stale_latest']}")

    # ------------------------------------------------------------------
    # 检查项 3：多版本 latest（multi_latest；--fix 按 DB 真值 tombstone）
    # ------------------------------------------------------------------
    async def _check_multi_latest(
        self, client: Any, fix_mode: bool, limit: int, counters: dict[str, int]
    ) -> None:
        latest_filter = models.Filter(
            must=[models.FieldCondition(key="is_latest", match=models.MatchValue(value=True))]
        )
        records = await self._scroll_points(client, latest_filter)
        # entity_id → {version: [point ids]}（召回面聚合）
        by_entity: dict[str, dict[int, list[str]]] = {}
        for record in records:
            payload = record.payload or {}
            entity_id = payload.get("entity_id")
            version_no = payload.get("version")
            if not entity_id or version_no is None:
                continue
            by_entity.setdefault(str(entity_id), {}).setdefault(int(version_no), []).append(
                str(record.id)
            )
        for entity_id, versions in by_entity.items():
            if len(versions) <= 1:
                continue
            counters["multi_latest"] += 1
            if not fix_mode:
                continue
            try:
                db_latest = await KnowledgeEntityVersion.objects.filter(
                    entity_id=uuid.UUID(entity_id), is_latest=True
                ).afirst()
                if db_latest is None:
                    # DB 无 latest 真值可对齐（孤儿一族，交检查项 4 处理）
                    counters["skipped"] += 1
                    continue
                stale_ids = [
                    pid
                    for version_no, pids in versions.items()
                    if version_no != db_latest.version
                    for pid in pids
                ]
                await vector_ops.tombstone_points(stale_ids)
                counters["fixed"] += 1
            except Exception as exc:
                counters["skipped"] += 1
                logger.warning(
                    "knowledge_reconcile_item_skipped",
                    check="multi_latest",
                    entity_id=entity_id,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
        self.stdout.write(f"检查项 3（多版本 latest）: multi_latest={counters['multi_latest']}")

    # ------------------------------------------------------------------
    # 检查项 4：孤儿点（orphans；--fix 物理删除）
    # ------------------------------------------------------------------
    async def _check_orphans(
        self, client: Any, fix_mode: bool, limit: int, counters: dict[str, int]
    ) -> None:
        records = await self._scroll_points(client, None)
        version_to_points: dict[str, list[str]] = {}
        for record in records:
            payload = record.payload or {}
            version_id = str(payload.get("version_id") or "")
            version_to_points.setdefault(version_id, []).append(str(record.id))

        candidate_ids: list[uuid.UUID] = []
        for version_id in version_to_points:
            try:
                candidate_ids.append(uuid.UUID(version_id))
            except ValueError:
                continue  # 非法 version_id（含空串）直接按孤儿处理
        existing = {
            str(vid)
            async for vid in KnowledgeEntityVersion.objects.filter(
                id__in=candidate_ids
            ).values_list("id", flat=True)
        }
        orphan_ids = [
            pid
            for version_id, pids in version_to_points.items()
            if version_id not in existing
            for pid in pids
        ]
        counters["orphans"] += len(orphan_ids)
        if fix_mode and orphan_ids:
            await vector_ops.delete_points(orphan_ids)
            counters["fixed"] += 1
        self.stdout.write(f"检查项 4（孤儿点）: orphans={counters['orphans']}")

    # ------------------------------------------------------------------
    # 检查项 5：DB 不变量抽检（report-only，恒不 fix——约束兜底理论恒 0）
    # ------------------------------------------------------------------
    async def _check_db_invariants(
        self, client: Any, fix_mode: bool, limit: int, counters: dict[str, int]
    ) -> None:
        multi_latest_db = await sync_to_async(
            lambda: KnowledgeEntityVersion.objects.filter(is_latest=True)
            .values("entity_id")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
            .count()
        )()
        invalid_range = await KnowledgeEntityVersion.objects.filter(
            invalid_at__isnull=False, invalid_at__lte=F("valid_at")
        ).acount()
        unsynced_latest = await KnowledgeEntityVersion.objects.filter(
            is_latest=True, vector_synced=False
        ).acount()
        counters["db_anomalies"] += multi_latest_db + invalid_range + unsynced_latest
        self.stdout.write(
            f"检查项 5（DB 不变量）: db_anomalies={counters['db_anomalies']}"
            f"（multi_latest_db={multi_latest_db} invalid_range={invalid_range} "
            f"unsynced_latest={unsynced_latest}）"
        )

    # ------------------------------------------------------------------
    # 检查项 6：HAS_PLAN 边一致性（missing_edges；--fix 经 normalizer 补建）
    # ------------------------------------------------------------------
    async def _check_missing_edges(
        self, client: Any, fix_mode: bool, limit: int, counters: dict[str, int]
    ) -> None:
        qs = (
            KnowledgeEntity.objects.filter(
                origin=EntityOrigin.MCP,
                kind=EntityKind.TECH_PLAN,
                versions__is_latest=True,
            )
            .distinct()
            .order_by("created_at")
        )
        if limit:
            qs = qs[:limit]
        async for entity in qs:
            try:
                in_edges = await graph_store.neighbors(
                    entity.id, relations=[EdgeRelation.HAS_PLAN], direction="in"
                )
                if in_edges:
                    continue
                counters["missing_edges"] += 1
                if fix_mode:
                    if await self._fix_missing_edge(entity):
                        counters["fixed"] += 1
                    else:
                        counters["skipped"] += 1
            except Exception as exc:
                counters["skipped"] += 1
                logger.warning(
                    "knowledge_reconcile_item_skipped",
                    check="missing_edges",
                    entity_id=str(entity.id),
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
        self.stdout.write(
            f"检查项 6（HAS_PLAN 边一致性）: missing_edges={counters['missing_edges']}"
        )

    @staticmethod
    async def _fix_missing_edge(entity: KnowledgeEntity) -> bool:
        """经 normalizer 重建事件取 EdgeSpec 后补建边（apply_edge_specs 幂等可重入）。

        normalizer 不可用（KeyError）或源对象已删（事件无边可补）时返回 False，
        调用方计 skip + warning，不崩命令。
        """
        from knowledge import sources  # lazy import：normalizer 注册表按需加载

        try:
            normalize = sources.get_normalizer(entity.source_kind)
        except KeyError:
            logger.warning(
                "knowledge_reconcile_normalizer_unavailable",
                entity_id=str(entity.id),
                source_kind=entity.source_kind,
            )
            return False
        events = await normalize(
            ingestion.IngestionRequest(
                source_kind=entity.source_kind,
                source_id=entity.source_id,
                trigger="reconcile_fix",
            )
        )
        applied = False
        for event in events:
            if not event.edges:
                continue
            source_id = generate_entity_id(event.kind, event.source_kind, event.source_id)
            await ingestion.apply_edge_specs(source_id, event.edges, event_time=event.event_time)
            applied = True
        if not applied:
            logger.warning(
                "knowledge_reconcile_edge_source_missing",
                entity_id=str(entity.id),
                source_kind=entity.source_kind,
                source_id=entity.source_id,
            )
        return applied

    # ------------------------------------------------------------------
    # 工具：scroll 全量遍历（分页直至 next_offset 为 None）
    # ------------------------------------------------------------------
    @staticmethod
    async def _scroll_points(client: Any, scroll_filter: models.Filter | None) -> list[Any]:
        records: list[Any] = []
        offset = None
        while True:
            batch, offset = await sync_to_async(client.scroll)(
                collection_name=DELIVERY_KNOWLEDGE_COLLECTION,
                scroll_filter=scroll_filter,
                with_payload=["entity_id", "version", "version_id", "is_latest"],
                with_vectors=False,
                limit=_SCROLL_BATCH_SIZE,
                offset=offset,
            )
            records.extend(batch)
            if offset is None:
                return records
