---
phase: 25-commit-index-lineref
plan: 03
subsystem: api
tags: [rag, commit-index, qdrant, embedding, exclusion, fail-closed, git, incremental, uuid5]

# Dependency graph
requires:
  - phase: 22-fail-closed
    provides: "services.exclusion.build_matcher_for_repo / is_excluded / normalize_rel_path 单一匹配器（commit 变更摘要 fail-closed 过滤）"
  - phase: 14-mr-archive
    provides: "services.git_platform.base.truncate_diff_lines 变更摘要截断 helper"
provides:
  - "Repository.commit_index_boundary_sha：commit 历史索引专用增量边界（独立于 last_indexed_commit_sha）"
  - "migration 0035_repository_commit_index_boundary（AddField，nullable，无回填）"
  - "services/commit_index.py::index_commits(repository_id, repo_path)：git log → 排除过滤截断 → embedding → upsert kind=commit → 推进边界"
affects: [25-04 索引流程挂接, search_rag commit 文档召回, 多仓检索]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "commit 文档落主 collection + payload kind=commit（与代码 chunk 同检索面可区分/过滤）"
    - "确定性 uuid5 point id（uuid5(ns, repo_id:sha)）保重索引同 sha 不重复"
    - "合成 file_path=.friday/commits/{sha} + chunk_index=0 保既有去重 key 唯一且不被排除规则误命中"
    - "增量边界 boundary..HEAD + 失效回退首轮 bounded；upsert 成功才推进边界（绝不丢 commit）"
    - "git log NUL/RS(%x00/%x1e) 分隔解析（子进程参数不可内嵌 NUL，--format 用占位符）"

key-files:
  created:
    - server/services/commit_index.py
    - server/repositories/migrations/0035_repository_commit_index_boundary.py
    - server/tests/services/test_commit_index.py
  modified:
    - server/repositories/models.py

key-decisions:
  - "commit_index_boundary_sha 独立字段，绝不复用 last_indexed_commit_sha（代码 chunk 边界），避免口径串味"
  - "首轮 bounded 全量 COMMIT_INDEX_FIRST_RUN_CAP=500 + --no-merges 减量（T-25-11 DoS 兜底）"
  - "变更摘要只含路径不内联 diff 正文；被排除文件全程不进摘要/changed_files/content（T-25-08）"
  - "hybrid 判定与 sparse 生成复用 IndexerService._is_hybrid_enabled / _generate_sparse_vectors，避免双份真相"

patterns-established:
  - "commit 历史摄取唯一入口 services.commit_index.index_commits；排除判定复用 22 单一匹配器不另写过滤"
  - "边界推进严格幂等：无新 commit/embedding 缺失/upsert 失败均不推进 boundary"

requirements-completed: [IDX-01]

# Metrics
duration: ~13min
completed: 2026-06-15
---

# Phase 25 Plan 03: Commit 历史索引（IDX-01）Summary

**git 历史按 commit 产出 RAG 文档（message + author + 变更文件路径摘要），经 Phase 22 单一匹配器 fail-closed 剔除被排除文件、截断、embedding 入 Qdrant 主 collection 并打 kind=commit payload，确定性 uuid5 point id + 合成 file_path 保 dedup，增量 boundary..HEAD 只索引新 commit、upsert 成功才推进边界。**

## Performance

- **Duration:** ~13 min
- **Tasks:** 2
- **Files modified:** 4（3 created + 1 modified）

## Accomplishments
- `Repository.commit_index_boundary_sha` 字段 + migration 0035（nullable，无回填，向后兼容 per D-04）—— commit 索引专用增量边界，独立于代码 chunk 索引边界 `last_indexed_commit_sha`。
- `services/commit_index.py::index_commits`：读边界 → git log(增量 `boundary..HEAD` / 首轮 `--max-count` bounded，boundary 失效回退) → `git diff-tree` 取变更文件 → Phase 22 matcher fail-closed 过滤 → 构建文档（message+author+committed_at+过滤后路径摘要，截断）→ embedding → 构建 hybrid/dense point（确定性 uuid5 id）→ upsert kind=commit → upsert 成功才推进 boundary 到 HEAD。
- 7 例守护测试全绿：commit 文档构建（kind=commit/payload/content）、被排除文件不入摘要（.env/*.pem fail-closed）、增量只取新 commit + 二次同 HEAD 索引 0 不再 upsert、确定性 uuid5 dedup、大摘要截断、upsert 失败不推进边界、空仓库返回 0。

## Task Commits

Each task was committed atomically:

1. **Task 1: commit_index_boundary_sha 字段 + migration 0035** - `5a69406c7` (feat)
2. **Task 2: index_commits 摄取服务 + 守护测试** - `6aa4d3dc1` (feat)

**Plan metadata:** （见 docs 提交）

## Files Created/Modified
- `server/services/commit_index.py` - commit 历史摄取服务（git log 解析 + 排除过滤 + 截断 + embedding + upsert kind=commit + 增量边界）
- `server/repositories/migrations/0035_repository_commit_index_boundary.py` - boundary 字段 AddField 迁移（nullable，无回填）
- `server/tests/services/test_commit_index.py` - 7 例守护测试（真实临时 git 仓库驱动，仅 mock embedding/qdrant/hybrid）
- `server/repositories/models.py` - 新增 `Repository.commit_index_boundary_sha`

## Decisions Made
- **独立边界字段**：`commit_index_boundary_sha` 与 `last_indexed_commit_sha`（代码 chunk 边界）分离，注释强调切勿混用，避免两套索引口径串味。
- **首轮 bounded 全量**：boundary 空或失效（force-push/rebase 致 `boundary..HEAD` git log 报错）回退 `--max-count=COMMIT_INDEX_FIRST_RUN_CAP(500)` + `--no-merges`（T-25-11）。
- **git log 解析分隔符**：`--format` 用 git 占位符 `%x00`(字段)/`%x1e`(记录)，解析按实际字节切分；子进程参数本身不能内嵌 NUL（首跑触发 `ValueError: embedded null byte`，改用占位符修复）。
- **dedup 面隔离**：合成 `file_path=.friday/commits/{sha}` + `chunk_index=0` 保既有去重 key 唯一且不被排除规则误命中；确定性 `uuid5(ns, repo_id:sha)` point id 保重索引同 sha 命中同 point（T-25-10）。
- **边界推进严格性**：无新 commit / embedding 缺失 / upsert 失败均不推进 boundary（绝不丢 commit，T-25-09）。
- **hybrid 复用**：是否生成 sparse 向量复用 `IndexerService._is_hybrid_enabled` / `_generate_sparse_vectors`，commit point 结构与 `_build_points` hybrid 形态一致，匹配 collection schema。

## Deviations from Plan

None - plan executed exactly as written.

（说明：`git log --format` 用 `%x00`/`%x1e` 占位符而非 PLAN action 字面描述的「`\x00` 字段分隔」属落地细节修正——子进程参数不可内嵌 NUL，git 占位符在 git 侧展开为相同字节，解析口径与 PLAN 完全一致；`git diff-tree` 加 `--root` 以纳入根 commit 变更文件，属正确性细节。均不改变行为契约。）

## Issues Encountered
- 首次运行测试 `ValueError: embedded null byte`：`--format` 实参内嵌真实 NUL 字节导致 `create_subprocess_exec` 拒绝。改为 git 占位符 `%x00`/`%x1e`（git 侧展开为 NUL/RS），解析侧仍按实际字节切分。7 例测试随后全绿。

## User Setup Required
None - 无外部服务配置；既有部署升级后 `commit_index_boundary_sha=NULL`，首次 index_commits 走首轮 bounded 全量，向后兼容。

## Next Phase Readiness
- 25-04 可直接 `from services.commit_index import index_commits` 挂接 full/incremental 索引流程（best-effort 包裹，本服务内部对单 commit 失败/整体不抛致命）。
- 检索侧无需改动：commit 文档落主 collection + kind=commit，经既有 `search_rag` chokepoint 自然召回，且同受 Phase 22 排除约束。
- 注意：commit 文档 payload 含 `kind=commit` 区分维度，下游若需「仅代码 chunk / 仅 commit」过滤可据此筛选（本 plan 未改检索）。

## Self-Check: PASSED

- Files: commit_index.py / 0035_repository_commit_index_boundary.py / test_commit_index.py / 25-03-SUMMARY.md — all FOUND.
- Commits: 5a69406c7 / 6aa4d3dc1 — both FOUND (git cat-file -t = commit).
- Tests: 7 passed (`server/.venv/bin/python -m pytest tests/services/test_commit_index.py`).
- `makemigrations --check --dry-run repositories` — clean (No changes detected)。
- ruff check + format clean；mypy `services/commit_index.py` — Success no issues。
- grep 守护：`build_matcher_for_repo` / `is_excluded` 仅经 services.exclusion 复用，未另写过滤。

---
*Phase: 25-commit-index-lineref*
*Completed: 2026-06-15*
