---
phase: 22-fail-closed
plan: 06
subsystem: api
tags: [exclusion, fail-closed, security, mcp-tools, bare-mirror, EXCL-02]

# Dependency graph
requires:
  - phase: 22-fail-closed
    provides: "22-01 单一匹配器 is_excluded / build_matcher_for_repo / log_exclusion_blocked"
provides:
  - "MCP HTTP 直读面 fail-closed：grep_repository / get_repository_file / list_repository_files / find_related_chunks 对被排除文件不可见"
  - "bare-mirror 残留泄漏面关闭（DOMAIN §9.1/§9.3 工具层 denylist 兜底）"
affects: [外部 MCP 客户端读取面, 23-purge 存量清理对账]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "view 层只调 services.exclusion 单一匹配器，不另写过滤（与 indexer 同口径）"
    - "per-repo 预取 matcher 批量过滤（grep/list/find_related）；单文件入口判定（get_file）"
    - "判定/构造异常 → fail-closed（_FailClosedMatcher 兜底），绝不降级返回明文"

key-files:
  created:
    - server/tests/mcp_tools/test_mcp_exclusion.py
  modified:
    - server/mcp_tools/views.py

key-decisions:
  - "get_repository_file 对 requested + resolved_path 双判定，防后缀解析绕过（T-22-21）"
  - "grep 过滤后 total_matches/files_with_matches 用过滤后口径，避免泄漏被排除文件存在性"
  - "list 过滤发生在 requested_path 前缀筛选之后、items 组装之前；纯被排除文件目录因文件全移除而不生成目录项"
  - "matcher 构造异常用 _FailClosedMatcher 兜底（排除一切），而非降级放行"

requirements-completed: [EXCL-02]

# Metrics
duration: 9min
completed: 2026-06-14
---

# Phase 22 Plan 06: MCP 工具读取面 fail-closed 排除 Summary

**把外部暴露的 MCP HTTP 直读面（grep_repository / get_repository_file / list_repository_files / find_related_chunks）挂接 Plan 01 的单一匹配器，对被排除文件 fail-closed 不可见——镜像直读与索引回退两条路径都拦，关闭 bare-mirror 残留泄漏通道（EXCL-02 工具面补齐）。**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-06-14T08:43:29Z
- **Completed:** 2026-06-14T08:52:40Z
- **Tasks:** 2
- **Files modified:** 2（1 created test + 1 modified views）

## Accomplishments
- `GetRepositoryFileView`：新增 `_excluded_response`，在镜像命中路径（`_read_from_mirror` 返回后）与索引回退路径（`_scroll_file_from_collection` 解析后）返回 content 前，对 requested `file_path` 与 `resolved_path` 双判定 `is_excluded`；命中 → `error_response("file_excluded", 404)` + `log_exclusion_blocked(surface="get_repository_file")`，绝不返回任何 content/lines。后缀解析出的 `resolved_path` 复判防绕过。
- `GrepRepositoryView`：新增 `_filter_grep_result`，每 repo 预取匹配器，`grep_mirror` 返回后按 `file_path` 过滤 `matches` 与 `file_counts`，并用过滤后口径重算 `total_matches`/`files_with_matches`；命中过滤 → `log_exclusion_blocked(surface="grep_repository")`。token 预算、traces、files_only 均消费过滤后结果，无被排除路径泄漏。
- `ListRepositoryFilesView`：在 requested_path 前缀筛选后、items 组装前过滤被排除路径；纯由被排除文件构成的目录因其文件全部移除而不再生成目录项。
- `FindRelatedChunksView`：返回邻居前按 `file_path` 过滤被排除项（防御性兜底，T-22-24）+ 审计埋点。
- fail-closed 失败模式：`_exclusion_matcher` 在 `build_matcher_for_repo` 抛异常时返回 `_FailClosedMatcher`（判定一切为排除），不降级放行；`matcher.is_excluded` 自身对路径归一/匹配异常已 fail-closed（Plan 01 保证）。
- 守护测试 11 例（含跨工具一致性用例：单一 `.env` 在四个工具中均不可见），全部命中内置全局默认（开箱即用，无 per-repo 规则即生效）。

## Task Commits

Each task was committed atomically:

1. **Task 1（TDD）: 三个 bare-mirror/索引直读工具 fail-closed** - `19b463dae` (test, RED) → `7c553f10b` (feat, GREEN)
2. **Task 2: find_related_chunks 防御性过滤 + 跨工具守护** - `1a0c6f0cd` (feat)

_TDD: Task 1 走 RED（8 failed / 1 passed，过滤未挂接）→ GREEN（9 passed）。无 refactor 提交（GREEN 一次到位）。_

## Files Created/Modified
- `server/mcp_tools/views.py` - 四个 view 挂接 fail-closed 过滤 + `_exclusion_matcher`/`_FailClosedMatcher` 模块助手
- `server/tests/mcp_tools/test_mcp_exclusion.py` - MCP 读取面排除守护测试（镜像 + 索引回退 + 跨工具 + fail-closed）

## Decisions Made
- **双判定防绕过**：get_file 对 requested 与 resolved 路径都判定；后缀解析（`endswith` 候选）可能把无害请求名解析到被排除真实路径，故 resolved_path 必须复判（T-22-21）。
- **过滤后计数口径**：grep 的 `total_matches`/`files_with_matches` 用过滤后值，而非保留原值或标注，避免通过计数泄漏被排除文件的存在性。
- **fail-closed 兜底匹配器**：匹配器构造（DB/设置加载）异常时用 `_FailClosedMatcher` 排除一切，比"放行"更安全（宁可多排不可漏，T-22-25）。
- **不改 repo_mirror.py 助手**：仅在 view 层过滤（per D-04 只在读取/暴露侧加过滤层）；不重复 22-03 已覆盖的 `search_rag_chunks`。

## Deviations from Plan

None - plan executed exactly as written.

（落地细节说明：为保持改动最小、避免无关 churn，未对 `views.py` 跑整文件 `ruff format`——该文件在 HEAD 即非 ruff-format 规范且 import 块 I001 预存；新增代码按周边既有风格手写并通过 `ruff check`（仅余预存 I001，属既有问题、超出本 plan 范围）。新增/改动逻辑行均经 ruff check 干净。）

## Issues Encountered
- `views.py` 在 HEAD 上即未通过 `ruff format --check` 且存在预存 I001（import 块未排序）。为遵守"只修改本任务直接相关代码"的范围边界，未对整文件重排版（会引入大量无关 dict 字面量 churn）；仅保证新增逻辑符合既有风格、`ruff check` 不新增告警。预存 I001 留作既有问题。
- 测试运行器：用项目 venv `server/.venv/bin/python -m pytest`（rootdir=server），与既有 MCP 测试一致。

## User Setup Required
None - 无外部服务配置；既有部署升级后仅内置全局默认 + SystemSetting 生效，向后兼容（无 per-repo 规则即令 `.env` 等敏感文件在四个 MCP 工具中不可见）。

## Next Phase Readiness
- EXCL-02 读取面（索引扫描 / MCP 工具）地基完成；存量派生数据（Qdrant 残留 point、镜像 git object）清理留 Phase 23。
- 安全承诺与 DOMAIN §9.1 一致：承诺"被排除文件对 Friday 不可见"，不承诺 git object 物理消失。

## Threat Flags

None - 未引入新的网络端点 / 认证路径 / schema 变更；本 plan 仅在既有读取出口收紧过滤。

## Self-Check: PASSED
