"""系统公告领域服务：CRUD + 按用户可见性/已读聚合 + 实时推送。

参考 sub2api 的 AnnouncementService：
- 写库统一经本服务；公告内容与按用户已读态分离存储。
- ``list_for_user`` 在读取时即时按「受众 + 展示窗口 + 已读」聚合，支持「全体用户」广播
  且天然覆盖未来注册用户。
- 发布（status 进入 active）时通过 channel layer 实时推送：受众=all 推到全局广播分组，
  受众=specific 逐个推到收件人分组（复用站内信 consumer 的分组）。
"""

from __future__ import annotations

from typing import Any

import structlog
from asgiref.sync import async_to_sync, sync_to_async
from channels.layers import get_channel_layer
from django.utils import timezone

from notifications.models import Announcement, AnnouncementRead

from .notification_service import notification_group_name

logger = structlog.get_logger(__name__)

# 全体广播分组：NotificationConsumer 连接时无条件加入，用于 audience=all 公告实时下发
BROADCAST_GROUP = "announcements_broadcast"


def broadcast_group_name() -> str:
    return BROADCAST_GROUP


def serialize_announcement_for_user(announcement: Announcement, read_at=None) -> dict[str, Any]:
    """面向用户的公告序列化（WS / REST 通用，不依赖 DRF）。"""
    return {
        "id": str(announcement.id),
        "kind": "announcement",
        "type": "system",
        "title": announcement.title,
        "body": announcement.body,
        "link": announcement.link,
        "notify_mode": announcement.notify_mode,
        "read_at": read_at.isoformat() if read_at else None,
        "is_read": read_at is not None,
        "created_at": announcement.created_at.isoformat() if announcement.created_at else None,
    }


class AnnouncementService:
    """系统公告领域服务。"""

    # ---------------------------------------------------------------- 管理端写

    @staticmethod
    async def create(
        *,
        title: str,
        body: str,
        link: str = "",
        status: str = Announcement.Status.DRAFT,
        notify_mode: str = Announcement.NotifyMode.POPUP,
        audience: str = Announcement.Audience.ALL,
        target_user_ids: list[str] | None = None,
        starts_at=None,
        ends_at=None,
        created_by_id: Any = None,
    ) -> Announcement:
        announcement = await Announcement.objects.acreate(
            title=title,
            body=body,
            link=link or "",
            status=status,
            notify_mode=notify_mode,
            audience=audience,
            target_user_ids=list(target_user_ids or []),
            starts_at=starts_at,
            ends_at=ends_at,
            created_by_id=created_by_id,
        )
        if announcement.is_active_at(timezone.now()):
            await AnnouncementService._push(announcement)
        return announcement

    @staticmethod
    async def update(announcement: Announcement, *, fields: dict[str, Any]) -> Announcement:
        was_active = announcement.is_active_at(timezone.now())
        for key, value in fields.items():
            setattr(announcement, key, value)
        await announcement.asave()
        # 由「非展示」变为「展示中」时补推一次（例如草稿→发布、定时到点不在此处理）
        now_active = announcement.is_active_at(timezone.now())
        if now_active and not was_active:
            await AnnouncementService._push(announcement)
        return announcement

    @staticmethod
    async def delete(announcement: Announcement) -> None:
        await announcement.adelete()

    # ---------------------------------------------------------------- 用户端读

    @staticmethod
    async def list_for_user(user_id: Any, *, unread_only: bool = False) -> list[dict[str, Any]]:
        """当前用户可见的「展示中」公告，附已读态，未读优先、再按创建时间倒序。"""
        now = timezone.now()
        active = [a async for a in Announcement.objects.filter(status=Announcement.Status.ACTIVE)]
        visible = [a for a in active if a.is_active_at(now) and a.is_visible_to(user_id)]
        if not visible:
            return []

        read_map = await AnnouncementService._read_map(user_id, [a.id for a in visible])

        items: list[dict[str, Any]] = []
        for a in visible:
            read_at = read_map.get(a.id)
            if unread_only and read_at is not None:
                continue
            items.append(serialize_announcement_for_user(a, read_at))

        # 稳定排序：先按创建时间倒序，再按未读优先（保持组内倒序）
        items.sort(key=lambda it: it["created_at"] or "", reverse=True)
        items.sort(key=lambda it: it["is_read"])
        return items

    @staticmethod
    async def unread_count_for_user(user_id: Any) -> int:
        items = await AnnouncementService.list_for_user(user_id, unread_only=True)
        return len(items)

    @staticmethod
    async def popup_for_user(user_id: Any) -> list[dict[str, Any]]:
        """登录后需弹窗的公告：展示中 + 可见 + popup 模式 + 未读。"""
        items = await AnnouncementService.list_for_user(user_id, unread_only=True)
        return [it for it in items if it.get("notify_mode") == Announcement.NotifyMode.POPUP]

    @staticmethod
    async def mark_read(user_id: Any, announcement_id: Any) -> bool:
        """标记已读（仅当对该用户可见且展示中）。已读则幂等。"""
        try:
            announcement = await Announcement.objects.aget(id=announcement_id)
        except Announcement.DoesNotExist:
            return False
        if not announcement.is_active_at(timezone.now()):
            return False
        if not announcement.is_visible_to(user_id):
            return False
        await AnnouncementRead.objects.aget_or_create(
            announcement_id=announcement_id, user_id=user_id
        )
        return True

    # ---------------------------------------------------------------- 内部

    @staticmethod
    async def _read_map(user_id: Any, announcement_ids: list[Any]) -> dict[Any, Any]:
        reads = AnnouncementRead.objects.filter(
            user_id=user_id, announcement_id__in=announcement_ids
        ).values_list("announcement_id", "read_at")
        return {aid: read_at async for aid, read_at in reads}

    @staticmethod
    async def _recipient_ids(announcement: Announcement) -> list[Any]:
        """specific 受众的实际收件人 id（去重、字符串化）。"""
        return [str(uid) for uid in (announcement.target_user_ids or [])]

    @staticmethod
    async def _push(announcement: Announcement) -> None:
        """通过 channel layer 实时下发公告（失败仅告警，不阻断写库）。"""
        channel_layer = get_channel_layer()
        if channel_layer is None:
            return
        payload = {
            "type": "announcement.message",
            "announcement": serialize_announcement_for_user(announcement, None),
        }
        try:
            if announcement.audience == Announcement.Audience.ALL:
                await channel_layer.group_send(broadcast_group_name(), payload)
            else:
                for uid in await AnnouncementService._recipient_ids(announcement):
                    await channel_layer.group_send(notification_group_name(uid), payload)
        except Exception as exc:  # noqa: BLE001 — 推送失败不阻断业务
            logger.warning(
                "announcement_push_failed",
                announcement_id=str(announcement.id),
                error=str(exc),
            )

    @staticmethod
    def push_sync(announcement: Announcement) -> None:
        async_to_sync(AnnouncementService._push)(announcement)

    # ---------------------------------------------------------------- 管理端读

    @staticmethod
    async def read_status(
        announcement: Announcement, *, search: str = "", limit: int = 20, offset: int = 0
    ) -> dict[str, Any]:
        """某公告的按用户已读状态列表（管理端）。

        以系统用户为基底，标注该用户是否在受众内（eligible）及已读时间。
        """
        from accounts.models import User

        def _query() -> dict[str, Any]:
            qs = User.objects.all().order_by("created_at")
            if search:
                from django.db.models import Q

                qs = qs.filter(Q(username__icontains=search) | Q(email__icontains=search))
            total = qs.count()
            users = list(qs[offset : offset + limit])
            user_ids = [u.id for u in users]
            read_map = dict(
                AnnouncementRead.objects.filter(
                    announcement=announcement, user_id__in=user_ids
                ).values_list("user_id", "read_at")
            )
            rows = []
            for u in users:
                read_at = read_map.get(u.id)
                rows.append(
                    {
                        "user_id": str(u.id),
                        "username": u.username,
                        "email": u.email,
                        "eligible": announcement.is_visible_to(u.id),
                        "read_at": read_at.isoformat() if read_at else None,
                    }
                )
            return {"items": rows, "total": total, "limit": limit, "offset": offset}

        return await sync_to_async(_query)()
