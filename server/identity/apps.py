"""Identity app configuration."""
from django.apps import AppConfig
class IdentityConfig(AppConfig):
 """身份认证应用配置。"""
 default_auto_field = "django.db.models.BigAutoField"
 name = "identity"
 verbose_name = "身份认证"
