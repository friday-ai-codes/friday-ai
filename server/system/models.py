"""Settings models: SystemSetting, CacheVolumeTracker."""
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
class CacheVolumeTracker(models.Model):
 """跟踪 Docker 缓存卷的使用情况。
 Docker volume labels 创建后不可变，因此通过数据库模型跟踪
 缓存卷的最后使用时间，用于精确的过期清理。
 """
 volume_name = models.CharField(max_length=255, unique=True, db_index=True)
 volume_type = models.CharField(
 max_length=20,
 choices=[("repo", "仓库缓存"), ("deps", "依赖缓存")],
 )
 repo_url = models.CharField(max_length=500, blank=True, default="")
 created_at = models.DateTimeField(auto_now_add=True)
 last_used_at = models.DateTimeField(auto_now_add=True)
 is_expired = models.BooleanField(default=False, db_index=True)
 class Meta:
 db_table = "cache_volume_tracker"
 verbose_name = "缓存卷跟踪"
 verbose_name_plural = "缓存卷跟踪"
 def __str__(self) -> str:
 return f"{self.volume_name} ({self.volume_type})"
