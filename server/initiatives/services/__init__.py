"""initiatives services 包 —— 项目聚合根唯一写入入口与实时推送。

re-export ``ProjectService`` / ``ProjectTransitionError``（Project 单一写入入口，INV-6）
+ 实时推送 helper（``project_group_name`` / ``apush_project_event``）。
"""

from initiatives.services.project_board_sync import (
    BoardSyncResult,
    ProjectBoardSyncService,
)
from initiatives.services.project_service import (
    ProjectMemberError,
    ProjectService,
    ProjectTransitionError,
)
from initiatives.services.realtime import apush_project_event, project_group_name

__all__ = [
    "ProjectService",
    "ProjectTransitionError",
    "ProjectMemberError",
    "ProjectBoardSyncService",
    "BoardSyncResult",
    "project_group_name",
    "apush_project_event",
]
