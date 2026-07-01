"""项目关系星图 artifact/关联扩展测试（Phase 99-01，KDEP-10）。

覆盖：
- artifact 节点 + HAS_ARTIFACT/ARTIFACT_REPO/ARTIFACT_CAPABILITY 边；
- 项目↔仓库关联来源并入 verified RepoAssociation（不再仅 MR），同 repo 只一条 USES_REPO；
- artifact/关联分支 best-effort（异常吞掉，既有星图仍完整返回）；
- artifact 节点纳入 max_nodes 预算，超限截断并标注 meta.truncated。
"""

from __future__ import annotations

import pytest

from initiatives.models import Artifact, ArtifactType, MergeRequest, ProjectVisibility
from initiatives.models import Project as InitiativeProject
from initiatives.models.repo_association import RepoAssociation, RepoAssociationStatus
from initiatives.views import _build_project_galaxy

pytestmark = pytest.mark.django_db


def _make_project(space) -> InitiativeProject:
    return InitiativeProject.objects.create(
        space=space,
        name="P",
        feishu_project_key="",
        visibility=ProjectVisibility.MEMBERS_ONLY,
    )


def _make_artifact(iproj, *, title="登录方案") -> Artifact:
    atype = ArtifactType.objects.create(
        key=f"prd-{iproj.id.hex[:8]}", name="PRD", carrier="markdown", ragable=True
    )
    return Artifact.objects.create(
        project=iproj, type=atype, carrier="markdown", title=title, version=1
    )


def test_builder_includes_artifact_nodes_and_edges(project, repository):
    iproj = _make_project(project)
    artifact = _make_artifact(iproj)
    assocs = {
        str(artifact.id): {
            "repositories": [
                {"repository_id": str(repository.id), "repo_name": "r"}
            ],
            "capabilities": ["a/b"],
        }
    }

    payload = _build_project_galaxy(iproj, {}, artifact_assocs=assocs)

    node_ids = {n["id"] for n in payload["nodes"]}
    assert f"artifact:{artifact.id}" in node_ids
    assert "capability:a/b" in node_ids
    assert f"repository:{repository.id}" in node_ids

    relations = {e["relation"] for e in payload["edges"]}
    assert {"HAS_ARTIFACT", "ARTIFACT_REPO", "ARTIFACT_CAPABILITY"} <= relations

    # capability 节点 label 取路径末段
    cap = next(n for n in payload["nodes"] if n["id"] == "capability:a/b")
    assert cap["label"] == "b"
    assert cap["path"] == "a/b"

    art_node = next(n for n in payload["nodes"] if n["id"] == f"artifact:{artifact.id}")
    assert art_node["type"] == "artifact"
    assert art_node["type_key"] == artifact.type.key
    assert art_node["carrier"] == "markdown"

    assert payload["meta"]["artifact_nodes"] == 1
    assert payload["meta"]["artifact_edges"] >= 3


def test_builder_uses_repo_from_verified_association_deduped(project, repository):
    iproj = _make_project(project)
    # verified 关联（无 MR）→ project→repo USES_REPO 边
    RepoAssociation.objects.create(
        project=iproj,
        repository=repository,
        status=RepoAssociationStatus.VERIFIED,
    )
    # 同 repo 亦有 MR 来源 → USES_REPO 应去重为一条
    MergeRequest.objects.create(
        project=iproj, repository=repository, platform="github", title="MR1"
    )

    payload = _build_project_galaxy(iproj, {})

    uses_repo = [
        e
        for e in payload["edges"]
        if e["relation"] == "USES_REPO"
        and e["target"] == f"repository:{repository.id}"
    ]
    assert len(uses_repo) == 1


def test_builder_uses_repo_only_from_association_when_no_mr(project, repository):
    iproj = _make_project(project)
    RepoAssociation.objects.create(
        project=iproj,
        repository=repository,
        status=RepoAssociationStatus.VERIFIED,
    )

    payload = _build_project_galaxy(iproj, {})

    targets = {
        e["target"]
        for e in payload["edges"]
        if e["relation"] == "USES_REPO"
    }
    assert f"repository:{repository.id}" in targets


def test_builder_fail_soft_keeps_base_galaxy(project, repository, monkeypatch):
    iproj = _make_project(project)
    _make_artifact(iproj)

    # 让 artifact 查询抛错 → 分支被吞掉，基础节点仍返回
    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(Artifact.objects, "filter", _boom)

    payload = _build_project_galaxy(iproj, {"modules": [{"name": "M", "features": [{"name": "F"}]}]})

    node_ids = {n["id"] for n in payload["nodes"]}
    assert f"project:{iproj.id}" in node_ids
    assert "feature:M/F" in node_ids
    # 未因 artifact 分支异常而抛出；artifact 节点缺席
    assert payload["meta"]["artifact_nodes"] == 0


def test_builder_truncates_including_artifacts(project, repository):
    iproj = _make_project(project)
    atype = ArtifactType.objects.create(
        key="prd", name="PRD", carrier="markdown", ragable=True
    )
    for i in range(5):
        Artifact.objects.create(
            project=iproj, type=atype, carrier="markdown", title=f"a{i}", version=1
        )

    # max_nodes=2 → project + 只能再容 1 个节点
    payload = _build_project_galaxy(iproj, {}, max_nodes=2)

    assert payload["meta"]["truncated"] is True
    assert len(payload["nodes"]) == 2
