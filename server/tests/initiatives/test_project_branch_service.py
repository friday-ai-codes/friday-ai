"""ProjectBranchService 守护测试（Phase 85，BIND-01，INV-6 写收口）。

覆盖：bind 幂等（重复不产重复行/不抛）、unbind 不存在返回 False 不抛、非成员
bind/unbind fail-closed、bind/unbind 审计 emit、initiated_by_user_id 归因落审计 metadata。
"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from audit.models import AuditEvent
from audit.services import taxonomy
from initiatives.models import BranchSource, ProjectBranch
from initiatives.services import (
    ProjectBranchPermissionError,
    ProjectBranchService,
    ProjectService,
)
from projects.models import Space
from repositories.models import Repository

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


@sync_to_async
def _make_user(username: str):
    return User.objects.create_user(username=username, password="x")


@sync_to_async
def _make_repo(name: str = "repo"):
    return Repository.objects.create(name=name, git_url=f"https://git/{name}.git")


async def _make_project_with_member():
    space = await sync_to_async(Space.objects.create)(name="S", feishu_project_key="bs-k")
    owner = await _make_user("branch_owner")
    project, _ = await ProjectService().create(
        space=space, name="P", feishu_project_key="branch-svc-k", created_by=owner
    )
    return project, owner


@sync_to_async
def _branch_count(project_id, repository_id, branch_name) -> int:
    return ProjectBranch.objects.filter(
        project_id=project_id, repository_id=repository_id, branch_name=branch_name
    ).count()


@sync_to_async
def _latest_audit(action: str):
    return (
        AuditEvent.objects.filter(action=action).order_by("-occurred_at").first()
    )


async def test_bind_is_idempotent():
    project, owner = await _make_project_with_member()
    repo = await _make_repo()
    svc = ProjectBranchService()
    b1 = await svc.bind(
        project_id=project.id,
        repository_id=repo.id,
        branch_name="feature/x",
        actor=owner,
        initiated_by_user_id=owner.id,
    )
    b2 = await svc.bind(
        project_id=project.id,
        repository_id=repo.id,
        branch_name="feature/x",
        actor=owner,
        initiated_by_user_id=owner.id,
    )
    assert b1.id == b2.id
    assert await _branch_count(project.id, repo.id, "feature/x") == 1


async def test_unbind_missing_returns_false():
    project, owner = await _make_project_with_member()
    repo = await _make_repo()
    removed = await ProjectBranchService().unbind(
        project_id=project.id,
        repository_id=repo.id,
        branch_name="nope",
        actor=owner,
        initiated_by_user_id=owner.id,
    )
    assert removed is False


async def test_unbind_removes_existing():
    project, owner = await _make_project_with_member()
    repo = await _make_repo()
    svc = ProjectBranchService()
    await svc.bind(
        project_id=project.id,
        repository_id=repo.id,
        branch_name="feature/x",
        actor=owner,
        initiated_by_user_id=owner.id,
    )
    removed = await svc.unbind(
        project_id=project.id,
        repository_id=repo.id,
        branch_name="feature/x",
        actor=owner,
        initiated_by_user_id=owner.id,
    )
    assert removed is True
    assert await _branch_count(project.id, repo.id, "feature/x") == 0


async def test_non_member_cannot_bind_or_unbind_fail_closed():
    project, _owner = await _make_project_with_member()
    repo = await _make_repo()
    stranger = await _make_user("branch_stranger")
    svc = ProjectBranchService()
    with pytest.raises(ProjectBranchPermissionError):
        await svc.bind(
            project_id=project.id,
            repository_id=repo.id,
            branch_name="feature/x",
            actor=stranger,
        )
    with pytest.raises(ProjectBranchPermissionError):
        await svc.unbind(
            project_id=project.id,
            repository_id=repo.id,
            branch_name="feature/x",
            actor=stranger,
        )


async def test_bind_emits_audit_with_attribution():
    project, owner = await _make_project_with_member()
    repo = await _make_repo()
    await ProjectBranchService().bind(
        project_id=project.id,
        repository_id=repo.id,
        branch_name="feature/x",
        actor=owner,
        initiated_by_user_id=owner.id,
    )
    event = await _latest_audit(taxonomy.ACTION_PROJECT_BRANCH_BOUND)
    assert event is not None
    assert event.metadata.get("initiated_by_user_id") == str(owner.id)
    assert event.metadata.get("component") == "initiatives"
    assert event.metadata.get("category") == "caller"


async def test_unbind_emits_audit():
    project, owner = await _make_project_with_member()
    repo = await _make_repo()
    svc = ProjectBranchService()
    await svc.bind(
        project_id=project.id,
        repository_id=repo.id,
        branch_name="feature/x",
        actor=owner,
        initiated_by_user_id=owner.id,
    )
    await svc.unbind(
        project_id=project.id,
        repository_id=repo.id,
        branch_name="feature/x",
        actor=owner,
        initiated_by_user_id=owner.id,
    )
    event = await _latest_audit(taxonomy.ACTION_PROJECT_BRANCH_UNBOUND)
    assert event is not None
    assert event.metadata.get("initiated_by_user_id") == str(owner.id)


async def test_source_drift_backfilled_on_rebind():
    project, owner = await _make_project_with_member()
    repo = await _make_repo()
    svc = ProjectBranchService()
    await svc.bind(
        project_id=project.id,
        repository_id=repo.id,
        branch_name="feature/x",
        source=BranchSource.MANUAL,
        actor=owner,
        initiated_by_user_id=owner.id,
    )
    # 流水线复绑（成员闸跳过，模拟 Phase 89 seam）按需回填 source 漂移。
    rebound = await svc.bind(
        project_id=project.id,
        repository_id=repo.id,
        branch_name="feature/x",
        source=BranchSource.CODING,
        _skip_member_check=True,
    )
    assert rebound.source == BranchSource.CODING
    assert await _branch_count(project.id, repo.id, "feature/x") == 1
