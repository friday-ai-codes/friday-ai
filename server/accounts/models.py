"""Accounts models: User, Invitation."""
import secrets
import uuid
from collections.abc import Iterable
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.base import ModelBase
from django.utils import timezone
def _generate_invitation_token -> str:
 """生成 URL 安全的邀请令牌（Django migration 可序列化）。"""
 return secrets.token_urlsafe(32)
class User(AbstractUser):
 """Custom user model for Friday."""
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 display_name = models.CharField(max_length=100, blank=True, default="")
 must_change_password = models.BooleanField(
 default=False,
 verbose_name="必须修改密码",
 help_text="标记用户是否需要在下次登录时强制修改密码",
 )
 created_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 class Meta:
 db_table = "users"
 verbose_name = "用户"
 verbose_name_plural = "用户"
 def __str__(self) -> str:
 return self.username
class Invitation(models.Model):
 """用户邀请令牌。管理员创建，用于邀请新用户注册。"""
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 token = models.CharField(
 max_length=64,
 unique=True,
 default=_generate_invitation_token,
 verbose_name="邀请令牌",
 )
 email = models.EmailField(blank=True, default="", verbose_name="预填邮箱（可选）")
 created_by = models.ForeignKey(
 settings.AUTH_USER_MODEL,
 on_delete=models.CASCADE,
 related_name="created_invitations",
 verbose_name="创建者",
 )
 expires_at = models.DateTimeField(verbose_name="过期时间")
 accepted_at = models.DateTimeField(null=True, blank=True, verbose_name="接受时间")
 created_at = models.DateTimeField(auto_now_add=True)
 class Meta:
 db_table = "invitations"
 verbose_name = "邀请"
 verbose_name_plural = "邀请"
 indexes = [
 models.Index(fields=["token"]),
 models.Index(fields=["created_by"]),
 ]
 def is_valid(self) -> bool:
 """检查令牌是否有效（未使用且未过期）。"""
 return self.accepted_at is None and timezone.now < self.expires_at
 def save(
 self,
 *,
 force_insert: bool | tuple[ModelBase, ...] = False,
 force_update: bool = False,
 using: str | None = None,
 update_fields: Iterable[str] | None = None,
 ) -> None:
 if not self.expires_at:
 self.expires_at = timezone.now + timezone.timedelta(days=7)
 super.save(
 force_insert=force_insert,
 force_update=force_update,
 using=using,
 update_fields=update_fields,
 )
 def __str__(self) -> str:
 return f"Invitation({self.token[:8]}... by {self.created_by_id})"
