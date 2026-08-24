# Phase 138 Context：消歧与 bounded impact

## Smart Discuss 自动决策

| 灰区 | ✅ Recommended 决策 |
|---|---|
| 触发 | `include_impact` 显式请求；默认保持 `not_requested` |
| anchor | 接受稳定 Symbol UID；未给 UID 时仅单候选可自动锚定 |
| 重名/多候选 | 返回 UID、path、1-based line 的候选并标 `needs_disambiguation`，绝不跑 impact |
| 图算法 | 复用 `analyze_impact`，默认深度/节点/结果三重预算 |
| 空结果 | 标 `no_observed_impact_not_safe`，不得解释为安全 |
| stale/excluded | anchor 不在已过 exclusion 的图中即 unavailable + warning |
| 证据 | 只返回符号定位和边理由，不返回源码正文 |
| 脱敏 | query 不进日志；异常走 `redact_secrets_in_text`，ledger 只含结构化数值 |

## 边界

不做跨仓 impact，不新增图数据库，不放开 low-confidence 裸名边。
