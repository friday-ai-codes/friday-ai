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

    # Git 平台入站 webhook 共享密钥（MR-02，v0.15.0 Phase 80）：
    # GitHub 用其做 X-Hub-Signature-256 HMAC 校验，GitLab 用其做 X-Gitlab-Token 等值校验。
    # 未配置时入站 MR webhook 端点 fail-closed 拒绝（绝不放行未签名 payload）。
    GIT_WEBHOOK_SECRET = "git_webhook_secret"

    # Cursor 沉淀上报写回质量门槛（CURSOR-03，v0.15.0 Phase 81）：
    # value 为 JSON：{min_length:int, min_distinct_words:int, max_dup_ratio:float}，
    # 用于过滤 Cursor 上报的低信息量/过短/与既有记忆高度重复内容（防噪音污染共享记忆）。
    # 未配置时用 services.cursor_writeback 的合理默认值。
    CURSOR_WRITEBACK_CONFIG = "cursor_writeback_config"

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
    # feature list 逐模块解析槽位上限：粘贴文档解析 fan-out 时每个模块一个 LLM 调用，
    # 槽位池控并发（默认 4，避免同时打爆 AI Provider 触发 429）。
    CONCURRENCY_FEATURE_PARSE_MAX = "concurrency_feature_parse_max"  # 默认 4

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

    # 指标采样与保留（RATE-03，73-03 消费）：与 LOG_RETENTION_* 同款运行时可配。
    # GaugeSample 采样间隔；apscheduler IntervalTrigger 以 settings 启动值为准，
    # sample_gauges 内部按本键 clamp(30..300)；热改间隔需重启 scheduler（量级低可接受）。
    METRIC_SAMPLE_INTERVAL_SECONDS = "metric.sample_interval_seconds"  # int：采样间隔，默认 45。
    METRIC_RETENTION_DAYS = "metric.retention_days"  # int：指标表保留天数，默认 30。
    # int：单表行数上限兜底，默认 2_000_000（指标比日志高频，上限略放宽）。
    METRIC_RETENTION_SIZE = "metric.retention_max_rows"

    # 系统告警引擎运行时配置（ALERT-01/02/03，74-02 评估器 / 74-03 通知 / alert_retention 消费）：
    # 与 LOG_*/METRIC_* 同款运行时可配（SystemSetting + settings_service 60s 缓存 + signals）。
    # 点分命名风格一致；仅常量，无新键迁移。
    ALERT_EVAL_INTERVAL_SECONDS = "alert.eval_interval_seconds"  # int：评估间隔，默认 60（74-02 apscheduler 启动值）。
    ALERT_RETENTION_DAYS = "alert.retention_days"  # int：AlertEvent 保留天数，默认 90（告警低频，保留略长）。
    ALERT_RETENTION_SIZE = "alert.retention_max_rows"  # int：行数上限兜底，默认 500_000。
    ALERT_EMAIL_ENABLED = "alert.email_enabled"  # bool：邮件通道总开关，默认关（74-03 消费）。
    ALERT_EMAIL_RECIPIENTS = "alert.email_recipients"  # 收件人（逗号分隔或 JSON 列表，74-03 解析）。
    ALERT_FEISHU_CHAT_ID = "alert.feishu_chat_id"  # 系统告警飞书目标群 chat_id。
    ALERT_WEBHOOK_URL = "alert.webhook_url"  # 系统告警 webhook 目标 URL。


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
    - scope_id 用 UUIDField(null=True) 而非 FK，避免 Space 级联删除时凭证消失。
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
            "刻意不用 FK，避免 Space 级联删除导致凭证消失。"
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


class RequestMetric(models.Model):
    """请求级指标精简事件行（RATE-01 / SLA-02 / SLA-04）——每请求一行。

    与 ``SystemLogEntry`` 同域同范式（落 system app，复用 settings/清理/查询设施），
    但定位不同：本表是"指标精简行"（QPS/错误三口径/时长/TTFT），供 Phase 73 用
    Postgres ``percentile_cont`` 做精确分位聚合，**零进程内聚合**（第一性原理 §A.2）。

    - 高写入量用 ``BigAutoField`` 自增整数主键（非 UUID）。
    - **绝不**落 raw payload/headers/凭证——仅元数据 + 受控 ``labels``（白名单枚举键，
      禁用户输入原文，避免基数失控 + 泄漏，T-72-01-01/02）。
    - ``user_id`` 取服务端 Phase 71 contextvars（认证后权威值），非客户端 header。
    - 复合索引 ``(ts, source)`` + ``(ts, error_class)`` + ``(-ts)`` 支撑 Phase 73
      SQL 聚合 QPS/错误率/分位时长。

    append-only：只增不改，按需保留清理（复用 log_retention 同款）。
    """

    id = models.BigAutoField(primary_key=True)
    # 事件时间（倒序/聚合）；由 helper 写入 ISO，metric_sink 解析。
    ts = models.DateTimeField(db_index=True, help_text="事件时间（倒序/聚合）。")
    # LogSource 枚举值（rest/mcp/chat_sse/compat_openai/compat_anthropic/webhook_*/ws/rag）。
    source = models.CharField(max_length=32, db_index=True, default="")
    # 归一化路由（URL pattern，禁 query string / path 参数原文）。
    route = models.CharField(max_length=200, blank=True, default="")
    method = models.CharField(max_length=10, blank=True, default="")
    status_code = models.PositiveIntegerField(default=0)
    # 三口径：none/system/business/upstream（由 classify_error 单一收口）。
    error_class = models.CharField(max_length=10, blank=True, default="none")
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    # 流式首 chunk 计时（非流式 null）。
    ttft_ms = models.PositiveIntegerField(null=True, blank=True)
    # 触发用户 id（→ system 哨兵）；存字符串以兼容 system + 数字 id。
    user_id = models.CharField(max_length=64, blank=True, default="system", db_index=True)
    # 受控枚举键（call_source/provider/credential/model/关联键/synthetic），禁用户输入原文。
    labels = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "request_metrics"
        verbose_name = "请求指标"
        verbose_name_plural = "请求指标"
        ordering = ["-ts"]
        indexes = [
            models.Index(fields=["ts", "source"]),
            models.Index(fields=["ts", "error_class"]),
            models.Index(fields=["-ts"]),
        ]

    def __str__(self) -> str:
        return f"{self.source}:{self.route} {self.status_code} ({self.error_class})"


class GaugeSample(models.Model):
    """周期采样的瞬时度量值（RATE-03）——并发 / 队列深 / 积压趋势的时序点。

    与 ``RequestMetric`` 同域同范式（落 system app，复用 settings/清理/查询设施），
    但定位不同：``RequestMetric`` 是"每请求一行"的事件流，本表是 apscheduler
    周期任务（73-03，~45s）采样 ``snapshot_service`` 并发/队列部分写入的"仪表盘读数"，
    供 73-02 按 ``name`` + 时间桶聚合趋势（``GROUP BY date_trunc(step)``）。

    - 高写入量用 ``BigAutoField`` 自增整数主键（非 UUID）。
    - ``name`` / ``labels`` 为**受控枚举常量**（如 ``concurrency.provider_slots`` /
      ``queue.durable_doing`` / ``queue.runner_pending`` / ``backlog.subagent_active``），
      **禁用户输入原文**（避免基数失控 + 泄漏，T-73-01-03）。

    append-only：只增不改，按需保留清理（复用 log_retention 同款）。
    """

    id = models.BigAutoField(primary_key=True)
    # 采样时刻（倒序/聚合）；由 73-03 周期任务写入。
    ts = models.DateTimeField(db_index=True, help_text="采样时刻（倒序/聚合）。")
    # 受控指标名（点分命名，禁用户输入原文）。
    name = models.CharField(max_length=64, db_index=True, default="")
    # 采样值（瞬时读数，如槽位占用数 / 队列深度）。
    value = models.FloatField(default=0.0)
    # 受控枚举键（provider/credential/queue/source 等），禁用户输入原文。
    labels = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "gauge_samples"
        verbose_name = "仪表盘采样"
        verbose_name_plural = "仪表盘采样"
        ordering = ["-ts"]
        indexes = [
            # 支撑 73-02 按 name + 时间桶聚合趋势的两种访问路径。
            models.Index(fields=["ts", "name"]),
            models.Index(fields=["name", "-ts"]),
        ]

    def __str__(self) -> str:
        return f"{self.name}={self.value} @{self.ts:%Y-%m-%d %H:%M:%S}"


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


class SystemAlertRule(models.Model):
    """系统级告警阈值规则（ALERT-01）——**独立于** ``workflows.AlertRule``。

    系统告警语义（CPU>85%、错误率、队列深）与 workflow 强绑模型（project 非空、
    condition 全 execution_*）截然不同，故另起一张表落 ``system`` app（与
    SystemLogEntry/RequestMetric/GaugeSample 同域，复用 settings/清理/查询设施），
    避免拧巴（MILESTONE-PROPOSAL §A.3）。运行时可经 REST CRUD 增删改查（IsSuperUser）。

    - ``metric`` 受控枚举（校验在 serializer 侧 ChoiceField，模型层仅列出受控集合）：
      ``qps`` / ``error_rate`` / ``ttft`` / ``cpu`` / ``memory`` / ``db_connections`` /
      ``redis_clients`` / ``qdrant`` / ``queue_depth``。趋势类 gauge:* 不纳入
      （RATE-03 默认不参与告警）。
    - ``dimension`` 受控维度 jsonb（如 ``{"provider": "anthropic"}`` / ``{"queue": "index"}``，
      空 dict=overall）；**禁用户输入原文当 label**，避免基数失控（serializer 白名单收口）。
    """

    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=64, help_text="规则名（中文/英文）。")
    # 受控枚举（见 docstring）；校验在 serializer ChoiceField，模型层不强约束以便扩展。
    metric = models.CharField(max_length=32, db_index=True, help_text="受控指标枚举。")
    # 比较操作符：gt/gte/lt/lte。
    op = models.CharField(max_length=4, help_text="比较操作符 gt/gte/lt/lte。")
    value = models.FloatField(help_text="阈值。")
    # 评估窗口秒（时序类指标用；快照类指标忽略）。
    window = models.PositiveIntegerField(default=300, help_text="评估窗口秒（快照类忽略）。")
    # 受控维度 jsonb（空 dict=overall）；禁用户原文，serializer 白名单收口。
    dimension = models.JSONField(default=dict, blank=True, help_text="受控维度 jsonb（空=overall）。")
    # 级别 P0/P1/P2。
    severity = models.CharField(max_length=2, help_text="级别 P0/P1/P2。")
    enabled = models.BooleanField(default=True, db_index=True)
    # 通知通道子集（email/feishu/webhook）；空=不通知仅落事件。
    channels = models.JSONField(default=list, blank=True, help_text="通道子集 email/feishu/webhook；空=仅落事件。")
    # 同事件再次通知的冷却秒数（防抖）；0=不额外冷却。
    cooldown = models.PositiveIntegerField(default=600, help_text="再次通知冷却秒数（防抖）；0=不冷却。")
    # 中文标题模板，支持 {metric}/{current}/{value} 占位，由 74-02 渲染；空则默认拼接。
    title_template = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="中文标题模板（{metric}/{current}/{value} 占位）；空则默认拼接。",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "system_alert_rules"
        verbose_name = "系统告警规则"
        verbose_name_plural = "系统告警规则"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["enabled", "metric"]),
        ]

    def __str__(self) -> str:
        return f"{self.name}[{self.severity}] {self.metric} {self.op} {self.value}"


class AlertEvent(models.Model):
    """告警事件（ALERT-02）——P0/P1/P2 + 中文标题 + 机器可读规则信息 + 去重/持续时长/恢复。

    由 74-02 评估器写入（超阈触发 firing，恢复收尾 resolved），74-03 通知分发回写
    ``email_sent`` / ``notified_channels``，Phase 75 告警事件页消费查询 API。

    去重硬约束：同规则同对象（``rule`` + ``target_key``）最多保持一条 ``firing``——由
    ``(rule, target_key)`` status=firing 条件唯一约束在 DB 层兜底（恢复后 status 变
    ``resolved``，约束释放，可再触发新 firing），镜像 ProviderCredential 条件唯一约束范式。

    **绝不**落 raw payload / 凭证：``rule_info`` / ``title_zh`` / ``target`` 仅承载元数据
    （阈值 / 当前值 / 受控维度），写入侧（74-02/03）经脱敏（T-74-01-04）。

    列对齐 REFERENCE-UI §1.4（时间 / 级别 / 状态 / 维度 / 规则ID / 标题+规则信息 /
    持续时长 / 邮件状态）。
    """

    id = models.BigAutoField(primary_key=True)
    # 规则删除不抹历史事件（SET_NULL）。
    rule = models.ForeignKey(
        SystemAlertRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )
    # 冗余规则 severity，便于按级别查询/排序（规则删了仍可见）。
    severity = models.CharField(max_length=2, db_index=True, help_text="级别 P0/P1/P2（冗余）。")
    # 中文标题，由 74-02 按 title_template 渲染。
    title_zh = models.CharField(max_length=200, blank=True, default="")
    # 机器可读 jsonb：{metric,op,threshold,current,window_s,dimension,expr}；
    # expr 为 REFERENCE-UI §1.4 同款字符串
    # `cpu_usage_percent > 85.00 (current 95.40) over last 5m (overall)`。
    rule_info = models.JSONField(default=dict, blank=True, help_text="机器可读规则信息 jsonb。")
    # 对象标识 jsonb（如 {"provider":"anthropic"}；overall 为 {}）。
    target = models.JSONField(default=dict, blank=True, help_text="对象标识 jsonb（overall={}）。")
    # target 的规范化 JSON 串，由 74-02 写入；**仅用于 DB 层去重约束**（见 constraints）。
    target_key = models.CharField(
        max_length=128,
        blank=True,
        default="",
        help_text="target 规范化串，仅用于去重唯一约束。",
    )
    # firing/resolved。
    status = models.CharField(max_length=10, default="firing", db_index=True)
    # 首次触发时刻。
    started_at = models.DateTimeField(db_index=True, help_text="首次触发时刻。")
    # 恢复时刻（firing 时 null）。
    ended_at = models.DateTimeField(null=True, blank=True, help_text="恢复时刻（firing 时 null）。")
    # 恢复时回写 ended-started 秒数。
    duration_s = models.PositiveIntegerField(null=True, blank=True, help_text="持续秒数（恢复时回写）。")
    # 最近一次评估的当前值（74-02 重复评估时更新）。
    current_value = models.FloatField(null=True, blank=True, help_text="最近一次评估当前值。")
    # 最近一次仍超阈的评估时刻。
    last_seen_at = models.DateTimeField(null=True, blank=True, help_text="最近一次仍超阈评估时刻。")
    # pending/sent/skipped/failed（74-03 回写）。
    email_sent = models.CharField(max_length=10, default="pending", help_text="邮件状态（74-03 回写）。")
    # 实际成功通知的通道列表（74-03 回写）。
    notified_channels = models.JSONField(default=list, blank=True, help_text="实际成功通知通道（74-03 回写）。")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "alert_events"
        verbose_name = "告警事件"
        verbose_name_plural = "告警事件"
        ordering = ["-started_at"]
        indexes = [
            # Phase 75 列表两种访问路径 + 按级别查询。
            models.Index(fields=["status", "-started_at"]),
            models.Index(fields=["severity", "-started_at"]),
            models.Index(fields=["-started_at"]),
            models.Index(fields=["rule", "-started_at"]),
        ]
        constraints = [
            # 去重硬约束：同规则同对象最多一条 firing（恢复后约束释放，可再触发新 firing）。
            models.UniqueConstraint(
                fields=["rule", "target_key"],
                condition=models.Q(status="firing"),
                name="uniq_firing_alert_per_rule_target",
            ),
        ]

    def __str__(self) -> str:
        return f"[{self.severity}] {self.title_zh or self.status}@{self.started_at:%Y-%m-%d %H:%M:%S}"
