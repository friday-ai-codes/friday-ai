# Phase 1: AuditEvent 模型 + emit 机制 - Context

**Gathered:** 2026-06-15
**Status:** Ready for planning
**Mode:** Smart discuss — all recommended answers accepted (user directive: "采用最优解")

<domain>
## Phase Boundary

统一审计事件模型 + emit 基础设施：新建 `audit` Django app，定义 `AuditEvent` 模型（actor/action/target/before-after/timestamp/source），提供 `emit_audit_event()` 同步+异步双入口，自动从请求上下文提取 actor（JWT/PAT/系统），append-only 保护（无 DELETE/PATCH API）。

</domain>

<decisions>
## Implementation Decisions

### 模型设计与存放位置
- 新建 `server/audit/` 独立 app — 职责清晰，不污染 interactions
- `before` / `after` 各用一个 `JSONField(default=dict)` — 与 InteractionRun payload 模式一致
- target 用软关联：`target_type: CharField`（模型名）+ `target_id: CharField`（主键字符串），不建 FK，避免 CASCADE 复杂度
- actor 用 FK 到 User（nullable, SET_NULL）+ `actor_display: CharField` 冗余存用户名

### Actor 提取策略
- 请求级中间件提取 actor：JWT → request.user；PAT → AccessToken.owner；匿名/系统 → system actor
- `emit_audit_event()` 接受可选 `actor` override，中间件提取结果通过 contextvars 传递
- 系统/定时任务操作以特殊 `actor_type="system"` 标识，`actor` FK 为 NULL

### Emit API 设计
- 单一入口 `emit_audit_event(action, target_type, target_id, before, after, **kwargs)` — 同步 + async 双版本（`sync_to_async` bridge）
- 使用 `structlog.get_logger("audit")` 输出审计日志（复用现有 redact_credentials 处理器）
- emit 失败不抛异常（best-effort，log warning）— 审计不阻断业务

### Append-only 保护
- Model 层：不暴露 `delete()` / `update()` 方法（不加 admin 注册、不加 PATCH/DELETE API）
- API 层：仅提供 LIST + DETAIL GET（Phase 3 查询 UI 用），无 mutation 端点
- DB 层：可选 `db_constraints` 提示，但主要靠应用层守护

### Claude's Discretion
- Model 字段命名、index 策略、migration 细节由实现者决定
- structlog event name 命名规范（如 `audit.event_created`）由实现者按现有惯例决定

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/interactions/models.py` — InteractionRun 模型模式（UUID PK, TextChoices, JSONField, auto_now_add, append-only）
- `server/interactions/ledger.py` — 集中写入 helper 模式（sync/async 双入口，best-effort sub-events）
- `server/interactions/redaction.py` — redact_for_ledger 脱敏模式
- `server/common/logging.py` — structlog 配置 + redact_credentials 处理器
- `server/core/authentication.py` — JWT + PAT 认证链，actor 提取来源
- `server/system/signals.py` — AppConfig.ready() 信号注册模式

### Established Patterns
- UUID PK: `models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)`
- 枚举: `models.TextChoices` 内部类
- 时间戳: `auto_now_add=True` 作 created_at
- db_table: 显式声明 + Chinese verbose_name
- 软关联: `related_name="+"` + `on_delete=SET_NULL`

### Integration Points
- `server/friday/settings.py` INSTALLED_APPS — 注册新 audit app
- `server/friday/urls.py` — 注册审计 API 路由（Phase 3 用）
- `server/core/authentication.py` — 中间件级 actor 提取
- 各业务模块 — Phase 2 接入 emit_audit_event() 的调用点

</code_context>

<specifics>
## Specific Ideas

- 用户要求"优雅、好用"，采用所有推荐最优解
- 遵循 interactions/ledger.py 的集中写入模式 — 不散落 create() 调用
- structlog 命名遵循现有 `server_event_name` 惯例（小写+下划线）

</specifics>

<deferred>
## Deferred Ideas

- 审计日志自动过期/归档 — 后续里程碑
- WebSocket 实时推送审计事件 — 后续按需
- 审计事件 webhook 回调 — v0.11 范畴

</deferred>
