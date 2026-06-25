---
phase: 80
title: 项目记忆 + MR 实体 + 上下文召回接入 Web 会话
milestone: v0.15.0
status: passed
verified: 2026-06-26
requirements: [MEM-01, MEM-02, MEM-03, MEM-04, RECALL-01, RECALL-02, RECALL-03, MR-01, MR-02]
---

# Phase 80 VERIFICATION — 5 条 Success Criteria 逐条核验

> 方法：goal-backward——每条 Success Criteria 映射到代码落点 + 守护测试证据。
> 全量后端 6390 passed / 38 failed（== Phase-76 baseline，零新增回归）/ makemigrations 干净。

## SC-1 — 项目记忆成员共享 + 贡献限成员（fail-closed）+ 人工编辑可追溯

**status: passed**

- 落点：`ProjectMemory`（active/superseded）+ `ProjectMemoryRevision`（append-only 历史快照）；
  `MemoryService.append/edit/supersede`（INV-6 单一写入），`edit` 每次 append revision 保留历史。
- MEM-02 fail-closed：`MemoryService._assert_member` —— 非 `ProjectMember` 抛 `MemoryPermissionError`；
  私聊/未绑定项目会话无 project 不进入。
- 证据：`tests/initiatives/test_memory_service.py`（`test_edit_preserves_history_via_revisions` 验证编辑后
  revision=2 且历史内容均可回溯；`test_non_member_cannot_contribute_fail_closed`；`test_supersede_marks_status`）+
  `test_memory_inv6_guard.py`（旁路写表零命中）+ `test_memory_mr_api.py`（成员 append/edit、非成员 403）。

## SC-2 — LLM 提炼草稿人工确认入库（不自动写）+ 入库前脱敏不可绕过

**status: passed**

- 落点：`MemoryDistiller.distill_to_draft` → `MemoryService.create_draft`（**pending，绝不自动写 active**）；
  `confirm_draft` 人工确认才 `append` 入库。入库经 `redact_secrets_in_text`（蒸馏 + create_draft 双重脱敏）。
  蒸馏赋 `call_source="memory_distill"` + `arecord_llm_usage`（token/TTFT/上游错误码）。
- 证据：`tests/initiatives/test_memory_distill.py`（`test_distill_produces_pending_draft_only` 验证产草稿后
  active 记忆数=0；`test_distill_redacts_secret_before_store`；`test_distill_none_candidate_no_draft`；
  `test_distill_non_member_fail_closed`；`test_memory_distill_call_source_in_enum`）+
  `test_memory_service.py`（`test_draft_create_confirm_enters_active_memory` / `test_draft_reject_does_not_create_memory`）。

## SC-3 — MergeRequest 实体经单一入口 + 入站 webhook 同步（脱敏 payload）+ 项目内可见

**status: passed**

- 落点：`MergeRequest` 实体（initiatives）+ `MergeRequestService.upsert/sync_from_webhook`（INV-6）；
  入站 webhook `GitMergeRequestWebhookView`（共享密钥 fail-closed）→ 原始 payload `redact_for_ledger` 后落
  `MergeRequestEvent`（append-only，幂等 dedup_key）+ `InboundWebhookEvent`；`GET /api/projects/<id>/merge-requests/` 项目内可见。
- 证据：`tests/initiatives/test_merge_request_service.py`（open→merged/review 状态推进、幂等 dedup、raw payload 脱敏、未知 payload ignore）+
  `test_git_webhook.py`（无密钥 403 / 无效签名 403 / GitHub HMAC 200 / GitLab token 200）+
  `test_merge_request_inv6_guard.py` + `test_memory_mr_api.py::test_merge_request_list`。

## SC-4 — context packer（聚合 + grep + RAG + 排序 + 压缩 + token 预算可降级）

**status: passed**

- 落点：`services/project_context_packer.py::pack_project_context` —— 分层聚合（记忆/需求/工件/关联知识/历史）+
  grep(SQL 精确) + RAG(语义 `DeliveryKnowledgeSearchService`) + 按优先级 + score 排序 + 压缩 +
  token 预算超限按优先级裁剪低优层（记忆/需求 > 工件 > 知识/RAG > 历史）。
- 证据：`tests/services/test_project_context_packer.py`（`test_aggregates_memory_and_artifacts`；
  `test_token_budget_degradation_trims_low_priority` 验证 degraded=True 且 memory 保留/history 被裁剪）。

## SC-5 — Web 对话绑定项目自动加载上下文 + search_delivery_knowledge 接入白名单 + 召回 fail-closed + RetrievalTrace

**status: passed**

- 落点：`Conversation.bound_project` FK（区别于 space）；`chat_runner._INDEXED_TOOL_NAMES` 增
  `search_delivery_knowledge`/`get_entity_timeline`/`get_related_entities`；`build_sdk_config` 经
  `_maybe_pack_project_context` 自动注入项目上下文，**非成员 fail-closed 零注入**；packer 写 `RetrievalTrace`
  （条数/分层耗时/score，source=`chat_project_context`）。
- 证据：`tests/test_chat_project_recall.py`（`test_delivery_knowledge_tools_in_chat_whitelist`；
  `test_bound_project_member_context_injected`；`test_bound_project_non_member_no_injection_fail_closed`；
  `test_unbound_conversation_no_injection`）+ `test_project_context_packer.py::test_non_member_zero_recall_fail_closed` /
  `test_retrieval_trace_written`。

## 总判定

**status: passed** —— 5 条 Success Criteria 全部 TRUE，证据齐备；零新增回归（38 failed == baseline）；
makemigrations 干净。里程碑级人工验收（真实 GitHub/GitLab webhook E2E、真实 LLM 蒸馏质量）deferred。
