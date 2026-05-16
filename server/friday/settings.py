"""
Django settings for Friday project.
AI-powered Development Automation System
"""
import os
import secrets
from datetime import timedelta
from pathlib import Path
from typing import Any
import environ
from django.core.exceptions import ImproperlyConfigured
# adrf 0.1.12 兼容性补丁：替换已弃用的 asyncio.iscoroutinefunction
from core.patches import patch_asyncio_iscoroutinefunction
patch_asyncio_iscoroutinefunction
# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve.parent.parent
DATA_DIR = BASE_DIR / "data"
# Ensure data directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "repos").mkdir(exist_ok=True)
(DATA_DIR / "sessions").mkdir(exist_ok=True)
(DATA_DIR / "credentials").mkdir(exist_ok=True)
# 本地 Git clone 根目录（：_calculate_commit_distance 使用此路径 / {repo.id}/）
REPO_CLONE_DIR = DATA_DIR / "repos"
# Initialize django-environ
INSECURE_SECRET_KEY = "django-insecure-change-me-in-production"
LOCALHOST_HOSTS = ["localhost", "127.0.0.1", "[:1]"]
env = environ.Env(
 DEBUG=(bool, False),
 SECRET_KEY=(str, INSECURE_SECRET_KEY),
 ALLOWED_HOSTS=(list, LOCALHOST_HOSTS),
)
# Read .env file (server/.env 优先，回退到项目根 .env)
_env_file = BASE_DIR / ".env"
if not _env_file.exists:
 _env_file = BASE_DIR.parent / ".env"
env.read_env(_env_file, overwrite=False)
# =============================================================================
# Core Settings
# =============================================================================
debug_override = os.environ.get("FRIDAY_DEBUG")
if debug_override is not None:
 DEBUG = debug_override.lower in ("true", "1", "yes")
else:
 DEBUG = env.bool("DEBUG", default=False)
# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env("SECRET_KEY")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=LOCALHOST_HOSTS)
FRIDAY_ENV = env.str("FRIDAY_ENV", default="development").lower
IS_PRODUCTION = FRIDAY_ENV in {"prod", "production"} or env.bool("FRIDAY_PRODUCTION", default=False)
if IS_PRODUCTION:
 if DEBUG:
 raise ImproperlyConfigured("Production mode requires DEBUG=False")
 if not SECRET_KEY or SECRET_KEY == INSECURE_SECRET_KEY:
 raise ImproperlyConfigured("Production mode requires a non-default SECRET_KEY")
 if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
 raise ImproperlyConfigured(
 "Production mode requires explicit ALLOWED_HOSTS (wildcard not allowed)"
 )
# =============================================================================
# Application definition
# =============================================================================
INSTALLED_APPS = [
 "daphne",
 "django.contrib.auth",
 "django.contrib.contenttypes",
 "django.contrib.sessions",
 "django.contrib.messages",
 "django.contrib.staticfiles",
 "rest_framework",
 "adrf",
 "rest_framework_simplejwt",
 "rest_framework_simplejwt.token_blacklist",
 "drf_spectacular",
 "channels",
 "django_apscheduler",
 "accounts",
 "system",
 "repositories",
 "codegraph",
 "code_relations",
 "projects",
 "feishu",
 "chat",
 "workflows",
 "agents",
 "compat",
 "subagent",
 "runners",
 "tools",
 "identity",
 "permissions",
 "orchestration",
 "prompts",
 "services.code_intel.apps.CodeIntelConfig",
]
MIDDLEWARE = [
 "django.middleware.security.SecurityMiddleware",
 "whitenoise.middleware.WhiteNoiseMiddleware",
 "django.contrib.sessions.middleware.SessionMiddleware",
 "django.middleware.common.CommonMiddleware",
 "django.middleware.csrf.CsrfViewMiddleware",
 "django.contrib.auth.middleware.AuthenticationMiddleware",
 "django.contrib.messages.middleware.MessageMiddleware",
 "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "friday.urls"
# URL Configuration - Auto redirect to add trailing slash for collection resources
APPEND_SLASH = True
TEMPLATES = [
 {
 "BACKEND": "django.template.backends.django.DjangoTemplates",
 "DIRS":,
 "APP_DIRS": True,
 "OPTIONS": {
 "context_processors": [
 "django.template.context_processors.request",
 "django.contrib.auth.context_processors.auth",
 "django.contrib.messages.context_processors.messages",
 ],
 },
 },
]
WSGI_APPLICATION = "friday.wsgi.application"
ASGI_APPLICATION = "friday.asgi.application"
# =============================================================================
# Channels / WebSocket
# =============================================================================
USE_REDIS_CHANNEL_LAYER = env.bool("USE_REDIS_CHANNEL_LAYER", default=False)
REDIS_CHANNEL_LAYER_URL = env.str(
 "REDIS_CHANNEL_LAYER_URL",
 default=env.str("REDIS_URL", default="redis://127.0.0.1:6379/0"),
)
if USE_REDIS_CHANNEL_LAYER:
 CHANNEL_LAYERS = {
 "default": {
 "BACKEND": "channels_redis.core.RedisChannelLayer",
 "CONFIG": {
 "hosts": [REDIS_CHANNEL_LAYER_URL],
 },
 },
 }
else:
 CHANNEL_LAYERS = {
 "default": {
 "BACKEND": "channels.layers.InMemoryChannelLayer",
 },
 }
# Workflow idempotency backend migration entrypoint.
# Current default remains in-memory for compatibility.
WORKFLOW_IDEMPOTENCY_BACKEND = env.str("WORKFLOW_IDEMPOTENCY_BACKEND", default="memory")
WORKFLOW_IDEMPOTENCY_REDIS_URL = env.str(
 "WORKFLOW_IDEMPOTENCY_REDIS_URL",
 default=REDIS_CHANNEL_LAYER_URL,
)
# 生产模式下要求 WebSocket 使用 TLS (wss://)
# 默认值：仅生产环境启用，开发环境允许 ws://
# 可通过环境变量 WEBSOCKET_REQUIRE_TLS 显式控制
WEBSOCKET_REQUIRE_TLS = env.bool("WEBSOCKET_REQUIRE_TLS", IS_PRODUCTION)
# =============================================================================
# Database
# =============================================================================
# 支持多种数据库，通过 DATABASE_URL 环境变量配置
# 格式示例：
# SQLite: sqlite:///./data/friday.db
# PostgreSQL: postgres://user:${POSTGRES_PASSWORD}@host:5432/dbname
# MySQL: mysql://user:password@host:3306/dbname
# MariaDB: mysql://user:password@host:3306/dbname
#
# 注意：使用 PostgreSQL 需安装 psycopg[binary]
# 使用 MySQL/MariaDB 需安装 mysqlclient
DEFAULT_DATABASE_URL = f"sqlite:///{DATA_DIR / 'friday.db'}"
DATABASES = {"default": env.db("DATABASE_URL", default=DEFAULT_DATABASE_URL)}
# =============================================================================
# Custom User Model
# =============================================================================
AUTH_USER_MODEL = "accounts.User"
# =============================================================================
# Password validation
# =============================================================================
AUTH_PASSWORD_VALIDATORS = [
 {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
 {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
 {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
 {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
# =============================================================================
# Internationalization
# =============================================================================
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True
# =============================================================================
# Static files
# =============================================================================
STATIC_URL = "/api/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
 "staticfiles": {
 "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
 },
}
# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
# =============================================================================
# CORS Settings
# =============================================================================
# CORS_ALLOW_ALL_ORIGINS = DEBUG
# CORS_ALLOWED_ORIGINS = [
# origin.strip
# for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
# if origin.strip
# ]
# =============================================================================
# REST Framework Settings
# =============================================================================
REST_FRAMEWORK = {
 "DEFAULT_AUTHENTICATION_CLASSES": [
 "common.authentication.CookieJWTAuthentication",
 ],
 "DEFAULT_PERMISSION_CLASSES": [
 "rest_framework.permissions.IsAuthenticated",
 ],
 "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
 "EXCEPTION_HANDLER": "common.exceptions.custom_exception_handler",
 "DEFAULT_THROTTLE_RATES": {
 "auth_login": "5/min",
 "auth_refresh": "20/min",
 },
}
# =============================================================================
# JWT Settings
# =============================================================================
SIMPLE_JWT = {
 "ACCESS_TOKEN_LIFETIME": timedelta(
 minutes=int(os.environ.get("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
 ),
 "REFRESH_TOKEN_LIFETIME": timedelta(
 days=int(os.environ.get("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7"))
 ),
 "ROTATE_REFRESH_TOKENS": True,
 "BLACKLIST_AFTER_ROTATION": True,
 "SIGNING_KEY": os.environ.get("JWT_SECRET_KEY", "") or SECRET_KEY,
 "AUTH_HEADER_TYPES": ("Bearer",),
 "USER_ID_FIELD": "id",
 "USER_ID_CLAIM": "sub",
}
# Cookie settings for refresh token
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "False").lower in ("true", "1", "yes")
COOKIE_SAMESITE = os.environ.get("COOKIE_SAMESITE", "Lax")
COOKIE_HTTPONLY = os.environ.get("COOKIE_HTTPONLY", "True").lower in ("true", "1", "yes")
# =============================================================================
# drf-spectacular (Swagger/OpenAPI) Settings
# =============================================================================
SPECTACULAR_SETTINGS = {
 "TITLE": "Friday API",
 "DESCRIPTION": "AI-powered Development Automation System",
 "VERSION": "1.0.0",
 "SERVE_INCLUDE_SCHEMA": False,
 "COMPONENT_SPLIT_REQUEST": True,
}
# =============================================================================
# External Integrations
# =============================================================================
# Encryption key for sensitive data (base64 encoded 32-byte key)
FRIDAY_ENCRYPTION_KEY = os.environ.get("FRIDAY_ENCRYPTION_KEY", "")
# Feishu callback signature verification policy.
# In production, signatures are required by default.
FEISHU_ENCRYPT_KEY = env.str("FEISHU_ENCRYPT_KEY", default="")
FEISHU_SIGNATURE_REQUIRED = env.bool("FEISHU_SIGNATURE_REQUIRED", default=IS_PRODUCTION)
# =============================================================================
# Logging
# =============================================================================
LOGGING = {
 "version": 1,
 "disable_existing_loggers": False,
 "formatters": {
 "verbose": {
 "format": "{levelname} {asctime} {module} {message}",
 "style": "{",
 },
 },
 "handlers": {
 "console": {
 "class": "logging.StreamHandler",
 "formatter": "verbose",
 },
 },
 "root": {
 "handlers": ["console"],
 "level": "INFO",
 },
 "loggers": {
 "django": {
 "handlers": ["console"],
 "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
 "propagate": False,
 },
 "friday": {
 "handlers": ["console"],
 "level": "DEBUG" if DEBUG else "INFO",
 "propagate": False,
 },
 # 第三方 HTTP 客户端的每次成功请求默认是 INFO，索引时会刷屏。
 # 业务侧 structlog 已开放 DEBUG；第三方库只保留 warning/error。
 "httpx": {
 "handlers": ["console"],
 "level": os.environ.get("HTTPX_LOG_LEVEL", "WARNING"),
 "propagate": False,
 },
 "httpcore": {
 "handlers": ["console"],
 "level": os.environ.get("HTTPCORE_LOG_LEVEL", "WARNING"),
 "propagate": False,
 },
 "qdrant_client": {
 "handlers": ["console"],
 "level": os.environ.get("QDRANT_CLIENT_LOG_LEVEL", "WARNING"),
 "propagate": False,
 },
 },
}
# =============================================================================
# SubAgent Settings
# =============================================================================
# SubAgent container API URL
SUBAGENT_API_URL = os.environ.get("SUBAGENT_API_URL", "http://localhost:10241")
# Base URL for callbacks (this server's external URL)
FRIDAY_BASE_URL = os.environ.get("FRIDAY_BASE_URL", "http://localhost:10241")
# Frontend URL for OIDC redirects
FRIDAY_FRONTEND_URL = os.environ.get("FRIDAY_FRONTEND_URL", "http://localhost:10240")
# Container callback authentication (Phase)
CONTAINER_CALLBACK_TOKEN = os.environ.get(
 "CONTAINER_CALLBACK_TOKEN",
 secrets.token_urlsafe(32),
)
# =============================================================================
# Feature Flags
# =============================================================================
# When True, workflow status changes sync to Feishu
FF_SYNC_WORKFLOW_TO_FEISHU = env.bool("FF_SYNC_WORKFLOW_TO_FEISHU", True)
# When True, WebSocket real-time updates are enabled
FF_ENABLE_WORKFLOW_WEBSOCKET = env.bool("FF_ENABLE_WORKFLOW_WEBSOCKET", True)
# Default workflow template for new tasks
FF_DEFAULT_WORKFLOW_TEMPLATE = env.str("FF_DEFAULT_WORKFLOW_TEMPLATE", "code_generation")
# Phase: When True, code graph extraction runs during indexing. Set False to skip graph writes.
# **写入侧** 语义（per Phase）：控制 indexer 是否构建 ChunkEdge / 写
# Qdrant payload `related_chunks`；与读出侧 ENABLE_GRAPHRAG_ENRICHMENT 独立解耦。
ENABLE_CODEGRAPH = env.bool("ENABLE_CODEGRAPH", True)
# Phase：**读出侧** GraphRAG enrichment 开关（与 ENABLE_CODEGRAPH 写入侧解耦）。
# False 时 HybridSearchService.search 入口强制 ``_search_rag_only`` 路径，即使
# Provider 实现 GraphCapableProvider Protocol，输出 byte-equivalent Phase 路径。
# 默认 True 保持向后兼容（与 v23.0 / Phase 行为一致）。
# **唯一允许的直读点**：``services/retrieval/hybrid_search.py:HybridSearchService.search``
# 入口（per CONTEXT.md 关键不变量；新增直读点应 PR review 拒绝）。
ENABLE_GRAPHRAG_ENRICHMENT: bool = env.bool("ENABLE_GRAPHRAG_ENRICHMENT", default=True)
# Phase: 代码智能 Provider class path（默认 LocalProvider 包装 codegraph 现有服务，
# v25+ 可切到 RemoteProvider 一次替换全局生效，per / ）
CODE_INTELLIGENCE_PROVIDER: str = env.str(
 "CODE_INTELLIGENCE_PROVIDER",
 "services.code_intel.local_provider.LocalProvider",
)
# Phase: 各语言使用的 extractor backend（tree_sitter / volar / gopls）
# 默认全 tree_sitter；Stage B/C 完成后可覆盖为 "vue": "volar", "go": "gopls"
EXTRACTOR_BACKENDS: dict[str, str] = {
 "python": "tree_sitter",
 "go": "gopls", # Phase 已切换（原 tree_sitter）
 "typescript": "volar", # Phase 切（原 tree_sitter）
 "tsx": "volar", # Phase 切
 "vue": "volar", # Phase 切
 "javascript": "volar", # Phase 新增（之前未有）
 "jsx": "volar", # Phase 新增
 "html": "tree_sitter", # Phase
 "css": "tree_sitter", # Phase
}
# Phase B3：CoChangedEdgeBuilder min_support 阈值（per 0 条根因修复）。
# 默认 2 让小仓库默认能建至少 2 commit 触发的边；env 可覆盖（ops 调试需要）。
CODEGRAPH_COCHANGE_MIN_SUPPORT: int = env.int(
 "CODEGRAPH_COCHANGE_MIN_SUPPORT", default=2
)
# Phase：HybridSearchService 编排器 RAG/图谱 token 预算比例（per ）。
# 默认 0.6 表示 RAG 占 60%、图谱 enrichment 占 40%。
# 越界 [<0.1 | >0.9] 由 `HybridBudget.from_settings` clamp 到边界 + structlog warning。
# NOTE: 默认值与 services/retrieval/budget.py:GRAPHRAG_BUDGET_RATIO_DEFAULT 同值，
# 调整需双改（settings.py 加载顺序敏感，无法直接 import budget 常量避免循环）。
GRAPHRAG_BUDGET_RATIO: float = env.float("GRAPHRAG_BUDGET_RATIO", default=0.6)
# =============================================================================
# Phase LSP Client + Supervisor Settings
# =============================================================================
# Phase：volar 真实命令落地（vue-language-server --stdio）
# initialization_options.typescript.tsdk 由 VolarPool._build_supervisor 在每实例化时
# 用 node_check.discover_tsdk 动态注入；占位 None 仅给 mypy 用。
# advisory（per Pitfall P-）：study-app 大插件链场景启动 60-90s，
# 运维 env 调 LSP_STARTUP_TIMEOUT_SECONDS=60 缓解。
LSP_SERVERS: dict[str, dict[str, Any]] = {
 "volar": {
 "command": ["vue-language-server", "--stdio"],
 "language_ids": [
 "vue",
 "typescript",
 "typescriptreact",
 "javascript",
 "javascriptreact",
 ],
 "initialization_options": {
 "typescript": {"tsdk": None},
 "vue": {"hybridMode": False},
 },
 "enabled": True,
 },
 # Phase /：gopls 真实命令落地（gopls serve）
 # initialization_options 平铺 key（gopls 点号格式，非嵌套 dict）
 # advisory（per Pitfall P-）：大仓库启动 20-60s；运维 env 调：
 # LSP_STARTUP_TIMEOUT_SECONDS=60
 "gopls": {
 "command": ["gopls", "serve"],
 "language_ids": ["go"],
 "initialization_options": {
 "build.directoryFilters": ["-vendor", "-node_modules"],
 "ui.diagnostic.diagnosticsDelay": "1s",
 },
 "enabled": True,
 },
}
# Phase：LSP 三层超时（env 可覆盖）
# - STARTUP_TIMEOUT 默认 30s（volar 首次启动 30-60s spike 实测）
# - REQUEST_TIMEOUT 默认 10s（普通 capability 请求）
# - HEALTH_CHECK_TIMEOUT 默认 5s（workspace/symbol("") ping）
LSP_STARTUP_TIMEOUT_SECONDS: int = env.int("LSP_STARTUP_TIMEOUT_SECONDS", default=30)
LSP_REQUEST_TIMEOUT_SECONDS: int = env.int("LSP_REQUEST_TIMEOUT_SECONDS", default=10)
LSP_HEALTH_CHECK_TIMEOUT_SECONDS: int = env.int(
 "LSP_HEALTH_CHECK_TIMEOUT_SECONDS", default=5
)
# Phase：健康检查间隔（每 30s 一次 workspace/symbol("") ping）
LSP_HEALTH_CHECK_INTERVAL_SECONDS: int = env.int(
 "LSP_HEALTH_CHECK_INTERVAL_SECONDS", default=30
)
# Phase：crash-loop 防护硬阈值（连续 N 次重启失败后转 DISABLED）
LSP_MAX_RESTART_ATTEMPTS: int = env.int("LSP_MAX_RESTART_ATTEMPTS", default=3)
# Phase：idle timeout 回收（默认 30 分钟无使用即 stop）
LSP_IDLE_TIMEOUT_SECONDS: int = env.int("LSP_IDLE_TIMEOUT_SECONDS", default=1800)
# =============================================================================
# Phase Volar Backend Settings
# =============================================================================
# Phase：VolarPool 并发上限（per v25.0 spike 锁定 4GB 内存预算）
VOLAR_POOL_MAX_CONCURRENT: int = env.int("VOLAR_POOL_MAX_CONCURRENT", default=4)
# Phase：volar backend 运维 kill-switch；False 时 apps.ready 跳过
# register_backend，BACKEND_REGISTRY 5 项保留 tree-sitter 默认。
VOLAR_BACKEND_ENABLED: bool = env.bool("VOLAR_BACKEND_ENABLED", default=True)
# =============================================================================
# Phase Gopls Backend Settings
# =============================================================================
# Phase：gopls backend 运维 kill-switch
# 默认 False —— Phase 仅落基础设施，不切 BACKEND_REGISTRY["go"]
# Phase 已切 True 完成 Stage C 切换；可 env 覆盖：GOPLS_BACKEND_ENABLED=False
GOPLS_BACKEND_ENABLED: bool = env.bool("GOPLS_BACKEND_ENABLED", default=True)
# =============================================================================
# APScheduler Settings
# =============================================================================
# 仓库轮询间隔秒数，与 IntervalTrigger(hours=2) 及 SyncStatusView.interval_seconds 保持同步
SYNC_INTERVAL_SECONDS: int = 7200
# Format for django-apscheduler scheduler
APSCHEDULER_DATETIME_FORMAT = "N j, Y, f:s a"
# Seconds the scheduler checks for jobs to run
APSCHEDULER_RUN_NOW_TIMEOUT = 25
# Enable scheduler (can be disabled in tests)
FF_ENABLE_SCHEDULER = env.bool("FF_ENABLE_SCHEDULER", True)
# =============================================================================
# OpenAI 兼容层配置
# =============================================================================
# API Keys 白名单（逗号分隔），空字符串时 AllowAny
# 启用后自动触发 Bearer token 校验；启用时务须修复 T- IDOR（参见 compat/request_handler.py）
OPENAI_COMPAT_API_KEYS: list[str] = [
 k.strip
 for k in os.environ.get("OPENAI_COMPAT_API_KEYS", "").split(",")
 if k.strip
]
# =============================================================================
# MCP 工具安全
# =============================================================================
# MCP 工具执行白名单：仅允许以下 server_command 值
MCP_ALLOWED_COMMANDS: list[str] = [
 "npx",
 "uvx",
 "node",
 "python",
]
# =============================================================================
# Logging — Structlog 配置（Phase 凭证泄漏防护）
# =============================================================================
# configure_structlog 必须在 LOGGING dictConfig 之后、任何业务 logger 实例化之前调用。
# settings.py 末尾是最早安全点（pytest-django / gunicorn / daphne 启动时一次性配置完成）。
from common.logging import configure_structlog # noqa: E402
configure_structlog
