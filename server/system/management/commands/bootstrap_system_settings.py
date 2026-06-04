"""启动时引导系统设置默认值。"""
from __future__ import annotations
import os
import structlog
from django.core.management.base import BaseCommand
from common.encryption import encrypt_value
from system.models import SettingKeys, SystemSetting
logger = structlog.get_logger(__name__)
class Command(BaseCommand):
 """写入容器化部署需要的缺省 SystemSetting。"""
 help = "Bootstrap default system settings for container deployments"
 def handle(self, *args, **options) -> None:
 qdrant_url = os.environ.get("QDRANT_URL", "http://qdrant:6333").strip
 qdrant_api_key = os.environ.get("QDRANT_API_KEY", "").strip
 created_qdrant_url = False
 if qdrant_url:
 _, created_qdrant_url = SystemSetting.objects.get_or_create(
 key=SettingKeys.QDRANT_URL,
 defaults={
 "value": qdrant_url,
 "is_encrypted": False,
 "description": "Qdrant URL bootstrapped from container environment",
 },
 )
 created_qdrant_api_key = False
 if qdrant_api_key:
 _, created_qdrant_api_key = SystemSetting.objects.get_or_create(
 key=SettingKeys.QDRANT_API_KEY,
 defaults={
 "value": encrypt_value(qdrant_api_key),
 "is_encrypted": True,
 "description": "Qdrant API key bootstrapped from container environment",
 },
 )
 logger.info(
 "system_settings_bootstrapped",
 qdrant_url_created=created_qdrant_url,
 qdrant_api_key_created=created_qdrant_api_key,
 )
 self.stdout.write(self.style.SUCCESS("System settings bootstrap complete."))
