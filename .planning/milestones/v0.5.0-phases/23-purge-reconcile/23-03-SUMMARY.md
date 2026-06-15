---
phase: 23-purge-reconcile
plan: 03
subsystem: api
tags: [sensitive-purge, exclusion, scrub, diff-archive, async-orm, structlog, redaction]

# Dependency graph
requires:
  - phase: 23-purge-reconcile
    provides: 23-02 services/purge_reconcile.py run_cleanup(mode="sensitive") 懒导入契约（from services.sensitive_purge import purge_sensitive_planes）
  - phase: 14
    provides: knowledge/diff_archive.py compress_diff/decompress_diff（scrub 后重压缩复用纯函数）
provides:
  - purge_sensitive_planes(repository_id, file_paths) -> dict（敏感清理委托入口；scrubbed 各面计数 + unscrubbed + caveat + errors）
  - CodeChangeArchive file 级 scrub（剔除被排除文件 diff 段 + 重算计数；仅含该文件整行删；含他文件不误删）
  - TaskResult / ActionLog 经 session.repo_url 归一关联本仓的可控清理（关联不确定保守不动）
  - message parts/content 子串脱敏（无 repo 关联面 best-effort，只脱敏命中叶子不整库清空）
  - SENSITIVE_PLANES_CAVEAT（如实声明 git/备份不承诺物理消失，§9.1）
affects: [23-04-purge-frontend]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "敏感清理逐面隔离：四面 helper 各自 try/except，单面失败记 errors + warning 不中断其余面"
    - "file 级 vs repo 级关联二分：CodeChangeArchive/message 走 file 级（diff 段/正文叶子），TaskResult/ActionLog 走 repo 级（repo_url↔git_url 归一）+ file 级二次过滤"
    - "保守不删：repo_url 归一不等于本仓 git_url 的 TaskResult/ActionLog 完全不动（T-23-12 避免误删他仓产物）"
    - "诚实边界：无精确 file 关联面（prompt snapshot/备份/git object）计入 unscrubbed + caveat 文档化，绝不假装清除（T-23-11，§9.1）"
    - "递归叶子脱敏：_redact_value 只替换命中被排除路径的 str 叶子，保留同载荷其余字段（避免过度清理 T-23-13）"

key-files:
  created:
    - server/services/sensitive_purge.py
    - server/tests/services/test_sensitive_purge.py
  modified: []

key-decisions:
  - "CodeChangeArchive scrub recompute 直接过滤既有 files 列表 + decompress_diff/compress_diff 重压缩，不调 parse_diff_files（其解析平台 MR API 对象而非 unified-diff 文本，W4 类型不符）"
  - "diff 段剔除按 `diff --git a/old b/new` 边界切段（对齐 _assemble_raw_diff 拼接形态），new/old 任一命中即剔除该段"
  - "TaskResult/ActionLog 关联键 = _normalize_repo_url(session.repo_url) == _normalize_repo_url(repo.git_url)（去 .git/末尾斜杠/小写）；不匹配保守不动"
  - "message parts/content 无 repo 关联键（Conversation 绑 Project 非 Repository）→ best-effort 子串脱敏命中叶子，prompt snapshot/备份/git 记 unscrubbed 不假装清除"

patterns-established:
  - "敏感清理结果 dict 形状：{scrubbed:{plane:{scrubbed,deleted}}, unscrubbed:[...], caveat, errors:[...]}，落 CleanupRun.sensitive 经状态端点诚实回流"
  - "purge.sensitive_plane 结构化审计事件（plane/repository_id/scrubbed/deleted）差异化各面动作"

requirements-completed: [EXCL-05]

# Metrics
duration: ~25min
completed: 2026-06-14
---

# Phase 23 Plan 03: 敏感清理操作记录数据面 Summary

**`purge_sensitive_planes` 在普通排除清理之上额外清操作记录面——CodeChangeArchive file 级 scrub（剔除被排除文件 diff 段 + 重算计数，仅含该文件整行删，含他文件不误删）、TaskResult/ActionLog 经 repo_url↔git_url 归一关联本仓的可控清理（关联不确定保守不动）、message parts/content 子串脱敏；无精确 file 关联面（prompt snapshot/备份/git object）如实记 unscrubbed + caveat 绝不假装清除，兑现 23-02 sensitive 懒导入契约。**

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-06-14
- **Tasks:** 2
- **Files modified:** 2（2 created）

## Accomplishments
- 新建 `services/sensitive_purge.py`：`purge_sensitive_planes` 入口 + 四面 helper（`_scrub_code_change_archives` / `_scrub_task_results` / `_scrub_action_logs` / `_scrub_loose_text_planes`）+ `_normalize_repo_url` / `_split_diff_segments` / `_redact_value` 辅助 + `SENSITIVE_PLANES_CAVEAT` / `UNSCRUBBED_PLANES` 常量。
- **CodeChangeArchive file 级 scrub**：含被排除文件的归档剔除其 `files` 项与 diff 段（按 `diff --git` 边界切段，`decompress_diff`→去段→`compress_diff` 重压缩），重算 `file_count`/`total_additions`/`total_deletions`/`diff_size`/`compressed_size`/`diff_sha256`；仅含被排除文件 → 整行删；含他文件 → 保留他文件部分（不误删，T-23-13）。
- **TaskResult / ActionLog**：经 `session.repo_url` 归一匹配本仓 `git_url` 的记录才清理（`modified_files`/`raw_output.modified_files` 剔除被排除文件项；ActionLog payload 命中叶子脱敏）；归一不匹配的记录**完全不动**（T-23-12 保守不删他仓产物）。
- **无精确 file 关联面**：`_scrub_loose_text_planes` 对 message parts/content 中子串命中被排除 file_path 的文本叶子脱敏（只替换命中叶子，不整库清空，T-23-11/13）；`prompt_snapshot`/`backups`/`git_objects` 记入 `unscrubbed` + `SENSITIVE_PLANES_CAVEAT` 如实声明 git/备份不承诺物理消失（§9.1）。
- 逐面异常隔离（单面失败记 `errors` + warning 不中断其余）；`purge.sensitive_plane` 差异化审计事件。
- 守护测试 10 例全绿：三面被清 + 不误删 + 他仓保留 + 单面失败隔离 + parts/content 脱敏 + caveat/unscrubbed 如实 + 端到端 sensitive 清操作面 + 普通模式不触碰对照。

## Task Commits

1. **Task 1: CodeChangeArchive file 级 scrub + TaskResult/ActionLog 可控清理** - `beca0283c` (feat)
2. **Task 2: loose-text 脱敏 + caveat/unscrubbed + 端到端 sensitive 守护** - `869f534ac` (feat)

**Plan metadata:** (this commit) docs: complete 23-03 plan

_非 TDD 计划：feat 一次到位 + 守护测试同提交（与 23-01/23-02 风格一致）。_

## Files Created/Modified
- `server/services/sensitive_purge.py` - 敏感清理委托模块：四面 helper + 入口 + 归一/切段/脱敏辅助 + caveat 常量。
- `server/tests/services/test_sensitive_purge.py` - 守护测试 10 例（Task 1 三面 6 例 + Task 2 loose/caveat/端到端 4 例）。

## Decisions Made
- **scrub recompute 不调 `parse_diff_files`**：该函数解析平台 MR API 的 `MRDiffFile` 对象而非解压后的 unified-diff 文本（W4 类型不符）。改为直接过滤既有 `files` JSON 列表重算计数 + 按 `diff --git` 边界切段剔除目标文件 diff，`decompress_diff`/`compress_diff` 复用 `knowledge.diff_archive` 纯函数重压缩。
- **关联键归一**：`_normalize_repo_url`（去 `.git` 后缀/末尾斜杠/小写）统一 `SubAgentSession.repo_url` ↔ `Repository.git_url`；不匹配的 TaskResult/ActionLog 保守不动，宁漏勿误删他仓记录（T-23-12）。
- **message 面诚实降级**：`Conversation` 绑 `Project` 而非 `Repository`，无稳定 repo↔message 关联键 → 只做 best-effort 子串脱敏（命中叶子替换占位符），prompt snapshot/备份/git object 记 `unscrubbed` + caveat，不做激进全删（过度清理威胁 T-23-13），不假装清除不可达面（T-23-11）。

## Deviations from Plan
None - plan executed exactly as written（含 W4 规避 `parse_diff_files` 的预案，已按 PLAN action 落实）。

## Issues Encountered
- 测试/ruff 运行器沿用项目 venv `server/.venv/bin/python -m pytest|-m ruff`（与 22/23 前序一致）；ruff 初次报 test 文件 import 排序（I001），`--fix` 自动整理后复跑 10 passed。

## User Setup Required
None - 敏感清理为数据级 scrub，无 schema 变更（`makemigrations --check` 干净），无外部服务配置。

## Next Phase Readiness
- 23-04（前端面板）：`run_cleanup(mode="sensitive")` 端到端已清操作记录面，`CleanupReport.sensitive` / `CleanupRun.sensitive` 携带 `scrubbed`（各面计数）+ `unscrubbed` + `caveat`，状态端点（23-02 `RepositoryCleanupStatusView`）已可原样透传——前端可如实回显「已清各面 + 未清面 + 不承诺物理消失 caveat」，兑现 §9.1 诚实边界。

## Self-Check: PASSED

- FOUND: `server/services/sensitive_purge.py`
- FOUND: `server/tests/services/test_sensitive_purge.py`
- FOUND: `.planning/phases/23-purge-reconcile/23-03-SUMMARY.md`
- FOUND commit: `beca0283c` (Task 1)
- FOUND commit: `869f534ac` (Task 2)

---
*Phase: 23-purge-reconcile*
*Completed: 2026-06-14*
