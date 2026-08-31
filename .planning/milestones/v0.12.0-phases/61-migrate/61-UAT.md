---
status: testing
phase: 61-migrate
source: [61-VERIFICATION.md]
started: 2026-06-20
updated: 2026-06-20
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  gap_snapshot: "testing::scenarios=3"
---

## Current Test

number: 1
name: 真实升级迁移（migrate_resumable_to_durable on Postgres）
expected: |
  在真实 Postgres + DURABLE_TASK_BACKEND=procrastinate，存量有 PENDING/RUNNING index/graph resumable_tasks 时，
  运行 `migrate_resumable_to_durable` → 生成对应 durable job、旧行标 MIGRATED 记 legacy_durable_job_id、不双跑；重复运行幂等无重复。
awaiting: user response

## Tests

### 1. 真实升级迁移（Postgres）

expected: 命令把存量在途 index/graph resumable_tasks 转 durable job，旧行 MIGRATED + legacy id，重复运行幂等。
result: [pending]

### 2. procrastinate queueing_lock 去重（真实 Postgres）

expected: 同 repo 重复 defer（deterministic key index:/graph:{repo_id}）在真实 Postgres 下经 queueing_lock 去重，不产生重复在途 job。
result: [pending]

### 3. 多副本 reconcile 不误杀（真实 Postgres）

expected: 有在途 durable job 的仓库，启动 reconcile 经 has_active_by_key（queueing_lock）判定保留 RUNNING、不标 FAILED；无在途的仓库标 FAILED（旧行为）。
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps

None — implementation present, SQLite/in-process path fully green (66 passed). postgres_queue integration tests authored (incl. reconcile no-kill, WR-02). Remaining items are real-Postgres upgrade/runtime confirmations, deferred per project convention (external-system E2E). Pre-existing unrelated failures: test_index_retry_resume, test_changed_files_populated (pytest-django infra, not Phase 61).
