# Phase 122: impact / trace 工具面 - Context

**Gathered:** 2026-08-09
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous，用户授权全量采纳推荐答案）

<domain>
## Phase Boundary

本相位把 Phase 121 的内存图地基**变成 agent 能用的两个工具**，并在此定型「分析内核 + MCP/对话双面薄壳」的接线范式 —— 后续 123（detect_changes）、126（execution flow / rename_preview）全部照抄本相位的壳形状。

**IN SCOPE（IMPACT-01~06）:**
- `impact`：对任一符号做反向依赖分析，返回**深度分组**（d1/d2/d3 → WILL BREAK / LIKELY AFFECTED / MAY NEED TESTING）+ 每条边的 confidence 分档与 reason + `min_confidence` 过滤参数
- 跨仓穿越：沿 `CrossRepoApiCall` 边跨出本仓，结果标 `cross_repo: true` 与独立置信档；每穿一仓复核权限
- 确定性风险分级（LOW / MEDIUM / HIGH / CRITICAL），阈值可解释、**不走 LLM**
- 截断纪律：结果上限 + `summary` 计数，让 agent 知道被截断了多少
- `trace`：任意两符号间有向最短路，逐跳渲染 `file:line` + 边类型/置信度；重名返回消歧候选列表，**绝不静默取第一个**
- MCP 工具壳（PAT fail-closed + schema snapshot 测试）与 agents 对话 `@tool` 壳，两面共用同一内核
- 输出带索引 staleness 声明（「索引落后 N commits」）

**OUT OF SCOPE:**
- detect_changes / diff（Phase 123）、编码链集成（124）、社区与模块摘要（125）、执行流与 rename_preview（126）
- `affected_processes` 叙事层 —— Phase 126 回填，本相位**只预留输出字段位**，不实现
- 前端展示（本里程碑不做 impact 的 UI）
- 新增 Django 模型与迁移（本相位仍是纯读层，零迁移）
- `mcp` npm 包的客户端条目（跨仓欠债，ROADMAP 已记账，另批发版）

</domain>

<decisions>
## Implementation Decisions

### Area 1: 模块结构与对 Phase 121 的依赖纪律

- **D-01 — 内核放 `server/services/code_graph/impact.py` 与 `trace.py`，纯函数只吃 `MultiDiGraph`** 不碰 ORM、不碰 Django settings。理由：Phase 121 已经把 ORM 严格收在 `loader.py`，本相位继续这条分层；纯函数才能用合成图做毫秒级精度回归，不必起数据库。
- **D-02 — 取图一律经 `from services.code_graph import get_graph_service` 的包根 barrel**，⛔ 绝不 `from services.code_graph.loader import …` 或 `…cache import …`。Phase 121 已落地全仓 AST import 守护（`test_no_upper_layer_imports_internal_submodules`，且已修补 `from services.code_graph import loader` 这种拼法），本相位是它的**第一个真实承压者**——违规会在测试里立刻变红，不要绕。
- **D-03 — 内核不吞 `GraphError`，由壳层翻译**。`GraphNotIndexed` / `GraphAccessDenied` / `GraphBuildTimeout` 各自映射到明确的工具错误文案，⛔ 不允许 catch 成空结果——Phase 121 已把「不返回空图」写成硬约束，空影响面会被 agent 读成「改这里没影响」，是最危险的误导。
- **D-04 — 新增两个内核模块必须自动满足既有守护**：`services/code_graph/*.py` 被 AST 观测契约测试 glob，事件名须是静态可解析字面量（模块级 `Final[str]` 常量可以；共享 `_emit()` helper 会被拒——Phase 121 有四个 plan 各踩过一次）。`component = "code_graph"` 已在 `LOGGING-SPEC §5` 登记，本相位复用不必再登记。

### Area 2: impact 的算法与输出契约

- **D-05 — 反向 BFS 按层展开，深度即分组，不做打分排序**。d1/d2/d3 直接对应 WILL BREAK / LIKELY AFFECTED / MAY NEED TESTING 三档语义标签；**默认 `max_depth = 3`**，超过 3 层的影响面对 agent 没有行动价值（GitNexus 同款纪律）。同一符号在多层出现时取**最浅**那层（最坏情况优先）。
- **D-06 — 边的 confidence 沿用 Phase 121 已定型的 `EdgeConfidence` 四档**（`resolved` / `bare_name` / `cross_repo` / `chunk_level`），本相位**不发明新档位**。`min_confidence` 参数按 `confidence_score()` 的数值映射过滤（`resolved=1.0` / `bare_name=0.3` / `cross_repo=match_confidence` 原值）。
- **D-07 — 路径置信度取整条路径的最小值（弱边决定强度）**，不取平均、不取乘积。理由：平均会让一条 `resolved` 边把 `bare_name` 洗白；乘积会让深层路径的分数塌到无法与浅层比较。最小值语义直白可解释，正是 agent 需要的。
- **D-08 — `bare_name` 边默认不参与扩散**，与 Phase 121 的装配侧默认一致。开启需**同时**满足两件事：调用方显式传 `include_low_confidence=True`（透传给 `get_graph`，Phase 121 已把它并入缓存键）**且** `min_confidence` 低于 `bare_name` 的分值。两道闸是刻意的：单开一个不足以放行，避免误配置把假阳性灾难放出来。
- **D-09 — `reason` 现推不存**（沿用 Phase 121 的 D-08）：输出时调 `derive_reason()` 生成，⛔ 不在图边属性上新增第四个属性。
- **D-10 — 输出为结构化 dict，不是渲染好的字符串**。渲染留给壳层，让 MCP（JSON）与对话（markdown）两面各自决定形态，内核只出数据。

### Area 3: 跨仓穿越与权限

- **D-11 — 跨仓穿越默认开启但深度独立受限**：跨仓跳数默认上限 **1**（改后端 `Endpoint` → 列出前端调用点，正是一跳）。理由：Phase 121 实测跨仓边的 `(file_path, name)` 二次解析尚未验证命中率，多跳跨仓会把未验证的误差累乘。参数名 `max_cross_repo_hops`。
- **D-12 — 每穿一仓复核权限**，用 Phase 121 的 `get_graph`（它每次调用都跑 `ensure_repository_readable`，不因缓存命中跳过）。无权限的对端仓**整仓折叠**为 `REDACTED_REPOSITORY`（Phase 121 已导出该常量）——出现「有影响但不告诉你是什么」的占位，而**不是**静默丢弃。静默丢弃会让 agent 以为影响面更小。
- **D-13 — 跨仓结果标 `cross_repo: true` 并携带 `match_confidence` 原值**，不归一化到本仓的档位数值。跨仓边的可信度来源与本仓完全不同，混在一起比较是错的。
- **D-14 — 跨仓取图失败（对端未索引 / 建图超时）不使整个 impact 失败**：该仓折叠为一条带 `unavailable_reason` 的条目，本仓结果照常返回。fail-soft，但**必须显式声明**，不能假装没有这个仓。

### Area 4: 风险分级与截断纪律

- **D-15 — 风险分级是确定性函数，输入只有三个量**：d1 数量、是否穿仓、路径最高置信档。阈值写成模块级常量表并在 docstring 里逐条解释，⛔ 不走 LLM、不引入不可复现的判断。初值（可由后续相位用真实数据校准，照 Phase 121 的复校范式）：
  | 等级 | 判据 |
  |---|---|
  | CRITICAL | d1 ≥ 20，或（穿仓 且 d1 ≥ 5） |
  | HIGH | d1 ≥ 8，或穿仓 |
  | MEDIUM | d1 ≥ 3 |
  | LOW | 其余 |
  ⚠️ 阈值必须在 SUMMARY 里如实标注为**未经真实数据校准的初值**，不得表述成经验结论。
- **D-16 — 截断默认上限 200 条，按「深度升序 + 置信度降序」排序后截断**，并在 `summary` 里给出 `total_found` / `returned` / `truncated_by_depth` 分层计数。agent 必须能回答「我看到的是不是全部」。
- **D-17 — `include_content` 默认关**（只出 `file:line` 与符号名，不出源码正文）。token 纪律是 agent 工具的生命线；正文由 agent 自己按需要再去读文件。

### Area 5: trace 与重名消歧

- **D-18 — trace 用有向最短路（`networkx.shortest_path`），默认只走 `resolved` 边**。多条等长路径时返回**第一条**并在输出里声明「存在 N 条等长路径」，⛔ 不静默隐瞒多解。
- **D-19 — 符号解析统一走「uid 优先 + 重名返回候选列表」协议**，impact 与 trace **共用同一个解析器**（放 `symbol_resolve.py` 或内核共享私有函数，由执行方定）。候选列表逐条带 `file:line` + `symbol_type` + `signature`，让 agent 有依据二选一。⛔ 绝不静默取第一个——这是 REQUIREMENTS 明文要求。
- **D-20 — 不可达时返回明确的「无路径」结构**（含两端符号的解析结果与所用的 `min_confidence`），不是空数组。空数组会被读成「工具坏了」而不是「确实没有调用关系」。

### Area 6: 双面接线与 staleness

- **D-21 — MCP 壳照 `server/mcp_tools/views.py` 的 `McpToolView` 既有范式**：PAT fail-closed、`RetrievalTrace` 留痕、schema snapshot 测试。对话壳照 `server/agents/tools/` 的 `@tool` 注册范式。**两面共用同一内核函数**，壳层只做参数解析与渲染——⛔ 逻辑不许在壳里分叉，否则两面行为会漂移（v0.16.1 的 UNIFY 系列就是在还这笔债）。
- **D-22 — staleness 声明取 `CodeGraph`/`GraphMeta` 已有的水位字段**（Phase 121 已在图元数据上落 `as_of` 语义），换算成「索引落后 N commits」。拿不到落后数时降级为「as_of `<sha>`」原样透出，⛔ 不编造数字。
- **D-23 — Phase 121 的四个降级标记必须原样透传到工具输出**：`partial_edges` / `degraded` / `low_resolution` / `cross_repo_unresolved_count`。Phase 121 的实测发现全仓解析率中位数只有 **0.17**，因此 **`resolution_rate` 必须始终透出数值**，不能只透出 `low_resolution` 布尔标记 —— 在 17% 的常态下布尔值没有信息量（这是 121-10 写给本相位的硬要求）。
- **D-24 — 超预算大仓不自动降级**：Phase 121 的 `get_graph` 在无 `seed_symbol_ids` 时对超预算仓**抛 `GraphError`** 而非返回截断图。impact/trace 天然有种子符号，因此壳层**必须**把种子透传下去走按需子图路径；这是本相位必须处理的异常分支，不是可选优化。

### Area 7: 调研回灌的补充裁决（2026-08-09，RESEARCH.md 提出的 5 个 open question，已裁决为锁定决策）

调研（`122-RESEARCH.md`）推翻了 Area 3 的一条根本假设，以下裁决**优先级高于**上文对应条目：

- **D-25 — 跨仓穿越必须走 ORM 直查，不能靠图内的 `cross_repo` 边**（推翻 D-11/D-13 的隐含前提）。实测确认 `loader._load_cross_repo_edges`（`loader.py:812-828`）只在 `call_site.repository_id` 与 `endpoint.repository_id` **同时等于本仓**时才建边，凡有一端在别的仓库的行一律计入 `cross_repo_unresolved_count` 并丢弃 —— 图里 `kind == "cross_repo"` 的边**从来不跨仓**。因此跨仓 impact 的实现路径是：壳层直查 `CrossRepoApiCall` ORM 找到对端 `Endpoint` → 对对端仓再走一次 `get_graph` → 在对端图上继续反向 BFS。⛔ 不许改 `loader.py` 的建边口径来「顺手修好」——那是 Phase 121 已验证的冻结行为，改它要另开相位。
- **D-26 — IMPACT-03 在零生产样本下的验收方式**：生产库 `CrossRepoApiCall` = 0 / `ApiCallSite` = 0 / `ApiWrapper` = 0（`Endpoint` = 6,014），上游产出器依赖 volar LSP 而 server 镜像无 Node（归 LSP-01 / Phase 127）。所以本相位**用合成数据覆盖四条分支**（解析成功 / 对端无权限折叠 / 对端未索引 fail-soft / 跳数超限），并在 SUMMARY 里**如实声明「跨仓路径未经任何真实数据验证」**，同时在 ROADMAP 记一笔「Phase 127 补齐 LSP 后需回来用真实样本复验 IMPACT-03」。⛔ 不得把合成数据的通过表述成能力已验证。121-10 记的「样本不足」实为**样本为零**，本条更正之。
- **D-27 — 本相位不碰 `mcp` npm 包，欠债走 ROADMAP 记账**。`test_mcp_package_tools_match_server_snapshot` 在 HEAD 上已经红着（5 项既有漂移），新增两个 MCP 工具会让它变成 7 项。仍然不修，两个理由：① 该 submodule 当前正被另一个并发会话修改，本相位去动必然冲突；② ROADMAP 已明文记账「`mcp` npm 包需为本里程碑新增的 MCP 工具补条目并发版（另一仓库改动，v0.20.0 已有同款缺口在案）」。本相位**只需在 SUMMARY 里把漂移项从 5 更新为 7**，不改 submodule、不改守护测试的判据。
- **D-28 — `impact.py` / `trace.py` 不进 barrel，也不进 `_INTERNAL_SUBMODULES`**。它们是与 `model`/`loader`/`cache` 平级的新内核，壳层直连合法。理由：barrel 的红线守的是「绕过 `GraphService.get_graph` 的三道闸」，而 impact/trace 内核**自己就是经 `get_graph` 拿图的消费者**，把它们也锁进去只会逼壳层写无谓的转发。需在 `__init__.py` docstring 里补一句说明这个边界，避免下次 review 误判。
- **D-29 — 风险分级补上第三个输入的真实判据**（修正 D-15 的自相矛盾：原表列了三个输入却只用了两个）。新增一条**封顶规则**：若某符号的全部到达路径的最高置信档只到 `bare_name`，则其风险等级**封顶为 MEDIUM**，不得判 HIGH/CRITICAL。理由：弱证据不该产生强告警，否则裸名边的假阳性会直接变成 CRITICAL 噪音，正是 Pitfall 1 要防的事。封顶规则在阈值表之后生效（先按 d1/穿仓算,再封顶）。
- **D-30 — `REDACTED_REPOSITORY` 折叠条目不带 `affected_count`**，只出裸标记。裁决依据是存在性预言机（existence oracle）权衡：计数会泄漏一个调用方**无权访问**的仓库的内部规模。安全优先于便利，与本相位 fail-closed 的整体姿态一致。折叠条目携带的信息止于「这里有一个你无权看的仓库」。

### 调研带出的两个生产分布（planner 必须据此定参数）

- **符号重名率 19.3%**（2,436 个名字对应 >20 个符号）—— D-19 的候选列表是**主路径**，不是异常兜底，接口设计要按「多数查询都会撞重名」来做。
- **解析边入度 max 2,803 / p99 25** —— D-16 的 200 条截断在热点符号上**必然触发**，截断计数与排序策略是实际会被用到的功能，不是理论边界。
- **staleness 零成本**：`Repository.behind_commits` 是定时任务算好的库字段，生产 258/258 全覆盖 —— D-22 的降级分支基本用不上，但仍要保留。
- **networkx 性能实测**：冻结 `MultiDiGraph` 上 `reverse(copy=False)` 0.004ms、`subgraph_view(filter_edge)` 0.013ms、`shortest_path` 0.038ms；而 `copy()` / `reverse(copy=True)` 要 **330–690ms**。⛔ 任何实现都不许 copy 图，一律走视图。

### Claude's Discretion

- 模块与私有函数的切分粒度、`symbol_resolve` 是独立模块还是内核共享私有函数、渲染模板的具体措辞、测试文件的组织方式。
- 是否为 impact 增加 `exclude_test_files` 之类的便利过滤（推荐做，但不做也不算缺口）。
- 合成图 fixture 的构造方式（推荐建一个可复用的「已知拓扑」小图，让深度分组与最短路的断言可逐点核对）。

</decisions>

<code_context>
## Existing Code Insights

### Phase 121 交付的地基（本相位的唯一依赖，已验证 passed）

公开面 = `server/services/code_graph/__init__.py` 的 **17 项 barrel**：

- `GraphService` / `get_graph_service()` / `invalidate_repository()`
- `CodeGraph` / `GraphMeta` / `ChunkEvidence`
- `EdgeKind` / `EdgeConfidence` / `confidence_score()` / `derive_reason()`
- `GraphError` / `GraphAccessDenied` / `GraphNotIndexed` / `GraphBuildFailed` / `GraphBuildTimeout`
- `LOW_RESOLUTION_THRESHOLD`（= **0.10**，经 218 个仓真实数据校准）/ `REDACTED_REPOSITORY`

主入口签名（`cache.py:674`）：

```
async def get_graph(
    repository_id: str,
    branch: str = "",
    *,
    user: Any | None = None,
    include_low_confidence: bool = False,
    seed_symbol_ids: Sequence[str] | None = None,
    depth: int | None = None,
) -> CodeGraph
```

关键语义（逐条已在 Phase 121 落测）：
- 图对象是 **`MultiDiGraph`**（同一符号对之间多档边并存），且**出图时被 `nx.freeze` 冻结**——本相位拿到的图**不可变**，任何需要改图的算法必须自己 copy。
- 缓存键是 `(repository_id, branch, include_low_confidence)` 三元组。
- `ensure_repository_readable` **每次调用都跑**，不因缓存命中跳过。
- 边属性恰好 3 个，`reason` 由 `derive_reason()` 输出时现推。
- 字节常数经生产实测：`NODE_COST_BYTES=800` / `EDGE_COST_BYTES=680`；256MB 单图上限约当 8.6 万符号。

### 可照抄的既有范式

- **MCP 工具壳**：`server/mcp_tools/views.py::McpToolView`（PAT fail-closed、`_get_indexed_repo` 要求 `index_status == INDEXED`、`_exclusion_matcher`）；snapshot 测试见 `server/tests/mcp_tools/`。
- **对话工具壳**：`server/agents/tools/`（`@tool` 注册；`repository_relevance.py` 是形状相近的先例）。
- **观测**：`component="code_graph"` 已登记；事件名 `code_graph_*` 前缀 + `category`（本相位工具调用属 `caller` 类，内部图步骤属 `sampling`）。
- **测试**：`server/tests/services/code_graph/`（96 passed / 0 skipped，conftest 自建 fixture，含 `GraphService` 的 autouse 重置钩子）。⚠️ 本机跑库相关用例需带
  `GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False … --reuse-db`，否则 app-init 守护线程会占住 `test_friday` 导致建库失败。

### 集成点

- 新内核：`server/services/code_graph/impact.py`、`trace.py`（＋可选 `symbol_resolve.py`）
- MCP 壳：`server/mcp_tools/views.py` + `server/mcp_tools/urls.py`（照既有工具加两条）
- 对话壳：`server/agents/tools/`
- 测试：`server/tests/services/code_graph/`（内核）+ `server/tests/mcp_tools/`（壳与 snapshot）

</code_context>

<specifics>
## Specific Ideas

- `.planning/research/SUMMARY.md` 的 **Pitfall 1「裸名边假阳性灾难」**是本相位的验收内核：置信度分层透出是**输出契约**而非优化项。Phase 121 已把分档做进装配层，本相位负责把它**一路透到 agent 眼前**——中间任何一层把档位抹平，这条纪律就断了。
- GitNexus 的工具契约（深度分组语义标签、`minConfidence`、风险四级、截断 summary、重名消歧协议、`as_of` staleness）在调研里有一手引用，**可直接照搬形状**，不必重新设计。
- 跨仓 impact 是本里程碑相对 GitNexus 的**反超点**（它每仓独立图做不到）。但 Phase 121 如实记录了跨仓边二次解析的真实命中率**尚未测得**（生产 `CrossRepoApiCall` 样本不足），本相位若能在真实数据上测出该命中率，应写进 SUMMARY；若命中率过低，需要把结论上报而不是让一张大半不可见的跨仓图静默服务。

</specifics>

<deferred>
## Deferred Ideas

- **`affected_processes` 叙事层** — Phase 126 回填，本相位只预留字段位。
- **`context` 符号 360 度视图工具**（GitNexus 对标）— REQUIREMENTS 的 Future 段已登记，等 impact/trace 稳定后自然演化。
- **`detect_impact` 式 MCP 编排 prompt** — 等工具面稳定（v2+），已在 Future 段登记。
- **impact 结果的前端可视化** — 本里程碑不做 UI。
- **风险阈值的真实数据校准** — 本相位落初值并显式标注未校准；校准需要真实使用样本，留给工具上线后。
- **`mcp` npm 包补条目并发版** — 跨仓改动，ROADMAP 已记账。

</deferred>
