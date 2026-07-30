"""``RepositoryRoutingTrace`` 模型字段、枚举、cascade、
migration 与默认值断言。

测试范围（≥ 8 条）：
1. 枚举 3 态值
2. 字段类型 / 默认值（7 字段）
3. 行为与 cascade（最小创建 / 完整 candidates / 删 conversation 级联）
4. Meta + migration（ordering / indexes / makemigrations clean / 双 app dep）
5. 降级/分组两列（107-08）：默认值、列长形状约束、迁移 additive
6. 会话 detail 的 ``routing_trace`` payload 契约（9 键 + 后端唯一派生 degraded）
"""

from __future__ import annotations

import uuid
from io import StringIO

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management import call_command

from agents.models import AgentSession
from chat.models import Conversation, RepositoryRoutingTrace
from projects.models import Space


pytestmark = pytest.mark.django_db


@pytest.fixture
def project(db):
    return Space.objects.create(
        name=f"trace-test-{uuid.uuid4().hex[:6]}",
        feishu_project_key=f"k-{uuid.uuid4().hex[:6]}",
    )


@pytest.fixture
def conversation(db, project):
    return Conversation.objects.create(space=project, title="trace-conv")


@pytest.fixture
def agent_session(db):
    return AgentSession.objects.create(session_id=f"as-{uuid.uuid4().hex[:8]}")


@pytest.fixture
def sample_candidate():
    return {
        "repository_id": str(uuid.uuid4()),
        "repository_name": "example-app",
        "score": 0.92,
        "level": "high",
        "evidence": "命中 3 个相关文件：a.py / b.py / c.py",
        "selected_by_ai": True,
        "selected_by_user_final": True,
    }


# ---------------------------------------------------------------------------
# 1. 枚举 3 态
# ---------------------------------------------------------------------------


def test_triggered_by_enum_values():
    """三个枚举字面值与 REQUIREMENTS work item 完全对齐；禁止裸 'manual'。"""
    values = set(RepositoryRoutingTrace.TriggeredBy.values)
    assert values == {
        "chat_tool",
        "deep_analysis_completion",
        "manual_override",
    }
    # 防御回归：不要引入 "manual" 简写
    assert "manual" not in values


# ---------------------------------------------------------------------------
# 2. 字段类型 / 默认值
# ---------------------------------------------------------------------------


def test_field_definitions():
    """7 字段类型 / 默认值 / FK on_delete / related_name 锁定。"""
    fields = {f.name: f for f in RepositoryRoutingTrace._meta.get_fields()}

    assert fields["id"].primary_key  # type: ignore[union-attr]
    assert fields["id"].__class__.__name__ == "UUIDField"

    agent_fk = fields["agent_session"]
    assert agent_fk.__class__.__name__ == "ForeignKey"
    assert agent_fk.null is True  # type: ignore[union-attr]
    assert agent_fk.blank is True  # type: ignore[union-attr]
    assert agent_fk.remote_field.on_delete.__name__ == "CASCADE"  # type: ignore[union-attr]
    assert agent_fk.remote_field.related_name == "routing_traces"  # type: ignore[union-attr]

    conv_fk = fields["conversation"]
    assert conv_fk.__class__.__name__ == "ForeignKey"
    assert conv_fk.null is False  # type: ignore[union-attr]
    assert conv_fk.remote_field.on_delete.__name__ == "CASCADE"  # type: ignore[union-attr]
    assert conv_fk.remote_field.related_name == "routing_traces"  # type: ignore[union-attr]

    assert fields["query"].__class__.__name__ == "TextField"
    assert fields["candidates"].__class__.__name__ == "JSONField"
    assert fields["candidates"].default is list  # type: ignore[union-attr]
    assert fields["threshold"].__class__.__name__ == "FloatField"
    assert fields["threshold"].default == 0.5  # type: ignore[union-attr]

    trigger = fields["triggered_by"]
    assert trigger.__class__.__name__ == "CharField"
    assert trigger.max_length == 32  # type: ignore[union-attr]

    created_at = fields["created_at"]
    assert created_at.__class__.__name__ == "DateTimeField"
    assert created_at.auto_now_add is True  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# 3. 行为与 cascade
# ---------------------------------------------------------------------------


def test_create_trace_minimal(conversation):
    """最小创建路径：仅 conversation / query / triggered_by。"""
    trace = RepositoryRoutingTrace.objects.create(
        conversation=conversation,
        query="找跟书房相关的代码",
        triggered_by=RepositoryRoutingTrace.TriggeredBy.CHAT_TOOL,
    )
    trace.refresh_from_db()
    assert trace.candidates == []
    assert trace.threshold == 0.5
    assert trace.agent_session is None
    assert trace.id is not None


def test_create_trace_with_candidates(conversation, sample_candidate):
    trace = RepositoryRoutingTrace.objects.create(
        conversation=conversation,
        query="cross repo query",
        candidates=[sample_candidate],
        threshold=0.3,
        triggered_by=RepositoryRoutingTrace.TriggeredBy.DEEP_ANALYSIS_COMPLETION,
    )
    trace.refresh_from_db()
    assert len(trace.candidates) == 1
    cand = trace.candidates[0]
    for key in (
        "repository_id",
        "repository_name",
        "score",
        "level",
        "evidence",
        "selected_by_ai",
        "selected_by_user_final",
    ):
        assert key in cand
    assert trace.threshold == 0.3


def test_cascade_delete_on_conversation(conversation):
    trace = RepositoryRoutingTrace.objects.create(
        conversation=conversation,
        query="will be cascaded",
        triggered_by=RepositoryRoutingTrace.TriggeredBy.CHAT_TOOL,
    )
    trace_id = trace.id
    conversation.delete()
    assert not RepositoryRoutingTrace.objects.filter(id=trace_id).exists()


def test_cascade_delete_on_agent_session(conversation, agent_session):
    """agent_session CASCADE 删除：trace 同时被删（符合 must_have 锁定的 CASCADE 语义）。"""
    trace = RepositoryRoutingTrace.objects.create(
        conversation=conversation,
        query="agent cascade",
        agent_session=agent_session,
        triggered_by=RepositoryRoutingTrace.TriggeredBy.DEEP_ANALYSIS_COMPLETION,
    )
    trace_id = trace.id
    agent_session.delete()
    assert not RepositoryRoutingTrace.objects.filter(id=trace_id).exists()


# ---------------------------------------------------------------------------
# 4. Meta + migration
# ---------------------------------------------------------------------------


def test_meta_ordering():
    assert RepositoryRoutingTrace._meta.ordering == ["-created_at"]


def test_meta_indexes_present():
    names = {idx.name for idx in RepositoryRoutingTrace._meta.indexes}
    assert {
        "routing_trace_conv_idx",
        "routing_trace_session_idx",
        "routing_trace_trigger_idx",
    } <= names


def test_migration_makemigrations_clean():
    """makemigrations --check --dry-run 必须 exit 0（即无字段漂移）。"""
    out = StringIO()
    try:
        call_command("makemigrations", "--check", "--dry-run", stdout=out)
    except SystemExit as exc:
        pytest.fail(
            f"makemigrations detected drift (exit {exc.code}): {out.getvalue()}"
        )


def test_migration_dependencies_dual_app():
    """0014 migration 必须同时依赖 chat 0013 + agents 0003（跨 app FK）。"""
    import importlib

    module = importlib.import_module("chat.migrations.0014_repository_routing_trace")
    deps = set(module.Migration.dependencies)
    assert ("chat", "0013_codingsession_unique_active_plan_repo") in deps
    assert ("agents", "0003_nullable_session_project_user") in deps


# ---------------------------------------------------------------------------
# 5. 降级原因 / 区顺序两列（107-08 Task 1）
# ---------------------------------------------------------------------------


def test_degrade_reason_and_block_order_default_to_empty(conversation):
    """两列不传 → 取列默认值（"" / []），与迁移前的历史行等价、无需回填。"""
    trace = RepositoryRoutingTrace.objects.create(
        conversation=conversation,
        query="默认值",
        triggered_by=RepositoryRoutingTrace.TriggeredBy.CHAT_TOOL,
    )
    trace.refresh_from_db()
    assert trace.degrade_reason == ""
    assert trace.block_order == []


def test_degrade_reason_column_shape_constraints():
    """列长 32 与 JSON 默认工厂锁定：degrade_reason 结构上装不下上游异常原文。"""
    fields = {f.name: f for f in RepositoryRoutingTrace._meta.get_fields()}

    degrade = fields["degrade_reason"]
    assert degrade.__class__.__name__ == "CharField"
    assert degrade.max_length == 32  # type: ignore[union-attr]
    assert degrade.blank is True  # type: ignore[union-attr]
    assert degrade.default == ""  # type: ignore[union-attr]

    block = fields["block_order"]
    assert block.__class__.__name__ == "JSONField"
    assert block.default is list  # type: ignore[union-attr]
    assert block.blank is True  # type: ignore[union-attr]


def test_degrade_reason_rejects_overlong_value(conversation):
    """超过 32 字符（异常原文的典型长度）→ 校验层拒绝。"""
    trace = RepositoryRoutingTrace(
        conversation=conversation,
        query="超长",
        triggered_by=RepositoryRoutingTrace.TriggeredBy.CHAT_TOOL,
        degrade_reason="ConnectionResetError: peer closed the connection",
    )
    with pytest.raises(DjangoValidationError):
        trace.full_clean()


def test_degrade_reason_and_block_order_round_trip(conversation):
    """受控枚举值 + 长度 2 的区顺序写入读取后逐字不变。"""
    trace = RepositoryRoutingTrace.objects.create(
        conversation=conversation,
        query="round trip",
        triggered_by=RepositoryRoutingTrace.TriggeredBy.CHAT_TOOL,
        router_version="v2_stage0_only",
        degrade_reason="timeout",
        block_order=["global", "in_project"],
    )
    trace.refresh_from_db()
    assert trace.degrade_reason == "timeout"
    assert trace.block_order == ["global", "in_project"]


def test_migration_0032_is_additive_and_reversible():
    """两列迁移 additive：仅 AddField、无数据迁移、可逆、依赖指向 0031。"""
    import importlib

    module = importlib.import_module(
        "chat.migrations.0032_repositoryroutingtrace_degrade_reason"
    )
    ops = module.Migration.operations
    assert [type(op).__name__ for op in ops] == ["AddField", "AddField"]
    assert {op.name for op in ops} == {"degrade_reason", "block_order"}
    assert all(op.reversible for op in ops), "AddField 必须可逆（零回填的前提）"
    assert ("chat", "0031_remove_codingplan_canonical_plan_id") in set(
        module.Migration.dependencies
    )


# ---------------------------------------------------------------------------
# 6. 会话 detail 的 routing_trace payload 契约（107-08 Task 2）
#
# 全部经**真实 detail endpoint** 请求断言：直接调函数验不出「刷新页面后降级提示
# 消失」这条 —— 那条缺陷的现场就在 payload 组装处（107-RESEARCH §2 第 3 条）。
# ---------------------------------------------------------------------------

_DETAIL_PAYLOAD_KEYS = {
    "trace_id",
    "query",
    "candidates",
    "threshold",
    "triggered_by",
    "router_version",
    "degraded",
    "degrade_reason",
    "block_order",
}


def _detail_routing_trace(conversation):
    """GET 会话 detail，返回 routing_trace 子 payload（无 trace 时为 None）。"""
    from rest_framework.test import APIClient

    resp = APIClient().get(f"/api/chat/conversations/{conversation.id}/")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert "routing_trace" in body, body
    return body["routing_trace"]


def _make_trace(conversation, **kwargs):
    return RepositoryRoutingTrace.objects.create(
        conversation=conversation,
        query=kwargs.pop("query", "detail payload query"),
        triggered_by=RepositoryRoutingTrace.TriggeredBy.CHAT_TOOL,
        **kwargs,
    )


def test_detail_payload_exposes_degraded_facts_for_stage0_only(conversation):
    """v2_stage0_only + timeout → degraded True 且原因与版本原样出 API 边界。"""
    _make_trace(
        conversation,
        router_version="v2_stage0_only",
        degrade_reason="timeout",
        block_order=["global", "in_project"],
    )
    payload = _detail_routing_trace(conversation)
    assert payload["router_version"] == "v2_stage0_only"
    assert payload["degraded"] is True
    assert payload["degrade_reason"] == "timeout"


def test_detail_payload_v1_fallback_is_degraded(conversation):
    """v1_fallback 同属降级（与 v2_stage0_only 同一闭集）。"""
    _make_trace(conversation, router_version="v1_fallback")
    assert _detail_routing_trace(conversation)["degraded"] is True


def test_detail_payload_v2_is_not_degraded(conversation):
    """v2（Stage 1 正常参与）→ degraded False、无原因。"""
    _make_trace(conversation, router_version="v2")
    payload = _detail_routing_trace(conversation)
    assert payload["degraded"] is False
    assert payload["degrade_reason"] == ""


def test_detail_payload_legacy_hybrid_is_not_degraded(conversation):
    """legacy_hybrid（router_version 的列默认值）**不算**降级。

    算作降级会让全部历史 trace 突然出现降级横幅（UI-SPEC backstop 1 的历史兼容要求）。
    """
    trace = _make_trace(conversation)
    assert trace.router_version == "legacy_hybrid"
    assert _detail_routing_trace(conversation)["degraded"] is False


def test_detail_payload_passes_block_order_through(conversation):
    """block_order 原样输出（前端按 length === 2 判定是否启用分组呈现）。"""
    _make_trace(conversation, block_order=["global", "in_project"])
    assert _detail_routing_trace(conversation)["block_order"] == [
        "global",
        "in_project",
    ]


def test_detail_payload_empty_block_order_stays_empty_list(conversation):
    """无分组上下文（列默认值）→ 输出 []，前端走平铺。"""
    _make_trace(conversation)
    assert _detail_routing_trace(conversation)["block_order"] == []


def test_detail_payload_key_set_is_exactly_nine(conversation):
    """键集合恰 9 键（5 既有 + 4 新增）——精确集合断言，防将来漏键或悄悄加键。"""
    _make_trace(conversation, router_version="v2", block_order=["in_project", "global"])
    assert set(_detail_routing_trace(conversation)) == _DETAIL_PAYLOAD_KEYS


def test_detail_payload_is_none_without_trace(conversation):
    """无 trace 的会话 → routing_trace 为 None（行为不变）。"""
    assert _detail_routing_trace(conversation) is None


def test_candidate_json_schema_round_trip(conversation, sample_candidate):
    """JSON candidates 写入读取后字段保持齐全（防 Django JSONField 兼容回退）。"""
    trace = RepositoryRoutingTrace.objects.create(
        conversation=conversation,
        query="schema",
        candidates=[sample_candidate, {**sample_candidate, "level": "medium", "score": 0.55}],
        triggered_by=RepositoryRoutingTrace.TriggeredBy.MANUAL_OVERRIDE,
    )
    trace.refresh_from_db()
    assert isinstance(trace.candidates, list)
    assert len(trace.candidates) == 2
    assert trace.candidates[0]["level"] == "high"
    assert trace.candidates[1]["level"] == "medium"
