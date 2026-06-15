"""BitableReleaseAdapter 守护测试（Phase 31-03 Task 3，REL-02）。

覆盖 adapter 骨架职责：

- raw_row 无损 + natural key：注入 fake client（list_records 返回 2 条带 record_id 的
  record）+ 真实 ReleaseService → ``ingest_from_table`` 落库；断言 ReleaseRecord.raw_row
  含原始 record 全量、``bitable_record_key == "{app_token}:{table_id}:{record_id}"``。
- 经 service 落库：断言落库后 DB 有 ReleaseBatch + 对应 ReleaseRecord（经 ReleaseService，
  非旁路）。
- 降级：``create_bitable_client_for_project`` 抛 ValueError → ``ingest_from_table`` 返回
  None、不抛、DB 无新增 batch。

注入式 fake BitableClient 避免触网（pytest-socket 不报 SocketBlockedError）；异步 +
sync_to_async 跨线程写库 → ``transaction=True``。
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from delivery.models import ReleaseBatch, ReleaseRecord
from delivery.services import BitableReleaseAdapter
from services.feishu_doc import FeishuDocAPIError

pytestmark = pytest.mark.django_db(transaction=True)

APP_TOKEN = "bascnAppTokenXYZ"
TABLE_ID = "tblTableId123"


def _make_token_error() -> FeishuDocAPIError:
    """构造 token 取失败异常（list_records 内委托 FeishuDocClient 取 token 时可抛）。"""
    return FeishuDocAPIError("获取 tenant_access_token 失败")


class _FakeBitableClient:
    """注入式 fake client：list_records 返回固定 fixture（不触网）。"""

    def __init__(self, records: list[dict[str, Any]]):
        self._records = records

    async def list_records(
        self, app_token: str, table_id: str, **kwargs: Any
    ) -> dict[str, Any]:
        return {"items": self._records, "has_more": False, "page_token": ""}


class _RaisingBitableClient:
    """注入式 fake client：list_records 抛指定异常（验证 adapter 降级不崩，WR-01）。"""

    def __init__(self, exc: Exception):
        self._exc = exc

    async def list_records(
        self, app_token: str, table_id: str, **kwargs: Any
    ) -> dict[str, Any]:
        raise self._exc


async def test_ingest_preserves_raw_row_and_natural_key() -> None:
    """raw_row 无损 + natural key 正确 + 经 ReleaseService 落库。"""
    records = [
        {"record_id": "rec1", "fields": {"status": "released"}},
        {"record_id": "rec2", "fields": {"note": "hotfix"}},
    ]
    adapter = BitableReleaseAdapter(client=_FakeBitableClient(records))

    batch = await adapter.ingest_from_table(
        project=None, app_token=APP_TOKEN, table_id=TABLE_ID
    )

    # 经 service 落库：DB 有 1 个 ReleaseBatch + 2 条 ReleaseRecord。
    assert batch is not None
    assert await ReleaseBatch.objects.acount() == 1
    assert await ReleaseRecord.objects.filter(batch=batch).acount() == 2

    rec1_key = f"{APP_TOKEN}:{TABLE_ID}:rec1"
    record = await ReleaseRecord.objects.aget(bitable_record_key=rec1_key)
    # natural key {app_token}:{table_id}:{record_id} 标识正确。
    assert record.bitable_record_key == rec1_key
    # raw_row 保留原始 Bitable record 全量（REL-01 无损）。
    assert record.raw_row["record"] == records[0]
    # 占位列映射从 fields 顶层同名键取值。
    assert record.status == "released"


@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(_make_token_error(), id="token-fetch-FeishuDocAPIError"),
        pytest.param(httpx.ConnectError("network down"), id="httpx-network-error"),
        pytest.param(ValueError("Expecting value"), id="non-json-JSONDecodeError"),
    ],
)
async def test_list_records_failure_degrades_to_none(exc: Exception) -> None:
    """token / 网络 / 非 JSON 失败 → ingest_from_table 返回 None、不抛、DB 无新增（WR-01）。"""
    adapter = BitableReleaseAdapter(client=_RaisingBitableClient(exc))

    result = await adapter.ingest_from_table(
        project=None, app_token=APP_TOKEN, table_id=TABLE_ID
    )

    assert result is None
    assert await ReleaseBatch.objects.acount() == 0


async def test_no_credentials_graceful_degradation(monkeypatch: Any) -> None:
    """无凭证（create_bitable_client_for_project 抛 ValueError）→ 返回 None、不抛、DB 无新增。"""

    async def _raise(project: Any) -> Any:
        raise ValueError("项目未配置飞书开放平台应用凭证")

    import delivery.services.bitable_release_adapter as adapter_mod

    monkeypatch.setattr(adapter_mod, "create_bitable_client_for_project", _raise)

    # client=None → 走 create_bitable_client_for_project（被 monkeypatch 成抛 ValueError）。
    adapter = BitableReleaseAdapter()

    result = await adapter.ingest_from_table(
        project=object(), app_token=APP_TOKEN, table_id=TABLE_ID
    )

    # 降级：返回 None、不抛、DB 无新增 batch。
    assert result is None
    assert await ReleaseBatch.objects.acount() == 0
