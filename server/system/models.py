"""Settings models: SystemSetting."""
from django.db import models
class SystemSetting(models.Model):
 """System-wide configuration settings."""
 key = models.CharField(max_length=100, primary_key=True)
 value = models.TextField(blank=True, null=True)
 is_encrypted = models.BooleanField(default=False)
 description = models.TextField(blank=True, null=True)
 updated_at = models.DateTimeField(auto_now=True)
 class Meta:
 db_table = "system_settings"
 verbose_name = "系统设置"
 verbose_name_plural = "系统设置"
 def __str__(self):
 return self.key
class SettingKeys:
 """Predefined setting keys."""
 ANTHROPIC_API_KEY = "anthropic_api_key"
 ANTHROPIC_BASE_URL = "anthropic_base_url"
 GIT_HTTP_PROXY = "git_http_proxy"
