"""FetchGroupChatNode 和 JoinGroupChatNode 单元测试。

纯 mock 测试，不需要数据库。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.feishu_im import FeishuIMError
from workflows.nodes.base import ExecutionContext
from workflows.nodes.integrations.feishu_chat import (
    CreateGroupChatNode,
    FetchGroupChatNode,
    JoinGroupChatNode,
)


def _make_context(
    config: dict | None = None,
    input_data: dict | None = None,
    workflow_execution: object | None = None,
) -> ExecutionContext:
    """构建 mock ExecutionContext。"""
    ctx = ExecutionContext(
        execution_id="exec-001",
        node_id="node-001",
        node_config=config or {},
        input_data=input_data or {},
        workflow_context={},
        previous_outputs={},
        workflow_execution=workflow_execution,
    )
    return ctx


def _mock_im_service(
    get_chat_id_return: dict | None = None,
    ensure_bot_return: dict | None = None,
) -> AsyncMock:
    """构建 AsyncMock FeishuIMService。"""
    service = AsyncMock()
    service.get_chat_id_for_work_item = AsyncMock(return_value=get_chat_id_return)
    service.ensure_bot_in_chat = AsyncMock(return_value=ensure_bot_return)
    return service


# ==================== FetchGroupChatNode 测试 ====================


@pytest.mark.asyncio
async def test_fetch_group_chat_with_config_chat_id() -> None:
    """配置了 chat_id 时直接返回 {chat_id, source: "config"}。"""
    node = FetchGroupChatNode()
    ctx = _make_context(config={"chat_id": "oc_test123"})

    result = await node.execute(ctx)

    assert result.status == "completed"
    assert result.output["chat_id"] == "oc_test123"
    assert result.output["source"] == "config"
    assert result.next_handle == "default"


@pytest.mark.asyncio
async def test_fetch_group_chat_from_work_item() -> None:
    """未配置 chat_id 时从工作项获取。"""
    node = FetchGroupChatNode()
    mock_execution = MagicMock()
    mock_execution.workflow = MagicMock()
    mock_execution.workflow.project = MagicMock()
    ctx = _make_context(
        config={
            "project_key": "TEST",
            "work_item_id": "12345",
            "work_item_type": "story",
        },
        workflow_execution=mock_execution,
    )

    mock_service = _mock_im_service(
        get_chat_id_return={
            "chat_id": "oc_from_item",
            "chat_name": "测试群",
            "owner_id": "user_001",
            "source": "work_item_api",
        },
    )

    with patch(
        "workflows.nodes.integrations.feishu_chat.FeishuIMService.create",
        return_value=mock_service,
    ):
        result = await node.execute(ctx)

    assert result.status == "completed"
    assert result.output["chat_id"] == "oc_from_item"
    assert result.output["source"] == "work_item_api"
    assert result.next_handle == "default"


@pytest.mark.asyncio
async def test_fetch_group_chat_no_chat_found() -> None:
    """工作项也没群聊时返回 failed + error 端口。"""
    node = FetchGroupChatNode()
    mock_execution = MagicMock()
    mock_execution.workflow = MagicMock()
    mock_execution.workflow.project = MagicMock()
    ctx = _make_context(
        config={
            "project_key": "TEST",
            "work_item_id": "99999",
            "work_item_type": "story",
        },
        workflow_execution=mock_execution,
    )

    mock_service = _mock_im_service(get_chat_id_return=None)

    with patch(
        "workflows.nodes.integrations.feishu_chat.FeishuIMService.create",
        return_value=mock_service,
    ):
        result = await node.execute(ctx)

    assert result.status == "failed"
    assert result.error is not None
    assert result.next_handle == "error"


# ==================== JoinGroupChatNode 测试 ====================


@pytest.mark.asyncio
async def test_join_group_chat_success() -> None:
    """ensure_bot_in_chat 返回 success=True 时成功。"""
    node = JoinGroupChatNode()
    mock_execution = MagicMock()
    mock_execution.workflow = MagicMock()
    mock_execution.workflow.project = MagicMock()
    ctx = _make_context(
        config={"chat_id": "oc_join_test"},
        workflow_execution=mock_execution,
    )

    mock_service = _mock_im_service(
        ensure_bot_return={"success": True, "already_member": False, "error": None},
    )

    with patch(
        "workflows.nodes.integrations.feishu_chat.FeishuIMService.create",
        return_value=mock_service,
    ):
        result = await node.execute(ctx)

    assert result.status == "completed"
    assert result.output["chat_id"] == "oc_join_test"
    assert result.output["already_member"] is False
    assert result.next_handle == "default"


@pytest.mark.asyncio
async def test_join_group_chat_already_member() -> None:
    """已在群内时幂等成功（already_member=True）。"""
    node = JoinGroupChatNode()
    mock_execution = MagicMock()
    mock_execution.workflow = MagicMock()
    mock_execution.workflow.project = MagicMock()
    ctx = _make_context(
        config={"chat_id": "oc_already"},
        workflow_execution=mock_execution,
    )

    mock_service = _mock_im_service(
        ensure_bot_return={"success": True, "already_member": True, "error": None},
    )

    with patch(
        "workflows.nodes.integrations.feishu_chat.FeishuIMService.create",
        return_value=mock_service,
    ):
        result = await node.execute(ctx)

    assert result.status == "completed"
    assert result.output["already_member"] is True
    assert result.next_handle == "default"


@pytest.mark.asyncio
async def test_join_group_chat_permission_denied() -> None:
    """权限不足时返回 failed + error 端口。"""
    node = JoinGroupChatNode()
    mock_execution = MagicMock()
    mock_execution.workflow = MagicMock()
    mock_execution.workflow.project = MagicMock()
    ctx = _make_context(
        config={"chat_id": "oc_no_perm"},
        workflow_execution=mock_execution,
    )

    mock_service = _mock_im_service(
        ensure_bot_return={
            "success": False,
            "already_member": False,
            "error": "Bot 加入群聊失败: 权限不足",
        },
    )

    with patch(
        "workflows.nodes.integrations.feishu_chat.FeishuIMService.create",
        return_value=mock_service,
    ):
        result = await node.execute(ctx)

    assert result.status == "failed"
    assert result.error is not None
    assert "权限不足" in (result.error or "")
    assert result.next_handle == "error"


# ==================== GroupChatQuestionNode 测试 ====================


@pytest.mark.asyncio
async def test_chat_question_node_returns_waiting_event() -> None:
    """Test 6: GroupChatQuestionNode 执行后返回 waiting_event 状态。"""
    from workflows.nodes.integrations.chat_question import GroupChatQuestionNode

    node = GroupChatQuestionNode()
    mock_execution = MagicMock()
    mock_execution.workflow = MagicMock()
    mock_execution.workflow.project = MagicMock()
    ctx = _make_context(
        config={
            "chat_id": "oc_question_test",
            "question": "选择哪个方案？",
            "options": ["方案 A", "方案 B"],
            "work_item_name": "work item",
        },
        workflow_execution=mock_execution,
    )

    mock_im_client = AsyncMock()
    mock_im_client.send_card = AsyncMock(return_value="msg_12345")

    with (
        patch(
            "workflows.nodes.integrations.chat_question.FeishuIMClient",
            return_value=mock_im_client,
        ),
        patch(
            "workflows.nodes.integrations.chat_question._get_feishu_credentials",
            return_value=("app_id", "app_secret"),
        ),
    ):
        result = await node.execute(ctx)

    assert result.status == "waiting_event"
    assert result.output["message_id"] == "msg_12345"
    assert result.output["question"] == "选择哪个方案？"
    assert result.output["chat_id"] == "oc_question_test"

    # 确认 send_card 被调用
    mock_im_client.send_card.assert_called_once()
    call_kwargs = mock_im_client.send_card.call_args[1]
    assert call_kwargs["receive_id"] == "oc_question_test"
    assert call_kwargs["receive_id_type"] == "chat_id"


@pytest.mark.asyncio
async def test_chat_question_node_missing_question() -> None:
    """缺少 question 配置时返回 failed。"""
    from workflows.nodes.integrations.chat_question import GroupChatQuestionNode

    node = GroupChatQuestionNode()
    ctx = _make_context(config={"chat_id": "oc_test"})

    result = await node.execute(ctx)

    assert result.status == "failed"
    assert result.error is not None


@pytest.mark.asyncio
async def test_chat_question_node_config_has_mention_user_id() -> None:
    """config_schema 包含 mention_user_id 可选字段。"""
    from workflows.nodes.integrations.chat_question import GroupChatQuestionNode

    schema = GroupChatQuestionNode.config_schema
    props = schema["properties"]
    assert "mention_user_id" in props
    assert props["mention_user_id"]["type"] == "string"
    # mention_user_id 不在 required 中
    assert "mention_user_id" not in schema.get("required", [])


@pytest.mark.asyncio
async def test_chat_question_node_passes_mention_user_id() -> None:
    """mention_user_id 传递到 build_chat_question_card 和 output。"""
    from workflows.nodes.integrations.chat_question import GroupChatQuestionNode

    node = GroupChatQuestionNode()
    mock_execution = MagicMock()
    mock_execution.workflow = MagicMock()
    mock_execution.workflow.project = MagicMock()
    mock_execution.id = "we-001"
    mock_ne = MagicMock()
    mock_ne.id = "ne-001"
    ctx = _make_context(
        config={
            "chat_id": "oc_test",
            "question": "请确认",
            "mention_user_id": "ou_mention_test",
        },
        workflow_execution=mock_execution,
    )
    ctx.node_execution = mock_ne

    mock_im_client = AsyncMock()
    mock_im_client.send_card = AsyncMock(return_value="msg_m1")

    with (
        patch(
            "workflows.nodes.integrations.chat_question.FeishuIMClient",
            return_value=mock_im_client,
        ),
        patch(
            "workflows.nodes.integrations.chat_question._get_feishu_credentials",
            return_value=("app_id", "app_secret"),
        ),
        patch(
            "workflows.nodes.integrations.chat_question.WorkflowEventSubscription",
        ) as mock_sub_cls,
    ):
        mock_sub_cls.objects.acreate = AsyncMock()
        result = await node.execute(ctx)

    assert result.output["mention_user_id"] == "ou_mention_test"

    # 验证 send_card 的 card 参数包含 @mention
    card_arg = mock_im_client.send_card.call_args[1]["card"]
    md_elements = [e for e in card_arg["elements"] if e.get("tag") == "markdown"]
    mention_found = any('<at id="ou_mention_test">' in e.get("content", "") for e in md_elements)
    assert mention_found


@pytest.mark.asyncio
async def test_chat_question_node_creates_event_subscription() -> None:
    """执行后创建 WorkflowEventSubscription 记录 timeout_at。"""
    from workflows.nodes.integrations.chat_question import GroupChatQuestionNode

    node = GroupChatQuestionNode()
    mock_execution = MagicMock()
    mock_execution.workflow = MagicMock()
    mock_execution.workflow.project = MagicMock()
    mock_execution.id = "we-002"
    mock_ne = MagicMock()
    mock_ne.id = "ne-002"
    ctx = _make_context(
        config={
            "chat_id": "oc_sub_test",
            "question": "问题",
        },
        workflow_execution=mock_execution,
    )
    ctx.node_execution = mock_ne

    mock_im_client = AsyncMock()
    mock_im_client.send_card = AsyncMock(return_value="msg_s1")

    with (
        patch(
            "workflows.nodes.integrations.chat_question.FeishuIMClient",
            return_value=mock_im_client,
        ),
        patch(
            "workflows.nodes.integrations.chat_question._get_feishu_credentials",
            return_value=("app_id", "app_secret"),
        ),
        patch(
            "workflows.nodes.integrations.chat_question.WorkflowEventSubscription",
        ) as mock_sub_cls,
    ):
        mock_sub_cls.objects.acreate = AsyncMock()
        result = await node.execute(ctx)

    assert result.status == "waiting_event"
    # 验证 acreate 被调用
    mock_sub_cls.objects.acreate.assert_called_once()
    call_kwargs = mock_sub_cls.objects.acreate.call_args[1]
    assert call_kwargs["event_type"] == "ChatQuestionCallback"
    assert call_kwargs["timeout_action"] == "fail"
    assert call_kwargs["timeout_at"] is not None


@pytest.mark.asyncio
async def test_chat_question_node_missing_chat_id() -> None:
    """缺少 chat_id 配置时返回 failed。"""
    from workflows.nodes.integrations.chat_question import GroupChatQuestionNode

    node = GroupChatQuestionNode()
    ctx = _make_context(config={"question": "问题"})

    result = await node.execute(ctx)

    assert result.status == "failed"
    assert result.error is not None


@pytest.mark.asyncio
async def test_chat_question_node_config_has_max_rounds() -> None:
    """config_schema 包含 max_rounds 字段（默认 1，最大 5）。"""
    from workflows.nodes.integrations.chat_question import GroupChatQuestionNode

    schema = GroupChatQuestionNode.config_schema
    props = schema["properties"]
    assert "max_rounds" in props
    assert props["max_rounds"]["type"] == "integer"
    assert props["max_rounds"]["default"] == 1
    assert props["max_rounds"]["maximum"] == 5
    assert props["max_rounds"]["minimum"] == 1


@pytest.mark.asyncio
async def test_chat_question_node_output_includes_rounds_info() -> None:
    """execute 输出包含 max_rounds、current_round、rounds。"""
    from workflows.nodes.integrations.chat_question import GroupChatQuestionNode

    node = GroupChatQuestionNode()
    mock_execution = MagicMock()
    mock_execution.workflow = MagicMock()
    mock_execution.workflow.project = MagicMock()
    mock_execution.id = "we-rounds"
    mock_ne = MagicMock()
    mock_ne.id = "ne-rounds"
    ctx = _make_context(
        config={
            "chat_id": "oc_rounds",
            "question": "问题",
            "max_rounds": 3,
        },
        workflow_execution=mock_execution,
    )
    ctx.node_execution = mock_ne

    mock_im_client = AsyncMock()
    mock_im_client.send_card = AsyncMock(return_value="msg_r1")

    with (
        patch(
            "workflows.nodes.integrations.chat_question.FeishuIMClient",
            return_value=mock_im_client,
        ),
        patch(
            "workflows.nodes.integrations.chat_question._get_feishu_credentials",
            return_value=("app_id", "app_secret"),
        ),
        patch(
            "workflows.nodes.integrations.chat_question.WorkflowEventSubscription",
        ) as mock_sub_cls,
    ):
        mock_sub_cls.objects.acreate = AsyncMock()
        result = await node.execute(ctx)

    assert result.output["max_rounds"] == 3
    assert result.output["current_round"] == 1
    assert result.output["rounds"] == []


# ==================== CreateGroupChatNode 测试 ====================


def _make_create_context(config: dict) -> ExecutionContext:
    """构建带 workflow_execution（含 project）的 CreateGroupChatNode 上下文。"""
    mock_execution = MagicMock()
    mock_execution.workflow = MagicMock()
    mock_execution.workflow.project = MagicMock()
    return _make_context(config=config, workflow_execution=mock_execution)


def _mock_create_im_service(
    create_chat_return: dict | None = None,
    create_chat_side_effect: Exception | None = None,
) -> AsyncMock:
    """构建带 create_chat 的 AsyncMock FeishuIMService。"""
    service = AsyncMock()
    service.create_chat = AsyncMock(
        return_value=create_chat_return,
        side_effect=create_chat_side_effect,
    )
    return service


@pytest.mark.asyncio
async def test_create_group_chat_happy() -> None:
    """建群成功 → completed + chat_id 一等字段 + source，create_chat 收到解析后的 user_id_list。"""
    node = CreateGroupChatNode()
    ctx = _make_create_context(
        config={"name": "需求群", "member_ids": "ou_a, ou_b"},
    )
    mock_service = _mock_create_im_service(
        create_chat_return={"chat_id": "oc_x", "name": "需求群", "owner_id": ""},
    )

    with patch(
        "workflows.nodes.integrations.feishu_chat.FeishuIMService.create",
        return_value=mock_service,
    ):
        result = await node.execute(ctx)

    assert result.status == "completed"
    assert result.next_handle == "default"
    assert result.output["chat_id"] == "oc_x"
    assert result.output["source"] == "create_group_chat"
    assert result.output["chat_name"] == "需求群"
    # 群主为 bot 时飞书不返回 owner_id → 容错空串（P-3）
    assert result.output["owner_id"] == ""
    assert result.output["writeback"]["attempted"] is False

    mock_service.create_chat.assert_called_once()
    call_kwargs = mock_service.create_chat.call_args[1]
    assert call_kwargs["user_id_list"] == ["ou_a", "ou_b"]


@pytest.mark.asyncio
async def test_create_group_chat_member_ids_comma() -> None:
    """member_ids 逗号分隔形态 → user_id_list=["ou_a","ou_b"]。"""
    node = CreateGroupChatNode()
    ctx = _make_create_context(config={"name": "群", "member_ids": "ou_a, ou_b"})
    mock_service = _mock_create_im_service(
        create_chat_return={"chat_id": "oc_x", "name": "群", "owner_id": ""},
    )

    with patch(
        "workflows.nodes.integrations.feishu_chat.FeishuIMService.create",
        return_value=mock_service,
    ):
        result = await node.execute(ctx)

    assert result.status == "completed"
    assert mock_service.create_chat.call_args[1]["user_id_list"] == ["ou_a", "ou_b"]


@pytest.mark.asyncio
async def test_create_group_chat_member_ids_json() -> None:
    """member_ids JSON 列表形态 → user_id_list=["ou_a","ou_b"]。"""
    node = CreateGroupChatNode()
    ctx = _make_create_context(config={"name": "群", "member_ids": '["ou_a","ou_b"]'})
    mock_service = _mock_create_im_service(
        create_chat_return={"chat_id": "oc_x", "name": "群", "owner_id": ""},
    )

    with patch(
        "workflows.nodes.integrations.feishu_chat.FeishuIMService.create",
        return_value=mock_service,
    ):
        result = await node.execute(ctx)

    assert result.status == "completed"
    assert mock_service.create_chat.call_args[1]["user_id_list"] == ["ou_a", "ou_b"]


@pytest.mark.asyncio
async def test_create_group_chat_member_ids_template() -> None:
    """member_ids 模板形态（get_template_value 返回 list）→ user_id_list=["ou_a","ou_b"]。"""
    node = CreateGroupChatNode()
    ctx = _make_create_context(
        config={"name": "群", "member_ids": "{{nodes.x.member_ids}}"},
    )
    ctx.get_template_value = MagicMock(return_value=["ou_a", "ou_b"])
    mock_service = _mock_create_im_service(
        create_chat_return={"chat_id": "oc_x", "name": "群", "owner_id": ""},
    )

    with patch(
        "workflows.nodes.integrations.feishu_chat.FeishuIMService.create",
        return_value=mock_service,
    ):
        result = await node.execute(ctx)

    assert result.status == "completed"
    assert mock_service.create_chat.call_args[1]["user_id_list"] == ["ou_a", "ou_b"]


@pytest.mark.asyncio
async def test_create_group_chat_missing_name() -> None:
    """缺群名 → failed + error handle，且不调 create_chat。"""
    node = CreateGroupChatNode()
    ctx = _make_create_context(config={"name": "", "member_ids": "ou_a"})
    mock_service = _mock_create_im_service(
        create_chat_return={"chat_id": "oc_x", "name": "", "owner_id": ""},
    )

    with patch(
        "workflows.nodes.integrations.feishu_chat.FeishuIMService.create",
        return_value=mock_service,
    ):
        result = await node.execute(ctx)

    assert result.status == "failed"
    assert result.next_handle == "error"
    assert result.error is not None
    mock_service.create_chat.assert_not_called()


@pytest.mark.asyncio
async def test_create_group_chat_missing_members() -> None:
    """缺成员 → failed + error handle，且不调 create_chat。"""
    node = CreateGroupChatNode()
    ctx = _make_create_context(config={"name": "群", "member_ids": ""})
    mock_service = _mock_create_im_service(
        create_chat_return={"chat_id": "oc_x", "name": "群", "owner_id": ""},
    )

    with patch(
        "workflows.nodes.integrations.feishu_chat.FeishuIMService.create",
        return_value=mock_service,
    ):
        result = await node.execute(ctx)

    assert result.status == "failed"
    assert result.next_handle == "error"
    mock_service.create_chat.assert_not_called()


@pytest.mark.asyncio
async def test_create_group_chat_create_chat_error() -> None:
    """create_chat 抛 FeishuIMError → failed + error handle（D-7 建群失败）。"""
    node = CreateGroupChatNode()
    ctx = _make_create_context(config={"name": "群", "member_ids": "ou_a"})
    mock_service = _mock_create_im_service(
        create_chat_side_effect=FeishuIMError("no permission", code=230002),
    )

    with patch(
        "workflows.nodes.integrations.feishu_chat.FeishuIMService.create",
        return_value=mock_service,
    ):
        result = await node.execute(ctx)

    assert result.status == "failed"
    assert result.next_handle == "error"
    assert "no permission" in (result.error or "")


@pytest.mark.asyncio
async def test_create_group_chat_writeback_happy() -> None:
    """配置 work_item 标识 → writeback 被以三元组+chat_id 调用，节点 completed。"""
    node = CreateGroupChatNode()
    ctx = _make_create_context(
        config={
            "name": "群",
            "member_ids": "ou_a",
            "project_key": "P",
            "work_item_id": "123",
            "work_item_type": "story",
        },
    )
    mock_service = _mock_create_im_service(
        create_chat_return={"chat_id": "oc_x", "name": "群", "owner_id": ""},
    )
    mock_writeback = AsyncMock(return_value=True)

    with (
        patch(
            "workflows.nodes.integrations.feishu_chat.FeishuIMService.create",
            return_value=mock_service,
        ),
        patch(
            "delivery.services.work_item_service.WorkItemService.awriteback_feishu_chat_id",
            mock_writeback,
        ),
    ):
        result = await node.execute(ctx)

    assert result.status == "completed"
    assert result.output["writeback"]["attempted"] is True
    assert result.output["writeback"]["success"] is True
    mock_writeback.assert_called_once_with("P", "story", 123, "oc_x")


@pytest.mark.asyncio
async def test_create_group_chat_writeback_fail_soft() -> None:
    """writeback DB 异常 → 节点仍 completed 返回 chat_id，异常不冒泡（D-7 fail-soft）。"""
    node = CreateGroupChatNode()
    ctx = _make_create_context(
        config={
            "name": "群",
            "member_ids": "ou_a",
            "project_key": "P",
            "work_item_id": "123",
        },
    )
    mock_service = _mock_create_im_service(
        create_chat_return={"chat_id": "oc_x", "name": "群", "owner_id": ""},
    )
    mock_writeback = AsyncMock(side_effect=Exception("db down"))

    with (
        patch(
            "workflows.nodes.integrations.feishu_chat.FeishuIMService.create",
            return_value=mock_service,
        ),
        patch(
            "delivery.services.work_item_service.WorkItemService.awriteback_feishu_chat_id",
            mock_writeback,
        ),
    ):
        result = await node.execute(ctx)

    assert result.status == "completed"
    assert result.output["chat_id"] == "oc_x"
    assert result.output["writeback"]["attempted"] is True
    assert result.output["writeback"]["success"] is False


@pytest.mark.asyncio
async def test_create_group_chat_writeback_not_found() -> None:
    """writeback 返回 False（WorkItem 不存在）→ completed + success False。"""
    node = CreateGroupChatNode()
    ctx = _make_create_context(
        config={
            "name": "群",
            "member_ids": "ou_a",
            "project_key": "P",
            "work_item_id": "123",
        },
    )
    mock_service = _mock_create_im_service(
        create_chat_return={"chat_id": "oc_x", "name": "群", "owner_id": ""},
    )
    mock_writeback = AsyncMock(return_value=False)

    with (
        patch(
            "workflows.nodes.integrations.feishu_chat.FeishuIMService.create",
            return_value=mock_service,
        ),
        patch(
            "delivery.services.work_item_service.WorkItemService.awriteback_feishu_chat_id",
            mock_writeback,
        ),
    ):
        result = await node.execute(ctx)

    assert result.status == "completed"
    assert result.output["writeback"]["attempted"] is True
    assert result.output["writeback"]["success"] is False


@pytest.mark.asyncio
async def test_create_group_chat_no_writeback_config() -> None:
    """未配 work_item 标识 → 不调 awriteback，completed + attempted False。"""
    node = CreateGroupChatNode()
    ctx = _make_create_context(config={"name": "群", "member_ids": "ou_a"})
    mock_service = _mock_create_im_service(
        create_chat_return={"chat_id": "oc_x", "name": "群", "owner_id": ""},
    )
    mock_writeback = AsyncMock(return_value=True)

    with (
        patch(
            "workflows.nodes.integrations.feishu_chat.FeishuIMService.create",
            return_value=mock_service,
        ),
        patch(
            "delivery.services.work_item_service.WorkItemService.awriteback_feishu_chat_id",
            mock_writeback,
        ),
    ):
        result = await node.execute(ctx)

    assert result.status == "completed"
    assert result.output["writeback"]["attempted"] is False
    mock_writeback.assert_not_called()


@pytest.mark.asyncio
async def test_create_group_fenced() -> None:
    """IDEMP-02：已有 feishu_chat_id → 复用既有群，create_chat 未被调用。"""
    node = CreateGroupChatNode()
    ctx = _make_create_context(
        config={
            "name": "群",
            "member_ids": "ou_a",
            "project_key": "P",
            "work_item_id": "123",
            "work_item_type": "story",
        },
    )
    mock_service = _mock_create_im_service(
        create_chat_return={"chat_id": "oc_new", "name": "群", "owner_id": ""},
    )
    mock_aget = AsyncMock(return_value="oc_existing")

    with (
        patch(
            "workflows.nodes.integrations.feishu_chat.FeishuIMService.create",
            return_value=mock_service,
        ),
        patch(
            "delivery.services.work_item_service.WorkItemService.aget_feishu_chat_id",
            mock_aget,
        ),
    ):
        result = await node.execute(ctx)

    assert result.status == "completed"
    assert result.next_handle == "default"
    assert result.output["chat_id"] == "oc_existing"
    assert result.output["deduplicated"] is True
    assert result.output["writeback"]["attempted"] is False
    mock_aget.assert_called_once_with("P", "story", 123)
    mock_service.create_chat.assert_not_called()


@pytest.mark.asyncio
async def test_create_group_no_anchor_creates() -> None:
    """无 work_item 锚 → 不查 fence、照常建群（现状零回归）。"""
    node = CreateGroupChatNode()
    ctx = _make_create_context(config={"name": "群", "member_ids": "ou_a"})
    mock_service = _mock_create_im_service(
        create_chat_return={"chat_id": "oc_x", "name": "群", "owner_id": ""},
    )
    mock_aget = AsyncMock(return_value="oc_should_not_be_used")

    with (
        patch(
            "workflows.nodes.integrations.feishu_chat.FeishuIMService.create",
            return_value=mock_service,
        ),
        patch(
            "delivery.services.work_item_service.WorkItemService.aget_feishu_chat_id",
            mock_aget,
        ),
    ):
        result = await node.execute(ctx)

    assert result.status == "completed"
    assert result.output["chat_id"] == "oc_x"
    assert "deduplicated" not in result.output
    mock_aget.assert_not_called()
    mock_service.create_chat.assert_called_once()


@pytest.mark.asyncio
async def test_create_group_fence_failsoft() -> None:
    """fence 查询抛异常 → 节点仍照常建群（fail-soft 不阻断）。"""
    node = CreateGroupChatNode()
    ctx = _make_create_context(
        config={
            "name": "群",
            "member_ids": "ou_a",
            "project_key": "P",
            "work_item_id": "123",
        },
    )
    mock_service = _mock_create_im_service(
        create_chat_return={"chat_id": "oc_x", "name": "群", "owner_id": ""},
    )
    mock_aget = AsyncMock(side_effect=Exception("db down"))

    with (
        patch(
            "workflows.nodes.integrations.feishu_chat.FeishuIMService.create",
            return_value=mock_service,
        ),
        patch(
            "delivery.services.work_item_service.WorkItemService.aget_feishu_chat_id",
            mock_aget,
        ),
        patch(
            "delivery.services.work_item_service.WorkItemService.awriteback_feishu_chat_id",
            AsyncMock(return_value=True),
        ),
    ):
        result = await node.execute(ctx)

    assert result.status == "completed"
    assert result.output["chat_id"] == "oc_x"
    assert "deduplicated" not in result.output
    mock_service.create_chat.assert_called_once()


@pytest.mark.asyncio
async def test_create_group_chat_auto_registered() -> None:
    """@register_node 自动注册：NodeRegistry.get("create_group_chat") 返回 CreateGroupChatNode。"""
    from workflows.nodes.registry import NodeRegistry

    assert NodeRegistry.get("create_group_chat") is CreateGroupChatNode
    assert CreateGroupChatNode.node_type == "create_group_chat"
