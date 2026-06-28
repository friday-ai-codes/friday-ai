"""ArchitectMerge 模型守护测试（Phase 40-01，DOMAIN §6）。

model-only 守护（不触 40-02 融合 service/adapter，用 ORM 直建——tests/ 不受 INV-6
grep 守护约束）：覆盖默认态（fail-closed）/ CASCADE / 软引用可空 / makemigrations 零漂移。
"""

from __future__ import annotations

import uuid

import pytest
from django.core.management import call_command

from delivery.models import (
    ArchitectMerge,
    ArchitectMergeStatus,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
)


def _make_session() -> ConvergenceSession:
    return ConvergenceSession.objects.create(entrypoint=ConvergenceSessionEntrypoint.CHAT)


@pytest.mark.django_db
def test_architect_merge_defaults() -> None:
    """默认 status=failed（fail-closed）、attempt=0、report={}、软引用 None、时间戳非空。"""
    session = _make_session()
    merge = ArchitectMerge.objects.create(session=session)

    assert merge.validation_status == ArchitectMergeStatus.FAILED
    assert merge.attempt == 0
    assert merge.validation_report == {}
    assert merge.merged_artifact_version is None
    assert merge.created_at is not None


@pytest.mark.django_db
def test_architect_merge_passed_with_version() -> None:
    """passed 态可写入 merged_artifact_version 软引用（UUID）。"""
    session = _make_session()
    version_id = uuid.uuid4()
    merge = ArchitectMerge.objects.create(
        session=session,
        validation_status=ArchitectMergeStatus.PASSED,
        merged_artifact_version=version_id,
        attempt=1,
    )

    assert merge.validation_status == ArchitectMergeStatus.PASSED
    assert merge.merged_artifact_version == version_id
    assert merge.attempt == 1


@pytest.mark.django_db
def test_cascade_session_delete() -> None:
    """删 ConvergenceSession → 关联 ArchitectMerge 级联删除（CASCADE）。"""
    session = _make_session()
    merge = ArchitectMerge.objects.create(session=session)
    merge_id = merge.id

    session.delete()
    assert not ArchitectMerge.objects.filter(id=merge_id).exists()


@pytest.mark.django_db
def test_makemigrations_clean() -> None:
    """migration 0014 与模型零漂移：makemigrations --check --dry-run 不抛 SystemExit。"""
    call_command("makemigrations", "delivery", "--check", "--dry-run")
