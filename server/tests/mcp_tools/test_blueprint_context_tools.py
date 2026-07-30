"""Blueprint Context Bus 容器 MCP 工具守护测试（BUS-01，Phase 113-02）。

覆盖：
- 写读闭环：一个容器 report → 同会话另一个容器 read 即刻可见（写入即对并行容器可见）；
- 增量拉取：since_seq 只返回新增条目且 max_seq 单调；
- ⭐ 三道会话校验各一条负向断言（跨会话越权的唯一防线）：
  ① 归属——session 属于另一个 User → 403 session_not_owned，DB 零新增；
  ①b fail-closed——main_session.user 为 None（老会话/未赋值派发）→ 同样 403 session_not_owned；
  ② 流程——关联 ConvergenceSession.process_type != technical_blueprint → 403 not_blueprint_session；
  ③ 成员——令牌所有者不是会话所绑项目成员 → 403 not_member；
  另加缺 header → 404 missing_session_header、header 指向不存在 session → 404 session_not_found；
- ⭐ 跨会话读隔离：A 会话写 2 条、B 会话写 1 条，用 B 的 header 读只拿到 B 的 1 条；
- 脱敏结构保真：content 里的 PAT/密钥入库后不可见，且 JSON 结构与非字符串叶子未塌；
- ⭐ 绝不 5xx：service 抛异常 → 200 + applied=false；未知工具路径 → 404 而非 500；
- 入参非法：kind 非枚举 / content 非 object → 400 invalid_params 且 DB 零新增；
- waiter 顺带满足：report 命中等待 key → satisfied_waiters==1 且该 waiter 行置 superseded；
- 观测留痕：ToolCallRecord + RequestMetric.labels['call_source'] 落到两个新工具名，
  且留痕里不含 content 正文。
"""

from __future__ import annotations

import json
import uuid

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from agents.models import AgentSession
from chat.models import Conversation
from delivery.models import (
    BlueprintContextEntry,
    ContextEntryStatus,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
)
from delivery.services.blueprint_context_service import BlueprintContextService
from initiatives.services import ProjectService
from interactions.models import ToolCallRecord
from projects.models import Space
from subagent.models import SubAgentSession
from system.metric_sink import flush_now
from system.models import RequestMetric

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()

# 真打 URL：端到端过认证 + serializer + view（与 urls.py 逐字一致）。
_READ_URL = "/api/mcp/tools/read_blueprint_context/"
_REPORT_URL = "/api/mcp/tools/report_blueprint_context/"


# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------


async def _make_blueprint_session(
    *, process_type: str = "technical_blueprint", conversation_id=None
) -> ConvergenceSession:
    return await ConvergenceSession.objects.acreate(
        process_type=process_type,
        entrypoint=ConvergenceSessionEntrypoint.WORKFLOW,
        current_stage="repo_plan",
        conversation_id=conversation_id,
    )


async def _make_subagent_session(
    blueprint_session: ConvergenceSession,
    *,
    owner=None,
    repository_id: str = "",
    with_blueprint_link: bool = True,
) -> SubAgentSession:
    """造一条派发链上的容器会话。

    ⭐ ``owner`` 就是归属校验（道①）的唯一数据来源：写进 ``AgentSession.user``。
    传 None 即模拟「老会话 / 派发未赋值」，用于 fail-closed 断言。
    """
    sid = f"bp-research-{uuid.uuid4().hex[:12]}"
    agent_session = await AgentSession.objects.acreate(
        session_id=f"agent-{sid}",
        status=AgentSession.Status.RUNNING,
        user=owner,
        metadata={"source": "blueprint_repo_research"},
    )
    last_output = {"source": "blueprint_repo_research", "repository_id": repository_id}
    if with_blueprint_link:
        last_output["blueprint_session_id"] = str(blueprint_session.id)
    return await SubAgentSession.objects.acreate(
        session_id=sid,
        main_session=agent_session,
        repo_url="https://example.com/x.git",
        task_type=SubAgentSession.TaskType.PLAN,
        status=SubAgentSession.Status.RUNNING,
        last_output=last_output,
    )


async def _make_project(created_by, key: str, *, visibility: str = ""):
    """建项目；``visibility`` 缺省沿用模型默认（``public_org``）。

    ⚠️ ``Project.visibility`` 默认就是 ``public_org``（全员可读），成员闸对它天然放行
    （与 packer 口径一致）。要断言 ``not_member`` 必须显式设 ``members_only``。
    """
    space = await sync_to_async(Space.objects.create)(name="S", feishu_project_key=f"{key}-sp")
    project, _ = await ProjectService().create(
        space=space, name="P", feishu_project_key=key, created_by=created_by
    )
    if visibility:
        project.visibility = visibility
        await sync_to_async(project.save)(update_fields=["visibility"])
    return project


# ---------------------------------------------------------------------------
# 独立查询 helper（断言从 DB 重读，不信响应体）
# ---------------------------------------------------------------------------


@sync_to_async
def _entry_count(session_id) -> int:
    return BlueprintContextEntry.objects.filter(convergence_session_id=session_id).count()


@sync_to_async
def _entries(session_id) -> list[BlueprintContextEntry]:
    return list(
        BlueprintContextEntry.objects.filter(convergence_session_id=session_id).order_by("seq")
    )


@sync_to_async
def _entry_status(entry_id) -> str:
    row = BlueprintContextEntry.objects.filter(id=entry_id).first()
    return getattr(row, "status", "")


def _headers(sub: SubAgentSession) -> dict:
    return {"HTTP_X_FRIDAY_SESSION_ID": sub.session_id}


def _report_payload(**overrides) -> dict:
    payload = {
        "key": "repo:alpha.api_surface",
        "kind": "api_surface",
        "repository_id": "alpha",
        "content": {"endpoint": "/api/x", "method": "GET"},
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# 1. 写读闭环 / 增量
# ---------------------------------------------------------------------------


async def test_report_then_read_visible_to_parallel_container(mcp_client, access_user) -> None:
    """一个容器 report → 同会话**另一个** SubAgentSession 的容器 read 即刻可见。"""
    client, _ = mcp_client
    cs = await _make_blueprint_session()
    writer = await _make_subagent_session(cs, owner=access_user, repository_id="alpha")
    reader = await _make_subagent_session(cs, owner=access_user, repository_id="beta")

    resp = await sync_to_async(client.post)(
        _REPORT_URL, _report_payload(), format="json", **_headers(writer)
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["applied"] is True
    assert body["seq"] == 1
    assert body["satisfied_waiters"] == 0

    read = await sync_to_async(client.post)(_READ_URL, {}, format="json", **_headers(reader))
    assert read.status_code == 200
    read_body = read.json()
    assert read_body["count"] == 1
    assert read_body["max_seq"] == 1
    assert read_body["entries"][0]["key"] == "repo:alpha.api_surface"
    assert read_body["entries"][0]["content"]["endpoint"] == "/api/x"


async def test_incremental_read_since_seq(mcp_client, access_user) -> None:
    """写 3 条 → read(since_seq=1) 只返回 seq 2/3 且 max_seq==3。"""
    client, _ = mcp_client
    cs = await _make_blueprint_session()
    sub = await _make_subagent_session(cs, owner=access_user)

    for i in range(3):
        resp = await sync_to_async(client.post)(
            _REPORT_URL,
            _report_payload(key=f"contract:c{i}", kind="contract"),
            format="json",
            **_headers(sub),
        )
        assert resp.status_code == 200

    read = await sync_to_async(client.post)(
        _READ_URL, {"since_seq": 1}, format="json", **_headers(sub)
    )
    assert read.status_code == 200
    body = read.json()
    assert [e["seq"] for e in body["entries"]] == [2, 3]
    assert body["count"] == 2
    assert body["max_seq"] == 3


# ---------------------------------------------------------------------------
# 2. ⭐ 三道会话校验负向
# ---------------------------------------------------------------------------


async def test_session_owned_by_other_user_rejected(mcp_client, access_user) -> None:
    """① 归属：session 的 main_session.user 是另一个 User → 403 session_not_owned。"""
    client, _ = mcp_client
    other = await sync_to_async(User.objects.create_user)(username="bpc-other", password="x")
    cs = await _make_blueprint_session()
    sub = await _make_subagent_session(cs, owner=other)

    resp = await sync_to_async(client.post)(
        _REPORT_URL, _report_payload(), format="json", **_headers(sub)
    )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "session_not_owned"
    assert await _entry_count(cs.id) == 0

    read = await sync_to_async(client.post)(_READ_URL, {}, format="json", **_headers(sub))
    assert read.status_code == 403
    assert read.json()["error_code"] == "session_not_owned"


async def test_null_session_user_fail_closed(mcp_client, access_user) -> None:
    """①b fail-closed：main_session.user 为 None → 同样 403 session_not_owned。

    「字段为空」绝不等于放行——否则跨会话越权的唯一防线形同不存在。
    """
    client, _ = mcp_client
    cs = await _make_blueprint_session()
    sub = await _make_subagent_session(cs, owner=None)

    resp = await sync_to_async(client.post)(
        _REPORT_URL, _report_payload(), format="json", **_headers(sub)
    )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "session_not_owned"
    assert await _entry_count(cs.id) == 0


async def test_non_blueprint_process_rejected(mcp_client, access_user) -> None:
    """② 流程：关联会话 process_type=technical_plan → 403 not_blueprint_session。"""
    client, _ = mcp_client
    cs = await _make_blueprint_session(process_type="technical_plan")
    sub = await _make_subagent_session(cs, owner=access_user)

    resp = await sync_to_async(client.post)(
        _REPORT_URL, _report_payload(), format="json", **_headers(sub)
    )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "not_blueprint_session"
    assert await _entry_count(cs.id) == 0


async def test_missing_blueprint_link_rejected(mcp_client, access_user) -> None:
    """② 流程：last_output 无 blueprint_session_id → 403 not_blueprint_session。"""
    client, _ = mcp_client
    cs = await _make_blueprint_session()
    sub = await _make_subagent_session(cs, owner=access_user, with_blueprint_link=False)

    resp = await sync_to_async(client.post)(
        _REPORT_URL, _report_payload(), format="json", **_headers(sub)
    )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "not_blueprint_session"
    assert await _entry_count(cs.id) == 0


async def test_non_member_rejected(mcp_client, access_user) -> None:
    """③ 成员：会话绑定的 members_only 项目里令牌所有者非成员 → 403 not_member。"""
    from initiatives.models import ProjectVisibility

    client, _ = mcp_client
    stranger = await sync_to_async(User.objects.create_user)(username="bpc-owner", password="x")
    project = await _make_project(stranger, key="bpc-nm", visibility=ProjectVisibility.MEMBERS_ONLY)
    conversation = await sync_to_async(Conversation.objects.create)(
        title="t", bound_project=project, created_by=stranger
    )
    cs = await _make_blueprint_session(conversation_id=conversation.id)
    sub = await _make_subagent_session(cs, owner=access_user)

    resp = await sync_to_async(client.post)(
        _REPORT_URL, _report_payload(), format="json", **_headers(sub)
    )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "not_member"
    assert await _entry_count(cs.id) == 0


async def test_member_of_bound_project_allowed(mcp_client, access_user) -> None:
    """③ 成员正向：令牌所有者是绑定项目的成员 → 放行（成员闸不误伤主路径）。"""
    client, _ = mcp_client
    project = await _make_project(access_user, key="bpc-member")
    conversation = await sync_to_async(Conversation.objects.create)(
        title="t", bound_project=project, created_by=access_user
    )
    cs = await _make_blueprint_session(conversation_id=conversation.id)
    sub = await _make_subagent_session(cs, owner=access_user)

    resp = await sync_to_async(client.post)(
        _REPORT_URL, _report_payload(), format="json", **_headers(sub)
    )
    assert resp.status_code == 200
    assert resp.json()["applied"] is True
    assert await _entry_count(cs.id) == 1


async def test_public_org_non_member_allowed(mcp_client, access_user) -> None:
    """③ 成员口径与 packer 对称：非成员 + public_org 项目 → 放行（不是 not_member）。"""
    client, _ = mcp_client
    stranger = await sync_to_async(User.objects.create_user)(username="bpc-pub", password="x")
    project = await _make_project(stranger, key="bpc-pub")  # 默认 public_org
    conversation = await sync_to_async(Conversation.objects.create)(
        title="t", bound_project=project, created_by=stranger
    )
    cs = await _make_blueprint_session(conversation_id=conversation.id)
    sub = await _make_subagent_session(cs, owner=access_user)

    resp = await sync_to_async(client.post)(
        _REPORT_URL, _report_payload(), format="json", **_headers(sub)
    )
    assert resp.status_code == 200
    assert resp.json()["applied"] is True


async def test_missing_session_header_rejected(mcp_client, access_user) -> None:
    """缺 X-Friday-Session-Id → 404 missing_session_header（结构化，非 5xx）。"""
    client, _ = mcp_client
    resp = await sync_to_async(client.post)(_READ_URL, {}, format="json")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "missing_session_header"


async def test_unknown_session_header_rejected(mcp_client, access_user) -> None:
    """header 指向不存在的 session → 404 session_not_found。"""
    client, _ = mcp_client
    resp = await sync_to_async(client.post)(
        _READ_URL, {}, format="json", HTTP_X_FRIDAY_SESSION_ID="bp-research-nope"
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "session_not_found"


# ---------------------------------------------------------------------------
# 3. ⭐ 跨会话读隔离
# ---------------------------------------------------------------------------


async def test_cross_session_read_isolation(mcp_client, access_user) -> None:
    """A 写 2 条、B 写 1 条 → 用 B 的 header 读**只**返回 B 的 1 条。"""
    client, _ = mcp_client
    cs_a = await _make_blueprint_session()
    cs_b = await _make_blueprint_session()
    sub_a = await _make_subagent_session(cs_a, owner=access_user)
    sub_b = await _make_subagent_session(cs_b, owner=access_user)

    for i in range(2):
        resp = await sync_to_async(client.post)(
            _REPORT_URL,
            _report_payload(key=f"contract:a{i}", kind="contract"),
            format="json",
            **_headers(sub_a),
        )
        assert resp.status_code == 200
    resp = await sync_to_async(client.post)(
        _REPORT_URL,
        _report_payload(key="contract:b0", kind="contract"),
        format="json",
        **_headers(sub_b),
    )
    assert resp.status_code == 200

    read = await sync_to_async(client.post)(_READ_URL, {}, format="json", **_headers(sub_b))
    assert read.status_code == 200
    body = read.json()
    assert body["count"] == 1
    assert [e["key"] for e in body["entries"]] == ["contract:b0"]
    # A 的条目一条都拿不到（结构性隔离，非过滤巧合）。
    assert await _entry_count(cs_a.id) == 2


# ---------------------------------------------------------------------------
# 4. 脱敏结构保真
# ---------------------------------------------------------------------------


async def test_content_credentials_redacted_keeping_shape(mcp_client, access_user) -> None:
    """content 里的 PAT/密钥入库后零出现，且 JSON 结构与非字符串叶子未塌。"""
    client, _ = mcp_client
    cs = await _make_blueprint_session()
    sub = await _make_subagent_session(cs, owner=access_user)

    resp = await sync_to_async(client.post)(
        _REPORT_URL,
        _report_payload(
            content={
                "raw": "friday_pat_abcdefghij1234567890",
                "nested": {"n": 7, "s": "Bearer sk-0123456789abcdefghijklmn"},
            }
        ),
        format="json",
        **_headers(sub),
    )
    assert resp.status_code == 200

    rows = await _entries(cs.id)
    assert len(rows) == 1
    dumped = json.dumps(rows[0].content, ensure_ascii=False)
    assert "friday_pat_" not in dumped
    assert "sk-0123456789" not in dumped
    assert "***REDACTED***" in dumped  # 正向确认替换真的发生过
    assert rows[0].content["nested"]["n"] == 7  # 结构未塌，非字符串叶子原样


# ---------------------------------------------------------------------------
# 5. ⭐ 绝不 5xx
# ---------------------------------------------------------------------------


async def test_service_failure_never_5xx(mcp_client, access_user, monkeypatch) -> None:
    """service 抛异常 → 200 + applied=false（断言 status_code < 500）。"""
    client, _ = mcp_client
    cs = await _make_blueprint_session()
    sub = await _make_subagent_session(cs, owner=access_user)

    async def _boom(self, **kwargs):
        raise RuntimeError("boom friday_pat_abcdefghij1234567890")

    monkeypatch.setattr(BlueprintContextService, "append_entry", _boom)

    resp = await sync_to_async(client.post)(
        _REPORT_URL, _report_payload(), format="json", **_headers(sub)
    )
    assert resp.status_code < 500
    assert resp.status_code == 200
    body = resp.json()
    assert body["applied"] is False
    assert body["reason"] == "internal_error"
    assert await _entry_count(cs.id) == 0


async def test_read_failure_never_5xx(mcp_client, access_user, monkeypatch) -> None:
    """读侧 service 抛异常 → 200 + 空结果 + error=internal_error（< 500）。"""
    client, _ = mcp_client
    cs = await _make_blueprint_session()
    sub = await _make_subagent_session(cs, owner=access_user)

    async def _boom(self, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(BlueprintContextService, "read_entries", _boom)

    resp = await sync_to_async(client.post)(
        _READ_URL, {"since_seq": 3}, format="json", **_headers(sub)
    )
    assert resp.status_code < 500
    body = resp.json()
    assert body["entries"] == []
    assert body["count"] == 0
    assert body["max_seq"] == 3
    assert body["error"] == "internal_error"


async def test_unknown_tool_path_is_404_not_500(mcp_client) -> None:
    """未知工具路径 → Django 路由层 404（容器 handler 回显 code 即可，不崩）。"""
    client, _ = mcp_client
    resp = await sync_to_async(client.post)("/api/mcp/tools/no_such_tool/", {}, format="json")
    assert resp.status_code == 404
    assert resp.status_code < 500


# ---------------------------------------------------------------------------
# 6. 入参非法
# ---------------------------------------------------------------------------


async def test_invalid_kind_rejected(mcp_client, access_user) -> None:
    """kind 非枚举 → 400 invalid_params（serializer 层）且 DB 零新增。"""
    client, _ = mcp_client
    cs = await _make_blueprint_session()
    sub = await _make_subagent_session(cs, owner=access_user)

    resp = await sync_to_async(client.post)(
        _REPORT_URL, _report_payload(kind="bogus"), format="json", **_headers(sub)
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "invalid_params"
    assert await _entry_count(cs.id) == 0


async def test_non_object_content_rejected(mcp_client, access_user) -> None:
    """content 非 JSON 对象（list）→ 400 且 DB 零新增。"""
    client, _ = mcp_client
    cs = await _make_blueprint_session()
    sub = await _make_subagent_session(cs, owner=access_user)

    resp = await sync_to_async(client.post)(
        _REPORT_URL, _report_payload(content=[1, 2]), format="json", **_headers(sub)
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "invalid_params"
    assert await _entry_count(cs.id) == 0


# ---------------------------------------------------------------------------
# 7. waiter 顺带满足
# ---------------------------------------------------------------------------


async def test_report_satisfies_waiter(mcp_client, access_user) -> None:
    """先登记等 repo:alpha.api_surface 的 waiter → report 该 key 即置 superseded 并回报计数。"""
    client, _ = mcp_client
    cs = await _make_blueprint_session()
    sub = await _make_subagent_session(cs, owner=access_user)

    waiter = await BlueprintContextService().register_waiter(
        session=cs,
        from_repository_id="beta",
        wait_key_pattern="repo:alpha.api_surface",
        reason="需要 alpha 的接口面",
    )
    assert waiter["cycle_detected"] is False

    resp = await sync_to_async(client.post)(
        _REPORT_URL, _report_payload(), format="json", **_headers(sub)
    )
    assert resp.status_code == 200
    assert resp.json()["satisfied_waiters"] == 1
    assert await _entry_status(waiter["entry_id"]) == ContextEntryStatus.SUPERSEDED


# ---------------------------------------------------------------------------
# 8. 观测留痕
# ---------------------------------------------------------------------------


async def test_observability_records_tool_call_without_content(mcp_client, access_user) -> None:
    """两个新工具各落一条 ToolCallRecord + RequestMetric.labels['call_source']；

    留痕里不含 content 正文（脱敏后的值可留，但原始密钥字符串绝不出现）。
    """
    client, _ = mcp_client
    cs = await _make_blueprint_session()
    sub = await _make_subagent_session(cs, owner=access_user)

    secret = "friday_pat_abcdefghij1234567890"
    resp = await sync_to_async(client.post)(
        _REPORT_URL,
        _report_payload(content={"raw": secret}),
        format="json",
        **_headers(sub),
    )
    assert resp.status_code == 200
    read = await sync_to_async(client.post)(_READ_URL, {}, format="json", **_headers(sub))
    assert read.status_code == 200

    @sync_to_async
    def _tool_calls(name: str) -> list[ToolCallRecord]:
        return list(ToolCallRecord.objects.filter(tool_name=name))

    @sync_to_async
    def _metric_call_sources() -> set[str]:
        # 指标经内存队列异步落库，测试里显式 drain（既有 test_learning_cases 同款钩子）。
        flush_now()
        return {
            str((row.labels or {}).get("call_source") or "")
            for row in RequestMetric.objects.filter(route__startswith="mcp:")
        }

    report_calls = await _tool_calls("report_blueprint_context")
    read_calls = await _tool_calls("read_blueprint_context")
    assert len(report_calls) == 1
    assert len(read_calls) == 1
    # RequestMetric.labels['call_source'] 由 McpToolView._record 写入（已核实
    # views.py 基类 labels={"call_source": tool_name, "run_id": ...}）。
    call_sources = await _metric_call_sources()
    assert {"report_blueprint_context", "read_blueprint_context"} <= call_sources

    # 留痕不得回显原始密钥（入参留痕经 ledger 脱敏；读侧返回的是已脱敏条目）。
    dumped = json.dumps(
        [c.input for c in report_calls] + [c.output for c in read_calls],
        ensure_ascii=False,
        default=str,
    )
    assert secret not in dumped
