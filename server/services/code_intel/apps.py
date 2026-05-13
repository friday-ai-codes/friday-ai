"""代码智能 Provider AppConfig (per Phase / ).
``ready`` 阶段读 ``settings.CODE_INTELLIGENCE_PROVIDER`` 的 class path，
importlib 加载并实例化一次，注入到 ``services.code_intel.registry``，最后 freeze。
避免在 ``ready`` 内做任何 ORM 查询（Django app loading 阶段 ORM 尚未完全就绪）。
"""
from __future__ import annotations
from importlib import import_module
import structlog
from django.apps import AppConfig
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
logger = structlog.get_logger(__name__)
DEFAULT_PROVIDER_PATH = "services.code_intel.local_provider.LocalProvider"
class CodeIntelConfig(AppConfig):
 """代码智能 Provider App 配置。"""
 default_auto_field = "django.db.models.BigAutoField"
 name = "services.code_intel"
 verbose_name = "代码智能 Provider"
 def ready(self) -> None:
 from services.code_intel.protocols import BaseCodeProvider
 from services.code_intel.registry import freeze, register_provider
 provider_path: str = getattr(settings, "CODE_INTELLIGENCE_PROVIDER", DEFAULT_PROVIDER_PATH)
 try:
 module_path, class_name = provider_path.rsplit(".", 1)
 except ValueError as exc:
 raise ImproperlyConfigured(
 f"CODE_INTELLIGENCE_PROVIDER must be a dotted class path, got: {provider_path!r}"
 ) from exc
 try:
 module = import_module(module_path)
 provider_cls = getattr(module, class_name)
 except (ImportError, AttributeError) as exc:
 raise ImproperlyConfigured(
 f"Cannot import CODE_INTELLIGENCE_PROVIDER={provider_path!r}: {exc}"
 ) from exc
 provider = provider_cls
 if not isinstance(provider, BaseCodeProvider):
 raise ImproperlyConfigured(
 f"{provider_path} must implement BaseCodeProvider Protocol "
 "(per T- — prevents arbitrary class-path code execution)"
 )
 register_provider("default", provider)
 freeze
 logger.info(
 "code_intel_registry_initialized",
 provider=provider_path,
 capabilities=sorted(provider.capabilities),
 )
