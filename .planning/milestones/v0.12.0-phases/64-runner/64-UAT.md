---
status: testing
phase: 64-runner
source: [64-VERIFICATION.md]
started: 2026-06-20
updated: 2026-06-20
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  gap_snapshot: "testing::scenarios=3"
---

## Current Test

number: 1
name: 真实 k0s/containerd 集群经 k8s Job executor 跑通任务容器
expected: |
  在 k0s/containerd 集群（无 docker.sock）部署 runner（executor=kubernetes + SA/RBAC），派发任务 →
  经 k8s API 起 Job/Pod 跑任务容器至退出，日志流式回传、退出码正确、完成后 Pod/Job 被清理。
awaiting: user response

## Tests

### 1. k8s Job executor 真机跑通（无 docker.sock）

expected: 任务容器经 k8s Job 运行至退出，去 docker.sock，RBAC 生效。
result: [pending]

### 2. 运行期日志流式 / 退出码 / Pod 清理

expected: StreamLogs follow 实时回传、WaitContainer 取真实退出码、RemoveContainer/StartupCleanup/ZombieScan 正确清理本 runner Job（多副本隔离 friday.runner label）。
result: [pending]

### 3. 失败重试 + activeDeadline 兜底

expected: backoffLimit 重试生效；values-gated activeDeadlineSeconds 超时兜底杀 Job。
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps

None — implementation complete (KubernetesExecutor 7 methods via client-go), docker zero-regression confirmed, helm RBAC + podIP callback render correct, go build/vet/test green, fake-clientset unit tests cover dispatch/wait(re-watch)/logs/cleanup/zombie. Code-review CR-01 (WaitContainer closed-channel false-fail/leak) fixed; WR-01/WR-02/IN-02 fixed. Accepted known limitations (not gaps): HITL-answer-in-k8s and ReadContainerFile k8s product read require task-container changes / RWX volume (out of scope, deferred); plaintext secrets in Job env matches docker env-injection (mitigated by namespaced RBAC; Secret-based env is v2). Remaining items are real k0s/containerd runtime confirmations.
