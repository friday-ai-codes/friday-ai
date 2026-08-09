---
phase: 121-graph-base
plan: 06
subsystem: infra
tags: [code_graph, cross_repo, chunk_evidence, subgraph, degradation, sql-convergence, networkx]

# Dependency graph
requires:
  - phase: 121-02
    provides: "EdgeKind.CROSS_REPO / EdgeConfidence.CROSS_REPO / ChunkEvidence / CodeGraph.chunk_evidence / GraphMeta 的 cross_repo_* 两项"
  - phase: 121-03
    provides: "make_path_exclusion_memo（子图路径复用同一记忆化闭包）、test_observability_contract AST 守护"
  - phase: 121-05
    provides: "loader.py 主干：_SymbolNodeIndex.by_file_and_name（跨仓边二次解析的索引）、_load_symbol_nodes / _load_call_edges / load_graph"
provides:
  - "_load_cross_repo_edges：CrossRepoApiCall 的 (file_path, name) 二次解析，解析不上即丢弃 + cross_repo_unresolved_count 计数（D-05）"
  - "_load_chunk_evidence：ChunkEdge 旁挂证据面（CodeGraph.chunk_evidence），⛔ 不进 MultiDiGraph 边集"
  - "load_subgraph(repository_id, branch, *, seed_symbol_ids, depth, matcher, exclusion_fingerprint, include_low_confidence=False) -> CodeGraph"
  - "_expand_seed_ids：SQL 侧逐跳收敛（半径 depth+1，visited 去重兼防环，每轮 frontier 上限）"
  - "常量 CHUNK_EVIDENCE_MAX_PER_SYMBOL=50 / SUBGRAPH_FRONTIER_LIMIT=5000"
  - "INFO 事件 code_graph_degraded_subgraph"
affects: [121-08, 121-09, 121-10, 122, 123, 124, 125, 126, 127]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "跨表软引用的「二次解析」：没有 FK 时按 (归一后 file_path, name) 对已装载节点索引反查，解析不上即丢弃并计数，绝不造虚拟节点"
    - "降级路径的收敛在 SQL 侧多跳完成，而非「先全量装配再裁剪」——用例以「图数据表查询数不随仓库规模增长」把这条区分固化成回归"
    - "不同粒度的数据（chunk vs symbol）走并列的第二数据面，而不是强行对齐进同一张图"

key-files:
  created: []
  modified:
    - server/services/code_graph/loader.py
    - server/services/code_graph/model.py
    - server/tests/services/code_graph/test_loader.py

key-decisions:
  - "chunk 证据挂在边的**两端**符号上（源 chunk + 目标 chunk 各自的符号），而不是只挂源侧：一条边挂 k+k 条记录仍是线性，而只挂源侧会让被调侧的符号看不到自己身上的证据"
  - "子图路径的 CallEdge 收敛条件只加在**主叫**侧：任何幸存边都必须先满足 caller ∈ node_ids，再加 callee 侧的 OR 只会多捞一批注定被丢弃的行"
  - "cross_repo_branch_unfiltered 仅在真的装配到跨仓边时才置真——没有跨仓边就不存在这个语义缺口，长鸣的标记等于失效的标记"
  - "查询数契约只统计打到图数据表（codegraph_* / code_relations_*）的查询：INFO 事件触发的 system_settings 读属日志基础设施，不是装配取数"

patterns-established:
  - "「解析不上就丢弃 + 如实计数」在本模块已是第三处同款处理（模块级 caller / 裸名解析不到候选 / 跨仓边端点），三处注释互相指认同一条理由"
  - "旁挂数据面的 fan-out 上限与图边的属性个数一样，是可被用例守住的内存契约"

requirements-completed: []

# Metrics
duration: 40min
completed: 2026-08-09
---

# Phase 121 Plan 06: 跨仓边 / chunk 证据面 / 按需子图 Summary

**`loader.py` 后半落地：`CrossRepoApiCall` 的「文件路径 + 名字」二次解析（解析不上即丢弃并计数，绝不造虚拟节点）、`ChunkEdge` 的旁挂证据面（结构上消除 k² 笛卡尔爆炸），以及 GRAPH-03 降级路径的 `load_subgraph()`——收敛发生在 SQL 侧多跳，不是先全量装配再裁剪**

## Performance

- **Duration:** 约 40 分钟
- **Started:** 2026-08-09T06:55:00Z
- **Completed:** 2026-08-09T07:35:00Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- **四档边契约全部有了落地形态。** `resolved` / `bare_name` 由 121-05 交付，本 plan 补上 `cross_repo`（进图，唯一允许 4 个边属性）与 `chunk_level`（不进图，走 `CodeGraph.chunk_evidence` 旁挂面）。`test_cross_repo_edge_resolution` 的三个分支逐条对上验收：解析成功的边 `kind == "cross_repo"` / `match_confidence == 0.7`（原值透传、不归一化）、`handler_name` 对不上时该边不在图里且 `cross_repo_unresolved_count == 1`、`set(graph.nodes) <= 已装载 symbol_id 集合`——最后这条是 **T-121-虚假节点** 的直接回归，证明没有任何 `external` / `unresolved` 形态的虚拟节点混进来。
- **按仓过滤走的是反查，不是不存在的字段。** `CrossRepoApiCall` **自身没有 `repository` 字段**，过滤条件是 `Q(call_site__repository_id=…) | Q(endpoint__repository_id=…)`（`grep -c 'call_site__repository_id' loader.py` → 4；`grep -c 'CrossRepoApiCall.objects.filter(repository_id='` → 0）。这与 `codegraph/galaxy/cache.py:62` 登记的 `("cross_repo_api_call", CrossRepoApiCall, "call_site__repository_id", "matched_at")` 是同一个做法，注释里指明了这个先例，避免下一个读代码的人以为是本模块自创的绕路。
- **分支缺口被如实声明，而不是被抹平。** `ApiCallSite` 没有 `branch_name` 字段（`Endpoint` 侧有），跨仓边**无法按分支过滤**。装配到跨仓边时 `GraphMeta.cross_repo_branch_unfiltered` 置 `True`，成因同时写进 `load_graph` docstring 与该字段注释；`test_cross_repo_branch_unfiltered_false_without_cross_edges` 守住反向——没有跨仓边时不打标记，因为不存在这个缺口。
- **笛卡尔爆炸在结构上被消除，不是靠「注意别这么写」。** `ChunkEdge` 根本不经过 `graph.add_edge`：`_load_chunk_evidence` 只返回 `dict[symbol_id, tuple[ChunkEvidence, ...]]`。`test_chunk_evidence_side_channel` 先测出「还没有 ChunkEdge 时的边数」作对照，造完 chunk 边后断言 `graph.number_of_edges()` 与 `meta.edge_count` **都不变**，并遍历全部边断言不存在 `kind == "chunk"`。两个共享同一 `chunk_id` 的符号各拿到 1 条证据；`chunk_id` 为 `None` 的符号不在键里且不抛异常。
- **fan-out 上限是可测的内存契约。** `CHUNK_EVIDENCE_MAX_PER_SYMBOL = 50`：为同一符号造 60 条 chunk 边，证据长度恰为 50，截断条数进 `code_graph_assembled` 的 DEBUG 汇总。防的是 `SEMANTIC` / `CO_CHANGED` 这类边在热点 chunk 上成百上千条、而同 chunk 的每个符号都各挂一份。
- **降级路径被证明是 SQL 侧收敛。** `test_on_demand_subgraph_query_count_does_not_scale_with_repo` 用 `CaptureQueriesContext` 断言打到图数据表的查询数 ≤ `depth + 1 + 4`（实测 7 条：3 轮 frontier + Symbol/CallEdge/CrossRepoApiCall/ChunkEdge 各一条），随后**新增 200 个与种子无关的符号，查询数逐条相等**。这正是「SQL 侧多跳收敛」与「先全量装配再裁剪」的判别式——后者的取数量会随仓库规模线性膨胀。
- **半径取 `depth + 1` 有可执行证据。** 5 跳链 `s0→…→s5` 加一个孤立符号，`load_subgraph(seed=[s0], depth=2)` 得到节点集恰为 `{s0, s1, s2, s3}`，不含 `s5`、不含 `iso`。多留的那一跳保证边界节点 `s2` 的邻接完整——否则上层在第 `depth` 层会看到一批「假叶子」，影响面在边界处莫名截断。
- **exclusion 在子图路径同口径生效。** `test_on_demand_subgraph_applies_exclusion` 造 `src/ok.py::seed → secret/keys.py::load_key` 的真实解析边并加 `secret/**` 规则：子图节点集只剩 `seed`、边数 0、`excluded_file_count == 1`。子图与全量路径复用**同一个**记忆化闭包与同一套整文件 overlay 去重，不存在「降级路径的泄漏面比全量路径宽」的可能（T-121-泄漏）。
- **frontier 截断有标记也有日志。** `SUBGRAPH_FRONTIER_LIMIT` monkeypatch 成 2 后，1 个 hub + 5 个 leaf 的星形只装出 ≤ 3 个节点，`capture_logs` 抓到的 `code_graph_degraded_subgraph` 事件带 `frontier_truncated=True`，且 `component="code_graph"` / `category="sampling"` / `initiated_by_user_id="system"` 三项观测契约字段齐备。

## Task Commits

1. **Task 1: CrossRepoApiCall 端点二次解析（D-05）** — `5b65f93d` (feat)
2. **Task 2: ChunkEdge 旁挂证据面（Pitfall 2）** — `7625d000` (feat)
3. **Task 3: load_subgraph 按需诱导子图（GRAPH-03 降级路径）** — `7bb1aec1` (feat)

**Plan metadata:** 见本文件的收尾 docs 提交。

## Files Created/Modified

- `server/services/code_graph/loader.py`（677 → **1204 行**，plan 要求 ≥ 330）— 新增 `_CrossRepoStats` / `_load_cross_repo_edges` / `_resolve_by_file_and_name` / `_load_chunk_evidence` / `_log_degraded_subgraph` / `_expand_seed_ids` / `load_subgraph`；`_SymbolNodeIndex` 增 `chunk_to_symbols`；`_load_symbol_nodes` 增 `restrict_symbol_ids`、`_load_call_edges` 增 `restrict_caller_ids`；新增 4 个常量（`_CROSS_REPO_CHUNK_SIZE` / `_CHUNK_EDGE_CHUNK_SIZE` / `CHUNK_EVIDENCE_MAX_PER_SYMBOL` / `SUBGRAPH_FRONTIER_LIMIT`）与 `_CROSS_REPO_EDGE_ATTR_KEYS`；`__all__` 增 `load_subgraph`
- `server/services/code_graph/model.py` — **仅注释**：在 `CodeGraph.chunk_evidence` 字段上写明「`CHUNK_LEVEL` 档不产生任何图中的边」（见「偏差」第 1 条）
- `server/tests/services/code_graph/test_loader.py` — 3 个桩转真实断言 + 5 条新增用例 + 4 个本地造数助手（`_make_cross_repo_call` / `_bind_chunk` / `_make_chunk_edge` / `_make_call_chain` / `_assemble_subgraph`）

## Decisions Made

- **chunk 证据挂在边的两端，而不是只挂源侧。** plan 只说「用 `chunk_to_symbols` 把 chunk 边挂成 `chunk_evidence`」，没定挂哪一侧。选两端：证据面回答的是「哪些符号被这条共现关系触及」，只挂源侧会让被调侧的符号看不到自己身上的证据。代价仍是线性——一条边挂 `k + k` 条记录，不是 `k²` 条边，Pitfall 2 的风险不因此回来。跨仓 chunk 边的 target chunk 不在本仓，`chunk_to_symbols` 自然查不到，天然只挂得上源侧。同一条边在两端命中同一符号时（`source_chunk == target_chunk`）只挂一次。
- **`chunk_id` 取列但不进节点属性。** `_load_symbol_nodes` 的 `values_list` 多取一列 `chunk_id`，只喂 `_SymbolNodeIndex.chunk_to_symbols` 这个旁挂映射。进节点属性会把节点从 5 个属性推到 6 个，直接破掉内存契约——而它只在装配证据面时用一次。121-05 那条「字段清单即节点属性来源」的注释随之改成「字段清单**不等于**节点属性来源」，把这个区别写明。`test_assembles_multidigraph` 里 `"chunk_id" not in node_data` 的断言仍然成立。
- **子图的 `CallEdge` 收敛条件只加在主叫侧。** `restrict_caller_ids` 只生成 `caller_symbol_id__in=…`，不加 callee 侧的 `OR`：任何幸存的边都必须先满足 `caller_symbol_id ∈ node_ids`，而 `node_ids ⊆ reachable_ids`，加 `OR` 只会多捞一批注定被丢弃的行。副作用是子图路径的 `resolution_rate` 口径变成「该子图内的解析率」而非全仓解析率——这是子图的固有语义，已写进 `_load_call_edges` 的参数说明。
- **`_expand_seed_ids` 的每轮查询两侧都要 `OR`。** 与上一条相反：收敛阶段必须 `Q(caller_symbol_id__in=frontier) | Q(callee_symbol_id__in=frontier)`，否则子图只会沿调用方向单向扩张，「谁调用了我」那半边永远走不到——而 impact 的主用途恰恰是反向追溯。
- **`code_graph_degraded_subgraph` 取 INFO。** 与 121-05 那两条 DEBUG 汇总不同：这是**低频**事件（只有超预算大仓才走到），且对应一个上层必须透出的可信度标记。级别纪律禁止的是高频循环刷屏，不是这种一次一图的关键事件——plan 的 action 也是这么裁的。`initiated_by_user_id` 记 `system`：loader 是纯同步装配层，触发用户的绑定由 `cache.py` 在异步侧完成（它才拿得到 `user`）。
- **`cross_repo_branch_unfiltered` 按「是否真的装配到跨仓边」置位，不按「是否查了跨仓表」。** 没有跨仓边就不存在「无法按分支过滤」这个缺口；标记长鸣一次，上层就会学会无视它（与 121-05 对 `resolution_rate` 分母为 0 时取 `1.0` 同一条理由）。

## Deviations from Plan

三处，均为让验收条款真正成立所必需，无 Rule 1–4 触发，无功能性 scope creep。

**1. Task 2 多碰了一个文件：`server/services/code_graph/model.py`（仅注释）**

Task 2 的 `<files>` 只列了 `loader.py` + `test_loader.py`，但同一 task 的 action 明写：「`EdgeConfidence.CHUNK_LEVEL` 档在本相位**不产生任何图中的边**……这一点**必须写进 `chunk_evidence` 字段注释**，否则 Phase 122 的实现者会去图里找 `chunk` 边找不到。」而 `chunk_evidence` 字段在 `model.py` 的 `CodeGraph` 上。

处理：在该字段上加了 3 行注释，**零代码变更**（`git show 7625d000 -- server/services/code_graph/model.py` 只有注释行）。同一段话也写进了 `_load_chunk_evidence` 的 docstring，两处互相印证。

**2. Task 3 的查询数断言只统计打到图数据表的查询**

验收条款是「断言边查询次数 ≤ `depth + 1 + 常数`」。首次实现按 `len(ctx.captured_queries)` 计得 **11**，超出预期的 7。逐条打印后确认：7 条是装配取数（3 轮 frontier + Symbol/CallEdge/CrossRepoApiCall/ChunkEdge 各一条，形态完全符合预期），另外 **4 条是 `system_settings` 读**——由 `_log_degraded_subgraph` 这条 INFO 事件触发，属结构化日志基础设施的运行期配置读取，不是装配取数。

处理：断言改为只数 SQL 里含 `codegraph_` / `code_relations_` 的查询（7 ≤ `depth + 1 + 4`），理由写进用例注释。对照断言（新增 200 个无关符号后查询数**逐条相等**）同样用过滤后的口径——这反而更严格：不过滤的话，日志侧那 4 条读若被缓存，`==` 会因为无关原因失败。

⚠️ **顺带发现（留给 121-10 复核，本 plan 未处理）：一次 INFO 事件带来 4 次 `system_settings` 查询。** 对 `code_graph_degraded_subgraph` 这种一次一图的低频事件完全可接受，但若后续有人把这条埋点降到更热的路径上，代价会立刻显形。这是日志基础设施的既有行为（非本 plan 引入），未改。

**3. `_load_symbol_nodes` / `_load_call_edges` 各增一个可选参数**

plan 的 Task 3 action 说「只按最终 symbol_id 集合取 `Symbol` 行装配节点（同样过 exclusion 与 overlay 去重），并复用 Task 121-05/06 的边装配逻辑（限定在该节点集内）」。落地形态是给这两个私有函数各加一个默认 `None` 的关键字参数（`restrict_symbol_ids` / `restrict_caller_ids`），而不是复制一份子图专用的装配函数——复制必然让两条路径的 exclusion 与 overlay 口径漂移，那正是 T-121-泄漏 要防的东西。全量路径不传该参数，行为逐字节不变（121-05 的全部用例未改一行且仍绿）。

## Issues Encountered

**一处验收条款与实测不符**，已在「偏差」第 2 条完整记录（查询数统计口径）。除此之外三个 task 的自动化验收均一次通过。

**未触发观测契约拦截。** 新增的 `_log_degraded_subgraph` 照 121-05 的形态写：独立函数、事件名常量写在 `logger.info` 的第一个位置实参上、`component` / `category` 为字面量、异常吞掉。`test_observability_contract`（AST 扫全包 `*.py`）绿。

**Lint / 类型检查：**

- `uv run ruff check services/code_graph/ tests/services/code_graph/` → All checks passed。
- `uv run mypy services/code_graph/` → 唯一 1 条错误落在 `workflows/schemas/technical_plan.py:268`（预存在，121-01 ~ 121-05、121-07 已多次登记），本 plan 的文件 0 错误。

**测试范围：** 按本 plan 的测试预算跑了 `tests/services/code_graph` → **70 passed / 8 skipped**（121-05 收尾时是 47 passed / 13 skipped；本 plan 把 3 个桩转成真实断言并新增 5 条用例，其余增量来自 121-07）。plan `<verification>` 里点名的 `tests/codegraph tests/code_relations` 回归**未跑**——这条约 18 分钟的回归已排期为 Plan 121-10 的相位闸门，且本 plan 只读这两个 app 的表、未触碰其任何代码路径。Wave 0 登记的 4 条预存在失败（`test_chunkedge_fan_in_query_uses_target_index` 的 SQLite/PostgreSQL 方言耦合 + 3 条 `test_repo_summary_builder`）与本 plan 无关，未处理。

**工作区纪律：** 三次提交均按显式路径 staging，与本 plan 无关的预存在改动（`server/repositories/` / `server/mcp_tools/` / `web/src/` 及两个 submodule）全程未提交、未修改。

## User Setup Required

None — 纯 service 层装配模块，无外部服务、无新增配置项、无迁移。

## Next Phase Readiness

**已就绪：**

- **Plan 121-08（`cache.py` 取图链路）**：`load_subgraph` 与 `load_graph` 契约同款（`matcher` / `exclusion_fingerprint` 必填关键字参数、全同步、返回单值 `CodeGraph`），整段由 `cache.py` 一次性 `sync_to_async` 包裹即可。装配前的准入判据（`Symbol.count + CallEdge.count` 估算 > `CODE_GRAPH_MAX_GRAPH_BYTES`）决定走哪一条：超预算走 `load_subgraph`（**不进缓存**——它是种子相关的，缓存键里没有种子这一维）。`degraded` 在 `load_subgraph` 的返回值里已是终值 `"on_demand_subgraph"`，`cache.py` **不要**覆写它；需要覆写的仍是 `estimated_bytes` / `partial_edges` / `partial_reason` / `built_signature` 四项。
- **Plan 121-09（barrel）**：`loader.__all__` 现为 `["load_graph", "load_subgraph"]`，两者**都不进** `services/code_graph/__init__.py`——「不导出 loader / cache 是架构红线」（121-02 已定）。
- **Phase 122（上层工具）**：`GraphMeta` 的四个标记字段现在全部有真实来源（`low_resolution` ← 121-05、`cross_repo_unresolved_count` / `cross_repo_branch_unfiltered` ← 本 plan、`degraded` ← 本 plan、`partial_edges` ← 121-08）。四条输出声明可以照着写了。

**留给后续 plan 的显式待办：**

- **Plan 121-08**：`load_subgraph` 的 `seed_symbol_ids` 由上层传入，`cache.py` 需要决定「谁来给种子」——`get_graph()` 现有签名里没有这一维。建议不要把种子塞进缓存键（种子空间无界，缓存必然退化成一次一建），而是给超预算仓走一条**不缓存**的独立入口。
- **Plan 121-10**：`SUBGRAPH_FRONTIER_LIMIT = 5000` 与 `CHUNK_EVIDENCE_MAX_PER_SYMBOL = 50` 都是**未在真实仓上标定过**的保守值。该 plan 的实测交付物若顺带统计一下本仓最大仓的「单符号最大出入度」与「单 chunk 最大 fan-out」，可以据此复校这两个常数是否过紧或形同虚设。
- **Plan 121-10**：`visited` 集合的规模上界是 `(depth + 1) × SUBGRAPH_FRONTIER_LIMIT`（depth=5 时约 3 万），会作为 `id__in=` 的参数列表下发。Postgres 能吃下但不快，SQLite 的 `SQLITE_MAX_VARIABLE_NUMBER`（现代版本 32766）已经贴边。若实测发现大仓真的走到深层子图，需要给 `id__in` 加分批。本 plan 未做——当前上界仍在安全区内，提前分批只会让代码更难读。
- **Plan 121-10**：跨仓边的二次解析命中率**未在真实仓上统计过**。`cross_repo_unresolved_count` 现在是可观测的，建议该 plan 的解析率统计交付物顺带记一下这个数——若真实仓上绝大多数跨仓边都解析不上，说明 `(file_path, name)` 这个判据需要重新设计（比如放宽到 basename 匹配），而不是接受一个「大部分跨仓边都看不见」的图。

## Threat Flags

无——本 plan 未引入 `<threat_model>` 之外的新安全面（零新增网络入口、零新增鉴权路径、零文件访问、零 schema 变更）。威胁登记表的落地情况：

| Threat ID | Disposition | 落地 | 回归用例 |
|-----------|-------------|------|----------|
| T-121-虚假节点 | mitigate | ✅ 解析失败即丢弃 + 计数，⛔ 不建虚拟节点 | `test_cross_repo_edge_resolution` 分支 (b)(c)（含 `set(graph.nodes) <= 已装载 symbol_id 集合`） |
| T-121-跨仓越界 | mitigate | ✅ 不做多仓合并大图；边只挂在本图已有节点上，对端仓符号解析不到即丢弃 | 同上分支 (b) |
| T-121-分支缺口 | accept | ✅ `cross_repo_branch_unfiltered` 如实声明，成因写进 docstring 与字段注释 | `test_cross_repo_edge_resolution` + `test_cross_repo_branch_unfiltered_false_without_cross_edges` |
| T-121-笛卡尔爆炸 | mitigate | ✅ ChunkEdge 绝不进图边集 + `CHUNK_EVIDENCE_MAX_PER_SYMBOL=50` | `test_chunk_evidence_side_channel` / `test_chunk_evidence_fan_out_is_capped` |
| T-121-OOM | mitigate | ✅ SQL 侧多跳收敛 + `SUBGRAPH_FRONTIER_LIMIT=5000` | `test_on_demand_subgraph_query_count_does_not_scale_with_repo` / `test_on_demand_subgraph_frontier_truncation` |
| T-121-泄漏 | mitigate | ✅ 子图复用同一 exclusion 记忆化闭包与同一 overlay 去重键 | `test_on_demand_subgraph_applies_exclusion` |

## Self-Check: PASSED

- `server/services/code_graph/loader.py` FOUND（1204 行 ≥ plan 要求的 330），导出 `load_graph` / `load_subgraph`
- `server/services/code_graph/model.py` FOUND；`server/tests/services/code_graph/test_loader.py` FOUND
- 提交 `5b65f93d` / `7625d000` / `7bb1aec1` 均在 git 历史中可查
- `grep -c 'call_site__repository_id' loader.py` → **4**（≥ 1）；`grep -c 'CrossRepoApiCall.objects.filter(repository_id='` → **0**
- `grep -c 'build_matcher_and_fingerprint(' loader.py` → **0**（W-2 契约保持；docstring 里那句禁令散文的字面命中与 121-05 同因，已在该 plan 登记）
- `cd server && uv run pytest tests/services/code_graph -x -q` → **70 passed, 8 skipped**
- `uv run ruff check services/code_graph/ tests/services/code_graph/` → All checks passed
- `uv run mypy services/code_graph/` → 本 plan 文件 0 错误（唯一 1 条为预存在的 `workflows/schemas/technical_plan.py:268`）
- 三个 121-06 桩用例的 `@pytest.mark.skip` 已全部移除
- 工作区内与本 plan 无关的预存在改动保持未提交、未修改

---
*Phase: 121-graph-base*
*Completed: 2026-08-09*
