---
phase: 23-purge-reconcile
verified: 2026-06-14T15:52:00Z
status: passed
score: 22/22 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: null
deferred:
  - truth: "前端浏览器端真实交互（视觉渲染、真实 Qdrant 删除、端到端用户流）"
    addressed_in: "UAT（autonomous mode：前端 browser human check 按指示作非阻塞 UAT 项）"
    evidence: "用户指示：Treat any frontend-only browser human check as a deferred non-blocking UAT item"
---

# Phase 23: purge-reconcile Verification Report

**Phase Goal:** 新增排除后可清理存量派生数据，区分普通排除与敏感清理两模式 + 对账 UI。
**Verified:** 2026-06-14T15:52:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | 统一 `purge_file` 覆盖 Qdrant 主 collection | ✓ VERIFIED | `purge.py:119-133` 调 `QdrantService.delete_by_file_path` |
| 2 | `purge_file` 覆盖 overlay collections（PF-05） | ✓ VERIFIED | `purge.py:135-166` 枚举 `RepositoryBranchIndex.collection_name` 逐一 `delete_by_payload_field`；`qdrant_service.py:1085` 方法存在 |
| 3 | `purge_file` 删 FileIndex 行 | ✓ VERIFIED | `purge.py:168-184` `FileIndex.objects.filter(...).adelete()` |
| 4 | `purge_file` 删 ChunkRegistry 经 pre_delete 信号联动清 ChunkEdge | ✓ VERIFIED | `purge.py:189-204` queryset `.adelete()`（不绕过信号） |
| 5 | `purge_file` 删 codegraph（base+各分支） | ✓ VERIFIED | `purge.py:206-224` 逐分支 `GraphWriter.adelete_for_files` |
| 6 | `purge_file` 幂等、best-effort 逐面隔离 | ✓ VERIFIED | 各面独立 try/except + `PurgeResult.failures`；`test_purge_file.py` 幂等/未索引文件用例通过 |
| 7 | 索引删除路径收敛到 `purge_file`（PF-03） | ✓ VERIFIED | `indexer.py:1793` 与 `indexer.py:2236` 两条 DELETE 分支均调 `purge_file`；冗余 FileIndex 删除循环已移除（`indexer.py:2433`） |
| 8 | 对账枚举已索引文件（FileIndex ∪ ChunkRegistry）∩ 匹配器列差异（EXCL-06） | ✓ VERIFIED | `purge_reconcile.py:81-136` 双源并去重 + `build_matcher_for_repo` + `is_excluded` |
| 9 | 匹配器构造失败 → degraded+error，不谎报已一致（W3） | ✓ VERIFIED | `purge_reconcile.py:116-129` 构造异常置 `degraded=True/error/match_count=0`；`test_*_degraded*` 通过 |
| 10 | 普通清理逐差异文件 `purge_file` 删净 + 对账归零（EXCL-04） | ✓ VERIFIED | `purge_reconcile.py:228-243` + 服务层测试（删后无残留 + match_count==0） |
| 11 | 清理后调度 repo_summaries/index_nodes 重建（best-effort） | ✓ VERIFIED | `purge_reconcile.py:284-316`；`RepoSummaryBuilder.build` / `RepoIndexTreeBuilder.build` 签名匹配存在 |
| 12 | 每次清理持久化 `CleanupRun`（status/mode/counts/sensitive） | ✓ VERIFIED | `models.py:795` 模型 + `migration 0033`（makemigrations --check 干净）；`_finalize_run` 写终态 |
| 13 | 审计埋点 `purge.started`/`purge.completed` | ✓ VERIFIED | `purge_reconcile.py:223,274,319-334` `log_purge_event` |
| 14 | GET 对账 API 返回差异+degraded | ✓ VERIFIED | `views.py:1132-1140` + `ReconcileReportSerializer`（含 degraded/error） |
| 15 | POST 清理 API 派发后台返回 run_id（202） | ✓ VERIFIED | `views.py:1142-1177` 先建 running 行 → `run_in_background` → 202 |
| 16 | GET status API 返回最近 CleanupRun（含 sensitive unscrubbed/caveat） | ✓ VERIFIED | `views.py:1190-1205` + `CleanupRunSerializer` 透传 `sensitive` |
| 17 | mode=sensitive 懒导入委托 `purge_sensitive_planes`；普通模式零依赖 | ✓ VERIFIED | `purge_reconcile.py:246-259` 函数体内懒导入 + 失败隔离 |
| 18 | 敏感清理额外覆盖 CodeChangeArchive（file 级 scrub）（EXCL-05） | ✓ VERIFIED | `sensitive_purge.py:122-209` 剔除 files 项+diff 段+重算计数；仅含该文件整行删；含他文件保留 |
| 19 | 敏感清理覆盖 TaskResult / ActionLog（repo_url 关联） | ✓ VERIFIED | `sensitive_purge.py:212-328` 经 `_normalize_repo_url` 关联；关联不确定保守不动（T-23-12） |
| 20 | 无 file 关联面子串脱敏 + 诚实上报 unscrubbed + caveat | ✓ VERIFIED | `sensitive_purge.py:331-433` `_scrub_loose_text_planes` + `UNSCRUBBED_PLANES` + `SENSITIVE_PLANES_CAVEAT`（不假装清除 git/备份） |
| 21 | 前端对账面板：差异/degraded 警示/双清理入口/强确认/状态回显真实 unscrubbed+caveat（W1/W2/W3） | ✓ VERIFIED | `ReconcilePanel.vue` 全覆盖；degraded 禁用清理；敏感强确认含「不可逆/不承诺物理消失」；status 轮询渲染真实 `sensitive.unscrubbed`/`caveat` |
| 22 | 面板挂在仓库详情页排除规则面板旁 | ✓ VERIFIED | `[id]/index.vue:14` import + `:611` `<ReconcilePanel :repository-id>` |

**Score:** 22/22 truths verified

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | 前端浏览器端真实交互（视觉、真实 Qdrant 删除、端到端用户流） | UAT（非阻塞） | 用户指示：autonomous mode 下 frontend browser human check 作非阻塞 UAT 项 |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `server/services/purge.py` | 统一删除入口 + PurgeResult | ✓ VERIFIED | 238 行，五面覆盖，导出 `purge_file`/`PurgeResult` |
| `server/services/purge_reconcile.py` | 对账 + 两模式清理 + 审计 | ✓ VERIFIED | 335 行，`compute_reconciliation`/`run_cleanup`/`log_purge_event` |
| `server/services/sensitive_purge.py` | 敏感面 scrub | ✓ VERIFIED | 434 行，四面 helper + caveat/unscrubbed |
| `server/repositories/models.py::CleanupRun` | 清理运行持久化 | ✓ VERIFIED | `models.py:795` + 迁移 0033 |
| `server/repositories/migrations/0033_cleanup_run.py` | CreateModel | ✓ VERIFIED | 仅 CreateModel，依赖 0032；makemigrations --check 干净 |
| `web/src/api/reconcile.ts` | reconcileApi + 类型 | ✓ VERIFIED | getReconcile/cleanup/getCleanupStatus + degraded/sensitive 类型 |
| `web/src/components/repository/ReconcilePanel.vue` | 对账/清理面板 | ✓ VERIFIED | 244 行，全功能覆盖 |

### Key Link Verification

| From | To | Via | Status |
|------|----|----|--------|
| `purge_file` | `QdrantService.delete_by_file_path/delete_by_payload_field` | 主+overlay 删除 | ✓ WIRED |
| `indexer.run_incremental_index/run_git_diff_index` | `services.purge.purge_file` | DELETE 分支收敛 | ✓ WIRED (2 call sites) |
| `compute_reconciliation` | `services.exclusion.build_matcher_for_repo` | 复用 Phase 22 匹配器 | ✓ WIRED |
| `run_cleanup` | `services.purge.purge_file` | 逐差异文件删除 | ✓ WIRED |
| `run_cleanup` (sensitive) | `services.sensitive_purge.purge_sensitive_planes` | 懒导入委托 | ✓ WIRED |
| `RepositoryReconcileView` | `compute_reconciliation`/`run_cleanup` | GET/POST | ✓ WIRED |
| `RepositoryCleanupStatusView` | `CleanupRun` | GET 最近运行 | ✓ WIRED |
| `ReconcilePanel.vue` | `reconcileApi` | TanStack Query + mutation | ✓ WIRED |
| `[id]/index.vue` | `ReconcilePanel` | 挂在 ExclusionRulesPanel 旁 | ✓ WIRED |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| 后端 purge/reconcile/sensitive 测试 | `pytest test_purge_file.py test_purge_reconcile.py test_sensitive_purge.py` | 29 passed | ✓ PASS |
| 前端面板守护测试 | `vitest run ReconcilePanel.spec.ts` | 5 passed | ✓ PASS |
| 迁移一致性 | `makemigrations --check --dry-run repositories` | No changes detected | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| EXCL-04 | 23-01, 23-02 | 普通排除清理删派生数据 | ✓ SATISFIED | purge_file 五面 + run_cleanup normal + 对账归零（truths 1-12） |
| EXCL-05 | 23-03 | 敏感清理额外清操作记录面 | ✓ SATISFIED | purge_sensitive_planes 四面（truths 18-20） |
| EXCL-06 | 23-02, 23-04 | UI 对比规则 vs 已索引 + 一键清理 | ✓ SATISFIED | 对账 API + ReconcilePanel（truths 8,14-16,21-22） |
| PF-03 | 23-01 | incremental 删除收敛 purge_file | ✓ SATISFIED | indexer 两条 DELETE 路径（truth 7） |
| PF-05 | 23-01 | overlay 随 file_path 删除 | ✓ SATISFIED | overlay 枚举删除（truth 2） |

> 备注：`.planning/REQUIREMENTS.md` 中 EXCL-04/EXCL-05 复选框仍为 `[ ]`（EXCL-06 为 `[x]`）。三者代码实现均已验证落地，复选框状态为执行器未回填，非实现缺口；建议勾选。

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `sensitive_purge.py` | 42,274 | `REDACTION_PLACEHOLDER` 常量 | ℹ️ Info | 合法脱敏占位符常量名，非 stub 标记 |

无 `TBD/FIXME/XXX` 债务标记；无空实现 / 假数据 stub。

### Gaps Summary

无阻断性缺口。Phase 23 三条成功标准在代码层全部落地并由 29 个后端 + 5 个前端守护测试证明：
- **普通清理删净五面 + PF-03/PF-05 收口 + 对账归零**（EXCL-04）；
- **敏感清理额外覆盖 CodeChangeArchive/TaskResult/ActionLog/message 文本面，诚实上报 unscrubbed+caveat、不过度清理**（EXCL-05）；
- **对账/清理/状态 REST API + ReconcilePanel 前端可见闭环（degraded 警示、双入口强确认、真实结果回显）挂载到位**（EXCL-06）。

唯一非阻塞 UAT 项为前端浏览器端真实交互验证（按 autonomous mode 指示作非阻塞处理）。

---

_Verified: 2026-06-14T15:52:00Z_
_Verifier: Claude (gsd-verifier)_
