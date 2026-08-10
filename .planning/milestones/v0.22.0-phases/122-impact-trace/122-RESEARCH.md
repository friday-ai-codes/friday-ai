# Phase 122: impact / trace 工具面 - Research

**Researched:** 2026-08-09
**Domain:** 静态调用图分析（反向 BFS 深度分组 / 有向最短路）+ MCP·对话双面工具壳（brownfield 增量）
**Confidence:** HIGH（networkx 行为、壳层契约、机械守护、生产数据全部一手实测）

---

## Summary

本相位是纯装配工程：所有能力都已在仓里，缺的只是把它们接起来。networkx 3.6.1 已在依赖树，Phase 121 的 `MultiDiGraph` 已冻结出图，MCP 壳与 `@tool` 壳各有 40+ 个先例，staleness 所需的 `behind_commits` 是已经算好的库字段。**零新增依赖、零迁移、零新模型。** 算法侧的所有关键 API 都已在本仓 Python 3.14 / networkx 3.6.1 上实测通过（见 `## Code Examples`），包括「冻结图上的反向视图」「按边属性过滤而不复制」「MultiDiGraph 上的最短路」三个 CONTEXT 直接依赖的点。

但调研发现**一条会让 IMPACT-03 落空的硬事实**，planner 必须在开工前决策：Phase 121 的 `loader._load_cross_repo_edges` 只在 `call_site.repository_id` **与** `endpoint.repository_id` **同时等于本仓**时才建边，凡有一端在别的仓库的行一律 `unresolved_count += 1; continue`。也就是说，图里 `kind == "cross_repo"` 的边**从来不跨仓**（它们是「本仓调用自己的 endpoint」），真正的跨仓边 100% 落在 `cross_repo_unresolved_count` 里、从不入图。**沿 `CrossRepoApiCall` 边穿仓这条路在图上不存在**，IMPACT-03 只能靠壳层直查 ORM 实现。雪上加霜的是，生产库里 `CrossRepoApiCall` / `ApiCallSite` / `ApiWrapper` **三张表全部为 0 行**（Endpoint 有 6,014 行），跨仓链路的上游产出器根本没跑起来——这与 LSP-01（server 镜像无 Node ⇒ volar 不可用 ⇒ ApiWrapper 检测无法运行）是同一条因果链，归 Phase 127。

第二组值得据此调参的生产数字：符号重名率 **19.3%**（202,661 个 distinct `(repo, name)` 中 39,031 个对应多个符号，2,436 个名字对应 >20 个符号）——D-19 的消歧候选列表不是边缘分支，是**五分之一的调用都会走的主路径**；解析边入度 **中位数 1 / p99 25 / 最大 2,803**，出度 **中位数 4 / p99 54 / 最大 3,613**——D-16 的 200 条截断在热点符号上必然触发，`summary` 计数不是装饰。

**Primary recommendation:** 内核用**手写分层反向 BFS**（不是 `nx.bfs_layers`）走 `g.predecessors()` + `g[u][v]` 邻接，实测与 `subgraph_view` 同速，且顺带产出 D-07 的 path-min 置信度与逐跳 `file:line`（`bfs_layers` 一样都给不了）；trace 用 `nx.shortest_path` 跑在 `nx.subgraph_view(g, filter_edge=…)` 上（已验证冻结图可用、0.013ms 建视图）。IMPACT-03 改为「壳层用一次 `CrossRepoApiCall` ORM 查询做一跳穿仓 + 对端仓再走一次 `get_graph`」，并在 SUMMARY 里如实上报「生产零样本、未经真实数据验证」。

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Area 1: 模块结构与对 Phase 121 的依赖纪律**

- **D-01** — 内核放 `server/services/code_graph/impact.py` 与 `trace.py`，纯函数只吃 `MultiDiGraph`。不碰 ORM、不碰 Django settings。理由：Phase 121 已经把 ORM 严格收在 `loader.py`，本相位继续这条分层；纯函数才能用合成图做毫秒级精度回归，不必起数据库。
- **D-02** — 取图一律经 `from services.code_graph import get_graph_service` 的包根 barrel，⛔ 绝不 `from services.code_graph.loader import …` 或 `…cache import …`。Phase 121 已落地全仓 AST import 守护（`test_no_upper_layer_imports_internal_submodules`，且已修补 `from services.code_graph import loader` 这种拼法），本相位是它的**第一个真实承压者**——违规会在测试里立刻变红，不要绕。
- **D-03** — 内核不吞 `GraphError`，由壳层翻译。`GraphNotIndexed` / `GraphAccessDenied` / `GraphBuildTimeout` 各自映射到明确的工具错误文案，⛔ 不允许 catch 成空结果——Phase 121 已把「不返回空图」写成硬约束，空影响面会被 agent 读成「改这里没影响」，是最危险的误导。
- **D-04** — 新增两个内核模块必须自动满足既有守护：`services/code_graph/*.py` 被 AST 观测契约测试 glob，事件名须是静态可解析字面量（模块级 `Final[str]` 常量可以；共享 `_emit()` helper 会被拒——Phase 121 有四个 plan 各踩过一次）。`component = "code_graph"` 已在 `LOGGING-SPEC §5` 登记，本相位复用不必再登记。

**Area 2: impact 的算法与输出契约**

- **D-05** — 反向 BFS 按层展开，深度即分组，不做打分排序。d1/d2/d3 直接对应 WILL BREAK / LIKELY AFFECTED / MAY NEED TESTING 三档语义标签；**默认 `max_depth = 3`**，超过 3 层的影响面对 agent 没有行动价值（GitNexus 同款纪律）。同一符号在多层出现时取**最浅**那层（最坏情况优先）。
- **D-06** — 边的 confidence 沿用 Phase 121 已定型的 `EdgeConfidence` 四档（`resolved` / `bare_name` / `cross_repo` / `chunk_level`），本相位**不发明新档位**。`min_confidence` 参数按 `confidence_score()` 的数值映射过滤（`resolved=1.0` / `bare_name=0.3` / `cross_repo=match_confidence` 原值）。
- **D-07** — 路径置信度取整条路径的最小值（弱边决定强度），不取平均、不取乘积。理由：平均会让一条 `resolved` 边把 `bare_name` 洗白；乘积会让深层路径的分数塌到无法与浅层比较。最小值语义直白可解释，正是 agent 需要的。
- **D-08** — `bare_name` 边默认不参与扩散，与 Phase 121 的装配侧默认一致。开启需**同时**满足两件事：调用方显式传 `include_low_confidence=True`（透传给 `get_graph`，Phase 121 已把它并入缓存键）**且** `min_confidence` 低于 `bare_name` 的分值。两道闸是刻意的：单开一个不足以放行，避免误配置把假阳性灾难放出来。
- **D-09** — `reason` 现推不存（沿用 Phase 121 的 D-08）：输出时调 `derive_reason()` 生成，⛔ 不在图边属性上新增第四个属性。
- **D-10** — 输出为结构化 dict，不是渲染好的字符串。渲染留给壳层，让 MCP（JSON）与对话（markdown）两面各自决定形态，内核只出数据。

**Area 3: 跨仓穿越与权限**

- **D-11** — 跨仓穿越默认开启但深度独立受限：跨仓跳数默认上限 **1**（改后端 `Endpoint` → 列出前端调用点，正是一跳）。理由：Phase 121 实测跨仓边的 `(file_path, name)` 二次解析尚未验证命中率，多跳跨仓会把未验证的误差累乘。参数名 `max_cross_repo_hops`。
- **D-12** — 每穿一仓复核权限，用 Phase 121 的 `get_graph`（它每次调用都跑 `ensure_repository_readable`，不因缓存命中跳过）。无权限的对端仓**整仓折叠**为 `REDACTED_REPOSITORY`（Phase 121 已导出该常量）——出现「有影响但不告诉你是什么」的占位，而**不是**静默丢弃。静默丢弃会让 agent 以为影响面更小。
- **D-13** — 跨仓结果标 `cross_repo: true` 并携带 `match_confidence` 原值，不归一化到本仓的档位数值。跨仓边的可信度来源与本仓完全不同，混在一起比较是错的。
- **D-14** — 跨仓取图失败（对端未索引 / 建图超时）不使整个 impact 失败：该仓折叠为一条带 `unavailable_reason` 的条目，本仓结果照常返回。fail-soft，但**必须显式声明**，不能假装没有这个仓。

**Area 4: 风险分级与截断纪律**

- **D-15** — 风险分级是确定性函数，输入只有三个量：d1 数量、是否穿仓、路径最高置信档。阈值写成模块级常量表并在 docstring 里逐条解释，⛔ 不走 LLM、不引入不可复现的判断。初值（可由后续相位用真实数据校准，照 Phase 121 的复校范式）：

  | 等级 | 判据 |
  |---|---|
  | CRITICAL | d1 ≥ 20，或（穿仓 且 d1 ≥ 5） |
  | HIGH | d1 ≥ 8，或穿仓 |
  | MEDIUM | d1 ≥ 3 |
  | LOW | 其余 |

  ⚠️ 阈值必须在 SUMMARY 里如实标注为**未经真实数据校准的初值**，不得表述成经验结论。
- **D-16** — 截断默认上限 200 条，按「深度升序 + 置信度降序」排序后截断，并在 `summary` 里给出 `total_found` / `returned` / `truncated_by_depth` 分层计数。agent 必须能回答「我看到的是不是全部」。
- **D-17** — `include_content` 默认关（只出 `file:line` 与符号名，不出源码正文）。token 纪律是 agent 工具的生命线；正文由 agent 自己按需要再去读文件。

**Area 5: trace 与重名消歧**

- **D-18** — trace 用有向最短路（`networkx.shortest_path`），默认只走 `resolved` 边。多条等长路径时返回**第一条**并在输出里声明「存在 N 条等长路径」，⛔ 不静默隐瞒多解。
- **D-19** — 符号解析统一走「uid 优先 + 重名返回候选列表」协议，impact 与 trace **共用同一个解析器**（放 `symbol_resolve.py` 或内核共享私有函数，由执行方定）。候选列表逐条带 `file:line` + `symbol_type` + `signature`，让 agent 有依据二选一。⛔ 绝不静默取第一个——这是 REQUIREMENTS 明文要求。
- **D-20** — 不可达时返回明确的「无路径」结构（含两端符号的解析结果与所用的 `min_confidence`），不是空数组。空数组会被读成「工具坏了」而不是「确实没有调用关系」。

**Area 6: 双面接线与 staleness**

- **D-21** — MCP 壳照 `server/mcp_tools/views.py` 的 `McpToolView` 既有范式：PAT fail-closed、`RetrievalTrace` 留痕、schema snapshot 测试。对话壳照 `server/agents/tools/` 的 `@tool` 注册范式。**两面共用同一内核函数**，壳层只做参数解析与渲染——⛔ 逻辑不许在壳里分叉，否则两面行为会漂移（v0.16.1 的 UNIFY 系列就是在还这笔债）。
- **D-22** — staleness 声明取 `CodeGraph`/`GraphMeta` 已有的水位字段（Phase 121 已在图元数据上落 `as_of` 语义），换算成「索引落后 N commits」。拿不到落后数时降级为「as_of `<sha>`」原样透出，⛔ 不编造数字。
- **D-23** — Phase 121 的四个降级标记必须原样透传到工具输出：`partial_edges` / `degraded` / `low_resolution` / `cross_repo_unresolved_count`。Phase 121 的实测发现全仓解析率中位数只有 **0.17**，因此 **`resolution_rate` 必须始终透出数值**，不能只透出 `low_resolution` 布尔标记 —— 在 17% 的常态下布尔值没有信息量（这是 121-10 写给本相位的硬要求）。
- **D-24** — 超预算大仓不自动降级：Phase 121 的 `get_graph` 在无 `seed_symbol_ids` 时对超预算仓**抛 `GraphError`** 而非返回截断图。impact/trace 天然有种子符号，因此壳层**必须**把种子透传下去走按需子图路径；这是本相位必须处理的异常分支，不是可选优化。

### Claude's Discretion

- 模块与私有函数的切分粒度、`symbol_resolve` 是独立模块还是内核共享私有函数、渲染模板的具体措辞、测试文件的组织方式。
- 是否为 impact 增加 `exclude_test_files` 之类的便利过滤（推荐做，但不做也不算缺口）。
- 合成图 fixture 的构造方式（推荐建一个可复用的「已知拓扑」小图，让深度分组与最短路的断言可逐点核对）。

### Deferred Ideas (OUT OF SCOPE)

- **`affected_processes` 叙事层** — Phase 126 回填，本相位只预留字段位。
- **`context` 符号 360 度视图工具**（GitNexus 对标）— REQUIREMENTS 的 Future 段已登记，等 impact/trace 稳定后自然演化。
- **`detect_impact` 式 MCP 编排 prompt** — 等工具面稳定（v2+），已在 Future 段登记。
- **impact 结果的前端可视化** — 本里程碑不做 UI。
- **风险阈值的真实数据校准** — 本相位落初值并显式标注未校准；校准需要真实使用样本，留给工具上线后。
- **`mcp` npm 包补条目并发版** — 跨仓改动，ROADMAP 已记账。⚠️ 见 `## Common Pitfalls` Pitfall 3：这条「out of scope」与一条既有 CI 守护测试直接冲突，planner 必须显式决策。
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| IMPACT-01 | 深度分组反向依赖（d1/d2/d3 = WILL BREAK / LIKELY AFFECTED / MAY NEED TESTING） | `## Code Examples` §1 手写分层反向 BFS（实测 0.012ms/查询，30k 节点 100k 边）；`g.reverse(copy=False)` 与 `g.predecessors()` 均已验证在冻结图上可用 |
| IMPACT-02 | 每边 confidence 分档 + reason + `min_confidence` 参数 | `EdgeConfidence` / `confidence_score()` / `derive_reason()` 均已在 barrel（`model.py:53-165`）；`## Code Examples` §2 给出 `min_confidence` 的两种落地（inline 谓词 / `subgraph_view`）与二者性能对照 |
| IMPACT-03 | 穿 `CrossRepoApiCall` 边界，`cross_repo: true` + 独立置信档 | 🚨 **不能走图边**——`loader.py:812-828` 证明真跨仓边全被丢弃；须走 ORM 直查，方案见 `## Architecture Patterns` §跨仓穿越。生产零样本（`## Open Questions` Q1） |
| IMPACT-04 | 确定性风险分级 + 截断 summary | 纯函数，D-15/D-16 已给死阈值；生产 fan-in 分布（max 2,803）证明截断必然触发 |
| IMPACT-05 | trace 最短路 + 逐跳 file:line + 重名消歧候选列表 | `nx.shortest_path` / `nx.all_shortest_paths` 在 MultiDiGraph + `subgraph_view` 上均已实测；重名率 19.3% 见 `## Common Pitfalls` Pitfall 2；`signature` 不在图节点属性上，须 ORM 补取（`loader.py:354-356`） |
| IMPACT-06 | MCP + 对话双面，输出带 staleness | `McpToolView` 契约见 `## Architecture Patterns` §MCP 壳；`@tool` 契约见 §对话壳；staleness 走 `Repository.behind_commits`（生产 258/258 覆盖，零 git 调用） |
</phase_requirements>

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 反向 BFS 深度分组 / 最短路 | **纯算法内核**（`services/code_graph/impact.py`, `trace.py`） | — | D-01：只吃 `MultiDiGraph`，可用合成图做毫秒级回归 |
| 置信度过滤 / path-min 计算 / 风险分级 / 截断排序 | **纯算法内核** | — | 全部是 `MultiDiGraph` + 参数的确定性函数，零 I/O |
| 符号解析（uid → 节点 / name → 候选列表） | **内核（图内解析）** + **ORM（`signature` 补取）** | — | 图节点属性恒 5 个、**不含 `signature`**（`loader.py:354-356`），D-19 要求的候选列表字段跨了两层，解析器必须分成「图内定位」与「ORM 补字段」两半 |
| 取图 / 权限 / exclusion / 水位 | **`GraphService.get_graph()`**（Phase 121，已存在） | — | D-02：唯一收口点，三道闸 |
| 跨仓一跳（`CrossRepoApiCall` 查询） | **壳层 / 独立 service**（ORM） | 对端仓再走 `get_graph` | D-01 禁止内核碰 ORM；且真跨仓边根本不在图里（见下） |
| staleness（落后 N commits） | **壳层**（读 `Repository.behind_commits`） | — | 已是库字段，定时任务算好；请求路径零 git 调用 |
| 参数校验 / 鉴权 / 留痕 / 渲染 | **壳层**（`McpToolView` / `@tool`） | — | D-21：两面共用内核，壳只做解析与渲染 |
| `caller` 类观测事件 + `RetrievalTrace` | **壳层** | — | 🚨 内核**不能**发 `caller` 事件：AST 契约测试硬性要求 `services/code_graph/*.py` 内所有 structlog 调用 `category == "sampling"` |

**为什么最后一行是硬约束而不是偏好：** `tests/services/code_graph/test_access.py::test_observability_contract` 用 `package_dir.glob("*.py")` 扫全包，对每个 `logger.<level>(...)` 断言 `category` 关键字必须是字面量 `"sampling"`（`test_access.py:437-441`）。新建的 `impact.py` / `trace.py` 自动进这个 glob。CONTEXT 说「本相位工具调用属 `caller` 类」——那些事件只能落在 `mcp_tools/views.py` 与 `agents/tools/*` 里。

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| networkx | **3.6.1**（已装，`uv.lock` 传递依赖） | 反向遍历、最短路、只读视图 | `[VERIFIED: 本地 venv `python -c "import networkx; print(networkx.__version__)"` → 3.6.1]` Phase 121 的图就是它建的；本相位所有 API 已在该版本实测 |
| Python stdlib（`collections.deque` / `itertools.islice` / `dataclasses` / `enum`） | 3.14 | 分层 BFS、候选列表值对象 | 零依赖 |

### Supporting（全部已在仓）

| Module | Purpose | When to Use |
|--------|---------|-------------|
| `services.code_graph`（barrel，17 项） | 取图 + 契约类型 + 置信度函数 + 异常层级 | 内核与壳的唯一图入口（D-02） |
| `mcp_tools.views.McpToolView` | MCP 壳基类：PAT fail-closed / `_validate` / `_record` / `_get_indexed_repo` | MCP 面 |
| `agents.tools.base.tool` / `ToolResult` | 对话壳 `@tool` 注册 | 对话面 |
| `repositories.freshness_service.compute_freshness_status` | fresh/stale/unknown 三态 | staleness 声明 |
| `common.logging.redact_secrets_in_text` | 异常文本脱敏 | 所有 `error=` 埋点（AST 守护强制） |
| `interactions.models.RetrievalTrace` | MCP 链召回留痕 | MCP 壳（LOGGING-SPEC 要求） |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 手写分层反向 BFS | `nx.bfs_layers(g.reverse(copy=False), [seed])` | `bfs_layers` 给不出「经由哪条边」「path-min 置信度」，而 D-07 与逐跳渲染两条都要这些。实测两者同速（0.011 vs 0.012ms），没有性能理由选它 |
| 内联边谓词 | `nx.subgraph_view(g, filter_edge=…)` | 两者实测同速（0.013 vs 0.012ms）。`subgraph_view` 更「一处过滤」，但 impact 仍要在遍历中取边属性算 path-min，收益有限；**trace 用它更划算**（`nx.shortest_path` 需要一张「只有合格边」的图） |
| `nx.shortest_path` | `nx.bidirectional_shortest_path` | 实测 0.036 vs 0.038ms，无差别；`shortest_path` 是 CONTEXT D-18 点名的 API，照写即可 |
| — | `g.reverse(copy=True)` / `g.copy()` | ⛔ **禁止**：30k 节点 / 100k 边上实测 **498ms / 330–690ms**，比 `copy=False` 慢 5 个数量级 |

**Installation:** 无。本相位**零新增 Python 依赖**。

**Version verification:** `[VERIFIED]` `uv run python -c "import networkx; print(networkx.__version__)"` → `3.6.1`（2026-08-09，本机 server venv）。所有 `## Code Examples` 的输出均在该解释器上实跑得到。

---

## Package Legitimacy Audit

**本相位不安装任何外部包。**

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| （无） | — | — | — | — | — | N/A |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

`networkx` 已在 `server/uv.lock`，由 llama-index 传递引入，Phase 121 已作为生产依赖使用，不属于「本相位新增」，无需 slopcheck 门。

---

## Architecture Patterns

### System Architecture Diagram

```text
        MCP 客户端 (PAT)                        对话 Agent (chat_runner 白名单)
               │                                            │
               ▼                                            ▼
  ┌──────────────────────────────┐          ┌──────────────────────────────┐
  │ mcp_tools/views.py           │          │ agents/tools/graph_tools.py  │
  │  ImpactAnalysisView          │          │  @tool impact_analysis       │
  │  TraceCallPathView           │          │  @tool trace_call_path       │
  │  · _begin  → PAT fail-closed │          │  · conversation_id → user    │
  │  · _validate → Serializer    │          │  · pydantic schema 校验      │
  │  · _get_indexed_repo         │          │  · ToolResult(success/error) │
  │  · _record → ToolCallRecord  │          │  · category="caller" 埋点    │
  │            + RetrievalTrace  │          └──────────────────────────────┘
  │  · category="caller" 埋点    │                          │
  └──────────────────────────────┘                          │
               │                                            │
               └──────────────┬─────────────────────────────┘
                              ▼
             ┌────────────────────────────────────────┐
             │  共享编排层（壳内私有，两面共用）        │
             │  1. resolve_symbol()  ← uid 优先/候选   │
             │  2. get_graph(seed_symbol_ids=[uid])   │──► GraphService（Phase 121）
             │     · 三道闸每次都跑                    │    ├ ensure_repository_readable
             │     · D-24：必带种子，绕过 GraphError   │    ├ exclusion matcher (fail-closed)
             │  3. 内核调用（纯函数）                  │    ├ 签名复校 + in-flight 闸门
             │  4. 跨仓一跳（ORM，仅 impact）          │    └ 超预算 ⇒ 按需子图
             │  5. staleness（Repository 字段）        │
             │  6. 渲染（JSON / markdown 各自）        │
             └────────────────────────────────────────┘
                              │
             ┌────────────────┴──────────────────┐
             ▼                                   ▼
  ┌────────────────────────┐        ┌──────────────────────────┐
  │ code_graph/impact.py   │        │ code_graph/trace.py      │
  │ 纯函数，只吃            │        │ 纯函数                    │
  │ MultiDiGraph + params  │        │ subgraph_view(resolved)  │
  │ · 分层反向 BFS          │        │ · shortest_path          │
  │ · path-min 置信度       │        │ · all_shortest_paths 计数│
  │ · 风险分级 / 截断       │        │ · 逐跳 file:line + 边属性 │
  │ · 输出 dict（D-10）     │        │ · 无路径显式结构（D-20）  │
  └────────────────────────┘        └──────────────────────────┘

  跨仓一跳（IMPACT-03，⚠️ 不经图）:
      本仓命中的 Endpoint handler 符号
              │  ORM: Endpoint(repo, file_path, handler_name)
              ▼        → CrossRepoApiCall → ApiCallSite(repo_B, caller_file, caller_function)
      对端仓 repo_B ──► get_graph(repo_B, user=…)  ← D-12 权限复核
              │           ├ 成功 → 该仓子影响面，cross_repo: true + match_confidence 原值
              │           ├ GraphAccessDenied → 整仓折叠 REDACTED_REPOSITORY（D-12）
              └───────────┴ GraphNotIndexed/Timeout → unavailable_reason 条目（D-14）
```

### Recommended Project Structure

```text
server/
├── services/code_graph/
│   ├── __init__.py          # ⚠️ barrel 恰 17 项，有逐字断言（见 Pitfall 4）
│   ├── impact.py            # 新建：analyze_impact(graph, seeds, …) -> dict
│   ├── trace.py             # 新建：trace_path(graph, src, dst, …) -> dict
│   └── symbol_resolve.py    # 新建（可选）：图内 name → 候选节点（纯函数）
├── services/code_graph_tools.py  # 建议新建：跨仓一跳 + signature 补取 + staleness
│                                 #   （ORM 层；⛔ 不能放 code_graph/ 包内，
│                                 #    否则 AST 观测契约强制 category="sampling"）
├── mcp_tools/
│   ├── views.py             # +2 View 类
│   ├── urls.py              # +2 path()
│   └── serializers.py       # +2 请求 Serializer, +2 TOOL_SCHEMA_SNAPSHOT 条目
└── agents/
    ├── tools/graph_tools.py # 新建：2 个 @tool
    ├── tools/__init__.py    # 顶层 import 触发注册
    └── chat_runner.py       # _INDEXED_TOOL_NAMES 加两条（否则 LLM 看不到）
```

### Pattern 1: MCP 壳（copy-paste 形状）

`McpToolView`（`mcp_tools/views.py:223-401`）的完整契约，逐项核对过：

| 元素 | 规定 | 出处 |
|---|---|---|
| 基类 | `class XxxView(McpToolView)` | `views.py:223` |
| 鉴权 | 基类已定 `authentication_classes = [AccessTokenAuthentication, CookieJWTAuthentication]` + `permission_classes = [IsAuthenticated]`，⛔ 子类不要覆写 | `views.py:226-227` |
| 工具名 | 类属性 `tool_name = "impact_analysis"` | `views.py:228` |
| 入口 | `async def post(self, request: Request) -> Response` | 全部 40+ 工具同形 |
| 第 1 步 | `run, err = await self._begin(request)`；`if err: return err`；`assert run is not None` | `views.py:239-253`；内部做 `bind_source(LogSource.MCP)` + `request.auth is None` 兜底 401 |
| 第 2 步 | `input_data, err = await self._validate(XxxRequestSerializer, request)`；`if err: return err` | `views.py:255-269`；失败自动返回 `invalid_params` 400 |
| 第 3 步 | `started_at = time.perf_counter()` | 必须在业务前 |
| 仓库闸 | `repo, err = await self._get_indexed_repo(repository_id)`；`if err: return err` | `views.py:363-381`；`Repository.objects.aget(id=…, is_deleted=False)` → 404 `repository_not_found`；`index_status != INDEXED` → 400 `repository_not_indexed` |
| 分支解析 | `graph_branch, _ = await self._resolve_graph_branch(repository_id, repo, branch)` | `views.py:383-401`；返回 `None` 表示 base 分支 → 传给 `get_graph` 时转 `""` |
| 收尾 | `await self._record(run, input_data=…, output_data=…, traces=[…], started_at=started_at)` | `views.py:271-310`；内部同时写 `RequestMetric`（`route=f"mcp:{tool_name}"`）+ `ToolCallRecord` + 逐条 `RetrievalTrace` |
| 返回 | `return Response(output_data, status=status.HTTP_200_OK)`，`output_data` 必须含 `"run_id": str(run.run_id)` | 全部工具同形 |
| 错误 | `error_response(code, detail, status_code=…)`（`mcp_tools/errors.py`） | `views.py:201-206` 是 mirror 错误的映射先例 |
| 注册 | `mcp_tools/urls.py` 加 `path("tools/<name>/", XxxView.as_view(), name="mcp-tool-<dashed-name>")` | `urls.py:50-186` |
| Snapshot | `mcp_tools/serializers.py::TOOL_SCHEMA_SNAPSHOT` 加同名键，`{"request": [...], "response": [...]}` | `serializers.py:985+` |
| Snapshot 测试 | `tests/mcp_tools/test_schema_snapshot.py` 里**手写一份字面量**（⛔ 不 import 常量自比） | `test_schema_snapshot.py:8` 注释明令 |

⚠️ `test_registered_tools_match_snapshot`（`test_schema_snapshot.py:28-49`）从 `urls.py` 正则提取 `tools/([a-z0-9_]+)/` 并断言 == snapshot 键集。**漏掉 snapshot 或 URL 任一边 CI 立刻红。**

参考最短的一个完整实现：`ReverseLookupView`（`views.py:1213-1261`，49 行含 docstring）。

### Pattern 2: 对话壳（`@tool`）

`agents/tools/base.py:90-185` 的 `tool` 装饰器：

- 被装饰函数**必须 `async def`**，否则装饰时 `TypeError`（`base.py:136-140`）。
- 重名注册 `ValueError`（`base.py:143-147`）——注册表是模块级 `_tool_registry` 字典。
- `category` 从 `ToolCategory` 枚举取；本相位建议 `"RETRIEVAL"`（`analyze_repository_relevance` 同档）或 `"PROJECT"`（`list_endpoints` / `find_api_callers` 同档）。
- `parameters` 是手写 JSON Schema dict（`{"type":"object","properties":{…},"required":[…]}`）。
- **返回 `ToolResult(success=bool, output=…, error=…)`，永不冒泡异常**——`list_endpoints.py:92-113` 是双层防御的标准形状：外层 `try` 捕 `(ValueError, TypeError, DjangoValidationError)` 与 `pydantic.ValidationError`，各自 `logger.warning` 后转 `ToolResult(success=False, error=…)`。
- `ToolResult.to_content()`（`base.py:50-66`）把 dict 序列化成 JSON 喂 LLM；`success=False` 时输出 `f"Error: {error}"`。
- **注册路径**：在 `agents/tools/__init__.py` 顶层 `import`（`__init__.py:12-54`）+ 加进 `__all__`。
- 🚨 **还要加进 `agents/chat_runner.py::_INDEXED_TOOL_NAMES`**（`chat_runner.py:86-124`）——注册 ≠ 暴露。`chat_runner.py:95-96` 的注释就是这条债的现场记录：「这些工具早已在 `agents/tools/__init__.py` 注册，此前漏挂进 chat 白名单导致 LLM 全程只能 RAG 搜索」。

### Pattern 3: 与 MCP 侧的四点差异（D-21「不许分叉」要防的正是这些）

| 维度 | MCP 壳 | 对话壳 |
|---|---|---|
| 用户来源 | `request.user`（PAT / Cookie JWT） | `conversation_id` → `_resolve_conversation_user()`（`agents/tools/delivery_knowledge_tools.py:56`，`knowledge_read_tools.py:27` 复用同一个） |
| 参数校验 | DRF `Serializer` | 手写 JSON Schema + pydantic 模型（`agents/tools/schemas/`） |
| 错误面 | `error_response(code, detail, status)` HTTP 码 | `ToolResult(success=False, error=str)`，HTTP 概念不存在 |
| 留痕 | `_record()` 写 `ToolCallRecord` + `RetrievalTrace` + `RequestMetric` | 由 chat runner 统一记，工具自身只 `logger.info` |
| 渲染 | JSON dict | 建议 markdown 字符串塞进 `output`（LLM 更好读），但**数据必须同源** |

**落地建议：** 把「解析符号 → 取图 → 调内核 → 跨仓一跳 → 附 staleness」这五步做成一个 `async def run_impact(repository_id, symbol, *, user, …) -> dict` 的共享编排函数，放 `services/code_graph_tools.py`。两个壳各自只写 ~40 行（校验 + 调它 + 渲染 + 留痕）。这是唯一能机械保证「两面不漂移」的形状——可以写一条测试断言两面对同一输入产出的 `data` 段逐字节相同。

### Pattern 4: 跨仓穿越（IMPACT-03 的唯一可行路径）

🚨 **不要沿图边穿仓。** `loader._load_cross_repo_edges`（`loader.py:791-844`）的逻辑：

```python
caller_node = _resolve_by_file_and_name(...) if str(call_site_repository_id) == local_repository_id else None
callee_node = _resolve_by_file_and_name(...) if str(endpoint_repository_id) == local_repository_id else None
if caller_node is None or callee_node is None:
    unresolved_count += 1
    continue
```

一条边只在**两端都属于本仓**时才 `add_edge`。因此图里 `kind == "cross_repo"` 的边全部是「本仓前端调本仓后端」这种同仓 API 调用；**真正跨仓的行 100% 进 `cross_repo_unresolved_count`，永远不入图**。`loader.py:751-754` 的注释也写明了这点：「跨仓 impact 由 Phase 122 通过『按需再取对端仓的图』组合」。

正确形状（放壳层 / `services/code_graph_tools.py`，ORM）：

```python
# 方向：本仓被改的 Endpoint handler → 别的仓里调用它的 ApiCallSite
# 输入：本仓命中的符号（需要 file_path + name，图节点属性里都有）
rows = (
    CrossRepoApiCall.objects
    .filter(
        endpoint__repository_id=local_repo_id,
        endpoint__file_path=symbol_file_path,
        endpoint__handler_name=symbol_name,
    )
    .exclude(call_site__repository_id=local_repo_id)   # 只要真跨仓的
    .values_list(
        "call_site__repository_id",
        "call_site__caller_file",
        "call_site__caller_function",
        "call_site__line_number",
        "match_confidence",
    )
)
# 按 call_site__repository_id 分组 → 对每个对端仓：
#   await get_graph(peer_repo_id, user=user, seed_symbol_ids=[…])   ← D-12 权限每仓复核
#   GraphAccessDenied  → {"repository": REDACTED_REPOSITORY, "count": n}     (D-12)
#   GraphNotIndexed / GraphBuildTimeout / GraphError
#                      → {"repository_id": …, "unavailable_reason": "..."}   (D-14)
```

对端符号的定位仍要靠 `(caller_file, caller_function)` → `Symbol` 二次解析（与 loader 同口径，`normalize_rel_path` 归一），命中不上就计数不丢——⛔ 别造虚拟节点（Phase 121 D-05）。

⚠️ `max_cross_repo_hops` 默认 1（D-11）意味着这段代码只跑一层，**不递归**。

### Anti-Patterns to Avoid

- **`g.copy()` / `g.reverse(copy=True)`** — 30k/100k 图上 330–690ms / 498ms，比只读视图慢 5 个数量级。冻结图只需 `reverse(copy=False)`（0.004ms）或 `subgraph_view`（0.013ms）。
- **`list(nx.bfs_layers(...))[:d]`** — `bfs_layers` 是生成器，`list()` 先物化整个可达分量（Phase 121 实测 97.3ms vs 0.0ms）。要用 `itertools.islice`。
- **在 `services/code_graph/*.py` 里发 `category="caller"` 的日志** — AST 契约测试硬拒。
- **在内核里 `import` 任何 Django / ORM 符号** — 破 D-01，也破「合成图毫秒级回归」的前提。
- **共享 `_emit()` 日志 helper** — AST 测试要求事件名是**该调用点**静态可解析的字面量或模块级 `Final[str]`；包一层就不可解析（D-04 明写 Phase 121 有四个 plan 各踩过一次）。
- **`from services.code_graph import loader`** — 现在会被守护抓到（121 验证后已补 `ImportFrom.names` 分支）。
- **catch `GraphError` 返回空结果** — D-03；空影响面 = 「改这里没影响」的致命误导。

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 反向邻接 | 自建 `dict[node, list[pred]]` | `g.predecessors(n)` / `g.reverse(copy=False)` | MultiDiGraph 自带 `_pred`，视图零成本；自建索引会与冻结图不同步 |
| 按边属性筛子图 | 遍历后 `g.copy()` 再 `remove_edges_from` | `nx.subgraph_view(g, filter_edge=…)` | 冻结图不能改；copy 要 300ms+。`subgraph_view` 惰性、保 `is_multigraph()`、结果仍冻结 |
| 最短路 | 自写 BFS 回溯 | `nx.shortest_path` / `nx.all_shortest_paths` / `nx.bidirectional_shortest_path` | MultiDiGraph 已支持；`all_shortest_paths` 直接回答 D-18 的「N 条等长路径」 |
| 置信度数值映射 | 自己写 `{"resolved": 1.0, …}` | `services.code_graph.confidence_score()` | `cross_repo` 档必须传 `match_confidence`，缺参**故意抛 `ValueError`**（`model.py:121-126`）；自己写会静默把跨仓可信度抹成常量 |
| reason 文案 | 自己拼字符串 | `services.code_graph.derive_reason()` | D-09；四档文案已定型，两处各写一份必然漂移 |
| 「落后 N commits」 | `git rev-list --count` 子进程 | `Repository.behind_commits` 字段 | 已由 `update_behind_commits_for_stale_repos()` 定时任务算好（`freshness_service.py:43-73`）；生产 258/258 全覆盖。请求路径起 git 子进程是 30s+15s 超时的两次 `create_subprocess_exec` |
| fresh/stale 判定 | 自己比 sha | `freshness_service.compute_freshness_status(repo)` | 三态决策表已定（含 `remote_head_checked_at is None` → unknown 这条容易漏） |
| exclusion 过滤 | 在 impact 输出里再过一遍 | 什么都不做 | Phase 121 已在**装配阶段**过滤（`loader.py:401`），被排除符号根本不在图里。输出阶段再过是多余的，且会给人「这里也管」的错觉 |
| 权限校验 | 壳里自己查 `Repository` 可见性 | `get_graph(user=…)` 每次都跑 `ensure_repository_readable` | D-12；`access.py` 是唯一收口点，四道判定（UUID 合法性 / 存在性与软删 / 未索引 / ACL 扩展点） |
| 异常文本脱敏 | `str(exc)` 直接进日志 | `redact_secrets_in_text(str(exc))` | AST 契约测试对 `error=` 关键字做 `ast.unparse` 子串检查（`test_access.py:444-449`） |

**Key insight:** 本相位几乎所有「看起来要写的东西」在 Phase 121 或既有壳层里都已经有了。真正需要新写的只有三块纯逻辑：分层反向 BFS + path-min、风险分级表、跨仓一跳的 ORM 查询。其余全是接线。

---

## Common Pitfalls

### Pitfall 1: 🚨 IMPACT-03 在当前图上无法实现，且生产零样本

**What goes wrong:** planner 按 CONTEXT 字面「沿 `CrossRepoApiCall` 边跨出本仓」写任务，执行方在图里找 `kind == "cross_repo"` 的边、发现它们全是同仓边，或者更糟——找到了几条同仓边就当跨仓边处理，输出「跨仓影响面」实际上全在本仓。

**Why it happens:** `EdgeKind.CROSS_REPO` 这个名字暗示它跨仓，但 `_load_cross_repo_edges` 的实现（`loader.py:812-828`）要求两端都在本仓。这是 Phase 121 刻意的正确设计（拿对端仓的 `(file_path, name)` 撞本仓索引会造伪边，`loader.py:804-811` 有长注释），但**结果就是真跨仓边一条都不在图里**。

**How to avoid:**
1. IMPACT-03 走 ORM 直查（`## Architecture Patterns` Pattern 4），不走图遍历。
2. 在 impact 输出里把 `cross_repo_unresolved_count`（D-23 已要求透出）与「本次穿仓查到 N 条」并列——前者是「装配时丢了多少」，后者是「本次 ORM 查到多少」，两个不同的数。
3. 写一条回归断言：图里任何 `kind == "cross_repo"` 的边，两端节点必须都在本仓图内（即：不要在这些边上做 `cross_repo: true` 标记）。

**Warning signs:** impact 输出里 `cross_repo: true` 的条目，其 `repository_id` 与查询仓相同。

**生产数据（🚨 决定这条要不要现在做）** `[VERIFIED: 生产 PostgreSQL 只读聚合，2026-08-09]`：

| 表 | 生产行数 |
|---|---|
| `codegraph_endpoint` | **6,014**（覆盖 117 个仓） |
| `codegraph_apiwrapper` | **0** |
| `codegraph_apicallsite` | **0** |
| `codegraph_crossrepoapicall` | **0** |
| 已索引仓库（`index_status='indexed'`, 未删） | 258 |

跨仓链路的上游产出器完全没跑：`ApiWrapper` 检测依赖 volar LSP（前端侧），而 server 镜像目前无 Node（`.planning/research/SUMMARY.md` STACK 段：「当前 `python:3.14-slim` 无 Node 无 Go」）——这正是 LSP-01 / Phase 127 要修的。**IMPACT-03 可以实现并用合成数据完整测试，但在今天的生产环境上必然返回 0 条跨仓结果。** 这一点必须写进 SUMMARY，且不得表述成「跨仓 impact 已上线可用」。

121-10 说「跨仓边二次解析命中率未测，样本不足」——本次查证给出了更硬的答案：**不是样本不足，是样本为零**，且 `ApiCallSite`/`ApiWrapper` 也为零，所以命中率这个数在 Phase 127 之前根本不可测。建议 planner 把「测跨仓解析命中率」这条从本相位移出，改为一条明确的上游依赖记账。

---

### Pitfall 2: 重名不是边缘分支，是五分之一的主路径

**What goes wrong:** D-19 的候选列表被当作「万一撞名了的兜底」，实现得草率（不带 `signature`、不排序、不限条数），结果 agent 拿到 20 个候选无从选择。

**生产数据** `[VERIFIED: 生产 PostgreSQL，base 分支符号 562,465 行]`：

| `(repository_id, name)` 对应的符号数 | distinct 名字数 | 占比 |
|---|---|---|
| 1（唯一） | 163,630 | 80.7% |
| 2 | 17,710 | 8.7% |
| 3–5 | 12,987 | 6.4% |
| 6–20 | 5,898 | 2.9% |
| >20 | 2,436 | **1.2%** |
| **合计 distinct (repo, name)** | **202,661** | — |

**19.3% 的名字在仓内不唯一。** 更进一步：连 `(repository_id, file_path, name)` 三元组都还有 **24,312** 组冲突（同文件同名多符号，典型是不同 class 的同名 method）——这正是 Phase 121 `_AMBIGUOUS` 哨兵要处理的情况（`loader.py:424-431`），命中它时 `_resolve_by_file_and_name` 直接返回 `None`。

**How to avoid:**
1. `symbol_id`（UUID）优先，agent 拿到过一次候选列表后就该带 uid 回来。
2. 候选列表**必须限条数**（建议 20，超出给 `total_candidates` 计数），按 `(file_path, start_line)` 稳定排序。
3. 候选条目要 `symbol_id` / `name` / `symbol_type` / `file_path` / `start_line` / `signature`。⚠️ **`signature` 不在图节点属性里**——`loader.py:354-356` 明确不取（TextField 可达数 KB）。要它就得对候选 uid 做一次 `Symbol.objects.filter(id__in=…).values_list("id","signature")`，这是 ORM，必须放壳层/`code_graph_tools.py`，不能放内核（D-01）。截断 `signature` 到 200 字符（token 纪律，D-17 同理）。
4. `symbol_type` 与 `file_path` 支持作为消歧**输入参数**（`symbol="Handler", file_path="internal/api/user.go"`），能一次收敛就不要往返两轮。

---

### Pitfall 3: 🚨 加两个 MCP 工具会撞上一条已经红着的 CI 守护

**What goes wrong:** CONTEXT 把「`mcp` npm 包的客户端条目」列为 OUT OF SCOPE，但 `tests/mcp_tools/test_mcp_package_alignment.py::test_mcp_package_tools_match_server_snapshot` 断言 `mcp/src/tools.ts` 的工具名集合与 `TOOL_SCHEMA_SNAPSHOT` **双向相等**。

**现状** `[VERIFIED: 本机实跑 2026-08-09]`：

```
FAILED tests/mcp_tools/test_mcp_package_alignment.py::test_mcp_package_tools_match_server_snapshot
  服务端有、包缺失：['apply_repo_association', 'generate_requirement_spec',
                    'get_repo_research', 'route_blueprint_repos', 'start_repo_research']
```

- 这条测试**在 HEAD 上已经是红的**（5 项漂移，来自 commit `d08a3e90` 的阶段沙箱工具，与本相位无关）——121-10 的相位门也记录了同一条失败。
- `mcp/` 是 git submodule（`.gitmodules`），**本机已 checkout**，且 **CI 明确 `submodules: recursive`**（`.github/workflows/ci.yaml:59, 205`），所以 CI 上这条也会跑、不会 skip。
- 本相位加 2 个工具会把漂移从 5 项变成 7 项。

**How to avoid:** planner 必须在计划里显式选一条，⛔ 不许默认「反正已经红了」：

1. **同批改 submodule**（在 `mcp/src/tools.ts` 的 `FRIDAY_TOOLS` 加两条）—— 与 CONTEXT 的 OUT OF SCOPE 冲突，但只需两条 `name: '...'` 条目；且顺手能把已有的 5 项补齐，把这条守护从红变绿。
2. **在 SUMMARY 里如实记账**「本相位使既有失败从 5 项扩大到 7 项，npm 包补齐另批发版」——诚实但让红灯继续红。
3. **不做**，并在相位门里把这条列进「已知既有失败」白名单。

**顺带核实的两条不会撞：**
- `test_skills_snapshot_guard.py` 的工具名正则只认 `(search|create|get|list|execute|improve|analyze|summarize|route|find|grep|read|report|lookup|reverse|update|confirm|answer|apply|generate|start)_` 开头的 token；`impact_*` / `trace_*` 不在其中，且它做的是「skills 文档 ⊆ snapshot」的子集检查，加工具不会让它红。
- `test_registered_tools_match_snapshot`（urls ↔ snapshot）**会**红，但那是本相位自己该做的事（两边都加即可）。

---

### Pitfall 4: barrel 的 17 项有逐字断言，加不加要想清楚

**What goes wrong:** 想把 `analyze_impact` / `trace_path` 从 `services/code_graph/__init__.py` 导出，改了 `__all__`，`test_barrel_exports_only_public_surface` 立刻红（`test_access.py:511-533`：`assert len(exported) == 17` + `set(exported) == _EXPECTED_BARREL_EXPORTS` 逐字集合 + 字母序断言）。

**注意这不是 bug，是刻意设计**：注释写着「⛔ 绝不从 `__all__` 反查——从模块自身反查出期望值的用例是自证的」。

**How to avoid（两条都可行，选一条并写进 plan）：**
- **A（推荐）：不进 barrel。** 壳层写 `from services.code_graph.impact import analyze_impact`。合法性已核实：`test_no_upper_layer_imports_internal_submodules` 的 `_INTERNAL_SUBMODULES = {"loader", "cache", "signature", "access"}`（`test_access.py:545`）**不含 `impact` / `trace` / `symbol_resolve`**，所以直连不算违规。语义上也对——那四个是「绕过三道闸的通路」，新内核不是。
- **B：进 barrel。** 同批把 `_EXPECTED_BARREL_EXPORTS` 与 `== 17` 改成 19（保持字母序），并在测试注释里写明本次扩容的理由。

⚠️ 无论选哪条，**取图仍必须经 `get_graph_service()`**（D-02 的实质），别把「内核可以直连」误读成「图可以直连」。

---

### Pitfall 5: D-24 的超预算分支：种子必须真的传下去

**What goes wrong:** 壳层调 `get_graph(repository_id, branch, user=user)` 忘了 `seed_symbol_ids`，在超预算大仓上直接吃 `GraphError`（`cache.py:970-981`），agent 看到「本仓超出单图内存预算」这种内部消息。

**How to avoid:**
1. 解析符号 → 拿到 `symbol_id` → **必须**作为 `seed_symbol_ids=[symbol_id]` 传下去，并把 `depth=max_depth` 一并传（`cache.py:727`：缺省 2，而 impact 默认 `max_depth=3`，不传会让子图边界比遍历深度浅一层）。
2. `load_subgraph` 内部按 `radius = depth + 1` 扩张（`loader.py:1127`），已经替你多留了一跳，但前提是你传对了 `depth`。
3. `depth` 会被 `_clamped_depth` 钳到 `[0, _MAX_SUBGRAPH_DEPTH]`。`[VERIFIED: cache.py:98 `_MAX_SUBGRAPH_DEPTH = 10`，:93 `_DEFAULT_SUBGRAPH_DEPTH = 2`]` —— 10 ≥ 3，`max_depth=3` 不会被削；但**缺省是 2**，不传 `depth` 就会让子图边界比遍历深度浅一层，d3 会莫名残缺。
4. ⚠️ **子图路径不进缓存也不进 single-flight**（`cache.py:833-839`）。这意味着大仓上每次 impact 都要重新装配一次子图；同时它绕过了 single-flight，并发查询会各建各的。这是已知设计，不是缺陷，但**性能特性与小仓完全不同**，验收时要分开量。
5. ⚠️ **子图路径上 `_expand_seed_ids` 只沿 `CallEdge` 扩张**（`loader.py:1011-1015`），不沿 `CrossRepoApiCall`——但那本来也不跨仓（Pitfall 1），所以实际不影响；只是别指望子图里的 `cross_repo` 边邻接完整。

---

### Pitfall 6: 热点符号的 fan-in 会撑爆输出

**生产数据** `[VERIFIED: 生产 PostgreSQL，`codegraph_calledge` 1,585,137 行]`：

| 指标 | 中位数 | p99 | 最大值 |
|---|---|---|---|
| 已解析 callee 的入度（= impact d1 规模） | 1 | 25 | **2,803** |
| caller 的出度 | 4 | 54 | **3,613** |
| 解析边占比 | 298,216 / 1,585,137 = **18.8%** | | |

d1 就能到 2,803 条 → d2/d3 是指数级。**D-16 的 200 条截断在热点符号上必然触发**，`summary` 的 `total_found` / `returned` / `truncated_by_depth` 三个计数不是可选项。

**How to avoid:**
1. 遍历本身也要有预算，不只是输出截断：建议除 `max_depth=3` 外加一个 `max_nodes`（如 2,000）软上限，撞上时置 `truncated_by_nodes` 标记（PITFALLS.md Pitfall 4 的三重预算纪律）。⚠️ 这是 CONTEXT 未覆盖的空白，属 Claude's Discretion 范围，建议做。
2. 排序键（D-16「深度升序 + 置信度降序」）要在截断**之前**算完，否则截掉的可能是最该看的。
3. `include_content` 默认关（D-17）在这个量级上是生命线：2,803 条 × 一段源码 = 上下文爆炸。

---

### Pitfall 7: `low_resolution` 布尔量在本仓等于没有信息

121-10 的硬要求，复述以防漏：本仓解析率 **p50 = 0.17**（218 仓样本；本次复算全库 = 18.8%），全库最高 0.56。阈值校准到 0.10 后 `low_resolution` 命中 38/218。**没有任何一个仓「解析得好」。**

因此输出必须**始终**带数值 `resolution_rate` 与保守性声明（如「本仓约 81% 的调用边未解析到具体符号，影响面结论偏保守」），⛔ 不得只在 `low_resolution == True` 时才提醒。

### Pitfall 8: 高频调用的日志与 RetrievalTrace 纪律

AI agent 一次任务可能调几百次 impact。PITFALLS.md Pitfall 8 §3 与 LOGGING-SPEC 的要求：

- 工具级一次调用 = 一条 `caller` 事件 + 一条 `RetrievalTrace`（记「查询符号 + 结果计数 + 置信度分布」，⛔ 不整体复制结果集）。
- BFS 内部逐节点 ⛔ 绝不 INFO；内核事件一律 `category="sampling"` + DEBUG（AST 契约已强制 `sampling`，级别靠自律）。
- MCP 壳的 `_record()` 已自动写 `RequestMetric`（QPS/错误率/时长），不需额外做。

---

## Code Examples

> 以下全部在本机 `server/.venv`（CPython 3.14 / networkx 3.6.1）实跑验证，输出即实测结果。

### 1. 冻结 `MultiDiGraph` 上的反向遍历（IMPACT-01 内核骨架）

```python
# [VERIFIED: 本机实测 2026-08-09, networkx 3.6.1]
# 冻结图上 reverse(copy=False) / predecessors / bfs_layers / subgraph_view 全部可用。
#
#   nx.is_frozen(g)                     -> True
#   r = g.reverse(copy=False)           -> MultiDiGraph, is_frozen(r) == True, 0.004ms
#   r.add_edge(...)                     -> NetworkXError: Frozen graph can't be modified
#   list(nx.bfs_layers(r, ["D"]))       -> [['D'], ['C', 'A'], ['B']]
#   list(g.predecessors("D"))           -> ['C', 'A']
#
# 30,000 节点 / 100,000 边上的耗时（min of 5）：
#   g.reverse(copy=False)               0.004 ms   ← 只读视图
#   g.reverse(copy=True)              498     ms   ← ⛔ 12 万倍
#   g.copy()                          326–690 ms   ← ⛔
#   bfs_layers d3 on reverse view       0.011 ms
#   手写 predecessors + 内联过滤 d3      0.012 ms   ← 同速，且能带出边信息

from collections import deque
from services.code_graph import EdgeConfidence, confidence_score, derive_reason

def _edge_score(attrs: dict) -> float:
    """一条边的置信度数值。cross_repo 档必须带 match_confidence（否则 ValueError）。"""
    conf = EdgeConfidence(attrs["confidence"])
    if conf is EdgeConfidence.CROSS_REPO:
        return confidence_score(conf, match_confidence=attrs["match_confidence"])
    return confidence_score(conf)


def reverse_layers(graph, seed_id: str, *, max_depth: int, min_confidence: float):
    """分层反向 BFS。返回 {node_id: (depth, path_min_confidence, via_edge_attrs)}。

    - 最浅深度优先（D-05）：BFS 天然保证首次访问即最浅层。
    - path_min（D-07）：同一层内取「各条到达路径的 min 之最大值」——先按层扩展，
      层内对每个候选取 max(min(前驱 path_min, 边分值))，即经典 widest-path 的
      层受限形式。
    - ⛔ 不用 nx.bfs_layers：它只给节点，给不出经由哪条边、path_min 是多少。
    """
    best: dict[str, tuple[int, float, dict]] = {seed_id: (0, 1.0, {})}
    frontier = deque([seed_id])
    for depth in range(1, max_depth + 1):
        nxt: dict[str, tuple[float, dict]] = {}
        while frontier:
            node = frontier.popleft()
            node_min = best[node][1]
            for pred in graph.predecessors(node):
                if pred in best:            # 已在更浅层出现过 → 最坏情况优先，跳过
                    continue
                # MultiDiGraph：同一对符号间可能并存多档边，逐条取分值。
                for attrs in graph[pred][node].values():
                    score = _edge_score(attrs)
                    if score < min_confidence:
                        continue            # D-06/D-08：不合格边不参与扩散
                    cand = min(node_min, score)
                    prev = nxt.get(pred)
                    if prev is None or cand > prev[0]:
                        nxt[pred] = (cand, attrs)
        for pred, (path_min, attrs) in nxt.items():
            best[pred] = (depth, path_min, attrs)
        frontier = deque(nxt)
        if not frontier:
            break
    return best
```

渲染每条时用 `derive_reason(EdgeKind(attrs["kind"]), EdgeConfidence(attrs["confidence"]), callee_name=…, match_confidence=attrs.get("match_confidence"))`（D-09）；`file:line` 取 `graph.nodes[nid]["file_path"]` + `graph.nodes[nid]["start_line"]`，边上的 `line_number` 是调用点行号。

### 2. `min_confidence` 的另一种落地：`subgraph_view`（trace 用它更划算）

```python
# [VERIFIED: 本机实测 2026-08-09]
#   sv = nx.subgraph_view(g, filter_edge=keep)   -> 0.013 ms 建视图
#   nx.is_frozen(sv)         -> True
#   sv.is_multigraph()       -> True
#   sv.reverse(copy=False)   -> 可组合，边正确反向
#   ⚠️ filter_edge 对 MultiDiGraph 的签名是 (u, v, k) 三参
#   ⚠️ 即便在 reverse 视图上遍历，filter_edge 仍以**原始方向** (u, v, k) 被调用
#      （实测：rv.edges 触发的谓词入参是 ('A','B',0)，不是 ('B','A',0)）
#   ⚠️ filter_node 会连带隐藏其所有邻接边

import networkx as nx

def resolved_only_view(graph):
    """D-18：trace 默认只走 resolved 边。"""
    def keep(u, v, k):
        return graph.edges[u, v, k]["confidence"] == "resolved"
    return nx.subgraph_view(graph, filter_edge=keep)
```

### 3. trace 最短路 + 等长路径计数（IMPACT-05 / D-18 / D-20）

```python
# [VERIFIED: 本机实测 2026-08-09]
#   nx.shortest_path(multidigraph, "A", "D")        -> ['A', 'D']        (0.038 ms @30k/100k)
#   list(nx.all_shortest_paths(g, "A", "D"))        -> [['A', 'D']]
#   nx.shortest_path(subgraph_view, "A", "D")       -> NetworkXNoPath    (视图过滤生效)
#   nx.bidirectional_shortest_path(g, …)            -> 0.036 ms（无实质差异）
# ⚠️ shortest_path 返回的是**节点序列**，不含边 key。MultiDiGraph 上并存多档边时，
#    逐跳渲染必须自己在 g[u][v] 里挑一条（建议挑置信度最高的那条）。
# ⚠️ all_shortest_paths 数的是**节点序列**的条数，不是边组合数。它是生成器，
#    在高扇出图上可能极多——必须 islice 封顶。

import itertools
import networkx as nx

def trace_path(graph, src: str, dst: str, *, min_confidence: float, alt_cap: int = 10):
    view = resolved_only_view(graph)  # 或按 min_confidence 构造谓词
    try:
        path = nx.shortest_path(view, src, dst)
    except nx.NetworkXNoPath:
        return {"found": False, "reason": "no_path", "min_confidence": min_confidence,
                "source": src, "target": dst}          # D-20：显式结构，不是空数组
    except nx.NodeNotFound as exc:
        return {"found": False, "reason": "node_not_in_graph", "detail": str(exc)}

    # D-18：声明等长路径条数，但要封顶（生成器可能极多）
    alts = sum(1 for _ in itertools.islice(nx.all_shortest_paths(view, src, dst), alt_cap + 1))
    hops = []
    for u, v in zip(path, path[1:]):
        # 并存多档边时挑置信度最高的一条渲染
        attrs = max(view[u][v].values(), key=_edge_score)
        hops.append({
            "from": u, "to": v,
            "file": graph.nodes[u]["file_path"],
            "line": attrs["line_number"],
            "kind": attrs["kind"],
            "confidence": attrs["confidence"],
        })
    return {"found": True, "path": path, "hops": hops,
            "equal_length_path_count": alts,
            "equal_length_path_count_capped": alts > alt_cap}
```

### 4. staleness（D-22，零 git 调用）

```python
# [VERIFIED: 生产 258/258 个已索引仓库的 behind_commits / remote_head_sha /
#            last_indexed_commit_sha 三个字段全部非空；当前全部 fresh(behind=0)]
from repositories.freshness_service import compute_freshness_status

def staleness_payload(repo) -> dict:
    status = compute_freshness_status(repo)          # fresh / stale / unknown
    out = {
        "as_of": repo.last_indexed_commit_sha or "",
        "freshness": status,
        # behind_commits 由 update_behind_commits_for_stale_repos() 定时任务算好，
        # ⛔ 不在请求路径跑 git（那是两次 create_subprocess_exec + 30s/15s 超时）。
        "behind_commits": repo.behind_commits,        # None ⇒ 未知，降级为只报 as_of（D-22）
        "behind_commits_calculated_at": (
            repo.behind_commits_calculated_at.isoformat()
            if repo.behind_commits_calculated_at else None
        ),
    }
    return out
```

⚠️ `behind_commits` 只由 `update_behind_commits_for_stale_repos()` 对 `auto_index_enabled=True` 且 `stale` 的仓刷新（`freshness_service.py:49-58`），且 `_calculate_commit_distance` 在**本地无 clone 时返回 `None`**（`freshness_service.py:88-94`）。所以 `None` 是真实存在的分支，D-22 的降级路径必须实现，⛔ 不能默认它总有值。

### 5. 合成图 fixture（Claude's Discretion 里的推荐做法）

```python
# 已知拓扑，深度分组与最短路都可逐点核对。零 DB、零 Django。
# 内核测试用它就能跑毫秒级回归（D-01 的全部意义所在）。
import networkx as nx

def known_topology() -> nx.MultiDiGraph:
    """
        E ──resolved──▶ B ──resolved──▶ A          (A 的 d1={B}, d2={E,C})
        C ──bare_name─▶ B
        D ──resolved──▶ C ──resolved──▶ A          (C 同时是 d1 和 d2 ⇒ 取最浅 d1)
        F ──cross_repo(0.7)──▶ A
        A ──resolved──▶ G                          (下游，反向遍历不应看到)
        H（孤立）
    """
    g = nx.MultiDiGraph()
    for n, f, ln in [("A","pkg/a.go",10), ("B","pkg/b.go",20), ("C","pkg/c.go",30),
                     ("D","pkg/d.go",40), ("E","pkg/e.go",50), ("F","web/f.ts",60),
                     ("G","pkg/g.go",70), ("H","pkg/h.go",80)]:
        g.add_node(n, name=n.lower(), symbol_type="FUNCTION",
                   file_path=f, start_line=ln, end_line=ln + 5)
    g.add_edge("B","A", kind="call", confidence="resolved",  line_number=21)
    g.add_edge("E","B", kind="call", confidence="resolved",  line_number=51)
    g.add_edge("C","B", kind="call", confidence="bare_name", line_number=31)
    g.add_edge("C","A", kind="call", confidence="resolved",  line_number=32)
    g.add_edge("D","C", kind="call", confidence="resolved",  line_number=41)
    g.add_edge("F","A", kind="cross_repo", confidence="cross_repo",
               line_number=61, match_confidence=0.7)
    g.add_edge("A","G", kind="call", confidence="resolved",  line_number=11)
    nx.freeze(g)          # 🚨 fixture 也要冻结：内核若就地改图，测试必须当场红
    return g
```

可点检的断言：
- `min_confidence=1.0`（只 resolved）：A 的 d1 = {B, C}，d2 = {E, D}，F **不在**（0.7 < 1.0）。
- `min_confidence=0.7`：F 进 d1，`path_min == 0.7`。
- `min_confidence=0.3` + `include_low_confidence=True`：C→B 的 bare_name 边生效，但 C 已在 d1（最浅优先），不会重复出现在 d2。
- `trace(D → A)` 只走 resolved：`['D','C','A']`，`equal_length_path_count == 1`。
- `trace(E → A)`：`['E','B','A']`。
- `trace(H → A)`：`NetworkXNoPath` → D-20 的显式无路径结构。
- G 永不出现在任何 impact 结果里（方向纪律）。

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `DiGraph` + 单档边 | `MultiDiGraph` + 四档 `EdgeConfidence` | Phase 121 D-01 | 同一符号对并存多档边；遍历时必须 `for attrs in g[u][v].values()`，⛔ 不能 `g[u][v]` 当单个 dict 用 |
| 图可变、上层随手改 | 出图一律 `nx.freeze` | Phase 121（`cache.py:1025`） | 任何就地修改抛 `NetworkXError`；`copy=False` 视图不受影响 |
| `LOW_RESOLUTION_THRESHOLD = 0.6` | `= 0.10`（218 仓分位数校准） | 121-10 | 0.6 命中 218/218，是永远触发的失效信号 |
| `NODE_COST=640 / EDGE_COST=560`，256MB ≈ 11 万符号 | `800 / 680`，256MB ≈ **8.6 万符号** | 121-10 生产实测 | 当前最大仓 3 万符号，不触发降级 |
| 超预算自动降级 | 超预算 + 无种子 ⇒ **抛 `GraphError`** | Phase 121（`cache.py:970-981`） | D-24：本相位必须传种子 |

**Deprecated/outdated:**
- 「沿 `CrossRepoApiCall` 边跨出本仓」这个说法（在 REQUIREMENTS / SUMMARY / CONTEXT 里反复出现）—— 对当前图实现**不成立**，见 Pitfall 1。

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| ~~A1~~ | ~~`_MAX_SUBGRAPH_DEPTH ≥ 3`~~ | Pitfall 5 | **已核实，撤销**：`cache.py:98` = 10。但缺省 `_DEFAULT_SUBGRAPH_DEPTH = 2`（:93）——壳层**必须显式传 `depth`**，否则 d3 残缺 |
| A2 | 生产 `CrossRepoApiCall = 0` 的根因是 volar/Node 缺失导致 `ApiWrapper` 检测未跑 | Pitfall 1 | 有强旁证（`ApiWrapper` 也为 0；SUMMARY 记载镜像无 Node）但未直接验证。若根因是别的（如 offline join 任务从未调度），Phase 127 修了 LSP 也不会有数据 |
| A3 | 新工具名建议 `impact_analysis` / `trace_call_path`（SUMMARY.md Phase 2 段的措辞） | 全文 | 纯命名，无技术风险；但一旦定下会进 snapshot、skills、npm 包三处，改名成本非线性 |
| A4 | 对话壳的用户解析走 `_resolve_conversation_user(conversation_id)` | Pattern 3 | 已核实该函数存在且被 4 处复用（`delivery_knowledge_tools.py:56`），但未核实它对「会话无 owner」的返回语义；`get_graph(user=None)` 会走系统路径埋点记 `system`，可能不是期望的 fail-closed |
| A5 | `max_nodes` 软上限（建议 2,000）是必要补充 | Pitfall 6 | CONTEXT 未要求，属 Discretion。不做的风险是热点符号上遍历本身（而非输出）撑爆延迟 |

---

## Open Questions

1. **IMPACT-03 在零生产样本下如何验收？**
   - 已知：`CrossRepoApiCall` / `ApiCallSite` / `ApiWrapper` 生产均为 0 行；`Endpoint` 有 6,014 行。上游产出器依赖 volar LSP，归 Phase 127。
   - 不清楚：产品上是否接受「实现 + 合成数据测试 + 显式声明生产无数据」。
   - 建议：**接受**，但把三件事写死——(a) 合成数据覆盖全部四条分支（成功穿仓 / 权限拒 → `REDACTED_REPOSITORY` / 未索引 → `unavailable_reason` / 解析不上 → 计数）；(b) SUMMARY 明写「本能力在当前生产环境返回 0 条，因上游 `ApiWrapper` 抽取未启用（LSP-01 / Phase 127）」；(c) ROADMAP 记一条「Phase 127 落地后回来实测跨仓解析命中率」的账。⛔ 不得在验收里写「跨仓 impact 已可用」。

2. **`mcp` npm 包对齐守护怎么处理？**（Pitfall 3）
   - 三个选项已列，需要人选。推荐选项 1（顺手把 5+2 项一起补齐，把一条红着的守护变绿），成本约 20 行 TS。

3. **`impact` / `trace` 内核要不要进 barrel？**（Pitfall 4）
   - 推荐不进（选项 A），理由已述。但这是可逆决策，plan 里定一次即可。

4. **风险分级里的「路径最高置信档」具体指什么？**
   - D-15 说输入是「d1 数量、是否穿仓、路径最高置信档」，但表格里的四条判据只用到前两个。第三个量在阈值表里没有出现。
   - 建议：要么在 docstring 里说明它是**保留输入**（供后续校准用），要么补一条判据（如「全部路径的最高置信档都 ≤ `bare_name` 时降一级」）。⛔ 不要让函数签名收一个从不使用的参数而不解释。

5. **`equal_length_path_count` 的封顶值取多少？**
   - `nx.all_shortest_paths` 是生成器，高扇出图上可能天文数字。建议 `islice(…, 11)` 报「≥10 条」。CONTEXT 未定，属 Discretion。

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| networkx | impact/trace 内核 | ✓ | 3.6.1 | — |
| Python | 全部 | ✓ | 3.14（`server/.venv`） | — |
| `services.code_graph` barrel | 取图 | ✓ | Phase 121，96 passed | — |
| `mcp/` git submodule | `test_mcp_package_alignment` | ✓ 本机已 checkout；CI `submodules: recursive` | — | 未 checkout 时该测试 skip（本机不会） |
| 生产 PostgreSQL | 本次调研的数据核实 | ✓（只读聚合已跑） | — | 实现与测试不需要它 |
| 生产 `CrossRepoApiCall` 数据 | IMPACT-03 的真实验证 | ✗ **0 行** | — | 合成数据测试 + 显式声明（见 Q1） |
| Node / volar（server 镜像） | 跨仓链路上游 `ApiWrapper` 抽取 | ✗ | — | 无——归 LSP-01 / Phase 127 |

**Missing dependencies with no fallback:**
- 生产跨仓数据。IMPACT-03 可实现、可测、**不可在生产验证**。

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2+ / pytest-django 4.8+ / pytest-asyncio（`asyncio_mode = "auto"`） |
| Config file | `server/pyproject.toml` `[tool.pytest.ini_options]` |
| addopts（已生效） | `-v --tb=short --disable-socket --allow-unix-socket -m 'not perf and not integration and not slow and not postgres_queue'` |
| Quick run（内核，无 DB） | `cd server && uv run pytest tests/services/code_graph/test_impact.py tests/services/code_graph/test_trace.py -q` |
| Full suite（相位门） | `cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False DATABASE_URL=sqlite:///./data/test_gate.db uv run pytest --reuse-db` |

🚨 **本机跑库相关用例的必备前缀**（121-CONTEXT 记录，本次实跑复现）：`GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False`，否则 app-init 守护线程占住 `test_friday` 导致建库失败；配 `--reuse-db` 省重建。
🚨 **不要在生产 PostgreSQL 上跑全量**：121-10 实测 75 分钟只推进 25%（跨网每查询 ~6ms RTT），全量约 10 小时。相位门用 SQLite。

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| IMPACT-01 | 合成图上 d1/d2/d3 分组逐点正确；同符号多层出现取最浅；方向正确（下游不出现） | unit（无 DB） | `pytest tests/services/code_graph/test_impact.py::test_depth_grouping -x` | ❌ Wave 0 |
| IMPACT-01 | `max_depth` 生效；超深节点不出现 | unit | `pytest tests/services/code_graph/test_impact.py::test_max_depth_budget -x` | ❌ Wave 0 |
| IMPACT-01 | 内核不修改入参图（fixture 已 `freeze`，就地改必抛） | unit | `pytest tests/services/code_graph/test_impact.py::test_kernel_does_not_mutate_graph -x` | ❌ Wave 0 |
| IMPACT-02 | 每条结果带 `confidence` 档 + `reason`（经 `derive_reason`）+ `path_confidence`（= path min，D-07） | unit | `pytest tests/services/code_graph/test_impact.py::test_edge_confidence_and_reason -x` | ❌ Wave 0 |
| IMPACT-02 | `min_confidence` 各阈值下结果集单调收缩；`cross_repo` 用 `match_confidence` 原值参与比较（不归一化） | unit | `pytest tests/services/code_graph/test_impact.py::test_min_confidence_filter -x` | ❌ Wave 0 |
| IMPACT-02 | **D-08 双闸**：单开 `include_low_confidence` 或单降 `min_confidence` 都不足以让 bare_name 边参与扩散 | unit | `pytest tests/services/code_graph/test_impact.py::test_bare_name_requires_both_gates -x` | ❌ Wave 0 |
| IMPACT-03 | 跨仓一跳：对端仓成功 → `cross_repo: true` + `match_confidence` 原值 | integration（DB） | `pytest tests/services/code_graph/test_cross_repo_hop.py::test_cross_repo_success -x` | ❌ Wave 0 |
| IMPACT-03 | `GraphAccessDenied` → 整仓折叠 `REDACTED_REPOSITORY`，不泄漏仓名/路径/符号名（D-12） | integration | `pytest tests/services/code_graph/test_cross_repo_hop.py::test_unauthorized_repo_redacted -x` | ❌ Wave 0 |
| IMPACT-03 | `GraphNotIndexed` / `GraphBuildTimeout` → `unavailable_reason` 条目，本仓结果照常返回（D-14） | integration | `pytest tests/services/code_graph/test_cross_repo_hop.py::test_peer_unavailable_fail_soft -x` | ❌ Wave 0 |
| IMPACT-03 | `max_cross_repo_hops=1` 不递归（D-11） | integration | `pytest tests/services/code_graph/test_cross_repo_hop.py::test_hop_budget -x` | ❌ Wave 0 |
| IMPACT-03 | **反向守护**：图里 `kind=="cross_repo"` 的边两端必在同仓，不得被标 `cross_repo: true` | unit | `pytest tests/services/code_graph/test_impact.py::test_graph_cross_repo_edges_are_intra_repo -x` | ❌ Wave 0 |
| IMPACT-04 | 四级风险分级在阈值边界（d1 = 2/3/7/8/19/20 与穿仓组合）上逐点正确 | unit（参数化） | `pytest tests/services/code_graph/test_impact.py::test_risk_levels -x` | ❌ Wave 0 |
| IMPACT-04 | 截断：`total_found`/`returned`/`truncated_by_depth` 计数正确；排序键为「深度升序 + 置信度降序」且在截断前生效 | unit | `pytest tests/services/code_graph/test_impact.py::test_truncation_summary -x` | ❌ Wave 0 |
| IMPACT-05 | 最短路逐跳 `file:line` + `kind` + `confidence` 正确 | unit | `pytest tests/services/code_graph/test_trace.py::test_shortest_path_hops -x` | ❌ Wave 0 |
| IMPACT-05 | 多条等长路径时返回第一条 + `equal_length_path_count`（D-18） | unit | `pytest tests/services/code_graph/test_trace.py::test_equal_length_paths_declared -x` | ❌ Wave 0 |
| IMPACT-05 | 不可达 → 显式「无路径」结构（含两端解析结果与 `min_confidence`），⛔ 不是空数组（D-20） | unit | `pytest tests/services/code_graph/test_trace.py::test_no_path_explicit_structure -x` | ❌ Wave 0 |
| IMPACT-05 | 重名 → 候选列表（带 `file:line`/`symbol_type`/`signature`），⛔ 绝不静默取第一个（D-19） | integration（`signature` 需 DB） | `pytest tests/services/code_graph/test_symbol_resolve.py::test_ambiguous_returns_candidates -x` | ❌ Wave 0 |
| IMPACT-05 | uid 优先：传 `symbol_id` 时不走候选路径 | unit | `pytest tests/services/code_graph/test_symbol_resolve.py::test_uid_takes_precedence -x` | ❌ Wave 0 |
| IMPACT-06 | MCP：未带 PAT → 401 `authentication_failed`；未索引仓 → 400 `repository_not_indexed` | integration | `pytest tests/mcp_tools/test_impact_trace_tools.py -k "auth or not_indexed" -x` | ❌ Wave 0 |
| IMPACT-06 | MCP：schema snapshot 与 urls 双向一致 | unit | `pytest tests/mcp_tools/test_schema_snapshot.py -x` | ✅ 存在（需加两条字面量） |
| IMPACT-06 | 对话：`@tool` 已注册且在 `chat_runner._INDEXED_TOOL_NAMES` 白名单内 | unit | `pytest tests/agents/tools/test_graph_tools.py::test_registered_and_whitelisted -x` | ❌ Wave 0 |
| IMPACT-06 | **双面同源**：同一输入下 MCP 与对话壳产出的 `data` 段逐字节相同（D-21 防漂移） | integration | `pytest tests/mcp_tools/test_impact_trace_tools.py::test_two_surfaces_same_payload -x` | ❌ Wave 0 |
| IMPACT-06 | staleness：`behind_commits` 有值 → 报数字；`None` → 降级只报 `as_of <sha>`，⛔ 不编造（D-22） | unit | `pytest tests/services/code_graph/test_staleness.py -x` | ❌ Wave 0 |
| D-23 | 四个降级标记 + **数值** `resolution_rate` 全部出现在两面输出里 | unit | `pytest tests/mcp_tools/test_impact_trace_tools.py::test_degradation_markers_surfaced -x` | ❌ Wave 0 |
| D-24 | 超预算仓：壳层传了 `seed_symbol_ids` + `depth`，不吃 `GraphError` | integration（mock 预算） | `pytest tests/services/code_graph/test_impact_shell.py::test_over_budget_uses_seeded_subgraph -x` | ❌ Wave 0 |
| D-04 | 新内核模块满足既有 AST 观测契约（自动生效） | unit | `pytest tests/services/code_graph/test_access.py -k "observability or upper_layer or barrel" -x` | ✅ 存在 |
| GRAPH-04 回填 | 被排除文件的符号不出现在 impact/trace 输出（Phase 121 SC-4 的端到端兑现） | integration | `pytest tests/mcp_tools/test_impact_trace_tools.py::test_excluded_files_invisible -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `cd server && uv run pytest tests/services/code_graph/ -q`（内核部分零 DB，秒级）
- **Per wave merge:** `cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest tests/services/code_graph/ tests/mcp_tools/ tests/agents/ --reuse-db -q`
- **Phase gate:** SQLite 上全量 + `ruff check services/code_graph/ mcp_tools/ agents/tools/` + `mypy services/code_graph/` + `makemigrations --check --dry-run`（本相位零迁移，退出码必须 0）

### Wave 0 Gaps

- [ ] `tests/services/code_graph/conftest.py` — **追加**一个 `known_topology()` 合成冻结图 fixture（现有 conftest 只有 DB fixtures）；覆盖 IMPACT-01/02/04/05 的全部内核断言
- [ ] `tests/services/code_graph/test_impact.py` — 新建，覆盖 IMPACT-01/02/04
- [ ] `tests/services/code_graph/test_trace.py` — 新建，覆盖 IMPACT-05
- [ ] `tests/services/code_graph/test_symbol_resolve.py` — 新建，覆盖 D-19
- [ ] `tests/services/code_graph/test_cross_repo_hop.py` — 新建，覆盖 IMPACT-03（需 DB：两个 Repository + Endpoint + ApiCallSite + CrossRepoApiCall 工厂）
- [ ] `tests/services/code_graph/test_staleness.py` — 新建，覆盖 D-22
- [ ] `tests/services/code_graph/test_impact_shell.py` — 新建，覆盖 D-24
- [ ] `tests/mcp_tools/test_impact_trace_tools.py` — 新建，覆盖 IMPACT-06 + D-21 双面同源 + D-23 + GRAPH-04 回填
- [ ] `tests/agents/tools/test_graph_tools.py` — 新建，覆盖对话壳注册与白名单
- [ ] `tests/mcp_tools/test_schema_snapshot.py` — **修改**，加两条手写字面量条目
- [ ] 框架安装：无（pytest 全套已在）

---

## Security Domain

**配置：** `security_enforcement: true`，`security_asvs_level: 1`，`security_block_on: "high"`（`.planning/config.json`）。

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V1 架构 / 可信边界 | **yes** | 单一图访问入口（`GraphService.get_graph`）+ AST import 守护（`test_no_upper_layer_imports_internal_submodules`）；本相位是这道防线的首个承压者 |
| V2 Authentication | yes | 复用 `AccessTokenAuthentication`（PAT）+ `CookieJWTAuthentication`；⛔ 子类不覆写 `authentication_classes` |
| V3 Session Management | no（复用既有 JWT / PAT，不新增会话面） | — |
| V4 Access Control | **yes（本相位的核心风险面）** | `ensure_repository_readable(user, repo_id)` 每次调用都跑（不因缓存命中跳过）；**跨仓每穿一仓复核**（D-12） |
| V5 Input Validation | yes | MCP 侧 DRF `Serializer`（`repository_id` 用 `UUIDField`）；对话侧 JSON Schema + pydantic。`get_graph` 内部另有 `_validated_seed_ids` 对非法 UUID 抛 `GraphError` |
| V6 Cryptography | no（本相位不碰凭证） | — |
| V7 Error Handling & Logging | **yes** | 异常文本必过 `redact_secrets_in_text`（AST 契约强制）；⛔ 不把 `GraphError` 的内部 `details`（含 `estimated_bytes` / `max_graph_bytes`）原样吐给 agent |
| V8 Data Protection | **yes** | exclusion 在装配阶段生效（Phase 121）；`REDACTED_REPOSITORY` 折叠；`include_content` 默认关（D-17） |

### Known Threat Patterns for 本相位（STRIDE）

| # | Pattern | STRIDE | Standard Mitigation |
|---|---------|--------|---------------------|
| T-122-穿仓 | 低权用户以有权仓为起点，沿跨仓一跳读到**从未授权**仓库的符号名 / 文件路径 / 行号——比 RAG 泄漏更结构化 | **Information Disclosure** | D-12：对端仓调 `get_graph(peer_id, user=user)`，`ensure_repository_readable` 照样跑；`GraphAccessDenied` → 整仓折叠 `REDACTED_REPOSITORY`。🚨 **`REDACTED_REPOSITORY` 条目本身也不得泄漏对端仓名/路径/符号名/文件数**——只能给「有 N 条影响，无权查看」。回归测试必须断言响应体里不出现对端仓的任何标识符 |
| T-122-折叠泄漏 | `REDACTED_REPOSITORY` 条目携带 `repository_id` 或计数细节，构成存在性预言机（oracle） | Information Disclosure | 折叠条目只出 `{"repository": "redacted_repository", "affected_count": n}`。⚠️ 连 `n` 都是弱信号——建议桶化（`1-9` / `10+`）或干脆省略，由 planner 裁决并在 docstring 记明理由 |
| T-122-绕闸 | 内核或壳层直连 `loader` / `cache` 自造 matcher，一次绕过权限 + exclusion + 水位三道闸 | **Elevation of Privilege** | D-02 + `test_no_upper_layer_imports_internal_submodules`（121 验证后已覆盖 `from services.code_graph import loader` 拼法）。本相位新代码是这条守护的首个真实压力测试 |
| T-122-exclusion 回流 | 被排除文件（`.env` / `*.pem` / `id_rsa`）的符号名与路径经 impact 输出回流给 LLM | Information Disclosure | Phase 121 已在**装配阶段**过滤（`loader.py:401`），节点根本不入图；本相位补一条**端到端**回归（Phase 121 SC-4 的 deferred 项由本相位兑现） |
| T-122-空图误导 | `GraphNotIndexed` 被 catch 成空影响面，agent 得出「改这里安全」 | **Tampering（结论被污染）** | D-03：内核不吞 `GraphError`，壳层逐类翻译成明确文案。断言：未索引仓的 impact 必须是错误响应而非 `{"affected": []}` |
| T-122-半新图误导 | `partial_edges=True`（水位已推进但边未建完）的图被当完整图用 | Tampering | D-23：四个标记全部透出；输出头部声明「边构建在途，结果可能不完整」 |
| T-122-日志放大 | agent 单任务数百次 impact，逐节点 INFO / 逐结果 `RetrievalTrace` 撑爆日志表 | **Denial of Service** | 工具级一条 `caller` 事件 + 一条汇总 `RetrievalTrace`（只记查询符号 + 计数 + 置信度分布）；内核 `category="sampling"` + DEBUG |
| T-122-遍历 DoS | 热点符号（fan-in 2,803）+ `min_confidence=0` + `include_low_confidence=True` 让一次查询遍历整个仓库 | Denial of Service | `max_depth=3`（D-05）+ `max_nodes` 软上限（建议 2,000，Discretion）+ 截断 200（D-16）+ D-08 双闸让 bare_name 不易被误开 |
| T-122-错误细节泄漏 | `GraphError.details` 里的 `estimated_bytes` / `max_graph_bytes` 直出给外部 agent | Information Disclosure | 壳层只出映射后的用户文案，内部 `details` 只进（已脱敏的）日志 |

**ASVS L1 判定：** 上述 9 条均有既有机制可直接复用，无需新建安全设施。唯一需要**新设计**的是 T-122-折叠泄漏的粒度裁决（`affected_count` 出不出、出多细），建议在 plan 里作为一条显式决策，⛔ 不要留给执行方即兴决定。

---

## Sources

### Primary (HIGH confidence)

**本仓代码一手核实（路径 + 行号均真实存在，2026-08-09 读取）：**
- `server/services/code_graph/__init__.py`（barrel 17 项 + 架构红线 docstring）
- `server/services/code_graph/model.py`（`EdgeKind` / `EdgeConfidence` / `confidence_score` :105 / `derive_reason` :133 / `LOW_RESOLUTION_THRESHOLD` :219 / `REDACTED_REPOSITORY` :224 / `GraphMeta` :250 / `CodeGraph` :319 / 五个异常类）
- `server/services/code_graph/cache.py`（`get_graph` :674 / `_get_graph_sync` :744 / 超预算 raise :970-981 / `nx.freeze` :1025 / 子图不进缓存与 single-flight :833-839）
- `server/services/code_graph/loader.py`（节点 5 属性 :414-422 / 不取 `signature` :354-356 / `_AMBIGUOUS` 标记 :424-431 / **跨仓边两端同仓才建 :804-828** / `_resolve_by_file_and_name` :936 / `_expand_seed_ids` :960 / `load_subgraph` :1053 / ME-10 已知局限 :1093-1109）
- `server/services/code_graph/access.py`（`ensure_repository_readable` 的四道判定与 fail-closed 说明）
- `server/mcp_tools/views.py`（`McpToolView` :223-401 / `ReverseLookupView` 完整范例 :1213-1261）、`urls.py`、`serializers.py::TOOL_SCHEMA_SNAPSHOT` :985
- `server/agents/tools/base.py`（`tool` 装饰器 :90-185 / `ToolResult` :35-66）、`__init__.py`、`list_endpoints.py`（双层防御范例）、`repository_relevance.py`、`delivery_knowledge_tools.py:56`（`_resolve_conversation_user`）
- `server/agents/chat_runner.py:86-124`（`_INDEXED_TOOL_NAMES` 白名单 + 「漏挂白名单」历史债注释）
- `server/repositories/freshness_service.py`（`compute_freshness_status` :25 / `update_behind_commits_for_stale_repos` :43 / `_calculate_commit_distance` :76）
- `server/repositories/models.py`（`behind_commits` :312 / `behind_commits_calculated_at` :317 / `remote_head_sha` :299 / `last_indexed_commit_sha` :233）
- `server/codegraph/models.py`（`Symbol` :12 / `CallEdge` :97 / `Endpoint` :176 / `ApiCallSite` :263 / `CrossRepoApiCall` :297）
- `server/tests/services/code_graph/test_access.py`（观测契约 :383-449 / barrel 17 项 :470-541 / AST import 守护 :544-610）、`conftest.py`
- `server/tests/mcp_tools/test_schema_snapshot.py`（:28-49 注册↔snapshot 双向）、`test_mcp_package_alignment.py`、`test_skills_snapshot_guard.py`
- `server/pyproject.toml`（`[tool.pytest.ini_options]` :120-134）、`.github/workflows/ci.yaml`（`submodules: recursive` :59, :205）、`.planning/config.json`

**本机实测（CPython 3.14 / networkx 3.6.1，2026-08-09）：**
- 冻结 `MultiDiGraph` 上 `reverse(copy=False)` / `predecessors` / `bfs_layers` / `subgraph_view(filter_edge)` / `restricted_view` / `shortest_path` / `all_shortest_paths` / `bidirectional_shortest_path` 全部可用；`filter_edge` 以原始方向 `(u,v,k)` 被调用；视图仍为 frozen 且 `is_multigraph()` 为真
- 30,000 节点 / 100,000 边规模的耗时对照（见 `## Code Examples` §1）
- `pytest tests/mcp_tools/test_mcp_package_alignment.py` → 1 failed（5 项漂移，HEAD 既有）

**生产 PostgreSQL 只读聚合（2026-08-09，沿用 121-10 建立的诊断先例；仅 COUNT / 分位数，无路径、无符号名、无凭证）：**
- `CrossRepoApiCall = 0` / `ApiCallSite = 0` / `ApiWrapper = 0` / `Endpoint = 6,014`（117 个仓）
- 已索引仓 258，`behind_commits` / `remote_head_sha` / `last_indexed_commit_sha` 覆盖 258/258，当前全部 `fresh`
- 符号重名分布（distinct `(repo,name)` = 202,661，其中 39,031 非唯一 = 19.3%；`(repo,file,name)` 仍有 24,312 组冲突）
- `CallEdge` 1,585,137 行，resolved 298,216（18.8%）；入度 p50=1 / p99=25 / max=2,803；出度 p50=4 / p99=54 / max=3,613

**规划文档：** `.planning/phases/122-impact-trace/122-CONTEXT.md`、`.planning/REQUIREMENTS.md`、`.planning/research/SUMMARY.md` / `PITFALLS.md`、`.planning/phases/121-graph-base/121-VERIFICATION.md` / `121-10-SUMMARY.md`、`.cursor/rules/observability-logging.mdc`、`.planning/codebase/TESTING.md`

### Secondary (MEDIUM confidence)

- GitNexus 工具契约形状（深度分组语义标签 / `minConfidence` / 风险四级 / 截断 summary / 消歧协议 / `as_of`）—— 经 `.planning/research/FEATURES.md` 转引，本次未回源

### Tertiary (LOW confidence)

- 「生产跨仓表为 0 的根因是 volar/Node 缺失」（假设 A2）—— 有强旁证，未直接验证

---

## Metadata

**Confidence breakdown:**

| Area | Level | Reason |
|------|-------|--------|
| Standard stack | HIGH | 零新增依赖；networkx 版本与全部 API 行为本机实跑 |
| networkx 算法与性能 | HIGH | 8 项 API 在冻结 MultiDiGraph 上逐一验证；30k/100k 规模耗时实测 |
| MCP / 对话壳契约 | HIGH | 逐行读 `McpToolView` 与 `tool` 装饰器；40+ 既有工具同形 |
| 机械守护清单 | HIGH | 四条守护（观测契约 / barrel 17 项 / AST import / snapshot 双向）均读源码 + 实跑确认，含一条已红的 |
| 跨仓机制 | HIGH（结论） / LOW（根因） | 「图里没有真跨仓边」由 `loader.py:812-828` 直接证明；「生产零样本」由只读聚合证明；根因归属为假设 |
| staleness | HIGH | 字段存在、覆盖 258/258、helper 已在 |
| 生产数据分布 | HIGH | 只读聚合直查，口径与 121-10 一致 |
| 风险阈值（D-15） | LOW（CONTEXT 已自认） | 未经真实数据校准的初值，本相位只落值 + 标注 |

**Research date:** 2026-08-09
**Valid until:** 2026-09-08（30 天）。⚠️ 两个例外会更早失效：(a) Phase 127 落地 LSP 后跨仓表可能开始有数据，Pitfall 1 的「零样本」结论需重测；(b) `mcp/` submodule 若被别的批次同步，Pitfall 3 的漂移清单会变。
