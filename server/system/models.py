"""Settings models: SystemSetting, CacheVolumeTracker, ProviderCredential,
SystemLogEntry, InboundWebhookEvent。"""

from __future__ import annotations

import json
import uuid

from django.db import models
from django.utils import timezone


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

    def __str__(self) -> str:
        return self.key


class SettingKeys:
    """Predefined setting keys.

    implementation（contract/contract）：以下 v8.1 legacy 常量已硬删：
        - ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL / ANTHROPIC_MODEL / ANTHROPIC_SMALL_MODEL
        - DEFAULT_PROVIDER_TYPE
    已由 ProviderCredential 表 + ProviderConfigService 承载。
    """

    GIT_HTTP_PROXY = "git_http_proxy"

    # 站点配置：当前站点的外部访问地址（如 https://friday.example.com），
    # 用于生成 OIDC 回调 URL、登录跳转等用户可见链接；空则回退 env
    # FRIDAY_BASE_URL / FRIDAY_FRONTEND_URL（设置页「站点 Host」写入）。
    SITE_HOST = "site_host"

    # Claude Code 编码容器配置（Claude Code 编码容器配置）
    # value 为 JSON：{credential_id: str, model_mapping: {opus, sonnet, haiku}}
    CLAUDE_CODE_CONFIG = "claude_code_config"

    # Vector Index Settings
    QDRANT_URL = "qdrant_url"
    QDRANT_API_KEY = "qdrant_api_key"
    EMBEDDING_API_URL = "embedding_api_url"
    EMBEDDING_API_KEY = "embedding_api_key"
    EMBEDDING_MODEL = "embedding_model"
    EMBEDDING_DIMENSION = "embedding_dimension"

    # Chat Auth Settings
    CHAT_AUTH_ENABLED = "chat_auth_enabled"
    CHAT_KEY = "chat_key"

    # Feishu IM Settings
    FEISHU_APP_ID = "feishu_app_id"
    FEISHU_APP_SECRET = "feishu_app_secret"

    # Budget Control
    MAX_BUDGET_USD = "max_budget_usd"

    # Web Push
    WEB_PUSH_VAPID_PUBLIC_KEY = "web_push_vapid_public_key"
    WEB_PUSH_VAPID_PRIVATE_KEY = "web_push_vapid_private_key"
    WEB_PUSH_VAPID_SUBJECT = "web_push_vapid_subject"

    # Knowledge（delivery_knowledge collection）元信息：
    # value 为 JSON：{model: str, dimension: int, schema_version: int}，
    # 由 knowledge.collection.ensure_delivery_knowledge_collection 写入/校验。
    KNOWLEDGE_COLLECTION_META = "knowledge_collection_meta"

    # 代码索引排除规则全局默认（Phase 22 fail-closed，EXCL-01 单一事实源）。
    # value 为 JSON 规则列表，结构 = ExclusionRuleSpec 序列化形
    # （[{"pattern": str, "rule_type": "dir|glob|regex", "enabled": bool, "source": str}, ...]）。
    # 与内置 BUILTIN_GLOBAL_DEFAULTS 取并集，由 services/exclusion.py 加载合并。
    CODE_INDEX_EXCLUSION_GLOBAL_DEFAULTS = "code_index.exclusion.global_defaults"

    # RAG Enhancement Settings
    RERANKER_ENABLED = "reranker_enabled"
    RERANKER_API_URL = "reranker_api_url"
    RERANKER_API_KEY = "reranker_api_key"
    RERANKER_MODEL = "reranker_model"
    RERANKER_TOP_N = "reranker_top_n"
    # Reranker provider 请求/响应格式适配。当前支持 "openai_compatible"
    # （兼容 qwen3-rerank / SiliconFlow / Jina / Cohere 的 {model,query,documents,top_n} 体）。
    RERANKER_PROVIDER = "reranker_provider"
    # 模型重排前的候选 over-fetch 数量（召回多少条交给 reranker 精排）。
    RERANK_FETCH_K = "rerank_fetch_k"
    # 无 rerank 模型时的 model-free 启发式重排开关（业务降级，默认开启）。
    HEURISTIC_RERANK_ENABLED = "heuristic_rerank_enabled"
    HYBRID_SEARCH_ENABLED = "hybrid_search_enabled"
    HYBRID_SEARCH_ALPHA = "hybrid_search_alpha"

    # 并发治理（）：按资源分治的可配置并发上限。
    # 索引/图谱用 Procrastinate 原生 lock 槽位池排队 —— defer 带
    # lock=index-slot-{stable_hash(repo_id)%N}，N 从下列设置实时读取，
    # 超限 job 原生留 todo 排队、worker 自动跳过、零空转；同仓恒定同槽天然串行。
    # 不设全局总上限（容器走 runner.concurrent、LLM 走 ProviderCredential.max_concurrency）。
    CONCURRENCY_INDEX_MAX = "concurrency_index_max"  # 默认 5
    CONCURRENCY_GRAPH_MAX = "concurrency_graph_max"  # 默认 3
    # repo_summary 派发槽位上限：durable job 只做轻量派发，槽位用于平滑批量建仓时的
    # session 创建与 Runner 投递洪峰（默认 8，与 Runner.concurrent 量级对齐）。
    CONCURRENCY_SUMMARY_MAX = "concurrency_summary_max"  # 默认 8

    # 运行时日志配置（LOG-06，实时生效）：复用 SystemSetting + settings_service(60s 缓存)
    # + signals(写时失效 + 即时调级别)。点分命名与 code_index.exclusion.* 风格一致。
    # 写入即经 signal 失效缓存 + 重设过滤级别，无需重启。
    LOG_LEVEL = "log.level"  # 全局级别 DEBUG/INFO/WARNING/ERROR（空回退 env→INFO）。
    LOG_COMPONENT_LEVELS = "log.component_levels"  # JSON map {component: level}，分组件覆盖全局。
    LOG_STACK_THRESHOLD = "log.stack_threshold"  # 记录堆栈的最低级别（如 ERROR）。
    LOG_SAMPLING_INITIAL = "log.sampling_initial"  # int：首 N 条全记，默认 50。
    LOG_SAMPLING_RATE = "log.sampling_rate"  # float 0..1：之后按比例记录，默认 0.1。
    LOG_RETENTION_DAYS = "log.retention_days"  # int：保留天数，默认 30（清理在 71-04 消费）。
    LOG_RETENTION_SIZE = "log.retention_max_rows"  # int：行数上限兜底，默认 1_000_000（71-04 消费）。


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


class ProviderCredential(models.Model):
    """多 Provider 凭证（v21.0 引入）。系统级 + 项目级双作用域。

    设计要点：
    - encrypted_config 字段存 Fernet 整体加密的 JSON 字符串（由 service 层显式
      encrypt_value(json.dumps(...))），不在 save() override 里自动加密，
      避免 ORM 查询副作用与 update_fields 漏加密。
    - scope_id 用 UUIDField(null=True) 而非 FK，避免 Project 级联删除时凭证消失。
    - last_health_check_* / available_models 字段一次性预留 implementation/229 所需，
      schema 一次到位，避免未来再加 AddField 迁移。
    """

    class Scope(models.TextChoices):
        SYSTEM = "system", "系统级"
        PROJECT = "project", "项目级"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    provider_type = models.CharField(
        max_length=32,
        db_index=True,
        help_text=("Provider 类型字符串。本 phase 仅 'anthropic'，implementation 扩展为 5 种。"),
    )
    name = models.CharField(
        max_length=64,
        default="default",
        help_text=("同 Provider 多凭证区分键（contract）。例 'openai-prod' / 'openai-dev'。"),
    )

    scope = models.CharField(max_length=16, choices=Scope.choices, default=Scope.SYSTEM)
    scope_id = models.UUIDField(
        null=True,
        blank=True,
        help_text=(
            "scope=PROJECT 时为 project.id；scope=SYSTEM 时为 NULL。"
            "刻意不用 FK，避免 Project 级联删除导致凭证消失。"
        ),
    )

    encrypted_config = models.TextField(
        help_text=("encrypt_value(json.dumps({...})) Fernet 整体加密；service 层显式加解密。"),
    )

    base_url = models.CharField(max_length=500, blank=True, default="")
    default_model = models.CharField(max_length=128, blank=True, default="")
    is_active = models.BooleanField(default=True)

    # 并发治理（CONC-02）：该凭证的 LLM 并发上限。
    # 各家 provider 限制不同，故挂在每个凭证上（不共用一个全局数）。
    # chat/深度分析/编码的 LLM 调用按凭证 id 限流（Redis 租约信号量 + 进程内 fallback），
    # 超过该上限时排队等待、超时返回友好「系统繁忙」，不打到 provider 触发 429。
    # 0 = 不限（默认 50，开箱即用）。
    max_concurrency = models.PositiveIntegerField(
        default=50,
        help_text=("该凭证的 LLM 并发上限（CONC-02）。0=不限，默认 50。"),
    )

    is_default = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            "该 (scope, scope_id, provider_type) 维度的系统/项目默认凭证。"
            "替代 name='default' 魔法约定。"
        ),
    )

    # implementation (contract) 健康检查预留字段
    last_health_check_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="implementation (contract) 写入；本 phase 仅预留字段。",
    )
    last_health_check_status = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="ok/error/untested。implementation (contract) 写入；本 phase 仅预留字段。",
    )
    last_health_check_error = models.TextField(blank=True, default="")

    # implementation/229 (contract/contract) 模型清单缓存预留字段
    available_models = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "模型清单缓存。implementation/229 (contract/contract) 写入；本 phase 仅预留字段。"
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "provider_credentials"
        verbose_name = "Provider 凭证"
        verbose_name_plural = "Provider 凭证"
        constraints = [
            # 系统级：每 (provider_type, name) 唯一
            models.UniqueConstraint(
                fields=["provider_type", "name"],
                condition=models.Q(scope="system"),
                name="uniq_system_provider_credential",
            ),
            # 项目级：每 (scope_id, provider_type, name) 唯一
            models.UniqueConstraint(
                fields=["scope_id", "provider_type", "name"],
                condition=models.Q(scope="project"),
                name="uniq_project_provider_credential",
            ),
            # 默认凭证唯一性 DB 兜底：同 (scope, scope_id, provider_type) 维度
            # 最多一个 is_default=True（唯一性主动保证放在 service 层 set_default）。
            models.UniqueConstraint(
                fields=["scope", "scope_id", "provider_type"],
                condition=models.Q(is_default=True),
                name="uniq_default_provider_per_scope_type",
            ),
        ]
        indexes = [
            models.Index(fields=["scope", "scope_id", "provider_type"]),
            models.Index(fields=["is_active", "provider_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.provider_type}/{self.scope}/{self.name}"

    def get_decrypted_config(self) -> dict:
        """Service 层 helper：解密 + JSON parse 一步到位。

        只读 helper；不在模型层做 set_config，避免 ORM 副作用（CONTEXT 决策 1）。
        """
        from common.encryption import decrypt_value

        plain = decrypt_value(self.encrypted_config)
        return json.loads(plain) if plain else {}


class SystemLogEntry(models.Model):
    """系统日志落库条目（LOG-01）——队列化批量写入的目标表。

    把"每进程 800 条内存环形缓冲"升级为"可搜索、可清理、可配置"的日志中心存储载体：
    - 高写入量用 ``BigAutoField`` 自增整数主键（非 UUID）。
    - 落库内容**必经脱敏**（structlog ``redact_credentials`` / stdlib
      ``redact_secrets_in_text``）后才入队，本表绝不含明文凭证（脱敏契约）。
    - 复合索引支撑"时间倒序 + 组件/级别/用户/来源"筛选（71-04 查询消费）；
      全文搜索用 ``message`` ILIKE/icontains（量级低，不引专用全文索引）。

    append-only：只增不改，按需保留清理（71-04 LOG-08）。
    """

    id = models.BigAutoField(primary_key=True)
    # 事件时间（倒序查看）；由 structlog timestamp 解析，缺失用 timezone.now()。
    ts = models.DateTimeField(db_index=True, help_text="事件时间（倒序查看）。")
    # debug/info/warn/error（小写归一；WARNING→warn）。
    level = models.CharField(max_length=10, blank=True, default="info")
    # 组件（见 LOGGING-SPEC §5 组件清单）。
    component = models.CharField(max_length=40, blank=True, default="")
    # caller（调用类）/ sampling（采样类）。
    category = models.CharField(max_length=10, blank=True, default="")
    # snake_case 事件名。
    event = models.CharField(max_length=128, blank=True, default="")
    # 全文搜索目标。
    message = models.TextField(blank=True, default="")
    # 触发用户 id（→ system 哨兵）；存字符串以兼容 system + 数字 id。
    user_id = models.CharField(max_length=64, blank=True, default="system", db_index=True)
    # LogSource 枚举值。
    source = models.CharField(max_length=32, blank=True, default="", db_index=True)
    trace_id = models.CharField(max_length=64, blank=True, default="")
    request_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    # 已脱敏的完整 event_dict 剩余字段。
    payload = models.JSONField(default=dict, blank=True)
    # run_id/conversation_id/execution_id 等关联键（供 71-05 下钻与三链关联，不复制数据）。
    correlation = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "system_log_entries"
        verbose_name = "系统日志条目"
        verbose_name_plural = "系统日志条目"
        ordering = ["-ts"]
        indexes = [
            models.Index(fields=["-ts"]),
            models.Index(fields=["component", "-ts"]),
            models.Index(fields=["level", "-ts"]),
            models.Index(fields=["user_id", "-ts"]),
            models.Index(fields=["source", "-ts"]),
        ]

    def __str__(self) -> str:
        return f"[{self.level}] {self.component}:{self.event}"


class InboundWebhookEvent(models.Model):
    """入站 webhook 原始留痕载体（LOG-07）。

    本 plan 仅建表（避免 71-05 与本 plan 抢 models.py/migration）；**写入逻辑在 71-05**：
    各 webhook 入口（飞书 / 通用 workflow / Git push / 容器回调）入库前必经
    ``redact_for_ledger`` / ``redact_secrets_in_text`` 脱敏，``raw_body`` 过大截断
    由写入方控制。
    """

    id = models.BigAutoField(primary_key=True)
    received_at = models.DateTimeField(default=timezone.now, db_index=True)
    # feishu/workflow/git_push/container_callback。
    kind = models.CharField(max_length=32, db_index=True)
    source_ip = models.CharField(max_length=64, blank=True, default="")
    # 脱敏后的请求头。
    headers = models.JSONField(default=dict, blank=True)
    # 脱敏后的原始 body（过大截断由 71-05 写入方控制）。
    raw_body = models.TextField(blank=True, default="")
    user_id = models.CharField(max_length=64, blank=True, default="system", db_index=True)
    verified = models.BooleanField(default=False)
    # trigger_log_id / event_uuid / execution_id 关联。
    correlation = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inbound_webhook_events"
        verbose_name = "入站 Webhook 事件"
        verbose_name_plural = "入站 Webhook 事件"
        ordering = ["-received_at"]
        indexes = [
            models.Index(fields=["kind", "-received_at"]),
            models.Index(fields=["-received_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.kind}@{self.received_at:%Y-%m-%d %H:%M:%S}"
