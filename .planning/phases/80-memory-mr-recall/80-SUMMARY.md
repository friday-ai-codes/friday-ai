---
phase: 80
title: 项目记忆 + MR 实体 + 上下文召回接入 Web 会话
milestone: v0.15.0
status: complete
completed: 2026-06-26
requirements: [MEM-01, MEM-02, MEM-03, MEM-04, RECALL-01, RECALL-02, RECALL-03, MR-01, MR-02]
---

# Phase 80 SUMMARY — 项目记忆 + MR 实体 + 上下文召回接入 Web 会话

## 落点决策 + 盘点结论

- **MR 实体落点**：盘点确认 MR/PR 状态此前仅以 url 字符串/JSON 散落在 `CodingTask.pr_url` /
  `CodingSession.pr_url` / `McpCodingExecutionTrace.mr_result`，**无独立实体**。本期新建独立
  `MergeRequest` 实体落 **`initiatives` app**（与 `Project` 同域），不改既有散落字段（零回归），
  作统一可见 + 入站同步面。
- **git webhook 接收面盘点**：`system/webhook_views.py` 仅是 `InboundWebhookEvent` 只读查看 API；
  `workflows/triggers/handlers/webhook.py` 是通用工作流 webhook 触发——**均非 git 平台 MR 状态
  接收端点**。本期**新增**受保护端点 `POST /api/git-webhooks/<platform>/`。
- **观测新增 call_source**：`memory_distill` 不在 LOGGING-SPEC §4.1 既有 22 枚举内 → 新增（§4.1
  表 + `CallSource` 枚举，共 **23** 值）。

## 新增模型（migrations）

| 模型 | 表 | 说明 |
|---|---|---|
| `initiatives.ProjectMemory` | `initiative_project_memories` | 记忆当前态：project FK + content + contributor + status(active/superseded) |
| `initiatives.ProjectMemoryRevision` | `initiative_project_memory_revisions` | **append-only** 编辑历史快照（MEM-03 可追溯） |
| `initiatives.ProjectMemoryDraft` | `initiative_project_memory_drafts` | LLM 草稿（pending/confirmed/rejected）+ source_conversation_id 软引用 + confirmed_memory FK |
| `initiatives.MergeRequest` | `initiative_merge_requests` | MR 实体：project/repository/work_item + url + 源·目标分支 + status + review_status + platform + external_id（幂等键 `(platform,repository,external_id)`） |
| `initiatives.MergeRequestEvent` | `initiative_merge_request_events` | **append-only** webhook 事件留痕：脱敏 raw_payload + 幂等 `dedup_key`(unique) |

- 迁移：`initiatives/migrations/0005_mergerequest_mergerequestevent_projectmemory_and_more.py`、
  `chat/migrations/0028_conversation_bound_project.py`（`Conversation.bound_project` FK）。

## 服务 / 入口

- **`MemoryService`（INV-6 单一写入）** `initiatives/services/memory_service.py`：
  `append`/`edit`（append revision 保留历史）/`supersede` + `create_draft`/`confirm_draft`/`reject_draft`。
  **MEM-02 成员校验 fail-closed**（`_assert_member`，非成员 `MemoryPermissionError`）；
  **脱敏不可绕过**（`redact_secrets_in_text` 入库 + AuditService before/after redact）；审计 component=initiatives。
- **`MemoryDistiller`** `initiatives/services/memory_distill.py`：LLM 从成员会话提炼 → 脱敏 →
  `create_draft`（**pending，绝不自动写 active**）。`call_source="memory_distill"` +
  `arecord_llm_usage`（token/TTFT/上游错误码，best-effort）；成员校验 fail-closed；LLM 失败 fail-soft。
- **`MergeRequestService`（INV-6 单一写入）** `initiatives/services/mr_service.py`：
  `upsert`（幂等键建/更）+ `sync_from_webhook`（解析 GitHub/GitLab → 幂等 `dedup_key` 去重 →
  upsert + append `MergeRequestEvent`，**原始 payload `redact_for_ledger` 脱敏后落库**）。
  仓库 best-effort 按 git_url 归一化匹配；审计 component=initiatives。
- **context packer** `services/project_context_packer.py` `pack_project_context`：
  **fail-closed**（非成员零召回零泄漏）+ 分层聚合（记忆/需求/工件/关联知识/历史 grep + RAG 语义）+
  排序（按优先级 + score）+ 压缩 + **token 预算可降级**（超预算裁剪低优层：记忆/需求 > 工件 > 知识/RAG > 历史）+
  **写 RetrievalTrace**（条数/分层耗时/score，source=`chat_project_context`，best-effort）。

## 入站 webhook（MR-02）

- `initiatives/webhook_views.py` `GitMergeRequestWebhookView` + `webhook_urls.py`：
  - **共享密钥校验 fail-closed**：GitHub `X-Hub-Signature-256` HMAC-SHA256 / GitLab `X-Gitlab-Token` 等值；
    密钥取 `SettingKeys.GIT_WEBHOOK_SECRET`，**未配置即 403**。
  - 原始 payload 经 `system.webhook_recorder.record_inbound_webhook`（kind=`git_mr`，已 redact + 截断）留痕。
  - `MergeRequestService.sync_from_webhook`（dedup_key 取 delivery id，幂等），后台/外部触发携 `initiated_by_user_id="system"`。

## chat 集成（RECALL-02/03）

- `Conversation.bound_project` FK（区别于 `space` 组织单元）——绑定项目聚合根。
- `agents/chat_runner.py`：import `delivery_knowledge_tools` + `_INDEXED_TOOL_NAMES` 增
  `search_delivery_knowledge`/`get_entity_timeline`/`get_related_entities`（这些工具以 conversation_id 解析 owner 做权限）。
- `chat/config.py` `build_sdk_config`：`_maybe_pack_project_context` —— 绑定项目 + owner 是成员时经 packer
  把项目上下文拼进 system_prompt；非成员/未绑定/无 owner → 不注入（fail-closed）；整体 best-effort。

## REST API

- 记忆：`GET/POST /api/projects/<id>/memories/`、`PATCH/DELETE /api/projects/<id>/memories/<mid>/`（DELETE=supersede）。
- 草稿：`GET/POST /api/projects/<id>/memory-drafts/`（POST=从会话蒸馏）、`.../<did>/confirm/`、`.../<did>/reject/`。
- MR：`GET /api/projects/<id>/merge-requests/`（项目内可见）。
- webhook：`POST /api/git-webhooks/<platform>/`（共享密钥鉴权）。
- 权限：读 = Space viewer+ 或项目成员；记忆写入由 MemoryService 成员校验 fail-closed（API 转 403/400）。

## 观测新增

- **call_source** `memory_distill`（LOGGING-SPEC §4.1 + `CallSource` 枚举，23 值）+ 蒸馏 LLM 上报 token/TTFT/上游错误码。
- **RetrievalTrace**：context packer 召回写 `RetrievalTrace`（kind=chunk，payload 含 counts/layer_timing_ms/scores，source=`chat_project_context`）。
- webhook 原始 payload `redact_for_ledger`（事件留痕 + InboundWebhookEvent）。
- 审计词表 +7 action：`project.memory_created/edited/superseded/draft_created/draft_confirmed/draft_rejected`、`merge_request.synced`。

## 文件改动清单（28 文件）

- 新增源码（10）：`initiatives/models/memory.py`、`initiatives/models/merge_request.py`、
  `initiatives/services/memory_service.py`、`initiatives/services/memory_distill.py`、
  `initiatives/services/mr_service.py`、`initiatives/webhook_views.py`、`initiatives/webhook_urls.py`、
  `services/project_context_packer.py`、`initiatives/migrations/0005_*.py`、`chat/migrations/0028_*.py`。
- 修改源码（11）：`initiatives/models/__init__.py`、`initiatives/services/__init__.py`、
  `initiatives/serializers.py`、`initiatives/views.py`、`initiatives/urls.py`、
  `audit/services/taxonomy.py`、`agents/call_source.py`、`agents/chat_runner.py`、
  `chat/models.py`、`chat/config.py`、`system/models.py`、`friday/urls.py`。
- 新增/修改测试（8 + 1）：`tests/initiatives/test_memory_inv6_guard.py`、`test_merge_request_inv6_guard.py`、
  `test_memory_service.py`、`test_memory_distill.py`、`test_merge_request_service.py`、`test_git_webhook.py`、
  `test_memory_mr_api.py`、`tests/services/test_project_context_packer.py`、`tests/test_chat_project_recall.py`；
  扩展 `tests/test_model_usage_call_source.py`（22→23）。
- 文档：`.planning/observability/LOGGING-SPEC.md`（§4.1 +memory_distill）。

## 测试结果

- **新增 39 用例全绿**（+ call_source 基准 25 用例全绿）：
  - INV-6 grep 守护（Memory ×2 / MergeRequest ×2）
  - MemoryService append/edit(revision 历史保留)/supersede + 成员 fail-closed + 脱敏 + 草稿 create/confirm/reject + 非成员确认拒绝（8）
  - 蒸馏：仅产 pending 草稿/脱敏/NONE 不产/非成员 fail-closed/call_source 枚举（5）
  - MergeRequestService github/gitlab open→merged/review/幂等 dedup/raw payload 脱敏/未知 payload ignore（6）
  - webhook：无密钥 403 / 无效签名 403 / GitHub HMAC 200 同步 / GitLab token 200（4）
  - API：成员 append+list / 非成员 403 / 编辑 / 草稿确认 / MR 列表（5）
  - packer：非成员零召回 / 聚合记忆+工件 / token 预算降级裁剪低优层 / RetrievalTrace 写入（4）
  - chat 召回：白名单含 3 工具 / 绑定成员注入 / 非成员不注入 fail-closed / 未绑定不注入（4）
- **全量后端**：**6390 passed / 38 failed（==Phase-76 baseline，零新增回归）/ 61 skipped / 8 xfailed / 26 deselected**（~425s）。
  - 唯一新增失败 `test_enum_has_all_22_values` 是 `memory_distill` 合法新增导致的基准更新（22→23），已同步修正测试为 23（属规范内变更，非回归）。
  - `test_webhook_dedup_same_sha` = prompt 明示的已知 flaky cross-suite ordering（单跑通过，已验证），属 baseline。
- chat/agents/audit 套件单独跑 **347 passed** 全绿（chat_runner 广用面零回归）。
- `makemigrations --check --dry-run` 干净（`No changes detected`）。

## 偏差 / caveats

- MR webhook 触发用户固定 `system`（无 git 平台账号 ↔ Friday 用户映射；决策允许 "mapped 或 system"）。
- webhook 仓库匹配为 best-effort（按 git_url 归一化）；未匹配时 MR `repository`/`project` 留空（仍可见、仍同步状态），项目级关联待 Phase 81 前端/Cursor 回流补全。
- 真实 GitHub/GitLab webhook 端到端 MR 状态同步人工验收为里程碑级 deferred。
- 富前端（记忆编辑器 / 召回结果 / LLM 提议确认 UI）按 CONTEXT 留 Phase 81（UI-02/03）；本期仅后端 + REST + chat 接入。
