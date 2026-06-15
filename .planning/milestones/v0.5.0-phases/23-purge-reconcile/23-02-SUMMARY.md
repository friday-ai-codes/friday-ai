---
phase: 23-purge-reconcile
plan: 02
subsystem: api
tags: [reconcile, purge, cleanup, exclusion, async-orm, drf, structlog, background-runner]

# Dependency graph
requires:
  - phase: 22-fail-closed
    provides: services/exclusion.py build_matcher_for_repo（复用匹配器判定已索引文件是否命中排除）
  - phase: 23-purge-reconcile
    provides: 23-01 services/purge.py purge_file 统一删除入口（逐差异文件删净五面）
provides:
  - compute_reconciliation(repository_id) -> ReconcileReport（已索引 ∩ 排除差异 + degraded/error，EXCL-06/W3）
  - run_cleanup(repository_id, mode, paths?, cleanup_run_id?) -> CleanupReport（普通清理删净 + 敏感懒导入契约，EXCL-04）
  - CleanupRun 模型 + 迁移 0033（清理运行持久化：status/mode/counts/failures/sensitive，W1/W2）
  - RepositoryReconcileView（GET 差异含 degraded / POST 派发后台清理返回 run_id）
  - RepositoryCleanupStatusView（GET 最近 CleanupRun，sensitive unscrubbed/caveat 透传）
  - 审计埋点 log_purge_event(purge.started/completed)
affects: [23-03-sensitive-purge, 23-04-purge-frontend]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "对账双源并：FileIndex ∪ ChunkRegistry file_path 去重，避免单源漏报（T-23-05）"
    - "degraded 二分：匹配器构造失败置 degraded+error（不污染 single-file fail-closed），贯通 dataclass→serializer→client（W3）"
    - "后台清理派发：API 先建 CleanupRun(running) 拿 run_id，run_in_background 派发 run_cleanup，立即 202（D-04/T-23-08）"
    - "敏感面懒导入契约：mode=sensitive 函数体内 import services.sensitive_purge（23-03 提供），普通模式零依赖"

key-files:
  created:
    - server/services/purge_reconcile.py
    - server/repositories/migrations/0033_cleanup_run.py
    - server/tests/services/test_purge_reconcile.py
  modified:
    - server/repositories/models.py
    - server/repositories/views.py
    - server/repositories/urls.py
    - server/repositories/serializers.py

key-decisions:
  - "compute_reconciliation 仅在 build_matcher_for_repo 构造抛错时置 degraded；单文件 is_excluded 运行期异常由 matcher 内部 fail-closed（命中）兜底，不污染 degraded"
  - "run_cleanup 终态：有任一 failures → failed，否则 completed；普通模式 sensitive 恒 None"
  - "POST 在派发前 compute_reconciliation 取 match_count 即时回客户端（degraded 时为 0）；后台 run_cleanup 复算差异执行删除"
  - "状态路由 reconcile/status/ 注册于 reconcile/ 之前（exact match，顺序安全）"

patterns-established:
  - "对账失败可见（degraded）而非假干净；后台清理结果（含敏感未清面）经 CleanupRun 状态端点诚实回流前端"
  - "清理统一审计事件名 purge.started/purge.completed（mode/repository_id/match_count/failures）"

requirements-completed: [EXCL-04, EXCL-06]

# Metrics
duration: ~30min
completed: 2026-06-14
---

# Phase 23 Plan 02: 对账 + 两模式清理服务/API Summary

**`compute_reconciliation`（已索引 ∪ ChunkRegistry ∩ 现行匹配器，列出已索引但现命中排除的差异，匹配器构造失败置 degraded 不谎报已一致）+ `run_cleanup(normal)`（逐差异文件 purge_file 删净四面、对账归零）+ `CleanupRun` 持久化 + 对账/清理/状态 REST API（GET 差异 / POST 派发后台返回 run_id / GET 状态回流敏感未清面）+ 审计埋点，敏感分支懒导入契约就位。**

## Performance

- **Duration:** ~30 min
- **Completed:** 2026-06-14
- **Tasks:** 2
- **Files modified:** 7（3 created + 4 modified）

## Accomplishments
- 新建 `services/purge_reconcile.py`：`ReconcileReport`（含 degraded/error）、`CleanupReport`、`compute_reconciliation`、`run_cleanup`、`_indexed_file_paths`、`_schedule_summary_rebuild`、`log_purge_event`。
- 对账双源并（FileIndex ∪ ChunkRegistry）∩ 复用 Phase 22 `build_matcher_for_repo`，列出差异；匹配器构造失败 → `degraded=True` + `error`、`match_count=0`（W3，不谎报已一致）。
- 普通清理逐差异文件调 23-01 `purge_file` 删净五面，best-effort 逐文件隔离；清理后 best-effort 后台调度 repo_summaries + repo_index_nodes 重建（失败不致命）。
- `CleanupRun` 模型 + 迁移 0033（仅 CreateModel）：status/mode/match_count/failures/sensitive/started_at/completed_at/error，`(repository, -started_at)` 索引取最近一次。
- 敏感模式懒导入 `services.sensitive_purge.purge_sensitive_planes`（23-03 提供）→ 结果落 `CleanupReport.sensitive` + `CleanupRun.sensitive`；未就绪 → failures + `CleanupRun.error`，普通清理结果不受损。
- REST API：`GET …/reconcile/`（差异含 degraded）、`POST …/reconcile/`（先建 running 行拿 run_id，`run_in_background` 派发 run_cleanup，202 + {mode, match_count, dispatched, run_id}）、`GET …/reconcile/status/`（最近 CleanupRun，sensitive unscrubbed/caveat 原样透传；无记录 {status:none}）。
- 守护测试 15 例全绿：对账差异 + degraded + 普通清理删后无残留 + 对账归零 + 审计事件 + 非法 mode ValueError + 敏感懒导入失败隔离 + API GET/POST/status + 401/404。

## Task Commits

1. **Task 1 (RED): 对账/清理服务/API 失败守护测试** - `8f91c8cb7` (test)
2. **Task 1 (GREEN): CleanupRun 模型/迁移 + 对账(含 degraded) + 普通清理服务 + 审计** - `63f492be9` (feat)
3. **Task 2: 对账/清理/状态 REST API + serializer + 路由** - `b20f7bedf` (feat)

_TDD：Task 1 先 RED（test，模块/模型缺失 → 3 失败）后 GREEN（feat，6 服务层测试通过）；Task 2 补 API 层（共 15 passed）。GREEN 一次到位，无 refactor 提交。_

## Files Created/Modified
- `server/services/purge_reconcile.py` - 对账 + 两模式清理服务 + 审计埋点 + 摘要重建调度（含 degraded 语义）。
- `server/repositories/migrations/0033_cleanup_run.py` - CleanupRun 建表迁移（仅 CreateModel，依赖 0032）。
- `server/tests/services/test_purge_reconcile.py` - 服务层 + API 守护测试 15 例。
- `server/repositories/models.py` - 新增 `CleanupRun` 模型（Mode/Status TextChoices + (repository,-started_at) 索引）。
- `server/repositories/views.py` - 新增 `RepositoryReconcileView` / `RepositoryCleanupStatusView` + import run_in_background/compute_reconciliation/run_cleanup。
- `server/repositories/urls.py` - 注册 `repository-reconcile` + `repository-reconcile-status` 路由。
- `server/repositories/serializers.py` - 新增 `ReconcileReportSerializer` / `CleanupRequestSerializer` / `CleanupRunSerializer`。

## Decisions Made
- **degraded 边界**：仅 `build_matcher_for_repo` 构造抛错触发 degraded；单文件 `is_excluded` 运行期异常由 matcher 内部 fail-closed（命中）兜底，不污染 degraded——避免把「判定不可信」与「构造不可信」混为一谈。
- **清理终态**：任一 `failures` → `failed`，否则 `completed`；普通模式 `sensitive` 恒 `None`。
- **POST match_count**：派发前 `compute_reconciliation` 取命中数即时回客户端（degraded 时为 0），后台 `run_cleanup` 再复算执行删除——API 响应诚实反映「将清理多少」，后台保证「真正删干净」。
- **路由顺序**：`reconcile/status/` 注册于 `reconcile/` 之前（Django path exact match，顺序安全且语义清晰）。

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
- 测试运行器沿用项目 venv `server/.venv/bin/python -m pytest`（与 22-01/23-01 一致，`uv run pytest` 在本机回落全局 pytest）。
- ruff 初次报 test 文件两处未使用 `sync_to_async` import（GREEN 阶段清理），随 feat 提交修复。

## User Setup Required
None - 无外部服务配置；CleanupRun 迁移仅建表，既有部署升级向后兼容。

## Next Phase Readiness
- 23-03（敏感面清理）：`run_cleanup(mode="sensitive")` 已留好懒导入契约 `services.sensitive_purge.purge_sensitive_planes(repository_id, purged_paths)`，其返回 dict（含 unscrubbed/caveat）落 `CleanupRun.sensitive`，状态端点已可透传回显。
- 23-04（前端 UI）：对账 GET（含 degraded）、清理 POST（run_id）、状态 GET（含 sensitive 未清面）三端点契约就位。

## Self-Check: PASSED

---
*Phase: 23-purge-reconcile*
*Completed: 2026-06-14*
