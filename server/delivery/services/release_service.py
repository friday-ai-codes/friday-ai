"""ReleaseService —— Release 账本（ReleaseBatch/ReleaseRecord/ReleaseArtifact）唯一写入入口（REL-01，INV-6）。

Release 账本落库的单一写入收口：所有路径（31-03 Bitable adapter / 未来手动录入）
都经本服务收敛，**禁旁路写 ReleaseBatch/ReleaseRecord/ReleaseArtifact 表**
（test_release_inv6_guard.py grep 守护）。结构镜像 ``DocumentService`` /
``WorkItemService`` 单一写入范式：async 公共方法 + ``@sync_to_async`` 包同步
``transaction.atomic`` 写库；``structlog`` 结构化日志。

宽容收口范式（对齐 CONTEXT Grey Area 3 / REL-01）：

- ``ingest_batch`` 把一批 Bitable 原始行 → 一个 ``ReleaseBatch`` + 多条
  ``ReleaseRecord``，**raw_row 始终原样保留**（adapter 演进 / 列映射变化不丢数据）。
- ``ReleaseRecord`` 按 ``bitable_record_key`` 幂等 upsert（同 key 重摄收敛同行，
  复用 ``select_for_update().get_or_create`` + 31-01 条件唯一约束防并发重复）。
- ``work_item`` 经 ``work_item_external_id`` 反查已落库 ``WorkItem``：命中连 FK，
  未命中留 ``work_item_external_id`` 占位 + ``work_item=None``（不抛——对齐
  ``WorkItemRelation`` / ``Document.work_item`` 占位范式）。

**自然键契约（natural-key contract，单一来源）**：ReleaseService 把传入行里
**预先组装好的** ``bitable_record_key`` 作为自然键的唯一来源——读 ``record_key``
显式入参，缺省则读 ``raw_row["bitable_record_key"]``。**绝不**在本服务内由顶层
``app_token``/``table_id``/``record_id`` 重新拼接 natural key（拼接归 31-03 adapter
经 ``build_bitable_record_key`` 收口；本服务只消费成品 key，避免拼接逻辑漂移）。

降级策略（§1.4 / T-31-04）：``ingest_batch`` 逐行 best-effort try/except——单行
映射异常不回滚整批、不冒泡致整批失败，已建 batch 与成功行保留。

业务列 → 字段的真实 Bitable 列映射归 v2 REL-03（待开放平台凭证 + 列样例）；本
phase 仅占位映射（从 raw_row 顶层同名键取值），相关处标 ``TODO(REL-03)``。
"""

from __future__ import annotations

from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.db import transaction

from delivery.models import (
    ReleaseArtifact,
    ReleaseBatch,
    ReleaseRecord,
    WorkItem,
)

logger = structlog.get_logger(__name__)

__all__ = ["ReleaseService"]


class ReleaseService:
    """Release 账本唯一写入入口（INV-6）。"""

    async def ingest_batch(
        self,
        *,
        raw_rows: list[dict[str, Any]],
        source: str,
        batch_meta: dict[str, Any] | None = None,
    ) -> ReleaseBatch:
        """**Release 账本落库唯一写入收口**：一批原始行 → 1 个 ReleaseBatch + N 条 ReleaseRecord。

        每行经 ``upsert_record`` 按 ``bitable_record_key`` 幂等 upsert（raw_row 无损
        保留）。逐行 best-effort：单行映射异常不回滚整批（§1.4 降级），已建 batch 与
        成功行保留。

        Args:
            raw_rows: Bitable 原始行列表（含预组装 ``bitable_record_key``；不可信外部输入）。
            source: ``ReleaseSource`` 值（bitable / manual）。
            batch_meta: 批次级元信息（name/released_at/external_ref + 原始内容落 raw_row）。

        Returns:
            收口后的 ``ReleaseBatch``（records 已落库）。
        """
        meta = batch_meta or {}
        batch = await self._resolve_batch(source=source, batch_meta=meta)

        success = 0
        for raw_row in raw_rows:
            try:
                await self.upsert_record(batch=batch, raw_row=raw_row, source=source)
                success += 1
            except Exception as exc:  # best-effort：单行畸形不回滚整批（T-31-04）
                logger.warning(
                    "release_record_ingest_failed",
                    batch_id=str(batch.id),
                    error=str(exc),
                )

        logger.info(
            "release_batch_ingested",
            batch_id=str(batch.id),
            source=source,
            record_count=success,
            total_rows=len(raw_rows),
        )
        return batch

    async def upsert_record(
        self,
        *,
        batch: ReleaseBatch,
        raw_row: dict[str, Any],
        source: str,
        record_key: str | None = None,
    ) -> ReleaseRecord:
        """单行 upsert 的 async 公共方法（供 31-03 adapter / 未来手动录入复用）。

        委托 ``_upsert_record`` 在同步原子事务内落库。``record_key`` 显式入参优先，
        缺省读 ``raw_row["bitable_record_key"]``（自然键契约：消费预组装成品 key）。
        """
        return await self._upsert_record(
            batch=batch, raw_row=raw_row, source=source, record_key=record_key
        )

    async def add_artifact(
        self,
        *,
        release_record: ReleaseRecord,
        artifact_type: str,
        ref: str = "",
        payload: dict[str, Any] | None = None,
    ) -> ReleaseArtifact:
        """新增上线证据（MR / 分支 / commit / ...）——同样经 service 收口（不旁路写表）。"""
        return await self._create_artifact(
            release_record=release_record,
            artifact_type=artifact_type,
            ref=ref,
            payload=payload or {},
        )

    @sync_to_async
    def _resolve_batch(self, *, source: str, batch_meta: dict[str, Any]) -> ReleaseBatch:
        """幂等解析 ReleaseBatch（batch_meta 原始内容落 raw_row 保留，REL-01 / WR-02）。

        非空 ``external_ref`` → 按其作 batch 稳定自然键 ``select_for_update().get_or_create``
        收敛同批（条件唯一约束 ``uniq_release_batch_external_ref`` 防并发重复）：重复摄取
        同一张表（external_ref=``{app_token}:{table_id}``）复用同一 ReleaseBatch，不累积
        空批次、ingested 记录均挂回这一复用批次。已存在时刷新批次元信息（raw_row 无损覆盖
        为最新，镜像 record 级 upsert）。空 ``external_ref``（如手动录入未给键）→ 直接 create
        （豁免唯一，允许多批共存）。
        """
        external_ref = batch_meta.get("external_ref", "")
        # TODO(REL-03): 批次级字段的真实 Bitable 列映射待开放平台凭证 + 列样例。
        defaults = {
            "source": source,
            "name": batch_meta.get("name", ""),
            "released_at": batch_meta.get("released_at"),
            "raw_row": batch_meta,
        }

        with transaction.atomic():
            if external_ref:
                batch, created = ReleaseBatch.objects.select_for_update().get_or_create(
                    external_ref=external_ref,
                    defaults=defaults,
                )
                if not created:
                    # 复用既有批次：刷新批次元信息（raw_row 无损覆盖为最新，REL-01）。
                    batch.source = source
                    batch.name = defaults["name"]
                    batch.released_at = defaults["released_at"]
                    batch.raw_row = batch_meta
                    batch.save(
                        update_fields=[
                            "source",
                            "name",
                            "released_at",
                            "raw_row",
                            "updated_at",
                        ]
                    )
                return batch
            # 空 external_ref 无去重依据 → 直接 create（条件唯一约束豁免空键）。
            return ReleaseBatch.objects.create(external_ref="", **defaults)

    @sync_to_async
    def _upsert_record(
        self,
        *,
        batch: ReleaseBatch,
        raw_row: dict[str, Any],
        source: str,
        record_key: str | None = None,
    ) -> ReleaseRecord:
        """单锁原子：按 ``bitable_record_key`` 幂等 upsert ReleaseRecord（raw_row 无损覆盖）。

        非空 key → ``select_for_update().get_or_create`` 收敛同行（条件唯一约束防并发
        重复）；空 key（无法定位的行）→ 直接 create（豁免唯一，允许多行共存）。已存在
        时 ``raw_row`` 始终覆盖为传入原始行（不丢数据），并刷新占位映射字段。
        """
        # 自然键契约：消费预组装成品 key（不在此重新拼接 app_token/table_id/record_id）。
        key = record_key if record_key is not None else raw_row.get("bitable_record_key", "")

        work_item, external_id = self._resolve_work_item(raw_row)
        # TODO(REL-03): status/note 的真实 Bitable 业务列映射待开放平台凭证 + 列样例（当前占位取顶层同名键）。
        mirror = {
            "raw_row": raw_row,
            "work_item": work_item,
            "work_item_external_id": external_id,
            "status": raw_row.get("status", ""),
            "note": raw_row.get("note", ""),
            "release_date": self._coerce_release_date(raw_row.get("release_date")),
        }

        with transaction.atomic():
            if key:
                record, created = ReleaseRecord.objects.select_for_update().get_or_create(
                    bitable_record_key=key,
                    defaults={"batch": batch, **mirror},
                )
                if not created:
                    # 已存在：raw_row 始终覆盖为最新原始行（REL-01 无损）+ 刷新占位映射。
                    record.raw_row = mirror["raw_row"]
                    record.work_item = work_item
                    record.work_item_external_id = external_id
                    record.status = mirror["status"]
                    record.note = mirror["note"]
                    record.release_date = mirror["release_date"]
                    record.save(
                        update_fields=[
                            "raw_row",
                            "work_item",
                            "work_item_external_id",
                            "status",
                            "note",
                            "release_date",
                            "updated_at",
                        ]
                    )
            else:
                # 空 key 行无去重依据 → 按 batch 内新建（条件唯一约束豁免空键）。
                record = ReleaseRecord.objects.create(
                    batch=batch, bitable_record_key="", **mirror
                )

        return record

    @staticmethod
    def _coerce_release_date(value: Any) -> int | None:
        """``release_date`` 容错为 ms epoch 整数；非数字 → None（不丢整行）。"""
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value)
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

    def _resolve_work_item(
        self, raw_row: dict[str, Any]
    ) -> tuple[WorkItem | None, int | None]:
        """经 ``work_item_external_id`` 反查已落库 WorkItem（命中连 FK，未命中留占位，不抛）。

        本 phase 占位反查按 ``WorkItem.work_item_id``（非三元组自然键）；命中多条取首条
        + warning（T-31-05 accept，真实粒度定型留 REL-03）。
        """
        # TODO(REL-03): work_item 反查的真实 Bitable 列映射 / 三元组粒度待开放平台凭证。
        external_id = raw_row.get("work_item_external_id")
        if external_id is None:
            return None, None

        # 占位反查对非整型容错：脏值（字符串/dict 等）只丢弃 work_item 占位，绝不丢整行
        # ——raw_row 仍无损落库 + work_item=None（REL-01 无损意图，WR-03）。
        try:
            external_id = int(external_id)
        except (TypeError, ValueError):
            logger.info(
                "release_record_workitem_external_id_invalid",
                value=str(external_id),
            )
            return None, None

        matches = list(WorkItem.objects.filter(work_item_id=external_id)[:2])
        if not matches:
            logger.info(
                "release_record_workitem_placeholder",
                work_item_external_id=external_id,
            )
            return None, external_id

        if len(matches) > 1:
            logger.warning(
                "release_record_workitem_multimatch",
                work_item_external_id=external_id,
            )
        logger.info(
            "release_record_workitem_linked",
            work_item_external_id=external_id,
            work_item_id=str(matches[0].id),
        )
        return matches[0], external_id

    @sync_to_async
    def _create_artifact(
        self,
        *,
        release_record: ReleaseRecord,
        artifact_type: str,
        ref: str,
        payload: dict[str, Any],
    ) -> ReleaseArtifact:
        """建一条 ReleaseArtifact（上线证据，经 service 收口）。"""
        with transaction.atomic():
            return ReleaseArtifact.objects.create(
                release_record=release_record,
                artifact_type=artifact_type,
                ref=ref,
                payload=payload,
            )
