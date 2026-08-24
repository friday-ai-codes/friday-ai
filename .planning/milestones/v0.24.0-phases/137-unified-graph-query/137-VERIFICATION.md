---
phase: 137
status: passed
score: 8/8
verified_at: 2026-08-24
---

# Phase 137 Verification

| Requirement | 结果 | 证据 |
|---|---|---|
| QUERY-01/02 | passed | service 同次调用检索 Symbol 与 Process，Community canonical join |
| QUERY-03 | passed | 固定权重 RRF、round、stable ID tie-break、ranking version |
| QUERY-04 | passed | `ledger` 可离线重算 |
| QUERY-05 | passed | `graph-query/v1` 稳定结构 |
| QUERY-06 | passed | Process `steps` 未降维，Symbol 反挂 membership |
| QUERY-07 | passed | commit scope 唯一，Community 混水位降级且不拼接 |
| QUERY-08/09 | passed | capabilities、partial、warnings 与 matched/returned/truncated |
| QUERY-10 | passed | 空查询在权限/检索前失败；正常查询每次调用 `get_graph()` |

测试：`9 passed`；ruff 通过。`mypy` 受仓库既存 3 文件 5 项错误影响，目标文件无错误。
