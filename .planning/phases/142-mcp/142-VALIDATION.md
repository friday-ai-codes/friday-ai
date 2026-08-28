---
phase: 142
slug: mcp
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-28
---

# Phase 142 — Validation Strategy

> Per-phase validation contract for `report_session_knowledge` MCP 契约接线。挂钩矩阵仍以 Phase 141 `test_capture_service.py` 为准，本阶段只锁 HTTP 接受语义、三面字段与旧工具零回归。

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ≥9.0.2 + pytest-django + pytest-asyncio；npm 面 vitest 4（`mcp/package.json` `test`: `vitest run`） |
| **Config file** | `server/pyproject.toml` `[tool.pytest.ini_options]`；mcp 无独立 vitest config（`mcp/package.json` scripts） |
| **Quick run command** | `cd server && uv run pytest tests/mcp_tools/test_report_session_knowledge.py tests/mcp_tools/test_schema_snapshot.py tests/mcp_tools/test_mcp_package_alignment.py tests/mcp_tools/test_report_project_knowledge.py tests/initiatives/test_capture_inv6_guard.py -q --tb=short` |
| **Full suite command** | `cd server && uv run pytest tests/mcp_tools/ tests/initiatives/test_capture_service.py tests/initiatives/test_capture_inv6_guard.py tests/initiatives/test_memory_inv6_guard.py -q --tb=short` |
| **npm command** | `cd mcp && npm test -- tests/server.test.ts` |
| **Estimated runtime** | contract quick（schema + alignment + npm）<30s；full ~120s |

`addopts` 已排除 `perf`/`integration`/`slow`/`postgres_queue`。MCP 写库 + async 用 `pytest.mark.django_db(transaction=True)`（见 `test_report_project_knowledge.py`）。npm 契约以 Python 读 `mcp/src/tools.ts` 为 SSOT；vitest 锁 `FRIDAY_TOOLS` 长度（51→52）与 `report_session_knowledge` 名存在。

---

## Sampling Rate

- **After every task commit:** 该任务 `<verify><automated>` 命令（Plan 04 Task 1 的 contract quick 须 <30s）
- **After MCP-03 npm 白名单变更:** 另跑 `cd mcp && npm test -- tests/server.test.ts`
- **After every plan wave:** Run `cd server && uv run pytest tests/mcp_tools/ tests/initiatives/test_capture_service.py tests/initiatives/test_capture_inv6_guard.py tests/initiatives/test_memory_inv6_guard.py -q --tb=short`
- **Before `$gsd-verify-work`:** Full suite must be green；`test_report_project_knowledge.py` 全文件不得漏跑
- **Max feedback latency:** 30 seconds（Plan 04 Task 1 contract quick）

---

## Per-Task Verification Map

计划尚未落地；下表按 ROADMAP MCP-01..04 与 RESEARCH 推荐任务切分预映射。Wave 0 任务在实现前应为 RED；`File Exists` 标 ❌ W0 的用例必须先写入测试文件。

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 142-01-01 | 01 | 0 | MCP-01 | T-142-01 / T-142-06 | 认证用户 POST 非空 Q/A（可选元数据全集）→ HTTP 200、`accepted=true`、DB 有 Capture 行可证 `capture_id`；成功不声称已挂钩或已入 RAG | integration | `cd server && uv run pytest tests/mcp_tools/test_report_session_knowledge.py::test_member_report_persists_capture -x` | ❌ W0 | ⬜ pending |
| 142-01-02 | 01 | 0 | MCP-01 | T-142-01 | 缺 `question` 或 `answer`（含 blank）→ 400 `invalid_params`，无 Capture 行 | integration | `cd server && uv run pytest tests/mcp_tools/test_report_session_knowledge.py::test_missing_question_or_answer_400 -x` | ❌ W0 | ⬜ pending |
| 142-01-03 | 01 | 0 | MCP-01 | T-142-01 | 匿名 POST `/api/mcp/tools/report_session_knowledge/` → 401 `authentication_failed` | integration | `cd server && uv run pytest tests/mcp_tools/test_report_session_knowledge.py::test_missing_token_401 -x` | ❌ W0 | ⬜ pending |
| 142-01-04 | 01 | 0 | MCP-02 | T-142-03 / T-142-06 | 无 `project_id`/仓元数据 → 200 `accepted=true`，行存在，`reason=unanchored`；**不是** `branch_unresolved` | integration | `cd server && uv run pytest tests/mcp_tools/test_report_session_knowledge.py::test_unanchored_still_accepted -x` | ❌ W0 | ⬜ pending |
| 142-01-05 | 01 | 0 | MCP-02 | T-142-03 | 无法解析的 `git_url` → 200 `accepted=true`，`reason=repo_unresolved`，有 Capture 行 | integration | `cd server && uv run pytest tests/mcp_tools/test_report_session_knowledge.py::test_unresolved_repo_still_accepted -x` | ❌ W0 | ⬜ pending |
| 142-01-06 | 01 | 0 | MCP-02 | T-142-07 | 仅 `branch_name=main`（无 `project_id`）→ 200 `accepted=true`，`reason` 不是 `branch_unresolved` | integration | `cd server && uv run pytest tests/mcp_tools/test_report_session_knowledge.py::test_default_branch_does_not_mean_rejected -x` | ❌ W0 | ⬜ pending |
| 142-01-07 | 01 | 0 | MCP-02 | T-142-03 | 响应 `reason` 原样透传 persist `link_reason`（含 `repo_unauthorized` 等成功挂钩码）；挂钩失败仍 `accepted=true` | integration | `cd server && uv run pytest tests/mcp_tools/test_report_session_knowledge.py::test_link_reason_passthrough -x` | ❌ W0 | ⬜ pending |
| 142-01-08 | 01 | 0 | MCP-01, MCP-02 | T-142-05 | 同用户/session/question 重试 → 同一 `capture_id`，`idempotent_hit=true`，首次答案与挂钩原因不覆盖 | integration | `cd server && uv run pytest tests/mcp_tools/test_report_session_knowledge.py::test_idempotent_hit_keeps_first_write -x` | ❌ W0 | ⬜ pending |
| 142-01-09 | 01 | 0 | MCP-03 | — | Wave 0 同时落 serializer↔snapshot 与三面守卫（禁止全量 51 工具字段对齐）；Plan 02 T1 只绿前者，Plan 04 T1 才要求三面绿 | unit | `cd server && uv run pytest tests/mcp_tools/test_mcp_package_alignment.py::test_report_session_knowledge_serializer_matches_snapshot tests/mcp_tools/test_mcp_package_alignment.py::test_report_session_knowledge_request_keys_aligned -x` | ✅ | ✅ green |
| 142-01-10 | 01 | 0 | MCP-04 | T-142-07 | 新工具不增加 `ProjectMemory`、不调用 `MemoryService.append`；旧 `branch_unresolved` 未收语义保持在旧工具测试 | integration | `cd server && uv run pytest tests/mcp_tools/test_report_session_knowledge.py::test_session_tool_does_not_write_project_memory tests/mcp_tools/test_report_project_knowledge.py::test_unresolvable_branch_fail_soft -x` | ❌ W0 / ✅ | ⬜ pending |
| 142-01-11 | 01 | 0 | OBS-02 | T-142-02 | MCP 路径 persist 后 Capture 行不含明文 `sk-` 等密钥（persist 已测；本路径再钉一次） | integration | `cd server && uv run pytest tests/mcp_tools/test_report_session_knowledge.py::test_redaction_on_mcp_path -x` | ❌ W0 | ⬜ pending |
| 142-02-01 | 02 | 1 | MCP-03 | — | Task 1：serializer.fields == snapshot.request；snapshot 字面量含新工具全键；**不**跑 urls 名集、**不**跑三面 npm | unit | `cd server && uv run pytest tests/mcp_tools/test_schema_snapshot.py::test_mcp_read_tool_schema_snapshot tests/mcp_tools/test_mcp_package_alignment.py::test_report_session_knowledge_serializer_matches_snapshot -x` | ✅ | ✅ green |
| 142-02-02 | 02 | 1 | MCP-01 | T-142-01 / T-142-06 | Task 2：注册 URL 后 `test_registered_tools_match_snapshot`；HTTP 200/401/400 与 persist | integration | `cd server && uv run pytest tests/mcp_tools/test_report_session_knowledge.py tests/mcp_tools/test_schema_snapshot.py::test_registered_tools_match_snapshot tests/initiatives/test_capture_inv6_guard.py -x` | ❌ W0 | ⬜ pending |
| 142-03-01 | 03 | 1 | MCP-03 | — | 同任务同时加 `FRIDAY_TOOLS` 与 `TOOL_ANNOTATIONS`；长度 52、含名、`idempotentHint: true`；`server.test.ts` 独立绿 | unit | `cd mcp && npm test -- tests/server.test.ts` | ✅ | ✅ green |
| 142-04-01 | 04 | 2 | MCP-03 | — | 三面键相等 + urls/snapshot/npm 名集；contract quick <30s | unit | `cd server && uv run pytest tests/mcp_tools/test_schema_snapshot.py tests/mcp_tools/test_mcp_package_alignment.py -q --tb=short && cd ../mcp && npm test -- tests/server.test.ts` | ✅ | ✅ green（server 6 + npm 12，2.9s） |
| 142-04-02 | 04 | 2 | MCP-01..04 / STORE-03 | T-142-07 | 完整 `tests/mcp_tools/` + Capture/INV-6/Memory 回归；旧工具全绿；无 SessionCapture 旁路 create | regression | `cd server && uv run pytest tests/mcp_tools/ tests/initiatives/test_capture_service.py tests/initiatives/test_capture_inv6_guard.py tests/initiatives/test_memory_inv6_guard.py -q --tb=short` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `server/tests/mcp_tools/test_report_session_knowledge.py` — MCP-01/02/04 HTTP 契约：`test_member_report_persists_capture`、`test_missing_question_or_answer_400`、`test_missing_token_401`、`test_unanchored_still_accepted`、`test_unresolved_repo_still_accepted`、`test_default_branch_does_not_mean_rejected`、`test_link_reason_passthrough`、`test_idempotent_hit_keeps_first_write`、`test_session_tool_does_not_write_project_memory`、`test_redaction_on_mcp_path`
- [x] `server/tests/mcp_tools/test_mcp_package_alignment.py` — `test_report_session_knowledge_serializer_matches_snapshot`（serializer↔snapshot）与 `test_report_session_knowledge_request_keys_aligned`（三面；Plan 04 已验证为 green）
- [x] `server/tests/mcp_tools/test_schema_snapshot.py` 与 `TOOL_SCHEMA_SNAPSHOT` 同步加 `report_session_knowledge` 条目（非新文件；`test_registered_tools_match_snapshot` + `test_mcp_read_tool_schema_snapshot`）
- [x] `mcp/tests/server.test.ts` — 工具计数 51→52，并 `expect(names).toContain('report_session_knowledge')`
- [x] Framework install: 无 — 已有 pytest / vitest

既有 `mcp_client` / `access_user` fixture（`server/tests/mcp_tools/conftest.py`、`server/tests/conftest.py`）可复用。仓挂钩代表性路径复用 `repository` fixture + 把 user 放进 space（参考 `test_capture_service.py`）。**不要**在 MCP 合同里重复 141 全挂钩矩阵。

---

## Manual-Only Verifications

All phase behaviors have automated verification.

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 40s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
