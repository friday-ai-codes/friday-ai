"""Prompts app configuration。"""
from __future__ import annotations
from django.apps import AppConfig
class PromptsConfig(AppConfig):
 default_auto_field = "django.db.models.BigAutoField"
 name = "prompts"
 verbose_name = "提示词管理"
 def ready(self) -> None:
 """注册 signal handler 并 pre-warm Jinja2 环境。"""
 # 触发 @receiver(post_save, sender=Prompt) 注册（ 预埋 handler）
 from prompts import signals # noqa: F401
 # Pre-warm Jinja2 环境避免首次并发渲染时 parser lazy init race
 from prompts.engine import get_jinja_env
 get_jinja_env
