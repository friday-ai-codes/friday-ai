from __future__ import annotations

import uuid
from io import StringIO
from unittest.mock import AsyncMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from initiatives.management.commands.propose_project_repos import Command
from initiatives.models import Project
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def project() -> Project:
    space = Space.objects.create(name="学习工具")
    return Project.objects.create(space=space, name="高三提分专项")


def test_dry_run_prints_scope_without_proposing(project: Project) -> None:
    out = StringIO()
    corpus = AsyncMock(return_value=[{"module": "练习", "name": "错题本"}])
    propose = AsyncMock()
    with (
        patch(
            "initiatives.services.context_link_service.ContextLinkService._afeature_corpus",
            corpus,
        ),
        patch(
            "initiatives.services.repo_association_service.RepoAssociationService.propose",
            propose,
        ),
    ):
        call_command(
            "propose_project_repos",
            str(project.id),
            "--initiated-by-user-id",
            "owner-1",
            "--dry-run",
            stdout=out,
        )

    assert "[DRY-RUN]" in out.getvalue()
    assert "feature_count=1" in out.getvalue()
    propose.assert_not_awaited()


def test_propose_uses_repo_association_service(project: Project) -> None:
    out = StringIO()
    corpus = AsyncMock(return_value=[{"module": "练习", "name": "错题本"}])
    propose = AsyncMock(
        return_value={
            "candidates": [
                {
                    "repo_id": "repo-1",
                    "repo_name": "practice-service",
                    "score": 0.91,
                    "confidence": "high",
                    "reason": "匹配练习模块",
                }
            ]
        }
    )
    with (
        patch(
            "initiatives.services.context_link_service.ContextLinkService._afeature_corpus",
            corpus,
        ),
        patch(
            "initiatives.services.repo_association_service.RepoAssociationService.propose",
            propose,
        ),
    ):
        call_command(
            "propose_project_repos",
            str(project.id),
            "--initiated-by-user-id",
            "owner-1",
            stdout=out,
        )

    assert "practice-service" in out.getvalue()
    kwargs = propose.await_args.kwargs
    assert kwargs["project"].id == project.id
    assert kwargs["space"].id == project.space_id
    assert kwargs["initiated_by_user_id"] == "owner-1"
    assert kwargs["features_flat"] == [{"module": "练习", "name": "错题本"}]


def test_confirm_uses_service_for_all_candidates(project: Project) -> None:
    propose = AsyncMock(
        return_value={
            "candidates": [
                {"repo_id": "repo-1", "repo_name": "one"},
                {"repo_id": "repo-2", "repo_name": "two"},
            ]
        }
    )
    confirm = AsyncMock(return_value=[])
    with (
        patch(
            "initiatives.services.context_link_service.ContextLinkService._afeature_corpus",
            AsyncMock(return_value=[]),
        ),
        patch(
            "initiatives.services.repo_association_service.RepoAssociationService.propose",
            propose,
        ),
        patch(
            "initiatives.services.repo_association_service.RepoAssociationService.confirm_repos",
            confirm,
        ),
    ):
        call_command(
            "propose_project_repos",
            str(project.id),
            "--initiated-by-user-id",
            "owner-1",
            "--confirm",
        )

    assert confirm.await_args.kwargs["repo_ids"] == ["repo-1", "repo-2"]
    assert confirm.await_args.kwargs["initiated_by_user_id"] == "owner-1"


def test_missing_initiated_by_user_id_raises(project: Project) -> None:
    with pytest.raises(CommandError):
        call_command("propose_project_repos", str(project.id))


def test_invalid_project_id_raises() -> None:
    with pytest.raises(CommandError, match="合法 UUID"):
        call_command(
            "propose_project_repos",
            "not-a-uuid",
            "--initiated-by-user-id",
            "owner-1",
        )


def test_unknown_project_raises() -> None:
    with pytest.raises(CommandError, match="项目不存在"):
        call_command(
            "propose_project_repos",
            str(uuid.uuid4()),
            "--initiated-by-user-id",
            "owner-1",
        )


def test_help_lists_arguments() -> None:
    output = Command().create_parser("manage.py", "propose_project_repos").format_help()
    assert "project_id" in output
    assert "--initiated-by-user-id" in output
    assert "--dry-run" in output
    assert "--confirm" in output
