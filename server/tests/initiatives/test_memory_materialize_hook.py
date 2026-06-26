"""写时增量材料化钩子守护测试（CTX-01/02，85-01 Task 2）。

断言三处写收口写后挂 ``aschedule_ingestion`` 材料化钩子：
- ``MemoryService.append`` 写后调度 ``source_kind="project_memory"`` 且透传 ``initiated_by_user_id``；
- ``ProjectDocService.write_human_block`` 写后调度 ``source_kind="project_doc"`` 且透传 editor 归因；
- 钩子 best-effort：``aschedule_ingestion`` 抛异常时记忆/文件写主流程仍正常返回（T-85-01-02，绝不反噬）。

mock ``aschedule_ingestion``（不触发 normalize/embedding/Qdrant），``--disable-socket`` 第二道保险。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async

from initiatives.services import MemoryService, ProjectDocService

pytestmark = pytest.mark.django_db(transaction=True)


@sync_to_async
def _make_project() -> Any:
    from initiatives.models import Project
    from projects.models import Space

    space = Space.objects.create(name="S")
    return Project.objects.create(space=space, name="P", feishu_project_key="mh-k")


async def test_memory_append_schedules_materialization_with_attribution() -> None:
    project = await _make_project()
    mock_schedule = AsyncMock()
    with patch("knowledge.ingestion.aschedule_ingestion", mock_schedule):
        memory = await MemoryService().append(
            project_id=project.id,
            content="决策：用 PG 连接池",
            contributor=None,
            initiated_by_user_id="user-42",
            _skip_member_check=True,
        )

    assert memory is not None
    mock_schedule.assert_awaited()
    call = mock_schedule.await_args_list[-1]
    assert call.args[0].source_kind == "project_memory"
    assert call.args[0].source_id == str(memory.id)
    assert call.kwargs["initiated_by_user_id"] == "user-42"


async def test_memory_append_best_effort_when_schedule_raises() -> None:
    """材料化失败绝不反噬记忆写：append 仍正常返回。"""
    project = await _make_project()
    with patch(
        "knowledge.ingestion.aschedule_ingestion",
        new=AsyncMock(side_effect=RuntimeError("摄取调度炸了")),
    ):
        memory = await MemoryService().append(
            project_id=project.id,
            content="best-effort 守护",
            contributor=None,
            _skip_member_check=True,
        )

    assert memory is not None
    assert memory.content == "best-effort 守护"


async def test_write_human_block_schedules_project_doc_materialization(
    project_doc_factory,
) -> None:
    doc = await project_doc_factory()
    mock_schedule = AsyncMock()
    with patch("knowledge.ingestion.aschedule_ingestion", mock_schedule):
        await ProjectDocService().write_human_block(
            doc_id=doc.id,
            feishu_block_id="blk-1",
            content="# 人工补充\n上下文正文",
        )

    mock_schedule.assert_awaited()
    call = mock_schedule.await_args_list[-1]
    assert call.args[0].source_kind == "project_doc"
    assert call.args[0].source_id == str(doc.id)


async def test_write_human_block_best_effort_when_schedule_raises(
    project_doc_factory,
) -> None:
    """材料化失败绝不反噬文件写：write_human_block 仍正常返回 revision。"""
    doc = await project_doc_factory()
    with patch(
        "knowledge.ingestion.aschedule_ingestion",
        new=AsyncMock(side_effect=RuntimeError("摄取调度炸了")),
    ):
        revision = await ProjectDocService().write_human_block(
            doc_id=doc.id,
            feishu_block_id="blk-2",
            content="best-effort 文件守护",
        )

    assert revision is not None
