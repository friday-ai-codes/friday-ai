---
phase: 80
title: 项目记忆 + MR 实体 + 上下文召回接入 Web 会话
milestone: v0.15.0
status: planned
requirements: [MEM-01, MEM-02, MEM-03, MEM-04, RECALL-01, RECALL-02, RECALL-03, MR-01, MR-02]
---

# Phase 80 PLAN — 项目记忆 + MR 实体 + 上下文召回接入 Web 会话

## 目标回顾（5 条 Success Criteria）

1. 项目记忆（自由文本 append/edit + 时间戳/贡献者）成员共享；贡献仅限成员（非成员/私聊 fail-closed）；可人工编辑覆盖且**保留可追溯**。
2. LLM 从成员会话提炼记忆草稿 → 人工确认入库（绝不自动写 active）；入库前脱敏不可绕过。
3. `MergeRequest` 实体（项目/仓库/分支/工作项 + url + 状态 + review）经单一入口 `MergeRequestService`；入站 webhook 同步 GitHub/GitLab（脱敏原始 payload 落库），项目内可见。
4. context packer——聚合需求/工件/记忆/关联知识/历史，grep(SQL) + RAG(语义) 召回 + 排序 + 压缩，token 预算可降级。
5. Web 对话可绑定项目自动加载上下文；`search_delivery_knowledge` 等接入 chat runner 白名单；召回按项目 scope + 用户权限 fail-closed + 写 `RetrievalTrace`。

## 盘点结论（plan-phase 调研）

- **MR 落点**：现状 `CodingTask.pr_url` / `CodingSession.pr_url` / `McpCodingExecutionTrace.mr_result` 是散落的 url 字符串/JSON，无独立实体。**新 `MergeRequest` 实体落 `initiatives` app**（默认决策成立），与 `Project` 同域；不改既有散落字段（零回归），新实体作统一可见/同步面。
- **git webhook 接收面盘点**：`system/webhook_views.py` 只是 `InboundWebhookEvent` 的**只读查看 API**；`workflows/triggers/handlers/webhook.py` 是通用工作流 webhook 触发，非 git 平台 MR 状态接收。**无既有 git 平台 MR 状态入站端点 → 本期新增受保护端点**（`initiatives/webhook_views.py` + `webhook_urls.py`）。
- **原始 payload 留痕**：复用 `system.webhook_recorder.record_inbound_webhook`（已 `redact_for_ledger` + 截断 + best-effort）写 `InboundWebhookEvent`（kind=`git_mr`）；MR 同步侧 `MergeRequestEvent` append-only 行额外存 redact 后的事件 payload + 幂等 dedup_key。
- **call_source**：`memory_distill` 不在 LOGGING-SPEC §4.1 的 22 枚举内 → 本期**新增**（§4.1 表 + `agents/call_source.py` `CallSource` 枚举，共 23 值）。

## 锁定设计决策

### 记忆（MEM-01~04）
- 三模型落 `initiatives`：`ProjectMemory`（project FK + content + contributor + status active/superseded + 时间戳）/ `ProjectMemoryRevision`（append-only：memory FK + content 快照 + editor + edited_at）/ `ProjectMemoryDraft`（status pending/confirmed/rejected + source_conversation_id 软引用 UUID + proposed_by + confirmed_memory FK）。模型层无业务方法（INV-6，grep 守护）。
- **MemoryService 单一写入入口**：append/edit/supersede + create_draft/confirm_draft/reject_draft 全收口。
- **MEM-02 成员校验 fail-closed**：`_assert_member(project_id, user)` —— 非 `ProjectMember` 抛 `MemoryPermissionError`（贡献/编辑/确认草稿均校验）。私聊/未绑定项目会话天然无 project 不进入。
- **MEM-03 可追溯**：edit 不就地丢历史——更新 `ProjectMemory.content` 同时 append 一条 `ProjectMemoryRevision` 快照（编辑前态）；首次 append 也落初始 revision。
- **MEM-04 草稿**：`MemoryDistiller`（LLM）从成员会话消息提炼候选 → `redact_secrets_in_text` 脱敏 → `MemoryService.create_draft`（pending，**绝不写 active**）。`confirm_draft` → `MemoryService.append`（create_from_draft 语义）入库。distill 是新增 LLM 调用 → `use_call_source("memory_distill")` + `arecord_llm_usage`（token/TTFT/上游错误码，best-effort）。
- 写入经 `AuditService.aemit`（component=initiatives）；async ORM 走 `sync_to_async`。

### MR（MR-01/02）
- `MergeRequest`（initiatives）：project/repository/work_item FK（均 SET_NULL nullable）+ url + source_branch/target_branch + status(open/merged/closed) + review_status + platform(github/gitlab) + external_id + title。幂等键 `UniqueConstraint(platform, repository, external_id)`（external_id 非空）。
- `MergeRequestEvent`（append-only）：merge_request FK + event_type + dedup_key(unique) + raw_payload(TextField，redact 后) + created_at。
- **MergeRequestService 单一写入入口**：`upsert`（按幂等键建/更）+ `sync_from_webhook`（解析 github/gitlab payload → 幂等 dedup（dedup_key 已存在则跳过）→ upsert + append event）。审计 component=initiatives。
- **MR-02 webhook**：新增受保护端点 `POST /api/git-webhooks/<platform>/`——校验共享密钥（GitHub `X-Hub-Signature-256` HMAC / GitLab `X-Gitlab-Token`，密钥取 `SettingKeys.GIT_WEBHOOK_SECRET`；未配置 → fail-closed 403）→ `record_inbound_webhook(kind="git_mr")` 原始留痕 → `MergeRequestService.sync_from_webhook`（携 `initiated_by_user_id`：身份映射或 `system`）。后台/外部触发，worker 入口 re-bind 经现有 `record_inbound_webhook` 范式。

### 召回（RECALL-01~03）
- **context packer** `services/project_context_packer.py`：`pack_project_context(project, user, *, query, conversation_id, token_budget)`：
  - **fail-closed**：user 非 `ProjectMember` → 返回空（zero recall / zero leakage）。
  - 分层聚合（grep=SQL 精确）：① 记忆（active ProjectMemory）② 需求（ProjectWorkItemLink→WorkItem 三元组/标题）③ 工件（Artifact TEXT_CARRIERS + content_ref）④ 关联知识（ProjectKnowledgeGraphService.query_graph）⑤ 历史（conversation 最近消息）。
  - **RAG（语义）**：`DeliveryKnowledgeSearchService.search_similar(query, user, project_ids=...)`（已 fail-closed scope）。
  - **排序 + 压缩 + token 预算可降级**：优先级 记忆/需求 > 工件 > 知识/RAG > 历史；超预算按优先级裁剪低优层。
  - **RetrievalTrace**：`arecord_retrieval_trace(kind="chunk", payload={counts, layer_timing_ms, scores}, conversation_id, user_id, source="chat_project_context")`（best-effort）；分层耗时 + 条数 + score 上报。
- **RECALL-02 chat 接入**：`Conversation.bound_project` FK→`initiatives.Project`（SET_NULL nullable，**区别于 `space`**）。`build_sdk_config`：bound_project 且 created_by 是成员 → packer → 把打包上下文段拼进 system_prompt；非成员/未绑定 → 不注入（fail-closed）。`chat_runner._INDEXED_TOOL_NAMES` 增 `search_delivery_knowledge`/`get_entity_timeline`/`get_related_entities`（import `agents.tools.delivery_knowledge_tools` 触发注册）。
- **RECALL-03 fail-closed + Trace**：packer + 工具两条召回面均按 user 权限 fail-closed；packer 写 RetrievalTrace（AI 对话链；MCP/Cursor 链 Phase 81）。

### 观测/异步
- 新 LLM（memory_distill）赋 call_source + token/TTFT/上游错误码；新召回写 RetrievalTrace + 条数/分层耗时/score；webhook 原始 payload redact_for_ledger；webhook 带 initiated_by_user_id。best-effort 不反噬主流程；脱敏不可绕过。

## Waves

### Wave 1 — 模型 + 迁移 + 词表 + call_source（地基）
- `initiatives/models/memory.py`：`ProjectMemory`/`ProjectMemoryStatus`/`ProjectMemoryRevision`/`ProjectMemoryDraft`/`DraftStatus`。
- `initiatives/models/merge_request.py`：`MergeRequest`/`MRStatus`/`MRPlatform`/`MergeRequestEvent`。
- `initiatives/models/__init__.py` 导出。
- 迁移 `initiatives/0005_memory_mergerequest.py`。
- `audit/services/taxonomy.py` +actions：`project.memory_created/memory_edited/memory_superseded`、`project.memory_draft_created/draft_confirmed/draft_rejected`、`merge_request.synced`。
- `agents/call_source.py` + LOGGING-SPEC §4.1：`memory_distill`。
- commit `feat(80): 项目记忆/MR 实体模型 + 迁移 + 审计词表 + memory_distill call_source`

### Wave 2 — MemoryService（INV-6 + 成员校验 + 草稿 + 蒸馏 LLM）
- `initiatives/services/memory_service.py`：append/edit/supersede + create_draft/confirm_draft/reject_draft（成员校验 fail-closed + redact + 可追溯 revision + 审计）。
- `initiatives/services/memory_distill.py`：`MemoryDistiller`（LLM 提炼 → 脱敏 → create_draft；call_source + arecord_llm_usage；fail-soft）。
- `initiatives/services/__init__.py` 导出。
- commit `feat(80): MemoryService 单一写入 + 成员校验 + 可追溯 revision + LLM 草稿蒸馏`

### Wave 3 — MergeRequestService（INV-6）+ 入站 webhook
- `initiatives/services/mr_service.py`：`MergeRequestService.upsert` + `sync_from_webhook`（解析 + 幂等 dedup + append event + 审计）。
- `initiatives/webhook_views.py`：`GitMergeRequestWebhookView`（共享密钥校验 fail-closed + record_inbound_webhook + sync）。
- `initiatives/webhook_urls.py` + `friday/urls.py` 接线；`SettingKeys.GIT_WEBHOOK_SECRET`。
- commit `feat(80): MergeRequestService 单一写入 + 入站 git webhook 状态同步（脱敏 + 幂等）`

### Wave 4 — context packer
- `services/project_context_packer.py`：`pack_project_context`（fail-closed + grep + RAG + rank + compress + token 预算降级 + RetrievalTrace）。
- commit `feat(80): 项目上下文打包器（grep+RAG+排序+压缩+token预算降级+RetrievalTrace）`

### Wave 5 — chat 接入
- `chat/models.py`：`Conversation.bound_project` FK；迁移 `chat/0028_conversation_bound_project.py`。
- `agents/chat_runner.py`：import delivery_knowledge_tools + `_INDEXED_TOOL_NAMES` 增 3 工具。
- `chat/config.py`：`build_sdk_config` 注入打包上下文（fail-closed）。
- commit `feat(80): 会话绑定项目 + chat runner 召回工具白名单 + 自动加载项目上下文`

### Wave 6 — REST API
- `initiatives/serializers.py`：Memory*/MemoryDraft*/MergeRequest* serializers。
- `initiatives/views.py`：Memory CRUD + supersede + draft list/distill/confirm/reject + MR list。
- `initiatives/urls.py` 接线。
- commit `feat(80): 项目记忆/草稿/MR REST API`

### Wave 7 — 测试
- `tests/initiatives/`：`test_memory_inv6_guard.py`、`test_merge_request_inv6_guard.py`、`test_memory_service.py`、`test_memory_distill.py`、`test_merge_request_service.py`、`test_git_webhook.py`、`test_memory_mr_api.py`。
- `tests/services/test_project_context_packer.py`。
- `tests/test_chat_project_recall.py`（绑定 + 白名单 + fail-closed + RetrievalTrace）。
- `tests/audit/test_audit_taxonomy.py` 扩展。
- commit `test(80): 记忆/草稿/MR/webhook/packer/chat 召回守护测试`

## 验证
- `makemigrations --check --dry-run` 干净。
- `uv run pytest -q`：baseline 38 failed 不变（零新增回归，+1 已知 flaky cross-suite ordering），新增用例全绿；chat/agents 套件确认绿。
