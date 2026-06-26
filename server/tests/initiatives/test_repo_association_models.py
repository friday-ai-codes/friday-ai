"""RepoAssociation / RepoVerifyTask 模型守护测试（Phase 88，REPO-01/02）。

覆盖：
- 唯一约束 ``(project, repository)`` DB 层生效（重复 IntegrityError）；
- ``RepoAssociation.status`` 默认 ``proposed``；
- ``RepoVerifyTask.verdict``/``error`` 默认空 dict、``status`` 默认 ``pending``；
- ``SubAgentSession.TaskType.REPO_VERIFY`` 枚举存在；
- 两个新 call_source（``repo_verify_container`` / ``repo_association``）normalize 命中不回退。
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from agents.call_source import CallSource
from initiatives.models import (
    Project,
    RepoAssociation,
    RepoAssociationStatus,
    RepoVerifyTask,
    RepoVerifyTaskStatus,
)
from projects.models import Space
from repositories.models import Repository
from subagent.models import SubAgentSession

pytestmark = pytest.mark.django_db(transaction=True)


def _make_project(key: str = "assoc-k") -> Project:
    space = Space.objects.create(name="AssocSpace", feishu_project_key=key)
    return Project.objects.create(space=space, name="P", feishu_project_key="")


def _make_repo(name: str = "repo") -> Repository:
    return Repository.objects.create(name=name, git_url=f"https://git/{name}.git")


def test_unique_project_repository_enforced() -> None:
    project = _make_project()
    repo = _make_repo()
    RepoAssociation.objects.create(project=project, repository=repo)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            RepoAssociation.objects.create(project=project, repository=repo)


def test_same_project_different_repo_coexist() -> None:
    project = _make_project()
    repo1 = _make_repo("repo1")
    repo2 = _make_repo("repo2")
    RepoAssociation.objects.create(project=project, repository=repo1)
    RepoAssociation.objects.create(project=project, repository=repo2)
    assert RepoAssociation.objects.filter(project=project).count() == 2


def test_association_status_defaults_to_proposed() -> None:
    project = _make_project()
    repo = _make_repo()
    assoc = RepoAssociation.objects.create(project=project, repository=repo)
    assert assoc.status == RepoAssociationStatus.PROPOSED
    assert assoc.source == "router_v2"
    assert assoc.score == 0.0
    assert assoc.matched_node_paths == []
    assert assoc.initiated_by_user_id == "system"


def test_verify_task_defaults() -> None:
    project = _make_project()
    repo = _make_repo()
    assoc = RepoAssociation.objects.create(project=project, repository=repo)
    task = RepoVerifyTask.objects.create(association=assoc, repository=repo)
    assert task.status == RepoVerifyTaskStatus.PENDING
    assert task.verdict == {}
    assert task.error == {}
    assert task.attempt == 0
    assert task.subagent_session is None
    # related_name verify_tasks 反查
    assert list(assoc.verify_tasks.all()) == [task]


def test_verify_task_status_mirrors_research_states() -> None:
    assert RepoVerifyTaskStatus.PENDING == "pending"
    assert RepoVerifyTaskStatus.RUNNING == "running"
    assert RepoVerifyTaskStatus.DONE == "done"
    assert RepoVerifyTaskStatus.FAILED == "failed"
    assert RepoVerifyTaskStatus.STALE == "stale"


def test_subagent_task_type_repo_verify_exists() -> None:
    assert SubAgentSession.TaskType.REPO_VERIFY == "repo_verify"


def test_new_call_sources_normalize() -> None:
    assert CallSource.normalize("repo_verify_container") == "repo_verify_container"
    assert CallSource.normalize("repo_association") == "repo_association"
    assert CallSource.REPO_VERIFY_CONTAINER.value == "repo_verify_container"
    assert CallSource.REPO_ASSOCIATION.value == "repo_association"
