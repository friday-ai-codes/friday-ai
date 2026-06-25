"""Permissions models: Space roles and membership."""

import uuid

from django.conf import settings
from django.db import models


class SpaceRole(models.TextChoices):
    """空间角色"""

    ADMIN = "admin", "管理员"
    MEMBER = "member", "成员"
    VIEWER = "viewer", "观察者"


class SpaceMembership(models.Model):
    """空间成员关系。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="space_memberships",
    )
    space = models.ForeignKey(
        "projects.Space",
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(
        max_length=20,
        choices=SpaceRole.choices,
        default=SpaceRole.MEMBER,
        verbose_name="角色",
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_invitations",
    )
    joined_at = models.DateTimeField(auto_now_add=True, verbose_name="加入时间")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "project_memberships"
        verbose_name = "空间成员"
        verbose_name_plural = "空间成员"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "space"], name="unique_user_project"
            ),
        ]
        indexes = [
            models.Index(fields=["space", "role"]),
            models.Index(fields=["user"]),
        ]

    def __str__(self) -> str:
        return f"{self.user} - {self.space} ({self.get_role_display()})"
