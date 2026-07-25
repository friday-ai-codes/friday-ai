"""评论 webhook 接线测试（Phase 29-03 Task 1）。

- webhook 评论 handler 在保留既有 approval 处理（FeishuApprovalHandler）+ knowledge
  投影（INV-3）的同时，经 run_in_background 后台调 CommentEventService.append_webhook_comment
  (source="feishu_webhook")。
- approval 语义复用单一判定来源 classify_approval_semantic（关键词不在两处漂移）。
- 三元组不全（缺 work_item_type_key / work_item_id / comment）→ 跳过后台 append，不抛、不调度。

handler 接线测试用 SimpleNamespace project + mock，不触 DB / 网络。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

PROJECT_KEY = "000000000000000000000001"
STORY_ID = 1000000002


def _make_view():
    from feishu.views import FeishuWebhookView

    return FeishuWebhookView()


async def test_comment_handler_wires_background_append() -> None:
    """评论 handler：携完整三元组 → 后台经 append_webhook_comment 投递（source=feishu_webhook）。"""
    from delivery.services import CommentEventService

    view = _make_view()
    project = SimpleNamespace(feishu_project_key=PROJECT_KEY)
    payload = {
        "id": STORY_ID,
        "work_item_type_key": "story",
        "comment": "看起来不错，继续",
        "comment_id": "cmt_123",
        "operator_id": "user_abc",
        "create_time": 1700000000000,
        "reply_comment_id": "",
    }

    captured: dict = {}

    def _fake_rib(factory, *, name=None, initiated_by_user_id=None):
        captured["factory"] = factory
        captured["name"] = name
        captured["initiated_by_user_id"] = initiated_by_user_id
        return MagicMock()

    with patch("services.background_runner.run_in_background", new=_fake_rib):
        await view._handle_workitem_comment(project, payload, MagicMock())

    # 后台 append 已投递
    assert "factory" in captured
    assert captured["name"].startswith(f"comment-append:{PROJECT_KEY}:story:{STORY_ID}")
    # CTX-02：webhook 无真实触发用户，后台任务必须显式归因到 system，否则日志失去可归因性
    assert captured["initiated_by_user_id"] == "system"

    # 执行后台 factory，断言以 source="feishu_webhook" 调 append_webhook_comment
    with patch.object(
        CommentEventService, "append_webhook_comment", new=AsyncMock(return_value=1)
    ) as mock_append:
        await captured["factory"]()
    mock_append.assert_awaited_once()
    identity_arg = mock_append.await_args.args[0]
    assert identity_arg.feishu_project_key == PROJECT_KEY
    assert identity_arg.work_item_type == "story"
    assert identity_arg.work_item_id == STORY_ID
    kwargs = mock_append.await_args.kwargs
    assert kwargs["comment_id"] == "cmt_123"
    assert kwargs["body"] == "看起来不错，继续"
    assert kwargs["author"] == "user_abc"
    assert kwargs["created_at"] == 1700000000000
    assert kwargs["source"] == "feishu_webhook"


async def test_comment_handler_extracts_comment_id_from_alternate_key() -> None:
    """WR-01：评论 id 在备选候选键（comment_id_str）下仍被取到并投递（非硬编码单键）。"""
    from delivery.services import CommentEventService

    view = _make_view()
    project = SimpleNamespace(feishu_project_key=PROJECT_KEY)
    # 无 comment_id，但提供备选键 comment_id_str
    payload = {
        "id": STORY_ID,
        "work_item_type_key": "story",
        "comment": "换个字段名也要能取到",
        "comment_id_str": "cmt_alt_456",
    }

    captured: dict = {}

    def _fake_rib(factory, *, name=None, initiated_by_user_id=None):
        captured["factory"] = factory
        captured["initiated_by_user_id"] = initiated_by_user_id
        return MagicMock()

    with patch("services.background_runner.run_in_background", new=_fake_rib):
        await view._handle_workitem_comment(project, payload, MagicMock())

    assert "factory" in captured
    assert captured["initiated_by_user_id"] == "system"
    with patch.object(
        CommentEventService, "append_webhook_comment", new=AsyncMock(return_value=1)
    ) as mock_append:
        await captured["factory"]()
    mock_append.assert_awaited_once()
    assert mock_append.await_args.kwargs["comment_id"] == "cmt_alt_456"


async def test_comment_handler_missing_comment_id_warns_but_still_delivers() -> None:
    """WR-01：所有候选键均缺 → comment_id="" + 显式 warning，但仍投递（service 侧跳过），不崩溃。"""
    from delivery.services import CommentEventService

    view = _make_view()
    project = SimpleNamespace(feishu_project_key=PROJECT_KEY)
    payload = {
        "id": STORY_ID,
        "work_item_type_key": "story",
        "comment": "无任何评论 id 字段",
    }

    captured: dict = {}

    def _fake_rib(factory, *, name=None, initiated_by_user_id=None):
        captured["factory"] = factory
        captured["initiated_by_user_id"] = initiated_by_user_id
        return MagicMock()

    with (
        patch("services.background_runner.run_in_background", new=_fake_rib),
        patch("feishu.views.logger.warning") as mock_warn,
    ):
        await view._handle_workitem_comment(project, payload, MagicMock())

    # 顶层 id 是 work_item_id，不得被误当评论 id
    with patch.object(
        CommentEventService, "append_webhook_comment", new=AsyncMock(return_value=0)
    ) as mock_append:
        await captured["factory"]()
    assert mock_append.await_args.kwargs["comment_id"] == ""
    warn_events = [c.args[0] for c in mock_warn.call_args_list if c.args]
    assert "comment_append_missing_comment_id" in warn_events


async def test_comment_handler_preserves_approval_via_single_source() -> None:
    """approval 评论：复用 classify_approval_semantic → 既有 FeishuApprovalHandler 仍被调（零回归）。"""
    view = _make_view()
    project = SimpleNamespace(feishu_project_key=PROJECT_KEY)
    payload = {
        "id": STORY_ID,
        "work_item_type_key": "story",
        "comment": "通过，lgtm",
        "comment_id": "cmt_approve",
    }

    handler_instance = MagicMock()
    handler_instance.on_approval_comment = AsyncMock(return_value=True)

    with (
        patch("feishu.approval.FeishuApprovalHandler", return_value=handler_instance),
        patch("services.background_runner.run_in_background", new=MagicMock()),
    ):
        await view._handle_workitem_comment(project, payload, MagicMock())

    # 既有 approval handler 仍被调用（approved=True）
    handler_instance.on_approval_comment.assert_awaited_once()
    assert handler_instance.on_approval_comment.await_args.kwargs["approved"] is True


async def test_comment_handler_rejection_routes_approved_false() -> None:
    """rejection 评论：classify 取 reject → approved=False（与既有关键词行为一致）。"""
    view = _make_view()
    project = SimpleNamespace(feishu_project_key=PROJECT_KEY)
    payload = {
        "id": STORY_ID,
        "work_item_type_key": "story",
        "comment": "驳回，需要修改",
        "comment_id": "cmt_reject",
    }

    handler_instance = MagicMock()
    handler_instance.on_approval_comment = AsyncMock(return_value=True)

    with (
        patch("feishu.approval.FeishuApprovalHandler", return_value=handler_instance),
        patch("services.background_runner.run_in_background", new=MagicMock()),
    ):
        await view._handle_workitem_comment(project, payload, MagicMock())

    handler_instance.on_approval_comment.assert_awaited_once()
    assert handler_instance.on_approval_comment.await_args.kwargs["approved"] is False


def test_schedule_comment_append_skips_incomplete_identity() -> None:
    """三元组不全（缺 work_item_type / work_item_id / comment）→ 跳过后台 append，不调度。"""
    view = _make_view()
    project = SimpleNamespace(feishu_project_key=PROJECT_KEY)

    with patch("services.background_runner.run_in_background") as mock_rib:
        view._schedule_comment_append(project, {"id": STORY_ID, "comment": "hi"})  # 缺 type
        view._schedule_comment_append(
            project, {"work_item_type_key": "story", "comment": "hi"}
        )  # 缺 id
        view._schedule_comment_append(
            project, {"id": STORY_ID, "work_item_type_key": "story"}
        )  # 缺 comment

    mock_rib.assert_not_called()
