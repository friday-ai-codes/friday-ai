---
status: testing
phase: 60-durable
source: [60-VERIFICATION.md]
started: 2026-06-20
updated: 2026-06-20
---

## Current Test

number: 1
name: postgres_queue 后端测试实跑（defer/priority/run_at/PsycopgConnector）
expected: |
  在真实 Postgres（DATABASE_URL=postgres://…）下 `cd server && uv run pytest -m postgres_queue -q` 全绿——
  ProcrastinateBackend defer/get/cancel/priority/run_at 正确入队执行，worker 经 PsycopgConnector 消费。
awaiting: user response

## Tests

### 1. postgres_queue 后端测试实跑
expected: 真实 Postgres 下 `uv run pytest -m postgres_queue -q` 全绿（defer/priority/run_at/PsycopgConnector）。
result: [pending]

### 2. forged-heartbeat stalled rescue（queueing_lock 单例 + 并发竞争）
expected: 伪造过期 heartbeat 后，周期 `retry_stalled_durable_jobs` 经 queueing_lock 单 leader 重投 stalled job；多副本下只有一个 leader 扫描。
result: [pending]

### 3. 真实 kill-worker E2E
expected: 启动 2 个 worker 跑 Postgres，defer 长任务后 `kill -9` 持有者，另一 worker 经周期 rescue 接管重跑（VALIDATION Manual-Only）。
result: [pending]

### 4. GitHub Actions postgres-queue job 推送后绿灯
expected: 推送触发 `.github/workflows/ci.yaml` 的 `postgres-queue` job（postgres:17-alpine service），`-m postgres_queue` 全绿；`server-ci`（SQLite 默认）零回归绿。
result: [pending]

## Summary

total: 4
passed: 0
issues: 0
pending: 4
skipped: 0
blocked: 0

## Gaps

None — implementation present and SQLite/fallback path fully green (31 passed). Remaining items are runtime-only confirmations requiring real Postgres / GitHub Actions, deferred per project convention (container/external-system E2E).
