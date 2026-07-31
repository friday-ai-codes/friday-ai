"""蓝图列表端点 REST 测试（Phase 115-01 Task 3，VIEW-03 / VIEW-04）。

守九件事（断言一律**从 DB 重读 / 从响应体结构**，不信实现细节）：

1. 未认证一律拒（401/403）。
2. ⭐ **只列「我是成员的项目」的蓝图（正反并列）**：项目 A（我是成员）+ 项目 B（我不是）
   各一份蓝图 ⇒ ``total == 1`` 且只含 A；把我加进 B 的成员 ⇒ ``total == 2``（**证明断言
   非恒真**）。
3. **superuser 见全部**；**零成员项目 ⇒ 空结构 ``total == 0``**（fail-closed）。
4. ⭐ **状态为空串的旧 artifact 不出现**（v0 数据未进状态机 ⇒ 不是蓝图）。
5. ⭐ **响应键是 ``current_status``**（防回归：改回模型字段名 ⇒ INV-6 守卫同时转红，两者
   互为双保险）。
6. **分页五键与 ``has_next`` 边界**：25 条 ⇒ page1 ``has_next is True`` / 20 条；page2
   ``has_next is False`` / 5 条；``page_size=999`` clamp 到 100；``page=0`` / ``page=abc``
   fail-soft 取 1。
7. **``?q=`` 命中标题与摘要各一例**；不命中 ⇒ ``total == 0``。
8. **``?project_id=`` / ``?repository_id=`` / 状态筛选各一条**；非 UUID 的 ``project_id``
   ⇒ **400**。
9. **计数字段**：``thread_count`` 全量、``unresolved_blocker_count`` 只算未决
   （``open``/``answered`` 都算未决，已 ``resolved`` 的 blocker 不计）。
"""

from __future__ import annotations

import pytest
from asgiref.sync import async_to_sync
from django.urls import reverse

from delivery.models import (
    Artifact,
    BlueprintStatus,
    ThreadKind,
    ThreadSeverity,
    ThreadStatus,
)
from delivery.services import ArtifactService
from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService
from tests.helpers.blueprint_samples import make_blueprint

pytestmark = pytest.mark.django_db(transaction=True)

_SCOPE_PROJECT_ID = "11111111-1111-1111-1111-111111111111"
_OTHER_PROJECT_ID = "22222222-2222-2222-2222-222222222222"
_REPO_ID = "33333333-3333-3333-3333-333333333333"


def _make_project(project_id: str, *, member=None):
    """建一个 ``initiatives.Project``（可选授予成员）——列表可见性的判据源。"""
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
def _scope_project(user):
    return _make_project(_SCOPE_PROJECT_ID, member=user)


def _make_blueprint_artifact(
    *,
    project_id: str = _SCOPE_PROJECT_ID,
    status: str = BlueprintStatus.PENDING_REVIEW,
    title: str = "蓝图标题",
    summary: str = "执行摘要正文",
    repository_id: str | None = None,
) -> Artifact:
    content = make_blueprint()
    content["meta"]["project_id"] = project_id
    content["meta"]["summary"] = [
        {"block_id": "blk_meta_summary", "type": "paragraph", "text": summary}
    ]
    if repository_id is not None:
        content["repo_associations"][0]["repository_id"] = repository_id
        for item in content["implementation_overview"]["items"]:
            if item["repository_id"] == "repo-backend":
                item["repository_id"] = repository_id
        for module in content["implementation_overview"]["modules"]:
            module["repository_ids"] = [
                repository_id if rid == "repo-backend" else rid for rid in module["repository_ids"]
            ]
        for analysis in content["current_state_analysis"]:
            if analysis.get("repository_id") == "repo-backend":
                analysis["repository_id"] = repository_id
        for api in content["api_contracts"]:
            if api.get("repository_id") == "repo-backend":
                api["repository_id"] = repository_id
    artifact = async_to_sync(ArtifactService().create)(
        "technical_plan", content, title=title, created_by_user_id="tester"
    )
    Artifact.objects.filter(id=artifact.id).update(blueprint_status=status)
    return artifact


def _open_thread(
    artifact: Artifact,
    *,
    kind: str = ThreadKind.HUMAN_COMMENT,
    severity: str = "",
    blocking: bool = False,
    status: str = ThreadStatus.OPEN,
):
    thread = async_to_sync(BlueprintLifecycleService().open_thread)(
        artifact,
        kind=kind,
        blocking=blocking,
        severity=severity,
        question="问题",
        initiated_by_user_id="tester",
    )
    if status != ThreadStatus.OPEN:
        from delivery.models import BlueprintThread

        BlueprintThread.objects.filter(id=thread.id).update(status=status)
    return thread


def _list(client, **params):
    return client.get(reverse("blueprint-list"), params)


# ═══════════════════════════════════════════════════════════════════════════
# 1. 鉴权
# ═══════════════════════════════════════════════════════════════════════════


def test_blueprint_list_rejects_unauthenticated(api_client) -> None:
    assert _list(api_client).status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════════
# 2-3. 可见性（正反并列 + superuser + fail-closed）
# ═══════════════════════════════════════════════════════════════════════════


def test_blueprint_list_only_shows_projects_i_belong_to(authenticated_client, user) -> None:
    """⭐ 正反并列：只列成员项目的蓝图；把我加进另一个项目后条数从 1 变 2（断言非恒真）。"""
    _make_project(_OTHER_PROJECT_ID)  # 存在但 user 不是成员
    mine = _make_blueprint_artifact(title="我的蓝图")
    theirs = _make_blueprint_artifact(project_id=_OTHER_PROJECT_ID, title="别人的蓝图")

    body = _list(authenticated_client).json()

    assert body["total"] == 1
    assert [item["artifact_id"] for item in body["items"]] == [str(mine.id)]

    # 加入另一个项目后同一请求可见两条 ⇒ 上面的断言不是恒真
    _make_project(_OTHER_PROJECT_ID, member=user)
    after = _list(authenticated_client).json()

    assert after["total"] == 2
    assert {item["artifact_id"] for item in after["items"]} == {str(mine.id), str(theirs.id)}


def test_blueprint_list_passes_through_for_superuser(api_client, admin_user) -> None:
    _make_project(_OTHER_PROJECT_ID)
    _make_blueprint_artifact()
    _make_blueprint_artifact(project_id=_OTHER_PROJECT_ID)
    api_client.force_authenticate(user=admin_user)

    body = _list(api_client).json()

    assert body["total"] == 2


def test_blueprint_list_is_fail_closed_without_any_membership(api_client, second_user) -> None:
    """零可见项目 ⇒ 空结构（**零 DB 越权查询**），⛔ 不是「看见全部」。"""
    _make_blueprint_artifact()
    api_client.force_authenticate(user=second_user)

    body = _list(api_client).json()

    assert body["total"] == 0
    assert body["items"] == []
    assert body["has_next"] is False


# ═══════════════════════════════════════════════════════════════════════════
# 4-5. 候选面与键名
# ═══════════════════════════════════════════════════════════════════════════


def test_blueprint_list_excludes_v0_artifacts_without_blueprint_state(authenticated_client) -> None:
    """⭐ 状态为空串 = v0 旧数据未进状态机 ⇒ 不是蓝图，不出现在列表里。"""
    blueprint = _make_blueprint_artifact()
    legacy = _make_blueprint_artifact(status="", title="旧方案")

    body = _list(authenticated_client).json()

    assert [item["artifact_id"] for item in body["items"]] == [str(blueprint.id)]
    assert str(legacy.id) not in {item["artifact_id"] for item in body["items"]}


def test_blueprint_list_item_uses_current_status_key(authenticated_client) -> None:
    """⭐ 防回归：响应键必须是 ``current_status``。

    改回模型字段名会让 INV-6 的字段级守卫（字典键那条正则）同时转红——两条测试互为双保险，
    且本条给出的报错信息是「键名」而不是那句会误导人的「旁路写状态字段」。
    """
    _make_blueprint_artifact(status=BlueprintStatus.CONFIRMED)

    item = _list(authenticated_client).json()["items"][0]

    assert item["current_status"] == BlueprintStatus.CONFIRMED
    assert "blueprint_status" not in item


def test_blueprint_list_item_exposes_the_full_contract(authenticated_client) -> None:
    """条目键集逐字对齐前端契约（115-02 起的 TS 接口照它写）。"""
    _make_blueprint_artifact(repository_id=_REPO_ID)

    item = _list(authenticated_client).json()["items"][0]

    assert set(item) == {
        "artifact_id",
        "title",
        "summary",
        "current_status",
        "project_id",
        "project_name",
        "repositories",
        "thread_count",
        "unresolved_blocker_count",
        "revision_round",
        "current_version_no",
        "updated_at",
    }
    assert item["title"] == "蓝图标题"
    assert item["summary"] == "执行摘要正文"
    assert item["project_id"] == _SCOPE_PROJECT_ID
    assert item["project_name"] == "proj-11111111"
    assert item["revision_round"] == 0
    assert item["current_version_no"] == 1
    # 仓库名取不到（库里没有该 Repository 行）时回落 content 快照名，⛔ 不丢行
    assert {"id": _REPO_ID, "name": "onion-practice", "role": "direct"} in item["repositories"]


# ═══════════════════════════════════════════════════════════════════════════
# 6. 分页
# ═══════════════════════════════════════════════════════════════════════════


def test_blueprint_list_paginates_with_five_keys(authenticated_client) -> None:
    for idx in range(25):
        _make_blueprint_artifact(title=f"蓝图 {idx:02d}")

    first = _list(authenticated_client, page=1, page_size=20).json()
    second = _list(authenticated_client, page=2, page_size=20).json()

    assert set(first) == {"total", "items", "page", "page_size", "has_next"}
    assert first["total"] == 25
    assert len(first["items"]) == 20
    assert first["has_next"] is True
    assert second["page"] == 2
    assert len(second["items"]) == 5
    assert second["has_next"] is False
    # 两页不重叠（稳定排序）
    assert not {i["artifact_id"] for i in first["items"]} & {
        i["artifact_id"] for i in second["items"]
    }


def test_blueprint_list_clamps_and_fail_softs_page_params(authenticated_client) -> None:
    _make_blueprint_artifact()

    assert _list(authenticated_client, page_size=999).json()["page_size"] == 100
    assert _list(authenticated_client, page=0).json()["page"] == 1
    assert _list(authenticated_client, page="abc").json()["page"] == 1
    assert _list(authenticated_client, page_size="abc").json()["page_size"] == 20


# ═══════════════════════════════════════════════════════════════════════════
# 7-8. 筛选
# ═══════════════════════════════════════════════════════════════════════════


def test_blueprint_list_q_matches_title_and_summary(authenticated_client) -> None:
    """``?q=`` 命中标题与摘要各一例（摘要是 ``block_list``，取文本走 ``_block_text`` 口径）。"""
    by_title = _make_blueprint_artifact(title="习题生成能力", summary="与关键词无关的摘要")
    by_summary = _make_blueprint_artifact(title="与关键词无关的标题", summary="覆盖习题生成主链路")

    hit_title = _list(authenticated_client, q="习题生成能力").json()
    hit_summary = _list(authenticated_client, q="生成主链路").json()
    miss = _list(authenticated_client, q="根本不存在的词").json()

    assert [i["artifact_id"] for i in hit_title["items"]] == [str(by_title.id)]
    assert [i["artifact_id"] for i in hit_summary["items"]] == [str(by_summary.id)]
    assert miss["total"] == 0


def test_blueprint_list_filters_by_project_status_and_repository(
    authenticated_client, user
) -> None:
    _make_project(_OTHER_PROJECT_ID, member=user)
    mine = _make_blueprint_artifact(status=BlueprintStatus.DRAFTING, repository_id=_REPO_ID)
    other = _make_blueprint_artifact(project_id=_OTHER_PROJECT_ID, status=BlueprintStatus.CONFIRMED)

    by_project = _list(authenticated_client, project_id=_OTHER_PROJECT_ID).json()
    by_status = _list(authenticated_client, blueprint_status=BlueprintStatus.DRAFTING).json()
    by_repo = _list(authenticated_client, repository_id=_REPO_ID).json()

    assert [i["artifact_id"] for i in by_project["items"]] == [str(other.id)]
    assert [i["artifact_id"] for i in by_status["items"]] == [str(mine.id)]
    assert [i["artifact_id"] for i in by_repo["items"]] == [str(mine.id)]


@pytest.mark.parametrize("param", ["project_id", "repository_id"])
def test_blueprint_list_rejects_malformed_uuid_params(authenticated_client, param: str) -> None:
    resp = _list(authenticated_client, **{param: "notauuid"})
    assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════
# 9. 计数字段（ORM annotate 自算，⛔ 不 import lifecycle 的未决计数方法）
# ═══════════════════════════════════════════════════════════════════════════


def test_blueprint_list_counts_threads_and_unresolved_blockers(authenticated_client) -> None:
    artifact = _make_blueprint_artifact()
    _open_thread(artifact)  # 普通评论
    _open_thread(
        artifact,
        kind=ThreadKind.AI_REVIEW_FINDING,
        severity=ThreadSeverity.BLOCKER,
        blocking=True,
    )

    item = _list(authenticated_client).json()["items"][0]

    assert item["thread_count"] == 2
    assert item["unresolved_blocker_count"] == 1


def test_blueprint_list_excludes_resolved_blockers_from_unresolved(authenticated_client) -> None:
    """已 ``resolved`` 的 blocker 不计入未决（``open``/``answered`` 才算未决，与 confirm
    守卫口径对齐）。"""
    artifact = _make_blueprint_artifact()
    _open_thread(
        artifact,
        kind=ThreadKind.AI_REVIEW_FINDING,
        severity=ThreadSeverity.BLOCKER,
        blocking=True,
        status=ThreadStatus.RESOLVED,
    )
    _open_thread(
        artifact,
        kind=ThreadKind.AI_REVIEW_FINDING,
        severity=ThreadSeverity.BLOCKER,
        blocking=True,
        status=ThreadStatus.ANSWERED,
    )

    item = _list(authenticated_client).json()["items"][0]

    assert item["thread_count"] == 2
    # answered 仍算未决，resolved 不算
    assert item["unresolved_blocker_count"] == 1
