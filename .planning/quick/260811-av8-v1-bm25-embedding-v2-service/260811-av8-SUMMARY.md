---
quick_id: 260811-av8
status: complete
completed: 2026-08-11
---

# 统一仓库路由服务

## 完成内容

- 以 `RepoRouterV2.route` 作为唯一生产路由入口。
- 将原 v1 的 `repo_summaries` BM25+dense RRF 召回、关键词微调与匹配原因生成迁入
  `repo_summaries_channel.py`，仅供 V2 在 `repo_index_nodes` 无命中时内部调用。
- 删除旧公开模块 `repo_router.py`（曾短暂保留的兼容壳也已去掉）；算法只活在 channel。
- 将 `LayeredSearchService` L1 切到 V2，并固定 `use_llm=False`，避免 RAG 热路径调用 LLM。
- 保留 `router_version=v1_fallback`、`degraded=True`、`degrade_reason=no_node_index`
  兼容契约，并补摘要通道生命周期日志。
- 新增静态守卫：禁止 `repo_router.py` 回潮、禁止生产直调旧入口或绕过 V2 调摘要通道。

## 验证

- `ruff check`：通过。
- `git diff --check`：通过。
- 仓库路由、LayeredSearch、MCP 与 NullProvider 定向回归：126 条用例执行。

## 提交

按会话约束未创建 git commit，修改保留在工作区。
