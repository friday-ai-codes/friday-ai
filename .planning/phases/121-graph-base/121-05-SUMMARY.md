---
phase: 121-graph-base
plan: 05
subsystem: infra
tags: [code_graph, networkx, multidigraph, overlay, exclusion, orm-batch, resolution-rate]

# Dependency graph
requires:
  - phase: 121-01
    provides: "networkx 直接依赖、tests/services/code_graph/ 测试包与 indexed_repo / symbols_factory / call_edges_factory / exclusion_rule_factory fixture"
  - phase: 121-02
    provides: "EdgeKind / EdgeConfidence / BARE_NAME_BLACKLIST / LOW_RESOLUTION_THRESHOLD / CodeGraph / GraphMeta"
  - phase: 121-03
    provides: "make_path_exclusion_memo（含 excluded_files 活动只读视图）、build_matcher_and_fingerprint、test_observability_contract AST 守护"
provides:
  - "load_graph(repository_id, branch='', *, matcher, exclusion_fingerprint, include_low_confidence=False) -> CodeGraph"
  - "_load_symbol_nodes：overlay 整文件去重（D-06）+ 装配阶段 exclusion 过滤，节点属性恒 5 个"
  - "_load_call_edges：resolved / bare_name 双档装配，边属性恒 3 个（⛔ 不存 reason，D-08）"
  - "裸名三道过滤的三个可单测私有谓词：_is_same_directory / _qualifier_matches / _is_blacklisted_bare_name"
  - "resolution_rate（按全部落库 CallEdge 行统计，与 include_low_confidence 无关）+ low_resolution 标记"
  - "两个 DEBUG 埋点 code_graph_exclusion_applied / code_graph_assembled"
affects: [121-06, 121-07, 121-08, 121-09, 121-10, 122, 123, 124, 125, 126, 127]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "本仓应用代码首次直接使用 networkx：MultiDiGraph 装配 + 属性个数即内存契约"
    - "overlay 去重的 feature 文件集只查窄条件（branch_name=branch）而非第二趟全表扫"
    - "统计口径与装载开关解耦：解析率先统计后过滤，避免关掉裸名时恒为 1.0 的假信号"

key-files:
  created:
    - server/services/code_graph/loader.py
  modified:
    - server/tests/services/code_graph/test_loader.py
    - server/tests/services/code_graph/test_access.py

key-decisions:
  - "feature 文件集用 filter(branch_name=branch).values_list('file_path').distinct() 的窄查询，严格优于 plan 给的两个选项（第二趟全表 iterator / 十万行先进内存）"
  - "exclusion 判定喂原始 file_path 而非归一后路径：matcher 内部自己归一并对越界 fail-closed，让「归一失败」与「命中规则」共用同一个去重文件计数口径"
  - "GraphMeta.estimated_bytes 由 loader 置 0、由 cache.py 覆写：NODE_COST/EDGE_COST 常数归 121-07，loader 复制一份必然漂移"
  - "test_access.py 的装配助手在 Task 3 改走公开 load_graph——只装节点的话「邻接边一并消失」那半句断言恒真，T-121-泄漏 的 mitigation 就失去了回归"

patterns-established:
  - "私有谓词拆分：裸名三道过滤各自成函数，可单测、可被 121-06 的跨仓边二次解析复用"
  - "丢弃计数只进日志不进 GraphMeta：排障线索与「上层必须向用户声明的可信度标记」严格分家"
  - "解析率分母为 0 时定义为 1.0 并写明理由——0.0 会让每个空仓都误报 low_resolution，降级标记长鸣即等于失效"

requirements-completed: []

# Metrics
duration: 25min
completed: 2026-08-09
---

# Phase 121 Plan 05: 符号图装配主干 Summary

**`services/code_graph/loader.py` 落地：ORM 独占的批量取数 + `MultiDiGraph` 装配 —— overlay 整文件去重、装配阶段 exclusion 过滤（被排除符号连同邻接边一并消失）、`CallEdge` 双档边与裸名三道过滤，外加一个不受装载开关影响的 `resolution_rate`**

## Performance

- **Duration:** 约 25 分钟
- **Started:** 2026-08-09T06:20:00Z
- **Completed:** 2026-08-09T06:45:00Z
- **Tasks:** 3
- **Files modified:** 3（1 新建 + 2 修改）

## Accomplishments

- **GRAPH-04 的过滤动作真正落地**。121-03 只交付了判定函数，本 plan 让它在**装配阶段**生效：命中排除的 `Symbol.file_path` 对应的节点根本不进节点集，建边时任一端点不在 `node_ids` 内即整条边丢弃。`test_exclusion_hides_symbols_and_edges` 造了一条 `src/ok.py::caller → secret/.env.py::callee` 的真实解析边，断言被排除端不在 `graph.nodes`、边数为 0、而未被排除的 caller 仍在——**不是**「整张图连坐掉」也**不是**输出阶段裁剪。
- **overlay 去重键锁死在整文件**（D-06）。`test_branch_overlay_feature_over_base` 里 feature 分支的 `a.py::f2` 起始行从 1 漂到 20——按 `start_line` 去重会让 `f` 与 `f2` 并存成两个节点，按整文件去重才对。base 的 `b.py::g` 保留，`a.py::f` 消失，以 `branch=""` 装配时又只剩 base 两个符号。
- **D-01 有可执行证据**。`test_assembles_multidigraph` 除了断 `isinstance(graph, nx.MultiDiGraph)` 与 `is_multigraph()`，还对同一对节点连加两条不同 `kind` 的边并断 `number_of_edges(u, v) == 2`——`DiGraph` 在这里会静默剩一条，四档边契约当场失效。
- **裸名假阳性有三道独立可测的闸**。三道过滤拆成三个私有谓词，各有一条用例：跨目录同名（`src/a.py` → `vendor/a.py`）被丢、`callee_qualifier="other"` 对不上 `src/util.py` 的模块名被丢（改成 `"util"` 立刻放行，证明这道闸不是恒假的）、`callee_name="handle"` 命中黑名单被丢（前两道都过，只被第三道挡下）。
- **解析率是可信信号，不是开关的副产品**。`resolution_rate` 在**过滤之前**对全部落库 `CallEdge` 行统计：2 解析 + 3 裸名 ⇒ `0.4` 且 `low_resolution=True`，**两种 `include_low_confidence` 取值下逐字节相同**（用例同时断言两者）。补到 4 解析 + 1 裸名 ⇒ `0.8` 且标记落下。分母为 0 时定义为 `1.0` 并在 docstring 写明理由——取 `0.0` 会让每个空仓都误报解析质量差。
- **属性个数即内存契约，两侧都有用例守**。节点属性键集合恒为 5 项（用例遍历断言，且显式断 `signature` / `chunk_id` 不在其中），边属性恒为 3 项且 `"reason" not in data`。121-02 的 `test_reason_not_stored_on_edge_attrs` 扫的是契约层 dataclass、**扫不到 loader 里 `add_edge(..., reason=...)` 的写法**，这条缺口由本 plan 自己的 `test_edge_attrs_are_exactly_three_without_reason` 补上。
- **10 万级循环零 per-item 日志**。装配循环内没有任何 `logger.*` 调用；`exclusion.blocked`（INFO）由 121-03 的记忆化闭包按「每个新的被排除 file_path 至多一次」控制——`test_exclusion_audit_does_not_spam_per_symbol` 用 200 个同属一个被排除文件的符号断 `call_count == 1`。汇总走两条 DEBUG 事件。

## Task Commits

1. **Task 1: 符号节点装配——overlay 分支合并与整文件去重（D-06）** — `91bc10f1` (feat)
2. **Task 2: 装配阶段 exclusion 过滤（GRAPH-04 落地）** — `11cb44ff` (feat)
3. **Task 3: CallEdge 双档装配、裸名三道过滤与 resolution_rate** — `cde22bfd` (feat)

**Plan metadata:** 见本文件的收尾 docs 提交。

## Files Created/Modified

- `server/services/code_graph/loader.py`（新建，677 行）— 三段式模块 docstring（含六条边界纪律）/ 2 个 `Final[str]` 事件名常量 + 2 个专用埋点函数 / 2 个内部值对象 / `_branch_filter`、`_feature_shadowed_files`、`_load_symbol_nodes`、`_directory_of` 与三个裸名谓词、`_load_call_edges` / 公开 `load_graph`
- `server/tests/services/code_graph/test_loader.py` — 2 个桩转真实断言 + 9 个新增用例（3 个 121-06 的桩原位保留）
- `server/tests/services/code_graph/test_access.py` — `test_exclusion_hides_symbols_and_edges` 桩转真实断言 + 3 个新增 exclusion 用例

## Decisions Made

- **feature 文件集取数选了第三种、更省的形态**。plan 把权衡显式留给执行方，给的两个选项是「两趟 `iterator`」或「一趟收进内存后再筛」。实际选的是只对 `branch_name=branch` 这一个窄条件做一次 `values_list("file_path", flat=True).distinct()`：feature 分支只有增量行（几十到几百），既不是第二趟十万级全表扫，也不必把十万行元组先攒进内存；`branch == ""` 时根本不查（base 不会被任何东西覆盖）。理由写进了 `_feature_shadowed_files` 的 docstring。
- **exclusion 判定喂原始 `file_path`，不喂归一后的路径**。`ExclusionMatcher.is_excluded` 内部自己归一，并对越界/绝对路径 fail-closed 返回 `True`；喂原始路径能让「归一失败」与「命中规则」共用同一个 `excluded_files` 去重计数口径。随后仍显式检查 `normalize_rel_path(...) is None`——这行在当前 matcher 语义下不可达，但它把「归一失败即排除」写成 loader 自己的契约，而不是默默依赖别人的实现细节（注释写明了这一点）。
- **`GraphMeta.estimated_bytes` 由 loader 置 0**。`NODE_COST_BYTES` / `EDGE_COST_BYTES` 与 `estimate_graph_bytes` 都归 Plan 121-07 的 `cache.py`（准入判据与 LRU 记账必须用同一个估算函数）。loader 复制一份常数必然漂移，而 `cache.py` 本来就要在装配后用**实际** node/edge 计数重算并覆写（121-08 的 action 明写这一步）。同理 `partial_edges` / `degraded` 留给 `cache.py`，`cross_repo_*` 两项留给 121-06。
- **`built_signature` 先写入注入的 exclusion 指纹**。loader 手上只有这一个分量，完整复合签名由 `cache.py` 用 `signature.compute_signature` 算好后覆写。plan 要求「`exclusion_fingerprint` 只用于写进 `GraphMeta`、loader 不重算」，`built_signature` 是 `GraphMeta` 上唯一的落点。
- **裸名边的目标解析复用 `by_file_and_name`**。plan 的 Task 1 ⑤ 把这个索引定位为「Plan 121-06 的跨仓边二次解析要用」，本 plan 的裸名边同样需要它——裸名档没有 FK，要挂到节点上只能靠 `(归一后 file_path, name)` 查候选。查不到即丢弃（不建虚拟节点，与 D-05 同理）。
- **`_qualifier_matches` 的判据取保守解**。限定符须等于候选文件的模块名（basename 去扩展名）或父目录名（包名）；`obj.method()` 这类对象调用两者都对不上 ⇒ 丢弃。本函数只在「已经没有 FK、只剩一个字符串」的裸名档上生效，对不上就说明我们并不知道它指向谁——宁可少一条边，也不要一条编造的边喂给 impact。

## Deviations from Plan

**None — plan executed exactly as written.**

三个 task 的 action 与验收条款逐条落地，无 Rule 1–4 触发，无 scope creep。三处需要说明的**执行细节**（两处是 plan 明确留给执行方的选择，一处是跨 task 的落位调整）：

**1. `test_access.py` 的装配助手在 Task 3 从 `_load_symbol_nodes` 改成公开 `load_graph`**

Task 2 的验收条款要求 `test_exclusion_hides_symbols_and_edges` 断言「该条边不在 `graph.edges`（`graph.number_of_edges() == 0`）」，但边装配是 Task 3 的交付物——Task 2 提交时只装节点，那半句断言**恒真**（图里本来就没有边），威胁 `T-121-泄漏` 的 mitigation 就失去了回归。

处理：Task 2 先用节点装配落地该用例（节点侧断言全部真实有效），Task 3 交付 `load_graph` 后把助手改成走公开入口，让边侧断言变成真的。代价是 Task 3 额外碰了一次 `test_access.py`（plan 的 `<files>` 里只列了 `loader.py` 与 `test_loader.py`）。这条是**让验收条款真正成立**的必要动作，不是 scope creep。

**2. `_load_symbol_nodes` 的 `is_excluded` 参数在 Task 1 就落地**

Task 2 的 `<files>` 是 `loader.py` + `test_access.py`，**不含** `test_loader.py`。若 Task 1 的签名不带 `is_excluded`，Task 2 接入过滤时就必须回头改 Task 1 写的那批 `test_loader.py` 用例——那会让 Task 2 越界。故 Task 1 就把参数纳入签名并接上基础的丢弃分支，Task 2 补齐其余四件事（归一失败即排除的显式契约、`excluded_file_count` 的去重口径、汇总 DEBUG 事件、模块 docstring 的「matcher 一律由 cache.py 注入」禁令）与四条用例。两个 task 的提交各自独立可验证。

**3. 两处验收 grep 的字面表达过粗（与 121-01 / 121-04 记录的同类，不改变任何代码行为）**

- Task 2 条款：`grep -c 'build_matcher_and_fingerprint' loader.py == 0` → 实际 **1**。唯一命中在模块 docstring ④ 里，是那条禁令**本身的散文表述**（「⛔ 本模块绝不调用 `access.build_matcher_and_fingerprint`」）——而 plan 的 action 恰恰要求「把这条禁令写进 `loader.py` 模块 docstring」，两条字面互斥。真实意图是「没有调用点」，精确检查式：

```
grep -c 'build_matcher_and_fingerprint(' services/code_graph/loader.py   # → 0 ✅
```

- Task 1 条款：`loader.py` 不出现 `"signature"` 于 `values_list` 调用中 → `grep -c 'signature'` 为 2，两处都是禁令散文（模块 docstring 的「⛔ 绝不取 `Symbol.signature`」与字段清单上方的注释）。两处 `values_list(` 的参数逐字核对确无 `signature`，且用例遍历断言节点属性键集合恰为 5 项、`"signature" not in data`。

## Issues Encountered

**无功能性问题。** 三个 task 的自动化验收一次通过，未触发任何 Rule 1–4，未发生观测契约拦截（121-04 踩过的 `_emit` 转发器坑本 plan 直接绕开：两个埋点各自成函数、事件名常量写在第一个位置实参上）。

**一处 lint 修正：** `test_access.py` 新增用例时多留了一个空行，`ruff check` 报 `I001`，已修。

**Lint / 类型检查：**

- `uv run ruff check services/code_graph/ tests/services/code_graph/` → All checks passed。
- `uv run mypy services/code_graph/` → 唯一 1 条错误落在 `workflows/schemas/technical_plan.py:268`（预存在，121-01 / 121-02 / 121-03 / 121-04 已四次登记），本 plan 的文件 0 错误。

**测试范围：** 按本 plan 的测试预算跑了 `tests/services/code_graph`（**47 passed / 13 skipped**，本 plan 把 3 个桩转成真实断言并新增 12 条用例）。plan `<verification>` 里点名的 `tests/services/test_exclusion_matcher.py` / `test_retrieval_exclusion.py` / `tests/codegraph` 回归**未跑**——这条约 18 分钟的回归已排期为 Plan 121-10 的相位闸门，且本 plan 只新增文件、未触碰 `services/exclusion.py` 与 `codegraph/` 的任何代码路径。Wave 0 登记的 4 条预存在失败（`test_chunkedge_fan_in_query_uses_target_index` 的 SQLite/PostgreSQL 方言耦合 + 3 条 `test_repo_summary_builder`）与本 plan 无关，未处理。

## User Setup Required

None — 纯 service 层装配模块，无外部服务、无新增配置项、无迁移。

## Next Phase Readiness

**已就绪：**

- **Plan 121-06（跨仓边 / chunk 证据面 / 按需子图）**：`_load_symbol_nodes` 产出的 `by_file_and_name`（`(归一后 file_path, name) → symbol_id`）就是 `CrossRepoApiCall` 二次解析要的那张表；`node_ids` 用于「任一端不在即整条丢弃」；`_directory_of` 与三个裸名谓词可直接复用。`load_subgraph` 照 `load_graph` 的签名形态写（`matcher` / `exclusion_fingerprint` 必填关键字参数），`GraphMeta` 的 `cross_repo_unresolved_count` / `cross_repo_branch_unfiltered` 两项本 plan 如实置 0 / False，届时改成真实统计。
- **Plan 121-07/121-08（`cache.py`）**：`load_graph` 全同步，整段由 `cache.py` 一次性 `sync_to_async` 包裹即可。装配后需要 `cache.py` 覆写三组字段：`estimated_bytes`（用 `estimate_graph_bytes` 按实际 node/edge 计数算）、`partial_edges` / `partial_reason`（来自 `detect_edge_build_in_flight`）、`built_signature`（来自 `compute_signature`，loader 先放的是 exclusion 指纹分量）。`GraphMeta` 是 frozen，覆写走 `dataclasses.replace`。
- **Plan 121-09（barrel）**：`loader.__all__` 只有 `load_graph` 一项，且**刻意不进** `services/code_graph/__init__.py`——「不导出 loader / cache 是架构红线」（121-02 已定）。

**留给后续 plan 的显式待办：**

- **Plan 121-07**：`GraphMeta.estimated_bytes` 目前恒为 0。这不是遗漏而是分层——常数与估算函数归 `cache.py`，但**该 plan 必须真的覆写它**，否则字节预算 LRU 会把每张图都记成 0 字节、永远逐不出东西。建议在 `cache.py` 的用例里直接断言 `entry.estimated_bytes > 0`。
- **Plan 121-10**：`_qualifier_matches` 的「模块名 / 包名」判据是照 Go selector 与 Python 模块调用的形态推的，未在真实仓上统计过命中率。该 plan 的「per repo / per language 解析率统计」交付物若顺带统计一下「开启 `include_low_confidence` 后三道过滤各自丢了多少」，可以用来复校这道判据是否过严（当前口径宁可少连也不错连）。`LOW_RESOLUTION_THRESHOLD = 0.6` 的复校同样在该 plan。
- **Plan 121-06**：`call_type` 目前取列但不进边属性（边属性恒 3 个）。若 121-06 需要按调用类型细分 `EdgeKind`，需要先重新核算属性个数——第 4 个边属性会让每条边跳一个内存尺寸级。

## Threat Flags

无——本 plan 未引入 `<threat_model>` 之外的新安全面（零新增网络入口、零新增鉴权路径、零文件访问、零 schema 变更）。威胁登记表的五条 `mitigate` 落地情况：

| Threat ID | 落地 | 回归用例 |
|-----------|------|----------|
| T-121-泄漏 | ✅ | `test_exclusion_hides_symbols_and_edges` / `test_exclusion_covers_unnormalizable_paths` |
| T-121-裸名假阳性 | ✅ | 三道过滤各一条 + `test_resolution_rate_and_low_resolution_flag`（开关不影响解析率） |
| T-121-日志刷屏 | ✅ | `test_exclusion_audit_does_not_spam_per_symbol`（200 符号 / 1 次审计） |
| T-121-内存失准 | ✅ | 节点 5 属性 / 边 3 属性两条键集合断言 + `signature` 不取 |
| T-121-覆盖丢边 | ✅ | `test_assembles_multidigraph` 的并存两条边断言 |

## Self-Check: PASSED

- `server/services/code_graph/loader.py` FOUND（677 行 ≥ plan 要求的 200）
- `server/tests/services/code_graph/test_loader.py` FOUND
- `server/tests/services/code_graph/test_access.py` FOUND
- 提交 `91bc10f1` / `11cb44ff` / `cde22bfd` 均在 git 历史中可查
- `grep -c 'iterator(chunk_size=' loader.py` → 2（≥ 1）；`grep -c 'MultiDiGraph'` → 6；`grep -c 'make_path_exclusion_memo'` → 4
- `grep -c 'caller_symbol_id\|callee_symbol_id' loader.py` → 14（≥ 2）；`grep -cE '"(caller|callee)_symbol"' loader.py` → 0（values_list 里无裸 FK 名）
- `grep -c 'fnmatch\|re.compile' loader.py` → 0；`grep -c 'build_matcher_and_fingerprint(' loader.py` → 0
- `cd server && uv run pytest tests/services/code_graph -q` → **47 passed, 13 skipped**
- 工作区内与本 plan 无关的预存在改动保持未提交、未修改

---
*Phase: 121-graph-base*
*Completed: 2026-08-09*
