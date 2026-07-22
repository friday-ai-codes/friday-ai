"""ProjectStateApi 上报后 STATE 文档物化钩子守护测试（KNOW-06，102-02 Task 4）。

范式照抄 ``test_memory_materialize_hook.py``：断言 ``ProjectDocService.upsert_state_api``
成功后按 (project, STATE) 反查 doc_id 调度 ``aschedule_ingestion``（``source_kind=
"project_doc"``、归因透传）；无 STATE 文档（工作区未 provision）静默跳过；调度失败
fail-soft 绝不反噬上报主流程。

mock ``aschedule_ingestion``（不触发 normalize/embedding/Qdrant），``--disable-socket``
第二道保险。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async

from initiatives.models import DocType, ProjectDoc
from initiatives.services import ProjectDocService

pytestmark = pytest.mark.django_db(transaction=True)


@sync_to_async
def _make_project(key: str) -> Any:
    from initiatives.models import Project
    from projects.models import Space

    space = Space.objects.create(name=f"S-{key}")
    return Project.objects.create(space=space, name="P", feishu_project_key=key)


@sync_to_async
def _make_state_doc(project: Any) -> Any:
    return ProjectDoc.objects.create(project=project, doc_type=DocType.STATE)


async def test_upsert_state_api_schedules_state_doc_materialization() -> None:
    project = await _make_project("sam-hook")
    doc = await _make_state_doc(project)
    mock_schedule = AsyncMock()
    with patch("knowledge.ingestion.aschedule_ingestion", mock_schedule):
        api, created = await ProjectDocService().upsert_state_api(
            project_id=project.id,
            method="GET",
            path="/api/x",
            initiated_by_user_id="user-42",
        )

    assert created is True
    mock_schedule.assert_awaited()
    call = mock_schedule.await_args_list[-1]
    assert call.args[0].source_kind == "project_doc"
    assert call.args[0].source_id == str(doc.id)
    assert call.kwargs["initiated_by_user_id"] == "user-42"


async def test_upsert_state_api_without_state_doc_skips_silently() -> None:
    """工作区未 provision（无 STATE ProjectDoc）→ 静默跳过物化调度，不抛。"""
    project = await _make_project("sam-nodoc")
    mock_schedule = AsyncMock()
    with patch("knowledge.ingestion.aschedule_ingestion", mock_schedule):
        api, created = await ProjectDocService().upsert_state_api(
            project_id=project.id, method="POST", path="/api/y"
        )

    assert created is True
    assert api.path == "/api/y"
    mock_schedule.assert_not_awaited()


async def test_upsert_state_api_defer_materialize_skips_scheduling() -> None:
    """defer_materialize=True（批量路径）→ 逐条不调度物化（102-REVIEW MED-01）。"""
    project = await _make_project("sam-defer")
    await _make_state_doc(project)
    mock_schedule = AsyncMock()
    with patch("knowledge.ingestion.aschedule_ingestion", mock_schedule):
        api, created = await ProjectDocService().upsert_state_api(
            project_id=project.id,
            method="GET",
            path="/api/deferred",
            defer_materialize=True,
        )

    assert created is True
    mock_schedule.assert_not_awaited()


async def test_schedule_state_materialization_coalesced_entry() -> None:
    """批量调用方循环后调 schedule_state_materialization 一次 → 恰调度一次物化。"""
    project = await _make_project("sam-coalesce")
    doc = await _make_state_doc(project)
    mock_schedule = AsyncMock()
    with patch("knowledge.ingestion.aschedule_ingestion", mock_schedule):
        await ProjectDocService().schedule_state_materialization(
            project.id, "user-99"
        )

    assert mock_schedule.await_count == 1
    call = mock_schedule.await_args_list[0]
    assert call.args[0].source_id == str(doc.id)
    assert call.kwargs["initiated_by_user_id"] == "user-99"


async def test_materialization_failure_does_not_break_upsert() -> None:
    """物化调度失败 fail-soft：upsert 仍正常返回（_schedule_materialization 吞异常）。"""
    project = await _make_project("sam-fail")
    await _make_state_doc(project)
    with patch(
        "knowledge.ingestion.aschedule_ingestion",
        new=AsyncMock(side_effect=RuntimeError("摄取调度炸了")),
    ):
        api, created = await ProjectDocService().upsert_state_api(
            project_id=project.id, method="DELETE", path="/api/z"
        )

    assert created is True
    assert api.method == "DELETE"


async def test_doc_id_lookup_failure_does_not_break_upsert() -> None:
    """doc_id 反查瞬时 DB 异常也 fail-soft：API 行已写入，upsert 不抛（102-REVIEW LO-04）。"""
    project = await _make_project("sam-lookup-fail")
    await _make_state_doc(project)
    with patch(
        "initiatives.services.project_doc_service.ProjectDoc.objects.filter",
        side_effect=RuntimeError("DB 瞬时抖动"),
    ):
        api, created = await ProjectDocService().upsert_state_api(
            project_id=project.id, method="PATCH", path="/api/lookup-fail"
        )

    assert created is True
    assert api.path == "/api/lookup-fail"
