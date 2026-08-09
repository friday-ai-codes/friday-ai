---
phase: 124-coding-chain
verified: 2026-08-09T19:56:03Z
status: passed
score: 8/8 must-haves verified
overrides_applied: 0
re_verification: false
gaps: []
deferred:
  - truth: "CreatePRNode / chat coding_graph MR paths also append impact_report"
    addressed_in: "backlog (CONTEXT Claude's Discretion / IN-01)"
    evidence: "CONTEXT deferred: CreatePRNode 推荐但非成功标准必达；REVIEW IN-01"
  - truth: "Recommendations 含 affected_processes 执行流叙事"
    addressed_in: "Phase 126"
    evidence: "Phase 126 goal: 执行流可追踪并回填影响面叙事层；CONTEXT D-07 / Phase 126 EXEC-03"
human_verification: []
---

# Phase 124: 编码链闭环 Verification Report

**Phase Goal:** detect_changes 真正进「需求→PR」编码链——容器提交前自查、MR 描述自动带影响面报告，这是 Friday 区别于 GitNexus 的落点

**Verified:** 2026-08-09T19:56:03Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | ------- | ---------- | -------------- |
| 1 | 编码任务容器经 MCP PAT 白名单可调 `detect_changes`；plan/execute + knowledge 挂载时 system prompt 含非阻断自查指引；不改 runner commit/push（SC1 / DIFF-03 / D-01..D-04） | ✓ VERIFIED | `KNOWLEDGE_TOOL_SCHEMAS` 含 `detect_changes`（required=`repository_id`,`compare`）；`knowledge_allowed_tools()` → `mcp__friday-knowledge__detect_changes`；`_get_system_prompt` 条件追加 `_detect_changes_guidance`（继续交付 / 勿因 HIGH·CRITICAL 停）；`task/core/runner.py` 零 `detect_changes` 引用 |
| 2 | HI-01：容器可获得权威 `repository_id`（dispatch 注入 + 指引内联） | ✓ VERIFIED | `TaskConfig.repository_id` ← `FRIDAY_TASK_REPOSITORY_ID`；`AICodingNode` / `coding_session_service` 注入 `env_FRIDAY_TASK_REPOSITORY_ID`；`_build_coding_prompt` 写「仓库 ID」；UUID 校验后内联进 guidance（commit `5a9de968`） |
| 3 | workflow + MCP 建 MR 链路 MR 描述自动附 `## 影响面` 四段 Changes/Affected/Risk/Recommendations（SC2 / DIFF-04 / D-05..D-07） | ✓ VERIFIED | 共享 `build_impact_report_section` 渲染四段；挂点：`AICodingNode._create_mr_for_repo`、`merge_request_service.create_merge_request`、`mr_service.create_mr_for_task`；`CreateMergeRequestView` 传 `user=request.user`；`work_item` 传 `user=initiating_user` |
| 4 | 影响面失败 fail-soft：建 MR 主流程零阻断（SC3 / D-09..D-12） | ✓ VERIFIED | helper 永不 raise；超时/ACL/`ok=False` → stub（稳定 `error_code`）；壳层 `except` 吞异常后仍 `create_merge_request`；测试 `test_*_failsoft*` 绿 |
| 5 | D-14 双路径对等：同一 (repo, compare, base_ref, user) 调同一 helper；stub 字节稳定 | ✓ VERIFIED | `test_workflow_mcp_impact_section_parity` spy kwargs 相等 + 未 patch helper 的 stub 对等（ME-01 / `7735b696`） |
| 6 | ME-02：外层 shell 失败可观测（`impact_report_shell_failed`） | ✓ VERIFIED | coding.py / merge_request_service.py / mr_service.py 均 best-effort log（`d783abff`） |
| 7 | ME-03：缺 user 使用独立 `user_missing`；`mr_service` 解析 triggered_by | ✓ VERIFIED | `impact_report.py` short-circuit stub `user_missing`；`_resolve_impact_user`；测试断言 stub/log（`2fb3a0b5`） |
| 8 | 冻结面：未改 `repo_router_v2.py` / `mcp/` submodule；无产品 kill-switch；仅 timeout/max_chars settings（D-13/D-16） | ✓ VERIFIED | phase commits 不触碰冻结文件；settings 仅 `CODE_GRAPH_IMPACT_REPORT_TIMEOUT_SECONDS=30` / `MAX_CHARS=10240` |

**Score:** 8/8 truths verified

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | CreatePRNode / coding_graph 方言 MR 路径未挂 impact_report | backlog (IN-01) | CONTEXT：推荐但非成功标准必达 |
| 2 | Recommendations `affected_processes` 叙事 | Phase 126 | ROADMAP Phase 126 goal / CONTEXT D-07 |
| 3 | LO-01：MR dedup 复用时不更新远端 description | product decision（REVIEW-FIX skipped） | 非成功标准阻断；create 路径已附报告 |

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | ----------- | ------ | ------- |
| `task/core/knowledge_tools.py` | detect_changes schema + whitelist | ✓ VERIFIED | 第 11 工具；required=`repository_id`,`compare` |
| `task/core/executor.py` | `_detect_changes_guidance` + 条件追加 | ✓ VERIFIED | plan/execute + knowledge；HI-01 UUID 内联 |
| `task/core/config.py` | `repository_id` / `FRIDAY_TASK_REPOSITORY_ID` | ✓ VERIFIED | BaseSettings env_prefix |
| `task/tests/test_detect_changes_prompt.py` | prompt 条件绿测 | ✓ VERIFIED | 含 UUID / 非法拒绝 / 非阻断文案 |
| `server/services/code_graph/impact_report.py` | 共享 formatter + fail-soft | ✓ VERIFIED | 418 行；exports marker/build/append |
| `server/friday/settings.py` | timeout / max_chars | ✓ VERIFIED | 无 kill-switch 注释明确 |
| `server/workflows/nodes/ai/coding.py` | MR append + env 注入 | ✓ VERIFIED | 挂点 + `env_FRIDAY_TASK_REPOSITORY_ID` |
| `server/mcp_tools/merge_request_service.py` | MCP MR append | ✓ VERIFIED | 幂等 append + shell log |
| `server/workflows/services/mr_service.py` | create_mr_for_task 消方言 | ✓ VERIFIED | `_resolve_impact_user` + append |
| `server/mcp_tools/work_item_execution_service.py` | `user=initiating_user` | ✓ VERIFIED | create_merge_request 传 user |
| `server/tests/.../test_impact_report.py` 等 | formatter / fail-soft / D-14 | ✓ VERIFIED | 18 server + 10 task 相关测全绿 |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | --- | --- | ------ | ------- |
| `knowledge_allowed_tools` | `KNOWLEDGE_TOOL_SCHEMAS` | `mcp__friday-knowledge__{name}` | ✓ WIRED | 含 `detect_changes` |
| `_get_system_prompt` | `_detect_changes_guidance` | knowledge+token+plan/execute | ✓ WIRED | parts-join 与 openspec 共存 |
| dispatch (AICodingNode / chat) | `TaskConfig.repository_id` | `env_FRIDAY_TASK_REPOSITORY_ID` | ✓ WIRED | HI-01 |
| `build_impact_report_section` | `run_detect_changes` | `asyncio.wait_for(timeout=settings…)` | ✓ WIRED | D-05/D-10 |
| `append_impact_report` | `IMPACT_SECTION_MARKER` | 幂等跳过已含段 | ✓ WIRED | D-06 |
| `_create_mr_for_repo` | `build_impact_report_section` | append before create | ✓ WIRED | D-06 workflow |
| MCP `create_merge_request` | same helper | `user=request.user` / initiating_user | ✓ WIRED | D-06 MCP |
| `create_mr_for_task` | same helper | `_resolve_impact_user` | ✓ WIRED | 第三条方言消除 |
| D-14 sentinel | shared helper kwargs/output | spy + unpatched stub | ✓ WIRED | ME-01 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `build_impact_report_section` | `envelope` / section markdown | `run_detect_changes` (live at MR create) | Yes（fixture/mock 测覆盖四段与 stub） | ✓ FLOWING |
| `_detect_changes_guidance` | `repo_clause` | `config.repository_id` ← dispatch env | Yes（UUID 内联；非法回退 env 提示） | ✓ FLOWING |
| MR `description`/`body` | impact section | `append_impact_report(build_…)` | Yes on create path；dedup reuse 远端不更新（LO-01 已知） | ✓ FLOWING（create） |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| DIFF-03 prompt/whitelist | `cd task && uv run pytest tests/test_knowledge_tools.py -k detect_changes tests/test_detect_changes_prompt.py tests/test_openspec_prompt.py -q` | 10 passed | ✓ PASS |
| DIFF-04 formatter + dual-path | `cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest tests/services/code_graph/test_impact_report.py tests/workflows/test_coding_impact_report.py tests/mcp_tools/test_mr_impact_report.py -q --reuse-db` | 18 passed | ✓ PASS |

### Probe Execution

| Probe | Command | Result | Status |
| ----- | ------- | ------ | ------ |
| — | — | 本相位未声明 `scripts/*/tests/probe-*.sh` | SKIPPED |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| DIFF-03 | 124-01 | 容器白名单 + 自查指引进提交决策 | ✓ SATISFIED | whitelist + prompt + HI-01 UUID；REQUIREMENTS Complete |
| DIFF-04 | 124-02 + 124-03 | MR 四段影响面 + fail-soft | ✓ SATISFIED | shared formatter + 三挂点 + 绿测；REQUIREMENTS Complete |

Orphaned requirements for Phase 124: none（仅 DIFF-03/04）。

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | -------- | -------- | ------ |
| — | — | TBD/FIXME/XXX in phase-touched sources | — | none found |
| `server/workflows/nodes/ai/coding.py` | ~2264+ | LO-01: impact before dedup；reuse 不写远端 description | ℹ️ Info | REVIEW-FIX 显式 skip（产品决策）；create 路径仍满足 SC2 |
| `server/workflows/nodes/git/pr.py` / `coding_graph.py` | — | IN-01 方言路径无 impact_report | ℹ️ Info | CONTEXT 明确非必达 |

### Human Verification Required

None required for phase gate. CONTEXT 明确本相位验收覆盖双链路自动化单元/哨兵，不要求人工点生产仓 tip。

可选运维确认（不阻断 status）：workflow 建 MR 时是否始终有 `triggered_by`——否则 description 会出现 `user_missing` stub（ME-03 已可区分）。

### Review Fixes Checklist

| ID | Status | Evidence |
| ---- | ------ | -------- |
| HI-01 | ✓ present | `5a9de968` — env + prompt + guidance |
| ME-01 | ✓ present | `7735b696` — spy kwargs + unpatched stub |
| ME-02 | ✓ present | `d783abff` — `impact_report_shell_failed` |
| ME-03 | ✓ present | `2fb3a0b5` — `user_missing` + `_resolve_impact_user` |
| LO-02 | ✓ present | `83521b38` — fail-soft assert tightened |
| LO-01 | skipped (product) | REVIEW-FIX documented |

### Gaps Summary

No blocking gaps. Phase goal achieved: DIFF-03 容器自查面（白名单 + 非阻断指引 + UUID 注入）与 DIFF-04 双路径 fail-soft 影响面报告均在代码与靶向测试中可证。已知非阻断项（MR dedup 远端描述、CreatePRNode 方言、Phase 126 Process 叙事）已记录为 deferred/info。

---

_Verified: 2026-08-09T19:56:03Z_
_Verifier: Claude (gsd-verifier)_
