"""MCP lookup_project_by_branch 守护测试（CURSOR-01 + BIND-02 显式多绑定）。

覆盖：
- happy（work_item 反查单命中 + 召回 + 写 RetrievalTrace）；
- 无法解析分支名 → fail-soft 空返回；
- 解析成功但无项目 → fail-soft 空候选；
- work_item 多命中 → fail-soft 候选列表（matched=False，不抛）；
- members_only 项目 + 非成员 → packer fail-closed 召回为空（matched 命中但 context 空，不泄漏）；
- public_org 项目 + 非成员 → WS-02 可读（matched 命中且 context 非空）；
- BIND-02：ProjectBranch 显式绑定单命中召回；双源指向同项目合并去重单命中；
  跨仓同名分支多绑定 fail-soft 多候选；repository_id 收窄到单命中；两源均无命中空候选。
- quick-260723 RepoAssociation 第三兜底源：人工命名分支 + repository_id 单命中召回；
  多关联仅候选；proposed 状态不计；分支源命中时兜底不介入。
"""

from __future__ import annotations

from typing import Any

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from delivery.services import WorkItemIdentity, WorkItemService
from initiatives.models import ProjectVisibility
from initiatives.services import ProjectBranchService, ProjectService
from interactions.models import RetrievalTrace
from projects.models import Space
from repositories.models import Repository

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()
_URL = "/api/mcp/tools/lookup_project_by_branch/"


@sync_to_async
def _make_space(key="lpb-space"):
    return Space.objects.create(name="S", feishu_project_key=key)


@sync_to_async
def _make_repo(name: str):
    return Repository.objects.create(name=name, git_url=f"https://git/{name}.git")


@sync_to_async
def _set_visibility(project, visibility):
    project.visibility = visibility
    project.save(update_fields=["visibility"])
    return project


async def _make_work_item(work_item_id: int, feishu_project_key="lpb-wpk"):
    return await WorkItemService().upsert(
        WorkItemIdentity(
            feishu_project_key=feishu_project_key,
            work_item_type="story",
            work_item_id=work_item_id,
        ),
        source="feishu_webhook",
        fetch=False,
    )


async def _make_project(created_by, key="lpb-board"):
    space = await _make_space(key=f"{key}-sp")
    project, _ = await ProjectService().create(
        space=space, name="P", feishu_project_key=key, created_by=created_by
    )
    return project


@sync_to_async
def _trace_count(source: str) -> int:
    # MCP 链 trace 的 source 落在 payload（基类 _record 不设 model.source 列）。
    return RetrievalTrace.objects.filter(payload__source=source).count()


async def test_happy_single_match_recall_and_trace(mcp_client, access_user) -> None:
    client, _ = mcp_client
    project = await _make_project(access_user, key="lpb-a")
    wi = await _make_work_item(1001)
    await ProjectService().attach_work_item(project_id=project.id, work_item=wi)

    resp = await sync_to_async(client.post)(
        _URL, {"branch_name": "feat/xxxx-m1001-add-login"}, format="json"
    )
    assert resp.status_code == 200
    body: dict[str, Any] = resp.json()
    assert body["matched"] is True
    assert body["work_item_id"] == 1001
    assert body["project"]["id"] == str(project.id)
    assert len(body["candidates"]) == 1
    # MCP 链 RetrievalTrace 已写（补齐 Phase-80 MCP 链）。
    assert await _trace_count("mcp_lookup_project_by_branch") >= 1


async def test_unparseable_branch_fail_soft(mcp_client) -> None:
    client, _ = mcp_client
    resp = await sync_to_async(client.post)(_URL, {"branch_name": "main"}, format="json")
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is False
    assert body["work_item_id"] is None
    assert body["candidates"] == []


async def test_parseable_no_project_fail_soft(mcp_client) -> None:
    client, _ = mcp_client
    resp = await sync_to_async(client.post)(
        _URL, {"branch_name": "feat/xxxx-m99999-nope"}, format="json"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is False
    assert body["work_item_id"] == 99999
    assert body["candidates"] == []


async def test_multi_match_fail_soft_candidates(mcp_client, access_user) -> None:
    client, _ = mcp_client
    p1 = await _make_project(access_user, key="lpb-m1")
    p2 = await _make_project(access_user, key="lpb-m2")
    # 同数字 work_item_id 不同 feishu_project_key → 两条 WorkItem → 两个项目命中。
    wi1 = await _make_work_item(2002, feishu_project_key="k1")
    wi2 = await _make_work_item(2002, feishu_project_key="k2")
    await ProjectService().attach_work_item(project_id=p1.id, work_item=wi1)
    await ProjectService().attach_work_item(project_id=p2.id, work_item=wi2)

    resp = await sync_to_async(client.post)(
        _URL, {"branch_name": "feat/xxxx-m2002-x"}, format="json"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is False  # 多命中绝不臆断
    assert len(body["candidates"]) == 2
    assert body["context"] == ""


async def test_non_member_members_only_failclosed_empty_context(mcp_client) -> None:
    """members_only 项目 + 非成员触发用户 → packer fail-closed 召回为空（不泄漏内容）。

    WS-02 后默认 visibility 为 public_org（非成员可读），故 fail-closed 必须以
    members_only 项目断言（不弱化 members_only 真·fail-closed 语义）。
    """
    client, _ = mcp_client
    other = await sync_to_async(User.objects.create_user)(username="other-owner-mo", password="x")
    project = await _make_project(other, key="lpb-nm-mo")
    await _set_visibility(project, ProjectVisibility.MEMBERS_ONLY)
    wi = await _make_work_item(3003)
    await ProjectService().attach_work_item(project_id=project.id, work_item=wi)

    resp = await sync_to_async(client.post)(
        _URL, {"branch_name": "feat/xxxx-m3003-x"}, format="json"
    )
    assert resp.status_code == 200
    body = resp.json()
    # 命中项目（候选可见），但 token 用户非成员 + members_only → packer fail-closed 零召回。
    assert body["matched"] is True
    assert body["context"] == ""


async def test_non_member_public_org_readable(mcp_client) -> None:
    """public_org 项目 + 非成员触发用户 → WS-02 可读（matched 且 context 非空）。"""
    client, _ = mcp_client
    other = await sync_to_async(User.objects.create_user)(username="other-owner-po", password="x")
    project = await _make_project(other, key="lpb-nm-po")
    # 默认 public_org；显式确保。
    await _set_visibility(project, ProjectVisibility.PUBLIC_ORG)
    wi = await _make_work_item(3004)
    await ProjectService().attach_work_item(project_id=project.id, work_item=wi)

    resp = await sync_to_async(client.post)(
        _URL, {"branch_name": "feat/xxxx-m3004-x"}, format="json"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is True
    # public_org 非成员可读 → 召回需求工件，context 非空（不再 fail-closed）。
    assert body["context"] != ""


# ---------------------------------------------------------------------------
# BIND-02：ProjectBranch 显式多绑定反查 + fail-soft 候选 + repository_id 收窄
# ---------------------------------------------------------------------------


async def test_branch_binding_single_match_recall_and_trace(mcp_client, access_user):
    """仅 ProjectBranch 显式绑定（分支名无 work_item_id）单命中 → 召回 + 写 RetrievalTrace。"""
    client, _ = mcp_client
    project = await _make_project(access_user, key="lpb-bind")
    repo = await _make_repo("bind-repo")
    branch = "feature/explicit-bind"
    await ProjectBranchService().bind(
        project_id=project.id,
        repository_id=repo.id,
        branch_name=branch,
        actor=access_user,
        initiated_by_user_id=access_user.id,
    )

    resp = await sync_to_async(client.post)(_URL, {"branch_name": branch}, format="json")
    assert resp.status_code == 200
    body = resp.json()
    assert body["work_item_id"] is None  # 分支名无 work_item，命中纯来自显式绑定
    assert body["matched"] is True
    assert body["project"]["id"] == str(project.id)
    assert len(body["candidates"]) == 1
    assert await _trace_count("mcp_lookup_project_by_branch") >= 1


async def test_both_sources_same_project_single_match(mcp_client, access_user):
    """work_item 反查 + ProjectBranch 绑定指向同一项目 → 合并去重后仍单命中（不变多命中）。"""
    client, _ = mcp_client
    project = await _make_project(access_user, key="lpb-both")
    repo = await _make_repo("both-repo")
    wi = await _make_work_item(4004)
    await ProjectService().attach_work_item(project_id=project.id, work_item=wi)
    branch = "feat/xxxx-m4004-both"
    await ProjectBranchService().bind(
        project_id=project.id,
        repository_id=repo.id,
        branch_name=branch,
        actor=access_user,
        initiated_by_user_id=access_user.id,
    )

    resp = await sync_to_async(client.post)(_URL, {"branch_name": branch}, format="json")
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is True
    assert len(body["candidates"]) == 1  # 双源同项目合并去重
    assert body["project"]["id"] == str(project.id)


async def test_cross_repo_multi_binding_fail_soft(mcp_client, access_user):
    """跨仓同名分支绑定多项目 + 不传 repository_id → fail-soft 多候选（matched=False，不抛）。"""
    client, _ = mcp_client
    p1 = await _make_project(access_user, key="lpb-x1")
    p2 = await _make_project(access_user, key="lpb-x2")
    r1 = await _make_repo("xrepo-1")
    r2 = await _make_repo("xrepo-2")
    branch = "shared/cross-repo-branch"
    svc = ProjectBranchService()
    await svc.bind(
        project_id=p1.id,
        repository_id=r1.id,
        branch_name=branch,
        actor=access_user,
        initiated_by_user_id=access_user.id,
    )
    await svc.bind(
        project_id=p2.id,
        repository_id=r2.id,
        branch_name=branch,
        actor=access_user,
        initiated_by_user_id=access_user.id,
    )

    resp = await sync_to_async(client.post)(_URL, {"branch_name": branch}, format="json")
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is False  # 多命中绝不臆断
    assert len(body["candidates"]) == 2
    assert body["context"] == ""


async def test_repository_id_narrows_to_single(mcp_client, access_user):
    """跨仓多绑定 + 传 repository_id → 收窄到单命中。"""
    client, _ = mcp_client
    p1 = await _make_project(access_user, key="lpb-n1")
    p2 = await _make_project(access_user, key="lpb-n2")
    r1 = await _make_repo("nrepo-1")
    r2 = await _make_repo("nrepo-2")
    branch = "shared/narrow-branch"
    svc = ProjectBranchService()
    await svc.bind(
        project_id=p1.id,
        repository_id=r1.id,
        branch_name=branch,
        actor=access_user,
        initiated_by_user_id=access_user.id,
    )
    await svc.bind(
        project_id=p2.id,
        repository_id=r2.id,
        branch_name=branch,
        actor=access_user,
        initiated_by_user_id=access_user.id,
    )

    resp = await sync_to_async(client.post)(
        _URL, {"branch_name": branch, "repository_id": str(r1.id)}, format="json"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["repository_id"] == str(r1.id)
    assert body["matched"] is True
    assert len(body["candidates"]) == 1
    assert body["project"]["id"] == str(p1.id)


async def test_no_match_any_source_empty_candidates(mcp_client, access_user):
    """work_item 反查与 ProjectBranch 均无命中 → 空候选 200（不抛、不阻断编码）。"""
    client, _ = mcp_client
    resp = await sync_to_async(client.post)(
        _URL, {"branch_name": "feature/never-bound-branch"}, format="json"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is False
    assert body["work_item_id"] is None
    assert body["candidates"] == []
    assert body["context"] == ""


async def test_requires_auth() -> None:
    from rest_framework.test import APIClient

    resp = await sync_to_async(APIClient().post)(
        _URL, {"branch_name": "feat/xxxx-m1-x"}, format="json"
    )
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# quick-260723：RepoAssociation 第三兜底源（人工命名分支的仓库级召回）
# ---------------------------------------------------------------------------


@sync_to_async
def _make_repo_association(project, repo, status):
    from initiatives.models import RepoAssociation

    return RepoAssociation.objects.create(project=project, repository=repo, status=status)


async def test_repo_association_fallback_single_match(mcp_client, access_user):
    """人工命名分支（两源无命中）+ repository_id + confirmed 关联 → 兜底单命中召回。"""
    from initiatives.models import RepoAssociationStatus

    client, _ = mcp_client
    project = await _make_project(access_user, key="lpb-ra1")
    repo = await _make_repo("ra-repo-1")
    await _make_repo_association(project, repo, RepoAssociationStatus.CONFIRMED)

    resp = await sync_to_async(client.post)(
        _URL,
        {"branch_name": "feat/login-page", "repository_id": str(repo.id)},
        format="json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["work_item_id"] is None  # 分支名无 work_item 段
    assert body["matched"] is True
    assert body["project"]["id"] == str(project.id)
    assert len(body["candidates"]) == 1


async def test_repo_association_fallback_multi_candidates(mcp_client, access_user):
    """仓库关联多个项目 → 兜底只回候选（matched=False，绝不臆断）。"""
    from initiatives.models import RepoAssociationStatus

    client, _ = mcp_client
    p1 = await _make_project(access_user, key="lpb-ra-m1")
    p2 = await _make_project(access_user, key="lpb-ra-m2")
    repo = await _make_repo("ra-repo-multi")
    await _make_repo_association(p1, repo, RepoAssociationStatus.CONFIRMED)
    await _make_repo_association(p2, repo, RepoAssociationStatus.VERIFIED)

    resp = await sync_to_async(client.post)(
        _URL,
        {"branch_name": "feature/manual-branch", "repository_id": str(repo.id)},
        format="json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is False
    assert len(body["candidates"]) == 2
    assert body["context"] == ""


async def test_repo_association_proposed_not_counted(mcp_client, access_user):
    """proposed（未经用户确认）状态的关联不参与兜底 → 空候选。"""
    from initiatives.models import RepoAssociationStatus

    client, _ = mcp_client
    project = await _make_project(access_user, key="lpb-ra-p")
    repo = await _make_repo("ra-repo-proposed")
    await _make_repo_association(project, repo, RepoAssociationStatus.PROPOSED)

    resp = await sync_to_async(client.post)(
        _URL,
        {"branch_name": "feature/unconfirmed", "repository_id": str(repo.id)},
        format="json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is False
    assert body["candidates"] == []


async def test_repo_association_not_used_when_branch_source_hits(mcp_client, access_user):
    """分支源（ProjectBranch 绑定）命中时兜底不介入——不把仓库关联的其他项目混进候选。"""
    from initiatives.models import RepoAssociationStatus

    client, _ = mcp_client
    p_bound = await _make_project(access_user, key="lpb-ra-b1")
    p_assoc = await _make_project(access_user, key="lpb-ra-b2")
    repo = await _make_repo("ra-repo-bound")
    branch = "feature/bound-branch"
    await ProjectBranchService().bind(
        project_id=p_bound.id,
        repository_id=repo.id,
        branch_name=branch,
        actor=access_user,
        initiated_by_user_id=access_user.id,
    )
    await _make_repo_association(p_assoc, repo, RepoAssociationStatus.CONFIRMED)

    resp = await sync_to_async(client.post)(
        _URL, {"branch_name": branch, "repository_id": str(repo.id)}, format="json"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is True
    assert body["project"]["id"] == str(p_bound.id)
    assert len(body["candidates"]) == 1
