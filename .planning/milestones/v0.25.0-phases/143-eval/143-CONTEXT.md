# Phase 143: 价值评估与中高入图 - Context

**Gathered:** 2026-08-28
**Status:** Ready for planning

<domain>
## Phase Boundary

在 Capture 已持久化之后，用 Friday LLM 异步完成 high/medium/low 价值评估与可检索精华提炼，并以可恢复、可重试的状态机仅把 medium/high 精华投递到既有 `delivery_knowledge`。本阶段不改变 MCP 接受契约，不实现对外检索/原文回放或 IDE hooks，也不把 Capture 转成 `ProjectMemory`。

</domain>

<decisions>
## Implementation Decisions

### 价值评估契约
- 评估结果使用严格闭集 `high`、`medium`、`low`；评估器同时产出一段可独立召回的 `distilled_essence`，只保留可复用结论、约束、根因、解决方案和验证证据。
- 价值等级必须由 Friday LLM 独立判断，不复用 `evaluate_writeback_quality`、`knowledge.llm_grader` 的 related/duplicate 词表或仓库路由 confidence；确定性质量门最多用于拒绝空输入，不能代替三档评估。
- 新 LLM 调用固定使用 `CallSource.SESSION_CAPTURE_EVAL = "session_capture_eval"`，在首次调用前同步更新 `server/agents/call_source.py`、LOGGING-SPEC 枚举/事件目录与用量断言。
- 评估失败保留原始 Capture，记录脱敏错误与可重试状态；不得删除行、把失败默认为 low，或猜测缺失模型/provider/token 元数据。

### Persist-first durable 状态机
- Phase 142 的同步请求先提交 Capture，再通过 `transaction.on_commit` 把仅含 `capture_id` 的任务交给 `DurableTaskService.defer`；数据库行是工作真相，进程内 `background_runner` 不得成为唯一投递。
- 状态机覆盖 `pending_eval → evaluating → evaluated_low | ingest_pending → ingesting → ingested`，评估/入图失败进入可重试失败态并保留 attempt、last_error、next retry 所需信息；状态转移只经 `CaptureService` 扩展方法，继续满足 INV-6。
- durable 任务以 Capture id 构造稳定 idempotency key/lock，worker 每步先读当前状态并以条件更新抢占；at-least-once 重放不得重复 LLM 评估、重复版本翻转或把终态退回处理中。
- worker 入口必须从 payload 读取并用 `bind_task_context` 重新绑定 `initiated_by_user_id`；缺失时显式使用 `system`。入队失败、进程重启和临时上游失败都能由 pending/failed 扫描或重投恢复。

### 中高价值统一知识摄取
- 只有 `medium`/`high` 进入摄取；`low` 仅保存等级和提炼结果供回放/评测，不调用 embedding、`aschedule_ingestion` 或 Qdrant。
- 入图固定复用 `EntityKind.DOCUMENT`、现有 `delivery_knowledge` collection 与新 `source_kind="session_capture"`；不得新增 EntityKind、collection 或平行向量库。
- 新 normalizer 只从 Capture 的 `distilled_essence` 构造 `IngestionEvent.content`；原始 `question`/`answer`、完整 transcript 与 Ledger payload 永远不进入 RAG 正文或版本 payload。
- 仓库信息写入 `repository_id`；存在授权项目关联时按既有项目图谱模式附加 `REFERENCES` 边与 `space_id`，无项目不阻断仓级入图。摄取仍经既有 ingestion 六步序，禁止直接写 KnowledgeEntity/Qdrant。

### 安全、记忆隔离与观测
- 评估与入图路径禁止调用 `MemoryService.append`、`record_hook_writeback` 或任何 active `ProjectMemory` 写入口；项目长期记忆继续遵守 draft/人工门控。
- 评估、normalizer、入图任务发 `sampling` 类 started/completed/failed 结构化事件，统一带 `component=knowledge`、`capture_id`、tier/状态、`duration_ms` 与触发用户，不记录问答或精华正文。
- LLM/embedding 既有 chokepoint 继续上报请求数、token、TTFT 与上游错误码；异常文本在日志或状态字段前经 `redact_secrets_in_text`，观测失败 best-effort 不改变状态机业务结果。
- 自动化验收必须覆盖低价值无向量、中高只索引精华、评估失败保留 Capture、重放幂等、重启后 pending 可恢复、触发用户重绑定以及 `ProjectMemory` 零写入。

### the agent's Discretion
- 具体状态枚举命名、retry backoff 参数、最大尝试次数、评估 JSON schema 与 evaluator 内部模块拆分由实现者决定，但必须保留 persist-first、可恢复和三档闭集语义。
- 可新增独立逻辑队列或复用合适的 knowledge/maintenance 队列；必须通过 `durable.queues` 常量登记并保持双后端 task/handler 参数对齐。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/initiatives/models/session_capture.py` 已有 `PENDING_EVAL`、`EVAL_FAILED`、`INGEST_PENDING`、`EVALUATED` 基础状态、仓库/项目可空 FK、触发用户、状态索引与幂等约束，可通过后续 migration 扩展评估/摄取字段。
- `server/initiatives/services/capture_service.py` 是 SessionCapture 唯一 writer；其脱敏、first-write-wins 与 caller 日志不能旁路，后续 CAS 状态方法应继续放在该服务。
- `server/durable/service.py::DurableTaskService.defer` 已支持 queue、idempotency_key、lock、run_at 与 `initiated_by_user_id` 跨 worker 传播。
- `server/knowledge/ingestion.py::ingest/ingest_events` 提供 normalizer → 六步版本翻转 → Qdrant 的幂等核心；`server/knowledge/sources/project_memory.py` 提供 DOCUMENT、脱敏与项目 REFERENCES 边范式。

### Established Patterns
- `server/durable/tasks.py`、`server/durable/tasks_impl.py`、`server/durable/handlers.py` 以 Procrastinate 包壳 + 共用 keyword-only 任务体 + in-process `**payload` adapter 保持双后端同语义。
- `server/durable/tasks_impl.py::run_runner_dispatch` 展示状态守卫、re-defer 退避、脱敏异常和 `bind_task_context`；`run_feature_list_parse_module` 展示有界重试。
- `server/agents/call_source.py::CallSource` + `use_call_source` 是所有 LLM 用量归因的权威有限枚举；Phase 141 明确未提前新增 `session_capture_eval`。

### Integration Points
- 为 `SessionCapture` 增加 value tier、distilled essence、评估/入图尝试与错误/终态字段，并在 `CaptureService` 添加条件状态转移、评估结果和失败记录方法。
- 在 `durable/queues.py`、`tasks.py`、`tasks_impl.py`、`handlers.py` 注册 Capture eval/ingest 任务；Phase 142 新 view 在 Capture commit 后只负责入队首个 durable 任务。
- 在 `server/knowledge/sources/__init__.py::_NORMALIZERS` 注册 `session_capture`，新增 normalizer 后复用 `knowledge.ingestion.ingest`，由 worker 根据实际摄取结果回写 Capture 状态。
- 在 `server/agents/call_source.py` 与 `.planning/observability/LOGGING-SPEC.md` 同步 `session_capture_eval` 及 sampling 生命周期。

</code_context>

<specifics>
## Specific Ideas

- durable payload 只携带 `capture_id`、attempt 与 `initiated_by_user_id` 等审计标量；问答正文从数据库读取，禁止复制进队列 payload。
- high/medium 的向量正文必须是“脱离原会话仍可理解”的可检索精华；low 的原始 Capture 仍完整可回放，但永不占用向量索引。
- “已接受”由 Phase 142 的 Capture commit 决定；Phase 143 的任何评估、队列或向量故障都不能追溯性改变该事实。

</specifics>

<deferred>
## Deferred Ideas

- 对外仓库/项目检索、Capture id 原文回放、`session_capture` 读白名单与 RetrievalTrace 收口延后到 Phase 144。
- Cursor / Claude Code hooks、技能和安装器接线延后到 Phase 145。
- 人工价值纠偏 UI、Capture → `ProjectMemory` 草稿提升与评估 golden set 产品化留后续版本。
- 不修复其他既有 knowledge ingestion 调用点仍使用 `background_runner` 的历史窗口；本阶段只保证 Session Capture 新路径 durable。

</deferred>
