---
phase: 122-impact-trace
plan: 10
subsystem: testing
tags: [D-21, dual-surface, IMPACT-06, D-26, D-27, mcp-drift]

# Dependency graph
requires:
  - plan: 122-08
    provides: "MCP impact_analysis / trace_call_path 壳 + test_impact_trace_tools 五用例"
  - plan: 122-09
    provides: "对话 @tool impact_analysis / trace_call_path 薄壳"
provides:
  - "test_two_surfaces_same_payload —— 本仓第一条双面同源逐字节守护（D-21）"
  - "ROADMAP D-26 IMPACT-03 真实样本复验欠债（挂 Phase 127）"
  - "ROADMAP D-27 mcp npm 漂移 5→7 记账（impact_analysis / trace_call_path）"
affects: [123-detect-changes, 127-semgrep-lsp]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "双面同源哨兵：json.dumps(sort_keys=True) 比对 MCP data（去 run_id）与 ToolResult.output.data"
    - "失败态成功语义：HTTP 200 + ToolResult.success=True；ok=False 是查询结论不是工具故障"
    - "跨相位记账措辞纪律：合成覆盖不得写成「已验证」；漂移必须带数字与工具名"

key-files:
  created: []
  modified:
    - server/tests/mcp_tools/test_impact_trace_tools.py
    - .planning/ROADMAP.md

key-decisions:
  - "D-21：成功态与 ambiguous_symbol 各一轮逐字节比对；run_id 是唯一允许且写死的差异"
  - "D-26：IMPACT-03 合成通过 ≠ 跨仓能力已验证；Phase 127 复验四点事实落地 ROADMAP"
  - "D-27：mcp npm 漂移 5→7（新增 impact_analysis / trace_call_path），不修 submodule、不改守护判据"

patterns-established:
  - "本仓第一条 test_two_surfaces_same_payload 范式：键集先行 + sort_keys dumps + 禁止 mock 编排层（AST）"
  - "django_db(transaction=True) 才能让 async Conversation.acreate 看见同用例造的 access_user"

requirements-completed: [IMPACT-01, IMPACT-02, IMPACT-03, IMPACT-04, IMPACT-05, IMPACT-06]

# Metrics
duration: 6min
completed: 2026-08-09
---

# Phase 122 Plan 10: Dual-surface equality + D-26/D-27 bookkeeping Summary

**本仓第一条双面同源逐字节守护落地：MCP 与对话壳对同一输入产出相同 `data`（成功态 + `ambiguous_symbol`）；ROADMAP 写实 D-26 复验欠债与 D-27 漂移 5→7**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-08-09T17:47:05Z
- **Completed:** 2026-08-09T17:52:38Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- **双面同源哨兵（D-21）。** `test_two_surfaces_same_payload` 去掉 skip：同用户（`access_user` ↔ `Conversation.created_by`）下成功态与 `ambiguous_symbol` 各一轮 `json.dumps(..., sort_keys=True)` 比对；键集先行保证失败可读；`run_id` 写死为 MCP 面唯一允许差异。
- **失败语义钉死。** MCP `status_code == 200`、对话 `ToolResult.success is True`；`ok=False` / `error_code=ambiguous_symbol` / 3 条 candidates——不是 4xx、不是工具故障。
- **跨相位记账。** Phase 127 挂 D-26 四点（生产零样本、合成覆盖、复验动作、样本为零）；跨仓记账句升级为 5→7 + 两个工具名；本相位使既有失败从 5 项**扩大到 7 项**（如实声明，不粉饰）。

## Task Commits

1. **Task 1: test_two_surfaces_same_payload** - `5587b7e2` (test)
2. **Task 2: D-26 / D-27 ROADMAP 记账** - `decbb8cb` (docs)

**Plan metadata:** docs commit（本 SUMMARY + STATE/ROADMAP/REQUIREMENTS）

## Files Created/Modified

- `server/tests/mcp_tools/test_impact_trace_tools.py` - 落地双面同源用例（成功态 + ambiguous）
- `.planning/ROADMAP.md` - Phase 127 D-26 回访 + 跨仓记账 D-27（5→7）

## Decisions Made

- 用例不 mock `run_impact`（AST 反自证）；两面真走全程。
- `django_db(transaction=True)` 解决 async `Conversation.acreate` 对未提交 `access_user` 的 FK 不可见。
- D-26 / D-27 只改 ROADMAP 文案；⛔ 不碰 `mcp/` submodule、⛔ 不改 `test_mcp_package_alignment.py` 判据。

## D-26 记账复述（四点）

1. 生产库 `CrossRepoApiCall` / `ApiCallSite` / `ApiWrapper` **均为 0 行**（`Endpoint` 6,014 行）；上游产出器依赖 volar LSP，server 镜像无 Node。
2. Phase 122 的 IMPACT-03 四条分支**全部由合成数据覆盖**，跨仓路径**未经任何真实数据验证**。
3. Phase 127 补齐 LSP 并重建索引后，**回来用真实样本复验 IMPACT-03** 的四条分支，并测出 `(file_path, name)` 二次解析的真实命中率。
4. 121-10 记的「样本不足」实为**样本为零**，命中率在 Phase 127 之前根本不可测。

## D-27 记账复述

- HEAD 上既有 **5** 项漂移：`apply_repo_association` / `generate_requirement_spec` / `get_repo_research` / `route_blueprint_repos` / `start_repo_research`。
- Phase 122 新增 `impact_analysis` / `trace_call_path` 后变为 **7** 项。
- 本相位按 D-27 **不修** submodule（并发会话占用 + 跨仓另批发版）；守护继续红着。**本相位使既有失败从 5 扩大到 7——不是「没有影响」。**

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] async 用例 FK 不可见**
- **Found during:** Task 1
- **Issue:** `Conversation.objects.acreate(created_by=access_user)` 在默认 `django_db` 事务隔离下看不到未提交的 user 行，触发 `ForeignKeyViolation`
- **Fix:** 给用例加 `@pytest.mark.django_db(transaction=True)`，并用 `sync_to_async` 包同步 ORM / `APIClient.post`
- **Files modified:** `server/tests/mcp_tools/test_impact_trace_tools.py`
- **Verification:** `test_two_surfaces_same_payload` 与整文件 `6 passed` 零 skip
- **Committed in:** `5587b7e2`

**2. [Rule 3 - Blocking] ROADMAP Progress 表未自动更新**
- **Found during:** state updates（`roadmap.update-plan-progress`）
- **Issue:** Progress 表是 6 列（含 Requirements），SDK 只认 4/5 列，返回 `complete: true` 但行仍停在 `7/10`
- **Fix:** 手改 Progress 行 → `10/10 | Complete | 2026-08-09`，勾 Phase 122 顶栏 checkbox，`**Plans**` → `10/10 plans complete`
- **Files modified:** `.planning/ROADMAP.md`
- **Verification:** 行文与 10 个 SUMMARY 计数一致
- **Committed in:** _(final docs commit)_

---

**Total deviations:** 2 auto-fixed (Rule 3 ×2)
**Impact on plan:** 必要收口记账，无范围蔓延。

## Issues Encountered

None beyond the transaction isolation fix above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 122 IMPACT-01..06 结构与双面哨兵齐备；IMPACT-03 真实样本复验挂 Phase 127（D-26）。
- Phase 123（detect_changes）可照抄本相位「内核 + 双面薄壳 + 双面同源哨兵」范式。
- `mcp` npm 包 7 项漂移仍是已知既有失败，另仓发版闭合（D-27）。

## Self-Check: PASSED

- FOUND: `server/tests/mcp_tools/test_impact_trace_tools.py`（含 `def test_two_surfaces_same_payload`）
- FOUND: `.planning/ROADMAP.md`（Phase 127 段含 IMPACT-03/复验/CrossRepoApiCall；跨仓记账含 impact_analysis/trace_call_path/5/7）
- FOUND: commit `5587b7e2`
- FOUND: commit `decbb8cb`
- VERIFIED: `mcp/` 与 `test_mcp_package_alignment.py` 未被本 plan 提交触碰
- VERIFIED: `makemigrations --check --dry-run` → No changes detected
- VERIFIED: `tests/mcp_tools/test_impact_trace_tools.py` → 6 passed 零 skip；`tests/services/code_graph` → 130 passed

---
*Phase: 122-impact-trace*
*Completed: 2026-08-09*
