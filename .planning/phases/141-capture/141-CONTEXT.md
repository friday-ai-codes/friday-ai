# Phase 141: Capture 账本与仓库挂钩 - Context

**Gathered:** 2026-08-28
**Status:** Ready for planning

<domain>
## Phase Boundary

建立独立的 Session Capture 持久化账本与唯一写入服务，使结构化问题和可见答案精华在仓库、项目解析失败时仍安全落库。本阶段只完成持久化、挂钩、状态初始化、权限边界与观测，不实现 MCP 工具、价值评估、入图、召回或 IDE hook。

</domain>

<decisions>
## Implementation Decisions

### 账本落点与数据边界
- 模型放在 `initiatives` app，命名为 `SessionCapture`，数据库表命名为 `initiative_session_captures`；它是独立 Capture 账本，不复用 `ProjectMemory` 或 Interaction Ledger。
- `project` 与 `repository` 外键都允许为空；以仓库为主挂钩，项目仅为可选上下文。
- 正文只保存结构化 `question`、可见 `answer` 精华和标量元数据；不保存完整 transcript、隐藏思维链或 Ledger payload。
- 状态机预留 `pending_eval`、`eval_failed`、`ingest_pending` 等后续阶段所需状态；本阶段新建记录只进入 `pending_eval`。

### 挂钩、幂等与权限
- 幂等键采用触发用户、`session_id` 与规范化问题哈希的组合；重复提交返回既有 Capture，不重复落账。
- `session_id` 缺失时仍接受写入，并为该次 Capture 使用稳定可审计的后备标识，不以缺少会话号拒绝数据。
- 仓库解析顺序固定为显式 `repository_id`、规范化 `git_url`，再结合可选 `project_id` 校验上下文；任何解析失败都保留 Capture，并写明确 `reason`。
- 提交者不是项目成员或无权访问目标仓库时，不建立未授权外键关系，但仍保存归属于该用户的 Capture 和拒绝挂钩原因；读取与回放继续按仓库可见性和本人归属 fail-closed。

### 评估状态与入图边界
- Phase 141 仅定义持久化所需状态字段与初始 `pending_eval`，不调用 LLM、不计算 high/medium/low。
- Phase 143 才负责持久化后的 durable 评估调度、失败重试和触发用户上下文重绑定。
- Phase 141 不调用 `aschedule_ingestion`、`background_runner`、`MemoryService.append` 或 `record_hook_writeback`。
- 原始问题与答案永远是 Capture 回放数据；后续只有评估产生的可检索精华可作为 `source_kind=session_capture` 入图。

### 服务边界、安全与可观测
- 所有写入只能经 INV-6 `CaptureService`；增加静态 grep 守卫，禁止业务代码旁路调用 `SessionCapture.objects.create`、`bulk_create`、`get_or_create`、`update_or_create` 或直接更新状态。
- `CaptureService` 在落库前统一调用现有脱敏能力；未知的 model、provider、token 字段保存为字面值 `unknown`，服务端不猜测。
- 持久化记录 `session_capture_persist_started/completed/failed` caller 事件，统一 `component=knowledge`，completed/failed 带 `duration_ms`、`initiated_by_user_id`、Capture/挂钩结果等非敏感关联字段。
- 日志与 Interaction Ledger 只记录审计元数据，不复制问题/答案正文；观测写入 best-effort，失败不得反噬 Capture 持久化。

### the agent's Discretion
- 具体字段长度、索引名称、枚举实现和内部 helper 拆分由实现者按现有 Django 约定决定。
- 可在不改变上述契约的前提下提取共享 git URL 规范化工具，避免继续复制私有实现。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/initiatives/models/memory.py` 与 `server/initiatives/services/memory_service.py` 提供 INV-6 唯一写入服务、脱敏和成员校验模式，但 Capture 不复用其存储或 active memory 写入口。
- `server/repositories/models.py` 的 `Repository`、`server/initiatives/models/member.py` 的 `ProjectMember`、`server/initiatives/models/repo_association.py` 的 `RepoAssociation` 可支持挂钩与访问校验。
- `server/common/logging.py` 提供 `redact_secrets_in_text` 和 credential processor；`server/common/log_context.py` 提供触发用户上下文绑定。

### Established Patterns
- `server/tests/initiatives/test_memory_inv6_guard.py` 与 `test_repo_association_inv6_guard.py` 使用源码扫描守卫唯一 writer，可直接复制为 Capture INV-6 验收。
- `server/durable/service.py` 的 `DurableTaskService.defer` 和 worker `bind_task_context` 是 Phase 143 persist-first 异步处理的既有模式。
- 服务生命周期日志使用 `structlog.get_logger(__name__)`、snake_case 事件、`category`/`component` kv 字段和 `duration_ms`。

### Integration Points
- 新模型从 `server/initiatives/models/__init__.py` 导出，并配套 migration、admin/serializer（如后续需要）与 service barrel。
- git URL 规范化目前散落在 `server/initiatives/services/mr_service.py` 和 `server/services/sensitive_purge.py`，规划时应选定单一可复用入口。
- Phase 142 的 `report_session_knowledge` 将调用 `CaptureService`；既有 `mcp_tools/views.py::_resolve_report_project_id` 的 `branch_unresolved` 跳过逻辑不得进入新服务。

</code_context>

<specifics>
## Specific Ideas

- “永不静默丢失”优先于仓库或项目挂钩成功；`accepted` 表示 Capture 已收，不代表挂钩成功。
- 默认分支误匹配修复属于 Phase 144；本阶段不得把 `main`、`master`、`develop` 单独作为项目唯一证据。

</specifics>

<deferred>
## Deferred Ideas

- MCP serializer、snapshot 与 npm 工具契约延后到 Phase 142。
- LLM 价值评估、durable 调度和 medium/high 入图延后到 Phase 143。
- 仓库召回、Capture 回放和默认分支 lookup 修复延后到 Phase 144。
- Cursor / Claude Code hooks 与安装器延后到 Phase 145。

</deferred>
