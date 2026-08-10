---
phase: 122-impact-trace
plan: 06
subsystem: code-graph
tags: [cross-repo, CrossRepoApiCall, REDACTED_REPOSITORY, fail-soft, hop-budget, observability-guard]

# Dependency graph
requires:
  - phase: 121-graph-base
    provides: "REDACTED_REPOSITORY、ensure_repository_readable 每次都跑、loader 两端同仓才建 cross_repo 边（D-25 冻结）"
  - plan: 122-01
    provides: "cross_repo_call_factory（endpoint_repository）、known_topology 同仓 cross_repo 边、四分支 Wave 0 桩"
  - plan: 122-03
    provides: "analyze_impact 内核（对端图上继续反向 BFS）"
  - plan: 122-05
    provides: "fetch_graph_for_tool / resolve_symbol_candidates / graph_error_to_tool_error、_SIBLING_GUARDED_MODULES"
provides:
  - "collect_cross_repo_impact：CrossRepoApiCall ORM 一跳 + 对端仓 get_graph 复核 + 三种显式条目"
  - "DEFAULT_MAX_CROSS_REPO_HOPS=1（不递归）"
  - "_find_peer_call_sites：真跨仓行按对端仓分组，match_confidence 原值透传"
  - "code_graph_cross_repo.py 已挂进 _SIBLING_GUARDED_MODULES"
affects: [122-07, 122-08, 122-09, 122-10]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "跨仓不沿图边：ORM 直查 CrossRepoApiCall.exclude(同仓) + 逐仓 fetch_graph_for_tool"
    - "无权限折叠仅两键 {cross_repo, repository=REDACTED_REPOSITORY}，无 affected_count（存在性预言机）"
    - "对端不可用 fail-soft：unavailable_reason 条目保留 repository_id（权限已过）"

key-files:
  created:
    - server/services/code_graph_cross_repo.py
  modified:
    - server/tests/services/code_graph/test_cross_repo_hop.py
    - server/tests/services/code_graph/test_access.py
    - server/tests/services/code_graph/test_impact.py

key-decisions:
  - "D-25：绝不改 loader 建边口径；跨仓只走 ORM + 对端 get_graph"
  - "D-30：折叠条目无 repository_id / affected_count——安全优先于便利"
  - "D-14：unavailable 保留 repository_id（ensure 已过）；与 redacted 形态刻意不同"
  - "D-26：四分支全靠合成数据；⛔ 不得表述成跨仓 impact 已上线可用"

requirements-completed: []  # IMPACT-03 路径未经真实数据验证（D-26）；壳层 122-07/08/09 未接线；⛔ 不得勾选

# Metrics
duration: 20min
completed: 2026-08-09
---

# Phase 122 Plan 06: 跨仓一跳（CrossRepoApiCall ORM + 对端 get_graph）Summary

**一个 418 行、因 ORM 边界待在包外的兄弟模块：用 `CrossRepoApiCall` 直查做一跳穿仓，对每个对端仓经 `fetch_graph_for_tool` 复核权限后跑 `analyze_impact`，无权限整仓折成 `REDACTED_REPOSITORY`、未索引/超时给 `unavailable_reason`——四条分支全部靠合成数据覆盖，跨仓路径未经任何真实数据验证**

## ⚠ D-26 如实声明（必须读）

1. **生产库 `CrossRepoApiCall` / `ApiCallSite` / `ApiWrapper` 均为 0 行**（`Endpoint` 6,014 行）。上游产出器依赖 volar LSP，而 server 镜像无 Node（LSP-01 / Phase 127）。
2. 本 plan 的四条分支（成功 / 无权限折叠 / 对端不可用 / 跳数上限）**全部由合成数据覆盖**。⛔ **不得**表述成「跨仓 impact 已上线可用」或「跨仓能力已验证」。
3. `(file_path, name)` 二次解析的真实命中率在 Phase 127 之前**根本不可测**（121-10 记的「样本不足」实为**样本为零**，本 plan 更正之）。
4. ROADMAP 需记一条「Phase 127 补齐 LSP 后回来用真实样本复验 IMPACT-03」——该动作由 **122-10** 执行，本 plan 不改 ROADMAP 跟进条目。

## Performance

- **Duration:** ~20 min
- **Started:** 2026-08-09T16:49:21Z
- **Completed:** 2026-08-09T17:05:00Z
- **Tasks:** 3
- **Files modified:** 4（1 新建 418 行 + 3 填实）

## Accomplishments

- **`_find_peer_call_sites` 只收真跨仓行**。`endpoint__repository_id=本仓` + `.exclude(call_site__repository_id=本仓)`，按对端仓分组进 `_PeerHits`；同仓行已在图里，排除避免同一条影响数两遍。`match_confidence=0.63` 原值透传，⛔ 不折成档位常量。
- **`collect_cross_repo_impact` 三种显式条目**。成功：`cross_repo` / `repository_id` / `match_confidence` / `call_sites` / `unresolved_call_sites` / `impact`；无权限：仅 `{"cross_repo": True, "repository": REDACTED_REPOSITORY}`（D-30）；不可用：`unavailable_reason` 取 `graph_error_to_tool_error` 错误码，保留 `repository_id`（ensure 已过）。条目排序：成功 → unavailable → redacted。
- **`max_hops<=0` 短路 + AST 不递归**。`max_hops=1` 时三仓链路（C→B→A）结果不含第三仓；函数体内无自调用。
- **观测契约收口**。`_SIBLING_GUARDED_MODULES` 增 `"code_graph_cross_repo.py"`；三个埋点事件名 `Final[str]`，unavailable 的 `error=` 过 `redact_secrets_in_text(...)[:500]`；redacted 埋点**不记**对端 `repository_id`。
- **反向守护落地**。`test_graph_cross_repo_edges_are_intra_repo`：图内 `kind==cross_repo` 两端都在同图；F 的 `via.confidence=="cross_repo"` 且 `path_confidence==0.7`，但遍历全部 item 无 `cross_repo: true`；内核顶层 `cross_repo==[]`。

## Task Commits

1. **Task 1: CrossRepoApiCall 直查与按对端仓分组（D-25）** - `68cb6d4b` (feat)
2. **Task 2: 逐仓权限复核与三种显式条目（D-12 / D-14 / D-30）** - `64b3a7ad` (feat)
3. **Task 3: 反向守护——图内 cross_repo 边不是跨仓结果** - `876984dd` (test)

## Files Created/Modified

- `server/services/code_graph_cross_repo.py`（新建，418 行）— 三段式中文 docstring（第一段写清 D-25）；`DEFAULT_MAX_CROSS_REPO_HOPS`；三个事件常量；`_PeerHits` / `_find_peer_call_sites` / `collect_cross_repo_impact`；三个 `_log_cross_repo_*`。
- `server/tests/services/code_graph/test_cross_repo_hop.py` — 四分支用例全绿（零 skip）。
- `server/tests/services/code_graph/test_access.py` — `_SIBLING_GUARDED_MODULES` 增本模块；⛔ 未改判据。
- `server/tests/services/code_graph/test_impact.py` — `test_graph_cross_repo_edges_are_intra_repo` 落地；本文件 **10 passed**。

## Decisions Made

- **跨仓唯一路径是 ORM + 对端 `fetch_graph_for_tool`**，不沿图边、不改 loader（D-25）。
- **折叠条目只有两键**：计数与 `repository_id` 都是存在性预言机（D-30 / T-122-折叠泄漏）。
- **unavailable 与 redacted 形态刻意不同**：前者调用方已有读权限，保留 `repository_id` 便于重试；后者信息止于「有一个你看不见的仓」。
- **二次 call site 复用 ApiWrapper**：factory 对同 peer 同 handler 会撞 `ApiWrapper` 唯一约束，测试里第二条 call site 手写复用 wrapper（不改 conftest 工厂，避免扰动 121 用例）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 同 peer 第二条 call site 撞 ApiWrapper 唯一约束**
- **Found during:** Task 1
- **Issue:** `cross_repo_call_factory` 每次新建 `ApiWrapper(function_symbol=fetch_{handler})`，同一 peer 上第二条同 handler 行触发 UniqueViolation
- **Fix:** 测试内第二条 `ApiCallSite` / `CrossRepoApiCall` 复用第一条的 wrapper 与 endpoint
- **Files modified:** `server/tests/services/code_graph/test_cross_repo_hop.py`
- **Commit:** `68cb6d4b`

**Total deviations:** 1 auto-fixed (Rule 1)
**Impact on plan:** 仅测试造数；未改生产代码或 conftest 工厂。

## Verification Results

| 判据 | 结果 |
|---|---|
| `pytest tests/services/code_graph -q --reuse-db` | **122 passed / 1 skipped**（基线 117/6；+5 passed / −5 skipped；剩 `test_impact_shell` 的 122-07 桩） |
| `test_cross_repo_hop.py` | **4 passed，零 skip** |
| `test_impact.py` | **10 passed**（含反向守护） |
| `_SIBLING_GUARDED_MODULES` 含本模块 | 退出码 0；observability / upper_layer 全绿 |
| AST 无自调用（不递归） | 退出码 0 |
| AST 无 loader/cache/signature/access 直连 | 退出码 0 |
| `ruff check` 对本 plan 文件 | All checks passed |
| `mypy services/code_graph_cross_repo.py` | 本文件零错误（报出的错误全在包外既有文件） |
| `makemigrations --check --dry-run` | `No changes detected`，退出码 0 |
| 未改 `loader.py` / `repo_router_v2.py` / `mcp/` | 本 plan 三笔 commit 的 diff 不含这些路径 |

## Issues Encountered

- 全量 `tests/services/code_graph` 偶发 `ERROR`（DB 连接 / reuse-db 与并发会话争用），单独复跑对应用例即绿；按 scope boundary 未修，不计入本 plan 失败。
- 并发会话在工作树有大量未提交改动；本 plan 仅按显式路径 stage 自己的四个文件。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 122-07 可把 `collect_cross_repo_impact` 接进 `run_impact` 编排（本模块已导出）。
- ⛔ 在 Phase 127 / LSP-01 补齐真实 `CrossRepoApiCall` 样本之前，不得对外宣称 IMPACT-03 已验证。
- 122-10 负责把「Phase 127 复验 IMPACT-03」记入 ROADMAP。

## Self-Check: PASSED

- FOUND: `server/services/code_graph_cross_repo.py`
- FOUND: `server/tests/services/code_graph/test_cross_repo_hop.py`
- FOUND: commits `68cb6d4b` / `64b3a7ad` / `876984dd`
- FOUND: `_SIBLING_GUARDED_MODULES` contains `code_graph_cross_repo.py`

---
*Phase: 122-impact-trace*
*Completed: 2026-08-09*
