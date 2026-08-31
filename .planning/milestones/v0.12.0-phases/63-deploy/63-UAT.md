---
status: testing
phase: 63-deploy
source: [63-VERIFICATION.md]
started: 2026-06-20
updated: 2026-06-20
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  gap_snapshot: "testing::scenarios=5"
---

## Current Test

number: 1
name: 真实 k8s 滚动更新下 worker SIGTERM 优雅 drain
expected: |
  k8s rolling update worker Deployment 时，收到 SIGTERM 的 worker 停止领取新 job、跑完在途或由 stalled rescue 被其他副本接管，在途任务不丢；terminationGracePeriodSeconds(120) 足够 drain。
awaiting: user response

## Tests

### 1. worker SIGTERM 优雅 drain（真实 k8s）

expected: 滚动更新/缩容时在途 job 跑完或被接管，不丢任务。
result: [pending]

### 2. compose `up -d` 升级既有部署不破坏

expected: 既有单/多副本 compose 部署 `up -d` 拉新镜像重建后服务正常、迁移顺序正确、worker/scheduler 起得来。
result: [pending]

### 3. scheduler 单例滚动（Recreate）

expected: scheduler replicas=1 + Recreate，升级时不出现两个 scheduler 并行跑 cron（无重复 cron）。
result: [pending]

### 4. KEDA 按队列深度真实伸缩

expected: KEDA 启用集群下，todo 队列深度上升 → worker 扩容；冷却后缩容到 minReplica≥1（不缩零）。
result: [pending]

### 5. 真实 GitLab/GitHub + 飞书外部副作用去重

expected: at-least-once 重复执行下不重复开 MR/PR（命中既有 open MR 复用）、不重复建群（命中 feishu_chat_id 复用）。
result: [pending]

## Summary

total: 5
passed: 0
issues: 0
pending: 5
skipped: 0
blocked: 0

## Gaps

None — implementation/render/static tests all in place (helm lint 0 failed, fail-closed render triggers correctly, 536 passed). Code-review WR-01 (duplicate keda key) fixed. Remaining items are live-cluster/external-platform runtime confirmations, deferred per project convention. Pre-existing unrelated failure: test_plan_session_inv6_guard (chat INV-6 regex false-positive, Phase 36 artifact).
