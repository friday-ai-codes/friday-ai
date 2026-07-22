---
phase: 102-knowledge-consumption
plan: 02
subsystem: chat-knowledge-tools
tags: [chat-tools, knowledge, retrieval-trace, project-state-api, know-05, know-06]
requires:
  - "Phase 100：mcp_tools.learning_case_service.search_learning_cases 向量版定版（user kwarg，fail-soft）"
  - "Phase 85：project_doc 物化 + 摄取管线（_schedule_materialization / normalizer / content_hash 短路）"
provides:
  - "Chat 白名单三个知识读工具：search_learning_cases（_INDEXED）、search_project_context / read_project_doc（_PROJECT_READ）"
  - "三工具权限 fail-closed（会话 owner / bound_project 成员或 public_org），零泄漏"
  - "Chat 链召回写 RetrievalTrace（conversation_id 关联、source=chat、best-effort）"
  - "KNOW-06 断链修复：upsert_state_api 后调度 STATE 文档物化；normalizer STATE 文档追加 live「METHOD path — status」API 清单行"
affects:
  - "Chat 对话：LLM 可主动检索历史任务经验 / 项目沉淀 / 工作区文档"
  - "search_project_context（MCP 与 Chat 两链）：IDE 上报的 API 清单入向量库后可命中"
tech-stack:
  added: []
  patterns:
    - "薄封装工具：@tool + ToolResult + 权限前置 fail-closed + service 转调 + 埋点，不写新业务逻辑"
    - "trace helper 整体 try/except 吞异常（best-effort，绝不反噬对话主流程）"
    - "normalizer live 内容追加：snapshot 人工区保留 + live 表查询拼接，拼接后全文脱敏"
key-files:
  created:
    - server/agents/tools/knowledge_read_tools.py
    - server/tests/agents/tools/test_knowledge_read_tools.py
    - server/tests/initiatives/test_state_api_materialize_hook.py
  modified:
    - server/agents/chat_runner.py
    - server/initiatives/services/project_doc_service.py
    - server/knowledge/sources/project_doc.py
    - server/tests/knowledge/test_project_doc_source.py
decisions:
  - "search_learning_cases 底层函数在工具函数内延迟 import（避免 agents ↔ mcp_tools 模块级 import 环）；测试 patch 源模块 mcp_tools.learning_case_service.search_learning_cases（按 plan 备选口径）"
  - "trace kind 用字符串字面量 chunk/file（与 RetrievalTrace.Kind TextChoices 值一致），避免模块级引入 interactions.models"
  - "normalizer live API 行直查 ProjectStateApi 表（get_doc_render 的 rendered_markdown 来自 snapshot 缓存，不能作 live 来源）；行数上限 500 防极端膨胀"
  - "验收链测试断言到「摄取内容包含 API 清单」这一确定性环节（CI 无 Qdrant 的诚实边界），向量入库与检索命中由既有 ingestion/search_similar 测试覆盖"
metrics:
  duration: "~12 分钟"
  completed: "2026-07-22"
---

# Phase 102 Plan 02: Chat 知识读工具 + ProjectStateApi 断链修复（KNOW-05/06）Summary

Chat 白名单新增三个薄封装知识读工具（search_learning_cases / search_project_context / read_project_doc，权限 fail-closed + Chat 链 RetrievalTrace），并修复 ProjectStateApi 不可检索断链——upsert_state_api 成功后调度 STATE 文档物化 + normalizer 对 STATE 文档追加 live「METHOD path — status」API 清单行（不建第二通路，INV-6 单一摄取入口）。

## Tasks

| Task | 内容 | Commit |
| --- | --- | --- |
| 1 | 新建 knowledge_read_tools.py：三个薄封装工具 + trace helper | cdb7a253 |
| 2 | chat_runner 白名单接线（_INDEXED / _PROJECT_READ + import 注册）+ 工具行为测试 | 19ff6302 |
| 3 | KNOW-06 断链修复：upsert 物化钩子 + normalizer STATE live 内容 | 0ce3c3de |
| 4 | KNOW-06 验收测试：上报→物化调度→物化内容命中链 | b7cfc8cf |

## 验证结果

- `uv run pytest tests/agents/tools/test_knowledge_read_tools.py tests/initiatives/test_state_api_materialize_hook.py tests/knowledge/test_project_doc_source.py tests/mcp_tools/test_report_project_state.py tests/agents/tools/test_delivery_knowledge_tools.py -q`：**33 passed**（新增 17 + 回归 16 全绿）。
- `uv run pytest tests/test_chat_project_recall.py -q`：8 passed（chat 白名单守护不回归）。
- `uv run pytest tests/initiatives/test_doc_sync_inv6_guard.py -x -q`：通过（INV-6 无旁路写表）。
- `uv run ruff check agents/tools/knowledge_read_tools.py agents/chat_runner.py initiatives/services/project_doc_service.py knowledge/sources/project_doc.py`：干净。
- Task 1 python -c 验证（含 django.setup()，按 plan 修订注记逐字执行）：三工具进 _tool_registry。

## 观测埋点（自检清单）

- 三工具各发 `<tool>_done` 结构化事件（category=caller, component=agents.tools, duration_ms）。
- Chat 链召回写 RetrievalTrace（kind=chunk/file，payload 只记计数/score/耗时/维度键，不记召回正文，T-102-07）；conversation_id + source=chat 关联；best-effort 吞异常。
- normalizer `project_doc_rag_normalize_completed` 事件补 `state_api_count` kv（category/component 既有值不变）。
- 脱敏不可绕过：STATE live API 行拼接后全文过 `redact_secrets_in_text` 才入图（T-102-06）。

## Deviations from Plan

None - plan executed exactly as written.

（实现口径说明，非偏差：search_learning_cases 底层函数为函数内延迟 import，测试按 plan 括注的备选口径 patch `mcp_tools.learning_case_service.search_learning_cases`；trace kind 用与 `RetrievalTrace.Kind` 等值的字符串字面量。）

## Known Stubs

无。三工具全部接真实 service；normalizer live 查询接真实 ProjectStateApi 表。

## Threat Flags

无新增计划外安全面：三工具权限沿 T-102-05 mitigation（fail-closed 双前置 + search_similar resolve_allowed_project_ids 二次收口）；normalizer 拼接内容按 T-102-06 全文脱敏；trace payload 按 T-102-07 不记正文；upsert 批量调度按 T-102-08 靠 content_hash 短路幂等。

## Self-Check: PASSED

- server/agents/tools/knowledge_read_tools.py — FOUND
- server/tests/agents/tools/test_knowledge_read_tools.py — FOUND
- server/tests/initiatives/test_state_api_materialize_hook.py — FOUND
- commits cdb7a253 / 19ff6302 / 0ce3c3de / b7cfc8cf — FOUND
