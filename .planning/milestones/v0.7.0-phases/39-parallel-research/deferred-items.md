# Phase 39 Deferred / Out-of-Scope Items

## Deferred (per CONTEXT/plan — 沿用既有里程碑惯例)
- status: acknowledged

- **真实容器端到端验收**：本 phase 全程以 mock dispatcher/runner/callback payload 覆盖
  dispatch 逻辑、prompt 注入、回调解析、barrier 聚合、stale 失效；真实 runner + docker +
  编码 agent 的端到端验收延后（本地无 runner+docker，对齐既有里程碑 deferred）。
- 架构师融合消费 valid partial → MergedPlan + PlanValidator（Phase 40）。
- Clarification 回路 + 事件 sink 基础设施完整化（Phase 41，本 phase `_emit_event` 仍为钩子占位）。
- 跨仓 partial 全局依赖 DAG 提取（融合 Phase 40 做；本 phase 仅产 `dependencies_on_other_repos` 字段）。

## Pre-existing / Environmental (NOT Phase 39 regression)
- status: acknowledged

扫描发现以下 3 个测试在本环境失败，经在 Phase 39 之前的 base 提交
（`abcaece7`）复跑确认**同样失败**——根因 `orchestration/coding_graph.py`
`_call_llm_for_pr_draft` 抛 `ValueError: Anthropic API key 未配置`（本地未 seed
Anthropic 凭证，`provider_credential_seed_skipped reason=anthropic_api_key_missing`）。
与 Phase 39（RepoResearchTask/PartialPlan/research callback routing）无关，出本 phase
SCOPE BOUNDARY，不修：

- `tests/test_coding_session.py::TestCodingSessionConfirmAPI::test_confirmed_without_subagent_restarts_graph`
- `tests/test_coding_session_graph_e2e.py::test_http_callback_resumes_graph_to_awaiting_commit_confirm`
- `tests/test_coding_session_graph_e2e.py::test_ws_callback_resumes_graph_same_as_http`
