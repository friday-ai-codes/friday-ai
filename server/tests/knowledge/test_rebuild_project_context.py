"""rebuild_project_context 兜底全量重建守护测试（CTX-01/02，85-01）。

断言：
- 命令对每个 ProjectDoc + 每个 active ProjectMemory 各调度一次 ``aschedule_ingestion``；
  superseded 记忆不调度。
- 重复运行计数稳定（命令侧总按 source 全量重调度，幂等由 ingestion 的 content_hash 短路承担）。
- 命令源码不含任何整库删除入口（``delete_collection`` / ``--yes`` / rebuild_delivery_knowledge），
  绝不连带删 delivery_knowledge 其他来源（A5 静态守护，镜像 INV-6 grep 守护）。

mock ``aschedule_ingestion``（normalize/embedding/Qdrant 全不触发），``--disable-socket`` 第二道保险。
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async

from initiatives.models import (
    DocType,
    Project,
    ProjectDoc,
    ProjectMemory,
    ProjectMemoryStatus,
)
from knowledge.management.commands import rebuild_project_context as cmd_mod
from knowledge.management.commands.rebuild_project_context import _rebuild_project_context
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)


@sync_to_async
def _seed(*, docs: int, active: int, superseded: int) -> None:
    space = Space.objects.create(name="S")
    project = Project.objects.create(space=space, name="P", feishu_project_key="rb-k")
    for i in range(docs):
        ProjectDoc.objects.create(
            project=project,
            doc_type=DocType.RESEARCH if i == 0 else DocType.STATE,
            last_synced_snapshot=f"# 文件 {i}\n正文 {i}",
        )
    for i in range(active):
        ProjectMemory.objects.create(
            project=project, content=f"active 记忆 {i}", status=ProjectMemoryStatus.ACTIVE
        )
    for i in range(superseded):
        ProjectMemory.objects.create(
            project=project,
            content=f"废弃记忆 {i}",
            status=ProjectMemoryStatus.SUPERSEDED,
        )


async def test_rebuild_schedules_each_doc_and_active_memory() -> None:
    await _seed(docs=2, active=3, superseded=2)

    mock_schedule = AsyncMock()
    with patch.object(cmd_mod, "aschedule_ingestion", mock_schedule):
        scheduled = await _rebuild_project_context()

    # 2 个 ProjectDoc + 3 个 active 记忆 = 5；2 个 superseded 不调度。
    assert scheduled == 5
    assert mock_schedule.await_count == 5

    source_kinds = sorted(
        call.args[0].source_kind for call in mock_schedule.await_args_list
    )
    assert source_kinds == ["project_doc", "project_doc"] + ["project_memory"] * 3


async def test_rebuild_skips_superseded_memory() -> None:
    await _seed(docs=0, active=0, superseded=3)

    mock_schedule = AsyncMock()
    with patch.object(cmd_mod, "aschedule_ingestion", mock_schedule):
        scheduled = await _rebuild_project_context()

    assert scheduled == 0
    assert mock_schedule.await_count == 0


async def test_rebuild_count_stable_across_runs() -> None:
    """重复运行计数稳定（命令侧全量重调度，幂等由 ingestion content_hash 承担）。"""
    await _seed(docs=1, active=1, superseded=0)

    mock_schedule = AsyncMock()
    with patch.object(cmd_mod, "aschedule_ingestion", mock_schedule):
        first = await _rebuild_project_context()
        second = await _rebuild_project_context()

    assert first == second == 2


def test_rebuild_command_never_deletes_collection() -> None:
    """静态守护：命令源码不含整库删除入口（绝不连带删其他来源，A5）。"""
    source = inspect.getsource(cmd_mod)
    assert "delete_collection" not in source
    assert "--yes" not in source
    assert "rebuild_delivery_knowledge" not in source
