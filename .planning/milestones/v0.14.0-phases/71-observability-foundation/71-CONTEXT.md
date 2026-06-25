# Phase 71: 可观测性地基（用户上下文贯穿 + 系统日志治理） - Context

**Gathered:** 2026-06-24
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous——grey area 按 MILESTONE-PROPOSAL/STATE.md 关键约束自动采纳最优解）

<domain>
## Phase Boundary

建立可观测性"地基"：①让每次调用都能绑定到触发用户（无则 `system`），②把系统日志从"每进程 800 条内存环形缓冲"升级为"队列化落库、可搜索、可按条件清理、可运行时配置"的日志中心，③统一 webhook 原始留痕与调用下钻 API。

**本 Phase 交付（CTX-01/02, LOG-01~08）：**
- 请求级 `structlog.contextvars` 中间件（注入 `user_id`/`request_id`/`source`/`trace_id`）+ 后台任务用户传播契约
- `SystemLogEntry` 模型 + 队列化批量落库 worker（deque maxlen=5000 + 四计数）
- `InboundWebhookEvent` 模型（webhook 原始 payload 脱敏入库）
- 运行时日志配置（复用 `SystemSetting`+signal，热更新级别/堆栈阈值/采样/保留）
- 日志查询 / 下钻 / 按条件清理 + 保留策略定时清理 API
- 事件目录（`LOGGING-SPEC.md` caller/sampling 分类补全）

**不在本 Phase（后续）：** 指标采集（72）、快照/查询/趋势（73）、告警（74）、运维大盘前端完整页（75，本 Phase 仅后端 API + 可选最小触面）。

</domain>

<decisions>
## Implementation Decisions

### 用户上下文贯穿（CTX-01/02）
- **机制**：`structlog.contextvars`（已在 `configure_structlog` processor 链首位 `merge_contextvars`，无需改链路）。新增请求级中间件在入口 `bind_contextvars(user_id, request_id, source, trace_id)`，请求结束 `clear_contextvars`。
- **DRF user 时序坑**：Django MIDDLEWARE 在 DRF 认证之前拿不到 JWT user → 采用「ASGI/Django 中间件外层兜底（request_id/source/trace_id + user_id=system 占位）+ DRF 基类/mixin 在 dispatch 拿到 `request.user` 后补绑 user_id」组合。提供可复用的 DRF 基类 mixin，现有 adrf 异步视图最小侵入接入。
- **source 取值受控枚举**：`rest` / `mcp` / `chat_sse` / `compat_openai` / `compat_anthropic` / `ws` / `webhook_feishu` / `webhook_workflow` / `webhook_git` / `container_callback` / `durable` / `background` / `workflow` / `scheduler` / `system`（与 LOGGING-SPEC 对齐）。
- **后台任务传播**：跨线程/`_run_in_thread`/durable worker/`background_runner`/apscheduler/飞书·webhook **不自动传播 contextvars**（用干净 `contextvars.Context()`），必须**显式** bind。约定：入队时序列化 `initiated_by_user_id`（durable job kwargs / background_runner 参数 / workflow execution metadata），worker 入口 `bind_contextvars(user_id=initiated_by_user_id or "system", source=..., ...)`。沿用 `access_tokens/context.py` 的 ContextVar 范式（set/get/reset，请求结束 reset）。
- **PAT 明文不受影响**：本 Phase 只加 user_id 等非敏感字段；明文凭证绝不进 contextvars/日志。

### 日志落库与队列（LOG-01/02/03）
- **模型 `SystemLogEntry`**（新 app 还是复用 `system` app？→ 落 `system` app，与 settings_service/observability_views 同域）。字段：`ts(index, 倒序)`, `level(debug/info/warn/error)`, `component`, `category(caller/sampling)`, `event`, `message`, `user_id(→system, index)`, `source`, `trace_id`, `request_id`, `payload(jsonb, 已脱敏)`, `correlation(run_id/conversation_id 等关联键)`。建复合索引支持「时间倒序 + 组件/级别/用户/来源」筛选；全文搜索用 PG `message` ILIKE + 关键词（量级低不引专用全文索引，SQLite dev 用 icontains 降级）。
- **队列**：模块级 `deque(maxlen=5000)` + 后台批量 worker（专用线程，定时/批量阈值触发 `bulk_create`）。满则丢弃 `log_dropped_total++`，落库失败 `log_write_failed_total++`，`log_enqueued_total`/队列当前深度四计数 best-effort 暴露。**绝不反噬业务**（沿用 `append_log`/`buffer_log` 的 `except: pass`）。
- **保留 `common/log_buffer.py`（800 条内存）作极速兜底**，新落库链路与之并存（buffer_log processor 之后再加一个 enqueue 到落库队列的 processor，或在 buffer_log 内 fan-out）。
- **写入挂载点**：新增 structlog processor `enqueue_system_log`（在 `redact_credentials` 之后，保证落库内容已脱敏）+ 扩展 `RingBufferHandler` 同步 enqueue（stdlib 日志也落库，经 `redact_secrets_in_text`）。

### 调用下钻（LOG-04）
- 复用现有 **Interaction Ledger**（`InteractionRun`/`InteractionEvent`/`ToolCallRecord`/`RetrievalTrace`）+ `Conversation`/`Message`，不新建。提供下钻 API：MCP 调用按 `request_id`/`run_id` 取触发用户；AI 对话按 `conversation_id` 取该会话全部请求与原始数据。三者经 `request_id/run_id/conversation_id` 关联，不复制数据。

### 事件分类与目录（LOG-05）
- 每条日志带 `category`(caller/sampling) + `component`。`caller`=用户可归因的一次调用（MCP/AI 对话/REST 写/compat/webhook/workflow 触发/登录）全量记录；`sampling`=高频内部步骤（单次 LLM turn/qdrant 查询/embedding/节点内步骤）按采样配置记录。补全 `LOGGING-SPEC.md` 事件目录（本 Phase 已知事件，72+ 增量补）。
- 提供 helper：`get_logger` 包装或约定，让业务事件能带 category/component（默认从 logger name 推 component，category 显式传或默认 sampling）。**不强制重写全仓事件**——地基就绪 + 关键生命周期补齐，存量渐进迁移。

### 运行时配置（LOG-06）
- 复用 `SystemSetting` + `settings_service`(60s 缓存) + `signals`(写时失效)。新增 `SettingKeys.LOG_*`：全局级别、分组件级别(jsonb map)、堆栈记录阈值、采样初始(首 N 全记)、采样后续(比例)、保留天数、保留大小。
- 把固定的 `_resolve_structlog_level()` 改为**可热更新**：structlog 用动态 `wrapper_class` 或在 processor 内读运行时级别 + `logging.setLevel()` 即时生效，无需重启。signal 写时调整 filtering level。

### Webhook 原始留痕（LOG-07）
- 新模型 `InboundWebhookEvent`（落 `system` app）：`received_at`, `kind(feishu/workflow/git_push/container_callback)`, `source_ip`, `headers(jsonb,脱敏)`, `raw_body(脱敏)`, `user_id`, `verified`, `correlation`。飞书已有 `TriggerLog` → 纳入统一视图（双写或视图聚合，优先新表统一 + 飞书入口补写 InboundWebhookEvent）。各 webhook 入口（飞书/通用 workflow/Git push/容器回调）入库前经 `redact_for_ledger`/`redact_secrets_in_text`。

### 日志清理（LOG-08）
- API 按条件（时间/级别/组件/用户/关键词）批量删除 `SystemLogEntry`。保留策略到期定时自动清理：apscheduler 周期任务按 `LOG_RETENTION_DAYS`/`LOG_RETENTION_SIZE` 删旧。InboundWebhookEvent 同款保留清理。

### 脱敏不可破（贯穿 + LOG-08 验收）
- 所有落库/留痕/webhook 原始入库前必经 `redact_credentials`/`redact_secrets_in_text`/`redact_for_ledger`。CI 守护 `server/tests/test_credential_leak_protection.py` 不能破，新增落库链路补对称守护测试。

### Claude's Discretion
- `SystemLogEntry`/`InboundWebhookEvent` migration 编号由 makemigrations 自动生成；具体索引组合、批量 worker 触发阈值（条数/间隔）、API 路由命名（`/api/system/logs/`、`/api/system/webhooks/`、`/api/system/logs/clear/` 等）在 plan 阶段定，遵循现有 `server/system/` idiom（adrf APIView + IsSuperUser）。
- 是否在现有运维页加最小日志查看触面：UI hint=maybe → 后端 API 优先，完整页留 Phase 75；若低成本可加最小列表。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/common/logging.py`：`configure_structlog`（processor 链）、`redact_credentials`/`redact_secrets_in_text`/`_redact_value`、`buffer_log`、`RingBufferHandler`、`_resolve_structlog_level`、`sentry_before_send`。
- `server/common/log_buffer.py`：`append_log`/`snapshot`/`clear`（800 条内存环形缓冲，best-effort，线程安全）。
- `server/access_tokens/context.py`：请求级 ContextVar set/get/reset 范式（PAT 明文），可镜像用于 user 上下文后台传播。
- `server/system/`：`settings_service`(60s 缓存)、`signals`(写时失效)、`models` 的 `SystemSetting`/`SettingKeys`、`observability_views.py`、`dashboard_views.py`。
- `server/interactions/`：Interaction Ledger（`InteractionRun`/`InteractionEvent`/`ToolCallRecord`/`RetrievalTrace`）+ `redact_for_ledger`。
- `server/feishu/`：`TriggerLog`（飞书 webhook 原始范本）。
- `server/friday/settings.py`：`MIDDLEWARE` / DRF 配置 / `DATABASES` / `CACHES` / apscheduler。

### Established Patterns
- structlog 结构化事件 snake_case + kv（started/completed/failed + duration_ms）。
- async ORM 走 `sync_to_async`；adrf 异步 DRF 视图；IsSuperUser 保护运维端点。
- best-effort 观测代码 `except: pass` 绝不反噬业务。
- 运行时配置走 `SystemSetting`+`settings_service`+`signals`。
- apscheduler（django-apscheduler）跑周期任务（repo sync polling 已用）。

### Integration Points
- 入口中间件挂 `MIDDLEWARE`（ASGI/Django 外层）+ DRF 基类 mixin（dispatch 补 user）。
- structlog processor 链插入 `enqueue_system_log`（redact 之后）。
- webhook 入口：`server/feishu/views.py`、workflow webhook、Git push webhook、`server/subagent/`/runner 容器回调。
- API 落 `server/system/`（新 views + urls）。
- 后台任务入队点：durable job、`background_runner`、workflow `_run_in_thread`、apscheduler。

</code_context>

<specifics>
## Specific Ideas

- 严格遵守 `.cursor/rules/observability-logging.mdc`（强制规则）与 `LOGGING-SPEC.md`。
- 第一性原理：量级低、人触发——最小自研基础设施，复用已有表与设施。
- 队列四计数（队列 x/5000 · 写入 · 丢弃 · 失败）必须可被快照采集（Phase 73 消费）。
- 后台任务"谁触发的"可回答是 CTX-02 验收硬指标。

</specifics>

<deferred>
## Deferred Ideas

- 指标采集（RequestMetric/ModelUsageRecord 扩展）→ Phase 72。
- 快照/时序查询/趋势 → Phase 73。
- 告警 → Phase 74。
- 运维大盘完整前端（日志页/告警页/配置面板 UI）→ Phase 75（本 Phase 仅后端 API + 可选最小触面）。

</deferred>
