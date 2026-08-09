---
phase: 122
slug: impact-trace
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-09
---

# Phase 122 — Validation Strategy

> 完整的 Requirements → Test Map（26 行）在 `122-RESEARCH.md` §Validation Architecture，
> 本文件是它的执行契约摘要。**planner 必须让每个 task 在那张表里有落点**，并把 Task ID / Plan / Wave 填回。

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

> **权威表在 `122-RESEARCH.md` §Validation Architecture**（26 行，逐条给了 Req ID / Behavior /
> Test Type / Automated Command / File Exists）。planner 补 Task ID / Plan / Wave 三列即可，
> ⛔ 不要重写那张表的 Behavior 与命令列。

覆盖面速查：

| Req | 断言条数 | 关键点 |
|---|---|---|
| IMPACT-01 | 3 | 深度分组逐点、`max_depth` 生效、**内核不修改入参图**（fixture 已 freeze，就地改必抛） |
| IMPACT-02 | 3 | 逐边 confidence + reason + `path_confidence`（path-min，D-07）、`min_confidence` 单调收缩、**D-08 双闸** |
| IMPACT-03 | 5 | 跨仓四分支（成功 / 无权限折叠 / 对端不可用 fail-soft / 跳数上限）+ **反向守护：图内 `cross_repo` 边两端必同仓** |
| IMPACT-04 | 2 | 风险四级在 d1 = 2/3/7/8/19/20 边界逐点、截断计数与排序 |
| IMPACT-05 | 5 | 逐跳渲染、等长多解声明、无路径显式结构、重名候选列表、uid 优先 |
| IMPACT-06 | 5 | MCP PAT fail-closed、schema snapshot 双向、对话壳注册与白名单、**双面同源 payload 逐字节相同**、staleness 不编造 |
| 横切 | 3 | 四标记 + **数值 `resolution_rate`** 透出（D-23）、超预算走种子子图不吃 `GraphError`（D-24）、被排除文件在输出中不可见（GRAPH-04 端到端回填） |

---

## Wave 0 Requirements

- [ ] `tests/services/code_graph/conftest.py` — **追加** `known_topology()` 合成冻结图 fixture（现有 conftest 只有 DB fixtures）。这是 IMPACT-01/02/04/05 全部内核断言的地基，必须能逐点核对深度与最短路。
- [ ] `tests/services/code_graph/test_impact.py`（IMPACT-01/02/04）
- [ ] `tests/services/code_graph/test_trace.py`（IMPACT-05）
- [ ] `tests/services/code_graph/test_symbol_resolve.py`（D-19 重名消歧）
- [ ] `tests/services/code_graph/test_cross_repo_hop.py`（IMPACT-03；需 DB：两个 `Repository` + `Endpoint` + `ApiCallSite` + `CrossRepoApiCall` 工厂——**生产零样本，全部靠合成**）
- [ ] `tests/services/code_graph/test_staleness.py`（D-22）
- [ ] `tests/services/code_graph/test_impact_shell.py`（D-24 超预算分支）
- [ ] `tests/mcp_tools/test_impact_trace_tools.py`（IMPACT-06 + D-21 双面同源 + D-23 + GRAPH-04 回填）
- [ ] `tests/agents/tools/test_graph_tools.py`（对话壳注册与白名单）
- [ ] `tests/mcp_tools/test_schema_snapshot.py` — **修改**，加两条手写字面量条目
- [ ] 框架安装：**无需** —— pytest 全套已在

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 跨仓 impact 在**真实**数据上的正确性与命中率 | IMPACT-03 | 生产库 `CrossRepoApiCall` / `ApiCallSite` / `ApiWrapper` 均为 **0 行**，上游产出器依赖 volar LSP 而 server 镜像无 Node（归 LSP-01 / Phase 127） | Phase 127 补齐 LSP 并重建索引后，取一对真实前后端仓复验四条分支，并测出 `(file_path, name)` 二次解析命中率 |
| 热点符号（入度 max 2,803）的真实响应时延 | IMPACT-04 | 需真实大仓与真实并发 | 工具上线后观察 `code_graph_*` 事件的 `duration_ms` 分布，据此复校 200 条截断上限 |
| 风险四级阈值是否符合工程直觉 | IMPACT-04 | 阈值初值未经真实样本校准（CONTEXT D-15 已声明） | 收集真实使用样本后回来校准，照 121-10 的复校范式 |

> ⚠️ 前两项**不阻塞本相位完成**，但必须在 SUMMARY 与 ROADMAP 里如实记账。
> 尤其 IMPACT-03：合成数据通过**不得**表述为「跨仓能力已验证」（CONTEXT D-26）。

---

## Validation Sign-Off

- [ ] 所有 task 在 `122-RESEARCH.md` §Validation Architecture 的表里有落点
- [ ] Sampling continuity: 不存在连续 3 个 task 没有自动化验证
- [ ] Wave 0 覆盖全部 MISSING 引用
- [ ] 无 watch-mode 标志
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` 写回 frontmatter

**Approval:** pending
