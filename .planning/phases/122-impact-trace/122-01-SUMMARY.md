---
phase: 122-impact-trace
plan: 01
subsystem: testing
tags: [pytest, networkx, multidigraph, fixtures, test-scaffolding, code-graph]

# Dependency graph
requires:
  - phase: 121-graph-base
    provides: "冻结 MultiDiGraph 内存契约（节点恒 5 属性 / 边恒 3 属性 + cross_repo 档第 4 个 match_confidence）、EdgeConfidence 四档、17 名 barrel、tests/services/code_graph 的 5 个 DB fixture 与 autouse 重置钩子"
provides:
  - "known_topology：13 节点的合成冻结 MultiDiGraph，深度分组与最短路可逐点核对"
  - "hub_topology(fan_in, *, confidence)：可调扇入的 hub 图工厂，服务截断上限与风险分级的边界取值"
  - "cross_repo_call_factory：ApiWrapper → ApiCallSite → Endpoint → CrossRepoApiCall 四模型造数链，支持真跨仓行"
  - "9 个测试文件里 27 个 pytest 节点（1 真 + 26 桩），覆盖 122-RESEARCH §Validation Architecture 表点名的全部落点"
affects: [122-02, 122-03, 122-04, 122-05, 122-06, 122-07, 122-08, 122-09, 122-10]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "合成冻结图 fixture：全仓第一个 networkx fixture，nx.freeze 使「内核不改图」可由构造保证"
    - "Wave 0 桩：docstring 逐字抄 RESEARCH 表的 Behavior 列 + （Req/决策）归属标注 + pytest.mark.skip(reason=\"Wave 0 桩：由 122-NN 落地\")"

key-files:
  created:
    - server/tests/services/code_graph/test_impact.py
    - server/tests/services/code_graph/test_trace.py
    - server/tests/services/code_graph/test_symbol_resolve.py
    - server/tests/services/code_graph/test_cross_repo_hop.py
    - server/tests/services/code_graph/test_staleness.py
    - server/tests/services/code_graph/test_impact_shell.py
    - server/tests/mcp_tools/test_impact_trace_tools.py
    - server/tests/agents/tools/test_graph_tools.py
  modified:
    - server/tests/services/code_graph/conftest.py

key-decisions:
  - "known_topology 在 RESEARCH §5 的 8 节点基础上扩到 13：加与 A 不连通的等长多解簇 P/Q/R/S，加只经裸名边可达的观察点 X"
  - "cross_repo_call_factory 是 test_loader.py::_make_cross_repo_call 之外有意的第二份实现，不搬走既有 helper 以免给 Phase 121 的绿测引入风险"
  - "test_symbol_resolve.py 不设文件级 pytestmark：uid 优先是零 DB 协议断言，重名候选要取 Symbol.signature 才需要库"

patterns-established:
  - "合成冻结图 fixture：fixture 自身 nx.freeze，让「内核不修改入参图」成为构造性保证而非口头约定"
  - "反滥用注释：X 的唯一出边与簇二的存在理由写进 docstring，防后人顺手加边把用例弄成恒真"

requirements-completed: []  # 本 plan 是 10 之 1，只落测试地基，IMPACT-01..06 均未交付实现

# Metrics
duration: 30min
completed: 2026-08-09
---

# Phase 122 Plan 01: 验收地基（合成冻结图 fixture + 测试骨架）Summary

**13 节点的合成冻结 MultiDiGraph fixture（含等长多解簇与只经裸名边可达的观察点）+ 可调扇入 hub 工厂 + 跨仓四模型造数链，外加 9 个测试文件里 27 个可被 --collect-only 收集到的 pytest 节点，让后续 9 个 plan 的每一条 `<verify>` 都命中一个真实存在的测试节点**

## Performance

- **Duration:** ~30 min
- **Started:** 2026-08-09T15:12:00Z
- **Completed:** 2026-08-09T15:42:00Z
- **Tasks:** 3
- **Files modified:** 9（8 新建 + 1 追加）

## Accomplishments

- `known_topology` 落地为**冻结**的 `MultiDiGraph`，节点/边属性个数与 Phase 121 的内存契约逐字一致（节点恒 5、边恒 3、`cross_repo` 档唯一例外多一个 `match_confidence`），并有一条**不 skip** 的真用例 `test_known_topology_fixture_is_frozen` 守着这份契约。
- 在 RESEARCH §Code Examples §5 的 8 节点拓扑之上补了两处刻意的扩展，各自解决一条原拓扑验证不了的断言：
  - **等长多解簇 `P → Q → S` / `P → R → S`**（与 A 完全不连通）——原图里 `D → A` 只有一条最短路，D-18 的「存在 N 条等长路径」声明验证不了。
  - **只经裸名边可达的观察点 `X`**（唯一出边 `X --bare_name--> B`）——D-08 双闸需要一个两道闸没同时开时必须缺席的节点；`C` 担不了，它还有 `C --resolved--> A`，用它会让 `test_bare_name_requires_both_gates` 恒真。两处的理由都写进了 docstring，防后人顺手加边。
- 27 个测试节点全部落位：`tests/services/code_graph` 的三个零 DB 文件 `--collect-only` 收集到 **15** 个（`test_impact.py` 10 = 1 真 + 9 桩、`test_trace.py` 3、`test_symbol_resolve.py` 2），五个壳层文件合计 **17 skipped**。
- `tests/services/code_graph` 从 Phase 121 基线 **96 passed** 变为 **97 passed / 23 skipped**，passed 计数恰好 +1（就是那条 fixture 自检），零新增失败。

## Task Commits

1. **Task 1: conftest 追加合成冻结图 fixture 与跨仓造数工厂** - `a263b822` (test)
2. **Task 2: 内核测试文件骨架（test_impact / test_trace / test_symbol_resolve）** - `7e7c5493` (test)
3. **Task 3: 壳层测试文件骨架（cross_repo / staleness / impact_shell / mcp / agents）** - `52400bf3` (test)

## Files Created/Modified

- `server/tests/services/code_graph/conftest.py` — 追加三个 fixture：`known_topology`（13 节点冻结图）、`hub_topology`（闭包工厂，`1 + 2 * fan_in` 节点）、`cross_repo_call_factory`（DB 闭包工厂，四模型链）；顶部加 `import networkx as nx`
- `server/tests/services/code_graph/test_impact.py` — 1 真用例 + 9 桩（IMPACT-01/02/04 的 8 个归 122-03；`test_graph_cross_repo_edges_are_intra_repo` 归 122-06）
- `server/tests/services/code_graph/test_trace.py` — 3 桩（IMPACT-05，归 122-04）
- `server/tests/services/code_graph/test_symbol_resolve.py` — 2 桩（`test_uid_takes_precedence` 零 DB 归 122-02；`test_ambiguous_returns_candidates` 挂 `django_db` 归 122-05）
- `server/tests/services/code_graph/test_cross_repo_hop.py` — 4 桩（IMPACT-03 四分支，归 122-06）
- `server/tests/services/code_graph/test_staleness.py` — 2 桩（D-22 两分支，归 122-05）
- `server/tests/services/code_graph/test_impact_shell.py` — 3 桩（D-24 / D-03 归 122-05，D-19 短路归 122-07）
- `server/tests/mcp_tools/test_impact_trace_tools.py` — `IMPACT_URL` / `TRACE_URL` 两个模块级常量 + 6 桩（5 个归 122-08，`test_two_surfaces_same_payload` 归 122-10）
- `server/tests/agents/tools/test_graph_tools.py` — 2 桩（归 122-09）

## Decisions Made

- **`known_topology` 扩到 13 节点**（RESEARCH §5 的 8 个 + P/Q/R/S + X）。理由见上方 Accomplishments：两处扩展各自对应一条原拓扑无法验证的断言，且都与 A 的反向影响面不连通，不扰动既有的深度分组点检值。
- **`cross_repo_call_factory` 是有意的第二份实现**，`test_loader.py::_make_cross_repo_call` 原地不动。搬走它会改到一批已绿的 Phase 121 用例，跨模块 import 别的测试模块里的私有 helper 也不是本仓做法。代价是几十行重复，收益是 121 的绿测不因 122 的需要而承担风险——理由已写进 fixture docstring。
- **`test_symbol_resolve.py` 不设文件级 `pytestmark`**：两条用例的数据库口径不同（uid 优先是零 DB 的纯协议断言；重名候选要取 `Symbol.signature`，那是 TextField、不在图节点属性里，只能回 ORM 补取），文件级标记会把零 DB 的那条也拖进建库路径。
- **`hub_topology` 每个直接前驱各带一个二级前驱**：只有 d1 的图验证不了「深度升序」这个排序主键，而它正是 D-16 截断排序的第一顺位。
- **不碰 `tests/mcp_tools/test_schema_snapshot.py`**（plan 明令）：两条字面量条目必须与 `mcp_tools/urls.py` + `TOOL_SCHEMA_SNAPSHOT` 同批落地（归 122-08），否则那条 urls ↔ snapshot 的双向断言会在两个 wave 之间一直红着。

## Deviations from Plan

None - plan executed exactly as written。三个 task 的 acceptance criteria 全部逐条实测通过，未触发任何 Rule 1–4 的自动修复。

## Issues Encountered

- `uv run ruff check tests/services/code_graph tests/mcp_tools tests/agents`（plan `<verification>` 的第二条）报 **2 个 error**，但两条都在**本 plan 从未触碰**的既有文件里：`tests/mcp_tools/test_delivery_knowledge_tools.py:9`（F401 未使用的 `sync_to_async`）与 `tests/mcp_tools/test_find_related_chunks.py:1`（I001 import 未排序）。两个文件的最后一次改动是 `062f686f`（Phase 76），`git status` 显示未被本会话或并发会话修改。按 scope boundary 未修，已记入 `deferred-items.md`。本 plan 新增/修改的 9 个文件 `ruff check` 与 `ruff format --check` 全部通过。

## Known Stubs

本 plan 的交付物**本身就是 26 个 skip 桩**——这是 Wave 0 的既定形态，不是缺口。每个桩挂 `@pytest.mark.skip(reason="Wave 0 桩：由 122-NN 落地")`，`NN` 逐个指向 `122-RESEARCH.md` §Validation Architecture 表里该行的归属 plan：

| 文件 | 桩数 | 归属 |
|---|---|---|
| `test_impact.py` | 9 | 122-03（8）/ 122-06（1） |
| `test_trace.py` | 3 | 122-04 |
| `test_symbol_resolve.py` | 2 | 122-02（1）/ 122-05（1） |
| `test_cross_repo_hop.py` | 4 | 122-06 |
| `test_staleness.py` | 2 | 122-05 |
| `test_impact_shell.py` | 3 | 122-05（2）/ 122-07（1） |
| `tests/mcp_tools/test_impact_trace_tools.py` | 6 | 122-08（5）/ 122-10（1） |
| `tests/agents/tools/test_graph_tools.py` | 2 | 122-09 |

桩体统一是 docstring + `pytest.fail("Wave 0 桩")`：万一哪个 plan 把 `@pytest.mark.skip` 摘了却忘了写实现，用例会立刻红，而不是静默通过。

## Threat Flags

无。本 plan 只新增测试文件与 fixture，零生产代码、零网络入口、零鉴权路径；`<threat_model>` 里的两条 `mitigate`（T-122-exclusion 回流 / T-122-穿仓）都按计划以桩与工厂形式占位：`test_excluded_files_invisible` 已在 `tests/mcp_tools/test_impact_trace_tools.py` 落位待 122-08 填实，`cross_repo_call_factory` 的 `endpoint_repository` 参数已支持指向另一个仓，让 122-06 能造出真跨仓行来验证 `REDACTED_REPOSITORY` 折叠。

## 如实记账（供 122-10 汇总）

- **IMPACT-03 的跨仓路径未经任何真实数据验证**（D-26）。生产库 `CrossRepoApiCall` / `ApiCallSite` / `ApiWrapper` **均为 0 行**，上游产出器依赖 volar LSP 而 server 镜像无 Node（归 LSP-01 / Phase 127）。本 plan 交付的 `cross_repo_call_factory` 只是让四条分支能被**合成数据**覆盖；⛔ 合成数据通过不得表述成「跨仓能力已验证」。该声明已写进 `test_cross_repo_hop.py` 的模块 docstring。
- **`mcp` submodule 全程未碰**（D-27）。本 plan 的三个 commit 只触及 9 个 `server/tests/**` 文件，`git diff --name-only HEAD~3 HEAD` 中无任何 `mcp/` 路径。

## User Setup Required

None - 零新增依赖（`122-RESEARCH.md` §Package Legitimacy Audit 审计表为空；networkx 3.6.1 已是 Phase 121 的生产依赖），无外部服务配置。

## Next Phase Readiness

- 后续 9 个 plan 的 `<verify>` 命令现在**全部**指向一个真实存在、可被 `--collect-only` 收集到的 pytest 节点。Wave 0 的地基已成立。
- 122-03 可直接消费 `known_topology` 的 7 条点检断言（RESEARCH §5 末尾列出）与 `hub_topology` 的边界取值；122-06 可直接消费 `cross_repo_call_factory`。
- 唯一遗留的测试面改动是 `tests/mcp_tools/test_schema_snapshot.py` 的两条字面量条目，已明确归 122-08 T2，与 `urls.py` + `TOOL_SCHEMA_SNAPSHOT` 同批。
- **无 blocker。**

## Self-Check: PASSED

9 个交付文件全部存在于磁盘，3 个 task commit（`a263b822` / `7e7c5493` / `52400bf3`）
全部可在 `git log` 中查到。

---
*Phase: 122-impact-trace*
*Completed: 2026-08-09*
