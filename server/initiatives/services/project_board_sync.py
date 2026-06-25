"""飞书"项目跟踪"看板 → Project 聚合根的同源建项目入口（FSPROJ-02/03）。

``ProjectBoardSyncService.sync_from_board`` 是**飞书事件 handler** 与 **`create_project`
工作流节点**共用的同源入口（不造两套）：幂等建项目 + 枚举看板 + 拉人带身份 + 组合子项 WorkItem。

幂等语义（FSPROJ-02）：
- 项目以 ``(space, feishu_project_key)`` 经 ``ProjectService.create`` get_or_create 幂等
  （Phase 77 已实现）——重复事件不重复建（``created=False``）。
- 成员经 ``add_member``（get_or_create）/ 链接经 ``attach_work_item``（get_or_create）只补齐不重复。

fail-soft 降级（FSPROJ-01）：枚举硬路径抛 ``FeishuResponseError``（看板工作项取数非 JSON）→
本 service 捕获并**降级半自动**：仍返回已建项目 + ``degraded=True``，子项/成员留待后续 webhook
逐个并入。未配置飞书凭证（无法建 client）同样降级，不阻断建项目。

观测（强制规范）：
- 后台/事件触发 → 带 ``initiated_by_user_id``（解析触发飞书人对应 Friday 用户；未映射标
  ``system``）；``component="initiatives"``, ``category="caller"``；关键生命周期
  ``project_board_sync_started/completed`` + ``duration_ms``。
- 飞书上游响应体脱敏由 ``strict/safe_response_json`` 兜底；本 service 只投三元组标量，绝不把
  原始 webhook payload 再次落库（入口 ``record_inbound_webhook`` 已脱敏留痕）。
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from initiatives.models import LinkProvenance, ProjectRole
from initiatives.services.project_service import ProjectService

logger = structlog.get_logger(__name__)

__all__ = ["ProjectBoardSyncService", "BoardSyncResult"]


class BoardSyncResult(dict):
    """看板同步结果（dict 子类，便于节点直接作 output 透出）。

    键：``project_id`` / ``created`` / ``degraded`` / ``warnings`` /
    ``members_added`` / ``members_unmapped`` / ``work_items_linked``。
    """


class ProjectBoardSyncService:
    """飞书看板 → Project 同源建项目/拉人/组合入口。"""

    async def sync_from_board(
        self,
        *,
        space: Any,
        feishu_project_key: str,
        board_work_item_id: int,
        board_work_item_type: str = "story",
        name: str,
        feishu_board_url: str = "",
        feishu_board_id: str = "",
        client: Any = None,
        created_by: Any = None,
        initiated_by_user_id: Any = "system",
    ) -> BoardSyncResult:
        """幂等建项目 + 枚举看板 + 拉人带身份 + 组合子项（同源入口）。

        Args:
            space: 所属 ``Space`` 实例。
            feishu_project_key: 飞书看板 project_key（幂等键）。
            board_work_item_id: "项目跟踪"看板工作项 ID（枚举锚）。
            board_work_item_type: 看板工作项类型（默认 story）。
            name: 项目名称（建项目用）。
            feishu_board_url / feishu_board_id: 看板引用。
            client: 飞书 client（缺省按 space 凭证构建；构建失败降级）。
            created_by: 创建者（事件路径通常 None；节点路径可带触发用户）。
            initiated_by_user_id: 触发用户 id（审计绑定；未映射 "system"）。

        Returns:
            ``BoardSyncResult``。
        """
        started = time.monotonic()
        logger.info(
            "project_board_sync_started",
            feishu_project_key=feishu_project_key,
            board_work_item_id=board_work_item_id,
            initiated_by_user_id=str(initiated_by_user_id) if initiated_by_user_id else "system",
            component="initiatives",
            category="caller",
        )

        service = ProjectService()

        # 1) 幂等建项目（Phase 77 get_or_create）
        project, created = await service.create(
            space=space,
            name=name,
            feishu_project_key=feishu_project_key,
            feishu_board_url=feishu_board_url,
            feishu_board_id=feishu_board_id,
            created_by=created_by,
            initiated_by_user_id=initiated_by_user_id,
        )

        result = BoardSyncResult(
            project_id=str(project.id),
            created=created,
            degraded=False,
            warnings=[],
            members_added=0,
            members_unmapped=0,
            work_items_linked=0,
        )

        # 2) 枚举看板（fail-soft：硬路径抛错 → 降级半自动，仍返回已建项目）
        enumeration = await self._enumerate_soft(
            space=space,
            client=client,
            feishu_project_key=feishu_project_key,
            board_work_item_id=board_work_item_id,
            board_work_item_type=board_work_item_type,
            result=result,
        )
        if enumeration is None:
            self._finish_log(result, started)
            return result

        result["degraded"] = enumeration.degraded
        result["warnings"] = list(enumeration.warnings)

        # 3) 拉人带身份（resolve_feishu_user JIT；未映射 fail-soft 跳过可后补绑定）
        await self._pull_people(
            service, project.id, enumeration.people, initiated_by_user_id, result
        )

        # 4) 组合子项（board_derived 自动并入，经 WorkItemService 落 canonical + attach）
        await self._link_work_items(
            service,
            project.id,
            feishu_project_key,
            enumeration.work_items,
            initiated_by_user_id,
            result,
        )

        self._finish_log(result, started)
        return result

    async def _enumerate_soft(
        self,
        *,
        space: Any,
        client: Any,
        feishu_project_key: str,
        board_work_item_id: int,
        board_work_item_type: str,
        result: BoardSyncResult,
    ):
        """构建 client（缺省）+ 枚举看板，任何失败 → 降级半自动（degraded + warning）。"""
        from services.feishu_project_board import enumerate_board

        if client is None:
            from services.feishu import create_feishu_client_for_project

            try:
                client = await self._build_client(space, create_feishu_client_for_project)
            except Exception as exc:  # noqa: BLE001 — 缺凭证/构建失败降级，不阻断建项目
                logger.warning(
                    "project_board_sync_client_unavailable",
                    feishu_project_key=feishu_project_key,
                    error=str(exc),
                    error_type=type(exc).__name__,
                    component="initiatives",
                    category="caller",
                )
                result["degraded"] = True
                result["warnings"] = [*result["warnings"], "feishu_client_unavailable"]
                return None

        try:
            return await enumerate_board(
                client,
                feishu_project_key=feishu_project_key,
                board_work_item_id=board_work_item_id,
                board_work_item_type=board_work_item_type,
            )
        except Exception as exc:  # noqa: BLE001 — 硬路径取数失败 → 降级半自动
            logger.warning(
                "project_board_enumeration_failed",
                feishu_project_key=feishu_project_key,
                board_work_item_id=board_work_item_id,
                error=str(exc),
                error_type=type(exc).__name__,
                component="initiatives",
                category="caller",
            )
            result["degraded"] = True
            result["warnings"] = [*result["warnings"], "enumeration_failed"]
            return None

    @staticmethod
    async def _build_client(space: Any, factory):
        """在线程外构建飞书 client（factory 读 space 加密字段，async 安全经 sync_to_async）。"""
        from asgiref.sync import sync_to_async

        return await sync_to_async(factory)(space)

    @staticmethod
    async def _pull_people(
        service: ProjectService,
        project_id: Any,
        people: list,
        initiated_by_user_id: Any,
        result: BoardSyncResult,
    ) -> None:
        """逐人解析身份并落成员（owner 角色经 add_member+transfer_owner，其余 add_member）。"""
        from feishu.services.identity import resolve_feishu_user

        for person in people:
            user = await resolve_feishu_user(feishu_user_key=person.user_key)
            if user is None:
                result["members_unmapped"] += 1
                continue
            try:
                if person.role == ProjectRole.OWNER:
                    # owner 不可经 add_member 直设：先确保成员（保守 backend）再 transfer_owner。
                    await service.add_member(
                        project_id=project_id,
                        user=user,
                        role=ProjectRole.BACKEND,
                        initiated_by_user_id=initiated_by_user_id,
                    )
                    await service.transfer_owner(
                        project_id=project_id,
                        new_owner_user_id=user.id,
                        initiated_by_user_id=initiated_by_user_id,
                    )
                else:
                    await service.add_member(
                        project_id=project_id,
                        user=user,
                        role=person.role,
                        initiated_by_user_id=initiated_by_user_id,
                    )
                result["members_added"] += 1
            except Exception as exc:  # noqa: BLE001 — 单人落库失败不阻断其余拉人
                logger.warning(
                    "project_board_member_pull_failed",
                    project_id=str(project_id),
                    role=person.role,
                    error=str(exc),
                    error_type=type(exc).__name__,
                    component="initiatives",
                    category="caller",
                )

    @staticmethod
    async def _link_work_items(
        service: ProjectService,
        project_id: Any,
        feishu_project_key: str,
        work_items: list,
        initiated_by_user_id: Any,
        result: BoardSyncResult,
    ) -> None:
        """逐子项经 WorkItemService 落 canonical 行 + attach（board_derived，INV-6）。"""
        from delivery.services import WorkItemIdentity, WorkItemService

        wi_service = WorkItemService()
        for ref in work_items:
            try:
                work_item = await wi_service.upsert(
                    WorkItemIdentity(
                        feishu_project_key=feishu_project_key,
                        work_item_type=ref.work_item_type,
                        work_item_id=ref.work_item_id,
                    ),
                    source="feishu_webhook",
                    fetch=False,
                )
                await service.attach_work_item(
                    project_id=project_id,
                    work_item=work_item,
                    provenance=LinkProvenance.BOARD_DERIVED,
                    initiated_by_user_id=initiated_by_user_id,
                )
                result["work_items_linked"] += 1
            except Exception as exc:  # noqa: BLE001 — 单子项失败不阻断其余组合
                logger.warning(
                    "project_board_work_item_link_failed",
                    project_id=str(project_id),
                    work_item_id=ref.work_item_id,
                    work_item_type=ref.work_item_type,
                    error=str(exc),
                    error_type=type(exc).__name__,
                    component="initiatives",
                    category="caller",
                )

    @staticmethod
    def _finish_log(result: BoardSyncResult, started: float) -> None:
        logger.info(
            "project_board_sync_completed",
            project_id=result["project_id"],
            created=result["created"],
            degraded=result["degraded"],
            members_added=result["members_added"],
            members_unmapped=result["members_unmapped"],
            work_items_linked=result["work_items_linked"],
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            component="initiatives",
            category="caller",
        )
