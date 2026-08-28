---
phase: 144
slug: capture
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-08-28
---

# Phase 144 — Validation Strategy

> 仓库召回与 Capture 回放的 Nyquist 合同。Wave 0 tracer、Plans 02–05 实现与跨面契约均已落地；Plan 05 最终门禁为 server 163 项、npm 14 项与改动 Python 文件 ruff 全绿，Phase 144 已验证。

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 + pytest-django + pytest-asyncio（`asyncio_mode=auto`）；npm 面 vitest（`mcp/package.json` `test`: `vitest run`） |
| **Config file** | `server/pyproject.toml` `[tool.pytest.ini_options]`；mcp 无独立 vitest config |
| **Quick run command** | `cd server && uv run pytest tests/knowledge/test_vector_recall.py tests/mcp_tools/test_lookup_project_by_branch.py tests/mcp_tools/test_retrieval_trace.py -q --tb=short` |
| **Full suite command** | `cd server && uv run pytest tests/knowledge/test_vector_recall.py tests/knowledge/test_retrieval.py tests/knowledge/test_session_capture_retrieval.py tests/mcp_tools/test_search_session_knowledge.py tests/mcp_tools/test_get_session_capture.py tests/mcp_tools/test_get_session_capture_schema_pending.py tests/mcp_tools/test_lookup_project_by_branch.py tests/mcp_tools/test_retrieval_trace.py tests/mcp_tools/test_report_session_knowledge.py tests/mcp_tools/test_mcp_package_alignment.py tests/mcp_tools/test_schema_snapshot.py tests/agents/tools/test_search_session_knowledge.py tests/services/test_project_context_packer.py tests/initiatives/test_capture_service.py tests/initiatives/test_capture_access.py tests/knowledge/test_session_capture_source.py -q --tb=short` |
| **npm command** | `cd mcp && npm test -- tests/server.test.ts` |
| **Measured runtime** | per-task 6 项授权测试 35.29s；phase full 281.80s；npm 契约 0.20s |

默认 `addopts` 含 `--disable-socket` 与 `-m 'not postgres_queue'`。LLM / Qdrant / embedding 一律 mock；不连真实 Qdrant。无新运行时依赖；不新建 collection。

---

## Sampling Rate

- **After every task commit:** 该任务 `<automated>`（窄 pytest `-x` 或 npm 单文件；禁止用 full suite 当 per-task 反馈）
- **After Wave 0:** 新 RED 文件 `--collect-only`，并跑 npm command 确认现有 52 工具全绿
- **After Plan 02/03:** 各自窄 pytest；不运行尚未实现的 MCP search/get RED
- **After Plan 04:** search/lookup 相关 pytest + 完整 snapshot/package alignment + npm command，恰好 53 工具全绿；排除 get-only pending RED
- **After Plan 05 / phase gate:** Full suite command 上表 + npm command，恰好 54 工具全绿
- **Before `$gsd-verify-work`:** Full suite + npm 必须全绿；触及的生产文件过 ruff
- **Measured feedback latency:** 单文件授权门禁 35.29s；phase full 仅在 Plan 05 最终门禁执行

---

## Per-Task Verification Map

威胁编号对应 RESEARCH Security Domain：T-144-01 IDOR/404 防枚举；T-144-02 Ledger 拼原文；T-144-03 向量跨项目泄漏；T-144-04 Trace 含 query/正文；T-144-05 默认分支错误项目注入；T-144-06 观测失败变 500。MCP-03 延续为新工具三面 schema 对齐（不扩大历史工具字段门禁）。

Plan 列在计划落地前按需求簇占位为 `01`；planner 拆 PLAN.md 后可改 Plan/Wave 列，**不得删除 Automated Command 或把行为改成仅人工**。

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 144-01-01 | 01→02 | 0→1 | RECALL-01 | T-144-03 | `source_kinds=["session_capture"]` 时 Qdrant `must` 含 `source_kind` MatchAny；`source_kinds=None` 无该条件；`source_kinds=[]` embedding 前返回 `[]`；真实 `search_similar` 把 source_kinds 原样传给 recall | unit | `cd server && uv run pytest tests/knowledge/test_vector_recall.py tests/knowledge/test_retrieval.py -x` | ✅ | ✅ green |
| 144-01-01b | 02 | 1 | RECALL-01 | T-144-03 | 真实 `search_session_knowledge` helper 精确调用 `search_similar`：repo 单元素、project 可选单元素/None、DOCUMENT、include_document_kind、session_capture 闭集 | unit | `cd server && uv run pytest tests/knowledge/test_session_capture_retrieval.py -x` | ✅ | ✅ green |
| 144-01-02 | 01→04 | 0→2 | RECALL-01 | T-144-03 | 缺 `repository_id` / 空 query / `top_k` 越界 → 400；仓必填、`project_id` 仅为 AND 收窄；未授权仓 → 200 空 `results`；只返回 `source_kind=session_capture` | integration | `cd server && uv run pytest tests/mcp_tools/test_search_session_knowledge.py -x` | ✅ | ✅ green |
| 144-01-03 | 01→02 | 0→1 | RECALL-02 | — | packer `_layer_rag` 传 `project_ids=[当前项目]`、`include_document_kind=True`；**不** exclusive `source_kinds=["session_capture"]`；hydrate 后 `session_capture` 可进 RAG，既有 project_doc 等 DOCUMENT 仍可进 | unit | `cd server && uv run pytest tests/services/test_project_context_packer.py -x` | ✅ | ✅ green |
| 144-01-04 | 01→05 | 0→3 | RECALL-03 | T-144-01 / T-144-02 | 创建者 + 挂钩仍可见 → 200 含脱敏 `question`/`answer` allowlist；他用户 / 失 scope / 无行 → 同一 404 body；monkeypatch Ledger 查询抛错仍成功；禁止回放模块查 `ToolCallRecord`/`RetrievalTrace`；只读无状态推进 | integration | `cd server && uv run pytest tests/mcp_tools/test_get_session_capture.py -x` | ✅ | ✅ green |
| 144-01-05 | 01→03 | 0→1 | RECALL-04 | T-144-05 | `main`/`master`/`develop`/仓 `default_branch` + 唯一 `RepoAssociation` → `matched=false`、`context=""`、有 candidates、不调 packer；`feat/login-page` 第三源仍 `matched=true`；默认分支上显式 `ProjectBranch` 仍命中 | integration | `cd server && uv run pytest tests/mcp_tools/test_lookup_project_by_branch.py -x` | ✅ | ✅ green |
| 144-01-06 | 01→03 | 0→1 | RECALL-04 | T-144-05 | `branch_name=main` + 真实仓 + 唯一 association、未传 `project_id` → `accepted=true`、仓库 FK 在、`project_id is None`、reason 不是 `branch_unresolved`；写路径不调 lookup/packer | integration | `cd server && uv run pytest tests/mcp_tools/test_report_session_knowledge.py -x` | ✅ | ✅ green |
| 144-01-07 | 01→04 | 0→2 | OBS-03 | T-144-04 / T-144-06 | MCP 会话检索即使空命中也写一条 RetrievalTrace（`result_count=0`）；payload 仅标量/计数/分数/标识，无 query/title/text/question/answer/essence；`RetrievalTrace.objects.create` 抛错仍 HTTP 200 且业务结果不变 | unit | `cd server && uv run pytest tests/mcp_tools/test_search_session_knowledge.py tests/mcp_tools/test_retrieval_trace.py -x` | ✅ | ✅ green |
| 144-01-08 | 01→04 | 0→2 | OBS-03 | T-144-04 / T-144-06 | Chat `search_session_knowledge` 与 MCP 同过滤（必填 repo、AND project、共享 helper）；空命中 `result_count=0`；trace 无正文/query 且经 `redact_for_ledger`；`arecord_retrieval_trace` 抛错仍 `ToolResult.success=True` | unit | `cd server && uv run pytest tests/agents/tools/test_search_session_knowledge.py -x` | ✅ | ✅ green |
| 144-01-09a | 01 | 0 | MCP-03 延续 | — | Wave 0 保持 npm 52 工具并全绿；新行为测试仅 collectable RED；get-only snapshot RED 独立文件，不污染完整 snapshot | unit | `cd server && uv run pytest tests/mcp_tools/test_get_session_capture_schema_pending.py --collect-only -q && cd ../mcp && npm test -- tests/server.test.ts` | ✅ | ✅ green |
| 144-01-09b | 04 | 2 | MCP-03 延续 | — | 只加入 `search_session_knowledge`：完整 snapshot/package/npm 对齐且工具数 53；get-only RED 不纳入本波 verify | unit | `cd server && uv run pytest tests/mcp_tools/test_schema_snapshot.py tests/mcp_tools/test_mcp_package_alignment.py -q --tb=short && cd ../mcp && npm test -- tests/server.test.ts` | ✅ | ✅ green |
| 144-01-09c | 05 | 3 | MCP-03 延续 | — | 再加入 `get_session_capture`：完整 snapshot/package/npm 对齐且工具数 54；独立 get-only 契约转绿 | unit | `cd server && uv run pytest tests/mcp_tools/test_get_session_capture_schema_pending.py tests/mcp_tools/test_schema_snapshot.py tests/mcp_tools/test_mcp_package_alignment.py -q --tb=short && cd ../mcp && npm test -- tests/server.test.ts` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `server/tests/mcp_tools/test_search_session_knowledge.py` — RECALL-01 / OBS-03 MCP：缺仓库 400、AND `project_id`、未授权空结果、`source_kind` 闭集、空命中仍写 trace、trace 无正文、create boom 仍 200
- [x] `server/tests/mcp_tools/test_get_session_capture.py` — RECALL-03：创建者 200；他用户/无行/失挂钩 visibility 同 404；allowlist 无 `last_error`/`distilled_essence`/`question_hash`/client/CoT；Ledger 查询失败仍回放；无 enqueue/CAS
- [x] `server/tests/agents/tools/test_search_session_knowledge.py` — Chat 同过滤 + 无正文 RetrievalTrace + empty hits `result_count=0` + best-effort（也可扩 `test_knowledge_read_tools.py`，命令须指向实际文件）
- [x] 扩展 `server/tests/knowledge/test_vector_recall.py` — `source_kinds` MatchAny / `None` 零回归 / 空列表短路；断言真实 Qdrant filter shape，不只 helper kwargs
- [x] `server/tests/knowledge/test_retrieval.py` — Plan 02 直接调用真实 `search_similar`，精确断言 `source_kinds` 传给 `recall_similar_chunks`
- [x] `server/tests/knowledge/test_session_capture_retrieval.py` — Plan 02 直接调用真实 helper，精确断言完整 `search_similar` kwargs
- [x] 扩展 `server/tests/services/test_project_context_packer.py` — inclusion：`session_capture` 可出现且**不**排他过滤其它 DOCUMENT 源
- [x] 扩展 `server/tests/mcp_tools/test_lookup_project_by_branch.py` — 默认分支第三源 unmatched；`feat/login-page` 仍 matched；保留无 repository 的 `test_unparseable_branch_fail_soft`
- [x] 扩展 `server/tests/mcp_tools/test_report_session_knowledge.py` — 默认分支不绑项目、仓库 FK 仍接受
- [x] `server/tests/mcp_tools/test_get_session_capture_schema_pending.py` — get-only 独立 RED，不污染 Plan 04 的完整 snapshot
- [x] 分波冻结 MCP：Wave 0 npm=52 且全绿；Plan 04 加 search 后 npm=53 且完整 snapshot/package 全绿；Plan 05 加 get 后 npm=54 且独立 get-only 契约转绿
- [x] Framework install: 无 — 已有 pytest / vitest

既有 `mcp_client` / `access_user` fixture（`server/tests/mcp_tools/conftest.py`）与 `test_vector_recall.py` 的 hybrid mock 可复用。会话 MCP/Chat 必须委托同一 `search_session_knowledge` helper，禁止各写一套 Qdrant filter。

---

## Manual-Only Verifications

All phase behaviors have automated verification. Vue Capture 回放工作台不在本阶段范围。

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verification or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verification
- [x] Wave 0 covers all missing references
- [x] No watch-mode flags
- [x] Measured feedback latency recorded; full suite reserved for final phase gate
- [x] `nyquist_compliant: true` set in frontmatter after Wave 0 files exist and phase tasks are green

**Approval:** validated — 2026-08-28（server 163 passed；npm 14 passed；ruff passed）
