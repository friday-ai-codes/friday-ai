---
phase: 22-fail-closed
plan: 02
subsystem: services
tags: [exclusion, fail-closed, security, indexer, scan_directory, PF-04, EXCL-02, tdd]

# Dependency graph
requires:
  - phase: 22-fail-closed
    plan: 01
    provides: "services.exclusion 单一匹配器（build_matcher_for_repo / ExclusionMatcher.is_excluded / BUILTIN_GLOBAL_DEFAULTS）"
provides:
  - "scan_directory 支持注入相对路径排除回调（is_excluded_rel），dir 级提前剪枝 + 文件级跳过 + 判定异常 fail-closed"
  - "run_full_index / run_incremental_index 两条扫描路径在源头剔除被排除文件（不进 files_to_process / local_hashes）"
  - "PF-04 修正：scan_directory 不再谎称已应用 .gitignore，注释/docstring 如实描述真实过滤口径"
affects: [22-fail-closed Wave 2 其余读取面（MCP/RAG/agent）, 23-purge 存量清理]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "纯函数 + 调用方注入：scan_directory 不硬依赖 services.exclusion，避免循环导入"
    - "async 预取 matcher + 同步回调注入：matcher.is_excluded 是纯同步，喂给同步 scan_directory"
    - "扫描期 fail-closed：判定异常 → 跳过文件 / 剪掉子树（T-22-07）"

key-files:
  created:
    - server/tests/services/test_indexer_exclusion.py
  modified:
    - server/services/code_parser.py
    - server/services/indexer.py

key-decisions:
  - "scan_directory 用 is_excluded_rel: Callable[[str], bool] | None 注入（而非接收 matcher 对象），保持纯函数无硬依赖、向后兼容"
  - "dir 级剪枝与文件级判定都 fail-closed：回调抛异常时分别剪掉子树 / 跳过文件，绝不放进索引"
  - "守护测试用 recognized-extension 的被排除文件（config/secret.json、secrets/leak.py、app.private.js）真正验证 matcher 钩子，而非被扩展名白名单顺带挡掉"

requirements-completed: [EXCL-02]

# Metrics
duration: 6min
completed: 2026-06-14
---

# Phase 22 Plan 02: 索引扫描面排除挂接 + PF-04 修正 Summary

**把 Plan 01 的单一匹配器挂接到索引扫描面（full + incremental 两条 `scan_directory` 路径），被排除文件从源头不进 `files_to_process` / `local_hashes`，fail-closed；同时修正 PF-04 —— `scan_directory` 不再谎称已应用 `.gitignore`，注释/docstring 如实描述「目录名 + 扩展名白名单 + 排除匹配器」真实口径。**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-06-14T08:31:55Z
- **Completed:** 2026-06-14T08:37:41Z
- **Tasks:** 2（均 TDD）
- **Files modified:** 3（1 新增测试 + 2 修改 service）

## Accomplishments
- `code_parser.scan_directory` 新增可选 `is_excluded_rel(rel_posix) -> bool` 回调：在 `os.walk` 内对目录做名字级裁剪（现状）+ 相对路径级提前剪枝，对文件按「相对 directory 根的 POSIX 路径」判定跳过；不传回调时与历史行为字节等价（向后兼容）。
- `scan_directory` docstring 与 `indexer.py` ~833 注释修正（PF-04）：明确「不应用 .gitignore」，如实描述三层过滤口径。
- `run_full_index` / `run_incremental_index` 在 `SCANNING_FILES` 阶段预取 `build_matcher_for_repo(self.repository_id)`（async 加载 + TTL 缓存），把 `matcher.is_excluded`（纯同步）注入同步 `scan_directory`，被排除文件从源头不进待索引集。
- 扫描期 fail-closed：`is_excluded_rel` 判定异常 → 跳过该文件 / 剪掉该子树（T-22-07）；matcher 自身亦对运行期异常 fail-closed。
- 守护测试 6 个全绿（3 个 `scan_directory` 单测 + 3 个 indexer full/incremental 集成测试）。

## Task Commits

Each task committed atomically (TDD RED → GREEN)：

1. **Task 1: scan_directory 相对路径排除回调 + PF-04** - `d21f2915c` (test, RED) → `580364312` (feat, GREEN)
2. **Task 2: indexer full + incremental 扫描挂接排除过滤** - `abc0e0452` (test, RED) → `428c25d0c` (feat, GREEN)

_两个任务均走 RED（新参数缺失 TypeError / 被排除文件仍进 FileIndex）→ GREEN。无 refactor 提交（GREEN 一次到位）。_

## Files Created/Modified
- `server/services/code_parser.py` - `scan_directory` 新增 `is_excluded_rel` 回调 + dir 剪枝 + fail-closed + docstring 修正（PF-04）。
- `server/services/indexer.py` - 两条扫描路径预取 `build_matcher_for_repo` 并注入 `scan_directory`；修正 ~833 谎称 .gitignore 注释；新增 `from services.exclusion import build_matcher_for_repo`。
- `server/tests/services/test_indexer_exclusion.py` - 6 个守护测试。

## Decisions Made
- **注入回调而非 matcher 对象**：`scan_directory` 接收 `Callable[[str], bool]` 而非 `ExclusionMatcher`，保持纯函数、不引入对 `services.exclusion` 的硬依赖（避免潜在循环导入），调用方（indexer）负责预取 matcher 并传 `matcher.is_excluded`。
- **dir 级剪枝是纯优化**：剪掉命中 `dir` 规则的子树与逐文件判定结果等价（如 `secrets/` 子树内文件也会被文件级 `secrets/...` 前缀命中），但提前剪枝省去无谓 walk。
- **测试选材**：刻意用 `config/secret.json`（builtin `*secret*.json`）、`secrets/leak.py`（builtin `secrets/` dir）、`app.private.js`（per-repo `*.private.js`）等 **被扩展名白名单收录** 的文件，确保断言真正验证 matcher 钩子，而非被扩展名过滤顺带挡掉；`.env` 因无识别扩展名本就不入扫描，作补充断言。

## Deviations from Plan

None - plan executed exactly as written.

（说明：测试断言以 FileIndex 集合见证「未进入 files_to_process / diff」，符合 plan acceptance「可 mock parse 计数或断言 FileIndex 集合」的第二选项；fail-closed 异常注入用 `scan_directory` 单测覆盖，比注入全链路更稳定。）

## Threat Surface (this plan)
- T-22-05（scan_directory 漏过被排除文件）→ mitigated：两条扫描路径统一注入匹配器 + 守护测试（full + incremental）+ builtin 兜底。
- T-22-06（PF-04 谎称 .gitignore）→ mitigated：注释/docstring 修正；`grep -rn "已应用 .gitignore" server/services/` 0 命中。
- T-22-07（扫描期判定异常 fail-open）→ mitigated：`scan_directory` 回调 try/except → 跳过文件 / 剪子树（fail-closed），`matcher.is_excluded` 亦内部 fail-closed。

## Known Stubs
None - 无占位/空值返回；本 plan 仅在扫描入口加过滤，未引入未接数据源的 UI/组件。

## Next Phase Readiness
- 索引扫描面（EXCL-02 第一面）已 fail-closed。Wave 2 其余读取面（MCP `get_file`/`grep`、RAG 检索、agent/编码容器）可继续直接复用 `services.exclusion.is_excluded` / `build_matcher_for_repo`，口径一致。
- 存量已索引的被排除文件清理仍留 Phase 23（本阶段仅保证扫描不再新增/更新它们，未删历史 Qdrant/FileIndex 记录，per D-04）。

## Self-Check: PASSED

- Files: code_parser.py / indexer.py / test_indexer_exclusion.py / 22-02-SUMMARY.md — all FOUND.
- Commits: d21f2915c / 580364312 / abc0e0452 / 428c25d0c — all FOUND (`git cat-file -e`).
- Tests: 6 passed（`tests/services/test_indexer_exclusion.py`）；55 passed 抽样回归（`tests/services -k "index or exclusion"`）；26 passed（resume + exclusion_matcher + per_run_delta）。
- Grep gate: `grep -rn "已应用 .gitignore" server/services/` → 0 命中（PF-04 关闭）。
- Lint: `ruff check` All checks passed；`ruff format` 已应用。

---
*Phase: 22-fail-closed*
*Completed: 2026-06-14*
