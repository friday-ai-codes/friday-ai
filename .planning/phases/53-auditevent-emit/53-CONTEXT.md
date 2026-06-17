# Phase 53: `AuditEvent` 模型 + emit 地基 - Context

**Gathered:** 2026-06-17
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous) — 基础设施 phase，grey area 由 agent 裁量；关键约束已由里程碑级决策锁定

<domain>
## Phase Boundary

立起统一、不可篡改的 `AuditEvent` 横切审计模型与 fail-soft emit 地基，供本里程碑后续所有敏感操作（Phase 54）与查询/导出（Phase 55）复用。

**本 phase 交付（what must be TRUE）：**
1. `AuditEvent` 表落库：`actor` / `action` / `target_type` / `target_id` / `target_repr` / `before` / `after` / `source` / `occurred_at` / `metadata`，写入经**单一 service 入口**（INV-6 精神）。
2. append-only 不可篡改——无 update/delete 业务路径，模型层 + grep 守护无旁路写表。
3. emit helper / 信号可被任意敏感操作调用，emit 失败 **best-effort 不阻断主操作**（fail-soft）。
4. 凭证 / 密钥 / 明文 token 字段在审计 before/after 中**脱敏**，绝不落明文。

**不在本 phase（顺延）：**
- 各敏感操作的实际 emit 埋点覆盖、v0.5 既有埋点（`purge.started/completed`、`TriggerLog`/`ActionLog`）收口 → Phase 54。
- 查询 REST API / 前端视图 / 导出 → Phase 55。
- 密码学级防篡改（hash chain / WORM）、实时告警/SIEM/webhook、保留/归档策略 → v2 AUDITX（Out of Scope）。

</domain>

<decisions>
## Implementation Decisions

### 里程碑级已锁约束（plan-phase 必须遵守，非 grey area）
- **系统管理员 = 现有 `is_superuser`**：不新建审计角色/权限层（沿用既有决策）；查询/导出 superuser fail-closed（Phase 55 落地，本 phase 不涉权限面）。
- **不可篡改 = 应用层 append-only**：`AuditEvent` 无 update/delete 业务路径；写入经单一 service 入口，grep 守护无旁路写表（对齐 INV-6 既有守护范式）。密码学级防篡改留 v2。
- **fail-soft emit**：emit 失败 best-effort 吞异常 + warning 日志，绝不阻断/回滚主操作（对齐既有 `_run_sensitive_detection` / `record_produced_artifacts` best-effort 范式）。
- **凭证脱敏**：Provider/Git/飞书凭证、Agent API key/PAT 等的 before/after 必须脱敏，绝不落明文 token（对齐既有 PAT-02 / 凭证加密约束）。脱敏经统一构造入口（参考 Phase 24 `_redact_reason` / `_redact_value` 收口范式），禁止调用方各自手工脱敏后再传入而无服务端兜底。

### the agent's Discretion（基础设施细节，plan-phase 自行裁量）
- `AuditEvent` 落在哪个 app（建议复用既有横切位置：`system` app 或新建轻量 `audit` app；优先复用而非新建，遵循 STACK 约定）、表名、字段精确类型（`action` 用 `str` + 稳定 taxonomy 常量集；`before`/`after`/`metadata` 用 `JSONField`；`actor` 关联 `AUTH_USER_MODEL` FK 还是冗余标量 + 可空以容纳系统/匿名 actor）。
- emit 入口形态：service helper 函数 vs Django signal vs 两者并存（success_criteria 允许「helper / 信号」二选一或并存）——选最小且可被任意调用方复用的形态。
- action taxonomy 的初始词表与命名规范（动词.对象 风格，参考既有 `PlanSessionEvent` event_taxonomy / `purge.started` 命名）；本 phase 至少定义稳定常量容器，具体 action 值由 Phase 54 各埋点补充。
- 脱敏实现：字段名敏感词匹配（token/secret/password/api_key/access_token 等）+ 值级高熵/密钥模式兜底，复用/对齐 Phase 24 `sensitive_detect` 的 `_SECRET_PATTERNS` 思路（可不 import，语义对齐即可，遵守 INV-3 不跨层硬依赖）。
- async 约束：emit 在 async 上下文经 `sync_to_async` 桥接 ORM；提供 sync + async 双调用面或单一面由 plan 裁量（对齐既有 service async 范式）。
- 索引设计：按 `actor` / `action` / `target_type+target_id` / `occurred_at` 的常用过滤维度建索引，为 Phase 55 查询过滤铺底。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets（可直接复用 / 对齐的范式）
- **append-only 模型范式**：`server/delivery/models/status_event.py`（`WorkItemStatusEvent`：UUID PK、`auto_now_add` 时间戳、`(target, time)` 复合索引、模型层无 create/save 业务方法）；`server/delivery/models/comment_event.py`（`WorkItemCommentEvent`，编辑/删除作为新事件行）——`AuditEvent` 逐项镜像此形状。
- **单一写入入口 + INV-6 grep 守护**：`WorkItemService` / `CommentEventService.append_events` / `SddSpecService` 均经专用 service 单一入口写表，配 `test_*_inv6_guard.py` 正则守护（除 service 外无旁路写表）。`AuditEvent` 的 emit service 须配套同款 grep 守护测试。
- **fail-soft best-effort 范式**：`services.indexer._run_sensitive_detection`、`plan_orchestration.artifact_extraction.record_produced_artifacts`（整段 try/except 吞异常 + warning，绝不阻断主流程）。
- **脱敏范式**：`server/services/sensitive_detect.py`（`_redact_reason` 仅写类型+行号、`_SECRET_PATTERNS` 密钥正则、高熵 Shannon 检测、服务端兜底脱敏，绝不回填明文）；`server/services/exclusion.py` 的 `BUILTIN_GLOBAL_DEFAULTS` glob 基线。
- **凭证加密 / 不落明文**：`system.models.ProviderCredential`（Fernet 加密）、`repositories` 的 `GitInstanceCredential`、PAT 仅存 sha256（`access_tokens`）——脱敏需覆盖这些凭证的 before/after。
- **结构化日志**：`common.logging.configure_structlog`（structlog key-value 事件 + 凭证泄漏保护），emit 失败的 warning 走此通道。

### Established Patterns
- Django app 为边界上下文，各 app 自持 `models/`（按实体拆分 + `__init__.py` curated re-export）、`api/`、`urls.py`、`migrations/`。
- async-first：adrf 异步视图 + channels；async 上下文 ORM 经 `asgiref.sync_to_async`。
- 枚举/闭集用 `str, Enum`；值对象用 `@dataclass`；dict 形状用 `TypedDict`（mypy 拦截契约漂移）。
- 迁移用 `makemigrations` 自动生成；`makemigrations --check` 干净为 gate。

### Integration Points
- emit 地基将被 Phase 54 各敏感操作调用方接入（身份/权限类 + 凭证/数据治理类 + v0.5 `purge.started/completed`、`TriggerLog`/`ActionLog` 收口）。
- 字段/索引设计需为 Phase 55 查询过滤（actor/action/target/时间范围 + 分页）与导出（CSV/JSON）铺底。
- v0.5 既有埋点位置参考：`server/services/sensitive_purge.py`、`server/services/purge_reconcile.py`（`purge.started/completed`）；`server/subagent/`（`ActionLog`，见 `subagent/migrations/0007_add_action_log.py`）；`server/feishu/`（`TriggerLog` 相关）。

</code_context>

<specifics>
## Specific Ideas

- `AuditEvent` 字段集合以 REQUIREMENTS AUDIT-01 为准：`actor / action / target_type / target_id / target_repr / before / after / source / occurred_at / metadata`。
- `source` 字段语义：标记审计来源（如 `web` / `api` / `feishu` / `workflow` / `system`），为 Phase 55 过滤与溯源服务。
- `target_repr` 为人类可读快照（如 "用户 zhangsan" / "仓库 friday-ai"），与 `target_id` 并存，避免关联对象删除后审计不可读。
- emit service 须同时可被同步（Django 视图/signal）与异步（adrf/channels）调用方使用——优先提供统一面 + `sync_to_async` 桥接。

</specifics>

<deferred>
## Deferred Ideas

- 各敏感操作的实际 emit 埋点与 v0.5 既有埋点收口 → Phase 54。
- 审计查询 API / 前端视图 / 导出 → Phase 55。
- 密码学级防篡改（hash chain / WORM）、实时告警 / SIEM / webhook 外发、审计保留/归档/自动清理策略、读操作全量审计 → v2 AUDITX（Out of Scope）。

</deferred>
