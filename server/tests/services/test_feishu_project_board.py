"""飞书"项目跟踪"看板枚举守护测试（FSPROJ-01）。

覆盖：枚举 happy（子项 story/缺陷 + 人员带角色）、无子项·无人员 fail-soft 降级、硬路径非 JSON
fail-loud、角色映射表 + 保守默认、story vs 缺陷类型推断。飞书响应经 respx mock（先 token 后
query 端点），pytest-socket 隔离不发真实网络，不依赖真实凭证。
"""

from __future__ import annotations

import httpx
import pytest
import respx

from services.feishu import FeishuClient
from services.feishu_parsing import FeishuResponseError, RELATION_FIELD_TYPE_KEY
from services.feishu_project_board import (
    DEFAULT_PROJECT_ROLE,
    DEFECT_WORK_ITEM_TYPE,
    STORY_WORK_ITEM_TYPE,
    enumerate_board,
    map_role,
)

API_BASE = "https://project.feishu.cn"
PROJECT_KEY = "board-pk-001"
BOARD_ID = 9000001


def _client() -> FeishuClient:
    return FeishuClient(
        plugin_id="pid", plugin_secret="psecret", project_key=PROJECT_KEY, user_key="uk"
    )


def _mock_token() -> None:
    respx.post(f"{API_BASE}/open_api/authen/plugin_token").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {"token": "ptok", "expire_time": 7200},
                "error": {"code": 0, "msg": "success"},
            },
        )
    )


def _mock_board(fields: list[dict], *, work_item_type: str = "project") -> None:
    """mock 看板工作项 query 端点（fields 决定派生结果）。"""
    item = {"id": BOARD_ID, "name": "项目跟踪看板", "fields": fields}
    respx.post(
        f"{API_BASE}/open_api/{PROJECT_KEY}/work_item/{work_item_type}/query"
    ).mock(return_value=httpx.Response(200, json={"err_code": 0, "data": [item]}))


def _relation_field(name: str, value: list[int], key: str = "field_rel") -> dict:
    return {
        "field_key": key,
        "field_name": name,
        "field_value": value,
        "field_type_key": RELATION_FIELD_TYPE_KEY,
        "field_alias": None,
    }


def _user_field(name: str, value: list, key: str = "field_user") -> dict:
    return {
        "field_key": key,
        "field_name": name,
        "field_value": value,
        "field_type_key": "user",
        "field_alias": None,
    }


# === 纯函数：角色映射表 + 保守默认 ===


def test_map_role_table_hits() -> None:
    assert map_role({"field_name": "前端"}) == "frontend"
    assert map_role({"field_name": "后端负责人"}) == "owner"  # 子串"负责人"命中 owner
    assert map_role({"field_alias": "qa"}) == "qa"
    assert map_role({"field_name": "产品经理"}) == "pm"


def test_map_role_default_when_undecidable() -> None:
    assert map_role({"field_name": "某未知字段"}) == DEFAULT_PROJECT_ROLE
    assert map_role({}) == DEFAULT_PROJECT_ROLE


# === 枚举：happy / 类型推断 / 角色 ===


@respx.mock
async def test_enumerate_happy_children_and_people() -> None:
    _mock_token()
    _mock_board(
        [
            _relation_field("关联需求", [7001, 7002], key="f_story"),
            _relation_field("关联缺陷", [8001], key="f_defect"),
            _user_field("后端", ["ou_be"], key="f_be"),
            _user_field("测试", ["ou_qa"], key="f_qa"),
        ]
    )
    result = await enumerate_board(
        _client(),
        feishu_project_key=PROJECT_KEY,
        board_work_item_id=BOARD_ID,
        board_work_item_type="project",
    )
    assert result.degraded is False
    # story vs 缺陷类型推断
    story = [w for w in result.work_items if w.work_item_type == STORY_WORK_ITEM_TYPE]
    defect = [w for w in result.work_items if w.work_item_type == DEFECT_WORK_ITEM_TYPE]
    assert {w.work_item_id for w in story} == {7001, 7002}
    assert {w.work_item_id for w in defect} == {8001}
    # 人员带角色
    roles = {p.user_key: p.role for p in result.people}
    assert roles == {"ou_be": "backend", "ou_qa": "qa"}


@respx.mock
async def test_enumerate_no_children_no_people_degraded() -> None:
    """无子项·无人员 → fail-soft 部分结果 + warning + degraded（不抛）。"""
    _mock_token()
    _mock_board([])  # 空 fields
    result = await enumerate_board(
        _client(),
        feishu_project_key=PROJECT_KEY,
        board_work_item_id=BOARD_ID,
        board_work_item_type="project",
    )
    assert result.degraded is True
    assert result.work_items == []
    assert result.people == []
    assert "no_child_work_items" in result.warnings
    assert "no_people" in result.warnings


@respx.mock
async def test_enumerate_hard_path_non_json_fail_loud() -> None:
    """硬路径（看板工作项取数）非 JSON → fail-loud 抛 FeishuResponseError（调用方降级）。"""
    _mock_token()
    respx.post(f"{API_BASE}/open_api/{PROJECT_KEY}/work_item/project/query").mock(
        return_value=httpx.Response(
            200, text="<html>502</html>", headers={"content-type": "text/html"}
        )
    )
    with pytest.raises(FeishuResponseError):
        await enumerate_board(
            _client(),
            feishu_project_key=PROJECT_KEY,
            board_work_item_id=BOARD_ID,
            board_work_item_type="project",
        )
