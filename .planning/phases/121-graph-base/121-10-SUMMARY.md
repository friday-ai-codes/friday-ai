---
phase: 121-graph-base
plan: 10
subsystem: testing
tags: [code_graph, perf, tracemalloc, rss, calibration, resolution-rate, phase-gate, networkx]

# Dependency graph
requires:
  - phase: 121-graph-base (121-07)
    provides: "estimate_graph_bytes / NODE_COST_BYTES / EDGE_COST_BYTES 与字节预算 LRU"
  - phase: 121-graph-base (121-05)
    provides: "loader._CallEdgeStats.resolution_rate —— 解析率统计必须与它同口径"
  - phase: 121-graph-base (121-02)
    provides: "LOW_RESOLUTION_THRESHOLD 契约常量（本 plan 校准它的取值）"
  - phase: 121-graph-base (121-09)
    provides: "封口后的 code_graph 包与 86 passed 的测试基线"
provides:
  - "test_perf_diagnostics.py：两个 @pytest.mark.perf 的一次性诊断用例（默认跳过），在干净子进程里直连生产库出数"
  - "字节常数的生产实测复校：NODE_COST 640 → 800、EDGE_COST 560 → 680（实测 733 B/节点、626 B/边）"
  - "假设 A1 的回答：rss/tracemalloc = 1.081（RSS 确实更高，但只是 8% 量级，不是数量级）"
  - "假设 A2 的回答：生产准入口径边:节点 = 3.40:1；实际入图口径只有 0.73:1"
  - "假设 A5 的回答：218 个已索引仓库的解析率分布 p10=0.0762 / p50=0.1697 / p90=0.2426，阈值 0.6 → 0.10"
  - "单图容量结论重定：256MB 触顶点从「约 11 万符号」下调到「约 8.6 万」"
  - "相位门：零迁移守护（makemigrations --check）+ 全量测试 / ruff / mypy 的 delta 记录"
affects: [122-impact-analysis, 125-容量规划, 任何调整 CODE_GRAPH_* 预算默认值的运维动作]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "内存实测必须在干净子进程里做：胖进程（Django + langchain + llama-index）的堆上有几百 MB 已驻留空闲页，RSS 增量在那里只是下界"
    - "RSS 与 tracemalloc 分两趟量：tracemalloc 的 traceback 账本本身会计进 RSS"
    - "取 tracemalloc 的 retained（current）而非 peak：常数标定的是图**留下来**的那部分"
    - "「节点-only + full」两次测量差分出每节点 / 每边成本 —— 一个总数回答不了「该上调哪个常数」"
    - "诊断的行数据全程流式（生成器 / 服务端游标），与 loader 的 .iterator() 同形，避免临时行顶高测量值"
    - "记账类断言经 _entry_bytes() 派生，⛔ 不写死 1200/2400 这类常数派生字面量"

key-files:
  created:
    - server/tests/services/code_graph/test_perf_diagnostics.py
  modified:
    - server/services/code_graph/cache.py
    - server/services/code_graph/model.py
    - server/friday/settings.py
    - server/tests/services/code_graph/test_cache.py
    - server/tests/services/code_graph/test_loader.py
    - server/tests/services/code_graph/test_model.py

key-decisions:
  - "诊断数据源改用**生产 PostgreSQL**：pytest 连的是空测试库，本地 sqlite 快照落后一个数量级（11k vs 31k 符号 / 6 vs 218 个仓），拿它标定等于标定一个不存在的仓库形态"
  - "连接串只经环境变量继承传给子进程，⛔ 不进 argv（argv 会出现在 ps 输出里）"
  - "常数取「真实仓与合成图逐项最大值 × 1.05」：真实仓每项都更贵，因为属性字符串在真实数据里长得多"
  - "rss/tracemalloc = 1.081 < 1.15 的上调判据，故不再叠加 RSS 系数；最终裕度 1.091/1.086 本身已高于 1.081"
  - "LOW_RESOLUTION_THRESHOLD 校准为 0.10 而非「保持 0.6」：0.6 命中 218/218，永远触发的标记等于不存在的标记"
  - "校准后 low_resolution 的语义改为「比本仓常态更差」的异常标记，并把「Phase 122 必须始终透出数值 resolution_rate」写成硬要求"
  - "容量测试改用准入口径（3.40:1）而非入图口径（0.73:1）：准入判据看不到后者，用它会去守一个永远算不出来的数"

patterns-established:
  - "一次性诊断交付物的形态：@pytest.mark.perf + 默认 addopts 排除 + 结论双处留痕（源码注释 + SUMMARY）+ 注释里写明重跑命令"
  - "「跑完不留痕」是被禁止的：即便复校结论是「维持原值」，也要在常数注释里追加一行带日期的复校记录"
  - "诊断输出的脱敏纪律：只出仓库名 / 计数 / 比率 / 扩展名，⛔ 无 file_path 明细、无符号名、无连接串"

requirements-completed: [GRAPH-01, GRAPH-02, GRAPH-03, GRAPH-04]

# Metrics
duration: ~130min
completed: 2026-08-09
---

# Phase 121 Plan 10: 诊断交付物与相位门 Summary

本 plan 是 Phase 121 的收口：把三个「先落保守值、等真实数据说话」的常数用生产数据复校，并跑完相位门。

## 交付物

### 1. `test_perf_diagnostics.py` —— 两个一次性诊断用例

均为 `@pytest.mark.perf`，被 `addopts` 的 `-m 'not perf ...'` 默认跳过，重跑命令写在源码注释里：

```
cd server && uv run pytest -m perf tests/services/code_graph/ -s
```

⚠️ 本机重跑的前置：`test_friday` 若被 app-init 守护线程占住会导致建库失败，需带
`GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False` 与 `--reuse-db`。

数据源是**生产 PostgreSQL**，不是 pytest 的空测试库：本地 sqlite 快照落后一个数量级
（11k vs 31k 符号 / 6 vs 218 个仓），拿它标定等于标定一个不存在的仓库形态。连接串只经
环境变量继承传给子进程，不进 argv。

### 2. 字节常数复校：640/560 → **800/680**

实测每节点 733 B、每边 626 B（由「节点-only」与「full」两次测量差分得到），
取「真实仓与合成图逐项最大值 × 1.05」再向上取整。真实仓每项都更贵，因为属性字符串
在真实数据里比合成图长得多。

两个原假设的答案：
- **A1（RSS 远高于 tracemalloc）—— 否。** 合成参照图 `rss/tracemalloc = 0.984`，生产仓 1.081，
  都低于 1.15 的上调判据，因此不再额外叠加 RSS 系数；最终裕度 1.091/1.086 本身已覆盖。
- **A2（边:节点 = 3:1）—— 分口径。** 准入估算口径（`CallEdge` 原始行数 104,192 / `Symbol` 30,632）
  = **3.40:1**；实际入图口径（解析边且两端都在节点集内）只有 **0.73:1**。准入判据用的是前者，
  所以它对真实入图规模是**高估**，方向安全。

**容量结论重定：** 256 MB 单图上限的触顶点从「约 11 万符号」下调到「约 8.6 万」。

### 3. `LOW_RESOLUTION_THRESHOLD` 校准：0.6 → **0.10**

218 个已索引且有调用边的仓库，解析率分布 **p10=0.0762 / p50=0.1697 / p90=0.2426**。

原值 0.6 命中 218/218 —— 一个永远触发的标记等于不存在的标记。校准到 0.10 后命中 **38/218**，
既不长鸣也非永不触发。

按扩展名（以 `caller_file` 后缀近似，本仓无 language 字段）：

| ext | call_edges | resolved | rate |
|---|---|---|---|
| .go | 1,355,803 | 263,334 | 0.1942 |
| .vue | 101,981 | 19,156 | 0.1878 |
| .ts | 63,864 | 9,321 | 0.1460 |
| .py | 10,711 | 1,582 | 0.1477 |
| .tsx | 44,669 | 4,622 | 0.1035 |
| .js | 8,109 | 201 | 0.0248 |

**这个数字改变了 `low_resolution` 的语义**：全仓解析率普遍在 17% 量级，所以它不再是
「这个仓不可信」，而是「这个仓比本仓常态更差」的**异常标记**。由此派生一条对 Phase 122 的硬要求：
**必须始终透出数值 `resolution_rate`**，不能只透出布尔标记 —— 布尔值在 17% 的常态下没有信息量。

## 相位门结果

| 检查 | 结果 |
|---|---|
| `pytest tests/services/code_graph` | **86 passed / 0 skipped** |
| `pytest -m perf tests/services/code_graph/` | **2 passed**（两个诊断均出数） |
| `makemigrations --check --dry-run` | **No changes detected** —— 「零新模型 / 零迁移」守护通过 |
| `ruff check services/code_graph tests/services/code_graph` | **All checks passed** |
| `mypy services/code_graph` | 包内 **0 error**（全局 127 个为既有，经 follow-imports 带出） |
| 全量 `pytest` | **10 failed / 10128 passed / 61 skipped**（34m27s） |

### 全量套件 10 条失败的归因（逐条查证，均与本相位无关）

用两个临时 worktree 做了双向对照，**不触碰工作区里的未提交改动**：

- **6 条在相位 121 之前的基线（`85736953`）就已失败** ⇒ 既有问题：
  `test_blueprint_export_views` / `test_project_branch_inv6_guard` / `test_blueprint_ambiguity_score` /
  `test_identity_union_attr` / `test_other_union_attr`（2 条）。
- **4 条在干净的相位 121 HEAD（`2043602b`）上全部通过**（3 passed / 1 skipped）⇒ 由工作区里
  **既有的未提交改动**引入，非本相位：
  `test_repo_router_v2_meta` / `test_runner_dispatch` / `test_blueprint_confirm_gate` /
  `test_mcp_package_alignment`。

结论：**Phase 121 对全量套件的净贡献为 0 回归、+86 新增用例。**

⚠️ 仓库级 `ruff check .` 另有约 276 个既有告警（集中在 `workflows/nodes/**` 等），
本相位六个文件里为 0，未做清理。

## 给后续相位的交接

- `SUBGRAPH_FRONTIER_LIMIT = 5000` 与 `CHUNK_EVIDENCE_MAX_PER_SYMBOL = 50`（121-06 引入）仍是保守猜测，
  本 plan 未校准 —— 留给 Phase 122 用真实 max-degree / max-fan-out 数据验证。
- 跨仓边 `(file_path, name)` 二次解析的真实命中率仍未测（生产 `CrossRepoApiCall` 样本不足），
  若 Phase 122 发现多数跨仓边解析不上，该谓词需要重新设计，而不是接受一张跨仓链路大半不可见的图。
- 运维若要调 `CODE_GRAPH_*` 预算默认值，先重跑上面的 perf 诊断，不要凭经验改。
