"""ProjectBoardSyncService 守护测试（FSPROJ-02/03 同源建项目入口）。

覆盖：幂等建项目（重复不新建、dup 补齐成员/链接不重复）、枚举 fail-soft 降级仍建项目、
拉人经身份映射（未映射跳过）、initiated_by_user_id 审计绑定。飞书 client 用鸭子类型 fake
（不依赖真实凭证/网络），WorkItem 落库经 WorkItemService（INV-6）。
"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from audit.models import AuditEvent
from audit.services import taxonomy
from feishu.services import bind_feishu_user
from initiatives.models import ProjectMember, ProjectRole, ProjectWorkItemLink
from initiatives.services import ProjectBoardSyncService
from projects.models import Space
from services.feishu import WorkItemInfo
from services.feishu_parsing import FeishuResponseError, RELATION_FIELD_TYPE_KEY

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()
BOARD_PK = "sync-board-pk"
BOARD_ID = 9100001


def _board_fields() -> list[dict]:
    return [
        {
            "field_key": "f_story",
            "field_name": "关联需求",
            "field_value": [7001, 7002],
            "field_type_key": RELATION_FIELD_TYPE_KEY,
            "field_alias": None,
        },
        {
            "field_key": "f_be",
            "field_name": "后端",
            "field_value": ["uk_mapped"],
            "field_type_key": "user",
            "field_alias": None,
        },
        {
            "field_key": "f_qa",
            "field_name": "测试",
            "field_value": ["uk_unmapped"],
            "field_type_key": "user",
            "field_alias": None,
        },
    ]


class _FakeClient:
    """鸭子类型飞书 client：get_work_item 返回构造的 WorkItemInfo。"""

    def __init__(self, fields: list[dict]):
        self._fields = fields

    async def get_work_item(self, project_key, work_item_id, work_item_type):
        return WorkItemInfo(
            id=work_item_id,
            name="项目跟踪看板",
            description="",
            status="",
            project_key=project_key,
            work_item_type=work_item_type,
            fields={},
            feishu_fields=self._fields,
        )


class _RaisingClient:
    async def get_work_item(self, *a, **k):
        raise FeishuResponseError("非 JSON 响应")


@sync_to_async
def _make_space() -> Space:
    return Space.objects.create(name="S", feishu_project_key=BOARD_PK)


@sync_to_async
def _make_user(username) -> object:
    return User.objects.create_user(username=username, password="x")


async def _sync(space, client, initiated_by="system"):
    return await ProjectBoardSyncService().sync_from_board(
        space=space,
        feishu_project_key=BOARD_PK,
        board_work_item_id=BOARD_ID,
        board_work_item_type="project",
        name="自动项目",
        client=client,
        initiated_by_user_id=initiated_by,
    )


async def test_idempotent_create_no_duplicate_tops_up() -> None:
    """重复事件：项目不重复建，成员/链接 get_or_create 只补齐不重复。"""
    space = await _make_space()
    mapped = await _make_user("mapped")
    await bind_feishu_user(user=mapped, feishu_user_key="uk_mapped")

    r1 = await _sync(space, _FakeClient(_board_fields()))
    assert r1["created"] is True
    assert r1["work_items_linked"] == 2
    assert r1["members_added"] == 1  # uk_mapped 命中
    assert r1["members_unmapped"] == 1  # uk_unmapped 跳过

    r2 = await _sync(space, _FakeClient(_board_fields()))
    assert r2["created"] is False  # 幂等：不重复建

    # 链接/成员不重复
    from initiatives.models import Project

    project = await Project.objects.aget(space=space, feishu_project_key=BOARD_PK)
    assert await ProjectWorkItemLink.objects.filter(project=project).acount() == 2
    assert (
        await ProjectMember.objects.filter(project=project, user=mapped).acount() == 1
    )


async def test_pull_people_resolves_role_and_skips_unmapped() -> None:
    space = await _make_space()
    mapped = await _make_user("be_user")
    await bind_feishu_user(user=mapped, feishu_user_key="uk_mapped")

    result = await _sync(space, _FakeClient(_board_fields()))
    from initiatives.models import Project

    project = await Project.objects.aget(space=space, feishu_project_key=BOARD_PK)
    member = await ProjectMember.objects.aget(project=project, user=mapped)
    assert member.role == ProjectRole.BACKEND  # "后端" 字段 → backend
    assert result["members_unmapped"] == 1


async def test_enumeration_fail_soft_still_creates_project() -> None:
    """枚举硬路径抛错 → 降级半自动：仍建项目 + degraded=True，不抛。"""
    space = await _make_space()
    result = await _sync(space, _RaisingClient())
    assert result["created"] is True
    assert result["degraded"] is True
    assert "enumeration_failed" in result["warnings"]
    assert result["work_items_linked"] == 0

    from initiatives.models import Project

    assert await Project.objects.filter(
        space=space, feishu_project_key=BOARD_PK
    ).aexists()


async def test_initiated_by_user_id_bound_in_audit() -> None:
    """触发用户 id 经审计绑定（initiated_by_user_id 写入 AuditEvent.metadata）。"""
    space = await _make_space()
    actor = await _make_user("trigger_user")
    await _sync(space, _FakeClient([]), initiated_by=str(actor.id))
    ev = await AuditEvent.objects.filter(action=taxonomy.ACTION_PROJECT_CREATED).afirst()
    assert ev is not None
    assert ev.metadata.get("initiated_by_user_id") == str(actor.id)


async def test_result_carries_only_scalars_no_raw_payload() -> None:
    """脱敏：结果只含标量计数字段，绝不回传原始 payload（不泄漏）。"""
    space = await _make_space()
    result = await _sync(space, _FakeClient(_board_fields()))
    assert set(result.keys()) == {
        "project_id",
        "created",
        "degraded",
        "warnings",
        "members_added",
        "members_unmapped",
        "work_items_linked",
    }
