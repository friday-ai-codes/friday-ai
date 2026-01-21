"""Accounts models: User."""
import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models
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
 def __str__(self):
 return self.username
