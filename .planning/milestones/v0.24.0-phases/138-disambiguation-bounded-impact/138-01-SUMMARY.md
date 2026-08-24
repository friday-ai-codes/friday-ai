# Plan 138-01 Summary

## 交付

- `GraphQueryService` 支持显式 `include_impact` 与稳定 `anchor_symbol_id`。
- 多候选返回 UID/path/1-based line 并标 `needs_disambiguation`，不执行影响分析。
- 唯一锚定后复用已过权限/exclusion/水位闸的图与 `analyze_impact`。
- 深度、遍历节点和结果数量均硬上限；返回风险、置信输入、总数/返回数、截断和 drill-down。
- 空结果明确标 `no_observed_impact_not_safe`；缺失/stale/excluded anchor 显式 partial。

## 验证

`19 passed`（GraphQueryService 9 + impact 内核 10）；ruff 通过。

## Commit

- `3fc58f28 feat(138): 接入消歧与有界影响面`
