---
phase: 60-durable
reviewed: 2026-06-20T02:45:00+08:00
depth: deep
files_reviewed: 14
files_reviewed_list:
  - server/durable/__init__.py
  - server/durable/apps.py
  - server/durable/service.py
  - server/durable/backends.py
  - server/durable/queues.py
  - server/durable/roles.py
  - server/durable/tasks.py
  - server/durable/management/commands/run_worker.py
  - server/friday/settings.py
  - server/repositories/apps.py
  - server/codegraph/apps.py
  - server/resumable/apps.py
  - server/pyproject.toml
  - .github/workflows/ci.yaml
findings:
  critical: 2
  warning: 2
  info: 2
  total: 6
status: clean
fixes_applied: 2026-06-20T02:50:00+08:00
fixes_note: CR-01/CR-02/WR-01/WR-02/IN-01 已修复并提交；IN-02（rescue 循环去重）保守保留
---

# Phase 60: Code Review Report

**Reviewed:** 2026-06-20T02:45:00+08:00
**Depth:** deep（含对 `procrastinate==3.8.1` 库 API 的跨模块溯源）
**Files Reviewed:** 14（source + CI；测试文件作为契约旁证一并阅读）
**Status:** issues_found

## Summary

Phase 60 立起 `DurableTaskService` 适配层 + 进程角色门禁 + 周期 stalled rescue + Postgres 专项 CI。整体结构扎实，且**多数关键约束被正确兑现**：

- ✅ 唯一权威后端判定 `_use_procrastinate(engine, backend)` 是纯函数，service 与 settings 共用同一函数，无另写等价判据（`settings.py` 顶层零 settings 访问，无循环 import）。
- ✅ `procrastinate.contrib.django` 仅在 `_use_procrastinate` 为真时条件追加 `INSTALLED_APPS`——SQLite 路径无 orphan procrastinate 表。
- ✅ fail-soft：`backend="procrastinate"` 而引擎非 Postgres 时记 warning 回退、不启动期 raise（`test_service_fallback.py` 守护）。
- ✅ worker 用 `get_worker_connector()`（非 `DjangoConnector`），`listen_notify=False` 显式传入。
- ✅ `retry_stalled_durable_jobs` 为 `@app.periodic` + `queueing_lock` 单例，stalled 判定基于 `get_stalled_jobs()`（heartbeat），源码零 `nb_seconds=`。
- ✅ 进程角色门禁默认 `web` 零回归，worker/migrate/test 短路且记 info；业务代码零直接 import procrastinate（`test_no_direct_import.py` 守护）。

**但 durable 的 Postgres 生产路径存在两处会导致即刻崩溃的 BLOCKER**，且二者**均未被任何已实际执行的测试覆盖**——`60-04-SUMMARY.md` 明确记载 postgres-queue 的真实 GitHub Actions run 为 `human_needed`（"实际 CI 绿待推送验证"），real kill-worker E2E 亦为 `human_needed`。也就是说，整条 Postgres durable 入队/消费链路从未真正跑通过，两处缺陷是**已合入但未被验证暴露**的潜伏 bug。

关键风险点：Phase 61/62 将依赖本底座迁移真实业务任务；若不先修 CR-01/CR-02，迁移一上 Postgres 即全线 `defer`/worker 崩溃。

## Critical Issues

### CR-01: Procrastinate 路径 `defer` 按裸任务名查 `app.tasks`，与库的全路径注册名不匹配 → `KeyError`

**File:** `server/durable/backends.py:228`
**Issue:**
`ProcrastinateBackend.defer` 用调用方传入的**逻辑名**查注册表：

```228:234:server/durable/backends.py
        task_obj = app.tasks.get(task)
        if task_obj is None:
            raise KeyError(
                f"durable 任务 {task!r} 未在 procrastinate app 注册"
                "（确认 durable.tasks 已被 DurableConfig.ready() 导入触发 @app.task）"
            )
```

但 procrastinate 的 `@app.task`（`durable/tasks.py` 未传 `name=`）默认以**函数全路径**注册任务。经溯源 `procrastinate/tasks.py:111` `self.name = name if name else self.full_path`，`procrastinate/utils.py:154` `return f"{_get_module_name(obj)}.{name}"`，`durable_ping` 实际注册名为 `"durable.tasks.durable_ping"`，而 `app.tasks` 是以该全路径为 key 的 dict（`blueprints.py:131` `result_dict[name] = task`）。

因此 `DurableTaskService.defer("durable_ping", ...)` → `app.tasks.get("durable_ping")` → `None` → 抛 `KeyError`。**Postgres 路径下没有任何 task 能成功入队**。

测试 `tests/durable/test_procrastinate_backend.py:38` 正是用裸名 `"durable_ping"` 调 `defer`，同时断言 `job.task_name.endswith("durable_ping")`（`:50`，全路径才需要 `endswith`）——契约自相矛盾，该用例一旦在真实 Postgres 上运行必然 error。但 `60-04-SUMMARY.md:106` 记载 postgres-queue 真实 CI run 为 `human_needed`，故该用例从未实际执行、缺陷未暴露。

**Fix:** 让注册名与查找键一致。推荐给 `@app.task` 显式 `name=`（用 `durable.queues` 风格的稳定逻辑名），并让 `defer` 按同一逻辑名查找：

```python
# durable/tasks.py
@app.task(name="durable_ping", queue=QUEUE_MAINTENANCE)
async def durable_ping(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    ...

@app.periodic(cron="*/10 * * * *")
@app.task(name="retry_stalled_durable_jobs", queueing_lock="retry_stalled_durable_jobs", pass_context=True)
async def retry_stalled_durable_jobs(context: Any, timestamp: int) -> int:
    ...
```

或在 `defer` 内对裸名做容错兜底（按 `.endswith` / 全路径双查），但显式 `name=` 更稳、与测试断言更自洽。修复后务必让 postgres-queue CI 真正跑一次确认 green。

### CR-02: `run_worker` 用 `async with` 包同步上下文管理器 `app.replace_connector(...)` → worker 启动即 `TypeError`

**File:** `server/durable/management/commands/run_worker.py:66`
**Issue:**

```65:69:server/durable/management/commands/run_worker.py
        connector = app.connector.get_worker_connector()
        async with app.replace_connector(connector) as worker_app:
            # listen_notify=False 必须显式传入（锁定决策）：v1 走 polling，低延迟
            # NOTIFY 唤醒 deferred 到 v2（DURABLEX-01）。
            await worker_app.run_worker_async(queues=queues, listen_notify=False)
```

`app.replace_connector` 在库里是 **同步** 上下文管理器（`procrastinate/app.py:152` `@contextlib.contextmanager` + 普通 `yield self`，返回 `Iterator[App]`，仅有 `__enter__`/`__exit__`）。用 `async with` 套同步 CM 会因缺少 `__aenter__` 抛 `TypeError`（`... can't be used in 'async with' expression`），worker 进程**一启动就崩**，永远无法消费队列。

对照库自带官方命令 `procrastinate/contrib/django/management/commands/procrastinate.py:45` 用的是普通 `with context:`（同步），可印证正确用法。

该命令没有任何自动化测试覆盖到 `_run_worker`（`run_worker --help` 由 argparse 在 `handle()` 前短路；真实 worker 跑队列属 `60-VALIDATION.md` 的 `human_needed` E2E），故缺陷潜伏未暴露。

**Fix:** 改用同步 `with`（在 async 函数内对同步 CM 用同步 `with` 是合法的，进入/退出只是替换 connector，不阻塞）：

```python
async def _run_worker(self, queues: list[str]) -> None:
    from procrastinate.contrib.django import app

    connector = app.connector.get_worker_connector()
    with app.replace_connector(connector) as worker_app:
        await worker_app.run_worker_async(queues=queues, listen_notify=False)
```

（亦可仿官方命令：在 `handle()` 内 `with app.replace_connector(...)`，再 `asyncio.run(app.run_worker_async(...))`。）修复后建议补一条最小 worker 冒烟（即便 `human_needed`，也应有一次人工实跑记录）。

## Warnings

### WR-01: `ProcrastinateBackend.get` / `cancel` 无防护 `int(job_id)`，非数字 id 直接 `ValueError` 崩溃（与 in-process 后端不一致）

**File:** `server/durable/backends.py:274`、`server/durable/backends.py:295`
**Issue:**
`get` 与 `cancel` 对入参直接 `int(job_id)`：

```271:295:server/durable/backends.py
    async def get(self, job_id: str) -> dict[str, Any]:
        from procrastinate.contrib.django import app

        jobs = list(await app.job_manager.list_jobs_async(id=int(job_id)))
        ...
    async def cancel(self, job_id: str) -> bool:
        from procrastinate.contrib.django import app

        return bool(await app.job_manager.cancel_job_by_id_async(int(job_id)))
```

任何非数字 `job_id` 会抛 `ValueError`，而 in-process 后端对未知 id 返回结构化 `{"status": "unknown"}` / `False`、**从不抛**（`backends.py:170-171`、`:173-177`）。两后端契约不一致，调用方拿到的"job_id"未必是数字串——见 WR-02：`AlreadyEnqueued` 兜底路径会返回 `str(idempotency_key)`（非数字），随后 `get`/`cancel` 该 id 即崩。

**Fix:** 解析失败按 unknown/False 优雅返回，对齐 in-process 语义：

```python
async def get(self, job_id: str) -> dict[str, Any]:
    try:
        jid = int(job_id)
    except (TypeError, ValueError):
        return {"job_id": job_id, "status": "unknown"}
    from procrastinate.contrib.django import app
    jobs = list(await app.job_manager.list_jobs_async(id=jid))
    ...

async def cancel(self, job_id: str) -> bool:
    try:
        jid = int(job_id)
    except (TypeError, ValueError):
        return False
    from procrastinate.contrib.django import app
    return bool(await app.job_manager.cancel_job_by_id_async(jid))
```

### WR-02: `_find_job_by_queueing_lock` 未按状态过滤，可能返回历史/已结束 job 的 id

**File:** `server/durable/backends.py:266`
**Issue:**

```260:269:server/durable/backends.py
    @staticmethod
    async def _find_job_by_queueing_lock(idempotency_key: str | None) -> str | None:
        if idempotency_key is None:
            return None
        from procrastinate.contrib.django import app

        jobs = list(await app.job_manager.list_jobs_async(queueing_lock=idempotency_key))
        if not jobs:
            return None
        return str(jobs[0].id)
```

`list_jobs_async(queueing_lock=...)` 不限状态，会返回该 lock 下**所有历史 job**（含 succeeded/failed）。`AlreadyEnqueued` 命中时本意是查"当前在 todo 的那条"，但 `jobs[0]` 取的是返回序的第一条，可能是早先已结束的同 lock job，导致幂等 `defer` 返回**错误的（陈旧的）job 标识**。当 lock 被复用（不同时间多次入队同 key）时尤为明显。同时若库在 job 离开 todo 后清空 `queueing_lock` 列，`jobs` 可能为空 → 返回 `str(idempotency_key)`（非数字，触发 WR-01）。

`test_queueing_lock_singleton_no_pileup` 仅在同一测试内连续两次 defer、无中途完成，掩盖了跨时间复用场景。

**Fix:** 过滤活跃状态并取最新：

```python
jobs = list(await app.job_manager.list_jobs_async(
    queueing_lock=idempotency_key, status="todo",
))
if not jobs:
    jobs = list(await app.job_manager.list_jobs_async(
        queueing_lock=idempotency_key, status="doing",
    ))
if not jobs:
    return None
return str(jobs[-1].id)  # 取最新一条
```

## Info

### IN-01: `durable/__init__.py` 的 `default_app_config` 为死代码（Django 4.1+ 已移除该机制）

**File:** `server/durable/__init__.py:24`
**Issue:** `default_app_config = "durable.apps.DurableConfig"` 自 Django 3.2 起 deprecated、4.1 起移除并忽略；项目用 Django 5.1+，该行为 no-op 死代码。`durable` 已在 `INSTALLED_APPS` 直接列出且只有单个 `AppConfig`，Django 会自动发现。
**Fix:** 删除该行（无功能影响，纯清理）。

### IN-02: stalled rescue 循环在 `backends.py` 与 `tasks.py` 重复实现

**File:** `server/durable/backends.py:297-309`、`server/durable/tasks.py:54-65`
**Issue:** `ProcrastinateBackend.retry_stalled` 与 periodic `retry_stalled_durable_jobs` 是逐字相同的 `get_stalled_jobs()` + `retry_job()` 循环（docstring 自述"同算法"）。两处独立维护，未来改判定阈值/增加 queue 过滤时易漂移。
**Fix:** periodic 任务直接复用 `procrastinate_backend.retry_stalled()`（经 `DurableTaskService` 或直接调后端），单一实现单点维护。注意保持 `tasks.py` 仍在 no-direct-import 允许清单内。

---

## 复核备注（非缺陷，供 orchestrator 参考）

- **后端选择 / 循环 import / 条件注册 / fail-soft / 角色门禁 / no-direct-import 守护 / heartbeat-only rescue / listen_notify=False / get_worker_connector** 等 focus checks **均已正确实现**，对应单元测试（SQLite 路径）真实可跑、零回归门禁合理。
- 两处 BLOCKER 的共性根因是 **Postgres 路径缺乏一次真实端到端执行**（CI 与 kill-worker 均 `human_needed`）。建议在修复 CR-01/CR-02 后，**优先推送触发一次真实 postgres-queue CI run**，把"human_needed"降级为已验证，再进入 Phase 61 迁移。
- 安全面：CI 中 `friday:friday` 为临时 ephemeral 测试库凭证（service container 内），非真实 secret，不计为发现；`payload` 不携凭证的约束（T-60-08）本阶段未接业务任务，留 Phase 61 守护。

## Fixes applied（2026-06-20）

| 发现 | 处理 | Commit | 说明 |
|------|------|--------|------|
| CR-01 | ✅ fixed | `4f24d836c` | `durable/tasks.py` 为每个 `@app.task` 显式声明 `name=`（`durable_ping` / `retry_stalled_durable_jobs`），与 `backends.defer` 的 `app.tasks.get(task)` 查找键统一为同一 single source of truth；不再依赖 procrastinate 默认全路径注册名。`backends.py` 同步补充注释/报错文案。测试 `endswith("durable_ping")` 仍成立，无需改测试。 |
| CR-02 | ✅ fixed | `b9a36f1cf` | `run_worker._run_worker` 由 `async with app.replace_connector(...)` 改为同步 `with`（该 CM 为同步 `@contextlib.contextmanager`，对照官方 `procrastinate` worker 命令）。worker 启动不再抛 `TypeError`。 |
| WR-01 | ✅ fixed | `39e569731` | `ProcrastinateBackend.get/cancel` 对 `int(job_id)` 加 try/except，非数字/None 优雅返回 `{"status": "unknown"}` / `False`，对齐 in-process 后端"从不抛"语义。 |
| WR-02 | ✅ fixed | `3e0d7514a` | `_find_job_by_queueing_lock` 改为优先按 `status="todo"`、其次 `status="doing"` 过滤，并取 `id` 最大（最新）一条，避免返回陈旧/已结束 job 标识。 |
| IN-01 | ✅ fixed | `58e7a5a20` | 删除 `durable/__init__.py` 的死代码 `default_app_config`（Django 4.1+ 已移除该机制）。 |
| IN-02 | ⏸️ deferred | — | rescue 循环去重为可选低收益项；复用会改变 periodic 任务的日志事件名/契约，保守保留两处独立实现，留待后续按需统一。 |

**约束守护：** 单一 `_use_procrastinate` 判定、`listen_notify=False`、`queueing_lock` 单 leader、heartbeat-only rescue（零 `nb_seconds`）、业务代码零直接 import procrastinate 均未触动。未改动 STATE.md / ROADMAP.md。

**验证：**
- `cd server && uv run pytest tests/durable -q` → 31 passed, 8 deselected（postgres_queue 仍 deselect、未 error）。
- `cd server && uv run python manage.py check` → System check identified no issues。
- `ast.parse` `backends.py` / `run_worker.py` / `tasks.py` / `__init__.py` 均通过。
- `python manage.py run_worker --help` 正常输出。
- Postgres 真实端到端（postgres-queue CI / kill-worker E2E）仍为 `human_needed`，建议推送触发一次真实 run 把两处 BLOCKER 的修复落到实证。

_Reviewed: 2026-06-20T02:45:00+08:00_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
