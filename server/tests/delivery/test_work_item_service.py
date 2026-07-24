"""WorkItemService.upsert 与派生纯函数守护测试（Phase 28-02）。

覆盖 DOMAIN §13.1 upsert 步骤与 WIT-01..05：
- Task 1：`derive_status_fields` / `derive_status_events` 纯函数 + `work_item_synced` 信号。
- Task 2：三元组幂等收敛（WIT-01）、mirror-only 刷新保护 enhanced（WIT-02）、
  per-facet `WorkItemSyncState` 且回源失败不整体回滚（WIT-03）。
- Task 3：关系派生 + `target_external_id` 占位/回填（WIT-04）、状态变更 append
  `WorkItemStatusEvent`（WIT-05）、relations facet 完整度。

所有回源经 `respx` mock（先 token 端点后业务端点），pytest-socket 隔离不发真实网络。
fixture 字段形状取 DOMAIN §16 实测（story 1000000002：field_000008=[1000000004]）。
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from delivery.services.derivation import derive_status_events, derive_status_fields

# 回源 upsert 测试经 sync_to_async / 异步 ORM 写库——须用 transaction=True
# （TransactionTestCase 语义：每测试后 flush 表），否则跨线程连接写入不被主连接
# 事务回滚清理，导致 Space.feishu_project_key 唯一约束跨测试冲突。
# 纯函数派生测试不触 DB，不受影响。
pytestmark = pytest.mark.django_db(transaction=True)

# === DOMAIN §16 实测自然键 ===
PROJECT_KEY = "000000000000000000000001"
API_BASE = "https://project.feishu.cn"
STORY_ID = 1000000002
TARGET_PROJECT_ID = 1000000004


# ============================================================================
# Task 1：派生纯函数 + 信号（纯函数，无 DB / 无网络）
# ============================================================================


def _story_raw_item() -> dict:
    """story 工作项响应 item（current_nodes 给出人类名）。"""
    return {
        "id": STORY_ID,
        "name": "实现学习平台 A",
        "work_item_status": {
            "state_key": "fi46o4r6m",
            "sub_stage": "dev",
            "current_nodes": [{"id": "state_2", "name": "Sprint计划"}],
            "state_times": [{"state_key": "fi46o4r6m", "name": "Sprint计划(times)"}],
            "is_archived_state": False,
            "is_init_state": True,
        },
    }


def _issue_raw_item() -> dict:
    """issue 工作项响应 item（无 current_nodes，仅 state_times 回退）。"""
    return {
        "id": 1000000006,
        "name": "登录崩溃",
        "work_item_status": {
            "state_key": "OPEN",
            "state_times": [
                {"state_key": "OPEN", "name": "待处理"},
                {"state_key": "CLOSED", "name": "已关闭"},
            ],
        },
    }


def test_derive_status_fields_story_current_nodes() -> None:
    """story：state_key 透传，display_name 取 current_nodes 优先。"""
    result = derive_status_fields(_story_raw_item())
    assert result["status_state_key"] == "fi46o4r6m"
    assert result["status_sub_stage"] == "dev"
    assert result["status_display_name"] == "Sprint计划"
    assert result["is_init_state"] is True
    assert result["is_archived_state"] is False


def test_derive_status_fields_issue_state_times_fallback() -> None:
    """issue：无 current_nodes → display_name 回退 state_times（匹配 state_key）。"""
    result = derive_status_fields(_issue_raw_item())
    assert result["status_state_key"] == "OPEN"
    assert result["status_display_name"] == "待处理"


def test_derive_status_fields_missing_display_name_returns_empty() -> None:
    """current_nodes / state_times 皆缺 → display_name 空串，不抛。"""
    result = derive_status_fields({"work_item_status": {"state_key": "X"}})
    assert result["status_state_key"] == "X"
    assert result["status_display_name"] == ""


def test_derive_status_fields_missing_archived_init_default_false() -> None:
    """is_archived_state / is_init_state 缺失 → False（降级），不抛。"""
    result = derive_status_fields({"work_item_status": {"state_key": "X"}})
    assert result["is_archived_state"] is False
    assert result["is_init_state"] is False


def test_derive_status_fields_non_dict_input_degrades() -> None:
    """非 dict 输入 → 全空降级，不抛异常。"""
    result = derive_status_fields(None)  # type: ignore[arg-type]
    assert result["status_state_key"] == ""
    assert result["status_display_name"] == ""
    assert result["is_archived_state"] is False


def test_derive_status_events_from_history() -> None:
    """从 work_item_status.history[] 归一状态事件列表。"""
    raw = {
        "work_item_status": {
            "state_key": "B",
            "history": [
                {"state_key": "A", "updated_at": 1700000000000, "updated_by": "u1"},
                {"state_key": "B", "updated_at": 1700000100000, "updated_by": "u2"},
            ],
        }
    }
    events = derive_status_events(raw)
    assert len(events) == 2
    assert events[0]["state_key"] == "A"
    assert events[0]["updated_by"] == "u1"
    assert events[1]["state_key"] == "B"


def test_derive_status_events_empty_without_history() -> None:
    """无 history → 空列表，不抛。"""
    assert derive_status_events({"work_item_status": {"state_key": "X"}}) == []
    assert derive_status_events(None) == []  # type: ignore[arg-type]


def test_safe_error_redacts_secrets() -> None:
    """_safe_error 抹掉误入异常消息的 token/secret/Bearer，仅留键名供排障（IN-04）。"""
    from delivery.services import WorkItemService

    msg = (
        'feishu request failed: {"plugin_secret": "s3cr3t_value_xyz", '
        '"access_token": "tok_abcdef123456"} Authorization: Bearer abc.def.ghi'
    )
    redacted = WorkItemService()._safe_error(Exception(msg))

    assert "s3cr3t_value_xyz" not in redacted
    assert "tok_abcdef123456" not in redacted
    assert "abc.def.ghi" not in redacted
    assert "plugin_secret" in redacted  # 键名保留供排障
    assert "***" in redacted


def test_work_item_synced_signal_importable() -> None:
    """work_item_synced 信号对象可 import（best-effort 事件位）。"""
    from django.dispatch import Signal

    from delivery.signals import work_item_synced

    assert isinstance(work_item_synced, Signal)


# ============================================================================
# Task 2 / 3 共用：respx 回源 mock + 带凭证 Space fixture
# ============================================================================

# story 响应字段（含 work_item_related_multi_select → belongs_to_project 派生）
_STORY_FIELDS = [
    {
        "field_key": "field_000001",
        "field_name": "需求文档",
        "field_value": "https://tenant.feishu.cn/docx/doc_token_prd",
        "field_type_key": "link",
        "field_alias": "prd_url",
    },
    {
        "field_key": "field_000008",
        "field_name": "所属项目",
        "field_value": [TARGET_PROJECT_ID],
        "field_type_key": "work_item_related_multi_select",
        "field_alias": None,
    },
]


async def _make_project():
    """创建带飞书插件凭证的 Space（供 create_feishu_client_for_project）。"""
    from common.encryption import encrypt_value
    from projects.models import Space

    return await Space.objects.acreate(
        name="example_platform",
        feishu_project_key=PROJECT_KEY,
        feishu_plugin_id="plugin_test_id",
        feishu_plugin_secret_encrypted=encrypt_value("plugin_test_secret"),
        feishu_user_key="user_key_test",
    )


def _mock_token() -> None:
    """mock plugin_token 端点（业务端点前置）。"""
    respx.post(f"{API_BASE}/open_api/authen/plugin_token").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {"token": "plugin_token_xyz", "expire_time": 7200},
                "error": {"code": 0, "msg": "success"},
            },
        )
    )


def _mock_work_item(
    work_item_type: str = "story",
    *,
    work_item_id: int = STORY_ID,
    name: str = "实现学习平台 A",
    state_key: str = "fi46o4r6m",
    fields: list[dict] | None = None,
    current_nodes: list[dict] | None = None,
) -> None:
    """mock 工作项 query 端点，返回单条 item（DOMAIN §16 形状）。"""
    item = {
        "id": work_item_id,
        "name": name,
        "fields": fields if fields is not None else _STORY_FIELDS,
        "work_item_status": {
            "state_key": state_key,
            "current_nodes": current_nodes
            if current_nodes is not None
            else [{"id": "state_2", "name": "Sprint计划"}],
        },
    }
    respx.post(f"{API_BASE}/open_api/{PROJECT_KEY}/work_item/{work_item_type}/query").mock(
        return_value=httpx.Response(200, json={"err_code": 0, "data": [item]})
    )


def _mock_work_item_with_history(
    state_key: str,
    updated_at_ms: int,
    history: list[dict],
) -> None:
    """mock 工作项端点，带顶层 updated_at（业务时间，§16）+ work_item_status.history[]。"""
    item = {
        "id": STORY_ID,
        "name": "实现学习平台 A",
        "updated_at": updated_at_ms,
        "fields": [],
        "work_item_status": {
            "state_key": state_key,
            "current_nodes": [{"id": "state_2", "name": "Sprint计划"}],
            "history": history,
        },
    }
    respx.post(f"{API_BASE}/open_api/{PROJECT_KEY}/work_item/story/query").mock(
        return_value=httpx.Response(200, json={"err_code": 0, "data": [item]})
    )


def _identity(work_item_type: str = "story", work_item_id: int = STORY_ID):
    from delivery.services import WorkItemIdentity

    return WorkItemIdentity(
        feishu_project_key=PROJECT_KEY,
        work_item_type=work_item_type,
        work_item_id=work_item_id,
    )


# ============================================================================
# Task 2：upsert 核心 —— 幂等收敛 + mirror-only + facet SyncState
# ============================================================================


@respx.mock
async def test_upsert_idempotent_same_triple_multi_origin() -> None:
    """WIT-01：同三元组连续 upsert（不同 origin）→ 唯一行，origin 保持首次值。"""
    from delivery.models import WorkItem
    from delivery.services import WorkItemService

    await _make_project()
    _mock_token()
    _mock_work_item()

    service = WorkItemService()
    await service.upsert(_identity(), source="manual")
    await service.upsert(_identity(), source="feishu_webhook")

    assert await WorkItem.objects.acount() == 1
    wi = await WorkItem.objects.aget(work_item_id=STORY_ID)
    assert wi.origin == "manual"  # 首次创建的 origin 不被后续覆盖


@respx.mock
async def test_upsert_mirror_only_protects_enhanced() -> None:
    """WIT-02：mirror 刷新只动 mirror 字段，friday_enhanced 被保护。"""
    from asgiref.sync import sync_to_async

    from delivery.models import WorkItem, WorkItemOrigin
    from delivery.services import WorkItemService

    await _make_project()

    # 预置：库内已有该 WorkItem，带 enhanced 字段 + 旧 title
    await WorkItem.objects.acreate(
        feishu_project_key=PROJECT_KEY,
        work_item_type="story",
        work_item_id=STORY_ID,
        origin=WorkItemOrigin.MANUAL,
        title="旧标题",
        internal_note="x",
        business_line_normalized="L",
    )

    _mock_token()
    _mock_work_item(name="新标题")

    await WorkItemService().upsert(_identity(), source="feishu_webhook")

    wi = await WorkItem.objects.aget(work_item_id=STORY_ID)
    assert wi.title == "新标题"  # mirror 被刷新
    assert wi.internal_note == "x"  # enhanced 原样保留
    assert wi.business_line_normalized == "L"
    assert wi.origin == WorkItemOrigin.MANUAL  # origin 不被覆盖
    # 显式断言 sync_to_async 路径无副作用残留
    assert await sync_to_async(lambda: wi.status_display_name)() == "Sprint计划"


@respx.mock
async def test_upsert_fetch_failure_records_facet_missing_no_rollback() -> None:
    """WIT-03：回源失败 → basic_fields facet=missing/error，WorkItem 不整体回滚。"""
    from delivery.models import SyncFacet, SyncStatus, WorkItem, WorkItemSyncState
    from delivery.services import WorkItemService

    await _make_project()
    _mock_token()
    # 回源返回非 JSON → get_work_item 抛 FeishuResponseError
    respx.post(f"{API_BASE}/open_api/{PROJECT_KEY}/work_item/story/query").mock(
        return_value=httpx.Response(
            200, text="<html>502</html>", headers={"content-type": "text/html"}
        )
    )

    wi = await WorkItemService().upsert(_identity(), source="feishu_webhook")

    # WorkItem 行仍存在（已 get_or_create）
    assert await WorkItem.objects.filter(work_item_id=STORY_ID).aexists()
    state = await WorkItemSyncState.objects.aget(work_item=wi, facet=SyncFacet.BASIC_FIELDS)
    assert state.status == SyncStatus.MISSING
    assert state.error  # error 文本非空
    # 凭证不入 error
    assert "plugin_token_xyz" not in state.error
    assert "plugin_test_secret" not in state.error


@respx.mock
async def test_upsert_success_records_sync_state_and_provenance() -> None:
    """成功回源 → basic_fields=complete、last_synced_at、field_provenance 写入。"""
    from delivery.models import SyncFacet, SyncStatus, WorkItemSyncState
    from delivery.services import WorkItemService

    await _make_project()
    _mock_token()
    _mock_work_item()

    wi = await WorkItemService().upsert(_identity(), source="manual")

    assert wi.last_synced_at is not None
    assert wi.prd_url == "https://tenant.feishu.cn/docx/doc_token_prd"
    assert wi.field_provenance.get("title") == "manual"
    assert wi.field_provenance.get("status_state_key") == "manual"
    # enhanced 字段不入 provenance
    assert "internal_note" not in wi.field_provenance

    state = await WorkItemSyncState.objects.aget(work_item=wi, facet=SyncFacet.BASIC_FIELDS)
    assert state.status == SyncStatus.COMPLETE
    assert state.last_synced_at is not None


@respx.mock
async def test_upsert_project_unconfigured_records_missing() -> None:
    """project 未配置 → 仍建 WorkItem，basic_fields=missing + error，不抛。"""
    from delivery.models import SyncFacet, SyncStatus, WorkItem, WorkItemSyncState
    from delivery.services import WorkItemService

    # 不创建 Space
    wi = await WorkItemService().upsert(_identity(), source="manual")

    assert await WorkItem.objects.filter(work_item_id=STORY_ID).aexists()
    state = await WorkItemSyncState.objects.aget(work_item=wi, facet=SyncFacet.BASIC_FIELDS)
    assert state.status == SyncStatus.MISSING
    assert "project" in state.error


# ============================================================================
# Task 3：关系派生持久化（占位/回填）+ 状态事件 append + relations facet
# ============================================================================


@respx.mock
async def test_upsert_derives_relation_with_external_id_placeholder() -> None:
    """WIT-04：field_000008=[id]（target 未落库）→ belongs_to_project + target_external_id 占位。"""
    from delivery.models import RelationType, WorkItemRelation
    from delivery.services import WorkItemService

    await _make_project()
    _mock_token()
    _mock_work_item()

    wi = await WorkItemService().upsert(_identity(), source="manual")

    rel = await WorkItemRelation.objects.aget(source_work_item=wi)
    assert rel.relation_type == RelationType.BELONGS_TO_PROJECT
    assert rel.target_external_id == TARGET_PROJECT_ID
    assert rel.target_work_item_id is None  # target 未落库 → 占位
    assert rel.source_field_key == "field_000008"


@respx.mock
async def test_upsert_backfills_target_work_item() -> None:
    """WIT-04 回填：先 upsert source 产占位，再 upsert id=target → 占位关系回填 target_work_item。"""
    from delivery.models import WorkItem, WorkItemRelation
    from delivery.services import WorkItemService

    await _make_project()
    _mock_token()

    # source 与 target 同 type=story → 同一 query URL，按请求 work_item_ids 分发响应
    def _dispatch(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        wid = body["work_item_ids"][0]
        if wid == TARGET_PROJECT_ID:
            item = {
                "id": TARGET_PROJECT_ID,
                "name": "所属项目容器",
                "fields": [],
                "work_item_status": {"state_key": "open"},
            }
        else:
            item = {
                "id": STORY_ID,
                "name": "实现学习平台 A",
                "fields": _STORY_FIELDS,
                "work_item_status": {"state_key": "fi46o4r6m"},
            }
        return httpx.Response(200, json={"err_code": 0, "data": [item]})

    respx.post(f"{API_BASE}/open_api/{PROJECT_KEY}/work_item/story/query").mock(
        side_effect=_dispatch
    )

    service = WorkItemService()
    source_wi = await service.upsert(_identity(), source="manual")
    rel = await WorkItemRelation.objects.aget(source_work_item=source_wi)
    assert rel.target_work_item_id is None  # 尚未落库

    # upsert target（id=TARGET_PROJECT_ID）→ 回填占位
    target_wi = await service.upsert(_identity(work_item_id=TARGET_PROJECT_ID), source="manual")
    assert target_wi.work_item_id == TARGET_PROJECT_ID

    rel = await WorkItemRelation.objects.aget(source_work_item=source_wi)
    assert rel.target_work_item_id == target_wi.id
    assert await WorkItem.objects.acount() == 2


@respx.mock
async def test_upsert_relation_idempotent_no_duplicate() -> None:
    """重复 upsert 不产生重复 Relation（unique_together 走 update_or_create）。"""
    from delivery.models import WorkItemRelation
    from delivery.services import WorkItemService

    await _make_project()
    _mock_token()
    _mock_work_item()

    service = WorkItemService()
    wi = await service.upsert(_identity(), source="manual")
    await service.upsert(_identity(), source="feishu_webhook")

    assert await WorkItemRelation.objects.filter(source_work_item=wi).acount() == 1


@respx.mock
async def test_upsert_relations_facet_complete() -> None:
    """relations facet 派生成功后记 complete。"""
    from delivery.models import SyncFacet, SyncStatus, WorkItemSyncState
    from delivery.services import WorkItemService

    await _make_project()
    _mock_token()
    _mock_work_item()

    wi = await WorkItemService().upsert(_identity(), source="manual")

    state = await WorkItemSyncState.objects.aget(work_item=wi, facet=SyncFacet.RELATIONS)
    assert state.status == SyncStatus.COMPLETE


@respx.mock
async def test_upsert_status_change_appends_status_event() -> None:
    """WIT-05：状态变更 append StatusEvent(pre/cur)，非就地改写；无变更不重复 append。"""
    from delivery.models import WorkItemStatusEvent
    from delivery.services import WorkItemService

    await _make_project()
    _mock_token()

    service = WorkItemService()

    # 首次 upsert：state="A"（pre="" → cur="A"，append 1 条）
    _mock_work_item(state_key="A")
    wi = await service.upsert(_identity(), source="manual")
    assert wi.status_state_key == "A"
    assert await WorkItemStatusEvent.objects.filter(work_item=wi).acount() == 1

    # 第二次 upsert：state="B"（pre="A" → cur="B"，新增 1 条）
    respx.routes.clear()
    _mock_token()
    _mock_work_item(state_key="B")
    wi = await service.upsert(_identity(), source="feishu_webhook")
    assert wi.status_state_key == "B"  # mirror 更新为 B
    events = [
        e async for e in WorkItemStatusEvent.objects.filter(work_item=wi).order_by("ingested_at")
    ]
    assert len(events) == 2
    assert events[1].pre_state_key == "A"
    assert events[1].cur_state_key == "B"

    # 第三次 upsert：state 仍="B"（无变更，不 append）
    respx.routes.clear()
    _mock_token()
    _mock_work_item(state_key="B")
    await service.upsert(_identity(), source="feishu_webhook")
    assert await WorkItemStatusEvent.objects.filter(work_item=wi).acount() == 2


@respx.mock
async def test_upsert_status_event_uses_payload_time_and_dedups_history() -> None:
    """WR-03：实时状态事件取 payload 业务时间（非 now()），与 history 回填同源去重。

    - 同态重复 upsert 不重复 append（实时合成事件 event_time 与 history 条目同戳 → 去重命中）。
    - 真实状态变更恰好新增 1 条事件，event_time 为 payload 派生的真实转移时间。
    """
    from datetime import UTC, datetime

    from delivery.models import WorkItemStatusEvent
    from delivery.services import WorkItemService

    event_ms_a = 1700000000000
    event_ms_b = 1700000600000
    event_dt_a = datetime.fromtimestamp(event_ms_a / 1000, tz=UTC)
    event_dt_b = datetime.fromtimestamp(event_ms_b / 1000, tz=UTC)

    await _make_project()
    service = WorkItemService()

    # 首次：state="A"，history 含同态同戳条目 → 实时合成 + 历史回填收敛为 1 条
    _mock_token()
    _mock_work_item_with_history(
        "A", event_ms_a, [{"state_key": "A", "updated_at": event_ms_a, "updated_by": "u1"}]
    )
    wi = await service.upsert(_identity(), source="manual")

    events = [e async for e in WorkItemStatusEvent.objects.filter(work_item=wi)]
    assert len(events) == 1
    assert events[0].cur_state_key == "A"
    assert events[0].event_time == event_dt_a  # payload 业务时间，非 timezone.now()

    # 同态重复 upsert（payload 不变）→ 无重复事件
    respx.routes.clear()
    _mock_token()
    _mock_work_item_with_history(
        "A", event_ms_a, [{"state_key": "A", "updated_at": event_ms_a, "updated_by": "u1"}]
    )
    await service.upsert(_identity(), source="feishu_webhook")
    assert await WorkItemStatusEvent.objects.filter(work_item=wi).acount() == 1

    # 真实状态变更 A→B → 恰好新增 1 条，event_time = payload 派生真实转移时间
    respx.routes.clear()
    _mock_token()
    _mock_work_item_with_history(
        "B",
        event_ms_b,
        [
            {"state_key": "A", "updated_at": event_ms_a, "updated_by": "u1"},
            {"state_key": "B", "updated_at": event_ms_b, "updated_by": "u2"},
        ],
    )
    wi = await service.upsert(_identity(), source="feishu_webhook")
    assert wi.status_state_key == "B"

    events = [
        e
        async for e in WorkItemStatusEvent.objects.filter(work_item=wi).order_by("event_time")
    ]
    assert len(events) == 2
    b_event = next(e for e in events if e.cur_state_key == "B")
    assert b_event.pre_state_key == "A"
    assert b_event.event_time == event_dt_b
