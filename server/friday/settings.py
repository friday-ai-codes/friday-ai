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

patch_asyncio_iscoroutinefunction()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

# Ensure data directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "repos").mkdir(exist_ok=True)
(DATA_DIR / "sessions").mkdir(exist_ok=True)
(DATA_DIR / "credentials").mkdir(exist_ok=True)

# 本地 Git clone 根目录（contract：_calculate_commit_distance 使用此路径 / {repo.id}/）
REPO_CLONE_DIR = DATA_DIR / "repos"

# Initialize django-environ
INSECURE_SECRET_KEY = "django-insecure-change-me-in-production"
LOCALHOST_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

env = environ.Env(
    DEBUG=(bool, False),
    SECRET_KEY=(str, INSECURE_SECRET_KEY),
    ALLOWED_HOSTS=(list, LOCALHOST_HOSTS),
)

# Read .env file (server/.env 优先，回退到项目根 .env)
_env_file = BASE_DIR / ".env"
if not _env_file.exists():
    _env_file = BASE_DIR.parent / ".env"
env.read_env(_env_file, overwrite=False)

# =============================================================================
# Core Settings
# =============================================================================

debug_override = os.environ.get("FRIDAY_DEBUG")
if debug_override is not None:
    DEBUG = debug_override.lower() in ("true", "1", "yes")
else:
    DEBUG = env.bool("DEBUG", default=False)

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env("SECRET_KEY")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=LOCALHOST_HOSTS)

# 仓库本地 bare 镜像（services/repo_mirror.py）：为 MCP grep_repository /
# get_repository_file 提供确定性的精确检索与全量文件读取；关闭后相关工具
# 回退到 Qdrant 索引路径。
REPO_MIRROR_ENABLED = env.bool("FRIDAY_REPO_MIRROR_ENABLED", default=True)
# grep 引擎偏好：True 且系统装有 rg 时用 ripgrep（快照 worktree 上跑），
# 否则回退 git grep（直接搜 bare 对象库，无额外依赖）。
REPO_MIRROR_USE_RIPGREP = env.bool("FRIDAY_REPO_MIRROR_USE_RIPGREP", default=True)

FRIDAY_ENV = env.str("FRIDAY_ENV", default="development").lower()
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
    "audit",
    "notifications",
    "feedback",
    "system",
    "resumable",
    "durable",
    "repositories",
    "codegraph",
    "code_relations",
    "knowledge",
    "projects",
    "feishu",
    "delivery",
    "initiatives",
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
    "interactions",
    "access_tokens",
    "mcp_tools",
    "prompts",
    "services.code_intel.apps.CodeIntelConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    # 靠最外层：尽早绑定 request_id/source/trace_id+system 占位，覆盖整个请求生命周期，
    # 请求结束清理 contextvars（CTX-01；真实 user_id 由 DRF LogContextMixin 认证后补绑）。
    "common.middleware.RequestLogContextMiddleware",
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
        "DIRS": [],
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

# -----------------------------------------------------------------------------
# Django 缓存（CACHES）
# -----------------------------------------------------------------------------
# 用 Redis 做**跨进程/跨副本共享**缓存（首页 stats、SystemSetting、健康检查结果、
# DRF 登录限流）。此前未配置 CACHES → 默认 LocMemCache（进程内，多 gunicorn worker
# 各自一份、不共享），导致缓存命中率低、限流可被绕过。
# 默认复用 channel layer 的 Redis（CACHE_REDIS_URL 留空时回退该 URL）；无 Redis 的
# 本地裸跑（USE_REDIS_CHANNEL_LAYER=false）退回 LocMem，保持开箱即用。
CACHE_REDIS_URL = env.str(
    "CACHE_REDIS_URL",
    default=(REDIS_CHANNEL_LAYER_URL if USE_REDIS_CHANNEL_LAYER else ""),
)
if CACHE_REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": CACHE_REDIS_URL,
            "KEY_PREFIX": "friday",
            "TIMEOUT": 300,
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
                # Redis 抖动/不可用时 fail-soft：缓存操作退化为 miss/no-op，绝不
                # 让缓存故障拖垮业务请求（缓存只是优化、不是真相源）。
                "IGNORE_EXCEPTIONS": True,
            },
        }
    }
    DJANGO_REDIS_IGNORE_EXCEPTIONS = True
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        },
    }

# 项目文件（ProjectDoc）渲染内容 read-through 缓存 TTL（秒，SYNC-05）。
# 缓存只是渲染加速、DB 恒为真相源：写时/收飞书事件按 doc_id delete 失效，下次读回填；
# TTL 仅作"漏失效"的兜底过期（秒级最终一致）。redis 不可用时 IGNORE_EXCEPTIONS +
# doc_sync_cache 模块的 try/except 静默降级直读 DB，绝不反噬渲染主流程。
DOC_RENDER_CACHE_TTL = env.int("DOC_RENDER_CACHE_TTL", default=300)

# 方案编排 recalling 阶段召回的实体 kinds（KNOW-04 编排召回扩容）。
# 默认含 document（项目沉淀）与 learning_case（历史经验），新 kinds 默认开；
# env 逗号分隔列表可覆盖（如 PROCESS_RECALL_ENTITY_KINDS=work_item,tech_plan）。
# 非法 kind 经 vector_recall「传入 ∩ 白名单」严格交集过滤，不放大召回面。
PROCESS_RECALL_ENTITY_KINDS = env.list(
    "PROCESS_RECALL_ENTITY_KINDS",
    default=["work_item", "tech_plan", "code_change", "document", "learning_case"],
)

# 每 kind 召回上限（KNOW-04）：编排召回单查后按 kind 截断，守 token 预算
# （防召回候选集膨胀挤爆下游 prompt）。env 用 JSON 覆盖，
# 如 PROCESS_RECALL_KIND_LIMITS='{"work_item": 2}'；未配置的 kind 上限兜底 3。
PROCESS_RECALL_KIND_LIMITS = env.json(
    "PROCESS_RECALL_KIND_LIMITS",
    default={
        "work_item": 4,
        "tech_plan": 4,
        "code_change": 4,
        "document": 3,
        "learning_case": 3,
    },
)


def _require_redis_for_multi_replica(*, expect_multi: bool, use_redis: bool) -> None:
    """多副本 / 多 worker 部署必须启用 Redis channel layer 的运行期 fail-closed 校验。

    抽成无副作用纯函数（不读 env、不触全局），便于单测直接断言而不必重载整个
    settings 模块。``expect_multi=True``（声明多副本/多进程）且未启用 Redis channel
    layer 时 raise ``ImproperlyConfigured``；否则 return None。
    """
    if expect_multi and not use_redis:
        raise ImproperlyConfigured(
            "多副本 / 多 worker 部署必须启用 Redis channel layer"
            "（USE_REDIS_CHANNEL_LAYER=true + REDIS_URL），否则 WebSocket 推送跨副本丢消息；"
            "单副本单 worker 才可用内存 channel layer。"
        )


# 多副本信号：helm configmap 在 server.replicaCount>1 / gunicornWorkers>1 时注入
# FRIDAY_EXPECT_MULTI_REPLICA=true；单进程多 gunicorn worker 同样需共享 channel layer，
# 故 GUNICORN_WORKERS>1 也触发校验。与 helm 模板期 fail 条件同源（web/server 层），
# 避免"模板通过、运行期崩"的不对称。
_EXPECT_MULTI_REPLICA = (
    env.bool("FRIDAY_EXPECT_MULTI_REPLICA", default=False)
    or env.int("GUNICORN_WORKERS", default=1) > 1
)
_require_redis_for_multi_replica(
    expect_multi=_EXPECT_MULTI_REPLICA, use_redis=USE_REDIS_CHANNEL_LAYER
)

# Workflow idempotency backend migration entrypoint.
# Current default remains in-memory for compatibility.
WORKFLOW_IDEMPOTENCY_BACKEND = env.str("WORKFLOW_IDEMPOTENCY_BACKEND", default="memory")
WORKFLOW_IDEMPOTENCY_REDIS_URL = env.str(
    "WORKFLOW_IDEMPOTENCY_REDIS_URL",
    default=REDIS_CHANNEL_LAYER_URL,
)

# =============================================================================
# LLM 并发治理（CONC-02）：按 ProviderCredential 凭证级限流
# =============================================================================
# 每个 ProviderCredential 可配 max_concurrency（默认 50，0=不限）。chat/深度分析/
# 编码的 LLM 调用按凭证 id 限流：配置 Redis 时用租约信号量（跨副本精确），否则
# 进程内 asyncio.Semaphore fallback（单进程精确、多进程各自计数，降级可用）。
# 超过上限时排队等待至超时，再抛友好「系统繁忙」错误，不打到 provider 触发 429。
# Redis URL：显式 LLM_CONCURRENCY_REDIS_URL 优先；否则仅当启用 channel layer redis
# 时复用其 URL；都没有则走进程内 fallback（空串）。
LLM_CONCURRENCY_REDIS_URL = env.str(
    "LLM_CONCURRENCY_REDIS_URL",
    default=(REDIS_CHANNEL_LAYER_URL if USE_REDIS_CHANNEL_LAYER else ""),
)
# 获取并发槽位的最大等待时长（秒），超时抛「系统繁忙」
LLM_CONCURRENCY_ACQUIRE_TIMEOUT_SECONDS = env.float(
    "LLM_CONCURRENCY_ACQUIRE_TIMEOUT_SECONDS", default=60.0
)
# Redis 租约 TTL（秒）：持有者崩溃后租约自动过期回收，避免永久占槽；
# 须 > 单次 LLM 调用最长耗时（深度分析可达数分钟），持有期内自动续租。
LLM_CONCURRENCY_LEASE_TTL_SECONDS = env.int(
    "LLM_CONCURRENCY_LEASE_TTL_SECONDS", default=900
)

# =============================================================================
# 仓库路由 v2（RepoRouterV2）Stage 1 调参
# =============================================================================
# Stage 1 是 LLM 树推理，超时即静默降级为 Stage 0（置信度全 low、auto_selected
# 恒 false，下游强制确认因此无差别触发）。默认 30s 对推理型模型偏紧：实测
# mimo-v2.5-pro 单次 80s、mimo-v2.5 在 12 候选下也 >30s，导致 Stage 1 从未成功。
# 三个值均可用环境变量按供应商速度调整，不必改代码发版。
REPO_ROUTER_STAGE1_TIMEOUT_SECONDS = env.float("REPO_ROUTER_STAGE1_TIMEOUT_SECONDS", default=90.0)
# 送进 Stage 1 prompt 的候选仓数量上限。Stage 0 仍聚合更多候选供降级时使用，
# 这里只收窄"喂给 LLM"的部分——prompt 越短越快，且尾部低分候选本就不会被选中。
REPO_ROUTER_STAGE1_MAX_CANDIDATES = env.int("REPO_ROUTER_STAGE1_MAX_CANDIDATES", default=8)
# 每个候选仓在 prompt 里展示的命中节点数上限。
REPO_ROUTER_STAGE1_HITS_PER_REPO = env.int("REPO_ROUTER_STAGE1_HITS_PER_REPO", default=4)

# =============================================================================
# 仓库路由 v2 确定性置信度阈值（RELY-04）
# =============================================================================
# confidence 由分数 margin 确定性推导（codegraph.services.repo_router_scoring
# .derive_confidence）：S(1) >= θ_abs 且 margin >= θ_margin → high；
# S(1) >= θ_med → medium；否则 low。调用方读取后以参数注入纯函数。
# 初值来自 .planning/research/ROUTING-RANKING.md §1.3a；golden set 校准后
# 可经环境变量调整，不必改代码发版。
REPO_ROUTER_CONF_THETA_ABS = env.float("REPO_ROUTER_CONF_THETA_ABS", default=0.55)
REPO_ROUTER_CONF_THETA_MARGIN = env.float("REPO_ROUTER_CONF_THETA_MARGIN", default=0.08)
REPO_ROUTER_CONF_THETA_MED = env.float("REPO_ROUTER_CONF_THETA_MED", default=0.35)

# =============================================================================
# 可恢复任务（断点恢复）
# =============================================================================
# 真相源 = DB（Postgres/SQLite）：长任务（索引 / 图谱构建等）登记到 ResumableTask，
# 进程被 docker compose 升级、Pod 被 k8s 重建后由 RecoveryScheduler 自动续跑，
# 断电不丢。Redis 仅在多副本部署时做"每轮恢复扫描"的集群级互斥（去重加速），
# 不作为状态真相源 —— 关闭时正确性仍由 DB 行级 CAS 保证。
RESUMABLE_RECOVERY_ON_STARTUP = env.bool("RESUMABLE_RECOVERY_ON_STARTUP", default=True)
# 租约 TTL：运行中任务每 HEARTBEAT 秒续租到 now+TTL；启动扫描只领取已过期租约。
RESUMABLE_LEASE_TTL_SECONDS = env.int("RESUMABLE_LEASE_TTL_SECONDS", default=90)
RESUMABLE_HEARTBEAT_INTERVAL_SECONDS = env.int(
    "RESUMABLE_HEARTBEAT_INTERVAL_SECONDS", default=30
)
# 可选：启用基于 Redis 的集群级恢复锁（多副本/k8s 推荐）。默认关闭走 DB CAS。
RESUMABLE_USE_REDIS_LOCK = env.bool("RESUMABLE_USE_REDIS_LOCK", default=False)

# 生产模式下要求 WebSocket 使用 TLS (wss://)
# 默认值：仅生产环境启用，开发环境允许 ws://
# 可通过环境变量 WEBSOCKET_REQUIRE_TLS 显式控制
WEBSOCKET_REQUIRE_TLS = env.bool("WEBSOCKET_REQUIRE_TLS", IS_PRODUCTION)

# =============================================================================
# Runner 注册
# =============================================================================
# 共享注册令牌（GitLab 风格）：容器化部署时 server 与 runner 通过同一个
# RUNNER_REGISTRATION_TOKEN 完成自动注册，无需先在 UI 创建一次性令牌。
# 留空则禁用共享令牌，仅接受 UI 创建的一次性 RegistrationToken。
RUNNER_REGISTRATION_TOKEN = env.str("RUNNER_REGISTRATION_TOKEN", default="")

# =============================================================================
# Database
# =============================================================================
# 支持多种数据库，通过 DATABASE_URL 环境变量配置
# 格式示例：
#   SQLite:    sqlite:///./data/friday.db
#   PostgreSQL: postgres://user:password@host:5432/dbname
#   MySQL:      mysql://user:password@host:3306/dbname
#   MariaDB:    mysql://user:password@host:3306/dbname
#
# 注意：使用 PostgreSQL 需安装 psycopg[binary]
#       使用 MySQL/MariaDB 需安装 mysqlclient

DEFAULT_DATABASE_URL = f"sqlite:///{DATA_DIR / 'friday.db'}"
DATABASES = {"default": env.db("DATABASE_URL", default=DEFAULT_DATABASE_URL)}

# =============================================================================
# 数据库连接池 / PgBouncer（Phase A —— async 高并发底座）
# =============================================================================
# 背景：Django async ORM（aget/abulk_create 等）走 sync_to_async；高并发重活下若
# 无连接池，每个工作线程反复 connect/close，开销盖过查询本身。Django 6.0 官方 async
# 指引明确：async 模式应禁用持久连接（CONN_MAX_AGE），改用数据库后端自带连接池。
#
# 仅对 PostgreSQL 生效；SQLite / MySQL 保持原样（dev/pytest 走 SQLite，零回归）。
#
# 拓扑（per 架构讨论，进程角色分离已完成）：
# - web（server 角色）：可置于 PgBouncer(transaction pooling) 之后 → 设
#   DB_PGBOUNCER=true：禁用服务端/命名游标（事务级池化下跨事务不可用）+ 不再叠加
#   psycopg 应用层池（连接复用交给 PgBouncer，避免双层池）。
# - worker / scheduler：必须**直连** Postgres —— Procrastinate 依赖 LISTEN/NOTIFY，
#   穿不过 transaction pooling → 启用 psycopg3 应用层池高效复用连接。
DB_PGBOUNCER = env.bool("DB_PGBOUNCER", default=False)


def configure_postgres_pool(
    db_config: dict,
    *,
    pgbouncer: bool,
    pool_enabled: bool,
    min_size: int,
    max_size: int,
    timeout: int,
) -> None:
    """为 PostgreSQL 配置连接池 / PgBouncer 安全选项（就地修改 db_config）。

    抽成无副作用纯函数（不读 env、不触全局），便于单测直接断言三条分支，而不必
    重载整个 settings 模块。仅当 ENGINE 含 'postgresql' 时生效——非 postgres 引擎
    （SQLite/MySQL）直接 return、不改任何字段（dev/pytest 零回归红线）。

    - 任一 postgres 分支：CONN_MAX_AGE=0（pool 与持久连接互斥，Django 强约束）。
    - pgbouncer=True（web 置于 transaction pooling 之后）：禁用服务端/命名游标
      （跨事务不可用）+ 移除 psycopg 应用层池（连接复用交给 PgBouncer）。
    - 否则 + pool_enabled：启用 psycopg3 应用层池（Django 5.1+ 原生 OPTIONS["pool"]）。
    """
    if "postgresql" not in db_config.get("ENGINE", ""):
        return
    db_config["CONN_MAX_AGE"] = 0
    options = db_config.setdefault("OPTIONS", {})
    if pgbouncer:
        db_config["DISABLE_SERVER_SIDE_CURSORS"] = True
        options.pop("pool", None)
    elif pool_enabled:
        # 多 worker/副本时务必保证 Σ(进程数 × max_size) ≤ Postgres max_connections，
        # 否则改用 PgBouncer（DB_PGBOUNCER=true）跨进程复用连接。
        options["pool"] = {
            "min_size": min_size,
            "max_size": max_size,
            "timeout": timeout,
        }


configure_postgres_pool(
    DATABASES["default"],
    pgbouncer=DB_PGBOUNCER,
    pool_enabled=env.bool("DB_POOL_ENABLED", default=True),
    min_size=env.int("DB_POOL_MIN_SIZE", default=2),
    max_size=env.int("DB_POOL_MAX_SIZE", default=10),
    timeout=env.int("DB_POOL_TIMEOUT", default=30),
)

# =============================================================================
# durable 任务底座（DurableTaskService 适配层）
# =============================================================================
# 后端选择：auto=按 DB 引擎自动（Postgres→Procrastinate durable / 否则 in-process
# fallback）/ procrastinate=强制 durable（需 Postgres，非 Postgres 时 fail-soft 回退）
# / inprocess=强制进程内 fallback（即便 Postgres）。唯一权威判定见
# durable.service._use_procrastinate（service 与 settings 共用同一函数）。
DURABLE_TASK_BACKEND = env.str("DURABLE_TASK_BACKEND", default="auto")
# 进程角色：web|worker|scheduler|migrate|test，门禁 AppConfig.ready() 启动副作用
# （DURABLE-02，Plan 60-02 消费）；默认 web 保持既有单进程部署零回归。
FRIDAY_PROCESS_ROLE = env.str("FRIDAY_PROCESS_ROLE", default="web")

# Procrastinate Django 集成的条件注册（DURABLE-01）：
# 复用 durable.service 的唯一权威判定 _use_procrastinate（service 与 settings
# 共用同一纯函数，禁止在此另写等价引擎/backend 判据）。仅当默认 DB 引擎含
# postgresql 且 DURABLE_TASK_BACKEND ∈ {auto, procrastinate} 时，才把
# procrastinate.contrib.django 加入 INSTALLED_APPS——这样 procrastinate 自带迁移
# 创建的 procrastinate_* 表，只在后端真正启用时才存在。
#
# SQLite / auto+sqlite 永不追加：避免 Postgres-only 迁移在 SQLite migrate 失败
# （Pitfall 3），也不会留下 orphan procrastinate_jobs 表。_use_procrastinate 是顶层
# 零 settings 访问的纯函数，django.setup() 期 import 不触发循环 import。
# 注意：Django 集成下 schema 由 procrastinate 自带迁移管理，绝不调用 procrastinate
# CLI 的 schema 子命令。
from durable.service import _use_procrastinate  # noqa: E402

if _use_procrastinate(DATABASES["default"]["ENGINE"], DURABLE_TASK_BACKEND):
    INSTALLED_APPS.append("procrastinate.contrib.django")

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
#     origin.strip()
#     for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
#     if origin.strip()
# ]

# =============================================================================
# REST Framework Settings
# =============================================================================

REST_FRAMEWORK = {
    # PAT 类必须排首位：它对非 friday_pat_ 前缀的 Bearer return None 让行，CookieJWT
    # 接住 JWT（前缀闸门，互不吞）。反之若 CookieJWT 在前，会对 friday_pat_ Bearer 抛
    # InvalidToken，PAT 类永远跑不到（Pitfall 1）。站点级 401 由 PAT 类的
    # authenticate_header 保住（Pitfall 2）。
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "access_tokens.authentication.AccessTokenAuthentication",
        "common.authentication.CookieJWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "common.exceptions.custom_exception_handler",
    "DEFAULT_THROTTLE_RATES": {
        # 登录限流按「IP+用户名」计数，且登录成功即清零——实际只拦"对单一账号
        # 连续失败 5 次"的爆破行为，不影响共享出口 IP 的正常团队
        "auth_login": "5/min",
        # 纯 IP 维度兜底，防单 IP 批量扫描多账号；需容纳 NAT 后整个团队的正常登录
        "auth_login_ip": "30/min",
        "auth_refresh": "20/min",
    },
    # 信任的反向代理跳数（默认 1 = 部署自带的 nginx）。决定 get_ident() 从
    # X-Forwarded-For 取哪一跳作为限流 IP；不设置时 DRF 信任整条 XFF，
    # 攻击者伪造头即可不断更换限流桶绕过限速。
    "NUM_PROXIES": int(os.environ.get("NUM_PROXIES", "1")),
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
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "False").lower() in ("true", "1", "yes")
COOKIE_SAMESITE = os.environ.get("COOKIE_SAMESITE", "Lax")
COOKIE_HTTPONLY = os.environ.get("COOKIE_HTTPONLY", "True").lower() in ("true", "1", "yes")

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

# 飞书开放平台 HTTP 超时（秒）。httpx 默认 timeout=None 即永不超时——半开连接、
# DNS 卡死或对端不回都会把 async worker 一直占住，进而级联拖垮工作流触发、webhook
# 处理与 IM 发卡。统一从这里取值，不在各调用点写魔数。
FEISHU_HTTP_TIMEOUT_SECONDS = env.float("FEISHU_HTTP_TIMEOUT_SECONDS", default=30.0)

# =============================================================================
# 邮件（系统告警通知，ALERT-03）
# =============================================================================
# 全仓首次引入 Django SMTP 配置：系统告警邮件通道（74-03 alert_notifier 消费）。
# EMAIL_HOST 留空 = 未配置 SMTP → 邮件通道降级（notify 据此回写 email_sent=skipped，
# 不依赖 backend 行为）；未配置时 backend 用 dummy（send_mail 静默丢弃不抛）。
# 收件人列表 / 总开关走 SystemSetting（ALERT_EMAIL_RECIPIENTS / ALERT_EMAIL_ENABLED）。
EMAIL_HOST = env.str("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env.str("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env.str("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=False)
DEFAULT_FROM_EMAIL = env.str("DEFAULT_FROM_EMAIL", default="Friday AI <noreply@localhost>")
# 防 SMTP 挂起拖垮评估线程（硬约束，T-74-03-03）。
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=10)
# EMAIL_HOST 非空走真实 SMTP backend；否则 dummy（静默丢弃，不抛）。
EMAIL_BACKEND = (
    "django.core.mail.backends.smtp.EmailBackend"
    if EMAIL_HOST
    else "django.core.mail.backends.dummy.EmailBackend"
)

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
        # 运维监控「系统日志」面板数据源：把 stdlib 日志写入内存环形缓冲
        "ring_buffer": {
            "class": "common.logging.RingBufferHandler",
            "level": "INFO",
        },
    },
    "root": {
        "handlers": ["console", "ring_buffer"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console", "ring_buffer"],
            "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
        "friday": {
            "handlers": ["console", "ring_buffer"],
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

# When True, code graph extraction runs during indexing. Set False to skip graph writes.
# **写入侧** 语义（per implementation contract）：控制 indexer 是否构建 ChunkEdge / 写
# Qdrant payload `related_chunks`；与读出侧 ENABLE_GRAPHRAG_ENRICHMENT 独立解耦。
ENABLE_CODEGRAPH = env.bool("ENABLE_CODEGRAPH", True)

# RAG 切片模式。"ast_aware" = 符号驱动精细切片（按函数/类边界切，复用
# codegraph tree-sitter 抽取，含 TS interface/type、export 解包、大符号不丢尾）；
# "fixed" = 旧 tree-sitter 节点直取（向后兼容回退）。默认 ast_aware；切换后需重新
# 索引仓库方能对存量 chunk 生效。
CHUNKING_MODE: str = env.str("CHUNKING_MODE", "ast_aware")

# implementation contract：**读出侧** GraphRAG enrichment 开关（与 ENABLE_CODEGRAPH 写入侧解耦）。
# False 时 HybridSearchService.search 入口强制 ``_search_rag_only`` 路径，即使
# Provider 实现 GraphCapableProvider Protocol，输出 byte-equivalent implementation 路径。
# 默认 True 保持向后兼容（与 v23.0 / implementation 行为一致）。
# **唯一允许的直读点**：``services/retrieval/hybrid_search.py::HybridSearchService.search``
# 入口（per CONTEXT.md 关键不变量；新增直读点应 PR review 拒绝）。
ENABLE_GRAPHRAG_ENRICHMENT: bool = env.bool("ENABLE_GRAPHRAG_ENRICHMENT", default=True)

# 代码智能 Provider class path（默认 LocalProvider 包装 codegraph 现有服务，
# future 可切到 RemoteProvider 一次替换全局生效，per contract / contract）
CODE_INTELLIGENCE_PROVIDER: str = env.str(
    "CODE_INTELLIGENCE_PROVIDER",
    "services.code_intel.local_provider.LocalProvider",
)

# 各语言使用的 extractor backend（tree_sitter / volar / gopls）—— 声明性映射。
# ：默认禁用 LSP 后，运行期实际后端由 VOLAR/GOPLS_BACKEND_ENABLED 两个
# kill-switch 经 codegraph/apps.py::ready() 决定（关闭即全回落 TreeSitterBackend），
# 本表仅记录「重开 LSP 时各语言期望切换的后端」。go 回落 tree_sitter（gopls 冷启动慢）；
# ts/tsx/vue/js/jsx 仍声明 volar 作为重开目标（kill-switch 关闭时不生效）。
EXTRACTOR_BACKENDS: dict[str, str] = {
    "python": "tree_sitter",
    "go": "tree_sitter",         # ：回落 tree_sitter（默认禁用 gopls）
    "typescript": "volar",       # 声明性：重开 volar 时目标后端（默认 kill-switch 关）
    "tsx": "volar",              # implementation 切
    "vue": "volar",              # implementation 切
    "javascript": "volar",       # implementation 新增（之前未有）
    "jsx": "volar",              # implementation 新增
    "html": "tree_sitter",       # implementation
    "css": "tree_sitter",        # implementation
}

# implementation B3：CoChangedEdgeBuilder min_support 阈值（per work item 0 条根因修复）。
# 默认 2 让小仓库默认能建至少 2 commit 触发的边；env 可覆盖（ops 调试需要）。
CODEGRAPH_COCHANGE_MIN_SUPPORT: int = env.int(
    "CODEGRAPH_COCHANGE_MIN_SUPPORT", default=2
)

# Galaxy 图谱文件缓存（codegraph/galaxy/cache.py）。
# 全量聚合结果落盘 + 数据签名失效，把数秒的聚合请求降到毫秒级。
# GALAXY_CACHE_ENABLED=False 为逃生舱：直接走实时聚合。
GALAXY_CACHE_ENABLED: bool = env.bool("GALAXY_CACHE_ENABLED", default=True)
# 启动后是否在后台线程对比签名预热各仓库缓存
GALAXY_CACHE_WARM_ON_STARTUP: bool = env.bool(
    "GALAXY_CACHE_WARM_ON_STARTUP", default=True
)
GALAXY_CACHE_DIR = DATA_DIR / "galaxy_cache"

# 图谱构建孤儿行回收：后台构建任务（run_in_background）随进程内存存活，无法
# 跨进程重启幸存。服务进程启动时把"超过该阈值仍处于 RUNNING 的 GraphBuildHistory"
# 视为孤儿 → 标记 FAILED 并把对应 Repository.graph_build_status 由 RUNNING 归位
# FAILED，避免幽灵 RUNNING 行永久卡住「准备中」并挡住 rebuild（graph already running）。
# 设阈值（而非无脑回收所有 RUNNING）是为多 worker 部署留安全边界：刚被另一个
# worker 创建的 RUNNING 行不应被新启动 worker 误杀。设 0 关闭该回收。
GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP: bool = env.bool(
    "GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP", default=True
)
GRAPH_BUILD_ORPHAN_TIMEOUT_MINUTES: int = env.int(
    "GRAPH_BUILD_ORPHAN_TIMEOUT_MINUTES", default=30
)

# HybridSearchService 编排器 RAG/图谱 token 预算比例（per contract）。
# 默认 0.6 表示 RAG 占 60%、图谱 enrichment 占 40%。
# 越界 [<0.1 | >0.9] 由 `HybridBudget.from_settings()` clamp 到边界 + structlog warning。
# NOTE: 默认值与 services/retrieval/budget.py:GRAPHRAG_BUDGET_RATIO_DEFAULT 同值，
# 调整需双改（settings.py 加载顺序敏感，无法直接 import budget 常量避免循环）。
GRAPHRAG_BUDGET_RATIO: float = env.float("GRAPHRAG_BUDGET_RATIO", default=0.6)

# 跨仓 API 扩散 token 预算 + 启停开关。
# CROSS_REPO_BUDGET_RATIO：cross_repo 预算比例（默认 0.0 = 不分配跨仓预算）。
#   设置为 0.20 + GRAPHRAG_BUDGET_RATIO=0.50 → HybridBudget 50/30/20 预算（per work item）。
# ENABLE_CROSS_REPO_ENRICHMENT：False 时 wave 跨仓扩散完全短路，输出 byte-equivalent v24。
#   默认 True（per work item）；生产环境可设 ENABLE_CROSS_REPO_ENRICHMENT=False 回 v24 行为。
CROSS_REPO_BUDGET_RATIO: float = env.float("CROSS_REPO_BUDGET_RATIO", default=0.0)
ENABLE_CROSS_REPO_ENRICHMENT: bool = env.bool("ENABLE_CROSS_REPO_ENRICHMENT", default=True)

# =============================================================================
# implementation LSP Client + Supervisor Settings
# =============================================================================

# volar 真实命令落地（vue-language-server --stdio）
# initialization_options.typescript.tsdk 由 VolarPool._build_supervisor 在每实例化时
# 用 node_check.discover_tsdk() 动态注入；占位 None 仅给 mypy 用。
# advisory（per Pitfall P-checkpoint）：example-app 大插件链场景启动 60-90s，
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
    # implementation / gopls 真实命令落地（gopls serve）
    # initialization_options 平铺 key（gopls 点号格式，非嵌套 dict）
    # advisory（per Pitfall P-checkpoint）：大仓库启动 20-60s；运维 env 调：
    #   LSP_STARTUP_TIMEOUT_SECONDS=60
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

# LSP 三层超时（env 可覆盖）
# - STARTUP_TIMEOUT 默认 30s（volar 首次启动 30-60s spike 实测）
# - REQUEST_TIMEOUT 默认 10s（普通 capability 请求）
# - HEALTH_CHECK_TIMEOUT 默认 5s（workspace/symbol("") ping）
LSP_STARTUP_TIMEOUT_SECONDS: int = env.int("LSP_STARTUP_TIMEOUT_SECONDS", default=30)
LSP_REQUEST_TIMEOUT_SECONDS: int = env.int("LSP_REQUEST_TIMEOUT_SECONDS", default=10)
LSP_HEALTH_CHECK_TIMEOUT_SECONDS: int = env.int(
    "LSP_HEALTH_CHECK_TIMEOUT_SECONDS", default=5
)

# 健康检查间隔（每 30s 一次 workspace/symbol("") ping）
LSP_HEALTH_CHECK_INTERVAL_SECONDS: int = env.int(
    "LSP_HEALTH_CHECK_INTERVAL_SECONDS", default=30
)

# crash-loop 防护硬阈值（连续 N 次重启失败后转 DISABLED）
LSP_MAX_RESTART_ATTEMPTS: int = env.int("LSP_MAX_RESTART_ATTEMPTS", default=3)

# idle timeout 回收（默认 30 分钟无使用即 stop）
LSP_IDLE_TIMEOUT_SECONDS: int = env.int("LSP_IDLE_TIMEOUT_SECONDS", default=1800)

# =============================================================================
# implementation Volar Backend Settings
# =============================================================================

# VolarPool 并发上限（per legacy spike 锁定 4GB 内存预算）
VOLAR_POOL_MAX_CONCURRENT: int = env.int("VOLAR_POOL_MAX_CONCURRENT", default=4)

# volar backend 运维 kill-switch；False 时 apps.ready 跳过
# register_backend，BACKEND_REGISTRY 5 项保留 tree-sitter 默认。
# ：默认改 False —— 仅用 tree-sitter，缓解图谱构建慢与 LSP 冷启动等待；
# 调好 Volar 后经 env `VOLAR_BACKEND_ENABLED=true` 可逆重开（无需改代码）。
VOLAR_BACKEND_ENABLED: bool = env.bool("VOLAR_BACKEND_ENABLED", default=False)

# =============================================================================
# implementation Gopls Backend Settings
# =============================================================================

# gopls backend 运维 kill-switch
# ：默认改 False —— 仅用 tree-sitter，缓解图谱构建慢与 gopls 冷启动等待；
# 调好 gopls 后经 env `GOPLS_BACKEND_ENABLED=true` 可逆重开（无需改代码）。
GOPLS_BACKEND_ENABLED: bool = env.bool("GOPLS_BACKEND_ENABLED", default=False)

# =============================================================================
# APScheduler Settings
# =============================================================================

# 仓库轮询间隔秒数（contract），与 IntervalTrigger(hours=2) 及 SyncStatusView.interval_seconds 保持同步
SYNC_INTERVAL_SECONDS: int = 7200

# 飞书文档 TTL 兜底轮询间隔秒数（SYNC-01 漏事件兜底，83-06）：进行中项目 READY doc
# 周期比对飞书 revision，漂移即 defer durable_doc_sync_pull（与事件链路共用 lock + idempotency）。
DOC_SYNC_POLL_INTERVAL_SECONDS: int = 120

# Format for django-apscheduler scheduler
APSCHEDULER_DATETIME_FORMAT = "N j, Y, f:s a"

# Seconds the scheduler checks for jobs to run
APSCHEDULER_RUN_NOW_TIMEOUT = 25

# Enable scheduler (can be disabled in tests)
FF_ENABLE_SCHEDULER = env.bool("FF_ENABLE_SCHEDULER", True)

# =============================================================================
# OpenAI 兼容层配置（contract/work item）
# =============================================================================

# API Keys 白名单（逗号分隔），空字符串时 AllowAny（contract）
# 启用后自动触发 Bearer token 校验；启用时务须修复 security mitigation IDOR（参见 compat/request_handler.py）
OPENAI_COMPAT_API_KEYS: list[str] = [
    k.strip()
    for k in os.environ.get("OPENAI_COMPAT_API_KEYS", "").split(",")
    if k.strip()
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
# Frontend API Call Resolver 配置（work item）
# =============================================================================

API_DETECTOR_CONFIG: dict = {
    # base URL 模板 patterns（Python regex），用于从 URL 字符串剥除前缀
    "base_url_patterns": [
        r"\$\{configGlobal\.api\}",
        r"\$\{import\.meta\.env\.VITE_API_URL\}",
        r"\$\{import\.meta\.env\.VUE_APP_API_URL\}",
        r"\$\{process\.env\.VUE_APP_API\}",
        r"\$\{process\.env\.BASE_URL\}",
    ],
    # 强制追加 LowLevelHelper（格式：{"file_path": "...", "func_name": "..."}）
    "force_helpers": [],
    # 排除特定 LowLevelHelper（字符串匹配 func_name 或 "file_path::func_name"）
    "exclude_helpers": [],
    # axios 方法名（识别 LowLevelHelper 的锚点）
    "axios_method_names": ["get", "post", "put", "delete", "del", "patch", "request"],
    # helper func name → HTTP method 映射
    "helper_method_map": {
        "get": "GET",
        "post": "POST",
        "put": "PUT",
        "del": "DELETE",
        "delete": "DELETE",
        "patch": "PATCH",
        "request": "GET",
    },
}

# =============================================================================
# Knowledge Retrieval（Phase 15 RETR-05 / ENH-02）
# =============================================================================

KNOWLEDGE_RETRIEVAL_ALPHA: float = env.float("KNOWLEDGE_RETRIEVAL_ALPHA", 0.7)
KNOWLEDGE_RETRIEVAL_BETA: float = env.float("KNOWLEDGE_RETRIEVAL_BETA", 0.3)
KNOWLEDGE_RETRIEVAL_HALF_LIFE_DAYS: int = env.int("KNOWLEDGE_RETRIEVAL_HALF_LIFE_DAYS", 90)
KNOWLEDGE_RETRIEVAL_GRAPH_MAX_HOPS: int = env.int("KNOWLEDGE_RETRIEVAL_GRAPH_MAX_HOPS", 2)
KNOWLEDGE_RETRIEVAL_LLM_RERANK_ENABLED: bool = env.bool(
    "KNOWLEDGE_RETRIEVAL_LLM_RERANK_ENABLED", False
)

# =============================================================================
# Logging — Structlog 配置（implementation contract 凭证泄漏防护）
# =============================================================================
# configure_structlog 必须在 LOGGING dictConfig 之后、任何业务 logger 实例化之前调用。
# settings.py 末尾是最早安全点（pytest-django / gunicorn / daphne 启动时一次性配置完成）。
from common.logging import configure_structlog  # noqa: E402

configure_structlog()
