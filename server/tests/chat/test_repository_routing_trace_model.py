"""``RepositoryRoutingTrace`` 模型字段、枚举、cascade、
migration 与默认值断言。

测试范围（≥ 8 条）：
1. 枚举 3 态值
2. 字段类型 / 默认值（7 字段）
3. 行为与 cascade（最小创建 / 完整 candidates / 删 conversation 级联）
4. Meta + migration（ordering / indexes / makemigrations clean / 双 app dep）
"""

from __future__ import annotations

import uuid
from io import StringIO

import pytest
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
