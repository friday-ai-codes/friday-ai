---
status: partial
phase: 17-varref
source: [17-VERIFICATION.md]
started: 2026-06-12T16:30:00Z
updated: 2026-06-12T16:30:00Z
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  gap_snapshot: "partial::scenarios=3"
---

## Current Test

[awaiting human testing]

## Tests

### 1. 端到端所选即所得

expected: 变量选择器选引用 → 保存 → 执行，好引用取到值；坏引用节点显式失败且中文错误指明哪个引用、哪个节点/字段缺失
result: [pending]

### 2. 端口复制缺 short_id 防护

expected: 未保存节点点击端口复制应 toast 提示「节点缺少 short_id，请先保存工作流」，且不产生 UUID 形式引用
result: [pending]

### 3. 运行时选择器双键去重

expected: 有执行结果时，变量选择器中同一字段只展示 short_id 形态一条（不出现 UUID 重复项）
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
