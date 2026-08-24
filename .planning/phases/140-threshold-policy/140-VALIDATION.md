---
phase: 140
slug: threshold-policy
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-08-24
---

# Phase 140 — Validation Strategy

> Threshold policy、paired comparator、resolver 分桶与可观测性收口的分层验证契约。

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 + pytest-asyncio/pytest-django；npm Vitest 4 |
| **Config file** | `server/pyproject.toml`、`task/pyproject.toml`、`mcp/package.json` |
| **Quick run command** | `cd server && uv run pytest tests/codegraph/test_graph_bench_policy.py tests/codegraph/test_graph_bench_compare.py tests/codegraph/test_graph_bench_resolver_metrics.py -x -q` |
| **Full suite command** | `cd server && uv run pytest tests/codegraph/test_graph_bench_*.py codegraph/resolver/tests tests/services/code_graph tests/mcp_tools/test_graph_query_tool.py -q --reuse-db` |
| **Estimated runtime** | quick < 60 秒；phase gate 依环境约 5–20 分钟 |

## Sampling Rate

- **After every task commit:** 运行该任务新增或修改测试文件的最小 pytest 集。
- **After every plan wave:** 运行 benchmark、resolver、query service、Process、impact 与 access/conformance 组合测试。
- **Before phase verification:** server 组合回归、task 全量、npm MCP test/typecheck/build/pack 必须全绿。
- **Max feedback latency:** 单任务自动反馈目标 < 90 秒；真实 benchmark 单独记录。

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 140-01-01 | 01 | 1 | BENCH-07, EDGE-06 | T-140-02/03 | identity/case-set/evaluator 与 resolver denominator fail-closed | unit | `cd server && uv run pytest tests/codegraph/test_graph_bench_resolver_metrics.py -x -q` | ❌ W0 | ⬜ pending |
| 140-01-02 | 01 | 1 | BENCH-07 | T-140-02/03 | run artifact 保留 system/comparison identity 且不可混水位 | integration | `cd server && uv run pytest tests/codegraph/test_graph_bench_integration.py -x -q` | ✅ extend | ⬜ pending |
| 140-02-01 | 02 | 2 | BENCH-06 | T-140-01/02 | policy 缺键、占位、hash、默认方向/容差均拒绝 | unit | `cd server && uv run pytest tests/codegraph/test_graph_bench_policy.py -x -q` | ❌ W0 | ⬜ pending |
| 140-02-02 | 02 | 2 | BENCH-06, BENCH-07 | T-140-01/02/03 | comparator 四态、required sparse、逐例配对与 hash pin | unit | `cd server && uv run pytest tests/codegraph/test_graph_bench_compare.py -x -q` | ❌ W0 | ⬜ pending |
| 140-02-03 | 02 | 2 | BENCH-07 | T-140-01/02 | compare command 只读输入、输出三 hash 与非零失败码 | command integration | `cd server && uv run pytest tests/codegraph/test_compare_graph_bench_command.py -x -q` | ❌ W0 | ⬜ pending |
| 140-03-01 | 03 | 2 | OBS-01 | T-140-04 | caller 三事件无 query/凭证，logger 失败不反噬 | async unit | `cd server && uv run pytest tests/services/code_graph/test_query_observability.py -x -q` | ❌ W0 | ⬜ pending |
| 140-03-02 | 03 | 2 | OBS-02 | T-140-04 | resolver/Process/lane/impact 仅 sampling 汇总，无 INFO 循环 | unit + static | `cd server && uv run pytest tests/services/code_graph/test_graph_query_sampling.py tests/services/code_graph/test_access.py -x -q` | ❌ W0 / ✅ extend | ⬜ pending |
| 140-04-01 | 04 | 3 | BENCH-06, BENCH-07, EDGE-06 | T-140-01/02/03 | 同条件 candidate 只有 required gates 全过才 PASS | external integration | `cd server && uv run python manage.py compare_graph_bench ...` | ❌ 需真实 artifacts | ⬜ pending |
| 140-04-02 | 04 | 3 | OBS-01, OBS-02 | T-140-04/05/06 | 权限/exclusion、触发用户、partial、hash、水位全量不回归 | regression | 运行 phase full suite、task 全量与 npm MCP 构建回归 | ✅ combine | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

## Wave 0 Requirements

- [ ] `tests/codegraph/test_graph_bench_policy.py` — policy schema/hash/pin/immutability。
- [ ] `tests/codegraph/test_graph_bench_compare.py` — paired comparator 与四态 gate。
- [ ] `tests/codegraph/test_graph_bench_resolver_metrics.py` — resolver cell 指标和 denominator。
- [ ] `tests/codegraph/test_compare_graph_bench_command.py` — 薄 I/O command。
- [ ] `tests/services/code_graph/test_query_observability.py` — caller 生命周期、无正文、best-effort。
- [ ] `tests/services/code_graph/test_graph_query_sampling.py` — sampling 事件与 INFO/query 正文守卫。
- [ ] 真实目标仓、独立 gold、非占位 manifest、v0.22 baseline report/run manifest/hashes。
- [ ] token 按 run/case 归因；若环境无法闭合则明确 `INSUFFICIENT_DATA`，不得把 0 当通过。
- [ ] holdout final-only 数据与开启审计；普通测试不读取 holdout 正文。

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 真实 v0.22 baseline 的身份、独立 gold、hash 与阈值推导审查 | BENCH-06 | 当前仓无真实已索引目标仓和合法 baseline artifact | 在固定 target repo/branch/commit 上运行 v0.22 command，核对 OK watermark、样本量、raw trials、report/manifest SHA-256，再审查 policy 每个 gate 的来源 |
| 同条件 v0.24 candidate 与最终 holdout | BENCH-07, EDGE-06 | 依赖真实 Qdrant/embedding/目标仓环境，默认 pytest 不可替代 | 使用相同 comparison identity 运行 candidate，显式 final-only 打开 holdout，compare verdict 必须 PASS；保存两命令、三 hash 与逐例 diff |

## Validation Sign-Off

- [x] 所有任务都有自动验证或明确 Wave 0 依赖。
- [x] 不允许连续 3 个任务缺少自动验证。
- [x] Wave 0 覆盖全部缺失测试引用。
- [x] 无 watch-mode 参数。
- [x] 自动反馈延迟目标已定义。
- [x] `nyquist_compliant: true` 已设置。

**Approval:** approved 2026-08-24（真实 baseline/candidate 项在执行期按 `human_needed` 路由）
