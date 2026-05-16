"""代码图谱 App 配置。"""
from __future__ import annotations
from django.apps import AppConfig
class CodegraphConfig(AppConfig):
 """codegraph 图谱数据持久化 App。"""
 default_auto_field = "django.db.models.BigAutoField"
 name = "codegraph"
 verbose_name = "代码图谱"
 def ready(self) -> None:
 """启动时注册 Phase volar backend + Phase gopls backend。"""
 from django.conf import settings
 if getattr(settings, "VOLAR_BACKEND_ENABLED", True):
 self._register_volar_backends
 if getattr(settings, "GOPLS_BACKEND_ENABLED", False):
 self._register_gopls_backend
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
 def _register_gopls_backend(self) -> None:
 """Phase：gopls backend 注册；GOPLS_BACKEND_ENABLED=True 时触发。
 默认 False —— Phase 仅落基础设施不切 BACKEND_REGISTRY["go"]。
 Phase 切 True 完成 Stage C 切换。
 """
 import structlog as _structlog
 from codegraph.extractors.registry import register_backend
 from codegraph.lsp.gopls_backend import make_gopls_backend
 register_backend("go", make_gopls_backend("go"))
 _structlog.get_logger(__name__).info(
 "go_backend_switched",
 backend="gopls",
 phase=268,
 )
