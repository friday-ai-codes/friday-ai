---
phase: 33-hist-diff-bitemporal
plan: 01
subsystem: knowledge
tags: [git-platform, gitlab, github, diff-archive, bitemporal, modifies-chunk, commit-anchor, merge-commit-sha]

# Dependency graph
requires:
  - phase: 14-knowledge-diff
    provides: knowledge.diff_archive（archive_code_change / resolve_modified_chunks / build_modifies_chunk_edge_spec / apply_edge_specs valid_at 收口）
  - phase: 32-one-click-ingest
    provides: delivery.services.ingest_orchestrator._ingest_mr_diff（合成 commit_sha 现状，WR-02 待修）+ knowledge.diff_archive.aarchive_exists
  - phase: 26-git-credentials
    provides: services.git_credentials.aresolve_git_token（per-repo 优先 → 同 host 凭证池）
provides:
  - services.git_platform.models.MRMetadataResult（merge_commit_sha/target_branch/source_branch/merged_at 值对象）
  - services.git_platform.base.GitPlatformClient.get_merge_request_metadata（抽象方法，双子类强制实现）
  - GitLabClient/GitHubClient.get_merge_request_metadata（真实 merge commit 元数据拉取，naive→aware 归一）
  - knowledge.diff_archive.aresolve_mr_commit_anchor（历史 MR commit 锚解析唯一 helper）
  - MODIFIES_CHUNK EdgeSpec.metadata.chunk_content_hash（冻结当年 chunk 版本指纹，供 HDIFF-02 对账）
  - 一键摄取 MR 步 commit 锚定真实 merge_commit_sha + target_branch（WR-02 收口）
affects: [33-02（HDIFF-02 重索引对账置 invalid_at + as-of 查询，消费 chunk_content_hash 与 commit 锚定 valid_at）]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "MR/PR 元数据拉取沿用 MRDiffResult 降级范式（失败 success=False 不上抛，token 绝不入日志）"
    - "merged_at naive→aware 归一（django.utils.timezone.make_aware + dateparse.parse_datetime，USE_TZ=True 下游 require_aware 防线）"
    - "commit 锚定：commit_sha=merge_commit_sha、base_branch=target_branch（绝不假设 master，DOMAIN §1.5）"
    - "anchor 不可用如实 skipped 不合成（WR-02：避免伪历史快照污染对账 T-33-03）"
    - "chunk 指纹批量回填（一次 ChunkRegistry.values_list 建 dict，覆盖 EdgeSpec.metadata 占位键）"

key-files:
  created: []
  modified:
    - server/services/git_platform/models.py
    - server/services/git_platform/base.py
    - server/services/git_platform/gitlab_client.py
    - server/services/git_platform/github_client.py
    - server/services/git_platform/__init__.py
    - server/knowledge/diff_archive.py
    - server/delivery/services/ingest_orchestrator.py
    - server/tests/knowledge/conftest.py
    - server/tests/knowledge/test_diff_archive.py
    - server/tests/knowledge/test_modifies_chunk.py
    - server/tests/delivery/conftest.py
    - server/tests/delivery/test_ingest_orchestrator.py

key-decisions:
  - "复用既有 CodeChangeArchive.commit_sha/base_branch 表达 commit 锚定，不新增 model 字段/migration（CONTEXT Claude's Discretion）"
  - "chunk_content_hash 落 KnowledgeEdge.metadata（JSONField）冻结指纹，无 schema 变更"
  - "no-credential 现归为 mr_diff skipped（anchor 解析早于 archive 拦截）而非 failed —— 反映「无法取得真实 commit 锚则不归档」的新语义"

patterns-established:
  - "aresolve_mr_commit_anchor：历史 MR commit 锚解析唯一 helper，凭证→client→元数据三步降级返回 None（仅 warning）"
  - "metadata 占位键 chunk_content_hash='' 保持形状稳定，末尾批量回填覆盖"

requirements-completed: [HDIFF-01]

# Metrics
duration: ~30min
completed: 2026-06-15
---

# Phase 33 Plan 01: 历史 MR diff 冻结为 commit 锚定快照 Summary

**给 git platform client 增加 `get_merge_request_metadata`（双客户端拉真实 `merge_commit_sha`/`target_branch`/`merged_at`），新增 `aresolve_mr_commit_anchor` 历史 commit 锚解析 helper，把一键摄取 MR 步从合成 `mr-{iid}` 改为真实 merge commit 锚定（WR-02），并在 MODIFIES_CHUNK 边 metadata 冻结 `chunk_content_hash` 指纹供 HDIFF-02 对账。**

## Performance

- **Duration:** ~30 min
- **Started:** 2026-06-15T12:39Z
- **Completed:** 2026-06-15T12:47Z
- **Tasks:** 3
- **Files modified:** 12

## Accomplishments
- `MRMetadataResult` 值对象 + `GitPlatformClient.get_merge_request_metadata` 抽象方法，GitLab/GitHub 双实现（naive merged_at 归一为 aware，失败 success=False 不上抛，token 不入日志）。
- `aresolve_mr_commit_anchor(repository, mr_id)`：凭证→client→元数据三步，缺凭证/拉取失败/空 merge_commit_sha 一律返回 None（仅 warning），成功返回真实 commit 锚。
- `resolve_modified_chunks` 在每条 MODIFIES_CHUNK EdgeSpec.metadata 冻结 `chunk_content_hash`（批量回填 ChunkRegistry.content_hash；registry 缺行保持 ""，不阻断建边）。
- `_ingest_mr_diff` 收口 WR-02：`commit_sha=merge_commit_sha`、`base_branch=target_branch`、`event_time=merged_at`（edge valid_at 锚定 commit 业务时间）；anchor 不可用如实 `skipped` 不再合成归档。

## Task Commits

Each task was committed atomically:

1. **Task 1: git platform client 增加 MR/PR 元数据拉取能力** - `76993a2f` (feat)
2. **Task 2: diff_archive commit 锚解析 helper + 冻结 chunk 指纹** - `daf63942` (test, RED) → `7d25b49f` (feat, GREEN)
3. **Task 3: 一键摄取 MR 步改用真实 merge_commit_sha + target_branch（WR-02）** - `b3b0e952` (feat)

_Note: Task 2 is a TDD task (RED `test(33-01)` → GREEN `feat(33-01)`)._

## Files Created/Modified
- `server/services/git_platform/models.py` — 新增 `MRMetadataResult` dataclass（import datetime）。
- `server/services/git_platform/base.py` — `get_merge_request_metadata` 抽象方法 + import。
- `server/services/git_platform/gitlab_client.py` — GitLab 实现（mergerequests.get + ISO8601 merged_at 解析归一）。
- `server/services/git_platform/github_client.py` — GitHub 实现（get_pull + base/head ref + naive merged_at 归一）。
- `server/services/git_platform/__init__.py` — 导出 `MRMetadataResult`。
- `server/knowledge/diff_archive.py` — `aresolve_mr_commit_anchor` helper、`__all__` 补项、`_chunk_edge_spec` 占位键、`resolve_modified_chunks` 末尾批量回填 chunk 指纹。
- `server/delivery/services/ingest_orchestrator.py` — `_ingest_mr_diff` 改用真实 commit 锚 + payload 新增 `target_branch`。
- `server/tests/knowledge/conftest.py` / `server/tests/delivery/conftest.py` — FakeGitPlatformClient 增加 `get_merge_request_metadata` + 可配置 `mr_metadata` seam。
- `server/tests/knowledge/test_diff_archive.py` — `TestMrCommitAnchor` 四分支。
- `server/tests/knowledge/test_modifies_chunk.py` — chunk_content_hash 三路径断言 + `_make_chunk` 加 content_hash/chunk_id 参数。
- `server/tests/delivery/test_ingest_orchestrator.py` — 强化全 ok 断言（真实 sha/target_branch/event_time）+ 新增 anchor 不可用 skipped、no-credential skipped、MODIFIES_CHUNK valid_at=merged_at 用例。

## Decisions Made
- 复用 `CodeChangeArchive.commit_sha`/`base_branch` 表达 commit 锚定，不新增字段/migration（CONTEXT 授权）。
- `chunk_content_hash` 直接落 `KnowledgeEdge.metadata`（JSONField），无 schema 变更。
- no-credential 在新流程下归为 `mr_diff skipped`（anchor 解析早于 archive 拦截），语义上「取不到真实 commit 锚就不归档」。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] delivery 测试 fake 需同步补 get_merge_request_metadata**
- **Found during:** Task 3
- **Issue:** orchestrator 测试用的是 `server/tests/delivery/conftest.py` 中独立复刻的 `FakeGitPlatformClient`（conftest 作用域不跨目录），plan 仅提及 `tests/knowledge/conftest.py`；不补则 `aresolve_mr_commit_anchor` 调用 fake 缺方法 AttributeError。
- **Fix:** 在 delivery conftest 的 fake 同款增加 `get_merge_request_metadata` + 默认 `mr_metadata`（target_branch=release/v1 非 master）。
- **Files modified:** server/tests/delivery/conftest.py
- **Verification:** `pytest tests/delivery/test_ingest_orchestrator.py -q` 11 passed
- **Committed in:** `b3b0e952` (Task 3 commit)

**2. [Rule 1 - Bug] 既有 no-credential 用例语义随新流程调整**
- **Found during:** Task 3
- **Issue:** 既有 `test_mr_archive_none_no_credential_marks_failed` 断言 mr_diff=failed；新流程 anchor 解析在 archive 之前拦截缺凭证 → 应为 skipped。
- **Fix:** 改名 `test_mr_no_credential_marks_skipped` 并断言 skipped + 无合成归档（plan 明确「按真实 commit_sha 调整既有断言」）。
- **Files modified:** server/tests/delivery/test_ingest_orchestrator.py
- **Verification:** 用例通过；语义与 WR-02「取不到真实锚不归档」一致。
- **Committed in:** `b3b0e952` (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug)
**Impact on plan:** 均为落地 plan 既定意图所必需（delivery 测试 seam 与既有断言随新语义调整），无范围蔓延。

## Issues Encountered
- Task 1 plan 给的 `python -c "import GitLabClient"` 校验在裸 Python 下因 Django settings 未配置而报 ImproperlyConfigured（包 `__init__` import `repositories.models`）；非代码缺陷——ruff 通过，且在 `DJANGO_SETTINGS_MODULE=friday.settings` + `django.setup()` 下双客户端可正常实例化、Task 2/3 pytest 在 Django 下全绿。

## Known Stubs
None —— 无悬空数据/占位渲染；`chunk_content_hash` 默认 "" 是有意占位（registry 缺行的弱引用 chunk），非未接线 stub。

## Threat Flags
None —— 未引入计划 `<threat_model>` 之外的新信任边界；MR 元数据（target_branch/source_branch/merge_commit_sha）仅作字符串存储与 commit 锚定，绝不拼入 shell 或作为新 fetch URL（SSRF 边界由 P32 `aresolve_repo_and_mr` 守住）；token 经 `aresolve_git_token` 取用，失败仅记 mr_id/repository_id（T-33-01）。

## Test Results
- `pytest tests/delivery/test_ingest_orchestrator.py tests/knowledge/test_diff_archive.py tests/knowledge/test_modifies_chunk.py -q` → **44 passed**。
- `ruff check`（services/git_platform/ knowledge/diff_archive.py delivery/services/ingest_orchestrator.py + 改动测试）→ All checks passed。

## Next Phase Readiness
- HDIFF-01 commit 锚定 + chunk 指纹冻结就位，33-02（HDIFF-02）可消费 `chunk_content_hash` 与 commit 锚定 `valid_at` 做重索引对账置 `invalid_at` + as-of 查询。
- 无新增 model 字段/migration；无阻断项。

## Self-Check: PASSED

- Files: models.py / diff_archive.py / ingest_orchestrator.py / 33-01-SUMMARY.md all FOUND.
- Commits: `76993a2f` / `daf63942` / `7d25b49f` / `b3b0e952` all present in git log.

---
*Phase: 33-hist-diff-bitemporal*
*Completed: 2026-06-15*
