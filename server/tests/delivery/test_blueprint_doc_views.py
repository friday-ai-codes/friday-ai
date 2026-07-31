"""蓝图只读供数面四端点 REST 测试（Phase 115-01 Task 3，VIEW-01 / CLAR-01）。

守十二件事（断言一律**从 DB 重读**，不信响应体）：

1. ⭐ **鉴权第一条**：四端点（正文 GET / 事件 GET / 线程 GET / 线程 POST）未认证一律拒
   （401/403），参数化四条无一例外。
2. ⭐ **范围闸正反并列（MJ-03 对称面）**：成员 → 200；**非成员 → 404 且响应体与「artifact
   不存在」的 404 逐字相同**（``resp.json() == missing.json()``，这是「不泄露存在性」的唯一
   可证伪形态）；superuser → 200。四端点各跑一遍。
3. ⭐ **``meta.project_id`` 缺失 → 400**（fail-closed，不是 404 也不是 200）。
4. **正文端点缺省取最新版本**：造三版 ⇒ 返 ``version_no`` 最大那版且 ``is_current`` 与
   ``artifact.current_version_id`` 一致。
5. ⭐ **``?version_id=`` 取历史版本且 ``is_current is False``**；指向别的 artifact 的版本 /
   不存在的 uuid → **404**；非 UUID → **400**。
6. ⭐ **``quality`` 三态并列（闭 114-MN-05）**：无数据 → ``None``（⛔ 不是 0）/ 有源零值 →
   ``0`` / 有数据 → 正值三组并列存在 ⇒ 逮得住 ``v or 0`` 这类改写；``citation_coverage``
   恒是 float（空引用池 → ``1.0``，⛔ 不为 None）。
7. ⭐ **events 无会话回 200 空结构不是 404**：``{"session_id": "", "current_stage": "",
   "events": []}``。
8. **events 只出 ``BLUEPRINT_EVENTS`` 且 ``ts`` 严格升序**（断言集合引用常量，⛔ 不硬编码
   21 条事件名）；另造一条**排序更靠前**的 ``technical_plan`` 会话证伪跨 process 污染。
9. ⭐ **threads GET 三补键**：``options``（非法形状归一 ``[]`` 不抛）/ ``last_reminded_at`` /
   ``messages[]``（``author`` 为 None 时 ``author_display`` 为空串不炸）；线程与消息各按
   ``created_at`` 升序；``_thread_row`` 原九键仍在（键集 ⊇ 九键）。
10. ⭐ **threads POST 的两条 400 且线程数不变**：``body`` 空 / 纯空格；蓝图状态 ∉ 可编辑
    白名单（``detail == NOT_EDITABLE_DETAIL``）。正路：DB 重读 ``kind == human_comment`` /
    ``blocking is False`` / ``severity == ""`` / ``anchor`` 落库 / ``created_on_version``
    是当前最新版本。
11. **视图零 ORM 写源码扫描**：``objects.<write>`` 与裸实例化均零命中（INV-6）。
12. **范围闸是 import 复用**：源码扫描断言含 ``from delivery.api.blueprint_review_views
    import`` 且**不重新定义**闸函数（防后人复制第三份）。

REST client 是同步的 ⇒ 同步用例 + ``async_to_sync`` 装配（照 114-05）；async service 跨线程
写库 ⇒ ``transaction=True``。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from asgiref.sync import async_to_sync
from django.urls import reverse
from django.utils import timezone

from delivery.models import (
    Artifact,
    ArtifactVersion,
    BlueprintStatus,
    BlueprintThread,
    BlueprintThreadMessage,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionEvent,
    ConvergenceSessionStatus,
    ThreadAuthorType,
    ThreadKind,
    ThreadStatus,
)
from delivery.services import ArtifactService
from delivery.services.blueprint_lifecycle_service import (
    NOT_EDITABLE_DETAIL,
    BlueprintLifecycleService,
)
from delivery.services.event_taxonomy import (
    BLUEPRINT_EVENTS,
    EVENT_BLUEPRINT_REVIEW_COMPLETED,
    EVENT_BLUEPRINT_STAGE_COMPLETED,
    EVENT_BLUEPRINT_STAGE_STARTED,
    EVENT_CLARIFICATION_ASKED,
    EVENT_REPO_ROUTING,
)
from tests.helpers.blueprint_samples import make_blueprint

pytestmark = pytest.mark.django_db(transaction=True)

SERVER_DIR = Path(__file__).resolve().parents[2]
_VIEWS_REL = "delivery/api/blueprint_doc_views.py"

_SCOPE_PROJECT_ID = "11111111-1111-1111-1111-111111111111"
_OTHER_PROJECT_ID = "22222222-2222-2222-2222-222222222222"

_TEXT_BLOCK = "blk_impl01_how"

# 四端点 × (name, http 方法)：鉴权与范围闸用例参数化的唯一来源
_ENDPOINTS = [
    ("blueprint-document", "get"),
    ("blueprint-events", "get"),
    ("blueprint-review-threads", "get"),
    ("blueprint-review-threads", "post"),
]


# ── 工厂（逐字复用 114-05 的范围闸工厂）─────────────────────────────────────


def _make_project(project_id: str, *, member: Any = None) -> Any:
    """建一个 ``initiatives.Project``（可选授予成员）——四端点的范围闸判据源。"""
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
def _project_scope(user) -> Any:
    """⭐ 四端点全挂项目范围闸 ⇒ 样例蓝图必须落在测试用户所属的项目里。"""
    return _make_project(_SCOPE_PROJECT_ID, member=user)


def _make_artifact(
    status: str = BlueprintStatus.PENDING_REVIEW,
    *,
    project_id: str = _SCOPE_PROJECT_ID,
    title: str = "蓝图样例",
) -> Artifact:
    content = make_blueprint()
    content["meta"]["project_id"] = project_id
    artifact = async_to_sync(ArtifactService().create)(
        "technical_plan", content, title=title, created_by_user_id="tester"
    )
    Artifact.objects.filter(id=artifact.id).update(blueprint_status=status)
    artifact.blueprint_status = status
    return artifact


def _add_version(artifact: Artifact, *, marker: str, produced_by_ref: str = "") -> ArtifactVersion:
    content = make_blueprint()
    content["meta"]["project_id"] = _SCOPE_PROJECT_ID
    content["meta"]["title"] = marker
    return async_to_sync(ArtifactService().add_version)(
        artifact, content, produced_by_ref=produced_by_ref
    )


def _make_session(
    artifact: Artifact,
    user: Any,
    *,
    process_type: str = "technical_blueprint",
    current_stage: str = "ai_review",
) -> ConvergenceSession:
    return ConvergenceSession.objects.create(
        process_type=process_type,
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage=current_stage,
        status=ConvergenceSessionStatus.RUNNING,
        current_artifact_version_id=Artifact.objects.get(id=artifact.id).current_version_id,
        created_by=user,
    )


def _emit(session: ConvergenceSession, event: str, *, ts: Any, payload: dict | None = None) -> Any:
    return ConvergenceSessionEvent.objects.create(
        session=session, event=event, ts=ts, payload=payload or {}
    )


def _open_comment(artifact: Artifact, *, question: str = "这一段要改") -> BlueprintThread:
    return async_to_sync(BlueprintLifecycleService().open_thread)(
        artifact,
        kind=ThreadKind.HUMAN_COMMENT,
        blocking=False,
        question=question,
        anchor={"block_id": _TEXT_BLOCK, "section_path": "impl", "quoted_text": "复用既有"},
        initiated_by_user_id="tester",
    )


def _url(name: str, artifact: Artifact) -> str:
    return reverse(name, args=[str(artifact.id)])


def _call(client: Any, name: str, method: str, artifact_id: Any, **kwargs: Any) -> Any:
    url = reverse(name, args=[str(artifact_id)])
    if method == "post":
        return client.post(url, kwargs.get("data") or {"body": "评论"}, format="json")
    return client.get(url, kwargs.get("params") or {})


def _thread_count(artifact: Artifact) -> int:
    return BlueprintThread.objects.filter(artifact_id=artifact.id).count()


# ═══════════════════════════════════════════════════════════════════════════
# 1. 鉴权（安全边界不降级）
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(("name", "method"), _ENDPOINTS)
def test_doc_endpoints_reject_unauthenticated(api_client, name: str, method: str) -> None:
    resp = _call(api_client, name, method, uuid.uuid4())
    assert resp.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════════
# 2-3. 范围闸（正反并列 + fail-closed）
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(("name", "method"), _ENDPOINTS)
def test_doc_endpoints_allow_project_members(authenticated_client, name: str, method: str) -> None:
    """正向对照：成员一律 2xx（证明下面那条 404 断言非恒真）。"""
    artifact = _make_artifact()
    resp = _call(authenticated_client, name, method, artifact.id)
    assert resp.status_code == 200


@pytest.mark.parametrize(("name", "method"), _ENDPOINTS)
def test_doc_endpoints_return_neutral_404_for_non_members(
    authenticated_client, name: str, method: str
) -> None:
    """⭐ 非成员 → 404 **且响应体与「artifact 不存在」逐字相同**（不泄露存在性，MJ-03）。

    403 会让未授权者靠状态码枚举出哪些 artifact_id 存在；两个 404 的响应体不同样能被
    差分出来 —— 所以判据必须是 ``resp.json() == missing.json()``。
    """
    _make_project(_OTHER_PROJECT_ID)  # 存在但 user 不是成员
    artifact = _make_artifact(project_id=_OTHER_PROJECT_ID)
    before = _thread_count(artifact)

    denied = _call(authenticated_client, name, method, artifact.id)
    missing = _call(authenticated_client, name, method, uuid.uuid4())

    assert denied.status_code == 404
    assert missing.status_code == 404
    assert denied.json() == missing.json()
    # DB 一字未动
    assert _thread_count(artifact) == before


@pytest.mark.parametrize(("name", "method"), _ENDPOINTS)
def test_doc_endpoints_pass_through_for_superuser(api_client, admin_user, name, method) -> None:
    """superuser 直通（与范围闸的 superuser 行对称）：非任何项目成员也能读。"""
    _make_project(_OTHER_PROJECT_ID)
    artifact = _make_artifact(project_id=_OTHER_PROJECT_ID)
    api_client.force_authenticate(user=admin_user)
    resp = _call(api_client, name, method, artifact.id)
    assert resp.status_code == 200


@pytest.mark.parametrize(("name", "method"), _ENDPOINTS)
def test_doc_endpoints_fail_closed_without_project_id(
    authenticated_client, name: str, method: str
) -> None:
    """⭐ 读不到合法 ``meta.project_id`` → **400** fail-closed（不是 404、更不是 200）。

    否则等于把闸门建在「蓝图恰好写了合法 project_id」这个可缺失字段上——攻击者只要拿一份
    ``project_id`` 是旧样例形状（非 UUID）的蓝图就能绕过整道闸。``project_id`` 是 schema 必填
    ⇒ 不可能造出缺该键的合法蓝图，用**非 UUID** 值复现同一条 fail-closed 分支。
    """
    artifact = _make_artifact(project_id="proj-0001")  # 非 UUID（旧样例形状）
    resp = _call(authenticated_client, name, method, artifact.id)
    assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════
# 4-5. 正文端点的取版本语义
# ═══════════════════════════════════════════════════════════════════════════


def test_document_defaults_to_the_latest_version(authenticated_client) -> None:
    artifact = _make_artifact()
    _add_version(artifact, marker="v2")
    latest = _add_version(artifact, marker="v3")

    resp = authenticated_client.get(_url("blueprint-document", artifact))

    assert resp.status_code == 200
    body = resp.json()
    assert body["version_id"] == str(latest.id)
    assert body["version_no"] == 3
    assert body["is_current"] is True
    assert str(Artifact.objects.get(id=artifact.id).current_version_id) == body["version_id"]
    # ⭐ 结构化 content（不是 markdown 串）：block 锚定与 block 级 diff 的物理前提
    assert body["content"]["schema_version"] == "blueprint/v1"
    assert body["content"]["meta"]["title"] == "v3"


def test_document_returns_history_version_with_is_current_false(authenticated_client) -> None:
    """⭐ ``?version_id=`` 取历史版本 ⇒ ``is_current is False``（判据是
    ``artifact.current_version_id``，不是「version_no 最大」二次推断）。"""
    artifact = _make_artifact()
    first = ArtifactVersion.objects.filter(artifact_id=artifact.id).order_by("version_no").first()
    _add_version(artifact, marker="v2")

    resp = authenticated_client.get(
        _url("blueprint-document", artifact), {"version_id": str(first.id)}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["version_id"] == str(first.id)
    assert body["version_no"] == 1
    assert body["is_current"] is False


def test_document_rejects_unknown_or_foreign_version_id(authenticated_client) -> None:
    artifact = _make_artifact()
    other = _make_artifact(title="别的蓝图")
    foreign = ArtifactVersion.objects.filter(artifact_id=other.id).first()

    unknown = authenticated_client.get(
        _url("blueprint-document", artifact), {"version_id": str(uuid.uuid4())}
    )
    borrowed = authenticated_client.get(
        _url("blueprint-document", artifact), {"version_id": str(foreign.id)}
    )
    malformed = authenticated_client.get(
        _url("blueprint-document", artifact), {"version_id": "notauuid"}
    )

    assert unknown.status_code == 404
    # 别的 artifact 的版本 id 一律 404：取版本必须同时约束 artifact_id
    assert borrowed.status_code == 404
    assert malformed.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════
# 6. ⭐ quality 三态并列（闭 114-MN-05）
# ═══════════════════════════════════════════════════════════════════════════


def test_quality_returns_null_for_missing_data_not_zero(authenticated_client) -> None:
    """⭐ 无数据源 → ``None``；有数据源但计数为零 → ``0``。**两者并列**才逮得住 ``or 0``。

    ``human_edit_volume`` 在同一响应里就是「有源零值」那一档（artifact 必有 v1 版本，但零
    人工编辑）—— 与两个 ``None`` 并排出现，任何「把 None 归一成 0」的改写都会让本用例转红。
    """
    artifact = _make_artifact()

    body = authenticated_client.get(_url("blueprint-document", artifact)).json()
    quality = body["quality"]

    # 无数据源 → None（⛔ 不是 0）
    assert quality["ai_rejection_rate"] is None
    assert quality["clarification_rounds"] is None
    # 有数据源（v1 已存在）但零人工编辑 → 0（真实零值）
    assert quality["human_edit_volume"] == 0
    # 纯函数恒有值：空引用缺口 → 1.0，⛔ 不为 None
    assert isinstance(quality["citation_coverage"], float)
    assert 0.0 <= quality["citation_coverage"] <= 1.0


def test_quality_returns_zero_for_a_thread_without_human_answers(authenticated_client) -> None:
    """同一指标的「零值」档：有线程但无人作答 → ``0``（而无线程时是 ``None``）。"""
    artifact = _make_artifact()
    _open_comment(artifact)

    quality = authenticated_client.get(_url("blueprint-document", artifact)).json()["quality"]

    assert quality["clarification_rounds"] == 0


def test_quality_returns_positive_values_when_data_exists(authenticated_client, user) -> None:
    artifact = _make_artifact()
    session = _make_session(artifact, user)
    now = timezone.now()
    _emit(session, EVENT_BLUEPRINT_REVIEW_COMPLETED, ts=now, payload={"review_status": "retry"})
    _emit(session, EVENT_BLUEPRINT_REVIEW_COMPLETED, ts=now, payload={"review_status": "passed"})
    _add_version(artifact, marker="human", produced_by_ref="human_edit:tester")
    thread = _open_comment(artifact)
    async_to_sync(BlueprintLifecycleService().record_answer)(
        thread, body="已按建议改", author=user, author_type=ThreadAuthorType.HUMAN
    )

    quality = authenticated_client.get(_url("blueprint-document", artifact)).json()["quality"]

    assert quality["ai_rejection_rate"] == pytest.approx(0.5)
    assert quality["human_edit_volume"] == 1
    assert quality["clarification_rounds"] == 1


def test_citation_coverage_is_one_for_an_empty_citation_pool(authenticated_client) -> None:
    """分母为 0 → ``1.0``（约定：不惩罚未写内容），⛔ 不返 None。"""
    # 三类关键结论条目全空 ⇒ citation_coverage 的分母为 0。⚠️ 清空 repo_associations 会让
    # 实现项/接口/流程的 repository_id 交叉校验失败 ⇒ 这几段一并清空（必填键保留）。
    content = make_blueprint(
        current_state_analysis=[],
        repo_associations=[],
        api_contracts=[],
        interaction_flows=[],
    )
    content["impact_analysis"]["affected_features"] = []
    content["implementation_overview"]["modules"] = []
    content["implementation_overview"]["items"] = []
    content["meta"]["project_id"] = _SCOPE_PROJECT_ID
    artifact = async_to_sync(ArtifactService().create)(
        "technical_plan", content, created_by_user_id="tester"
    )
    Artifact.objects.filter(id=artifact.id).update(blueprint_status=BlueprintStatus.DRAFTING)

    quality = authenticated_client.get(_url("blueprint-document", artifact)).json()["quality"]

    assert quality["citation_coverage"] == 1.0


# ═══════════════════════════════════════════════════════════════════════════
# 7-8. events 端点
# ═══════════════════════════════════════════════════════════════════════════


def test_events_returns_200_empty_structure_without_a_session(authenticated_client) -> None:
    """⭐ 无会话是**正常态**（蓝图还没跑过编排）⇒ 200 空结构，⛔ 不 404。

    404 会被前端的 404 分档吞成全页中性空态 ⇒ 生成中的蓝图看起来像「无权限」。
    """
    artifact = _make_artifact()

    resp = authenticated_client.get(_url("blueprint-events", artifact))

    assert resp.status_code == 200
    assert resp.json() == {"session_id": "", "current_stage": "", "events": []}


def test_events_only_exposes_blueprint_events_in_ts_order(authenticated_client, user) -> None:
    """只出 ``BLUEPRINT_EVENTS`` 子集、按 ``ts`` 严格升序（``ts`` 乱序写入 ⇒ 响应仍有序）。

    ⚠️ 断言集合引用 ``BLUEPRINT_EVENTS`` 常量本身，⛔ 不硬编码 21 条事件名（常量已被
    ``len(...) == 21`` 的既有用例锁死）。
    """
    artifact = _make_artifact()
    session = _make_session(artifact, user)
    now = timezone.now()
    _emit(session, EVENT_BLUEPRINT_STAGE_COMPLETED, ts=now)
    _emit(session, EVENT_BLUEPRINT_STAGE_STARTED, ts=now - timezone.timedelta(minutes=5))
    _emit(session, EVENT_BLUEPRINT_REVIEW_COMPLETED, ts=now - timezone.timedelta(minutes=1))
    # 非蓝图事件（同一会话上）：一律不出现
    _emit(session, EVENT_CLARIFICATION_ASKED, ts=now)
    _emit(session, EVENT_REPO_ROUTING, ts=now)

    body = authenticated_client.get(_url("blueprint-events", artifact)).json()

    assert body["session_id"] == str(session.id)
    assert body["current_stage"] == "ai_review"
    names = [row["event"] for row in body["events"]]
    assert names == [
        EVENT_BLUEPRINT_STAGE_STARTED,
        EVENT_BLUEPRINT_REVIEW_COMPLETED,
        EVENT_BLUEPRINT_STAGE_COMPLETED,
    ]
    assert set(names) <= BLUEPRINT_EVENTS
    stamps = [row["ts"] for row in body["events"]]
    assert stamps == sorted(stamps)


def test_events_ignores_the_legacy_technical_plan_session(authenticated_client, user) -> None:
    """⭐ 跨 process 污染证伪：另造一条**排序更靠前**（更新）的 ``technical_plan`` 会话，
    响应必须仍是蓝图会话的事件流（``_aload_session`` 自带 ``process_type`` 过滤）。"""
    artifact = _make_artifact()
    blueprint_session = _make_session(artifact, user)
    legacy = _make_session(artifact, user, process_type="technical_plan", current_stage="merge")
    now = timezone.now()
    _emit(blueprint_session, EVENT_BLUEPRINT_STAGE_STARTED, ts=now)
    _emit(legacy, EVENT_BLUEPRINT_STAGE_COMPLETED, ts=now)

    body = authenticated_client.get(_url("blueprint-events", artifact)).json()

    assert body["session_id"] == str(blueprint_session.id)
    assert body["current_stage"] == "ai_review"
    assert [row["event"] for row in body["events"]] == [EVENT_BLUEPRINT_STAGE_STARTED]


# ═══════════════════════════════════════════════════════════════════════════
# 9. threads GET —— 九键 + 三补键
# ═══════════════════════════════════════════════════════════════════════════

_THREAD_ROW_KEYS = {
    "thread_id",
    "kind",
    "severity",
    "status",
    "blocking",
    "anchor_status",
    "anchor",
    "return_stage",
    "created_at",
}


def test_threads_get_extends_the_nine_row_keys_with_three_more(authenticated_client, user) -> None:
    artifact = _make_artifact()
    thread = _open_comment(artifact)
    BlueprintThread.objects.filter(id=thread.id).update(
        options=[{"label": "选项 A", "value": "a", "note": "备注"}],
        last_reminded_at=timezone.now(),
    )
    async_to_sync(BlueprintLifecycleService().record_answer)(
        thread, body="收到", author=user, author_type=ThreadAuthorType.HUMAN
    )

    body = authenticated_client.get(_url("blueprint-review-threads", artifact)).json()

    assert len(body["threads"]) == 1
    row = body["threads"][0]
    # 原九键仍在（键集 ⊇ 九键）
    assert _THREAD_ROW_KEYS <= set(row)
    assert row["options"] == [{"label": "选项 A", "value": "a", "note": "备注"}]
    assert row["last_reminded_at"] is not None
    # 首条 AI 提问 + 人类回答，按 created_at 升序
    assert [m["author_type"] for m in row["messages"]] == ["ai", "human"]
    assert row["messages"][1]["author_display"] == user.username
    assert row["messages"][1]["author_user_id"] == str(user.id)
    assert row["anchor"]["block_id"] == _TEXT_BLOCK


def test_threads_get_normalizes_malformed_options_without_raising(authenticated_client) -> None:
    """``options`` 是 ``JSONField(default=list)`` **无 schema 校验** ⇒ 非法形状归一 ``[]``。"""
    artifact = _make_artifact()
    thread = _open_comment(artifact)
    BlueprintThread.objects.filter(id=thread.id).update(options={"x": 1})

    resp = authenticated_client.get(_url("blueprint-review-threads", artifact))

    assert resp.status_code == 200
    assert resp.json()["threads"][0]["options"] == []
    assert resp.json()["threads"][0]["last_reminded_at"] is None


def test_threads_get_tolerates_a_null_message_author(authenticated_client) -> None:
    """``author`` 是 ``SET_NULL`` FK（用户被删 / AI 作者）⇒ ``author_display`` 空串不炸。"""
    artifact = _make_artifact()
    thread = _open_comment(artifact)
    message = BlueprintThreadMessage.objects.filter(thread_id=thread.id).first()
    assert message.author_id is None  # 首条 AI 消息本就无作者

    resp = authenticated_client.get(_url("blueprint-review-threads", artifact))

    assert resp.status_code == 200
    row = resp.json()["threads"][0]["messages"][0]
    assert row["author_display"] == ""
    assert row["author_user_id"] is None


def test_threads_get_orders_threads_by_created_at(authenticated_client) -> None:
    """``BlueprintThread.Meta`` 无 ``ordering`` ⇒ 端点必须显式排序（114-MN-01）。"""
    artifact = _make_artifact()
    first = _open_comment(artifact, question="先提的")
    second = _open_comment(artifact, question="后提的")

    body = authenticated_client.get(_url("blueprint-review-threads", artifact)).json()

    assert [row["thread_id"] for row in body["threads"]] == [str(first.id), str(second.id)]


# ═══════════════════════════════════════════════════════════════════════════
# 10. threads POST —— 选区评论（CLAR-01 后半句）
# ═══════════════════════════════════════════════════════════════════════════


def test_threads_post_creates_a_human_comment_thread(authenticated_client, user) -> None:
    artifact = _make_artifact()
    latest = ArtifactVersion.objects.filter(artifact_id=artifact.id).order_by("-version_no").first()
    anchor = {
        "block_id": _TEXT_BLOCK,
        "section_path": "implementation_overview.items[impl_01].how",
        "start_offset": 0,
        "end_offset": 4,
        "quoted_text": "在练习域",
    }

    resp = authenticated_client.post(
        _url("blueprint-review-threads", artifact),
        {"body": "这段实现要拆两步", "anchor": anchor},
        format="json",
    )

    assert resp.status_code == 200
    thread_id = resp.json()["thread_id"]
    assert resp.json()["current_status"] == BlueprintStatus.PENDING_REVIEW
    # DB 重读（不信响应体）
    thread = BlueprintThread.objects.get(id=thread_id)
    assert thread.kind == ThreadKind.HUMAN_COMMENT
    assert thread.blocking is False
    assert thread.severity == ""
    assert thread.status == ThreadStatus.OPEN
    assert thread.anchor["block_id"] == _TEXT_BLOCK
    assert str(thread.created_on_version_id) == str(latest.id)
    assert thread.initiated_by_user_id == str(user.id)
    # 首条消息即评论正文（open_thread 线程行 + 首条消息同事务）
    assert BlueprintThreadMessage.objects.filter(thread_id=thread.id).count() == 1


@pytest.mark.parametrize("body", ["", "   ", None])
def test_threads_post_rejects_empty_body_without_touching_db(authenticated_client, body) -> None:
    artifact = _make_artifact()
    before = _thread_count(artifact)

    resp = authenticated_client.post(
        _url("blueprint-review-threads", artifact), {"body": body}, format="json"
    )

    assert resp.status_code == 400
    assert _thread_count(artifact) == before


def test_threads_post_rejects_a_non_editable_blueprint(authenticated_client) -> None:
    """⭐ 状态 ∉ 可编辑白名单 → 400 且线程数不变（与 answer / edit-blocks 同一张白名单）。"""
    artifact = _make_artifact(status=BlueprintStatus.CONFIRMED)
    before = _thread_count(artifact)

    resp = authenticated_client.post(
        _url("blueprint-review-threads", artifact), {"body": "确认后还想评论"}, format="json"
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == NOT_EDITABLE_DETAIL
    assert _thread_count(artifact) == before


def test_threads_post_accepts_a_comment_without_anchor(authenticated_client) -> None:
    """``anchor`` 非 dict 一律归一 ``None``（= 全局/段级评论，模型允许空 anchor）。"""
    artifact = _make_artifact()

    resp = authenticated_client.post(
        _url("blueprint-review-threads", artifact),
        {"body": "整体意见", "anchor": "不是 dict"},
        format="json",
    )

    assert resp.status_code == 200
    assert BlueprintThread.objects.get(id=resp.json()["thread_id"]).anchor is None


# ═══════════════════════════════════════════════════════════════════════════
# 11-12. 源码扫描（INV-6 视图零 ORM 写 + 范围闸 import 复用）
# ═══════════════════════════════════════════════════════════════════════════


def test_doc_views_never_write_orm_directly() -> None:
    """INV-6：``POST threads/`` 的落库全部委托 service，视图零 ORM 写。"""
    import re

    src = (SERVER_DIR / _VIEWS_REL).read_text(encoding="utf-8")
    write_call = re.compile(
        r"objects\.(?:a?create|a?bulk_create|a?get_or_create|a?update_or_create|a?update|delete)\b"
    )
    instantiate = re.compile(r"\b(?:BlueprintThread(?!Message)|BlueprintThreadMessage)\s*\(")

    assert not write_call.search(src), "视图内出现 ORM 写调用（落库必须走 service）"
    assert not instantiate.search(src), "视图内出现模型裸实例化（_RE_INSTANTIATE 也会逮）"
    assert "aopen_selection_comment" in src, "POST 必须委托 blueprint_comment_action"


def test_doc_views_reuse_the_project_scope_gate_by_import() -> None:
    """范围闸是 **import 复用**、不是复制第三份（MJ-03 的四条语义只能有一份实现）。"""
    src = (SERVER_DIR / _VIEWS_REL).read_text(encoding="utf-8")

    assert "from delivery.api.blueprint_review_views import" in src
    assert "async def _aassert_project_scope" not in src
    assert "async def _ais_project_member" not in src
    assert "async def _ablueprint_project_id" not in src
    # 四端点各调一次（threads 的 get/post 各算一次）
    assert src.count("await _aassert_project_scope(") == 4
