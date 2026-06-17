# Phase 54: 敏感操作全量覆盖 emit - Context

**Gathered:** 2026-06-17
**Status:** Ready for planning

<domain>
## Phase Boundary

把 Phase 53 立起的 `AuditService.emit/aemit` 单一写入入口接线到既有各敏感/管理操作，产出全量审计记录，并把 v0.5 既有分散埋点（`purge.started`/`purge.completed` 等）收口到统一 `AuditEvent` 表。

**交付:** 身份与权限类（成员/用户增删改、启停、角色/权限、空间配置、仓库权限）+ 凭证与数据治理类（Provider/Git 实例/飞书凭证增删改、Agent API key/PAT、飞书同步、排除规则变更、清理任务）敏感操作经统一入口 emit 审计；凭证字段脱敏；读操作/普通业务不产生审计噪音。

**不交付（顺延 Phase 55 / Out of Scope）:** 审计查询 REST API、前端审计视图、导出（Phase 55）；新建独立审计角色、密码学级防篡改、实时告警/SIEM/webhook 外发、审计保留/归档策略、读操作全量审计（v2 AUDITX-* / Out of Scope）。

**Requirements:** AUDITCOV-01, AUDITCOV-02
</domain>

<decisions>
## Implementation Decisions

### 覆盖范围与 action 词表
- 覆盖范围严格对齐 ROADMAP SC-1/SC-2 + `taxonomy.py` 既有种子常量：member.created/updated/deleted、user.activated/deactivated、role.changed、project.config_changed、repository.permission_changed、credential.created/updated/deleted、pat.created/revoked、feishu_sync.triggered、exclusion_rule.changed；v0.5 purge 收口用 `RESERVED_ACTIONS`（purge.started/completed）。
- 仅敏感/管理（写）操作 emit；读操作、普通业务操作（检索、索引、对话等）一律不 emit，避免审计噪音（SC-4）。
- action 一律引用 `taxonomy.py` 的 `Final[str]` 常量，禁止字符串字面量散落（消除漂移，对齐 INV-2 命名守护）。若发现 SC 覆盖点缺常量，先在 `taxonomy.py` 补常量并纳入 `ALL_ACTIONS`，再接线。

### emit 接线位置与 actor 传递
- emit 收口在**领域 service 层**（操作真正落库处），actor 由调用方（API view 的 `request.user`）显式下传到 service —— 不在 service 内部反查 actor。view 层无 service 的简单 CRUD 可在 view 内 service 调用成功后 emit。
- 一律 `transaction.on_commit(lambda: AuditService.emit(...))`：审计只记真正提交的事实，且彻底脱离主事务生命周期（Phase 53 入口 savepoint 兜底是纵深防御，不替代 on_commit 约定）。autocommit 路径直接 emit。
- async（adrf/channels）路径用 `aemit`；sync 路径用 `emit`。actor 字段访问交由 service 内部（已在 sync 块内，async 安全）。
- `source` 字段标注触发面（如 `api` / `feishu_webhook` / `scheduler` / `cli`），供 Phase 55 过滤区分。

### before/after 粒度与脱敏
- before/after 记录**变更字段的前后值快照**（非整对象 dump）：create 只填 after、delete 只填 before、update 填变更字段 diff。粒度以"可追溯谁改了什么"为准，不堆无关字段。
- 凭证/密钥/token/PAT 等字段绝不落明文——依赖 Phase 53 入口强制 `_redact_audit_payload` 兜底，但接线侧也应优先只传必要的非敏感标识（如 provider 名/类型/id），双重保险（对齐 PAT-02 / 凭证加密约束）。
- target_type 用稳定的领域类型名（如 `provider_credential` / `member` / `repository` / `pat`），target_id 用主键标量，target_repr 填人类可读快照（如 provider 名、用户名）。

### v0.5 既有埋点收口
- `purge.started`/`purge.completed`（`services/purge_reconcile.py` / `services/purge.py` 既有结构化日志）收口到统一 `AuditEvent`：保留原有结构化日志的同时，增设经 `AuditService` 的 emit（用 `RESERVED_ACTIONS` 常量），不破坏既有清理流程语义、fail-soft 不阻断清理。
- 收口以"补 emit"为主，不重写既有 purge 业务逻辑；若既有 `TriggerLog`/`ActionLog` 与本里程碑 SC 覆盖点重叠则一并 emit，无重叠则不动（避免 scope creep）。

### the agent's Discretion
- 具体每个 service 的 emit 落点行号、before/after 字段精确选取、target_repr 文案、是否抽取薄 helper 减少重复样板，均由 planner/executor 依既有代码形状定夺。
- 接线顺序（身份权限类 vs 凭证治理类先后）由 planner 按依赖与改动面切分 plan。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `audit/services/audit_service.py` — `AuditService.emit/aemit` 单一写入入口（强制脱敏 + fail-soft + savepoint 兜底），Phase 54 直接调用。
- `audit/services/taxonomy.py` — 15 个 `ACTION_*` 种子常量 + `ALL_ACTIONS` + `RESERVED_ACTIONS`（purge.started/completed），覆盖 Phase 54 全部 SC 词表。
- `audit/services/redaction.py` — `_redact_audit_payload`（入口已强制调用，接线侧无需重复脱敏）。
- `delivery/services/event_taxonomy.py` — taxonomy 常量范式来源（对齐命名/RESERVED 模式）。

### Established Patterns
- 服务层单一写入入口（INV-6）：写操作收口到专用 service，禁旁路写表（既有 `WorkItemService` / `TechnicalPlanService` / `DocumentService` 范式）。
- 既有敏感操作 service 散落多 app：`services/provider_config.py`（ProviderConfigService）、`services/git_credentials.py`、`services/feishu*.py` / `feishu/bot/service.py`、`services/exclusion.py`、`services/purge*.py` / `services/purge_reconcile.py`。
- 结构化日志 `logger.info("event.name", key=val)`（structlog）—— purge 既有埋点即此形态，收口为"日志 + audit emit"并存。
- async ORM 经 `sync_to_async`；adrf 异步 view 用 `aemit`。

### Integration Points
- API view 层 `request.user` 是 actor 来源，需下传到 service emit 调用。
- 各敏感操作 service 的成功落库点（create/update/delete / 状态切换 / sync 触发）是 emit 接线点。
- `transaction.on_commit` 钩子接入主操作事务，确保只记已提交事实。
</code_context>

<specifics>
## Specific Ideas

- 接线评审须把 `transaction.on_commit` 列为硬性检查项（Phase 53 audit_service docstring 已明确约定）。
- INV-6 grep 守护（Phase 53 已建）在本 phase 继续生效——所有 emit 仍只经 `AuditService`，新增接线不得旁路写 `AuditEvent`。
</specifics>

<deferred>
## Deferred Ideas

- 审计查询 REST API / 前端视图 / 导出 → Phase 55。
- 密码学级防篡改（hash chain/WORM）、实时告警/SIEM、保留归档策略、读操作全量审计 → v2 AUDITX-* / Out of Scope。
</deferred>
