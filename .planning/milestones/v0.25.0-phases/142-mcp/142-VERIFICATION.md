---
phase: 142-mcp
verified: 2026-08-28T09:32:00Z
status: passed
score: 6/6 must-haves verified
overrides_applied: 0
re_verification: false
---

# Phase 142: MCP 会话回写契约 Verification Report

**Phase Goal:** Cursor / Claude Code 可通过稳定的新 MCP 工具提交会话知识，任何挂钩失败都不影响 Capture 被接受
**Verified:** 2026-08-28T09:32:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

Goal-backward check starts from ROADMAP Success Criteria (MCP-01..04) plus PLAN-added truths that do not shrink that contract. SUMMARY.md claims were not treated as evidence.

### Observable Truths

| # | Truth | Status | Evidence |
| --- | ------- | ---------- | -------------- |
| 1 | 已认证用户可调用 `report_session_knowledge`，以必填 `question`/`answer` 和可选仓库、分支、会话、项目、模型、客户端字段获得 `accepted=true` 与 `capture_id` | ✓ VERIFIED | `ReportSessionKnowledgeView.post` 走 `_begin` → `_validate` → `CaptureService().persist` → HTTP 200 且 `accepted` 恒 True。`test_member_report_persists_capture` / `test_missing_token_401` / `test_missing_question_or_answer_400` / `test_client_metadata_is_accepted_and_audited` 本轮 `--reuse-db` 全绿。 |
| 2 | 无项目、仓库解析失败或默认分支无法唯一定位项目时，调用仍返回 200、`accepted=true` 并产生 Capture；`reason` 如实描述挂钩结果而不表示数据未收 | ✓ VERIFIED | 新 serializer **无** `project_id`/`branch_name` 门闩。测试：`unanchored`、`repo_unresolved`、仅 `branch_name=main` 仍 200/`accepted=true` 且 `reason != branch_unresolved`；`repo_unauthorized` 透传 `link_reason` 且 Capture 行存在、`repository_id` 为空。 |
| 3 | 服务端 serializer、`TOOL_SCHEMA_SNAPSHOT` 与 npm `mcp/src/tools.ts` 暴露同一工具契约，任一面漂移都会被自动化验收阻止 | ✓ VERIFIED | `test_report_session_knowledge_request_keys_aligned` 断言三面 request 键相等；独立 snapshot 字面量锁 12 请求键 + 7 响应键；npm `FRIDAY_TOOLS` 长度 52、`required: ['question','answer']`、专用 `idempotentHint: true`。vitest `tests/server.test.ts` 12 passed。 |
| 4 | 既有 `report_project_knowledge` 仍执行原有项目门闩与 git-diff 记忆路径，不会被扩成 Capture 入口或发生行为回退 | ✓ VERIFIED | `ReportProjectKnowledgeView` 仍调用 `_resolve_report_project_id`、`evaluate_writeback_quality`、`MemoryService`。`test_report_project_knowledge.py` 15 passed（含 `test_unresolvable_branch_fail_soft`、质量门、201 draft、active 路径）。新工具 `test_session_tool_does_not_write_project_memory` 证明不写 `ProjectMemory`、不 await `MemoryService.append`。 |
| 5 | `client` 作为公开可选请求字段被接受，并由 MCP `ToolCallRecord` 审计保留；不修改 `SessionCapture` / `CaptureService` 签名 | ✓ VERIFIED | serializer 开放 `CharField`；view **不**把 `client` 传入 `persist`（签名无 `client`）；`SessionCapture` 模型无 `client` 字段；`test_client_metadata_is_accepted_and_audited` 断言 `tool_call.input["client"]`。`git diff --exit-code` 对 `session_capture.py` / `capture_service.py` 为空。 |
| 6 | 新入口复用 `McpToolView` 生命周期且满足 SessionCapture INV-6（唯一 writer 仍是 `CaptureService`） | ✓ VERIFIED | `_begin`/`_validate`/`_record(..., traces=[])`；无 `SessionCapture.objects.create`。`test_capture_inv6_guard.py` 3 passed。npm `callFridayTool` 通用 POST `{baseUrl}/api/mcp/tools/${toolName}/`，白名单含新工具名即可到达 Django 路由。 |

**Score:** 6/6 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | ----------- | ------ | ------- |
| `server/tests/mcp_tools/test_report_session_knowledge.py` | MCP-01/02/04 HTTP 契约 | ✓ VERIFIED | 16 tests passed（含 parametrize 400 用例） |
| `server/tests/mcp_tools/test_mcp_package_alignment.py` | 三面 request 键守卫 | ✓ VERIFIED | serializer↔snapshot 与三面相等均绿 |
| `server/tests/mcp_tools/test_schema_snapshot.py` | 独立 snapshot 字面量 | ✓ VERIFIED | 含 `report_session_knowledge` 12+7 键 |
| `mcp/tests/server.test.ts` | npm 可发现性与 annotations | ✓ VERIFIED | 12 passed；length 52；四 hint 精确匹配 |
| `server/mcp_tools/serializers.py` | `ReportSessionKnowledgeRequestSerializer` + snapshot | ✓ VERIFIED | L1–L3 通过。工作树另有无关 2 行 snapshot 脏改动（他工具 `space_id`/`blueprint_project_id`），未破坏本工具键集 |
| `server/mcp_tools/views.py` | `ReportSessionKnowledgeView` | ✓ VERIFIED | 仅 persist + `_record`；挂钩失败不改 `accepted` |
| `server/mcp_tools/urls.py` | `tools/report_session_knowledge/` | ✓ VERIFIED | `ReportSessionKnowledgeView.as_view()` |
| `mcp/src/tools.ts` | 第 52 个工具 + 专用 annotations | ✓ VERIFIED | description 区分已收 Capture 与知识库/RAG |
| `.planning/phases/142-mcp/142-VALIDATION.md` | phase gate 台账 | ✓ VERIFIED | 存在；本报告以独立跑测为准，不采信其自述计数 |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | --- | --- | ------ | ------- |
| `test_report_session_knowledge.py` | `SessionCapture` | `capture_id` DB get | WIRED | `_capture(body["capture_id"])` 命中真实行 |
| `test_report_session_knowledge.py` | `ToolCallRecord` | `_record` + client | WIRED | `tool_name="report_session_knowledge"` 且 `input["client"]` |
| `test_mcp_package_alignment.py` | `mcp/src/tools.ts` | properties 解析 | WIRED | `_package_request_keys("report_session_knowledge")` |
| `views.py` | `CaptureService.persist` | 显式 `actor`/`initiated_by_user_id` | WIRED | 不传 `client` |
| `views.py` | ledger/metrics | `self._record` | WIRED | `traces=[]` |
| `urls.py` | `views.py` | `as_view()` | WIRED | path `tools/report_session_knowledge/` |
| `mcp/src/tools.ts` | `/api/mcp/tools/report_session_knowledge/` | `callFridayTool` 通用 POST | WIRED | `server.ts` 拼接 `tools/${toolName}/` |
| `serializers.py` | `tools.ts` | 三面键相等测试 | WIRED | pytest 断言 `serializer_keys == snapshot_keys == package_keys` |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `ReportSessionKnowledgeView` | `output_data.capture_id` / `reason` | `CaptureService.persist` → `result.capture` / `link_reason` | 是（集成测试读 ORM） | ✓ FLOWING |
| `_record` `input_data` | `client` | DRF validated serializer | 是（ToolCallRecord.input） | ✓ FLOWING |
| npm ListTools | `FRIDAY_TOOLS` | 静态白名单 | 是（非空 schema，非 stub） | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| MCP-01/02/04 + INV-6 + 三面键 + Capture persist | `uv run pytest` 上述 7 个文件 `--reuse-db -q` | 56 passed in 113.62s | ✓ PASS |
| npm 52 工具 / annotations / 描述语义 | `cd mcp && npm test -- tests/server.test.ts` | 12 passed | ✓ PASS |
| 无 `--reuse-db` 首次跑 | 同文件列表 | 34 ERROR：`test_friday` DuplicateDatabase / ObjectInUse | ? SKIP as product — 环境占用既有 test DB，干净 `--reuse-db` 后全绿 |

### Probe Execution

| Probe | Command | Result | Status |
| ----- | ------- | ------ | ------ |
| — | — | Phase 142 未声明 `scripts/*/tests/probe-*.sh` | SKIPPED |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| MCP-01 | 01–04 | 新工具提交结构化会话回写 | ✓ SATISFIED | 路由 + serializer + HTTP 200 persist |
| MCP-02 | 01–02, 04 | 挂钩失败仍 200/`accepted=true`；`branch_unresolved` 不表示未收 | ✓ SATISFIED | unanchored / repo_unresolved / main / repo_unauthorized 用例 |
| MCP-03 | 01–04 | 三面对齐，缺面则测试失败 | ✓ SATISFIED | alignment + snapshot + vitest |
| MCP-04 | 01–02, 04 | 旧工具零回归，不扩成 Capture 入口 | ✓ SATISFIED | 15 旧工具测试 + 新 view 不引用 Memory 路径 |

无 ORPHANED：REQUIREMENTS.md 映射到 Phase 142 的仅 MCP-01..04。

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| `server/mcp_tools/views.py` `ReportSessionKnowledgeView` | — | TBD/FIXME/XXX | none | 新 view 无债务标记 |
| `mcp/src/tools.ts` | — | TBD/FIXME/XXX | none | 无 |
| `test_mcp_package_alignment.py` | 87–97 | 三面比较只锁 **request 键**，不比较类型/`required` | ℹ️ Info | npm `required` 与 CharField 仍由 vitest + serializer 分别锁住；不构成目标失败 |
| MCP persist 异常路径 | — | persist 抛错会向上冒泡，无专用 MCP 500 用例 | ℹ️ Info | `CaptureService.persist` 已 `log_failed` 再 raise；Phase 141 覆盖 writer；合法问答成功路径已锁 |

无 BLOCKER 级债务标记。

### Unrelated baseline (independently confirmed, not Phase 142 gaps)

文档声称全目录 `tests/mcp_tools/` 有 2 个蓝图脏工作树失败。本轮 **独立复现**，且与 `report_session_knowledge` 无调用链：

| Test | Observed | Root cause in current tree | Why not 142 |
| ---- | -------- | -------------------------- | ----------- |
| `test_stage_runner_tools.py::test_route_blueprint_repos_dry_run` | `body["router_version"]` 期望 `v2`，实际 `clarify` | `stage_sandbox.py` 在无 project/space/team/`include` 时返回 `router_version="clarify"` / `clarify_reason=missing_team`（日志 `blueprint_stage_route_sandbox_clarify`）。测试只 mock `RepoRouterV2.route`，走不到被 mock 的路由器。 | 蓝图路由沙箱；`process_runtime` 脏改动。新会话工具未参与。 |
| `test_blueprint_clarification_tools.py::test_response_assembly_splats_the_extras_so_the_off_state_is_byte_identical` | `'"blueprint_status":' not in src` 失败 | `technical_plan_service.py` 约 L167 在 `retry_state["blueprint_extras"]` 写入 `"blueprint_status":` 字面量（非 MCP 响应顶层键）。测试是源码字符串扫描。 | 技术方案预约对账；未提交的 `technical_plan_service.py`。 |

这些失败 **不**进入 `gaps`，也不改变 Phase 142 状态。工作树其余脏文件（含 `serializers.py` 对他工具 snapshot 的 +2 键）按编排要求未改动。

### Human Verification Required

None. PLAN 无 `<human-check>`；MCP-01..04 均有可执行自动化。IDE 真实 ListTools 由 npm 静态白名单 + 通用 POST 覆盖，不单独升级为 human_needed。

### Gaps Summary

无目标缺口。Phase 143（价值评估/入图）与 Phase 145（宿主自动采集）是后续里程碑，不是本阶段失败。

---

_Verified: 2026-08-28T09:32:00Z_
_Verifier: Claude (gsd-verifier)_
