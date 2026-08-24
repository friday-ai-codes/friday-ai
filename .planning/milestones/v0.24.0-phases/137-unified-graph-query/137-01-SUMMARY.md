# Plan 137-01 Summary

## 交付

- 新增公开 `GraphQueryService` 与 `graph-query/v1`、`rrf-v1` 版本常量。
- 每次查询先经过 `get_graph()` 权限/exclusion/水位闸；空查询不触发检索。
- Symbol dense+BM25 与 Process dense+sparse 双 lane 固定权重融合，稳定 ID 决胜。
- 返回逐候选 lane rank/贡献、Community enhancement、final score 的可重算账本。
- Process step 的符号、文件和 1-based 行号原样保留，并反挂到 Symbol membership。
- lane 失败时返回同 schema partial；预算先裁正文并保留 matched/returned 和 continuation。

## 验证

- `5 passed`：统一服务契约。
- `9 passed`：Phase 136 Process index + Phase 137 回归。
- `ruff` 通过；`mypy` 仅报仓库既存 3 文件 5 项错误，目标文件无新增错误。

## Commit

- `69bd5b4a feat(137): 新增统一图查询服务`
