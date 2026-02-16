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
 ANTHROPIC_MODEL = "anthropic_model"
 LLM_PROVIDER_TYPE = "llm_provider_type"
 GIT_HTTP_PROXY = "git_http_proxy"
 # Vector Index Settings
 QDRANT_URL = "qdrant_url"
 QDRANT_API_KEY = "qdrant_api_key"
 EMBEDDING_API_URL = "embedding_api_url"
 EMBEDDING_API_KEY = "embedding_api_key"
 EMBEDDING_MODEL = "embedding_model"
 EMBEDDING_DIMENSION = "embedding_dimension"
 # Feishu IM Settings
 FEISHU_APP_ID = "feishu_app_id"
 FEISHU_APP_SECRET = "feishu_app_secret"
