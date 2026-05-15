"""代码图谱 App 配置。"""
from __future__ import annotations
from django.apps import AppConfig
class CodegraphConfig(AppConfig):
 """codegraph 图谱数据持久化 App。"""
 default_auto_field = "django.db.models.BigAutoField"
 name = "codegraph"
 verbose_name = "代码图谱"
 def ready(self) -> None:
 """启动时注册 Phase volar backend（per / ）。"""
 from django.conf import settings
 if getattr(settings, "VOLAR_BACKEND_ENABLED", True):
 self._register_volar_backends
 def _register_volar_backends(self) -> None:
 """Phase：5 项 BACKEND_REGISTRY 替换为 make_volar_backend(lang)。
 kill-switch ``settings.VOLAR_BACKEND_ENABLED=False`` 时跳过整段，
 BACKEND_REGISTRY 5 项保持 tree-sitter 默认。
 闭包注册 lazy：``make_volar_backend(language)`` 返工厂闭包，首次
 ``factory(lang)`` 调用才实例化 ``VolarBackend``；保 settings 加载顺序安全
 （per Pitfall P-）。
 """
 from codegraph.extractors.registry import register_backend
 from codegraph.lsp.volar_backend import make_volar_backend
 for language in ("vue", "typescript", "tsx", "javascript", "jsx"):
 register_backend(language, make_volar_backend(language))
