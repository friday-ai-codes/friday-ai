"""notifications models package — curated re-export（对齐 audit/delivery 范式）。"""

from notifications.models.announcement import Announcement, AnnouncementRead
from notifications.models.notification import Notification

__all__ = [
    "Announcement",
    "AnnouncementRead",
    "Notification",
]
