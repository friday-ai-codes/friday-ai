---
phase: 61-migrate
reviewed: 2026-06-20T04:35:00Z
depth: deep
files_reviewed: 18
files_reviewed_list:
  - server/durable/tasks_impl.py
  - server/durable/tasks.py
  - server/durable/handlers.py
  - server/durable/apps.py
  - server/durable/backends.py
  - server/durable/service.py
  - server/durable/reconcile.py
  - server/durable/management/commands/migrate_resumable_to_durable.py
  - server/repositories/index_views.py
  - server/repositories/views.py
  - server/repositories/apps.py
  - server/codegraph/views.py
  - server/codegraph/apps.py
  - server/tasks/index_trigger_tasks.py
  - server/resumable/handlers.py
  - server/resumable/models.py
  - server/resumable/migrations/0002_resumable_migrated.py
  - server/services/background_runner.py
findings:
  critical: 0
  warning: 2
  info: 2
  total: 4
status: clean
fixes_applied: 2026-06-20T05:05:00Z
---

# Phase 61: Code Review Report

**Reviewed:** 2026-06-20T04:35:00Z
**Depth:** deep（含跨文件 import/call-chain 追踪 + 双后端契约核对 + 关键测试实跑）
**Files Reviewed:** 18（源文件，不含测试）
**Status:** issues_found

## Summary

本阶段把 index/graph 后台任务从 `ResumableTask`/`background_runner` 迁移到 Phase 60 的 `DurableTaskService`，
整体实现质量高、与计划意图一致，**未发现 BLOCKER 级生产正确性缺陷**。逐项确认了用户列出的关键正确性检查：

- **5 处入队点全部迁移**：`index_views._schedule_index`(#1)、`views._schedule_default_branch_rolling_index`(#2)、
  `index_trigger_tasks.trigger_auto_index`(#3)、`codegraph.views.CodegraphRebuildView`(#4)、
  `resumable.handlers.resume_index/resume_graph`(#5) 均改 `DurableTaskService.defer`，queue/deterministic key
  正确；这 5 个生产文件零 `wrap_resumable`/`submit_resumable` 残留（`wrap_resumable`/`submit_resumable` 仅留在
  `resumable/service.py` 定义处）。chat/RAG 流式问答边界保留（recovery 仅注册 INDEX/GRAPH handler，CHAT 不进队列）。
- **双后端 payload 契约一致**：procrastinate 经 `@app.task` 包壳 + `defer_async(**payload)`、in-process 经
  `handlers.py` 的 `**payload` adapter，二者共用 `tasks_impl.py` 同一 keyword-only 任务体，键集合一致，不会一边炸。
- **reconcile 安全语义正确**：两处 reconcile 经 `has_active_durable_job_sync` → `DurableTaskService.has_active_by_key`
  按 queueing_lock 查活跃集（todo/doing/scheduled），**不**走 `get(numeric id)`；有在途 durable job 则保留
  RUNNING（仓库聚合态 + History 行均排除），非 durable(SQLite) 维持旧"标 FAILED"，fail-safe 朝标 FAILED 侧兜底；
  `reconcile.py` 零直接 import procrastinate。
- **一次性迁移命令**：只扫 PENDING/RUNNING + 条件 update 防并发 → 幂等可重入；deterministic key 去重；显式
  payload 白名单（repository_id/history_id/branch/trigger）避免 `run_index/run_graph(**payload)` 因额外键抛
  TypeError；非 durable 后端清晰中文提示、不静默迁移、不崩溃；MIGRATED 行因 `recoverable_target_ids` 仅查
  status=RUNNING 被天然排除（不双跑）。
- **idempotency / 真相源**：deterministic key + FileIndex/GraphFileIndex checkpoint + History 在入队点创建保持
  进度真相源，零改动。无泄密、payload 仅含内部 UUID，结构化 structlog 日志。

发现的问题集中在**测试侧契约同步缺失**与**reconcile 在真实 Postgres 多仓库路径下的健壮性/覆盖盲区**，详见下。

### 两处预存失败的归因结论（用户要求确认）

`test_index_retry_resume.py::test_failed_partial_index_with_checkpoint_resumes_full_index_not_incremental` 与
`test_index_history_changed_files.py::test_changed_files_populated_after_incremental_index` —— **确认为预存、与 Phase 61
无关**。证据：(1) 两测试文件均不在 Phase 61 变更集，且无 `durable`/`_schedule_index`/`DurableTaskService` 任何引用；
(2) 失败模式为 pytest-django `Database access not allowed`（缺 `django_db` mark 的 infra 问题），不经 durable 路径；
(3) 在 Phase 61 起始提交的父提交 `2cb55ea39~1` 上实跑，二者**同样失败**（行为完全一致）。故非本阶段引入。

## Warnings

### WR-01: Phase 61 改了 `_schedule_index` 契约但遗漏同步既有测试，引入 2 个新失败

**File:** `server/repositories/index_views.py:142-171`（契约变更点）；失败测试 `server/tests/test_data_foundation.py:130`、`:156`
**Issue:**
迁移把 `_schedule_index` 的返回从 `concurrent.futures.Future` 改为 durable job_id 字符串，且执行路径从
`repositories.index_views.clone_and_index_repository` 改为任务体内 `services.indexer.clone_and_index_repository`
（`index_views.py` 已不再 import `clone_and_index_repository`，确认无残留死 import）。但 `TestBackgroundRunnerIntegration`
的两个既有用例未同步：
- `test_schedule_index_returns_concurrent_future`：`patch("repositories.index_views.clone_and_index_repository", ...)`
  现指向不存在的属性，且断言 `isinstance(future, Future)` 不再成立。
- `test_task_runs_on_worker_thread_not_request_thread`：patch 目标失效，后台任务不再调到被 patch 的符号。

实跑确认（SQLite 默认路径）：`2 failed, 3 passed`。Plan 02 的验证门只跑 `tests/repositories tests/tasks`，而该文件位于
`tests/` 根目录，故迁移验证未捕获此回归。属测试套件回归（非生产缺陷），但会污染 CI 绿灯、掩盖真实问题。
**Fix:**
更新或删除这两个用例以反映 durable defer 契约，例如断言返回为 job_id 字符串并 patch 正确符号：

```python
async def test_schedule_index_defers_durable_index(self):
    from unittest.mock import AsyncMock
    with patch("durable.service.DurableTaskService.defer", new=AsyncMock(return_value="index:fake-repo-id")) as defer:
        job_id = _schedule_index("fake-repo-id", "fake-history-id")
        assert job_id == "index:fake-repo-id"
        # 校验 queue/idempotency_key
        _, kwargs = defer.call_args
        assert kwargs["idempotency_key"] == "index:fake-repo-id"
```

并把"后台任务跑在 worker 线程"的语义改由 durable in-process 后端层断言（或迁至 `tests/durable`）。

### WR-02: reconcile 逐仓库 `async_to_sync` 调 Procrastinate 异步后端，真实 Postgres 多仓库路径无集成覆盖且故障即误杀

**File:** `server/repositories/apps.py:72-76`；`server/codegraph/apps.py:82-84`；`server/durable/reconcile.py:68-84`
**Issue:**
两处 reconcile 对每个候选仓库各调一次 `has_active_durable_job_sync(...)`，而该 helper 内部是
`async_to_sync(has_active_durable_job)` —— 每次调用都在当前（daemon）线程新建并销毁一个事件循环。durable 路径下
`has_active_by_key` → `app.job_manager.list_jobs_async(...)` 走 Procrastinate 的 async DB。**在真实 Postgres 启动且
有 >1 个卡住 INDEXING/孤儿 graph 仓库时**，"每仓库一个新事件循环"对 loop 绑定的 async 连接/连接池存在兼容风险；一旦
某次调用抛异常，`has_active_durable_job` 的 fail-safe 会返回 False → 该在途仓库被标 FAILED，**正是本阶段要避免的误杀
（违反 SC3）**。

可证的覆盖盲区：`test_reconcile_durable.py` 的全部 reconcile 级用例都 `monkeypatch` 了 `has_active_durable_job_sync`
（Test 5-8），helper 的 postgres 用例（Test 1）只做**单次** defer+查询。因此"reconcile 在真实 Postgres 下逐仓库经
`async_to_sync` 多次查询"这条关键路径从未被集成验证。N+1 已在 Plan 03 评估为"小 N 可接受"，但被评估的是性能，
**健壮性（per-call new-loop + fail-safe-to-FAILED）未被覆盖**。
**Fix:**
把逐仓库 helper 调用收敛为**单次** `async_to_sync` 包一个 async 批处理（在同一事件循环内顺序/并发查多个 key），
既消除 per-call new-loop 风险，也顺带解决 N+1：

```python
# durable/reconcile.py
async def active_durable_keys(keys: list[str]) -> set[str]:
    from durable.service import DurableTaskService, use_procrastinate_backend
    if not use_procrastinate_backend():
        return set()
    active: set[str] = set()
    for k in keys:
        try:
            if await DurableTaskService.has_active_by_key(k):
                active.add(k)
        except Exception:  # noqa: BLE001
            pass  # 单 key 失败不影响其余；fail-safe 朝标 FAILED 侧
    return active

def active_durable_keys_sync(keys: list[str]) -> set[str]:
    from asgiref.sync import async_to_sync
    return async_to_sync(active_durable_keys)(keys)
```

reconcile 侧改为一次 `active_durable_keys_sync([f"index:{rid}" for rid in candidate_ids])`，并补一个真实
Postgres（`postgres_queue`）下"2 个仓库、其一有在途 durable job、其一无"的集成断言，锁定不误杀。

## Info

### IN-01: `trigger_auto_index` 入队 payload 的 `trigger` 传枚举成员而非字符串值，与其余入队点不一致

**File:** `server/tasks/index_trigger_tasks.py:160,183`
**Issue:**
`tt = TriggerType.WEBHOOK if ... else TriggerType.SCHEDULED`，payload 里 `"trigger": tt` 传的是 `TriggerType` 枚举成员；
而 #2/#5 传 `"manual"` 字符串、#4 传 `GraphBuildHistoryTrigger.MANUAL.value`。当前无害（`TriggerType` 是
`models.TextChoices`=str 子类，procrastinate `json` 序列化得到其字符串值；且 `run_index` 不转发 trigger），但风格不一致，
若将来 `run_index` 转发 trigger 或换非 str 枚举会埋雷。
**Fix:** 统一传字符串值：`"trigger": tt.value`（或 `str(tt)`）。

### IN-02: `code_relations/signals.py` 注释仍引用旧 `_schedule_index` 语义（陈旧注释）

**File:** `server/code_relations/signals.py:24`
**Issue:** 注释把自身 `run_in_background` 投递类比 `IndexTriggerView._schedule_index`，但后者已改为 durable defer，
不再是 `run_in_background` 范式，注释与现状不符（仅文档漂移，无行为影响）。
**Fix:** 更新注释，避免读者据陈旧类比误解 index 入队路径。

---

## Fixes applied（2026-06-20）

全部 4 项 findings 已修复，每项原子提交（Conventional Commits，中文 subject）。

| ID | 处置 | Commit | 说明 |
|----|------|--------|------|
| WR-01 | fixed | `f960041d6` | `tests/test_data_foundation.py` 4 处仍断言旧 `_schedule_index` 契约的用例同步到 durable defer：patch `durable.service.DurableTaskService.defer`（AsyncMock），断言返回 durable job id 字符串、`durable_index` 任务名、`queue=QUEUE_INDEX`、`idempotency_key=index:{repo_id}` 及 branch/trigger 透传。除 reviewer 实跑的 `TestBackgroundRunnerIntegration` 2 例外，全文件跑还暴露 `TestConcurrencyLock::test_index_trigger_creates_index_history`（patch 失效的 `clone_and_index_repository`）与 `TestRepositoryDefaultBranchUpdate::test_default_branch_change_...`（断言已迁移走的 `run_in_background.called`）两处同源迁移回归，一并修复（共 4 例）。`tests/test_data_foundation.py` 现 15 passed。 |
| WR-02 | fixed（低风险选项） | `097b47830` | 选择**低风险**路径：不改生产 reconcile 逐仓库循环（避免新增门面 API / 扩散改动面），改为在 `tests/repositories/test_reconcile_durable.py` 新增 `@pytest.mark.postgres_queue` 集成用例 `test_reset_stuck_indexing_real_postgres_multi_repo_no_misfire`——真实 Postgres、2 仓库（其一 defer 真实在途 durable job、其一无），实跑 `_reset_stuck_indexing` 的 per-call `async_to_sync` 路径，断言在途仓库保留 INDEXING/RUNNING（不误杀，锁定 SC3）、无在途仓库标 FAILED。关闭"真实 Postgres 多仓库逐仓库查询从未被集成验证"的覆盖盲区。保持 `has_active_by_key` queueing_lock 语义 / reconcile.py 零 procrastinate 直接依赖 / History 真相源不变。 |
| IN-01 | fixed | `eb751349e` | `tasks/index_trigger_tasks.py` 入队 payload `"trigger": tt` → `"trigger": tt.value`，与其余入队点字符串口径统一。 |
| IN-02 | fixed | `9dd9e0b97` | `code_relations/signals.py` 模块注释更新：标注 `IndexTriggerView._schedule_index` 已于 Phase 61 迁移到 durable defer、不再是 run_in_background 范式（本处 edge reconcile 仍走 run_in_background）。 |

### 验证

- `cd server && uv run pytest tests/durable tests/repositories tests/test_data_foundation.py -q` → **2 failed, 338 passed, 15 deselected**。WR-01 契约回归全消；仅剩的 2 个失败为本报告"两处预存失败的归因结论"已确认的预存 infra 失败（`test_index_retry_resume.py::test_failed_partial_index_with_checkpoint_resumes_full_index_not_incremental`、`test_index_history_changed_files.py::test_changed_files_populated_after_incremental_index`），与 Phase 61 无关。
- `uv run python manage.py check` → System check identified no issues (0 silenced)。
- `uv run python manage.py makemigrations --check --dry-run` → No changes detected。

> status 置 `clean`：4 项 findings 全部闭环；遗留 2 个失败为预存且与本阶段无关（不触达 durable / reconcile / 被改符号）。

---

_Reviewed: 2026-06-20T04:35:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
_Fixes applied: 2026-06-20 — Claude (gsd-code-fixer)_
