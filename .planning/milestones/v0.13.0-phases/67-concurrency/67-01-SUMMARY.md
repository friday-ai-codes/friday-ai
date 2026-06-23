---
phase: 67-concurrency
plan: 01
subsystem: durable-concurrency
tags: [procrastinate, lock, slot-pool, index, graph, system-setting]
requires: []
provides:
  - "DurableTaskService/backends defer 增 lock（Procrastinate doing 并发锁）透传"
  - "durable/concurrency.py 稳定 slot 锁池 + 设置驱动 N"
  - "SettingKeys.CONCURRENCY_INDEX_MAX/GRAPH_MAX"
affects: [所有 index/graph durable 入队点]
tech-stack:
  added: []
  patterns:
    - "Procrastinate 原生 lock 槽位池：lock=index-slot-{stable_hash(repo_id)%N}，与 queueing_lock 正交"
    - "稳定 slot 用 hashlib.md5 跨进程一致（避开 PYTHONHASHSEED）"
key-files:
  created:
    - server/durable/concurrency.py
    - server/tests/durable/test_concurrency_locks.py
  modified:
    - server/durable/service.py
    - server/durable/backends.py
    - server/system/models.py
    - server/repositories/index_views.py
    - server/repositories/views.py
    - server/tasks/index_trigger_tasks.py
    - server/codegraph/views.py
    - server/resumable/handlers.py
status: complete
---

# Phase 67 Plan 01 Summary — CONC-01 索引/图谱槽位锁池

- defer 全链（`DurableTaskService.defer` / `DurableBackend` 协议 / `ProcrastinateBackend.defer` / `InProcessBackend.defer`）新增 `lock` 参数；Procrastinate 落 `configure_options["lock"]`（doing 并发锁，与 `queueing_lock`=idempotency_key 的 todo 去重正交并存），InProcess 接受但忽略（dev 串行）。
- 新建 `durable/concurrency.py`：稳定 slot 计算用 `hashlib.md5`（非内置 `hash()`，避免 PYTHONHASHSEED 逐进程漂移破坏「同仓同槽串行」）；N<=0 clamp 到 1（防除零）；`index_slot_lock`/`graph_slot_lock` + async/sync 读 `SystemSetting` 的 N（默认索引 5 / 图谱 3，非法/0 回退默认）+ `aindex_lock`/`agraph_lock`/`*_lock_sync` 便捷入口。
- `SettingKeys` 新增 `CONCURRENCY_INDEX_MAX` / `CONCURRENCY_GRAPH_MAX`。
- 5 处 index/graph defer 入队点（`repositories/index_views.py`、`repositories/views.py`、`tasks/index_trigger_tasks.py`、`codegraph/views.py`、`resumable/handlers.py` 的 resume_index/resume_graph）全部带 `lock=...-slot-{N}`（async 用 `aindex/agraph_lock`，sync 用 `*_lock_sync`）。

验收：`tests/durable/test_concurrency_locks.py` 11 例 + `test_index_graph_migration.py` 9 例零回归全绿；durable 全套 71 passed。
