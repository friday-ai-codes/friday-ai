"""Runners app models - Runner 和 RegistrationToken。"""
import hashlib
import secrets
import uuid
from django.db import models
from django.utils import timezone
def generate_token -> str:
 """生成随机 token。"""
 return secrets.token_urlsafe(32)
def hash_token(token: str) -> str:
 """SHA256 哈希 token。"""
 return hashlib.sha256(token.encode).hexdigest
class RegistrationToken(models.Model):
 """一次性注册令牌，用于 Runner 注册。"""
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 token_hash = models.CharField(max_length=64, unique=True, db_index=True)
 description = models.CharField(max_length=200, blank=True, default="")
 scope = models.CharField(
 max_length=20,
 choices=[("global", "全局"), ("project", "项目")],
 default="global",
 )
 project = models.ForeignKey(
 "projects.Project", on_delete=models.CASCADE, null=True, blank=True
 )
 is_used = models.BooleanField(default=False)
 used_at = models.DateTimeField(null=True, blank=True)
 used_by_runner = models.ForeignKey(
 "Runner", on_delete=models.SET_NULL, null=True, blank=True
 )
 expires_at = models.DateTimeField
 created_by = models.ForeignKey("accounts.User", on_delete=models.CASCADE)
 created_at = models.DateTimeField(auto_now_add=True)
 class Meta:
 db_table = "runner_registration_tokens"
 @property
 def is_expired(self) -> bool:
 return timezone.now > self.expires_at
 @property
 def is_valid(self) -> bool:
 return not self.is_used and not self.is_expired
 def __str__(self) -> str:
 return f"RegToken {self.id} ({'used' if self.is_used else 'valid'})"
class Runner(models.Model):
 """已注册的 Runner 实例。"""
 class Scope(models.TextChoices):
 GLOBAL = "global", "全局"
 PROJECT = "project", "项目"
 class Status(models.TextChoices):
 ONLINE = "online", "在线"
 OFFLINE = "offline", "离线"
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 name = models.CharField(max_length=200)
 token_hash = models.CharField(max_length=64, unique=True, db_index=True)
 token_prefix = models.CharField(max_length=8, default="")
 scope = models.CharField(
 max_length=20, choices=Scope.choices, default=Scope.GLOBAL
 )
 projects = models.ManyToManyField("projects.Project", blank=True)
 concurrent = models.PositiveIntegerField(default=1)
 status = models.CharField(
 max_length=20, choices=Status.choices, default=Status.OFFLINE
 )
 version = models.CharField(max_length=50, blank=True, default="")
 is_active = models.BooleanField(default=True)
 last_heartbeat = models.DateTimeField(null=True, blank=True)
 ip_address = models.GenericIPAddressField(null=True, blank=True)
 registered_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 class Meta:
 db_table = "runners"
 def __str__(self) -> str:
 return f"Runner {self.name} ({self.status})"
