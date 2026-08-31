---
status: testing
phase: 43-env-resume
source: [43-VERIFICATION.md]
started: 2026-06-16T19:25:00Z
updated: 2026-06-16T19:25:00Z
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  gap_snapshot: "testing::scenarios=2"
---

## Current Test

number: 1
name: 真实 runner + Docker 端到端 resume —— 私有仓 clone 成功 + 落正确目标分支
expected: |
  派发编码容器后，容器用注入的 git token 成功 clone 私有仓，并在
  env_FRIDAY_TASK_BRANCH_STRATEGY 指定的工作分支上提交（target_branch 为 base_branch），
  不再落容器默认 friday/task-{id}。
awaiting: user response

## Tests

### 1. 真实 runner + Docker 端到端 resume —— 私有仓 clone 成功 + 落正确目标分支

expected: 派发编码容器后，容器用注入的 git token 成功 clone 私有仓，并在 env_FRIDAY_TASK_BRANCH_STRATEGY 指定的工作分支上提交（target_branch 为 base_branch）。
result: [pending]

### 2. 真实 deep-research 容器在途完成 → chat/workflow 会话自动续驱到 done

expected: 调研容器完成回调后，chat 入口 PlanSession 经 callback 续驱 merging→architecting→done，barrier 回灌使对话自动 resume 呈现 canonical 主方案。
result: [pending]

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
