"""蓝图异步澄清协议的两个 MCP 工具守护测试（GATE-01，Phase 116-06）。

守十二件事（断言一律**从 DB 重读**，不信响应体）：

1. **两工具的 snapshot 条目存在**且 ``request`` / ``response`` 键集与实际响应逐字一致。
2. ⭐ **``create_feishu_technical_plan`` 的三个追加键在 snapshot 里**（该文件自带的教训：
   漏在 snapshot 里会让外部客户端按已发布契约以为它不存在），且**既有 12 个响应键与
   9 个请求键一个不少**。
3. **未认证 ⇒ 401**（两工具各一条）。
4. ⭐ **非成员 ⇒ 中性 404**（范围闸生效，与 REST 面同源实现）。
5. ⭐ **对 ``ai_review_finding`` 线程作答 ⇒ 400 且线程状态一字未变**（从 DB 重读断言
   ``status`` 与消息计数均未变）—— 114-CR-01 的 MCP 对称面，**本文件头号靶子**。
6. ⭐ **不可编辑态（``confirmed``）⇒ 400 且 DB 未动**（闸 ② 在写之前）。
7. **正路作答 ⇒ 响应含 ``reflow``** 且 ``reflow.status`` 是五档之一；回灌抛异常时
   **仍不 5xx** 且 ``reflow.status == "failed"``。
8. ⭐ **``get_technical_blueprint`` 的 markdown 带未确认标注**（``pending_review`` 时）而
   ``confirmed`` 时不带 —— 证明它走的是 116-05 的 renderer 且传了**真实**状态。
9. ⭐ **``pending_clarifications`` 含两类线程**（``ai_clarification`` + ``repo_confirmation``）
   且题面经脱敏。
10. ⭐ **``pending_clarifications`` 读失败 ⇒ 503 且响应体逐字不含 ``items`` / ``total``**。
11. ⭐ **``create_feishu_technical_plan`` 开关两态**：``technical_plan`` ⇒ 追加键一个不出现；
    ``technical_blueprint`` ⇒ 三键出现（响应装配处用 ``**extras`` 展开 ⇒ 关闭态零键）。
12. **绝不 5xx**：两工具在内部异常时返回结构化错误信封而不是 500。

⚠️ ``tests/mcp_tools/test_skills_snapshot_guard.py::test_skill_files_discovered`` 在本
worktree **恒红**（``skills/`` 是空目录，P-16）——⛔ 与本文件无关。

REST client 是同步的 ⇒ 本文件用同步用例 + ``async_to_sync`` 装配；async service 跨线程
写库 ⇒ ``transaction=True``。
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import async_to_sync

from delivery.models import (
    Artifact,
    ArtifactVersion,
    BlueprintStatus,
    BlueprintThread,
    BlueprintThreadMessage,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionStatus,
    ThreadKind,
    ThreadSeverity,
    ThreadStatus,
)
from delivery.services import ArtifactService
from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService
from mcp_tools.serializers import TOOL_SCHEMA_SNAPSHOT
from tests.helpers.blueprint_samples import make_blueprint

pytestmark = pytest.mark.django_db(transaction=True)

# 真打 URL：端到端过认证 + serializer + view（与 urls.py 逐字一致）
_GET_URL = "/api/mcp/tools/get_technical_blueprint/"
_ANSWER_URL = "/api/mcp/tools/answer_blueprint_clarification/"

_RESUME_TARGET = "services.process_runtime.blueprint_resume.aresume_after_gate_action"
# view 内是函数级懒 import ⇒ 必须 patch **来源模块**的属性
_REFLOW_TARGET = "services.process_runtime.blueprint_reflow.aapply_thread_answers"
_PENDING_TARGET = "mcp_tools.views._aload_pending_clarifications"

_SCOPE_PROJECT_ID = "33333333-3333-3333-3333-333333333333"
_OTHER_PROJECT_ID = "44444444-4444-4444-4444-444444444444"

_TEXT_BLOCK = "blk_impl01_how"
# 半可信题面里夹带的凭证样本（脱敏断言用）
_SECRET = "sk-ant-api03-DEADBEEFDEADBEEFDEADBEEFDEADBEEF"

# 回灌五档（`blueprint_reflow.aapply_thread_answers` 的恒定取值）+ 端点兜底的 failed
_REFLOW_STATUSES = {"applied", "unchanged", "conflict", "invalid", "noop", "failed"}


# ── 工厂 ─────────────────────────────────────────────────────────────────────


def _make_project(project_id: str, *, member: Any = None) -> Any:
    from initiatives.models import Project, ProjectMember
    from projects.models import Space

    project = Project.objects.filter(id=project_id).first()
    if project is None:
        space, _ = Space.objects.get_or_create(
            name=f"space-{project_id[:8]}", defaults={"feishu_project_key": f"k-{project_id[:8]}"}
        )
        project = Project.objects.create(id=project_id, space=space, name=f"proj-{project_id[:8]}")
    if member is not None:
        ProjectMember.objects.get_or_create(project=project, user=member)
    return project


@pytest.fixture(autouse=True)
def _no_blueprint_background_ingest(monkeypatch: pytest.MonkeyPatch) -> None:
    """拦掉蓝图版本落地触发的**后台**知识图谱摄取（逐字复刻 ``tests/delivery/conftest.py``
    的同名 fixture —— conftest 作用域不跨目录树）。

    ``ArtifactService.create`` 落 ``blueprint/v1`` 版本时会 ``aschedule_ingestion`` →
    ``on_commit`` → ``run_in_background``，让后台线程在 **SQLite** 上并发写会撞
    ``database table is locked``（生产 PostgreSQL 无此问题）。⭐ 只拦
    ``source_kind == "blueprint"``，其它 source_kind 原样放行。
    """
    from knowledge import ingestion

    real = ingestion.aschedule_ingestion

    async def _guarded(request, **kwargs):
        if getattr(request, "source_kind", "") == "blueprint":
            return None
        return await real(request, **kwargs)

    monkeypatch.setattr(ingestion, "aschedule_ingestion", _guarded)


@pytest.fixture(autouse=True)
def _project_scope(access_user: Any) -> Any:
    """两个新工具都收项目范围闸 ⇒ 样例蓝图必须落在 token owner 所属的项目里。"""
    return _make_project(_SCOPE_PROJECT_ID, member=access_user)


@pytest.fixture(autouse=True)
def _isolate_switch():
    """开关隔离：每条用例前后都清干净（默认四键全 ``technical_plan``）。"""
    _clear_switch()
    yield
    _clear_switch()


def _clear_switch() -> None:
    from django.core.cache import cache

    from system.models import SettingKeys, SystemSetting
    from system.settings_service import _cache_key

    SystemSetting.objects.filter(key__startswith="blueprint.").delete()
    cache.delete(_cache_key(SettingKeys.BLUEPRINT_ENTRY_SWITCH))


def _save_switch(value: dict[str, str]) -> None:
    from system.models import SettingKeys, SystemSetting

    _clear_switch()
    SystemSetting.objects.update_or_create(
        key=SettingKeys.BLUEPRINT_ENTRY_SWITCH, defaults={"value": json.dumps(value)}
    )


def _make_artifact(
    status: str = BlueprintStatus.NEEDS_CLARIFICATION, *, project_id: str = _SCOPE_PROJECT_ID
) -> Artifact:
    content = make_blueprint()
    content["meta"]["project_id"] = project_id
    artifact = async_to_sync(ArtifactService().create)(
        "technical_plan", content, created_by_user_id="tester"
    )
    Artifact.objects.filter(id=artifact.id).update(blueprint_status=status)
    artifact.blueprint_status = status
    return artifact


def _make_session(artifact: Artifact, user: Any) -> ConvergenceSession:
    return ConvergenceSession.objects.create(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.WORKFLOW,
        current_stage="spec_gate",
        status=ConvergenceSessionStatus.RUNNING,
        current_artifact_version_id=artifact.current_version_id,
        created_by=user,
    )


def _open_thread(
    artifact: Artifact,
    *,
    kind: str = ThreadKind.AI_CLARIFICATION,
    question: str = "该接口的鉴权走哪套？",
    severity: str = "",
    blocking: bool = True,
) -> BlueprintThread:
    return async_to_sync(BlueprintLifecycleService().open_thread)(
        artifact,
        kind=kind,
        blocking=blocking,
        severity=severity,
        question=question,
        anchor={"block_id": _TEXT_BLOCK, "section_path": "impl", "quoted_text": "复用既有"},
        initiated_by_user_id="reviewer-agent",
    )


def _stub_resume(monkeypatch) -> AsyncMock:
    mock = AsyncMock(return_value=None)
    monkeypatch.setattr(_RESUME_TARGET, mock)
    return mock


def _thread_row(thread: BlueprintThread) -> tuple[str, Any, int]:
    """线程的可比对快照（status / updated_at / 消息数）—— 「一字未变」的判据。"""
    row = BlueprintThread.objects.get(id=thread.id)
    return (
        row.status,
        row.updated_at,
        BlueprintThreadMessage.objects.filter(thread_id=row.id).count(),
    )


# ═══════════════════════════════════════════════════════════════════════════
# 1-2. 契约快照（对外契约，⛔ 不是内部注释）
# ═══════════════════════════════════════════════════════════════════════════


def test_both_new_tools_are_registered_in_the_schema_snapshot() -> None:
    assert "get_technical_blueprint" in TOOL_SCHEMA_SNAPSHOT
    assert "answer_blueprint_clarification" in TOOL_SCHEMA_SNAPSHOT
    assert TOOL_SCHEMA_SNAPSHOT["get_technical_blueprint"]["request"] == ["artifact_id"]
    assert TOOL_SCHEMA_SNAPSHOT["answer_blueprint_clarification"]["request"] == [
        "thread_id",
        "body",
        "artifact_id",
    ]


def test_no_third_list_tool_was_added() -> None:
    """⛔ pending 清单内联在 ``get_technical_blueprint`` 里，⛔ 不建第三个 list 工具。"""
    assert "pending_clarifications" in TOOL_SCHEMA_SNAPSHOT["get_technical_blueprint"]["response"]
    blueprint_tools = {
        name
        for name in TOOL_SCHEMA_SNAPSHOT
        if "blueprint" in name
        and name not in ("read_blueprint_context", "report_blueprint_context")
    }
    assert blueprint_tools == {"get_technical_blueprint", "answer_blueprint_clarification"}


def test_create_feishu_technical_plan_only_gained_three_additive_keys() -> None:
    """⭐ 既有 12 个响应键 / 9 个请求键**一个不少**，追加项逐个列名（外形兼容纪律）。

    ⚠️ 116-REVIEW MJ-02 起请求侧多一个 ``assumptions_tier``（可选、缺省空串 ⇒ 不传时请求
    与改动前逐字相同）。此处**逐个列出**新增键而不是只数个数：数个数只能发现「多了几个」，
    列名才能发现「换掉了哪个」。
    """
    entry = TOOL_SCHEMA_SNAPSHOT["create_feishu_technical_plan"]
    old_request = [
        "context_id",
        "repository_ids",
        "repo_hints",
        "context_chunks",
        "similar_cases",
        "title",
        "folder_token",
        "create_document",
        "write_comment",
    ]
    assert [key for key in old_request if key not in entry["request"]] == []
    assert [key for key in entry["request"] if key not in old_request] == ["assumptions_tier"]
    old_response = [
        "technical_plan_id",
        "context_id",
        "project_id",
        "plan",
        "markdown",
        "repository_tasks",
        "evidence",
        "feishu_document",
        "comment",
        "status",
        "retry_state",
        "run_id",
    ]
    missing = [key for key in old_response if key not in entry["response"]]
    assert not missing, missing
    assert [key for key in entry["response"] if key not in old_response] == [
        # 116-REVIEW MJ-03：失败原因回传（恒在，成功时空串）。
        "error",
        "error_stage",
        # 116-06：仅在 mcp 开关切到蓝图时非空的三键。
        "blueprint_artifact_id",
        "blueprint_current_status",
        "pending_clarifications",
    ]
    for key in ("blueprint_artifact_id", "blueprint_current_status", "pending_clarifications"):
        assert key in entry["response"], key


def test_snapshot_response_keys_match_the_actual_get_response(mcp_client, access_user) -> None:
    """snapshot 的 response 键集与**实际响应**逐字一致（⛔ 不做「快照 vs 快照」自比）。"""
    client, _ = mcp_client
    artifact = _make_artifact()
    _make_session(artifact, access_user)

    resp = client.post(_GET_URL, {"artifact_id": str(artifact.id)}, format="json")

    assert resp.status_code == 200, resp.json()
    assert set(resp.json()) == set(TOOL_SCHEMA_SNAPSHOT["get_technical_blueprint"]["response"])


def test_snapshot_response_keys_match_the_actual_answer_response(
    mcp_client, access_user, monkeypatch
) -> None:
    client, _ = mcp_client
    _stub_resume(monkeypatch)
    artifact = _make_artifact()
    _make_session(artifact, access_user)
    thread = _open_thread(artifact)
    monkeypatch.setattr(_REFLOW_TARGET, AsyncMock(return_value={"status": "noop"}))

    resp = client.post(
        _ANSWER_URL, {"thread_id": str(thread.id), "body": "统一走 JWT"}, format="json"
    )

    assert resp.status_code == 200, resp.json()
    assert set(resp.json()) == set(
        TOOL_SCHEMA_SNAPSHOT["answer_blueprint_clarification"]["response"]
    )


# ═══════════════════════════════════════════════════════════════════════════
# 3-4. 鉴权与范围闸
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("url", [_GET_URL, _ANSWER_URL])
def test_unauthenticated_is_rejected(url: str) -> None:
    from rest_framework.test import APIClient

    resp = APIClient().post(url, {"artifact_id": str(uuid.uuid4())}, format="json")
    assert resp.status_code == 401


def test_get_returns_neutral_404_for_non_member(mcp_client) -> None:
    """⭐ 越权一律**中性 404**（与「artifact 不存在」逐字相同，不泄露存在性）。"""
    client, _ = mcp_client
    _make_project(_OTHER_PROJECT_ID)  # ⛔ 不把 token owner 加进去
    artifact = _make_artifact(project_id=_OTHER_PROJECT_ID)

    resp = client.post(_GET_URL, {"artifact_id": str(artifact.id)}, format="json")

    assert resp.status_code == 404
    missing = client.post(_GET_URL, {"artifact_id": str(uuid.uuid4())}, format="json")
    assert resp.json()["detail"] == missing.json()["detail"]


def test_answer_returns_neutral_404_for_non_member(mcp_client) -> None:
    client, _ = mcp_client
    _make_project(_OTHER_PROJECT_ID)
    artifact = _make_artifact(project_id=_OTHER_PROJECT_ID)
    thread = _open_thread(artifact)
    before = _thread_row(thread)

    resp = client.post(_ANSWER_URL, {"thread_id": str(thread.id), "body": "偷答"}, format="json")

    assert resp.status_code == 404
    assert _thread_row(thread) == before


def test_answer_rejects_a_thread_id_claimed_under_another_artifact(mcp_client) -> None:
    """自报 ``artifact_id`` 与线程实际归属不符 ⇒ 中性 404（⛔ 不信调用方自报归属）。"""
    client, _ = mcp_client
    artifact = _make_artifact()
    other = _make_artifact()
    thread = _open_thread(artifact)

    resp = client.post(
        _ANSWER_URL,
        {"thread_id": str(thread.id), "artifact_id": str(other.id), "body": "走 JWT"},
        format="json",
    )

    assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# 5-7. ⭐ 三道闸经 MCP 面全部继承（本文件头号靶子）
# ═══════════════════════════════════════════════════════════════════════════


def test_finding_thread_cannot_be_answered_and_stays_byte_identical(
    mcp_client, access_user, monkeypatch
) -> None:
    """⭐ 114-CR-01 的 MCP 对称面（T-116-48）：finding ⇒ 400 且线程状态**一字未变**。

    不分流即等于开一条「在 BLOCKER 上回一句任意文本」就解开 confirm 门的后门——
    回灌链落版本成功后会对被消费线程**无条件** ``resolve_thread``。
    """
    client, _ = mcp_client
    _stub_resume(monkeypatch)
    artifact = _make_artifact()
    _make_session(artifact, access_user)
    finding = _open_thread(
        artifact,
        kind=ThreadKind.AI_REVIEW_FINDING,
        severity=ThreadSeverity.BLOCKER,
        question="[R2] 关键结论缺 citations",
    )
    before = _thread_row(finding)

    resp = client.post(
        _ANSWER_URL, {"thread_id": str(finding.id), "body": "已经补上了"}, format="json"
    )

    assert resp.status_code == 400, resp.json()
    assert resp.json()["error_code"] == "not_answerable"
    # ⭐ 从 DB 重读：状态 / updated_at / 消息数三项都必须与作答前逐字相同
    assert _thread_row(finding) == before
    assert BlueprintThread.objects.get(id=finding.id).status == ThreadStatus.OPEN


def test_locked_blueprint_refuses_the_answer_before_any_write(
    mcp_client, access_user, monkeypatch
) -> None:
    """⭐ 闸 ② 在写之前（114-MJ-04 的 MCP 面，T-116-49）：越界 400 且 DB 一字未动。"""
    client, _ = mcp_client
    _stub_resume(monkeypatch)
    artifact = _make_artifact()
    _make_session(artifact, access_user)
    thread = _open_thread(artifact)
    Artifact.objects.filter(id=artifact.id).update(blueprint_status=BlueprintStatus.CONFIRMED)
    before_messages = BlueprintThreadMessage.objects.count()
    before_versions = ArtifactVersion.objects.filter(artifact=artifact).count()

    resp = client.post(_ANSWER_URL, {"thread_id": str(thread.id), "body": "偷答"}, format="json")

    assert resp.status_code == 400, resp.json()
    assert resp.json()["error_code"] == "not_editable"
    assert BlueprintThreadMessage.objects.count() == before_messages
    assert ArtifactVersion.objects.filter(artifact=artifact).count() == before_versions
    assert BlueprintThread.objects.get(id=thread.id).status == ThreadStatus.OPEN


def test_empty_body_is_rejected_without_touching_the_thread(
    mcp_client, access_user, monkeypatch
) -> None:
    client, _ = mcp_client
    _stub_resume(monkeypatch)
    artifact = _make_artifact()
    _make_session(artifact, access_user)
    thread = _open_thread(artifact)
    before = _thread_row(thread)

    resp = client.post(_ANSWER_URL, {"thread_id": str(thread.id), "body": "   "}, format="json")

    assert resp.status_code == 400
    assert _thread_row(thread) == before


def test_happy_path_answers_and_reports_reflow(mcp_client, access_user, monkeypatch) -> None:
    """⭐ 响应**必须带 ``reflow``**：否则调用方无法区分「答案记下了但正文没更新」。"""
    client, _ = mcp_client
    resume = _stub_resume(monkeypatch)
    artifact = _make_artifact()
    _make_session(artifact, access_user)
    thread = _open_thread(artifact)

    async def _writer(content: dict, answers: list[dict], *, session: Any = None) -> dict:
        assert answers, "生产 writer 必须收到答案条目"
        return content

    monkeypatch.setattr("services.process_runtime.blueprint_reflow.ablock_section_writer", _writer)

    resp = client.post(
        _ANSWER_URL,
        {"thread_id": str(thread.id), "body": "统一走 JWT，网关侧校验"},
        format="json",
    )

    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["status"] == "answered"
    assert body["reflow"]["status"] in _REFLOW_STATUSES
    assert body["reflow"]["status"] == "applied"
    assert BlueprintThread.objects.get(id=thread.id).status == ThreadStatus.RESOLVED
    assert resume.await_count == 1


def test_reflow_failure_never_5xx_and_is_reported_truthfully(
    mcp_client, access_user, monkeypatch
) -> None:
    client, _ = mcp_client
    _stub_resume(monkeypatch)
    artifact = _make_artifact()
    _make_session(artifact, access_user)
    thread = _open_thread(artifact)
    monkeypatch.setattr(_REFLOW_TARGET, AsyncMock(side_effect=RuntimeError("回灌炸了")))

    resp = client.post(_ANSWER_URL, {"thread_id": str(thread.id), "body": "走 JWT"}, format="json")

    assert resp.status_code == 200, resp.json()
    assert resp.json()["reflow"]["status"] == "failed"
    # 作答已持久化 ⇒ 绝不回滚
    assert BlueprintThread.objects.get(id=thread.id).status == ThreadStatus.ANSWERED


# ═══════════════════════════════════════════════════════════════════════════
# 8-10. get_technical_blueprint 的三条硬要求
# ═══════════════════════════════════════════════════════════════════════════


def test_markdown_carries_the_unconfirmed_watermark_for_pending_review(
    mcp_client, access_user
) -> None:
    """⭐ 走的是 116-05 的共享 renderer **且传了真实状态**（⛔ 不在 MCP 层拼、⛔ 不传空串）。"""
    client, _ = mcp_client
    artifact = _make_artifact(BlueprintStatus.PENDING_REVIEW)
    _make_session(artifact, access_user)

    resp = client.post(_GET_URL, {"artifact_id": str(artifact.id)}, format="json")

    assert resp.status_code == 200
    assert resp.json()["current_status"] == BlueprintStatus.PENDING_REVIEW
    assert "未经确认" in resp.json()["markdown"].splitlines()[0]


def test_markdown_drops_the_watermark_once_confirmed(mcp_client, access_user) -> None:
    """非恒真对照：``confirmed`` 时不带标注 ⇒ 证明传的是真实状态而不是常量。"""
    client, _ = mcp_client
    artifact = _make_artifact(BlueprintStatus.CONFIRMED)
    _make_session(artifact, access_user)

    resp = client.post(_GET_URL, {"artifact_id": str(artifact.id)}, format="json")

    assert resp.status_code == 200
    assert "未经确认" not in resp.json()["markdown"].splitlines()[0]


def test_pending_clarifications_cover_both_kinds_and_are_redacted(mcp_client, access_user) -> None:
    """⭐ ⛔ **不传 ``kind``**：``ai_clarification`` 与 ``repo_confirmation`` 两类都算。"""
    client, _ = mcp_client
    artifact = _make_artifact()
    _make_session(artifact, access_user)
    _open_thread(artifact, question=f"鉴权 token 是 {_SECRET} 吗？")
    _open_thread(artifact, kind=ThreadKind.REPO_CONFIRMATION, question="确认这三个仓？")
    # 非阻塞线程不算待澄清（对照，证明判据非恒真）
    _open_thread(artifact, kind=ThreadKind.HUMAN_COMMENT, question="顺手记一笔", blocking=False)

    resp = client.post(_GET_URL, {"artifact_id": str(artifact.id)}, format="json")

    assert resp.status_code == 200
    pending = resp.json()["pending_clarifications"]
    assert {item["kind"] for item in pending} == {
        ThreadKind.AI_CLARIFICATION,
        ThreadKind.REPO_CONFIRMATION,
    }
    joined = " ".join(item["question"] for item in pending)
    assert _SECRET not in joined, "半可信题面必须过 redact_secrets_in_text"


def test_pending_read_failure_is_a_truthful_503_without_items_or_total(
    mcp_client, access_user, monkeypatch
) -> None:
    """⭐ P-12：⛔ 绝不包成 200 空结构（调用方 ``len(...) == 0`` 会读成「没有待澄清」）。"""
    client, _ = mcp_client
    artifact = _make_artifact()
    _make_session(artifact, access_user)
    monkeypatch.setattr(_PENDING_TARGET, AsyncMock(side_effect=RuntimeError("db down")))

    resp = client.post(_GET_URL, {"artifact_id": str(artifact.id)}, format="json")

    assert resp.status_code == 503
    body = resp.json()
    assert "items" not in set(body)
    assert "total" not in set(body)
    assert body["error_code"] == "pending_unavailable"
    assert "db down" not in json.dumps(body), "中性 detail ⛔ 不回显内部异常原文"


def test_six_section_summary_is_a_summary_not_the_whole_content(mcp_client, access_user) -> None:
    """⛔ 不塞整份 content：只回每段的条目数与关键标题。"""
    client, _ = mcp_client
    artifact = _make_artifact()
    _make_session(artifact, access_user)

    resp = client.post(_GET_URL, {"artifact_id": str(artifact.id)}, format="json")

    sections = resp.json()["sections"]
    assert set(sections) == {
        "repo_associations",
        "current_state_analysis",
        "implementation_overview",
        "api_contracts",
        "impact_analysis",
        "interaction_flows",
    }
    for value in sections.values():
        assert set(value) == {"count", "titles"}


# ═══════════════════════════════════════════════════════════════════════════
# 11. create_feishu_technical_plan 的开关两态
# ═══════════════════════════════════════════════════════════════════════════


def test_response_extras_are_empty_when_the_mcp_switch_is_off() -> None:
    """⭐ 开关关闭 ⇒ 零追加键（响应装配处 ``**extras`` 展开为空 ⇒ 响应逐字不变）。"""
    from mcp_tools.technical_plan_service import _ablueprint_response_extras

    _save_switch({"workflow": "technical_blueprint", "mcp": "technical_plan"})
    delegate = _FakeDelegate(None)

    assert async_to_sync(_ablueprint_response_extras)(delegate) == {}


def test_response_extras_carry_three_keys_when_the_mcp_switch_is_on(access_user) -> None:
    from mcp_tools.technical_plan_service import _ablueprint_response_extras

    _save_switch({"mcp": "technical_blueprint"})
    artifact = _make_artifact()
    _open_thread(artifact, question=f"密钥是 {_SECRET} 吗？")
    delegate = _FakeDelegate(artifact.current_version_id)

    extras = async_to_sync(_ablueprint_response_extras)(delegate)

    assert set(extras) == {
        "blueprint_artifact_id",
        "blueprint_current_status",
        "pending_clarifications",
    }
    assert extras["blueprint_artifact_id"] == str(artifact.id)
    assert extras["blueprint_current_status"] == BlueprintStatus.NEEDS_CLARIFICATION
    assert len(extras["pending_clarifications"]) == 1
    assert _SECRET not in extras["pending_clarifications"][0]["question"]


def test_response_assembly_splats_the_extras_so_the_off_state_is_byte_identical() -> None:
    """源码断言：追加三键经 ``**blueprint_extras`` 展开 ⇒ 空 dict 时零键混入。"""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[2] / "mcp_tools" / "technical_plan_service.py"
    ).read_text(encoding="utf-8")
    assert "**blueprint_extras," in src
    # ⛔ 响应字典键不得出现字面 blueprint_status（INV-6 `_RE_FIELD_DICT_KEY`）
    assert '"blueprint_status":' not in src


def test_mcp_switch_argument_is_a_literal_constant() -> None:
    """⛔ 开关实参必须是字面量：写成 ``session.entrypoint``（蓝图 MCP 会话恒 ``workflow``）
    会让打开 workflow 键把 MCP 一起切走（116-01 的 ast 守卫在此覆盖新调用点）。"""
    import ast
    from pathlib import Path

    tree = ast.parse(
        (Path(__file__).resolve().parents[2] / "mcp_tools" / "technical_plan_service.py").read_text(
            encoding="utf-8"
        )
    )
    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = (
            node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        )
        if name == "aresolve_entry_process_type":
            assert node.args and isinstance(node.args[0], ast.Constant), "开关实参必须是字面量"
            found = True
    assert found, "缺开关查询"


def test_work_item_context_is_wired_into_the_delegate_call() -> None:
    """116-03 交接：⛔ 不传 ``work_item_context`` ⇒ mcp 开关打开时蓝图链恒「拒绝发起」。"""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[2] / "mcp_tools" / "technical_plan_service.py"
    ).read_text(encoding="utf-8")
    assert "work_item_context=context," in src


# ═══════════════════════════════════════════════════════════════════════════
# 12. 绝不 5xx
# ═══════════════════════════════════════════════════════════════════════════


def test_get_never_5xx_on_internal_error(mcp_client, access_user, monkeypatch) -> None:
    client, _ = mcp_client
    artifact = _make_artifact()
    monkeypatch.setattr(
        "delivery.api.blueprint_review_views._alatest_content",
        AsyncMock(side_effect=RuntimeError("boom")),
    )

    resp = client.post(_GET_URL, {"artifact_id": str(artifact.id)}, format="json")

    assert resp.status_code < 500 or resp.status_code == 503
    assert resp.json()["error_code"] == "internal_error"
    assert "boom" not in json.dumps(resp.json())


def test_answer_never_5xx_on_internal_error(mcp_client, access_user, monkeypatch) -> None:
    client, _ = mcp_client
    artifact = _make_artifact()
    thread = _open_thread(artifact)
    monkeypatch.setattr(
        "delivery.services.blueprint_answer_action.aanswer_thread",
        AsyncMock(side_effect=RuntimeError("boom")),
    )

    resp = client.post(_ANSWER_URL, {"thread_id": str(thread.id), "body": "走 JWT"}, format="json")

    assert resp.status_code == 503
    assert resp.json()["error_code"] == "internal_error"
    assert "boom" not in json.dumps(resp.json())


def test_mcp_layer_never_writes_blueprint_threads_directly() -> None:
    """⛔ 旁路 INV-6（直写线程）与 ⛔ 进程内自调 REST 的源码级双断言。"""
    import re
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "mcp_tools" / "views.py").read_text(
        encoding="utf-8"
    )
    assert not re.search(r"\bBlueprintThread(?!Message)\s*\(", src)
    assert not re.search(r"BlueprintThread\w*\.objects\.(a?create|a?update)", src)
    assert "aanswer_thread" in src, "作答必须走共享 service"
    # 范围闸复用不复制
    assert "_aassert_project_scope" in src
    assert "async def _aassert_project_scope" not in src


class _FakeDelegate:
    """``DelegateResult`` 的最小替身（只用到 ``session.current_artifact_version_id``）。"""

    def __init__(self, version_id: Any) -> None:
        self.session = type("_S", (), {"current_artifact_version_id": version_id})()
