"""RepoCodingTask 模型守护测试（Phase 44-01，DOMAIN §6/§14）。

model-only 守护（不触 plan 03 的 RepoCodingTaskService，用 ORM 直建——tests/ 不受
INV-6 grep 守护约束）：覆盖默认态 / db_table / 4 态枚举（无 stale）/ depends_on
有向 self-M2M / Meta 索引。
"""

from __future__ import annotations

import uuid

import pytest

from delivery.models import (
    Artifact,
    ArtifactVersion,
    RepoCodingTask,
    RepoCodingTaskStatus,
)
from repositories.models import Repository


def _make_repo() -> Repository:
    return Repository.objects.create(
        name=f"repo-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/test/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )


def _make_artifact_version() -> ArtifactVersion:
    plan = Artifact.objects.create(artifact_type="technical_plan")
    return ArtifactVersion.objects.create(artifact=plan, version_no=1, content={"a": 1})


@pytest.mark.django_db
def test_repo_coding_task_defaults() -> None:
    """默认 status=pending、wave=0、attempt=0、produced_artifacts={}、follow_openspec=False、error={}。"""
    artifact_version = _make_artifact_version()
    repo = _make_repo()
    task = RepoCodingTask.objects.create(artifact_version=artifact_version, repository=repo)

    assert task.status == RepoCodingTaskStatus.PENDING
    assert task.wave == 0
    assert task.attempt == 0
    assert task.produced_artifacts == {}
    assert task.follow_openspec is False
    assert task.error == {}
    assert task.subagent_session is None
    assert task.created_at is not None
    assert task.updated_at is not None


@pytest.mark.django_db
def test_db_table_and_status_choices() -> None:
    """db_table 为 delivery_repo_coding_task；状态值集恰为 4 态（无 stale）。"""
    assert RepoCodingTask._meta.db_table == "delivery_repo_coding_task"
    values = {s.value for s in RepoCodingTaskStatus}
    assert values == {"pending", "running", "done", "failed"}
    assert "stale" not in values


@pytest.mark.django_db
def test_depends_on_is_directed_self_m2m() -> None:
    """depends_on 是 symmetrical=False 有向 self-M2M——A→B 不蕴含 B→A。"""
    artifact_version = _make_artifact_version()
    repo_a = _make_repo()
    repo_b = _make_repo()
    task_a = RepoCodingTask.objects.create(artifact_version=artifact_version, repository=repo_a)
    task_b = RepoCodingTask.objects.create(artifact_version=artifact_version, repository=repo_b)

    task_a.depends_on.add(task_b)

    assert list(task_a.depends_on.all()) == [task_b]
    assert list(task_b.dependents.all()) == [task_a]
    # 有向性：B 不依赖 A
    assert list(task_b.depends_on.all()) == []
    assert task_a not in task_b.depends_on.all()


@pytest.mark.django_db
def test_meta_indexes() -> None:
    """Meta.indexes 含 (artifact_version,wave,status) 与 (repository) 两组字段。"""
    index_field_sets = {tuple(idx.fields) for idx in RepoCodingTask._meta.indexes}
    assert ("artifact_version", "wave", "status") in index_field_sets
    assert ("repository",) in index_field_sets
