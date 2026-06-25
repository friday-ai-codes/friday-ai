"""BitableReleaseAdapter —— Bitable 原始行 → Release 账本（经 ReleaseService 落库，REL-02）。

把飞书 Bitable 记录经**占位映射**落到 Release 宽容模型：

- **经 ``ReleaseService.ingest_batch`` 落库**（不旁路写 Release 表，守 INV-6；
  ``test_release_inv6_guard.py`` grep 守护覆盖本文件）。
- **保留 raw_row**：每条映射行原样保留 Bitable record 全量（adapter 演进 / 列映射
  变化不丢数据，REL-01）。
- **自然键契约**：adapter 经 ``build_bitable_record_key(app_token, table_id, record_id)``
  预组装 ``bitable_record_key`` 写进每行（natural key 唯一拼接点收口在此，ReleaseService
  只消费成品 key，避免拼接逻辑漂移）。
- **降级不崩**：无开放平台凭证（``create_bitable_client_for_project`` 抛 ValueError）或
  Bitable API 失败 → warning + 返回 None（不抛致调用方崩溃，对齐 doc tools 降级范式 +
  CONTEXT 范围守护）。

本 plan 是**骨架**：业务列 → 字段只建占位映射（natural key + raw_row 必填，业务列映射
``TODO(REL-03)``）；真实多维表格列结构映射 / 真实数据全量入库归 v2 REL-03。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import structlog

from delivery.models import ReleaseSource, build_bitable_record_key
from delivery.services.release_service import ReleaseService
from services.feishu_bitable import (
    BitableAPIError,
    BitableClient,
    create_bitable_client_for_project,
)
from services.feishu_doc import FeishuDocAPIError

if TYPE_CHECKING:
    from delivery.models import ReleaseBatch
    from projects.models import Space

logger = structlog.get_logger(__name__)

__all__ = ["BitableReleaseAdapter"]


class BitableReleaseAdapter:
    """Bitable 行 → ReleaseService 落库的骨架 adapter（REL-02）。"""

    def __init__(
        self,
        *,
        client: BitableClient | None = None,
        service: ReleaseService | None = None,
    ):
        """依赖可注入（便于测试），缺省内部构造。

        Args:
            client: 预构造 ``BitableClient``（缺省时按 project 凭证现解析、无凭证降级）。
            service: Release 写入入口（缺省内部构造，落库仍经 service 收口，守 INV-6）。
        """
        self._client = client
        self._service = service or ReleaseService()

    async def ingest_from_table(
        self,
        *,
        project: Space,
        app_token: str,
        table_id: str,
        source: str = ReleaseSource.BITABLE,
    ) -> ReleaseBatch | None:
        """读 Bitable 表 → 经 ReleaseService 落一个 ReleaseBatch（骨架 + 降级）。

        流程：解析凭证 / 建 client（无凭证降级 None）→ ``list_records`` 取记录（首页骨架，
        真实分页遍历留 REL-03）→ 每条经占位映射 ``_map_record`` 成 raw_row（含预组装
        ``bitable_record_key`` + 原始 record 全量保留）→ ``ReleaseService.ingest_batch``
        落库。

        Args:
            project: 解析开放平台凭证用的 Space（注入 client 时可不依赖）。
            app_token: Bitable app token。
            table_id: 数据表 id。
            source: ``ReleaseSource`` 值（默认 bitable）。

        Returns:
            落库后的 ``ReleaseBatch``；无凭证 / API 失败降级时返回 None（不抛）。
        """
        log = logger.bind(app_token=app_token, table_id=table_id)

        client = self._client
        if client is None:
            try:
                client = await create_bitable_client_for_project(project)
            except ValueError as exc:
                # 无开放平台凭证：骨架降级不崩（对齐 doc tools / CONTEXT 范围守护）。
                log.warning("bitable_credentials_missing", error=str(exc))
                return None

        try:
            data = await client.list_records(app_token, table_id)
        except (BitableAPIError, FeishuDocAPIError, httpx.HTTPError, ValueError) as exc:
            # 外部失败统一降级不崩（对齐 doc tools / CONTEXT 范围守护）：
            # - BitableAPIError：list_records 业务错误码 / 频控；
            # - FeishuDocAPIError：token 取失败（list_records 内委托 FeishuDocClient 取 token）；
            # - httpx.HTTPError：开放平台网络抖动（ConnectError/TimeoutException 等）；
            # - ValueError：非 JSON HTTP 响应触发 response.json() 的 JSONDecodeError（其父类）。
            # 只兜外部失败异常面，不过度吞编程错误（如 KeyError/AttributeError 仍冒泡暴露）。
            log.warning("bitable_list_records_failed", error=str(exc))
            return None

        records = data.get("items", []) if isinstance(data, dict) else []
        mapped_rows = [
            self._map_record(app_token, table_id, record) for record in records
        ]

        # 经 ReleaseService 收口落库（不旁路写 Release 表，守 INV-6）。
        # external_ref 取 {app_token}:{table_id} 作 batch 稳定自然键：重复摄取同一张表
        # 收敛回同一 ReleaseBatch（幂等，不累积空批次，WR-02）。
        batch = await self._service.ingest_batch(
            raw_rows=mapped_rows,
            source=source,
            batch_meta={
                "app_token": app_token,
                "table_id": table_id,
                "external_ref": f"{app_token}:{table_id}",
            },
        )
        log.info(
            "bitable_ingested",
            record_count=len(mapped_rows),
            batch_id=str(batch.id),
        )
        return batch

    def _map_record(
        self, app_token: str, table_id: str, record: dict[str, Any]
    ) -> dict[str, Any]:
        """Bitable record → raw_row（占位映射，保留原始 record 全量 + 预组装 natural key）。

        natural key 经 ``build_bitable_record_key`` 唯一构造（不在此重复拼接 app_token /
        table_id / record_id）；业务列 → 字段只建占位（从 record ``fields`` 顶层同名键
        尝试取，取不到留空 / None）。
        """
        record_id = record.get("record_id", "") if isinstance(record, dict) else ""
        fields = record.get("fields", {}) if isinstance(record, dict) else {}
        if not isinstance(fields, dict):
            fields = {}

        # natural key 收口经 build_bitable_record_key（自然键契约的唯一拼接点）。
        record_key = build_bitable_record_key(app_token, table_id, record_id)

        # raw_row 原样保留 Bitable record 全量（REL-01 无损）+ 顶层占位映射供 ReleaseService 消费。
        return {
            "bitable_record_key": record_key,
            "record": record,
            # TODO(REL-03): 真实业务列映射待列头/样例；当前从 fields 顶层同名键占位取值。
            "status": fields.get("status", ""),
            "note": fields.get("note", ""),
            "work_item_external_id": fields.get("work_item_external_id"),
        }
