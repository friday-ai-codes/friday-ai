# Phase 80: 项目记忆 + MR 实体 + 上下文召回接入 Web 会话 - Context

**Gathered:** 2026-06-26
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous，elegant defaults；后端 + 会话集成为主，富前端留 Phase 81）

<domain>
## Phase Boundary

给项目装上可变共享记忆、把 PR/MR 升级为实体并入站同步状态、做项目上下文打包器并接入 Web 对话，让对话能自动加载项目完整上下文。

**In scope（MEM-01~04, RECALL-01~03, MR-01/02）:**
- 项目记忆（自由文本 + 时间戳/贡献者，append/edit，成员共享）+ 人工编辑可追溯 + LLM 提炼草稿人工确认入库
- `MergeRequest` 实体 + `MergeRequestService`（INV-6）+ 入站 webhook 状态同步
- 项目上下文打包器（context packer，grep + RAG + 排序 + 压缩，token 预算可降级）
- Web 对话绑定项目自动加载上下文 + `search_delivery_knowledge` 接入 chat runner 工具白名单 + 召回 fail-closed + `RetrievalTrace`

**Out of scope:**
- **记忆编辑 / 召回 / LLM 提议确认的前端 UI** → Phase 81（UI-02/03）。本期交付后端 + API + chat runner 接入。
- Cursor 回流（分支反查/上报）→ Phase 81。
</domain>

<decisions>
## Implementation Decisions

### 项目记忆（MEM-01~04）
- `ProjectMemory` 落 `initiatives` app：`project` FK + `content`(text) + `contributor` FK→User + `created_at`/`updated_at` + `status`(active/superseded)。**编辑可追溯**：编辑写 `ProjectMemoryRevision`（append-only：memory FK + content 快照 + editor + edited_at），当前态读最新；不就地丢历史。
- **`MemoryService` 单一写入入口（INV-6）**：append/edit/supersede 全收口；模型层无业务方法 + grep 守护。
- **MEM-02 贡献限成员**：仅项目成员（`ProjectMember`）可贡献/编辑；私聊或未绑定项目/非成员会话**不纳入**（service 校验，非成员拒绝 fail-closed）。
- **MEM-04 LLM 草稿人工确认**：`ProjectMemoryDraft`（status pending/confirmed/rejected，source_conversation 引用）。LLM 从**成员会话**提炼草稿（不自动直接写 active 记忆）；人工确认 → `MemoryService.create_from_draft` 入库。**入库前脱敏不可绕过**（`redact_secrets_in_text` + `redact_for_ledger`）。提炼是**新增 LLM 调用** → 赋 `call_source`（枚举见 LOGGING-SPEC §4.1，如 `memory_distill`，无则按规范新增）+ 上报请求/token/TTFT/上游错误码。

### MR 实体（MR-01/02）
- `MergeRequest` 落 `initiatives`（或复用既有 MR/PR 散落处收口，plan-phase 盘点 `CodingTask.pr_url` 等现状决定落点，默认 `initiatives` 新实体）：`project`/`repository`/`work_item` 关联 + `url` + `source_branch`/`target_branch` + `status`(open/merged/closed) + `review_status` + `platform`(github/gitlab) + 外部 id。**`MergeRequestService` 单一写入入口（INV-6）**。
- **MR-02 入站 webhook**：复用既有 git 平台 webhook/接收面（plan-phase 盘点 `server/feishu/views.py` 之外是否已有 git webhook；无则新增受保护端点）同步 GitHub/GitLab open/merged/closed/review；**原始 payload `redact_for_ledger` 后落库**；项目内可见 MR 状态。webhook 为后台/外部触发 → 带 `initiatized_by_user_id`（经身份映射或 `system`）、幂等去重（平台 id + event）。

### 上下文召回（RECALL-01~03）
- **context packer**（service，如 `server/services/project_context_packer.py` 或 `initiatives/services/`）：按项目聚合需求(WorkItem) + 文字工件 + 记忆 + 关联知识(KnowledgeEdge) + 历史 → **grep(SQL 精确) + RAG(语义) 召回 → 排序 → 压缩**，输出可注入 LLM 的上下文；**token 预算可降级**（超预算按优先级裁剪：记忆/需求 > 工件 > 历史，plan-phase 定序）。复用 `knowledge/retrieval.py`/`vector_recall.py`/`graph_store.py`。
- **RECALL-02 接入 chat runner**：会话可绑定项目（`Conversation` 已有 project→space FK；新"绑定项目聚合根"用新字段或关联，plan-phase 定，避免与 space 混淆）；`search_delivery_knowledge` 等**接入 `agents/chat_runner.py` `_INDEXED_TOOL_NAMES` 工具白名单**（line 81 区域），对话自动加载项目上下文（经 context packer）。
- **RECALL-03 召回 fail-closed + Trace**：召回面覆盖项目全部文字工件/记忆/工作项，**按项目 scope + 用户权限 fail-closed**（非项目成员不召回该项目内容）；新增召回**上报条数/分层耗时/score 并写 `RetrievalTrace`**（MCP + AI 对话两条链都要覆盖——本期至少 AI 对话链；Cursor/MCP 链 Phase 81）。

### 观测与异步（强制规范，本期触面最多）
- 新增 LLM（记忆提炼）赋 `call_source` + token/TTFT/上游错误码；新增召回写 `RetrievalTrace` + 条数/分层耗时/score；webhook 原始 payload `redact_for_ledger`；后台/外部触发带 `initiated_by_user_id`，worker 入口 re-bind。
- 记忆/MR 写入经 `AuditService`（component=initiatives）；async ORM 走 `sync_to_async`；脱敏不可绕过；best-effort 观测不反噬主流程。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/initiatives/`（Phase 77~79）：`Project`/`ProjectMember`/`ProjectService`/`Artifact`/KnowledgeEdge 关联。
- `server/agents/chat_runner.py`（`_INDEXED_TOOL_NAMES` line 81、工具白名单与召回链）、`server/agents/tools/`（`delivery_knowledge_tools`/`space_tools`）。
- `server/knowledge/`：`retrieval.py`/`vector_recall.py`/`graph_store.py`（召回）+ `RetrievalTrace`（v0.14 观测）。
- `server/chat/`：`Conversation`（绑定 space 的 FK）/`conversation_service.py`/`services.py`。
- `server/services/git_platform/`：GitHub/GitLab 客户端（MR 平台 id/状态来源）；`CodingTask.pr_url` 等 MR 现状散落点。
- `server/audit/`、可观测设施（`call_source`/`RetrievalTrace`/`ModelUsageRecord`，v0.14 Phase 71–74）。

### Established Patterns
- 单一写入 service（INV-6）+ append-only 事件/版本（`delivery` status_event/`ProjectMemoryRevision` 同范式）。
- 召回经 search_rag chokepoint fail-closed；新增 LLM 赋 call_source；webhook 脱敏落库幂等。

### Integration Points
- context packer ← WorkItem(delivery) + Artifact(initiatives) + ProjectMemory(initiatives) + KnowledgeEdge(knowledge) → chat_runner 注入。
- MR webhook ← git 平台；MR 实体 ↔ project/repository/work_item。
- 记忆提炼 LLM ← 成员会话消息。
</code_context>

<specifics>
## Specific Ideas

- 记忆编辑保留可追溯用 append-only `ProjectMemoryRevision`（不就地覆盖丢历史）。
- LLM 提炼仅产 `ProjectMemoryDraft`（pending），**绝不自动写 active 记忆**；人工确认才入库（MEM-04 硬约束）。
- 会话"绑定项目聚合根"与现有 `Conversation.space`（原 project）区分清楚，避免命名/语义串味。
- MR 落点先盘点现状（`CodingTask.pr_url`/PR 散落），默认 `initiatives` 新实体 + service 收口。
- 召回 fail-closed：非项目成员对该项目记忆/工件零召回零泄漏（对齐 Phase 22~25 排除范式）。
</specifics>

<deferred>
## Deferred Ideas

- 记忆编辑 / 召回结果 / LLM 提议确认**前端 UI** → Phase 81（UI-02/03）。
- Cursor/MCP 分支反查召回链路 + 上报写回 → Phase 81（CURSOR）。
- 结构化记忆 / 自动降权 / 矛盾消解 / 全自动提炼 → v2（PROJX-02/03）。
- 每次对话全量加载（非召回压缩）→ 未来（上下文窗口扩大）。
- 真实 git 平台 webhook 端到端 MR 状态同步人工验收 → 里程碑级。
</deferred>
