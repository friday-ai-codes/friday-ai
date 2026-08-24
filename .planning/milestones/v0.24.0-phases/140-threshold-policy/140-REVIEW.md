---
phase: 140
phase_name: threshold-policy
status: fixed
depth: standard
files_reviewed: 25
findings:
  critical: 0
  warning: 1
  info: 0
  total: 1
fixed: 1
remaining: 0
reviewed_at: 2026-08-25
---

# Phase 140 Code Review

## Scope

按 `1434db96..HEAD` 与四份 SUMMARY 合并去重，审查 Phase 140 的 25 个源码、fixture 与测试文件，重点覆盖：

- benchmark identity、resolver cell、policy loader 与 paired comparator；
- evaluate/compare management commands 的 I/O、hash、holdout 与日志边界；
- GraphQueryService caller 生命周期、resolver/Process/retrieval/impact sampling 与脱敏；
- closure regression、task 允许工具及 npm MCP 生成物连接点。

## Findings

### WR-140-01 — threshold policy 未拒绝未知扩展字段

- **Severity:** Warning
- **Files:** `server/codegraph/services/graph_bench_compare.py`, `server/tests/codegraph/test_graph_bench_policy.py`
- **Status:** Fixed
- **Evidence:** loader 已对 `comparison_identity` 与 `system_identity` 做 exact-key 校验，但 policy 顶层、`baseline`、`insufficient_data`、每条 gate 和 primary metric 接受任意未知字段。这与“静态、内容寻址、闭集、无隐式扩展”的 policy 契约不一致，也可能让审计者误以为未知字段参与门禁。
- **Fix:** 为五层结构增加 exact-key 闭集，并新增参数化回归覆盖所有层级。
- **Commit:** `3f77225e`
- **Verification:** policy/comparator/command 专项 `78 passed`；Ruff lint/format 通过。

## Security and Observability Review

- 未发现凭证明文、query 正文日志、未脱敏异常或 ledger 绕过。
- caller 事件带 `category/component/initiated_by_user_id/duration_ms`；内部高频路径使用 debug/sampling。
- compare command 只写显式 output，不修改 baseline/policy；holdout 默认拒读并要求 `--final-acceptance`。
- 权限/exclusion 仍由 canonical `GraphService.get_graph` 入口 fail-closed，closure 与既有行为测试共同守护。

## Residual Risk

- 无未修复 Critical/Warning。
- 真实 v0.22 baseline、独立 gold、已索引目标仓、Qdrant 与 candidate 不在本地环境中，数值提升验证保持 `HUMAN_NEEDED`；这属于外部证据债，不是代码审查缺陷。

## Result

**FIXED — 1/1 finding 已自动修复，剩余 0。**
