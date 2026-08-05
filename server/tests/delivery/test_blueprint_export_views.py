"""蓝图飞书导出两端点 REST 测试（Phase 116-05 Task 2，VIEW-05）。

守十件事：

1. ⭐ **两端点未认证一律拒**（401/403，参数化两条）。
2. ⭐ **范围闸正反并列**：成员 200 / **非成员 404 且响应体与「artifact 不存在」逐字相同**
   / superuser 直通。两端点各跑一遍。
3. **读不到 ``meta.project_id`` ⇒ 400**（fail-closed，复用闸的既有语义）。
4. ⭐ **availability 判据链**：``no_space`` / ``no_folder_token`` / ``no_credentials`` /
   空间级凭证齐备 → ``true`` / 仅系统级凭证 → ``true``；⭐ **响应键集恰为两键**。
5. **availability 不满足时 POST ⇒ 400**（⛔ 不 500、⛔ 不静默 200 空结构）。
6. ⭐ **上游失败分档**：权限/资源不存在类 ⇒ **400**；限流/其它上游错误 ⇒ **502**；
   ⭐ 两档都断言响应体**不含**上游 body 的任何片段（构造含 ``secret-token-xyz`` 的上游
   错误文本）。
7. ⭐ **导出前后 ``ArtifactVersion`` 计数不变**且 ``current_version_id`` 不变
   （留痕⛔ 不写 content —— 本文件头号靶子）。
8. ⭐ **导出事件不在 ``BLUEPRINT_EVENTS`` 里**且该集合仍是 21；导出后
   ``ConvergenceSessionEvent`` 计数不变（⛔ 不污染阶段进展时间线）。
9. **成功路径四键**；⭐ 经 patch 捕获传给 ``create_document`` 的 markdown 实参断言
   未确认版本**带标注**、已确认版本**不带**。
10. **源码扫描**：范围闸是 import 复用不是复制；adrf + 零 DRF serializer；本文件零
    ``add_version`` / content 写；``BLUEPRINT_EVENTS`` 零命中。

REST client 是同步的 ⇒ 同步用例 + ``async_to_sync`` 装配（照 115-01）。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import async_to_sync
from django.urls import reverse

from delivery.models import Artifact, ArtifactVersion, BlueprintStatus, ConvergenceSessionEvent
from delivery.services import ArtifactService
from delivery.services.event_taxonomy import BLUEPRINT_EVENTS
from tests.helpers.blueprint_samples import make_blueprint

pytestmark = pytest.mark.django_db(transaction=True)

SERVER_DIR = Path(__file__).resolve().parents[2]
_VIEWS_REL = "delivery/api/blueprint_export_views.py"

_SCOPE_PROJECT_ID = "33333333-3333-3333-3333-333333333333"
_OTHER_PROJECT_ID = "44444444-4444-4444-4444-444444444444"
_UNRESOLVED_PROJECT_ID = "55555555-5555-5555-5555-555555555555"

# ⭐ 上游报错里夹带的凭证样本：断言它**不出现在响应体里**
_UPSTREAM_SECRET = "secret-token-xyz"

_ENDPOINTS = [
    ("blueprint-export-feishu", "post"),
    ("blueprint-export-feishu-availability", "get"),
]


# ── 工厂 ────────────────────────────────────────────────────────────────────


def _make_project(project_id: str, *, member: Any = None, **space_fields: Any) -> Any:
    from initiatives.models import Project, ProjectMember
    from projects.models import Space

    project = Project.objects.filter(id=project_id).first()
    if project is None:
        space = Space.objects.create(
            name=f"space-{project_id[:8]}", feishu_project_key=f"k-{project_id[:8]}"
        )
        project = Project.objects.create(id=project_id, space=space, name=f"proj-{project_id[:8]}")
    if space_fields:
        for key, value in space_fields.items():
            setattr(project.space, key, value)
        project.space.save()
    if member is not None:
        ProjectMember.objects.get_or_create(project=project, user=member)
    return project


@pytest.fixture(autouse=True)
def _project_scope(user) -> Any:
    """两端点全挂项目范围闸 ⇒ 样例蓝图必须落在测试用户所属的项目里。

    默认把空间配成「导出可用」（folder token + 空间级凭证齐备），不可用的分支各自覆写。
    """
    return _make_project(
        _SCOPE_PROJECT_ID,
        member=user,
        feishu_doc_folder_token="fld-1",
        feishu_app_id="cli_app",
        feishu_app_secret_encrypted="enc-secret",
    )


def _make_artifact(
    status: str = BlueprintStatus.PENDING_REVIEW,
    *,
    project_id: str | None = _SCOPE_PROJECT_ID,
    title: str = "导出样例蓝图",
) -> Artifact:
    content = make_blueprint()
    # ⚠️ ``meta.project_id`` 在 schema 里是必填 ⇒ 「读不到项目范围」的形态只能是**非 UUID**
    # 取值（闸的判据是 ``_is_uuid``，缺失与非法同归 fail-closed 400）。
    content["meta"]["project_id"] = "not-a-project-uuid" if project_id is None else project_id
    artifact = async_to_sync(ArtifactService().create)(
        "technical_plan", content, title=title, created_by_user_id="tester"
    )
    Artifact.objects.filter(id=artifact.id).update(blueprint_status=status)
    return Artifact.objects.get(id=artifact.id)


def _call(client: Any, name: str, method: str, artifact_id: Any, data: dict | None = None) -> Any:
    url = reverse(name, args=[str(artifact_id)])
    if method == "post":
        return client.post(url, data or {}, format="json")
    return client.get(url)


def _patch_doc_client(monkeypatch: pytest.MonkeyPatch, *, raises: Exception | None = None) -> Any:
    """把飞书 client 换成 mock；返回 ``create_document`` 的 AsyncMock 供捕获实参。"""
    import agents.tools.feishu_doc_tools as feishu_doc_tools

    create_document = AsyncMock()
    if raises is not None:
        create_document.side_effect = raises
    else:
        create_document.return_value = {
            "document_id": "doc-1",
            "url": "https://feishu.cn/docx/doc-1",
        }

    class _FakeClient:
        def __init__(self) -> None:
            self.create_document = create_document

    async def _fake_factory(space: Any) -> Any:
        return _FakeClient()

    monkeypatch.setattr(feishu_doc_tools, "create_feishu_doc_client_for_project", _fake_factory)
    return create_document


# ═══════════════════════════════════════════════════════════════════════════
# 1. 鉴权
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(("name", "method"), _ENDPOINTS)
def test_export_endpoints_reject_unauthenticated(api_client, name: str, method: str) -> None:
    resp = _call(api_client, name, method, uuid.uuid4())
    assert resp.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════════
# 2-3. 范围闸（正反并列 + fail-closed）
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(("name", "method"), _ENDPOINTS)
def test_export_endpoints_allow_project_members(
    authenticated_client, monkeypatch, name: str, method: str
) -> None:
    _patch_doc_client(monkeypatch)
    artifact = _make_artifact()
    resp = _call(authenticated_client, name, method, artifact.id)
    assert resp.status_code == 200


@pytest.mark.parametrize(("name", "method"), _ENDPOINTS)
def test_export_endpoints_return_neutral_404_for_non_members(
    authenticated_client, monkeypatch, name: str, method: str
) -> None:
    """⭐ 非成员 → 404 **且响应体与「artifact 不存在」逐字相同**（不泄露存在性）。"""
    _patch_doc_client(monkeypatch)
    _make_project(_OTHER_PROJECT_ID)
    artifact = _make_artifact(project_id=_OTHER_PROJECT_ID)

    denied = _call(authenticated_client, name, method, artifact.id)
    missing = _call(authenticated_client, name, method, uuid.uuid4())

    assert denied.status_code == 404
    assert missing.status_code == 404
    assert denied.json() == missing.json()


@pytest.mark.parametrize(("name", "method"), _ENDPOINTS)
def test_export_endpoints_pass_through_for_superuser(
    api_client, admin_user, monkeypatch, name: str, method: str
) -> None:
    _patch_doc_client(monkeypatch)
    api_client.force_authenticate(user=admin_user)
    artifact = _make_artifact()
    resp = _call(api_client, name, method, artifact.id)
    assert resp.status_code == 200


@pytest.mark.parametrize(("name", "method"), _ENDPOINTS)
def test_export_endpoints_fail_closed_without_project_id(
    authenticated_client, name: str, method: str
) -> None:
    """读不到 ``meta.project_id`` ⇒ **400**，绝不放行。"""
    artifact = _make_artifact(project_id=None)
    resp = _call(authenticated_client, name, method, artifact.id)
    assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════
# 4. availability 判据链（前端据它隐藏按钮）
# ═══════════════════════════════════════════════════════════════════════════


def test_availability_returns_exactly_two_keys(authenticated_client) -> None:
    """⭐ ``{available, reason}`` 两键逐字：键名一改前端就不再隐藏按钮。"""
    artifact = _make_artifact()
    body = _call(
        authenticated_client, "blueprint-export-feishu-availability", "get", artifact.id
    ).json()
    assert set(body) == {"available", "reason"}


def test_availability_true_with_space_level_credentials(authenticated_client) -> None:
    artifact = _make_artifact()
    body = _call(
        authenticated_client, "blueprint-export-feishu-availability", "get", artifact.id
    ).json()
    assert body == {"available": True, "reason": None}


def test_availability_true_with_system_level_credentials(authenticated_client, monkeypatch) -> None:
    """空间级凭证缺失但系统级可得 ⇒ 同样 ``true``（回退链与 chat 面同源）。"""
    _make_project(_SCOPE_PROJECT_ID, feishu_app_id="", feishu_app_secret_encrypted="")
    import agents.tools.feishu_doc_tools as feishu_doc_tools

    monkeypatch.setattr(
        feishu_doc_tools,
        "_aget_system_feishu_credentials_for_doc",
        AsyncMock(return_value=("sys_app", "sys_secret")),
    )
    artifact = _make_artifact()
    body = _call(
        authenticated_client, "blueprint-export-feishu-availability", "get", artifact.id
    ).json()
    assert body == {"available": True, "reason": None}


def test_availability_no_folder_token(authenticated_client) -> None:
    _make_project(_SCOPE_PROJECT_ID, feishu_doc_folder_token="")
    artifact = _make_artifact()
    body = _call(
        authenticated_client, "blueprint-export-feishu-availability", "get", artifact.id
    ).json()
    assert body == {"available": False, "reason": "no_folder_token"}


def test_availability_no_credentials(authenticated_client, monkeypatch) -> None:
    _make_project(_SCOPE_PROJECT_ID, feishu_app_id="", feishu_app_secret_encrypted="")
    import agents.tools.feishu_doc_tools as feishu_doc_tools

    monkeypatch.setattr(
        feishu_doc_tools,
        "_aget_system_feishu_credentials_for_doc",
        AsyncMock(return_value=None),
    )
    artifact = _make_artifact()
    body = _call(
        authenticated_client, "blueprint-export-feishu-availability", "get", artifact.id
    ).json()
    assert body == {"available": False, "reason": "no_credentials"}


def test_availability_no_space_when_project_unresolved(api_client, admin_user) -> None:
    """蓝图指向一个不存在的项目 ⇒ ``no_space``（superuser 直通范围闸才够得到这条分支）。"""
    api_client.force_authenticate(user=admin_user)
    artifact = _make_artifact(project_id=_UNRESOLVED_PROJECT_ID)
    body = _call(api_client, "blueprint-export-feishu-availability", "get", artifact.id).json()
    assert body == {"available": False, "reason": "no_space"}


# ═══════════════════════════════════════════════════════════════════════════
# 5-6. 上游失败如实回错（⛔ 不静默 200、⛔ 不回显上游 body）
# ═══════════════════════════════════════════════════════════════════════════


def test_export_returns_400_when_availability_not_satisfied(authenticated_client) -> None:
    """⛔ 不 500、⛔ 不 200 空结构：配置没到位就是一次可解释的 400。"""
    _make_project(_SCOPE_PROJECT_ID, feishu_doc_folder_token="")
    artifact = _make_artifact()
    resp = _call(authenticated_client, "blueprint-export-feishu", "post", artifact.id)
    assert resp.status_code == 400
    assert "detail" in resp.json()


@pytest.mark.parametrize("exc_name", ["PermissionDeniedError", "DocumentNotFoundError"])
def test_upstream_permission_and_not_found_map_to_400(
    authenticated_client, monkeypatch, exc_name: str
) -> None:
    import services.feishu_doc as feishu_doc

    exc_type = getattr(feishu_doc, exc_name)
    _patch_doc_client(monkeypatch, raises=exc_type(f"无权限访问文档: {_UPSTREAM_SECRET}"))
    artifact = _make_artifact()

    resp = _call(authenticated_client, "blueprint-export-feishu", "post", artifact.id)

    assert resp.status_code == 400
    assert _UPSTREAM_SECRET not in resp.content.decode("utf-8")


@pytest.mark.parametrize("exc_name", ["RateLimitError", "FeishuDocAPIError"])
def test_upstream_rate_limit_and_generic_map_to_502(
    authenticated_client, monkeypatch, exc_name: str
) -> None:
    import services.feishu_doc as feishu_doc

    exc_type = getattr(feishu_doc, exc_name)
    _patch_doc_client(monkeypatch, raises=exc_type(f"Rate limit hit: {_UPSTREAM_SECRET}"))
    artifact = _make_artifact()

    resp = _call(authenticated_client, "blueprint-export-feishu", "post", artifact.id)

    assert resp.status_code == 502
    assert _UPSTREAM_SECRET not in resp.content.decode("utf-8")


def test_upstream_failure_is_never_a_silent_200(authenticated_client, monkeypatch) -> None:
    """115-MJ-04 的反面教材：⛔ 上游炸了不许回 200 空结构。"""
    import services.feishu_doc as feishu_doc

    _patch_doc_client(monkeypatch, raises=feishu_doc.FeishuDocAPIError("boom"))
    artifact = _make_artifact()
    resp = _call(authenticated_client, "blueprint-export-feishu", "post", artifact.id)
    assert resp.status_code != 200


# ═══════════════════════════════════════════════════════════════════════════
# 7-8. 留痕不污染任何既有面
# ═══════════════════════════════════════════════════════════════════════════


def test_export_does_not_create_a_new_artifact_version(authenticated_client, monkeypatch) -> None:
    """⭐ 头号靶子：留痕写进 content 会让每次导出翻一个版本、把版本历史刷成噪声。"""
    _patch_doc_client(monkeypatch)
    artifact = _make_artifact()
    before_count = ArtifactVersion.objects.filter(artifact_id=artifact.id).count()
    before_current = Artifact.objects.get(id=artifact.id).current_version_id
    before_hash = ArtifactVersion.objects.get(id=before_current).content_hash

    resp = _call(authenticated_client, "blueprint-export-feishu", "post", artifact.id)
    assert resp.status_code == 200

    assert ArtifactVersion.objects.filter(artifact_id=artifact.id).count() == before_count
    assert Artifact.objects.get(id=artifact.id).current_version_id == before_current
    assert ArtifactVersion.objects.get(id=before_current).content_hash == before_hash


def test_export_event_is_not_in_blueprint_events(authenticated_client, monkeypatch) -> None:
    """⭐ 导出事件不进 taxonomy：集合大小双断言 + 不混进阶段进展时间线。

    ⚠️ 这里的数字是 ``BLUEPRINT_EVENTS`` 的**当前基数**（118 加了 6 个活动事件 ⇒ 21 → 27），
    权威断言在 ``test_blueprint_event_taxonomy_112.test_blueprint_events_shape``。本条真正
    要守的是「导出事件**不在**集合里」那一句，基数只是顺带的漂移哨兵。
    """
    _patch_doc_client(monkeypatch)
    artifact = _make_artifact()
    before_events = ConvergenceSessionEvent.objects.count()

    resp = _call(authenticated_client, "blueprint-export-feishu", "post", artifact.id)
    assert resp.status_code == 200

    assert "blueprint_exported_to_feishu" not in BLUEPRINT_EVENTS
    assert len(BLUEPRINT_EVENTS) == 27
    assert ConvergenceSessionEvent.objects.count() == before_events


def test_export_writes_an_interaction_ledger_run(authenticated_client, monkeypatch) -> None:
    """留痕的正向对照：确实落了 Interaction Ledger（⛔ 不是「哪都没记」）。"""
    from interactions.models import InteractionEvent, InteractionRun

    _patch_doc_client(monkeypatch)
    artifact = _make_artifact()

    resp = _call(authenticated_client, "blueprint-export-feishu", "post", artifact.id)
    assert resp.status_code == 200

    run = InteractionRun.objects.filter(source="blueprint_export").order_by("-created_at").first()
    assert run is not None
    event = InteractionEvent.objects.filter(run=run).first()
    assert event is not None
    assert event.payload.get("document_id") == "doc-1"
    assert event.payload.get("event") == "blueprint_exported_to_feishu"


# ═══════════════════════════════════════════════════════════════════════════
# 9. 成功路径 + 标注真的进了导出物
# ═══════════════════════════════════════════════════════════════════════════


def test_export_success_returns_four_keys(authenticated_client, monkeypatch) -> None:
    _patch_doc_client(monkeypatch)
    artifact = _make_artifact()
    body = _call(authenticated_client, "blueprint-export-feishu", "post", artifact.id).json()
    assert set(body) == {"document_id", "url", "version_no", "exported_at"}
    assert body["document_id"] == "doc-1"
    assert body["url"] == "https://feishu.cn/docx/doc-1"
    assert body["version_no"] >= 1


@pytest.mark.parametrize(
    ("status", "expects_watermark"),
    [
        (BlueprintStatus.PENDING_REVIEW, True),
        (BlueprintStatus.CONFIRMED, False),
    ],
)
def test_exported_markdown_carries_the_watermark_for_unconfirmed(
    authenticated_client, monkeypatch, status: str, expects_watermark: bool
) -> None:
    """⭐ 导出端点传的是**真实状态**（⛔ 不是注册表那条恒 ``""`` 的 fail-safe 路径）。"""
    create_document = _patch_doc_client(monkeypatch)
    artifact = _make_artifact(status)

    resp = _call(authenticated_client, "blueprint-export-feishu", "post", artifact.id)
    assert resp.status_code == 200

    markdown = create_document.await_args.kwargs["content"]
    assert ("未经确认" in markdown) is expects_watermark
    # 十段结构真的在（⛔ 不是在导出器里就地拼的空壳）
    assert "## 需求规格" in markdown
    assert "## 决策记录" in markdown


def test_export_accepts_explicit_version_id(authenticated_client, monkeypatch) -> None:
    _patch_doc_client(monkeypatch)
    artifact = _make_artifact()
    version = ArtifactVersion.objects.filter(artifact_id=artifact.id).first()
    body = _call(
        authenticated_client,
        "blueprint-export-feishu",
        "post",
        artifact.id,
        {"version_id": str(version.id)},
    ).json()
    assert body["version_no"] == version.version_no


def test_export_rejects_malformed_and_foreign_version_id(authenticated_client, monkeypatch) -> None:
    _patch_doc_client(monkeypatch)
    artifact = _make_artifact()
    bad = _call(
        authenticated_client, "blueprint-export-feishu", "post", artifact.id, {"version_id": "nope"}
    )
    assert bad.status_code == 400
    absent = _call(
        authenticated_client,
        "blueprint-export-feishu",
        "post",
        artifact.id,
        {"version_id": str(uuid.uuid4())},
    )
    assert absent.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# 10. 源码扫描（惯例不靠人肉复核）
# ═══════════════════════════════════════════════════════════════════════════


def _views_source() -> str:
    return (SERVER_DIR / _VIEWS_REL).read_text(encoding="utf-8")


def _views_identifiers() -> set[str]:
    """AST 里真正被**用到**的标识符集合。

    ⚠️ 不用字符串扫描：本模块的 docstring 与分节注释里逐字写着这些禁令（「⛔ 不进
    ``BLUEPRINT_EVENTS``」），文本判据会把「写清楚为什么不做」判成「做了」。
    """
    import ast

    tree = ast.parse(_views_source())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add((node.asname or node.name).split(".")[-1])
    return names


def test_scope_gate_is_imported_not_copied() -> None:
    source = _views_source()
    assert "from delivery.api.blueprint_review_views import" in source
    assert "_aassert_project_scope" in source
    assert "_ARTIFACT_MISSING_DETAIL" in source
    assert "async def _aassert_project_scope" not in source, "⛔ 不得复制第四份范围闸"


def test_views_use_adrf_and_no_drf_serializer() -> None:
    source = _views_source()
    assert "from adrf.views import APIView" in source
    assert "from rest_framework.views import APIView" not in source
    assert "Serializer" not in source, "本 View 家族全域手写 dict builder"
    assert source.count("permission_classes = [IsAuthenticated]") == 2


def test_views_never_write_artifact_content_or_taxonomy() -> None:
    identifiers = _views_identifiers()
    assert "add_version" not in identifiers, "⛔ 留痕绝不翻版本"
    assert "BLUEPRINT_EVENTS" not in identifiers, "⛔ 导出事件不进 21 常量集合"
    assert "ConvergenceSessionEvent" not in identifiers, "⛔ 不污染阶段进展时间线"
    assert "ArtifactVersion.objects.create" not in _views_source()


def test_views_redact_upstream_error_text() -> None:
    source = _views_source()
    assert "redact_secrets_in_text" in source, "异常文本必须脱敏"
    assert "HTTP_502_BAD_GATEWAY" in source, "缺 502 分档"
    assert "HTTP_400_BAD_REQUEST" in source, "缺 400 分档"
