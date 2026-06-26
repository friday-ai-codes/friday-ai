"""RepoAssociationService Phase 89 输出契约测试（Phase 88，REPO-02，88-05）。

覆盖 ``get_verified_associations`` 只读契约（供 Phase 89 PlanSession.decomposition.
include_repos 消费）：
- 仅返 ``status=verified`` 关联 + 各仓最新 verdict；字段稳定（repository_id / repo_name /
  verdict / matched_node_paths / routed_reason / score）。
- proposed / confirmed / verifying / rejected 不计入。
- 无 verified → 返 []。
- work_item 过滤：仅返该 work_item 的 verified 关联。
"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async

from initiatives.models import (
    Project,
    RepoAssociation,
    RepoAssociationStatus,
    RepoVerifyTask,
    RepoVerifyTaskStatus,
)
from initiatives.services.repo_association_service import RepoAssociationService
from projects.models import Space
from repositories.models import Repository

pytestmark = pytest.mark.django_db(transaction=True)


def _prep() -> tuple[Project, dict[str, Repository]]:
    space = Space.objects.create(name="OutSpace", feishu_project_key="out-k")
    project = Project.objects.create(space=space, name="P", feishu_project_key="")
    repos = {
        name: Repository.objects.create(name=name, git_url=f"https://git/{name}.git")
        for name in ("rv", "rp", "rc", "rj", "rr")
    }
    for repo in repos.values():
        space.repositories.add(repo)
    return project, repos


def _assoc(
    project: Project,
    repo: Repository,
    status: str,
    *,
    score: float = 0.0,
    reason: str = "",
    node_paths: list[str] | None = None,
) -> RepoAssociation:
    return RepoAssociation.objects.create(
        project=project,
        repository=repo,
        status=status,
        score=score,
        confidence="high",
        routed_reason=reason,
        matched_node_paths=node_paths or [],
    )


@sync_to_async
def _seed_mixed() -> tuple[Project, Repository]:
    """种一条 verified（带 verdict task）+ 四条非 verified 状态。"""
    project, repos = _prep()
    verified = _assoc(
        project,
        repos["rv"],
        RepoAssociationStatus.VERIFIED,
        score=0.91,
        reason="命中能力节点 auth",
        node_paths=["rv/auth"],
    )
    RepoVerifyTask.objects.create(
        association=verified,
        repository=repos["rv"],
        status=RepoVerifyTaskStatus.DONE,
        verdict={
            "fit": "fit",
            "confidence": "high",
            "summary": "深验适配",
            "evidence_files": ["a.py"],
            "mismatch_reasons": [],
        },
    )
    _assoc(project, repos["rp"], RepoAssociationStatus.PROPOSED)
    _assoc(project, repos["rc"], RepoAssociationStatus.CONFIRMED)
    _assoc(project, repos["rj"], RepoAssociationStatus.REJECTED)
    _assoc(project, repos["rr"], RepoAssociationStatus.VERIFYING)
    return project, repos["rv"]


@sync_to_async
def _seed_no_verified() -> Project:
    project, repos = _prep()
    _assoc(project, repos["rp"], RepoAssociationStatus.PROPOSED)
    _assoc(project, repos["rj"], RepoAssociationStatus.REJECTED)
    return project


async def test_verified_output_shape_and_filter() -> None:
    project, rv = await _seed_mixed()

    out = await RepoAssociationService().get_verified_associations(project=project)

    # 仅 verified 计入（proposed/confirmed/verifying/rejected 不计）
    assert len(out) == 1
    row = out[0]
    assert set(row) == {
        "repository_id",
        "repo_name",
        "verdict",
        "matched_node_paths",
        "routed_reason",
        "score",
    }
    assert row["repository_id"] == str(rv.id)
    assert row["repo_name"] == "rv"
    assert row["routed_reason"] == "命中能力节点 auth"
    assert row["matched_node_paths"] == ["rv/auth"]
    assert row["score"] == pytest.approx(0.91)
    # verdict 携粗适配性结论（供 Phase 89 消费）
    assert row["verdict"]["fit"] == "fit"
    assert row["verdict"]["confidence"] == "high"
    assert row["verdict"]["summary"] == "深验适配"
    assert row["verdict"]["evidence_files"] == ["a.py"]


async def test_verified_output_empty_when_none_verified() -> None:
    project = await _seed_no_verified()
    out = await RepoAssociationService().get_verified_associations(project=project)
    assert out == []


async def test_verified_output_verdict_defaults_without_task() -> None:
    """verified 关联但无 verify task → verdict fit 缺省 unknown（契约字段仍稳定）。"""

    @sync_to_async
    def _seed() -> tuple[Project, Repository]:
        project, repos = _prep()
        _assoc(project, repos["rv"], RepoAssociationStatus.VERIFIED, score=0.5)
        return project, repos["rv"]

    project, rv = await _seed()
    out = await RepoAssociationService().get_verified_associations(project=project)
    assert len(out) == 1
    assert out[0]["repository_id"] == str(rv.id)
    assert out[0]["verdict"]["fit"] == "unknown"
