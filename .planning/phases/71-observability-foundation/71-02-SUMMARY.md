---
phase: 71-observability-foundation
plan: "71-02"
subsystem: observability
tags: [logging, system-log, queue, redaction, django-model]
requires:
  - server/common/logging.py (redact_credentials / buffer_log / RingBufferHandler)
  - server/common/log_buffer.py (800 条内存兜底)
provides:
  - SystemLogEntry 模型（倒序时间 + 组件/级别/用户/来源复合索引）
  - InboundWebhookEvent 模型（webhook 原始留痕载体，写入在 71-05）
  - system/log_sink.py（deque(maxlen=5000) + daemon 批量 worker + 四计数 + best-effort enqueue/snapshot/flush）
  - common.logging.enqueue_system_log processor（redact 之后 fan-out 落库）
  - RingBufferHandler 落库 fan-out（stdlib 链路）
affects:
  - 71-03（运行时配置 / 采样 / category·component helper）
  - 71-04（日志查询 / 计数端点 / 清理）
  - 71-05（webhook 写入 InboundWebhookEvent + 下钻）
  - Phase 73（队列四计数快照采集）
tech-stack:
  added: []  # 仅标准库 deque/threading + 既有 Django ORM
  patterns: [best-effort-except-pass, deque-bounded-queue, daemon-batch-worker, redact-before-persist]
key-files:
  created:
    - server/system/log_sink.py
    - server/system/migrations/0009_inboundwebhookevent_systemlogentry.py
    - server/tests/test_system_log_sink.py
  modified:
    - server/system/models.py
    - server/common/logging.py
    - server/tests/test_credential_leak_protection.py
decisions:
  - "迁移文件名按 makemigrations 实际生成为 0009_inboundwebhookevent_systemlogentry.py（字母序），plan 引用的 0009_systemlogentry_inboundwebhookevent.py 仅命名顺序差异（per 71-CONTEXT Claude's Discretion）"
  - "daemon worker 在 PYTEST_CURRENT_TEST 下不自动启动；测试用同步 flush_now() 落库，保证确定性并避免跨线程 DB 连接污染测试隔离"
  - "_to_entry 把关联键（run_id/conversation_id/execution_id/node_execution_id/session_id）移出 payload 进 correlation，避免重复存储（不复制数据）"
metrics:
  duration: ~6m
  completed: 2026-06-24
---

# Phase 71 Plan 02: 系统日志队列化批量落库 Summary

系统日志从"每进程 800 条内存环形缓冲"升级为"deque(maxlen=5000) 队列 + daemon 批量 `bulk_create` 落库 + 四计数 best-effort 暴露"，落库内容经 structlog/stdlib 两条链路在脱敏之后 fan-out，`SystemLogEntry` 倒序可查、`InboundWebhookEvent` 建表待 71-05 写入。

## Tasks

- **Task 1 — PASS**：`SystemLogEntry`（BigAutoField + ts 倒序 + 组件/级别/用户/来源复合索引）与 `InboundWebhookEvent`（webhook 原始留痕，本 plan 仅建表）落 `system` app；迁移 `0009_inboundwebhookevent_systemlogentry.py`（纯 CreateModel + AddIndex，无数据迁移）。`makemigrations --check` 无未生成变更；`migrate --plan` 含两表。
- **Task 2 — PASS**：`server/system/log_sink.py`——`deque(maxlen=5000)` + 手动满丢弃计数、`_enqueued/_written/_dropped/_write_failed` 四计数、`enqueue_system_log`（同步热路径，不做 ORM）、专用 daemon 线程 `friday-log-sink`（定时 1.0s / 积压 200 触发）批量 `bulk_create(ignore_conflicts=True)`、`_to_entry` 字段映射、`snapshot_counters` / `flush_now` / `_reset_for_tests`。8 个测试覆盖落库 200 条、队列满丢弃、字段映射（WARNING→warn / 缺 ts / 未知字段进 payload / 关联键进 correlation / message 兜底 event）、bulk_create 抛错时 write_failed 递增不冒泡。
- **Task 3 — PASS**：`common/logging.py` 新增 `enqueue_system_log` processor 插在 `redact_credentials`/`buffer_log` 之后（保证落库已脱敏）、`RingBufferHandler.emit` 在内存缓冲之后 fan-out 落库（经 `redact_secrets_in_text`）。`test_credential_leak_protection.py` 追加 `TestSystemLogSinkRedaction`（structlog 业务事件 + stdlib record 两路对称守护，断言 `SystemLogEntry` 落库行含 `***REDACTED***`、绝不含明文）。既有顶层锁名 `test_no_credential_leak_in_logs` 与 stdout 守护不变。

## Verification

- `uv run pytest tests/test_system_log_sink.py tests/test_credential_leak_protection.py -x -q` → **32 passed**。
- `uv run pytest tests/test_system_logs.py -q` → **5 passed**（既有内存缓冲视图不破）。
- `uv run python manage.py makemigrations --check` → **No changes detected**。
- `uv run ruff check system/log_sink.py system/models.py common/logging.py tests/test_system_log_sink.py` → **All checks passed**。

## Deviations from Plan

### Naming-only

**1. 迁移文件名顺序差异**
- Plan `files_modified` 写 `0009_systemlogentry_inboundwebhookevent.py`；`makemigrations` 实际按模型字母序生成 `0009_inboundwebhookevent_systemlogentry.py`。
- 内容一致（两模型 CreateModel + 全部索引），编号与依赖正确（依赖 `0008_providercredential_max_concurrency`）。per 71-CONTEXT「migration 编号由 makemigrations 自动生成」属预期内 discretion。

### Implementation choices (non-deviation)

- **daemon worker 测试期不自启**：`_ensure_worker()` 检测 `PYTEST_CURRENT_TEST` 直接返回，测试走同步 `flush_now()`。规避跨线程独立 DB 连接破坏 pytest-django 事务隔离，同时保留生产懒启动语义。
- **关联键去重**：`_to_entry` 把 `run_id/conversation_id/execution_id/node_execution_id/session_id` 从 payload 移入 correlation（符合「不复制数据」）。

## Observability 规则符合性

- 落库链路 best-effort：`enqueue_system_log` / worker / `_flush` 全 `except: pass`，绝不反噬业务。
- 脱敏不可破：processor 严格挂在 `redact_credentials` 之后；stdlib 走 `redact_secrets_in_text`；新增对称守护测试证明落库行无明文。
- 四计数（queued/max/enqueued/written/dropped/write_failed）可 `snapshot_counters()` 采集，落库失败/满丢弃不静默（T-71-02-02/03 缓解）。
- `log_buffer.py`（800 条）作极速兜底保留，与落库链路并存。

## Known Stubs

- `InboundWebhookEvent` 本 plan 仅建表，无写入逻辑（写入在 71-05，plan 明确）。非阻塞性 stub。

## Self-Check: PASSED

- 文件存在：`server/system/log_sink.py`、`server/system/migrations/0009_inboundwebhookevent_systemlogentry.py`、`server/tests/test_system_log_sink.py`、`server/system/models.py`、`server/common/logging.py`、`server/tests/test_credential_leak_protection.py` 均 FOUND。
- 测试/迁移/lint 全绿（见 Verification）。
