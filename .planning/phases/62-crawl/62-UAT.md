---
status: testing
phase: 62-crawl
source: [62-VERIFICATION.md]
started: 2026-06-20
updated: 2026-06-20
---

## Current Test

number: 1
name: 真实容器/Pod 重启后队列恢复 + durable job 自动续跑
expected: |
  在真实 Postgres 部署贴链接入队爬取任务 → `docker compose up -d`（拉新镜像重建）或 Pod 重建后，
  刷新前端队列面板从后端 IngestRun 恢复列表、在途 durable job 自动续跑（不丢、不重复入库）。
awaiting: user response

## Tests

### 1. 真实容器/Pod 重启后队列恢复 + 自动续跑
expected: 贴链接入队 → 重启容器/Pod → 队列从 DB 恢复、durable job 自动续跑、入库 at-least-once 不重复。
result: [pending]

### 2. postgres_queue queueing_lock 去重 + 并发 at-least-once 幂等
expected: 真实 Postgres 下同 batch 重复 enqueue 经 queueing_lock 去重；并发 worker 竞争下入库幂等无重复数据。
result: [pending]

### 3. 知识树重建端到端（hash 变则真实重建）
expected: 真实数据变更后触发 KnowledgeTreeRebuild → build_full 真实执行落新 snapshot；数据未变 → 跳过。（SQLite 守护已覆盖；真实 Postgres 抽验。）
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps

None — implementation present and SQLite (495 passed) + vitest (8 passed) green. CR-01 (build_full never ran) fixed during code review. Remaining items are real-Postgres/container-restart runtime confirmations, deferred per project convention. Pre-existing unrelated failures (not Phase 62): test_plan_session_inv6_guard (chat INV-6 regex false-positive), test_index_retry_resume, test_index_history_changed_files, test_rebuild_repo_summaries (test-order pollution, passes in isolation).
