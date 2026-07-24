"""CommentEventService 服务守护测试（Phase 29-02 Task 1）。

覆盖 CMT-01 与 T-29-03/05/06：
- ``classify_approval_semantic`` 纯函数：approve / reject / none 三类 + reject 优先 + 空输入。
- ``append_events`` 单一写入入口：event_type 推导、幂等去重锚（同批两次新建数为 0）。
- ``ingest_comments`` 拉取路径：回源失败 → comments facet=missing/error 不抛不回滚；
  缺 project / 缺 canonical work_item → 降配 + warning；成功 → facet=complete。
- ``append_webhook_comment``：缺 work_item 跳过返回 0。

回源经 ``respx`` mock（先 token 端点后业务端点），pytest-socket 隔离不发真实网络。
"""

from __future__ import annotations

import httpx
import pytest
import respx

from delivery.services import classify_approval_semantic

# 回源 / append 测试经 sync_to_async 异步 ORM 写库——须 transaction=True
# （与 test_work_item_service.py 同款：跨线程连接写入需真实 flush 清理）。
pytestmark = pytest.mark.django_db(transaction=True)

PROJECT_KEY = "000000000000000000000001"
API_BASE = "https://project.feishu.cn"
STORY_ID = 1000000002


# ============================================================================
# classify_approval_semantic（纯函数，无 DB / 无网络）
# ============================================================================


@pytest.mark.parametrize(
    "text",
    ["通过", "批准上线", "approved", "LGTM", "ok 没问题", "\U0001f44d"],
)
def test_classify_approve(text: str) -> None:
    """approval 关键词命中 → approve。"""
    assert classify_approval_semantic(text) == "approve"


@pytest.mark.parametrize(
    "text",
    ["驳回", "拒绝该方案", "rejected", "需要修改", "不通过", "\U0001f44e"],
)
def test_classify_reject(text: str) -> None:
    """rejection 关键词命中 → reject。"""
    assert classify_approval_semantic(text) == "reject"


def test_classify_none() -> None:
    """无关键词 / 空 / None → none。"""
    assert classify_approval_semantic("随便聊两句") == "none"
    assert classify_approval_semantic("") == "none"
    assert classify_approval_semantic(None) == "none"


def test_classify_reject_precedence() -> None:
    """同时命中 approve + reject → reject 优先（最保守）。"""
    assert classify_approval_semantic("整体通过，但这里不通过") == "reject"
    assert classify_approval_semantic("lgtm 但需要修改") == "reject"


# ============================================================================
# 共用 fixture：Space + WorkItem + respx mock
# ============================================================================


async def _make_project():
    from common.encryption import encrypt_value
    from projects.models import Space

    return await Space.objects.acreate(
        name="example_platform",
        feishu_project_key=PROJECT_KEY,
        feishu_plugin_id="plugin_test_id",
        feishu_plugin_secret_encrypted=encrypt_value("plugin_test_secret"),
        feishu_user_key="user_key_test",
    )


async def _make_work_item(work_item_type: str = "story", work_item_id: int = STORY_ID):
    from delivery.models import WorkItem, WorkItemOrigin

    return await WorkItem.objects.acreate(
        feishu_project_key=PROJECT_KEY,
        work_item_type=work_item_type,
        work_item_id=work_item_id,
        origin=WorkItemOrigin.MANUAL,
        title="评论宿主工作项",
    )


def _identity(work_item_type: str = "story", work_item_id: int = STORY_ID):
    from delivery.services import WorkItemIdentity

    return WorkItemIdentity(
        feishu_project_key=PROJECT_KEY,
        work_item_type=work_item_type,
        work_item_id=work_item_id,
    )


def _mock_token() -> None:
    respx.post(f"{API_BASE}/open_api/authen/plugin_token").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {"token": "plugin_token_xyz", "expire_time": 7200},
                "error": {"code": 0, "msg": "success"},
            },
        )
    )


def _comment_list_url() -> str:
    return f"{API_BASE}/open_api/{PROJECT_KEY}/work_item/story/{STORY_ID}/comment/list"


def _mock_comments(comments: list[dict]) -> None:
    """mock comment/list 端点返回飞书形状（{data:{comments:[...]}}）。"""
    respx.get(_comment_list_url()).mock(
        return_value=httpx.Response(
            200,
            json={"err_code": 0, "data": {"comments": comments}},
        )
    )


def _raw_comment(
    cid: str,
    content: str,
    *,
    created_at: int = 1700000000000,
    author: str = "u1",
    parent_id: str = "",
) -> dict:
    """飞书 comment/list item 原始形状（parse_comments 输入）。"""
    return {
        "id": cid,
        "content": content,
        "created_at": created_at,
        "author": {"name": author},
        "parent_id": parent_id,
    }


# ============================================================================
# append_events：event_type 推导 + 幂等去重
# ============================================================================


async def test_append_events_event_type_derivation() -> None:
    """event_type 推导：无父 → created、有父 → replied、approval 关键词 → approval。"""
    from delivery.models import ApprovalSemantic, CommentEventType, WorkItemCommentEvent
    from delivery.services import CommentEventService

    work_item = await _make_work_item()
    comments = [
        {
            "id": "c1",
            "content": "根评论",
            "created_at": 1700000000000,
            "author": "u1",
            "thread_parent_id": "",
        },
        {
            "id": "c2",
            "content": "回复一下",
            "created_at": 1700000100000,
            "author": "u2",
            "thread_parent_id": "c1",
        },
        {
            "id": "c3",
            "content": "通过",
            "created_at": 1700000200000,
            "author": "u3",
            "thread_parent_id": "",
        },
    ]
    created = await CommentEventService().append_events(work_item, comments, "manual")
    assert created == 3

    by_id = {
        e.feishu_comment_id: e
        async for e in WorkItemCommentEvent.objects.filter(work_item=work_item)
    }
    assert by_id["c1"].event_type == CommentEventType.CREATED
    assert by_id["c2"].event_type == CommentEventType.REPLIED
    assert by_id["c2"].thread_parent_id == "c1"
    assert by_id["c3"].event_type == CommentEventType.APPROVAL
    assert by_id["c3"].approval_semantic == ApprovalSemantic.APPROVE


async def test_append_events_idempotent_dedup() -> None:
    """T-29-03：同一批 comments 调两次，第二次新建数为 0（去重锚生效）。"""
    from delivery.models import WorkItemCommentEvent
    from delivery.services import CommentEventService

    work_item = await _make_work_item()
    comments = [
        {
            "id": "c1",
            "content": "根评论",
            "created_at": 1700000000000,
            "author": "u1",
            "thread_parent_id": "",
        },
        {
            "id": "c2",
            "content": "驳回",
            "created_at": 1700000100000,
            "author": "u2",
            "thread_parent_id": "",
        },
    ]
    service = CommentEventService()
    first = await service.append_events(work_item, comments, "manual")
    second = await service.append_events(work_item, comments, "manual")

    assert first == 2
    assert second == 0  # 幂等可重入
    assert await WorkItemCommentEvent.objects.filter(work_item=work_item).acount() == 2


async def test_comment_event_unique_anchor_constraint() -> None:
    """WR-02：去重锚 DB 级唯一约束生效——同锚（含非空 event_time）重复直插抛 IntegrityError。

    绕过 ``get_or_create`` 直接 acreate 两条同锚行，验证
    ``uniq_comment_event_anchor`` 在 DB 层兜底（NULL 互不相等，故用非空 event_time）。
    """
    from django.db import IntegrityError
    from django.utils import timezone

    from delivery.models import CommentEventType, WorkItemCommentEvent

    work_item = await _make_work_item()
    anchor = {
        "work_item": work_item,
        "feishu_comment_id": "dup1",
        "event_type": CommentEventType.CREATED,
        "event_time": timezone.now(),  # 非空：NULL 在唯一约束下互不相等
    }
    await WorkItemCommentEvent.objects.acreate(**anchor)
    with pytest.raises(IntegrityError):
        await WorkItemCommentEvent.objects.acreate(**anchor)


async def test_append_events_graceful_when_anchor_preexists() -> None:
    """WR-02：同锚行已存在时 append_events 视作"已追加"——created=0、不重复、不崩溃。"""
    from datetime import UTC, datetime

    from delivery.models import CommentEventType, WorkItemCommentEvent
    from delivery.services import CommentEventService

    work_item = await _make_work_item()
    # 由毫秒值构造 event_time，确保与 append 路径的毫秒解析往返一致（避免锚漂移）
    ms = 1700000000000
    event_time = datetime.fromtimestamp(ms / 1000, tz=UTC)
    # 预置一条同锚行（模拟另一路径已落库）
    await WorkItemCommentEvent.objects.acreate(
        work_item=work_item,
        feishu_comment_id="c1",
        event_type=CommentEventType.CREATED,
        event_time=event_time,
    )
    created = await CommentEventService().append_events(
        work_item,
        [{"id": "c1", "content": "根评论", "created_at": ms, "thread_parent_id": ""}],
        "manual",
    )
    assert created == 0  # 命中既有锚，不重复
    assert await WorkItemCommentEvent.objects.filter(work_item=work_item).acount() == 1


async def test_append_events_skips_missing_id() -> None:
    """缺 feishu_comment_id → 跳过（无去重锚，不构造无锚事件）。"""
    from delivery.models import WorkItemCommentEvent
    from delivery.services import CommentEventService

    work_item = await _make_work_item()
    comments = [
        {"id": None, "content": "无 id", "created_at": 1700000000000, "author": "u1"},
        {"id": "c1", "content": "有 id", "created_at": 1700000100000, "author": "u1"},
    ]
    created = await CommentEventService().append_events(work_item, comments, "manual")
    assert created == 1
    assert await WorkItemCommentEvent.objects.filter(work_item=work_item).acount() == 1


async def test_append_events_reject_semantic_recorded() -> None:
    """approval 事件 approval_semantic 同步置 reject。"""
    from delivery.models import ApprovalSemantic, CommentEventType, WorkItemCommentEvent
    from delivery.services import CommentEventService

    work_item = await _make_work_item()
    created = await CommentEventService().append_events(
        work_item,
        [
            {
                "id": "c1",
                "content": "不通过",
                "created_at": 1700000000000,
                "author": "u1",
                "thread_parent_id": "",
            }
        ],
        "manual",
    )
    assert created == 1
    event = await WorkItemCommentEvent.objects.aget(work_item=work_item)
    assert event.event_type == CommentEventType.APPROVAL
    assert event.approval_semantic == ApprovalSemantic.REJECT


# ============================================================================
# ingest_comments：拉取路径 + 降配
# ============================================================================


@respx.mock
async def test_ingest_comments_success_complete_facet() -> None:
    """成功拉取 → append + comments facet=complete。"""
    from delivery.models import SyncFacet, SyncStatus, WorkItemCommentEvent, WorkItemSyncState
    from delivery.services import CommentEventService

    await _make_project()
    work_item = await _make_work_item()
    _mock_token()
    _mock_comments(
        [
            _raw_comment("c1", "根评论"),
            _raw_comment("c2", "回复", parent_id="c1"),
        ]
    )

    result = await CommentEventService().ingest_comments(_identity(), "manual")

    assert result["status"] == "complete"
    assert result["appended"] == 2
    assert await WorkItemCommentEvent.objects.filter(work_item=work_item).acount() == 2
    state = await WorkItemSyncState.objects.aget(work_item=work_item, facet=SyncFacet.COMMENTS)
    assert state.status == SyncStatus.COMPLETE
    assert state.last_synced_at is not None


@respx.mock
async def test_ingest_comments_empty_is_complete() -> None:
    """拉取空列表也算 complete（不假装 missing）。"""
    from delivery.models import SyncFacet, SyncStatus, WorkItemSyncState
    from delivery.services import CommentEventService

    await _make_project()
    work_item = await _make_work_item()
    _mock_token()
    _mock_comments([])

    result = await CommentEventService().ingest_comments(_identity(), "manual")

    assert result["status"] == "complete"
    assert result["appended"] == 0
    state = await WorkItemSyncState.objects.aget(work_item=work_item, facet=SyncFacet.COMMENTS)
    assert state.status == SyncStatus.COMPLETE


@respx.mock
async def test_ingest_comments_fetch_failure_facet_missing_no_rollback() -> None:
    """T-29-06：回源异常 → comments facet=missing/error，不抛、WorkItem 行保留。"""
    from delivery.models import SyncFacet, SyncStatus, WorkItem, WorkItemSyncState
    from delivery.services import CommentEventService

    await _make_project()
    work_item = await _make_work_item()
    _mock_token()
    # comment/list 抛连接异常 → get_comments 向上传播 → ingest 降配
    respx.get(_comment_list_url()).mock(side_effect=httpx.ConnectError("boom"))

    result = await CommentEventService().ingest_comments(_identity(), "manual")

    assert result["status"] == "error"
    # WorkItem 行仍存在（不回滚）
    assert await WorkItem.objects.filter(work_item_id=STORY_ID).aexists()
    state = await WorkItemSyncState.objects.aget(work_item=work_item, facet=SyncFacet.COMMENTS)
    assert state.status == SyncStatus.MISSING
    assert state.error  # error 文本非空
    assert "plugin_token_xyz" not in state.error
    assert "plugin_test_secret" not in state.error


async def test_ingest_comments_project_unconfigured_degrades() -> None:
    """缺 project → comments facet=missing + error=project_unconfigured，不抛。"""
    from delivery.models import SyncFacet, SyncStatus, WorkItemSyncState
    from delivery.services import CommentEventService

    # 不建 Space，但建 work_item（便于记 facet）
    work_item = await _make_work_item()

    result = await CommentEventService().ingest_comments(_identity(), "manual")

    assert result["status"] == "missing"
    assert result["reason"] == "project_unconfigured"
    state = await WorkItemSyncState.objects.aget(work_item=work_item, facet=SyncFacet.COMMENTS)
    assert state.status == SyncStatus.MISSING
    assert "project" in state.error


@respx.mock
async def test_ingest_comments_missing_work_item_skips_append() -> None:
    """缺 canonical work_item → 跳过 append + warning，不抛、不建 WorkItem。"""
    from delivery.models import WorkItem
    from delivery.services import CommentEventService

    await _make_project()  # 有 project，但不建 work_item
    _mock_token()
    _mock_comments([_raw_comment("c1", "根评论")])

    result = await CommentEventService().ingest_comments(_identity(), "manual")

    assert result["status"] == "missing"
    assert result["reason"] == "work_item_missing"
    assert not await WorkItem.objects.filter(work_item_id=STORY_ID).aexists()


# ============================================================================
# append_webhook_comment：单条归一 + 缺 work_item 跳过
# ============================================================================


async def test_append_webhook_comment_appends() -> None:
    """webhook 单条评论归一后经 append_events 落库（approval 关键词 → approval 事件）。"""
    from delivery.models import ApprovalSemantic, CommentEventType, WorkItemCommentEvent
    from delivery.services import CommentEventService

    work_item = await _make_work_item()
    appended = await CommentEventService().append_webhook_comment(
        _identity(),
        comment_id="wc1",
        body="批准",
        author="reviewer",
        created_at=1700000000000,
        source="feishu_webhook",
    )
    assert appended == 1
    event = await WorkItemCommentEvent.objects.aget(work_item=work_item)
    assert event.feishu_comment_id == "wc1"
    assert event.event_type == CommentEventType.APPROVAL
    assert event.approval_semantic == ApprovalSemantic.APPROVE


async def test_append_webhook_comment_missing_work_item_returns_zero() -> None:
    """缺 canonical work_item → 跳过返回 0（不创建 WorkItem）。"""
    from delivery.models import WorkItem
    from delivery.services import CommentEventService

    appended = await CommentEventService().append_webhook_comment(
        _identity(),
        comment_id="wc1",
        body="通过",
        source="feishu_webhook",
    )
    assert appended == 0
    assert not await WorkItem.objects.filter(work_item_id=STORY_ID).aexists()
