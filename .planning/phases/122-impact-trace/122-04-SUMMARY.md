---
phase: 122-impact-trace
plan: 04
subsystem: code-graph
tags: [shortest-path, subgraph-view, multi-solution, no-path-structure, pure-function, observability]

# Dependency graph
requires:
  - phase: 121-graph-base
    provides: "冻结 MultiDiGraph 内存契约、EdgeConfidence 四档、confidence_score() / derive_reason()、AST 观测契约"
  - plan: 122-01
    provides: "known_topology 13 节点冻结图（含专为多解测试而设的 P→Q→S / P→R→S 簇与孤立点 H）、test_trace.py 的 3 个 Wave 0 桩"
provides:
  - "trace_path：置信度视图 + 有向最短路 + 逐跳渲染 + 等长多解声明 + 显式无路径结构（纯函数，零 ORM）"
  - "DEFAULT_ALT_PATH_CAP=10：等长解计数的封顶值，islice 探一格的判据"
  - "输出契约：found / reason / source / target / min_confidence / path / hops / path_confidence / equal_length_path_count / equal_length_path_count_capped / alternatives_note 十一个顶层字段位"
  - "逐跳契约：from / to / from_file / from_line / call_line / kind / confidence / reason 八个字段，定义处行号与调用点行号分列两个字段"
affects: [122-05, 122-07, 122-08, 122-09, 122-10]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "运行期 import networkx 的内核模块：adapter seam 只约束契约层（model.py），算法内核以图库 API 为实现本体，理由写进模块 docstring 边界①防下次 review 误判"
    - "生成器只探一格：islice(gen, cap + 1) 拿「有没有超过 cap」这个布尔量，⛔ 不 list() 物化解集"

key-files:
  created:
    - server/services/code_graph/trace.py
  modified:
    - server/tests/services/code_graph/test_trace.py

key-decisions:
  - "alt_path_cap < 1 按 1 处理：0 会让 min(probed, 0) 恒为 0，输出「存在至少 0 条等长路径」而我们手上明明已有一条"
  - "封顶与未封顶两支的 alternatives_note 措辞刻意不同（「存在 N 条」vs「存在至少 N 条」），且封顶且计数为 1 时不落回空串"
  - "path_confidence 零跳取 1.0：source == target 的平凡路径没有任何边可以拉低它"
  - "_edge_score 在 impact.py 与 trace.py 各写一份，⛔ 不互相 import：两者是平级内核，数值表只有 model.py 一处"

requirements-completed: []  # IMPACT-05 的内核已落地，壳层（122-05/07/08）未齐，⛔ 不得据本 plan 勾选

# Metrics
duration: 12min
completed: 2026-08-09
---

# Phase 122 Plan 04: trace 内核（有向最短路 + 逐跳渲染 + 多解声明）Summary

**一个 384 行、零 ORM 零 Django 的纯函数内核：在按 `min_confidence` 过滤出的只读视图上跑有向最短路，把「定义在哪一行」与「在哪一行调用的」拆成两个字段，并让「不可达」和「还有别的等长解」这两件事都以显式结构说出来而不是靠 agent 猜**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-08-09T16:03:00Z
- **Completed:** 2026-08-09T16:15:00Z
- **Tasks:** 2
- **Files modified:** 2（1 新建 384 行 + 1 填实）

## Accomplishments

- **置信度视图落地，全程零复制**。`_confidence_view` 走 `nx.subgraph_view(graph, filter_edge=keep)`，`keep(u, v, k)` 三参签名（MultiDiGraph 上是三参，DiGraph 上才是两参，少一个形参会在第一次遍历时抛 `TypeError`）。视图建成后仍 frozen、`is_multigraph()` 仍为真，四档边契约不丢。AST 断言守着 ⛔ 无 `.copy()` / `copy=True`——实测视图 0.013ms vs 复制 330–690ms。
- **`from_line` 与 `call_line` 拆成两个字段**，这是本 plan 最容易被合成一个的地方。前者取 `graph.nodes[u]["start_line"]`（符号**定义**处），后者取边属性 `line_number`（**调用点**）。一个函数体几十行长，两者差出几十行是常态；合成一个 `line` 字段的话，agent 跳过去看到的是函数签名而不是那次调用，**且它无从察觉自己看错了**。用例直接钉死 `D→C` 那一跳的 `from_file == graph.nodes["D"]["file_path"]` 与 `call_line == 41`。
- **逐跳挑边挑的是置信度最高的那条**，不是 `next(iter(...))`。MultiDiGraph 上同一符号对可并存多档边，而 `shortest_path` 只给节点序列、不给边 key。随便取第一个会让渲染结果取决于建图时的插入顺序，更糟的是可能把「这里其实有一条 resolved 边」说成 `bare_name`。
- **D-20 的两个 `found=False` 分支 `reason` 不同**：`node_not_in_graph`（uid 打错 / 被 exclusion 挡掉 / 不在按需子图内）与 `no_path`（两端都在图里，但确实没有调用关系）。后者才是可据以决策的结论。两支都带 `source` / `target` / `min_confidence` 三个键，用例里直接断言返回值 `!= []` 且 `!= {}`——空数组会被 agent 读成「工具坏了」，这正是 D-20 要挡的形态。
- **D-18 的多解声明给了两份：一个数字 + 一句话**。`equal_length_path_count` 是机器读的，`alternatives_note` 是人读的。只给数字的话渲染层很容易整条漏掉，而漏掉就等于静默隐瞒多解。封顶时措辞从「存在 N 条」切成「存在**至少** N 条」——这是 agent 唯一能知道「我看到的计数不是全貌」的信号。
- **`all_shortest_paths` 只探一格**：`islice(gen, cap + 1)` 拿的是「有没有超过 cap 条」这一个布尔量。⛔ 不 `list()` 物化解集（高扇出图上等长解条数是各跳并行分支的乘积），两条 AST 断言分别守着「必须出现 islice」与「不许出现 `list(all_shortest_paths(...))`」。
- **`min_confidence` 有正反两面的反证**。只测「默认能找到路」的话，一个根本没建视图的实现照样能过。用例拿 `X`（唯一出边是 `bare_name` 档，`known_topology` docstring 明令不许给它加别的出边）做反例：默认门槛下 `X→A` 无解，门槛降到 0.3 立刻给出 `["X","B","A"]` 且 `path_confidence == 0.3`（弱边决定强度，取平均会是 0.65）。
- **方向纪律有独立断言**：`D→A` 有解、`A→D` 落 `no_path`。有向图上「反过来问没有答案」不是 bug，是语义。
- 新模块**自动**通过既有 AST 观测契约（`package_dir.glob("*.py")` 扫全包），未改动任何守护测试的判据。一次 `trace_path` 恰一条 DEBUG `sampling` 事件，只记 `found` / `hop_count` / `min_confidence` / `duration_ms`，⛔ 不记符号名与路径，🚨 逐跳循环内零 `logger.*`。

## Task Commits

1. **Task 1: 置信度视图与有向最短路（IMPACT-05 / D-18）** - `33ecd175` (feat)
2. **Task 2: 等长多解声明与封顶（D-18）** - `dfb60fce` (feat)

## Files Created/Modified

- `server/services/code_graph/trace.py`（新建，384 行）— 三段式中文 docstring（边界六条）；两个模块级常量 `DEFAULT_ALT_PATH_CAP: Final[int] = 10` 与事件名 `_EVENT_TRACE_COMPLETED: Final[str]`；公开 `trace_path`；私有 `_edge_score` / `_confidence_view` / `_node_descriptor` / `_render_hop` / `_log_trace_completed`；`__all__` 恰两项字母序。运行期 import：`__future__` / `itertools` / `time` / `collections.abc` / `typing` / `networkx` / `structlog` + 包根 barrel `services.code_graph`。
- `server/tests/services/code_graph/test_trace.py` — 摘掉 3 个 `@pytest.mark.skip` 并填实（本文件现已无 skip 桩），移除不再使用的 `import pytest`。

## Decisions Made

- **`alt_path_cap < 1` 按 1 处理**（plan 未规定）。`min(probed, 0)` 恒为 0，而 `probed > 0` 恒为真——cap=0 会输出「存在至少 0 条等长路径」这种自相矛盾的声明，而我们手上明明已经拿到一条路径了。`effective_cap = max(1, alt_path_cap)` 并把理由写进参数 docstring。
- **封顶分支的判定优先于「计数是否 >1」**。cap=1 时计数被压到 1，若按「计数 >1 才声明」的顺序写，这一支会落回空串——恰好在最需要声明「你看到的不是全部」的时候闭嘴。实现里 `if capped` 排在 `elif count > 1` 之前，用例用 `alt_path_cap=1` 钉死这个顺序。
- **`path_confidence` 零跳取 1.0**。`source == target` 的平凡路径没有任何边可以拉低它，`min(..., default=1.0)`。返回 0 会让壳层把一条平凡路径渲染成「完全不可信」。
- **模块运行期 import `networkx`**，与 `model.py` / `impact.py` 相反，理由写进 docstring 边界① 防下次 review 误判：adapter seam 那条纪律约束的是**契约层**（保证上层写输出结构时不必碰图库），而 `nx.subgraph_view` / `nx.shortest_path` 就是本模块的实现本体，藏进 `TYPE_CHECKING` 既做不到也没有意义。⛔ 零 Django / 零 ORM 这一条**不放松**，有 AST 断言守着。
- **`_edge_score` 与 `impact.py` 各写一份**（plan 明写，此处如实记账）：两者是平级内核，任何一方 import 另一方都会造出一条无谓的依赖边；两份都只是 `confidence_score()` 的一层薄封装，真正的数值表只有 `model.py` 一处，不存在漂移风险。理由写进函数 docstring。
- **`ruff format` 不作为本包门禁**（沿用 122-02 / 122-03 的裁决）。包内既有文件同样 `--check` 不过（ruff 配置 line-length 100，包内代码按 88 列换行），本文件对齐既有风格。plan `<verification>` 要求的 `ruff check` 全绿。

## Deviations from Plan

一处，Rule 2（补齐正确性所需的必要功能），无 Rule 1 / Rule 3 / Rule 4 触发：

**1. [Rule 2 - 缺失的必要功能] `alt_path_cap` 下界钳到 1**
- **Found during:** Task 2
- **Issue:** plan 的公式 `min(alts, alt_path_cap)` 与 `alts > alt_path_cap` 在 `alt_path_cap=0`（调用方完全可能传）时组合出「`capped is True` 且计数为 0」，渲染成「存在至少 0 条等长路径」——一句与「我们已经返回了一条路径」直接矛盾的声明。
- **Fix:** `effective_cap = max(1, alt_path_cap)`，后续计数与封顶判定一律用它；理由写进 `trace_path` 的参数 docstring 与就地注释。
- **Files modified:** `server/services/code_graph/trace.py`
- **Commit:** `dfb60fce`

## Verification Results

| 判据 | 结果 |
|---|---|
| `pytest tests/services/code_graph/test_trace.py -q`（**不带** `--reuse-db`，零 DB） | **3 passed** —— plan 明写的期望值，零 skip |
| `pytest tests/services/code_graph -q --reuse-db` | **111 passed / 11 skipped**（基线 108/14，+3 passed / −3 skipped，零新增失败） |
| `test_access.py -k "observability or upper_layer or barrel"` | 4 passed（新模块自动进 glob 扫描，契约未破） |
| 性能红线 AST 断言（无 `.copy()` / `copy=True`） | 退出码 0 |
| 零 ORM AST 断言（无 `django` / `codegraph` 运行期 import） | 退出码 0 |
| D-04 机械判据（logger 首个位置实参须字面量或模块级 `Final[str]`） | 退出码 0 —— 无 `_emit()` 包装 |
| `islice` 必须出现 / ⛔ 不许 `list(all_shortest_paths(...))` | 两条断言均退出码 0 |
| `ruff check services/code_graph/ tests/services/code_graph/` | All checks passed |
| `mypy services/code_graph/` | 本 plan 文件**零错误**（报出的 9 条全在包外既有文件：`codegraph/services/repo_router_scoring.py` ×4、`initiatives/services/feature_solution_render.py` ×2、`services/process_runtime/blueprint_execution.py` ×2、`workflows/schemas/technical_plan.py` ×1，均属并发会话编辑面或既有债） |
| `git diff --name-only HEAD~2 HEAD` | 恰两个文件，**不含** `services/code_graph/loader.py`（D-25 建边口径冻结面）与 `codegraph/services/repo_router_v2.py`（里程碑冻结面） |

## Issues Encountered

- 无新增。122-01 记入 `deferred-items.md` 的两条 `tests/mcp_tools/` ruff error 与本 plan 编辑面无交集，未新增任何 deferred 项。
- `mypy` 报出的 9 条既有错误构成与 122-03 时一致（同为并发会话正在改的那批文件），全部在 `services/code_graph/` 之外，未动。

## Known Stubs

无。本 plan 交付的两个文件里没有任何占位字段、没有恒空返回、没有 TODO。

⚠️ 一条**设计上的留白**（不是 stub）：`trace_path` 只做「图内定位 → 最短路」，它**不做符号解析**。D-19 的「uid 优先 + 重名候选列表」由 122-02 的 `resolve_symbol_in_graph` 承担，两者的接线（把用户传进来的名字先解析成 `symbol_id` 再喂给 `trace_path`，命中多个候选时**短路返回候选列表而不 trace**）归壳层 **122-05 / 122-07**。⛔ 内核不该也不能替壳层做这件事——候选列表要带 `signature`，那一列不在图节点属性里（`loader.py:354-356`），只能回 ORM 补取。

## Threat Flags

无新增威胁面。plan `<threat_model>` 的五条 `mitigate` / 一条 `accept` 落地情况：

| Threat ID | 落地方式 | 判据 |
|---|---|---|
| T-122-遍历 DoS | `itertools.islice(all_shortest_paths(...), cap + 1)` 只探一格；`DEFAULT_ALT_PATH_CAP=10` | 两条 AST 断言（必须有 `islice` / ⛔ 不许 `list(all_shortest_paths(...))`）退出码 0 |
| T-122-空图误导 | `node_not_in_graph` 与 `no_path` 两个不同 `reason`，两支都带 `source` / `target` / `min_confidence`；⛔ 不返回空数组 | `test_no_path_explicit_structure` 直接断言 `result != []` 且 `result != {}`，并分别断言两支的 `reason` |
| T-122-exclusion 回流 | `_node_descriptor` 的 `in_graph: False` 分支只回显调用方自己传进来的 id，其余字段一律空串/0；⛔ 不做模糊匹配、不提示「你是不是想找 X」 | 用例断言 `missing["source"]["file_path"] == ""` |
| T-122-日志放大 | 一次 `trace_path` 恰一条 DEBUG `sampling` 事件；逐跳循环内零 `logger.*` | AST 观测契约 4 passed + 就地复核退出码 0 |
| T-122-绕闸 | 运行期零 Django/ORM import，图只能由壳层经 `get_graph` 传入 | AST 断言退出码 0；运行期 import 面：`__future__` / `itertools` / `time` / `collections.abc` / `typing` / `networkx` / `structlog` / `services.code_graph` |
| T-122-SC | `accept` —— **零新增依赖**（networkx 3.6.1 已是 Phase 121 生产依赖） | `122-RESEARCH.md` §Package Legitimacy Audit 表为空 |

## 如实记账（供 122-10 汇总）

- **`DEFAULT_ALT_PATH_CAP = 10` 是未经真实数据校准的初值**，⛔ 不得表述成经验结论。它来自定性推理（「够区分『两条』与『很多条』，又不会让计数本身变成一次全解集遍历」），没有对应任何实测的等长解条数分布——本仓从未统计过真实代码里同一对符号之间有多少条等长调用路径。这一点已写进常量注释。
- **「返回第一条」的确定性有边界**：它是 `nx.shortest_path` 在同一张图、同一对端点上的稳定输出，但⛔ **不承诺**是「最重要」的那条。排序哪条更重要需要语义信息（业务主链路 / 热路径），本相位不做，已写进 `trace_path` docstring。
- **本 plan 全程未碰并发会话的编辑面**：两个 commit 恰触及两个文件，`git diff --name-only HEAD~2 HEAD` 中无 `mcp/`、无 `server/repositories/`、无 `server/durable/`、无 `server/codegraph/`、无 `web/`。

## User Setup Required

None - 零新增依赖、零迁移、零模型变更、无外部服务配置。

## Next Phase Readiness

- **122-05 / 122-07**（壳层）可直接 `from services.code_graph.trace import trace_path` 消费，十一个顶层字段位已定型。壳层要补的三件事：① 先走 `resolve_symbol_in_graph` 把名字解析成 `symbol_id`，命中多个候选时**短路返回候选列表而不 trace**（D-19）；② 候选的 `signature` 回 ORM 补取并截断 200 字符（D-17）；③ 把 `GraphMeta` 的四个降级标记与 `resolution_rate` 数值并进同一份输出（D-23）。
- **122-08 / 122-09** 双面壳共用同一个 `trace_path`，⛔ 逻辑不许在壳里分叉（D-21）。
- **IMPACT-05 未标记完成**：本 plan 只交付最短路内核，工具面还差壳层（122-05）、双面接线（122-07/08/09）。⛔ 不得据本 plan 勾选 REQUIREMENTS。
- **无 blocker。**

## Self-Check: PASSED

- 交付文件均存在于磁盘：`server/services/code_graph/trace.py`（384 行）、`server/tests/services/code_graph/test_trace.py`（143 行）。
- 两个 task commit（`33ecd175` / `dfb60fce`）均可在 `git log` 中查到。

---
*Phase: 122-impact-trace*
*Completed: 2026-08-09*
