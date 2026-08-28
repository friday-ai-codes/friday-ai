---
phase: 144-capture
verified: 2026-08-28T12:42:00Z
status: passed
score: 6/6 must-haves verified
overrides_applied: 0
re_verification: false
---

# Phase 144: 仓库召回与 Capture 回放 Verification Report

**Phase Goal:** 授权用户能按仓库或项目找回中高价值会话知识，并在需要时只读回放对应原始 Capture
**Verified:** 2026-08-28T12:42:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | 授权用户可按 `repository_id` 检索已入图会话知识；可选 `project_id` 只做 AND 收窄（RECALL-01） | ✓ VERIFIED | `SearchSessionKnowledgeRequestSerializer` 必填 `repository_id`；helper `search_session_knowledge` 传 `repository_ids=[rid]`、`project_ids=[pid] or None`、`source_kinds=["session_capture"]`。MCP 未授权仓 200 空 `results`。Chat 同 helper。pytest：`test_search_session_knowledge.py`、`test_session_capture_retrieval.py`、`test_retrieval.py`、`test_vector_recall.py` 全绿。 |
| 2 | `pack_project_context` 与交付知识检索纳入 `session_capture`，且不 exclusive 过滤其它 DOCUMENT（RECALL-02） | ✓ VERIFIED | `_layer_rag` 传 `project_ids=[str(project_id)]`、`include_document_kind=True`，不传 `source_kinds=["session_capture"]`。`SearchDeliveryKnowledgeView` 同样 `include_document_kind=True` 且默认 `source_kinds=None`。`test_rag_layer_includes_session_capture_without_excluding_project_docs` 通过。 |
| 3 | 创建者且挂钩仍可见时可按 Capture UUID 只读回放；不存在/未授权同一 404；正文只来自 SessionCapture，不读 Ledger（RECALL-03） | ✓ VERIFIED | `aget_readable_capture` 创建者 ∩ `resolve_allowed_*`，非创建者一律 `None`。`GetSessionCaptureView` 从 Capture 字段白名单构造响应，无 `client`/`last_error`/`distilled_essence`。404 `not_found`/`资源不存在`。`capture_access.py` 无 ToolCallRecord/RetrievalTrace。pytest：`test_get_session_capture.py`、`test_capture_access.py` 全绿。 |
| 4 | 默认分支第三源不 `matched=true`；feat 第三源仍可匹配；写路径不因仓关联绑项目（RECALL-04） | ✓ VERIFIED | `is_default_branch` 精确匹配 `main`/`master`/`develop` 与仓 `default_branch`。Lookup 第三源 skip 设 `binding_source=repo_association_skipped_default_branch`、不 `pack_project_context`。`feat/login-page` 仍 matched。`ReportSessionKnowledgeView` 不调用 lookup，只透传显式 `project_id`。lookup/report 相关测试全绿。 |
| 5 | MCP 与 Chat 空命中也写脱敏 RetrievalTrace；观测失败不改变检索结果（OBS-03） | ✓ VERIFIED | MCP `_record` 始终一条 CHUNK，payload 闭集 source/repository_id/project_id/source_kind/result_count/scores/top_score/duration_ms。Chat `source=chat_search_session_knowledge` 经 `_record_chat_retrieval` → `arecord_retrieval_trace`（`redact_for_ledger` + create 失败吞掉）。create boom 仍 HTTP 200 / `ToolResult.success=True`。 |
| 6 | `search_session_knowledge` 与 `get_session_capture` 使 MCP 工具面为 54，serializer/snapshot/npm/URL 对齐 | ✓ VERIFIED | urls 登记两路由；`TOOL_SCHEMA_SNAPSHOT` 含两键；`mcp/src/tools.ts` + vitest `toHaveLength(54)`。`test_schema_snapshot.py`、`test_mcp_package_alignment.py`、`test_get_session_capture_schema_pending.py` 与 npm 14 项通过。 |

**Score:** 6/6 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/knowledge/vector_recall.py` | `source_kinds` MatchAny + `[]` 短路 | ✓ VERIFIED | `_build_knowledge_must_filter` 追加 `source_kind` MatchAny；`recall_similar_chunks` 在 embed 前 `if source_kinds == []: return []` |
| `server/knowledge/retrieval.py` | `source_kinds` 原样透传到 recall | ✓ VERIFIED | `search_similar(..., source_kinds=source_kinds)` |
| `server/knowledge/session_capture_retrieval.py` | 共享 helper | ✓ VERIFIED | 导出 `search_session_knowledge`；固定 DOCUMENT + include_document_kind + session_capture 闭集 |
| `server/services/project_context_packer.py` | RAG inclusion | ✓ VERIFIED | `_layer_rag` 收窄 `project_ids`，不 exclusive source_kinds |
| `server/services/branch_parsing.py` | `is_default_branch` | ✓ VERIFIED | 导出；大小写敏感；空名 False |
| `server/mcp_tools/views.py` | Search/Get/Lookup 守卫 | ✓ VERIFIED | `SearchSessionKnowledgeView`、`GetSessionCaptureView`、第三源 skip |
| `server/initiatives/services/capture_access.py` | `aget_readable_capture` | ✓ VERIFIED | select_related get；无 objects.create |
| `server/agents/tools/knowledge_read_tools.py` | Chat 薄封装 | ✓ VERIFIED | 委托 helper；挂 `_INDEXED_TOOL_NAMES` 不挂 `_PROJECT_READ_TOOL_NAMES` |
| `mcp/src/tools.ts` | 两只读工具 | ✓ VERIFIED | query annotations；required 分别含 repository_id+query / capture_id |
| Wave 0 测试文件 | 契约可收集且现已绿 | ✓ VERIFIED | MCP/Chat/向量/packer/lookup/report/schema 测试均存在且本轮 163 通过 |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | --- | --- | ------ | ------- |
| `retrieval.py` | `recall_similar_chunks` | `source_kinds=source_kinds` | WIRED | 关键字参数原样传递 |
| `session_capture_retrieval.py` | `DeliveryKnowledgeSearchService.search_similar` | `source_kinds=["session_capture"]` | WIRED | 三件套 filter 齐全 |
| `SearchSessionKnowledgeView.post` | `search_session_knowledge` helper | `await` | WIRED | 权限闸后再调 helper |
| `SearchSessionKnowledgeView.post` | `McpToolView._record` | 一条 CHUNK payload | WIRED | 空结果仍 record |
| Chat `search_session_knowledge` | `_record_chat_retrieval` | `chat_search_session_knowledge` | WIRED | 空命中仍写 |
| `GetSessionCaptureView.post` | `aget_readable_capture` | None → 404 | WIRED | 成功路径只读 Capture 字段 |
| `capture_access.py` | `SessionCapture.objects` | filter+afirst | WIRED | 无 create/update/delete |
| `LookupProjectByBranchView.post` | `is_default_branch` | 第三源 pack 之前 | WIRED | skip 不进入 `len(projects)==1` pack 分支 |
| `project_context_packer._layer_rag` | `search_similar` | `project_ids=` | WIRED | inclusion，非 exclusive |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| MCP search view | `results` | helper → `search_similar` → Qdrant filter（测试 monkeypatch 边界） | 是（服务真实调用链；向量层 mock） | ✓ FLOWING |
| Chat tool | `serialized` | 同一 helper | 是 | ✓ FLOWING |
| Get capture view | `output_data.question/answer` | `SessionCapture` 行字段 | 是；Ledger 不参与正文 | ✓ FLOWING |
| Packer RAG | `lines` | `search_similar` DTO title/score | 是；含 session_capture 与其它 document | ✓ FLOWING |
| Lookup skip | `matched`/`context` | 默认分支不写入 merged | 候选可来自 association，context 保持 `""` | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Phase 144 server suite | `cd server && uv run pytest`（VALIDATION Full suite 文件列表） | 163 passed（清掉陈旧 `test_friday` 后） | ✓ PASS |
| MCP npm 54 工具 | `cd mcp && npm test -- tests/server.test.ts` | 14 passed，`FRIDAY_TOOLS` length 54 | ✓ PASS |

首次 pytest 因远程 Postgres 上残留 `test_friday` 在 `post_migrate` 撞 `django_content_type` UniqueViolation（9 passed / 154 errors）。删除 `test_friday` 后复跑与 Plan 05 宣称的 163 一致。该失败属测试库脏状态，不是生产缺口。

### Probe Execution

| Probe | Command | Result | Status |
| ----- | ------- | ------ | ------ |
| — | — | Phase 144 PLAN/SUMMARY 未声明 `probe-*.sh` | SKIPPED |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| RECALL-01 | 01/02/04 | 按仓检索；项目 AND 收窄 | ✓ SATISFIED | helper + MCP/Chat + source_kinds MatchAny |
| RECALL-02 | 02 | packer/交付检索纳入 session_capture | ✓ SATISFIED | inclusion，非 exclusive frozenset |
| RECALL-03 | 01/05 | Capture id 只读回放，不扫 Ledger | ✓ SATISFIED | capture_access + GetSessionCaptureView |
| RECALL-04 | 01/03 | 默认分支不误绑项目 | ✓ SATISFIED | lookup skip + report 不调 lookup |
| OBS-03 | 01/04 | 双链 RetrievalTrace best-effort | ✓ SATISFIED | MCP `_record` + Chat `_record_chat_retrieval` + ledger 吞 create 失败 |

无 ORPHANED：REQUIREMENTS.md 映射到 Phase 144 的 ID 均被计划覆盖。SKILL-* 属 Phase 145，不在本阶段。

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| `server/tests/mcp_tools/test_get_session_capture_schema_pending.py` | 文件名 | 仍含 `pending` | ℹ️ Info | 内容已转绿独立契约；命名遗留，不阻断目标 |
| `server/knowledge/session_capture_retrieval.py` 等生产文件 | — | 无 TBD/FIXME/XXX | — | 债务标记门通过 |

**Confirmation-bias notes（不构成 gap）：**

1. RECALL-02「显式纳入」实现为 `source_kinds=None` + `include_document_kind=True` 的 inclusion，而不是独立 frozenset 白名单——与 144-02 PLAN 已决议一致。
2. `GetSessionCaptureView` 在 404 路径不调用 `_record`（防枚举、不把未授权 UUID 写入工具 Ledger）；授权成功仍走 MCP 基类 `_record`。正文来源仍只有 SessionCapture。
3. 向量命中依赖 mock，未连真实 Qdrant；filter shape 由 `test_vector_recall.py` 断言。

### Human Verification Required

无。本阶段验收面为 MCP/Chat/向量 filter/授权 API，已由 pytest + vitest 覆盖。无 Vue 回放页；宿主采集属 Phase 145。

### Gaps Summary

无阻断缺口。Phase 144 目标在代码与门禁测试中成立。

---

_Verified: 2026-08-28T12:42:00Z_
_Verifier: Claude (gsd-verifier)_
