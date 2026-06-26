"""ProjectBranch 模型守护测试（Phase 85，BIND-01）。

覆盖：唯一约束 (project, repository, branch_name) DB 层生效（重复 IntegrityError）、
同项目不同仓/不同分支可并存、source 默认 manual。
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from initiatives.models import BranchSource, Project, ProjectBranch
from projects.models import Space
from repositories.models import Repository

pytestmark = pytest.mark.django_db(transaction=True)


def _make_project(key: str = "branch-k") -> Project:
    space = Space.objects.create(name="BranchSpace", feishu_project_key=key)
    return Project.objects.create(space=space, name="P", feishu_project_key="")


def _make_repo(name: str = "repo") -> Repository:
    return Repository.objects.create(name=name, git_url=f"https://git/{name}.git")


def test_unique_project_repo_branch_enforced() -> None:
    project = _make_project()
    repo = _make_repo()
    ProjectBranch.objects.create(
        project=project, repository=repo, branch_name="feature/x"
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ProjectBranch.objects.create(
                project=project, repository=repo, branch_name="feature/x"
            )


def test_same_project_different_repo_or_branch_coexist() -> None:
    project = _make_project()
    repo1 = _make_repo("repo1")
    repo2 = _make_repo("repo2")
    ProjectBranch.objects.create(
        project=project, repository=repo1, branch_name="feature/x"
    )
    # 不同分支可并存
    ProjectBranch.objects.create(
        project=project, repository=repo1, branch_name="feature/y"
    )
    # 不同仓库同分支名可并存
    ProjectBranch.objects.create(
        project=project, repository=repo2, branch_name="feature/x"
    )
    assert ProjectBranch.objects.filter(project=project).count() == 3


def test_source_defaults_to_manual() -> None:
    project = _make_project()
    repo = _make_repo()
    binding = ProjectBranch.objects.create(
        project=project, repository=repo, branch_name="main"
    )
    assert binding.source == BranchSource.MANUAL
