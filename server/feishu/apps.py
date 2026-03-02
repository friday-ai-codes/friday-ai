"""Feishu app configuration."""
import os
import threading
from django.apps import AppConfig
class FeishuConfig(AppConfig):
 """Feishu app configuration."""
 default_auto_field = "django.db.models.BigAutoField"
 name = "feishu"
 verbose_name = "飞书集成"
 def ready(self):
 """Called when Django app is ready.
 Starts Feishu WebSocket clients for all configured projects
 that have feishu_app_id and feishu_app_secret configured.
 """
 # runserver reloader: RUN_MAIN=true 表示子进程（应启动）
 # uvicorn/daphne: 没有 RUN_MAIN，但也不是 reloader 模式
 # 管理命令/迁移: 通过 sys.argv 检测跳过
 import sys
 is_runserver = any("runserver" in arg for arg in sys.argv)
 if is_runserver and os.environ.get("RUN_MAIN") != "true":
 # runserver reloader 主进程，跳过（子进程会再次调用 ready）
 return
 is_management_cmd = len(sys.argv) > 1 and sys.argv[1] in (
 "migrate", "makemigrations", "collectstatic", "check",
 "shell", "dbshell", "test", "startapp", "createsuperuser",
 )
 if is_management_cmd:
 return
 # Start in a delayed thread to avoid blocking app startup
 def delayed_start:
 import time
 time.sleep(3) # Wait for Django to fully initialize
 try:
 from feishu.websocket_client import auto_start_clients
 auto_start_clients
 except Exception as e:
 import structlog
 logger = structlog.get_logger(__name__)
 logger.error("feishu_ws_auto_start_failed", error=str(e))
 thread = threading.Thread(target=delayed_start, daemon=True)
 thread.start
