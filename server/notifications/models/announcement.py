"""Announcement / AnnouncementRead：管理员系统公告与按用户的已读追踪。

参考 sub2api 的公告实现：把「广播内容」（``Announcement``）与「按用户已读态」
（``AnnouncementRead``）拆成两张表，从而支持「面向全体用户（含未来注册用户）广播」
而无需为每个用户落一行通知。可见性（受众）在读取时即时判定。

与按收件人落库的 ``Notification``（反馈回复/状态变更）互补：``Notification`` 天然是
一对一的；``Announcement`` 则是一对多/广播，正文存 markdown，由前端实时渲染。
"""

import uuid

from django.db import models


class Announcement(models.Model):
    """管理员系统公告（表 ``announcement``）。"""

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ACTIVE = "active", "已发布"
        ARCHIVED = "archived", "已归档"

    class NotifyMode(models.TextChoices):
        SILENT = "silent", "静默（仅铃铛）"
        POPUP = "popup", "弹窗提醒"

    class Audience(models.TextChoices):
        ALL = "all", "全部用户"
        SPECIFIC = "specific", "指定用户"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    title = models.CharField(max_length=255)
    # markdown 正文（前端实时渲染）
    body = models.TextField()
    # 可选前端跳转路径（如 /repositories）
    link = models.CharField(max_length=512, blank=True, default="")

    status = models.CharField(max_length=16, default=Status.DRAFT, db_index=True)
    # 通知模式：silent 仅在铃铛/消息中心出现；popup 登录后自动弹窗
    notify_mode = models.CharField(max_length=16, default=NotifyMode.POPUP)

    # 受众：全部用户 or 指定用户
    audience = models.CharField(max_length=16, default=Audience.ALL)
    # audience=specific 时生效：目标用户 id（UUID 字符串）列表
    target_user_ids = models.JSONField(default=list, blank=True)

    # 展示窗口（为空 = 立即生效 / 永久生效）
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)

    # 创建人（删用户保留公告）
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_announcements",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "announcement"
        verbose_name = "系统公告"
        verbose_name_plural = "系统公告"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["starts_at"]),
            models.Index(fields=["ends_at"]),
        ]

    def is_active_at(self, now) -> bool:
        """在 ``now`` 时刻是否处于「已发布且在展示窗口内」。"""
        if self.status != self.Status.ACTIVE:
            return False
        if self.starts_at is not None and now < self.starts_at:
            return False
        # ends_at 语义：到点即下线
        if self.ends_at is not None and now >= self.ends_at:
            return False
        return True

    def is_visible_to(self, user_id) -> bool:
        """是否对指定用户可见（受众判定）。"""
        if self.audience == self.Audience.ALL:
            return True
        return str(user_id) in {str(uid) for uid in (self.target_user_ids or [])}

    def __str__(self) -> str:
        return f"Announcement({self.status}, {self.audience}, {self.title!r})"


class AnnouncementRead(models.Model):
    """用户对公告的已读记录（表 ``announcement_read``）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    announcement = models.ForeignKey(
        Announcement,
        on_delete=models.CASCADE,
        related_name="reads",
    )
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="announcement_reads",
    )
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "announcement_read"
        verbose_name = "公告已读记录"
        verbose_name_plural = "公告已读记录"
        constraints = [
            models.UniqueConstraint(
                fields=["announcement", "user"], name="uniq_announcement_user_read"
            ),
        ]
        indexes = [
            models.Index(fields=["user", "announcement"]),
        ]

    def __str__(self) -> str:
        return f"AnnouncementRead(a={self.announcement_id}, u={self.user_id})"
