---
phase: 122
slug: impact-trace
status: planned
nyquist_compliant: true
wave_0_complete: false
created: 2026-08-09
---

# Phase 122 — Validation Strategy

> 完整的 Requirements → Test Map（27 行）在 `122-RESEARCH.md` §Validation Architecture，
> 本文件是它的执行契约摘要。**planner 已让每个 task 在那张表里有落点**，Task ID / Plan / Wave 见下方 §Per-Task Verification Map。

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | `pytest>=9.0.2` + `pytest-django>=4.8` + `pytest-asyncio`（`asyncio_mode = "auto"`） |
| **Config file** | `server/pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run（内核，零 DB）** | `cd server && uv run pytest tests/services/code_graph/test_impact.py tests/services/code_graph/test_trace.py -q` |
| **Scoped run** | `cd server && uv run pytest tests/services/code_graph -q` |
| **Full suite（相位门）** | `cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest --reuse-db` |
| **Estimated runtime** | quick 秒级；scoped ~1.5 min；相位门 ~35 min |

🚨 **本机跑库相关用例的必备前缀**：`GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False`，
否则 app-init 守护线程占住 `test_friday` 导致建库失败；配 `--reuse-db` 省重建。

🚨 **绝不在生产 PostgreSQL 上跑全量**：121-10 实测 75 分钟只推进 25%（跨网每查询约 6ms RTT），全量约 10 小时。

---

## Sampling Rate

- **After every task commit:** `cd server && uv run pytest tests/services/code_graph/ -q`（内核部分零 DB，秒级）
- **After every wave:** `cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest tests/services/code_graph/ tests/mcp_tools/ tests/agents/ --reuse-db -q`
- **Phase gate:** 全量 + `ruff check services/code_graph/ mcp_tools/ agents/tools/` + `mypy services/code_graph/` + `makemigrations --check --dry-run`（本相位零迁移，退出码必须 0）
- **Max feedback latency:** 15 秒（quick run）

---

## Per-Task Verification Map

> **权威表在 `122-RESEARCH.md` §Validation Architecture**（27 行，逐条给了 Req ID / Behavior /
> Test Type / Automated Command / File Exists）。⛔ 本文件不重写那张表的 Behavior 与命令列，
> 只补 Plan / Task / Wave 三列的落点。

| # | Req | Test 节点 | Plan | Task | Wave |
|---|-----|-----------|------|------|------|
| 1 | IMPACT-01 | `test_impact.py::test_depth_grouping` | 122-03 | T1 | 1 |
| 2 | IMPACT-01 | `test_impact.py::test_max_depth_budget` | 122-03 | T1 | 1 |
| 3 | IMPACT-01 | `test_impact.py::test_kernel_does_not_mutate_graph` | 122-03 | T1 | 1 |
| 4 | IMPACT-02 | `test_impact.py::test_edge_confidence_and_reason` | 122-03 | T1 | 1 |
| 5 | IMPACT-02 | `test_impact.py::test_min_confidence_filter` | 122-03 | T2 | 1 |
| 6 | IMPACT-02 | `test_impact.py::test_bare_name_requires_both_gates` | 122-03 | T2 | 1 |
| 7 | IMPACT-03 | `test_cross_repo_hop.py::test_cross_repo_success` | 122-06 | T1（前半）+ T2（后半） | 3 |
| 8 | IMPACT-03 | `test_cross_repo_hop.py::test_unauthorized_repo_redacted` | 122-06 | T2 | 3 |
| 9 | IMPACT-03 | `test_cross_repo_hop.py::test_peer_unavailable_fail_soft` | 122-06 | T2 | 3 |
| 10 | IMPACT-03 | `test_cross_repo_hop.py::test_hop_budget` | 122-06 | T2 | 3 |
| 11 | IMPACT-03 | `test_impact.py::test_graph_cross_repo_edges_are_intra_repo` | 122-06 | T3 | 3 |
| 12 | IMPACT-04 | `test_impact.py::test_risk_levels` | 122-03 | T3 | 1 |
| 13 | IMPACT-04 | `test_impact.py::test_truncation_summary` | 122-03 | T3 | 1 |
| 14 | IMPACT-05 | `test_trace.py::test_shortest_path_hops` | 122-04 | T1 | 1 |
| 15 | IMPACT-05 | `test_trace.py::test_equal_length_paths_declared` | 122-04 | T2 | 1 |
| 16 | IMPACT-05 | `test_trace.py::test_no_path_explicit_structure` | 122-04 | T1 | 1 |
| 17 | IMPACT-05 | `test_symbol_resolve.py::test_ambiguous_returns_candidates` | 122-05 | T3 | 2 |
| 18 | IMPACT-05 | `test_symbol_resolve.py::test_uid_takes_precedence` | 122-02 | T1 | 1 |
| 19 | IMPACT-06 | `test_impact_trace_tools.py -k "auth or not_indexed"`（`test_impact_tool_unauthenticated` / `test_impact_tool_repository_not_indexed`） | 122-08 | T3 | 5 |
| 20 | IMPACT-06 | `test_schema_snapshot.py`（urls ↔ snapshot 双向 + 逐字快照两条目） | 122-08 | T2 | 5 |
| 21 | IMPACT-06 | `test_graph_tools.py::test_registered_and_whitelisted` | 122-09 | T2 | 6 |
| 22 | IMPACT-06 | `test_impact_trace_tools.py::test_two_surfaces_same_payload` | 122-10 | T1 | 7 |
| 23 | IMPACT-06 | `test_staleness.py`（`test_behind_commits_reported` / `test_behind_commits_none_degrades_to_as_of`） | 122-05 | T2 | 2 |
| 24 | D-23 | `test_impact_trace_tools.py::test_degradation_markers_surfaced` | 122-08 | T3 | 5 |
| 25 | D-24 | `test_impact_shell.py::test_over_budget_uses_seeded_subgraph` | 122-05 | T1 | 2 |
| 26 | D-04 | `test_access.py -k "observability or upper_layer or barrel"`（既有守护，新模块自动进扫描） | 122-02 / 122-03 / 122-04 各自 T1 的 `<verify>`；扫描面扩展见 122-05 T4 与 122-06 T2 | T1 / T4 / T2 | 1–3 |
| 27 | GRAPH-04 回填 | `test_impact_trace_tools.py::test_excluded_files_invisible` | 122-08 | T3 | 5 |

### Planner 追加行（RESEARCH 表未列，但由 CONTEXT / PATTERNS 的硬要求推出）

| # | 来源 | Test 节点 | Plan | Task | Wave |
|---|------|-----------|------|------|------|
| A1 | Wave 0 地基 | `test_impact.py::test_known_topology_fixture_is_frozen`（冻结图 fixture 自检，节点数 13） | 122-01 | T1 | 0 |
| A2 | D-19 | `test_symbol_resolve.py::test_ambiguous_never_silently_picks_first` / `test_candidate_list_is_capped` | 122-02 | T1 | 1 |
| A3 | D-03 | `test_impact_shell.py::test_graph_error_translated_not_swallowed` | 122-05 | T1 | 2 |
| A4 | D-23 | `degradation_payload` 单测（`low_resolution=False` 时仍出解析率声明） | 122-05 | T2 | 2 |
| A5 | D-19 | `test_impact_shell.py::test_ambiguous_symbol_short_circuits_before_graph_fetch` | 122-07 | T1 | 4 |
| A6 | D-21 / D-22 / D-23 | `test_run_impact_envelope_always_declares` / `test_run_impact_does_not_swallow_graph_error` / `test_symbol_not_in_graph_is_explicit` | 122-07 | T1 | 4 |
| A7 | D-18 / D-20 | `test_run_trace_envelope` / `test_run_trace_no_path_is_ok_true` / `test_run_trace_ambiguous_short_circuits` | 122-07 | T2 | 4 |
| A8 | D-24 落差 | `test_run_trace_no_path_on_subgraph_declares_uncertainty`（`degraded` 以 `on_demand_subgraph` 开头 且 `found is False` 时必须出补充声明） | 122-07 | T2 | 4 |
| A9 | IMPACT-06 / D-22 | `test_impact_trace_tools.py::test_staleness_declared`（端到端：`behind_commits=7` → 声明含数字） | 122-08 | T3 | 5 |
| A10 | PATTERNS 硬要求 | `test_graph_tools.py::test_conversation_owner_required_fail_closed`（🚨 `get_graph(user=None)` 走系统路径不会拒，对话壳必须自己挡） | 122-09 | T2 | 6 |
| A11 | 观测规范 | `test_impact_trace_tools.py::test_degradation_markers_surfaced` 内的三条观测断言（`RetrievalTrace` 恰 1 条 / payload 无正文 / `RequestMetric(route="mcp:impact_analysis")` 存在） | 122-08 | T3 | 5 |
| A12 | D-04 扫描面 | `test_access.py::test_observability_contract` 扩展到包外兄弟模块（含一次**变异测试**实跑证明守护有效） | 122-05 / 122-06 | T4 / T2 | 2 / 3 |
| A13 | D-26 / D-27 | ROADMAP 两笔记账的文件级断言（Phase 127 复验行 + 漂移 5→7 带两个工具名） | 122-10 | T2 | 7 |

覆盖面速查：

| Req | 断言条数 | 关键点 |
|---|---|---|
| IMPACT-01 | 3 | 深度分组逐点、`max_depth` 生效、**内核不修改入参图**（fixture 已 freeze，就地改必抛） |
| IMPACT-02 | 3 | 逐边 confidence + reason + `path_confidence`（path-min，D-07）、`min_confidence` 单调收缩、**D-08 双闸**（观察点 `X` 只经裸名边可达，由 122-01 交付） |
| IMPACT-03 | 5 | 跨仓四分支（成功 / 无权限折叠 / 对端不可用 fail-soft / 跳数上限）+ **反向守护：图内 `cross_repo` 边两端必同仓** |
| IMPACT-04 | 2 | 风险四级在 d1 = 2/3/7/8/19/20 边界逐点、截断计数与排序 |
| IMPACT-05 | 5 | 逐跳渲染、等长多解声明、无路径显式结构、重名候选列表、uid 优先 |
| IMPACT-06 | 5 | MCP PAT fail-closed、schema snapshot 双向、对话壳注册与白名单、**双面同源 payload 逐字节相同**、staleness 不编造 |
| 横切 | 3 | 四标记 + **数值 `resolution_rate`** 透出（D-23）、超预算走种子子图不吃 `GraphError`（D-24）、被排除文件在输出中不可见（GRAPH-04 端到端回填） |
| 观测规范 | 4 | 两面各一条 `caller` 事件（绑定触发用户）+ 各一条汇总 `RetrievalTrace`；`RequestMetric` 覆盖新入口；AST 观测契约扫描面覆盖包外兄弟模块 |

---

## Wave 0 Requirements

- [ ] `tests/services/code_graph/conftest.py` — **追加** `known_topology()` 合成冻结图 fixture（现有 conftest 只有 DB fixtures）。这是 IMPACT-01/02/04/05 全部内核断言的地基，必须能逐点核对深度与最短路；节点数 **13**（A–H + P/Q/R/S + 只经裸名边可达的观察点 `X`）
- [ ] `tests/services/code_graph/test_impact.py`（IMPACT-01/02/04；1 真 + 9 桩 = 10 节点）
- [ ] `tests/services/code_graph/test_trace.py`（IMPACT-05；3 桩）
- [ ] `tests/services/code_graph/test_symbol_resolve.py`（D-19 重名消歧；2 桩）
- [ ] `tests/services/code_graph/test_cross_repo_hop.py`（IMPACT-03；需 DB：两个 `Repository` + `Endpoint` + `ApiCallSite` + `CrossRepoApiCall` 工厂——**生产零样本，全部靠合成**；4 桩）
- [ ] `tests/services/code_graph/test_staleness.py`（D-22；2 桩）
- [ ] `tests/services/code_graph/test_impact_shell.py`（D-24 超预算分支；3 桩）
- [ ] `tests/mcp_tools/test_impact_trace_tools.py`（IMPACT-06 + D-21 双面同源 + D-23 + GRAPH-04 回填；6 桩）
- [ ] `tests/agents/tools/test_graph_tools.py`（对话壳注册与白名单；2 桩）
- [ ] `tests/mcp_tools/test_schema_snapshot.py` — **修改**，加两条手写字面量条目（归 122-08 T2，与 urls + `TOOL_SCHEMA_SNAPSHOT` 同批）
- [ ] 框架安装：**无需** —— pytest 全套已在

Wave 0 收尾核对：`--collect-only` 在三个零 DB 文件上收集到 **15** 个节点；五个壳层测试文件合计 **17 skipped**。

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 跨仓 impact 在**真实**数据上的正确性与命中率 | IMPACT-03 | 生产库 `CrossRepoApiCall` / `ApiCallSite` / `ApiWrapper` 均为 **0 行**，上游产出器依赖 volar LSP 而 server 镜像无 Node（归 LSP-01 / Phase 127） | Phase 127 补齐 LSP 并重建索引后，取一对真实前后端仓复验四条分支，并测出 `(file_path, name)` 二次解析命中率。**记账落点：122-10 T2 写进 ROADMAP 的 Phase 127 条目（D-26）** |
| 热点符号（入度 max 2,803）的真实响应时延 | IMPACT-04 | 需真实大仓与真实并发 | 工具上线后观察 `code_graph_*` 事件的 `duration_ms` 分布，据此复校 200 条截断上限 |
| 风险四级阈值是否符合工程直觉 | IMPACT-04 | 阈值初值未经真实样本校准（CONTEXT D-15 已声明） | 收集真实使用样本后回来校准，照 121-10 的复校范式 |
| `mcp` npm 包工具面对齐 | IMPACT-06 | `mcp` 是 submodule 且正被并发会话修改（D-27 ⛔ 全程不碰） | 另批发版时在 `mcp/src/tools.ts` 的 `FRIDAY_TOOLS` 补 7 条。**记账落点：122-10 T2 把漂移数从 5 更新为 7（D-27）** |

> ⚠️ 前两项**不阻塞本相位完成**，但必须在 SUMMARY 与 ROADMAP 里如实记账。
> 尤其 IMPACT-03：合成数据通过**不得**表述为「跨仓能力已验证」（CONTEXT D-26）。

---

## Validation Sign-Off

- [x] 所有 task 在 `122-RESEARCH.md` §Validation Architecture 的表里有落点（27 行逐条填了 Plan / Task / Wave；13 条 planner 追加行另表列出）
- [x] Sampling continuity: 不存在连续 3 个 task 没有自动化验证（10 个 plan 的每个 task 都有 `<verify><automated>`）
- [x] Wave 0 覆盖全部 MISSING 引用（9 个新建测试文件 + conftest 追加；`test_schema_snapshot.py` 的两条字面量归 122-08 T2 与 urls 同批）
- [x] 无 watch-mode 标志
- [x] Feedback latency < 15s（零 DB 内核用例秒级）
- [x] `nyquist_compliant: true` 写回 frontmatter

**Approval:** planner-signed 2026-08-09（10 plans / 8 waves）
