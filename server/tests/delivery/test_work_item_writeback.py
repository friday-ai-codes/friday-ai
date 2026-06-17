"""WorkItemService.awriteback_feishu_chat_id writeback 单一入口 DB 测（Phase 59-01）。

覆盖 D-6 / INV-6 / P-5：
- 命中：写回 feishu_chat_id 成功且不污染 mirror（title 未动）。
- 不存在：WorkItem 不存在返回 False 不抛、库中无该行。
- mirror 隔离：feishu_chat_id 绝不在 _MIRROR_FIELDS 白名单内。

writeback 经异步 ORM 写库——须用 transaction=True（跨线程连接写入）。
"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async

from delivery.models import WorkItem
from delivery.services.work_item_service import _MIRROR_FIELDS, WorkItemService

pytestmark = pytest.mark.django_db(transaction=True)

PROJECT_KEY = "P"
WORK_ITEM_TYPE = "story"
WORK_ITEM_ID = 123


@pytest.mark.asyncio
async def test_awriteback_feishu_chat_id_success_no_mirror_pollution():
    """命中三元组：写回 feishu_chat_id 成功且 title（mirror）未动。"""
    await sync_to_async(WorkItem.objects.create)(
        feishu_project_key=PROJECT_KEY,
        work_item_type=WORK_ITEM_TYPE,
        work_item_id=WORK_ITEM_ID,
        origin="manual",
        title="原标题",
    )

    ok = await WorkItemService().awriteback_feishu_chat_id(
        PROJECT_KEY, WORK_ITEM_TYPE, WORK_ITEM_ID, "oc_new"
    )
    assert ok is True

    reloaded = await sync_to_async(WorkItem.objects.get)(
        feishu_project_key=PROJECT_KEY,
        work_item_type=WORK_ITEM_TYPE,
        work_item_id=WORK_ITEM_ID,
    )
    assert reloaded.feishu_chat_id == "oc_new"
    # writeback 绝不污染 mirror（P-5）
    assert reloaded.title == "原标题"


@pytest.mark.asyncio
async def test_awriteback_feishu_chat_id_missing_returns_false():
    """WorkItem 不存在：返回 False 不抛、库中无该行。"""
    ok = await WorkItemService().awriteback_feishu_chat_id(
        PROJECT_KEY, WORK_ITEM_TYPE, 999, "oc_x"
    )
    assert ok is False

    exists = await sync_to_async(
        WorkItem.objects.filter(
            feishu_project_key=PROJECT_KEY,
            work_item_type=WORK_ITEM_TYPE,
            work_item_id=999,
        ).exists
    )()
    assert exists is False


def test_feishu_chat_id_not_in_mirror_fields():
    """mirror 隔离：feishu_chat_id 绝不在 _MIRROR_FIELDS 白名单内（P-5）。"""
    assert "feishu_chat_id" not in _MIRROR_FIELDS
