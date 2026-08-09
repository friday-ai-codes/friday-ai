# Phase 121: 内存图服务基座 - Research

**Researched:** 2026-08-09
**Domain:** in-process graph cache service (networkx) over an existing Django/SQL symbol graph; concurrency, invalidation, memory budgeting, fail-closed read gating
**Confidence:** HIGH（本相位几乎全部结论来自本仓代码一手核实 + 在本仓 venv 内实测；无外部依赖调研）

> 本文档**不重复**里程碑级调研（`.planning/research/{SUMMARY,ARCHITECTURE,STACK,PITFALLS}.md`）。
> 那四份已经裁决了「用 networkx、不用 rustworkx / leidenalg」「缓存四件套」「边准入分层」等选型问题。
> 本文只回答 **planner 靠读 CONTEXT 无法决定、必须查代码或实测才知道** 的问题。

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Area 1: 缓存键、失效信号与一致性**

- **缓存键**：`(repository_id, branch_name)` 二元组，`branch_name` 沿用既有模型语义（`""` = 基线分支），不做归一化别名。跨仓 impact 在 Phase 122 通过「按需再取对端仓的图」组合，**不做多仓合并大图**——合并图会让失效面与内存放大同时失控。
- **失效信号 = 复合签名**（仿 `codegraph/galaxy/cache.py::compute_signature` 范式，但在内存中比对、不落盘）：
  `sha256(last_indexed_commit_sha ‖ edge_build_generation ‖ symbol_count ‖ call_edge_count)`。
  - `last_indexed_commit_sha` 从 `RepositoryBranchIndex` 取，缺失时回落 `Repository.last_indexed_commit_sha`。
  - **`edge_build_generation` 本仓不存在**（scout 确认），本相位以既有信号合成而非新增字段：取 `IndexHistory` 中该仓最近一条 `graph_build_status == COMPLETED` 记录的 `id + finished_at`（无则用 `Repository.graph_last_built_at`）作为「代数」分量。⛔ 不新增迁移、不改既有表。
  - 计数分量用 `.count()` 聚合，与 Galaxy 的 `count + Max(timestamp)` 同款思路，成本可接受（毫秒级）。
- **半新图防护（GRAPH-02 硬要求）**：`get_graph()` 返回前**必须**复算签名并与缓存条目的 `built_signature` 比对；不一致直接丢弃重建。同时若该仓存在**进行中**的边构建（`graph_build_status ∈ {PENDING, RUNNING}`）而水位已推进，则判定为「水位已更新但边未建完」，**拒绝使用缓存并按当前落库状态重建 + 在返回结果上打 `partial_edges: true` 标记**，由上层工具透出，绝不静默返回半新图。
- **不落盘**：与 Galaxy 的文件缓存不同，本服务是 **per-worker 纯内存**缓存（多 worker 各持一份是已知且接受的代价，靠字节预算约束）。理由：图对象无法廉价序列化，落盘反而引入一致性第二源。

**Area 2: 内存预算、逐出与降级**

- **预算按字节，不按条目数**：新增 settings `CODE_GRAPH_CACHE_MAX_BYTES`（默认 **512MB**，环境变量可覆盖），`CODE_GRAPH_MAX_GRAPH_BYTES`（单图上限，默认 **256MB**）。默认值在本相位交付「本仓最大仓实测报告」后可调，**先落保守值不盲设大**。
- **字节估算方式**：不用 `sys.getsizeof` 递归（对 networkx 不准且慢），采用**确定性线性估算** `nodes * NODE_COST + edges * EDGE_COST`，两个常数由本相位的实测标定并写进常量注释；估算函数单独可测。
- **LRU**：`collections.OrderedDict` + `threading.RLock`，`move_to_end` 记访问序；插入后循环逐出直到总字节 ≤ 预算。逐出发结构化事件（含被逐 key、字节、原因）。
- **single-flight**：per-key `threading.Event` 占位法——首个请求放占位、其余等待同一结果；构建失败时唤醒所有等待者并让其各自失败（不做失败缓存，避免毒化）。锁粒度 = per (repo, branch)，全局锁只保护 map 本身。
- **超预算大仓降级**：单图估算 > `CODE_GRAPH_MAX_GRAPH_BYTES` 时**不进缓存**，改走「按需子图」——只装配以查询种子符号为中心、半径 = 调用方指定 depth + 1 的诱导子图（loader 层用 SQL 侧多跳收敛，而非先全量再裁剪）。返回结果标 `degraded: "on_demand_subgraph"`，上层工具须透出。
- **进程不 OOM 是硬约束**：预算检查在**装配前**用行数估算做准入（`Symbol.count + CallEdge.count`），避免「先 OOM 再逐出」。

**Area 3: 边准入与置信度契约（本相位定型，全里程碑复用）**

- **`EdgeConfidence` 三档枚举**（`code_graph/model.py`，字符串枚举，落进所有上层工具输出契约）：
  | 档 | 值 | 来源 | 默认参与扩散 |
  |---|---|---|---|
  | 解析边 | `resolved` | `CallEdge.callee_symbol IS NOT NULL` | ✅ 是 |
  | 裸名边 | `bare_name` | `CallEdge.callee_symbol IS NULL`，仅 `callee_name` 兜底 | ❌ 否（须显式开启） |
  | 跨仓边 | `cross_repo` | `CrossRepoApiCall`，数值取 `match_confidence` 原值 | ✅ 是（携带原值，不归一化） |
  - 每条边同时带 `reason` 字符串（如 `"callee_symbol resolved via FK"` / `"name-only match on 'handle'"` / `"cross-repo api match_confidence=0.7"`），供工具输出直接引用。
  - 数值映射（供 `min_confidence` 过滤用）：`resolved = 1.0`、`bare_name = 0.3`、`cross_repo = match_confidence` 原值。**三档语义标签才是契约，数值只是排序/过滤辅助**。
- **裸名边三道过滤**（仅在显式 `include_low_confidence=True` 时才装载，装载时也必须过滤）：
  1. 同目录/同文件优先（跨目录同名默认丢弃）；
  2. `callee_qualifier` 存在时须匹配；
  3. 常见名黑名单（`get`/`set`/`run`/`handle`/`main`/`init`/`new`/`close`/`read`/`write`/`start`/`stop`/`send`/`parse`/`format`/`String`/`Error` 等），黑名单以模块常量落地、可测。
- **`ChunkEdge`**：本相位装配但默认**不参与符号级扩散**（chunk 与 symbol 不同粒度），仅作为 `chunk_id` 软引用的补充证据面暴露给上层；边档位记 `bare_name` 语义等价的独立档 `chunk_level`（第四档，默认关）。
- **解析率指标**：loader 装配时统计 `resolved / (resolved + bare_name)`，随图返回 `resolution_rate`，低于 **0.6** 时在图元数据上置 `low_resolution: true`，上层工具据此在输出头部声明「本仓解析率偏低，影响面可能偏保守」。

**Area 4: 读取层鉴权与 exclusion 收口（fail-closed）**

- **单一入口**：所有图访问必须经 `GraphService.get_graph(repository_id, branch, *, user=None, ...)`，**loader 与 cache 均不对外导出**（`__init__.py` 只 re-export `GraphService` 与数据契约类型）。上层工具直连 loader 视为架构违规，在 plan-checker/code-review 明确列为红线。
- **exclusion**：复用既有 `server/services/exclusion.py` 的 `build_matcher_for_repo(repository_id)`，在**装配阶段**按 `Symbol.file_path` 过滤节点（被排除节点连同其所有邻接边一并丢弃），而非在输出阶段过滤——保证「排除文件在所有图分析工具输出中不可见」。matcher 失败时 **fail-closed**：整仓不返回图并抛 `GraphAccessDenied`。
  - **缓存与 exclusion 规则的一致性**：exclusion 规则版本纳入缓存签名分量（取 matcher 的规则指纹；`invalidate_matcher_cache` 已有 60s TTL，签名再加一层保险），规则改动后旧图自动失效。
- **权限**：当前仓库层只有 `RepositoryPermission`（存在性 + 认证）这一层，本相位**不发明新的 ACL 模型**，但把校验点收口成 `code_graph/access.py::ensure_repository_readable(user, repository_id)` 单一函数（内部先做 `is_deleted=False` + 索引态校验，预留 per-user ACL 扩展点）。Phase 122 的跨仓 impact 每穿一仓复核一次，未授权整仓折叠为 `redacted_repository`，该折叠语义在本相位的返回契约里先定义好。
- **未索引仓**：`index_status != INDEXED` 时不建图，抛显式错误（沿用 `_get_indexed_repo` 的语义），不返回空图——空图会被上层误读为「没有影响」。

**Area 5: 观测埋点（遵循 `.cursor/rules/observability-logging.mdc`）**

- `component = "code_graph"`；缓存/建图属高频内部步骤 → `category = "sampling"`，**建图完成**这类低频关键事件用 INFO，缓存命中用 DEBUG（禁止 INFO 刷屏）。
- 事件名：`code_graph_build_started` / `code_graph_build_completed`（带 `duration_ms` / `node_count` / `edge_count` / `estimated_bytes` / `resolution_rate`）/ `code_graph_build_failed` / `code_graph_cache_hit` / `code_graph_cache_evicted` / `code_graph_stale_watermark` / `code_graph_degraded_subgraph` / `code_graph_access_denied`。
- 触发用户绑定：走既有中间件注入的 contextvars；后台/预热路径显式 `initiated_by_user_id="system"`。
- 观测代码 best-effort，异常吞掉，绝不反噬取图主流程。

### Claude's Discretion

- 具体模块拆分粒度与私有函数命名、字节估算常数的标定方法、测试用例的组织方式（`server/tests/services/code_graph/` 下的文件切分）、是否额外抽 `signature.py`——均由执行方按本仓既有 service 写法自行决定。
- 是否为 `GraphService` 提供显式 `invalidate(repository_id)` 钩子并挂到 `code_relations/lifecycle.py` 的边构建完成点（推荐做，但形式自定；即便不挂，取图时水位校验也能兜住正确性）。
- 一次性诊断指标（内存实测 + 解析率统计）以什么形态交付——管理命令、pytest 标记用例或脚本均可，只要结果写进 SUMMARY。

### Deferred Ideas (OUT OF SCOPE)

- **rustworkx 图引擎升级** — 触发条件已在 REQUIREMENTS Future 段登记（单仓 >50 万边 / impact p95 >2s / 缓存 >2GB）。本相位只需保证 `model.py` 的图契约不泄漏 networkx 具体类型到上层（留 adapter seam），不做任何实现。
- **跨进程共享图缓存**（Redis / 共享内存） — 多 worker 各持一份是本相位接受的代价；若实测内存不可接受再单独立项。
- **per-user 仓库 ACL** — 本仓当前不存在，本相位只收口校验点并预留扩展位，不发明模型。
- **`purge_file` 从五面扩到六面**（研究 Pitfall 6 提到） — 属于删除链路的收口，与本相位读取层收口不同轨，留待有实际删除需求时处理。
- **图缓存预热**（仿 `GALAXY_CACHE_WARM_ON_STARTUP`） — 冷启动首查慢是可接受的；预热会在启动期制造内存尖峰，与本相位「进程不 OOM」目标冲突，不做。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| GRAPH-01 | Agent/工具查询任一已索引仓库时，系统提供该 `(repository, branch)` 的内存符号图（`Symbol`/`CallEdge`/`ChunkEdge`/`CrossRepoApiCall` 装配），首次构建后命中缓存，不重复建图 | §Code Examples 1（四类边的精确 ORM 查询形状与索引覆盖）、§Pitfall 1（`CrossRepoApiCall` 无 repository FK 也无 Symbol FK，必须按 name+file 解析）、§Pitfall 2（`ChunkEdge` 展开成符号级会笛卡尔爆炸）、§Pitfall 3（feature 分支必须 overlay `["", branch]`）、§Standard Stack（MultiDiGraph 而非 DiGraph） |
| GRAPH-02 | 索引水位（`last_indexed_commit_sha`）或边构建代数变化后缓存自动失效重建；取图时校验水位，不返回「水位已更新但边未建完」的半新图 | §Code Examples 2（signature 的精确字段清单，含两条**互相独立**的边构建轨）、§Code Examples 3（in-flight 判定）、§Pitfall 4（`IndexHistory.graph_build_status` 默认 PENDING 永不推进会导致永久 `partial_edges`）、§Pitfall 5（RUNNING 孤儿行需超时兜底）、§Pitfall 6（`RepositoryBranchIndex.branch_name` 从不为 `""`） |
| GRAPH-03 | 缓存带字节预算 LRU 逐出 + single-flight 防并发构建风暴；超预算大仓有降级路径（不缓存/按需子图），进程不 OOM | §Byte Estimation（本仓实测标定的 NODE_COST/EDGE_COST，线性模型误差 ±5% 且跨 20× 规模稳定）、§Threading Model（多 event loop 下正确的 single-flight 原语）、§Pitfall 7（不可在持锁状态下 await）、§Pitfall 8（默认预算只装得下 2 张大图） |
| GRAPH-04 | 图读取层统一收口权限校验与 exclusion 过滤（fail-closed），排除文件在所有图分析工具输出中不可见 | §Code Examples 5（exclusion 同步/异步双形态与规则指纹推导）、§Security Domain、§Pitfall 9（`_matcher_cache` 是无锁模块字典且 60s TTL，签名必须自算指纹不能依赖 TTL） |
</phase_requirements>

## Summary

本相位是纯后端、零新表、零前端的**基础设施相位**：在既有 SQL 符号图之上加一层 per-worker 内存图服务。技术选型在里程碑调研阶段已经裁决完毕（networkx 3.6.1 + stdlib 并发原语），所以本次调研的全部价值集中在**本仓事实核实**与**实测标定**两件事上，而不是选型。

调研得到四个会直接改变计划形状的结论。**第一，图对象必须用 `MultiDiGraph` 而不是 `DiGraph`**——实测确认 `DiGraph.add_edge(u, v, ...)` 对同一对节点的第二次调用是静默覆盖（三条不同 `kind` 的 A→B 边最终只剩最后一条），而本相位的契约明确要求同一符号对之间并存 `call`/`chunk_level`/`cross_repo` 多档边。代价是内存 +44%（约 +224 字节/边），这是必须付、也付得起的。**第二，`CrossRepoApiCall` 接不上 `Symbol`**：它连的是 `ApiCallSite`（只有 `caller_file` + `caller_function` 字符串）和 `Endpoint`（只有 `file_path` + `handler_name`），两端都没有 Symbol 外键，也没有 repository 外键，还缺 `branch_name`。把跨仓边挂到符号节点上必须走「文件路径 + 名字」的二次解析，这是一段 CONTEXT 里没有预算到的实打实工作量。**第三，「边构建代数」在本仓是两条互相独立的轨**：`IndexHistory.graph_build_status` 跟踪的是 `code_relations` 的 **ChunkEdge** 构建，而 `Symbol`/`CallEdge`/`Endpoint` 的抽取由 `Repository.graph_build_status` + `GraphBuildHistory` 跟踪，两者由完全不同的代码路径写入。签名要同时纳入这两条轨，只看一条会漏失效。**第四，字节线性估算模型是可靠的**——实测在 10k→200k 节点（20 倍跨度）上误差恒定为 -5.0%，只要把常数上调 5% 就能得到 ±1% 的预测精度，可以放心用作准入判据。

风险最高的两点都在并发与状态机上。取图入口是 async，而缓存锁是 `threading` 原语，而本仓同时存在三类 event loop（ASGI 主循环、`background_runner` 常驻循环、workflow engine 的 `_run_in_thread` 循环），所以 **`asyncio.Event` 不可用**（跨循环无法 await），single-flight 必须用 `threading.Event` + `asyncio.to_thread` 等待，且**绝不能在持锁状态下 await**。另一点是 `IndexHistory.graph_build_status` 的默认值就是 `PENDING`，且只有走 `enqueue_edge_build_for_history` 的路径才会推进——如果照 CONTEXT 字面实现「PENDING 或 RUNNING 即视为在途」，那些从未触发过边构建的仓库会**永久**被打上 `partial_edges: true`，这个降级标记一旦长鸣就等于没有。

**Primary recommendation:** 用 `MultiDiGraph`，把整条「取水位 → 算签名 → 查计数 → 装配 → 过滤」链路收进**单个 `sync_to_async` 包裹的同步函数**（锁与 ORM 全在同步侧，彻底规避 await-under-lock），签名同时纳入 ChunkEdge 与 Symbol 两条边构建轨 + 自算的 exclusion 规则指纹，in-flight 判定必须带 `GRAPH_BUILD_ORPHAN_TIMEOUT_MINUTES` 同款的超时兜底，字节常数取 `NODE_COST=640 / EDGE_COST=560`（MultiDiGraph 实测 +5% 安全裕度）并在相位内用真实最大仓复校。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 符号/边取数（ORM） | API/Backend — `code_graph/loader.py` | Database | CONTEXT 锁定 loader 独占 ORM；纯算法层不得碰 ORM，否则 Phase 122 的算法无法单测 |
| 图对象装配（networkx） | API/Backend — `loader.py`（纯 CPU） | — | 装配是 CPU 密集且持 GIL，必须与 ORM I/O 在同一同步上下文完成以避免多次线程切换 |
| 缓存 / LRU / single-flight | API/Backend — `code_graph/cache.py`（进程内单例） | — | per-worker 进程内状态，**不进 DB、不进 Redis**（CONTEXT 明确 deferred 跨进程共享） |
| 水位与代数签名计算 | API/Backend — `cache.py` 或 `signature.py` | Database（COUNT/MAX 聚合） | 仿 `GalaxyGraphCache.compute_signature`，但内存比对不落盘 |
| 权限校验（仓库可读性） | API/Backend — `code_graph/access.py` | — | 收口成单一函数；⛔ 不下沉到 DRF permission（图服务也被后台任务/工作流调用，没有 request 对象） |
| exclusion 过滤 | API/Backend — `access.py` 调 `services/exclusion.py` | — | `services/exclusion.py` 是全仓唯一事实源（模块 docstring 明写），绝不另写一套 |
| 边置信度分档与 reason | API/Backend — `code_graph/model.py` | — | 契约层，全里程碑复用；数据契约不得泄漏 networkx 类型（为 rustworkx 留 seam） |
| 图查询算法（impact/trace） | **OUT OF SCOPE → Phase 122** | — | 本相位只交付地基与契约 |
| 任何 UI | **无** | — | CONTEXT 明确本相位无前端改动 |

## Project Constraints (from `.cursor/rules/`)

`.cursor/rules/observability-logging.mdc` 是唯一 `alwaysApply: true` 的项目规则，其内容与 `AGENTS.md` / `CLAUDE.md` 内嵌的规范段落逐字同源。对本相位的**可执行**约束：

1. **必须**用 `structlog.get_logger(__name__)`；事件名 snake_case，`xxx_started` / `xxx_completed` / `xxx_failed` 三件套；字段走 kv，禁止拼进 message。
2. **必须**在每个事件上写 `category`（本相位全部 `sampling`）与 `component`（CONTEXT 锁定 `code_graph`）。
3. 关键生命周期事件**必须**带 `duration_ms`。
4. **必须**能绑定触发用户；无触发用户（后台/预热）记 `system`。
5. 异常文本入日志前**必须**过 `redact_secrets_in_text`（`server/common/logging.py:391` [VERIFIED: codebase]）。
6. 观测代码 best-effort，异常吞掉，**绝不**反噬主流程。
7. **禁止**在高频循环内用 INFO 刷屏——规范正文点名了历史教训「4000+ 文件的 `graph_bundle_written` 刷爆 stdout」。本相位的装配循环（10 万级迭代）绝对不能有 per-item 日志。

**⚠️ 一处必须在计划里显式处理的冲突：** `LOGGING-SPEC.md §5` 的 `component` 注册表当前收录的是 **`codegraph`**（无下划线），**没有 `code_graph`** [VERIFIED: `.planning/observability/LOGGING-SPEC.md` §5]。CONTEXT 锁定的值是 `code_graph`。规范原文写明「新增功能就近归类，没有就新增并在此登记」，所以计划里**必须包含一个任务：把 `code_graph` 补进 `LOGGING-SPEC.md §5` 的 component 清单**，否则违反规范且未来筛日志会漏。

**不适用的检查项**（在自检清单里逐条声明「N/A + 理由」，避免 code-review 误判漏项）：新增 LLM 调用点（本相位零 LLM 调用，无需 `call_source`）、新增请求入口（本相位不加 view/URL）、新增 webhook、新增队列任务、`RetrievalTrace`（图召回的留痕由 Phase 122 的 MCP/对话双壳承担，本相位不产生用户可归因调用）。

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `networkx` | 3.6.1（锁文件已在） | 内存图对象 + 后续图算法 | 里程碑调研已裁决；纯 Python wheel，Py3.14 天然兼容；`louvain_communities` 供 Phase 125 复用，换 rustworkx 会因缺社区检测而必须双持 [CITED: `.planning/research/SUMMARY.md`] |
| Python stdlib `collections.OrderedDict` | — | 字节预算 LRU | `move_to_end` + `popitem(last=False)`；本仓已有同款先例 `codegraph/lsp/volar_pool.py:63` [VERIFIED: codebase] |
| Python stdlib `threading` | — | 全局 map 锁 + per-key single-flight | 本仓 11 处模块级 `threading.Lock` 先例（见 §Threading Model）；`asyncio` 原语在本仓多 loop 环境下不可用 |
| Python stdlib `hashlib` | — | 复合签名 SHA256 | 与 `GalaxyGraphCache.compute_signature` 同款 [VERIFIED: `server/codegraph/galaxy/cache.py:104`] |

**依赖动作（必做）：** `networkx` 目前**只在 `server/uv.lock:2371` 作为 llama-index 的传递依赖存在，`server/pyproject.toml` 里没有直接声明** [VERIFIED: `grep networkx pyproject.toml uv.lock`——`pyproject.toml` 零命中]。本相位**必须**把它提升为直接依赖，否则 llama-index 某次升级不再传递它就会在运行期 `ImportError`。

```toml
# server/pyproject.toml [project] dependencies
"networkx>=3.6,<4",
```

版本约束用 `<4` 而不是锁死 `==3.6.1`：3.x 内 `DiGraph`/`MultiDiGraph`/BFS API 稳定，锁死会和 llama-index 的解析冲突。

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `MultiDiGraph` | `DiGraph` + 边属性里挂边列表 | 省 44% 内存，但每个消费点都要自己解列表；networkx 内置算法（BFS/最短路/社区）无法直接吃「一条边代表多条边」的语义，Phase 122/125/126 全都要写适配层。**不推荐**——本相位省的内存会在三个上层相位加倍还回去 |
| `MultiDiGraph` | `DiGraph`，只装 `resolved` 边 | 最省，但直接违反 CONTEXT Area 3 的四档边契约 |
| `threading.Event` single-flight | `asyncio.Event` | **不可行**：本仓有三类并存 event loop，`asyncio.Event` 绑定创建它的 loop，跨 loop await 会 `RuntimeError`（见 §Threading Model） |
| 自算 exclusion 规则指纹 | 依赖 `_matcher_cache` 的 60s TTL | 不可靠：TTL 只保证 matcher 对象刷新，不产生任何可比对的版本号；且 CONTEXT 明确要求把规则版本**纳入签名** |
| `sys.getsizeof` 递归测图大小 | — | CONTEXT 已否决；实测也支持——递归遍历 40 万对象需数秒且会漏共享引用 |

**Installation:**

```bash
cd server && uv add "networkx>=3.6,<4"
```

**Version verification（本次执行）：**

```
$ .venv/bin/python -c "import networkx; print(networkx.__version__)"
3.6.1
$ .venv/bin/python -c "import importlib.metadata as m; d=m.distribution('networkx'); print(d.version, d.metadata.get('License-Expression'))"
3.6.1 BSD-3-Clause
```

[VERIFIED: 本仓 `server/.venv`，Python 3.14.2]

## Package Legitimacy Audit

本相位**不引入任何新包**——唯一动作是把已在锁文件中的传递依赖提升为直接依赖。

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `networkx` | PyPI | 20+ 年（2005 起） | 数千万/月级 | `github.com/networkx/networkx`（元数据 `Project-URL: Source Code` 自证） | 不可用（未安装） | **Approved** |

**slopcheck 不可用时的替代证据**（强于 slopcheck 的判据，逐条为本次一手核实）：

- 已存在于 `server/uv.lock:2371-2376`，带 **sha256 哈希锁定**的 sdist 与 wheel — 供应链已 pin。
- 分发元数据 `License-Expression: BSD-3-Clause`，与本仓 MIT + Docker 镜像分发无 license 冲突（对照：里程碑调研因 GPL 否决了 leidenalg）。
- `Project-URL` 指向 `github.com/networkx/networkx`（真实上游，非空 source repo）。
- 无运行期强制依赖（`requires` 全部为 `extra ==` 可选组），**不会**因为提升为直接依赖而拉进 numpy/scipy。
- 已被 llama-index 传递引入并在生产镜像里跑了多个里程碑。

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```text
┌──────────── 调用方（Phase 122+；本相位只交付被调用面）─────────────┐
│  MCP McpToolView  │  对话 @tool  │  durable/workflow 后台任务      │
└─────────┬───────────────┬───────────────────┬────────────────────┘
          │               │                   │
          └───────────────┴───────────────────┘
                          │  await GraphService.get_graph(repo_id, branch, user=…)
                          ▼
        ┌─────────────────────────────────────────────────┐
        │  code_graph/__init__.py                          │
        │  仅 re-export：GraphService + 数据契约类型        │
        │  ⛔ 不导出 loader / cache（架构红线）             │
        └────────────────────────┬────────────────────────┘
                                 ▼
        ┌─────────────────────────────────────────────────┐
        │  access.py :: ensure_repository_readable()       │  ← GRAPH-04 第一道闸
        │   ① 仓库存在且 is_deleted=False                   │
        │   ② index_status == INDEXED（否则显式抛错，不返空图）│
        │   ③ per-user ACL 扩展点（本相位空实现）            │
        │   失败 → GraphAccessDenied / GraphNotIndexed      │
        └────────────────────────┬────────────────────────┘
                                 ▼
        ┌─────────────────────────────────────────────────┐
        │  cache.py :: GraphService（进程内单例）           │
        │                                                  │
        │  ┌── 每次取图都重算（毫秒级 COUNT/MAX 聚合）──┐    │
        │  │  compute_signature(repo, branch) →         │    │
        │  │    watermark ‖ chunkedge_gen ‖ symbol_gen  │    │
        │  │    ‖ counts ‖ exclusion_fingerprint        │    │
        │  └────────────────────────────────────────────┘    │
        │                     │                              │
        │        签名 == 缓存条目.built_signature ?           │
        │            ├── 是 ──→ 命中：move_to_end，返回       │
        │            └── 否 ──→ 丢弃条目，走构建              │
        │                                                    │
        │  ┌── single-flight（per-key threading.Event）──┐    │
        │  │  首个请求装占位 → 其余 await 同一 Event      │    │
        │  │  失败：唤醒全部等待者，各自抛，不缓存失败    │    │
        │  └────────────────────────────────────────────┘    │
        │                                                    │
        │  ┌── 准入（装配前，防 OOM）─────────────────────┐   │
        │  │  est = n*NODE_COST + e*EDGE_COST（用 COUNT）│   │
        │  │  est > MAX_GRAPH_BYTES → 不缓存，走子图降级  │   │
        │  └────────────────────────────────────────────┘   │
        │                                                    │
        │  OrderedDict + RLock，插入后循环逐出至 ≤ 预算       │
        └────────────────────────┬───────────────────────────┘
                                 ▼   （整体一次 sync_to_async）
        ┌─────────────────────────────────────────────────┐
        │  loader.py（ORM 独占 + networkx 装配，同步）      │
        │                                                  │
        │  1. exclusion matcher（同步取有效规则 + 算指纹）  │
        │  2. Symbol   → 节点（file_path 命中排除即丢弃）   │
        │  3. CallEdge → resolved / bare_name 双档          │
        │  4. ChunkEdge→ chunk_level 档（独立面，不展开）   │
        │  5. CrossRepoApiCall → 按 file+name 解析到符号    │
        │  6. 统计 resolution_rate → low_resolution 标记    │
        │  返回 CodeGraph（含 MultiDiGraph + 元数据）        │
        └────────────────────────┬────────────────────────┘
                                 ▼
     model.py：CodeGraph / GraphMeta / EdgeConfidence / EdgeKind
     （契约层；⛔ networkx 类型不外泄，为 rustworkx 留 adapter seam）
```

### Recommended Project Structure

```text
server/services/code_graph/          # 新包；同层兄弟参照 services/code_intel/
├── __init__.py       # 只 re-export GraphService + model.py 的契约类型
├── model.py          # CodeGraph / GraphMeta / EdgeConfidence / EdgeKind / 异常类
├── loader.py         # ORM 独占 + networkx 装配（全同步，由 cache 层一次性 sync_to_async）
├── cache.py          # GraphService 单例 + 签名 + LRU + single-flight
├── access.py         # ensure_repository_readable + exclusion 收口
└── signature.py      # （可选，Claude's Discretion）签名计算独立出来便于单测

server/tests/services/code_graph/    # 新目录
├── __init__.py       # 见 §Pitfall 11（本仓两种约定并存，建议加）
├── conftest.py       # 本地 fixture（tests/codegraph/conftest.py 的 fixture 跨目录不可见）
├── test_model.py
├── test_loader.py
├── test_signature.py
├── test_cache.py     # 命中 / 失效 / LRU 逐出 / single-flight
└── test_access.py    # exclusion + 权限 fail-closed
```

`services/code_intel/` 的实际结构是 `__init__.py / apps.py / protocols.py / registry.py / local_provider.py / null_provider.py` [VERIFIED: `ls services/code_intel/`]——即「契约 + 实现 + 注册」三层。本相位不需要 `registry.py`（只有一个实现）也不需要 `apps.py`（无 Django app 生命周期钩子）。

### Pattern 1: ORM 独占 + 一次性 sync_to_async 包裹

**What:** public API 全 async，全部 ORM 与 CPU 装配集中在**一个** `sync_to_async` 包裹的同步函数里。
**When to use:** 本相位的每一次建图。
**Why：** 每次 `sync_to_async` 跳转都是一次线程切换 + 上下文拷贝；四类边分四次跳转是纯浪费。更重要的是——**同步侧可以放心用 `threading` 锁而不必担心 await-under-lock**（见 §Threading Model）。

先例：`services/chunk_lookup.py`（public `find_chunk_at` 全 async，ORM 收进 `@sync_to_async def _query_covering_chunks`）[VERIFIED: `server/services/chunk_lookup.py:84-110`]。

### Pattern 2: `values_list(...).iterator(chunk_size=…)` 而非模型实例化

**What:** 取数一律 `.values_list()` 出元组，配 `.iterator(chunk_size=5000)`。
**Why:** 跳过 Django 模型实例化（每个 `Symbol` 实例带 `_state`、字段描述符、deferred 追踪），10 万级行数下这是数量级差异；`.iterator()` 同时避免 QuerySet 把整个结果集缓存进 `_result_cache`。Postgres 上 `chunk_size` 走服务端游标。

FK 列**必须**写成 `caller_symbol_id`（attname）而不是 `caller_symbol`——前者直接取列不产生 JOIN。

### Pattern 3: 签名失效（照抄 Galaxy，改内存比对）

`GalaxyGraphCache.compute_signature` 的范式是「每张源表一条 `COUNT` + 一条 `MAX(时间戳)`，拼成字符串再 SHA256」[VERIFIED: `server/codegraph/galaxy/cache.py:87-104`]。本相位复用**思路**但换构成分量（见 §Code Examples 2）——Galaxy 只需回答「数据变了吗」，本服务额外要回答「边建完了吗」。

### Anti-Patterns to Avoid

- **在持有 `threading` 锁的状态下 `await`** — 见 §Pitfall 7，会阻塞 event loop 甚至死锁。
- **把 `ChunkEdge` 展开成符号级笛卡尔积** — 见 §Pitfall 2。
- **上层工具直连 `loader`** — CONTEXT 明确列为架构红线；`__init__.py` 不导出即为机械防线。
- **在装配循环里打 INFO 日志** — 违反 `.cursor/rules/observability-logging.mdc` 的级别纪律，规范正文点名过同款事故。
- **未索引仓返回空图** — CONTEXT 明确：空图会被上层误读为「没有影响」，必须显式抛错。
- **把 `Symbol.signature`（TextField，可长达数 KB）放进节点属性** — 见 §Byte Estimation。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 排除规则判定 | 自己 glob/regex 匹配 `file_path` | `services/exclusion.py::build_matcher_for_repo` / `ExclusionMatcher.is_excluded` | 模块 docstring 明写它是「排除判定的**唯一事实源**」；内含 ReDoS 静态拒绝、大小写不敏感的 global 规则、basename 兜底匹配、运行期异常 fail-closed 四层语义，重写必漏 [VERIFIED: `server/services/exclusion.py:1-13, 209-236`] |
| 相对路径归一 | 自己 `os.path.normpath` | `services/exclusion.py::normalize_rel_path` | 绝对路径 / `..` 越界 / 空路径统一返 `None` 让调用方 fail-closed；与 qdrant `file_path` payload 口径对齐 |
| 排除拦截审计埋点 | 自己 `logger.info` | `services/exclusion.py::log_exclusion_blocked` | 事件名 `exclusion.blocked` 已是全仓统一审计面 |
| 签名/失效范式 | 自己设计 | 照抄 `GalaxyGraphCache.compute_signature` 结构 | 已在生产验证；照抄结构让两套缓存的排障心智一致 |
| LRU + 池上限 + 逐出埋点 | 从零写 | 照抄 `codegraph/lsp/volar_pool.py` | 该文件就是「`OrderedDict` + `threading.Lock` + `move_to_end` + 超限逐出 + 逐出结构化事件 + 模块级单例工厂」的完整实现，与本相位需求近乎同构 [VERIFIED: `server/codegraph/lsp/volar_pool.py:63-64, 103-109, 193`] |
| 后台线程 + 独立 loop | 自己起线程 | `services/background_runner.py::run_in_background` | 已解决 `CurrentThreadExecutor already quit` 类问题，且支持 `initiated_by_user_id` 绑定 |
| 异常文本脱敏 | 自己写正则 | `common/logging.py::redact_secrets_in_text` | 规范强制 |
| 图算法（BFS/最短路） | 自己写遍历 | networkx 内置（**带 `depth_limit`**） | 见 §Pitfall 10——自己写容易，写对边界很难；但 networkx 也有陷阱 |

**Key insight:** 本相位真正的新代码只有三样——**签名的构成**、**single-flight 的等待原语**、**字节估算常数**。其余一切都有本仓先例可照抄。计划的复杂度预算应当压在这三样上，其他任务都该是「参照 X 文件的写法」。

## Byte Estimation（实测标定）

> 本节回答 research focus #5：线性模型是否 sane，常数怎么标。
> 全部数据 [VERIFIED: 本次在 `server/.venv` 内实测，networkx 3.6.1 / CPython 3.14.2 / macOS arm64，`tracemalloc` 计量]

### 线性模型验证：结论是**可靠**

用 `DiGraph`、5 个节点属性、4 个边属性、UUID 字符串节点键、边数 = 节点数 × 3：

| nodes | edges | 实测 | `n*598 + e*288` 预测 | 误差 |
|-------|-------|------|---------------------|------|
| 10,000 | 30,000 | 14.86 MB | 14.62 MB | −1.6% |
| 50,000 | 150,000 | 76.93 MB | 73.10 MB | −5.0% |
| 100,000 | 300,000 | 153.90 MB | 146.20 MB | −5.0% |
| 200,000 | 600,000 | 307.87 MB | 292.40 MB | −5.0% |

**误差在 20 倍规模跨度上恒定为 −5.0%**——这正是线性模型可用的最强证据：偏差是系统性的常数比例，不是随规模发散的。把常数上调 5.3%（`×1.053`）即可把预测精度收进 ±1%。

### 推荐常数

`MultiDiGraph` 的边比 `DiGraph` 贵 **+224 B/边**（同为 100k 节点 / 300k 边 / 4 边属性：153.88 MB → 221.08 MB，**+44%**）。

```python
# 标定自 networkx 3.6.1 / CPython 3.14 / MultiDiGraph / UUID 字符串节点键。
# 测量方式：tracemalloc 峰值增量，10k–200k 节点跨度上线性误差恒为 -5%，已含 5% 安全裕度。
# 形态假设：节点 ≤5 个属性、边 ≤3 个属性；超出会低估（见下方属性敏感性表）。
# ⚠️ 常数必须在本相位的「最大仓实测」交付物中复校，并按 RSS（非 tracemalloc）修正。
NODE_COST_BYTES = 640   # 实测 598 × 1.05 ≈ 630，取整到 640 更保守
EDGE_COST_BYTES = 560   # MultiDiGraph 实测 ~515（3 属性）× 1.05 ≈ 540，取整到 560
```

### 属性数量敏感性（真正的省内存杠杆）

100k 节点 / 300k 边 / `DiGraph`，只变属性个数：

| 边属性个数 | 总内存 | 相对 0 属性 |
|---|---|---|
| 0 | 111.03 MB | — |
| 1 | 147.03 MB | +120 B/边 |
| 2 | 147.03 MB | +120 B/边 |
| 3 | 147.03 MB | +120 B/边 |
| **4** | **153.88 MB** | **+143 B/边** |

| 节点属性个数 | 总内存 | 相对 0 属性 |
|---|---|---|
| 0 | 124.81 MB | — |
| 2 | 142.90 MB | +181 B/节点 |
| 3 | 149.25 MB | +244 B/节点 |
| 5 | 153.88 MB | +291 B/节点 |

**这是一个阶跃函数，不是线性的**：1–3 个边属性成本完全相同（CPython 小字典预分配 8 槽，容纳 5 个条目），第 4 个属性才跳一级。

**可执行结论：把边属性控制在 3 个以内是免费的。** 推荐边只存 `kind` / `confidence` / `line_number` 三项，把 CONTEXT 要求的 `reason` 字符串**在输出时按 `(kind, confidence)` 现推**而不是每条边存一份——300k 边省 6.9 MB，且 `reason` 本来就是给人看的展示文案，不参与任何计算。

### 两个被证伪的"优化"（别浪费预算）

- **字符串驻留 `file_path`**：只省 6.3 MB / 4%。不值得为此增加一层池化代码。
- **把 UUID 字符串键换成 int 索引**：实测**反而多用 12.5 MB**（158.64 vs 146.18 MB）。反直觉，但数据如此——不要在没有实测的情况下把它当优化做。

### 建图耗时（`MultiDiGraph`，无 tracemalloc 干扰）

| nodes | edges | add_nodes | add_edges | 总建图 |
|---|---|---|---|---|
| 20,000 | 60,000 | 52 ms | 201 ms | **253 ms** |
| 100,000 | 300,000 | 479 ms | 1,586 ms | **2,066 ms** |
| 200,000 | 600,000 | 622 ms | 3,412 ms | **4,034 ms** |

这还**不含** ORM 取数时间。10 万符号级仓库一次冷建图约 2 秒纯 CPU（持 GIL），20 万级约 4 秒。这正是 single-flight + LRU 存在的理由，也是「超预算大仓走按需子图」不是可选项而是必需项的理由。

### 预算含义（计划必须知道的算术）

按 `NODE_COST=640 / EDGE_COST=560`、边:节点 = 3:1：

- 单图 = `n × (640 + 3×560)` = `n × 2320` 字节。
- `CODE_GRAPH_MAX_GRAPH_BYTES = 256 MB` → **单仓约 11 万符号即触顶**走降级。
- `CODE_GRAPH_CACHE_MAX_BYTES = 512 MB` → 只装得下 **约 2 张**接近上限的大图（或若干中小图）。
- 且这是 **per worker**。4 个 worker = 最坏 2 GB 常驻。

CONTEXT 说「先落保守值不盲设大」是对的，但计划应当**显式记录这个算术**，让本相位的实测交付物直接回答「本仓最大仓落在这条曲线的哪个位置」。

> **诚实声明：** `tracemalloc` 计的是 Python 分配器请求的字节数，**不含 arena 碎片与解释器开销**，真实 RSS 通常更高。实测交付物应同时记录 RSS 增量（`resource.getrusage` 或 `psutil`），若 RSS/tracemalloc 比值显著 > 1，需再上调常数。

## Common Pitfalls

### Pitfall 1: `CrossRepoApiCall` 两端都不是 `Symbol`，也没有 repository 外键

**What goes wrong:** 按 CONTEXT 字面「装配 `CrossRepoApiCall` 为边」直接开做，会发现两端接不上图里的符号节点。

**Root cause** [VERIFIED: `server/codegraph/models.py:263-338`]：

- `CrossRepoApiCall` 只有两个 FK：`call_site → ApiCallSite`、`endpoint → Endpoint`。
- `ApiCallSite` 有 `caller_file`（CharField）、`caller_function`（CharField）、`line_number`——**没有 `Symbol` FK**，而且**没有 `branch_name` 字段**。
- `Endpoint` 有 `file_path`、`handler_name`、`line_number`、`branch_name`——同样**没有 `Symbol` FK**。
- `CrossRepoApiCall` 自己**没有 `repository` 字段**；按仓库过滤必须走 `call_site__repository_id` 或 `endpoint__repository_id`（`GalaxyGraphCache` 就是这么做的：`("cross_repo_api_call", CrossRepoApiCall, "call_site__repository_id", "matched_at")` [VERIFIED: `server/codegraph/galaxy/cache.py:62`]）。

**How to avoid:** 计划里必须有一个**显式任务**做「跨仓边端点解析」：用 `(file_path, name)` 对着已装载的 `Symbol` 节点表做二次匹配（`ApiCallSite.caller_file` + `caller_function` → Symbol；`Endpoint.file_path` + `handler_name` → Symbol），匹配不上的端点要么丢弃要么建虚拟节点——**这个决策 CONTEXT 没覆盖，是 planner 必须补的**。同时因为 `ApiCallSite` 无 `branch_name`，跨仓边**无法按分支过滤**，这个语义缺口必须在图元数据里如实声明。

**Warning signs:** 装配后 `cross_repo` 边数为 0 但 DB 里 `CrossRepoApiCall` 有行。

### Pitfall 2: 把 `ChunkEdge` 展开成符号级边会笛卡尔爆炸

**What goes wrong:** `ChunkEdge` 连的是 `source_chunk_id` / `target_chunk_id`（UUID 软引用，无 FK）[VERIFIED: `server/code_relations/models.py:127-129`]。要挂到符号上，只能靠 `Symbol.chunk_id`（同样是软引用，`null=True`）反查。但**一个 chunk 通常含多个 Symbol**——一条 chunk 边在两端各有 k 个符号时，展开成符号级就是 k² 条边。

**Root cause:** chunk 与 symbol 是不同粒度，`chunk_id` 是多对一。

**How to avoid:** CONTEXT 已经给了正确答案（「装配但默认不参与符号级扩散，仅作为补充证据面」）——计划必须把它实现成**独立的旁挂数据面**（例如 `CodeGraph.chunk_evidence: dict[symbol_id, list[chunk_edge_record]]`），**绝不**写进 `MultiDiGraph` 的边集。若真要写进图，必须先做去重与 fan-out 上限。

**Warning signs:** 边数远大于 `CallEdge.count() + CrossRepoApiCall.count()`；内存估算严重偏低。

### Pitfall 3: feature 分支的图必须是 overlay（base ∪ feature），不是 feature-only

**What goes wrong:** 照 CONTEXT 的缓存键 `(repository_id, branch_name)` 直接 `filter(branch_name="feature/x")`，得到的图只含**该分支改动过的文件**里的符号——绝大多数调用边的另一端在 base 上，图会碎成一地。

**Root cause:** 本仓的分支语义是 **overlay**：`""` 是 base 全量，feature 分支只写增量行。既有代码的标准写法是 `branch_filter = ["", branch_name] if branch_name else [""]` [VERIFIED: `server/services/code_intel/local_provider.py:55`]。

**How to avoid:** loader 按 `branch_name__in=["", branch]`（branch 非空时）取数，并对同 `(file_path, name, start_line)` 的重复符号做「feature 覆盖 base」的去重。CONTEXT 只说了「沿用既有模型语义」，**没有明确 overlay 与去重规则**——planner 必须把它定死。

**内存含义：** overlay 意味着每个缓存的 feature 分支图都是「一整张 base 图 + 增量」，不是小增量。预算算术要按这个来。

### Pitfall 4: `IndexHistory.graph_build_status` 默认就是 `PENDING`，照字面判 in-flight 会让降级标记长鸣

**What goes wrong:** CONTEXT 写「`graph_build_status ∈ {PENDING, RUNNING}` 即判定边构建在途 → 打 `partial_edges: true`」。直接实现的后果是：**从未触发过边构建的仓库会被永久标记为半新图**。

**Root cause** [VERIFIED: `server/repositories/models.py:421-426` + `server/code_relations/lifecycle.py`]：

- `IndexHistory.graph_build_status` 的模型默认值就是 `GraphBuildStatus.PENDING`。
- 只有走 `enqueue_edge_build_for_history` 的路径才会把它推进到 RUNNING/COMPLETED/FAILED/SKIPPED。
- 该函数在 `history_id is None` 时**直接透传、完全跳过 lifecycle 更新**（`lifecycle.py` 的 docstring 明写「保兼容无 history 调用方」）。
- `ENABLE_CODEGRAPH=False` 或 `auto_build_graph_enabled=False` 的仓库同样不会推进。

**How to avoid:** in-flight 判定必须复合：只有当最近一条 `IndexHistory` 的 `graph_build_status ∈ {PENDING, RUNNING}` **且** 该行自身的 `IndexHistory.status ∈ {PENDING, RUNNING}` **且** `started_at` 在超时窗口内，才判为在途。`SKIPPED` 与 `IndexHistory.status` 终态一律视为不在途。

**Warning signs:** 所有仓库的图元数据都带 `partial_edges: true`。

### Pitfall 5: RUNNING 状态会留孤儿行，in-flight 判定必须带超时

**What goes wrong:** 一个卡住的 RUNNING 行会让该仓库**永久**拒绝使用缓存、每次查询都重建图。

**Root cause:** 这是本仓已知且已有对策的问题——`settings.py` 里存在 `GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP`（默认 True）与 `GRAPH_BUILD_ORPHAN_TIMEOUT_MINUTES`（默认 30），注释明写「后台构建任务随进程内存存活，无法跨进程重启幸存……避免幽灵 RUNNING 行永久卡住」[VERIFIED: `server/friday/settings.py` codegraph 区块]。

**How to avoid:** in-flight 判定复用同一个超时常量（`GRAPH_BUILD_ORPHAN_TIMEOUT_MINUTES`），超时的 RUNNING 不算在途。**不要**为此新增一个配置项——复用既有语义。

### Pitfall 6: `RepositoryBranchIndex.branch_name` 从不是 `""`；`Symbol.branch_name` 的 base 才是 `""`

**What goes wrong:** 按缓存键的 `branch_name=""` 去查 `RepositoryBranchIndex.objects.filter(branch_name="")` → 永远查不到 → 水位永远回落到 `Repository.last_indexed_commit_sha`，`RepositoryBranchIndex` 分量形同虚设。

**Root cause:** 两个模型的分支语义**不同**：

- `Symbol` / `CallEdge` / `ChunkEdge` / `Endpoint`：`branch_name = CharField(default="")`，`""` 表示 base [VERIFIED: `server/codegraph/models.py:33`]。
- `RepositoryBranchIndex`：`branch_name` 存**真实分支名**，base 由 `is_base_branch=True` 标识。indexer 写入时用的是 `_update_branch_index_record(branch_name=base_branch, is_base_branch=True)` [VERIFIED: `server/services/indexer.py:1310-1316`]。

**How to avoid:** 水位查询做键翻译——`branch == ""` 时查 `filter(repository_id=…, is_base_branch=True)`；`branch != ""` 时查 `filter(repository_id=…, branch_name=branch)`。

### Pitfall 7: 在持有 `threading` 锁的状态下 `await`

**What goes wrong:** `threading.Lock` 是阻塞原语。持锁时 `await`，协程让出控制权但锁还在手上；同一 loop 上的另一个协程跑到同一段代码就会**同步阻塞整个 event loop 线程**——不只是它自己卡住，整个 worker 停摆。若被 await 的工作本身需要该锁（例如 `sync_to_async` 排到同一个 thread-sensitive 执行器），就是死锁。

**How to avoid:** 见 §Threading Model——推荐的做法是把整段临界区做成同步函数，由 `cache.py` 一次性 `sync_to_async` 包裹，让「持锁」与「await」在物理上不可能同时发生。

### Pitfall 8: `asyncio.Event` 在本仓跨 loop 不可用

**What goes wrong:** 用 `asyncio.Event` 做 single-flight，在单元测试里一切正常，生产上偶发 `RuntimeError: ... is bound to a different event loop`。

**Root cause:** 本仓同时存在至少三类 event loop：ASGI 主循环、`background_runner` 的常驻 daemon 线程循环（`server/services/background_runner.py:74-99` [VERIFIED]）、workflow engine 的 `_run_in_thread` 循环（`ARCHITECTURE.md` 明载）。`asyncio.Event` 绑定创建它的 loop。一个进程内单例缓存会被三类 loop 共用。

**How to avoid:** single-flight 的等待信号用 **`threading.Event`**（loop 无关），异步侧用 `await asyncio.to_thread(ev.wait, timeout)` 等待。

### Pitfall 9: `_matcher_cache` 是无锁模块字典，且 TTL 不是版本号

**What goes wrong:** 想用 exclusion 的缓存状态当规则版本号，或假设 matcher 是线程安全的。

**Root cause** [VERIFIED: `server/services/exclusion.py:33-34, 343-361`]：`_matcher_cache: dict[str, tuple[float, ExclusionMatcher]]` 是裸模块字典，无锁保护（并发下只会重复构造，属良性竞态）；60s TTL 只控制**何时重建 matcher**，不产生任何可比对的版本标识。规则改了但 TTL 未到时，`build_matcher_for_repo` 仍返回旧 matcher。

**How to avoid:** 自算指纹（见 §Code Examples 5）。因为 loader 无论如何都要拿到有效规则集，对规则集直接哈希是**免费且精确**的——它同时覆盖 per-repo 规则、`SystemSetting` 全局 JSON、以及 `BUILTIN_GLOBAL_DEFAULTS` 的代码变更，比任何基于时间戳的方案都严密。

### Pitfall 10: `list(nx.bfs_layers(G, src))[:depth]` 会遍历整个可达分量

**What goes wrong:** 看似做了深度截断，实际把整张图走完了。实测 100k 节点 / 300k 边：

| 写法 | 耗时 | 结果 |
|---|---|---|
| `list(nx.bfs_layers(rg, [seed]))[:4]` | **97.3 ms** | 23 节点 |
| `itertools.islice(nx.bfs_layers(rg, [seed]), 4)` | **0.0 ms** | 23 节点 |
| `nx.bfs_tree(rg, seed, depth_limit=3)` | **0.6 ms** | 23 节点 |

[VERIFIED: 本次实测] 同样结果，**1000 倍以上**的耗时差。

**Root cause:** `bfs_layers` 是生成器，`list()` 先物化全部层再切片。

**How to avoid:** 用 `depth_limit=` 参数或 `itertools.islice`。虽然图算法本体属 Phase 122，但**本相位的降级路径「按需子图」就要做多跳收敛**，会直接踩到；且这条纪律应写进 `model.py` 的模块 docstring 传给下游相位。

**附带发现：** `G.reverse(copy=False)` 返回只读反向视图，实测建视图 0.1 ms（`copy=True` 需要完整复制，内存翻倍）。反向 BFS 用 `copy=False` 视图即可。

### Pitfall 11: `server/tests/codegraph/conftest.py` 的 fixture 在 `tests/services/code_graph/` 里看不到

**What goes wrong:** 计划里写「复用既有 `graph_repo` / `seed_symbol` / `caller_symbol` fixture」，执行时 `fixture 'graph_repo' not found`。

**Root cause:** pytest 的 `conftest.py` 作用域是**所在目录及其子目录**。`tests/codegraph/conftest.py` 与 `tests/services/code_graph/` 是兄弟分支，互不可见。

**额外陷阱：** 即便显式 import，`graph_repo` fixture 创建的 `Repository` **没有设 `index_status`**，默认是 `NOT_INDEXED` [VERIFIED: `server/tests/codegraph/conftest.py:23-30` + `server/repositories/models.py:195-199`]——而 `ensure_repository_readable` 要求 `INDEXED`，所有测试会在第一道闸就挂掉。

**How to avoid:** 在 `tests/services/code_graph/conftest.py` 里自建 fixture，显式设 `index_status=IndexStatus.INDEXED`。

**目录约定：** 本仓两种写法并存——`tests/services/retrieval/__init__.py` 存在，`tests/services/process_runtime/` 没有 [VERIFIED: `ls`]。两种都能跑，建议加 `__init__.py` 与 `tests/codegraph/` 保持一致。

## Threading Model

> 回答 research focus #6。

### 本仓既有先例（模块级单例 + `threading` 锁是主流做法）

| 位置 | 形态 |
|---|---|
| `codegraph/lsp/volar_pool.py:63-64, 193` | `OrderedDict` + `threading.Lock` + `move_to_end` LRU + `_SINGLETON_LOCK` 工厂 — **与本相位近乎同构** |
| `codegraph/lsp/__init__.py:35` | `_LOCK = threading.Lock()`，per-name 单例工厂 |
| `services/background_runner.py:57` | `_lock = threading.Lock()` 守 worker 线程懒启动 |
| `durable/backends.py:77` | `_jobs_lock = threading.Lock()` |
| `system/log_sink.py:40,60`、`system/metric_sink.py:38,50`、`common/log_buffer.py:27` | 同款模块级锁 |
| `codegraph/lsp/supervisor.py:141`、`gopls_backend.py:505`、`node_check.py:62`、`go_check.py:62` | 同款 |

[VERIFIED: `grep -n "threading\.(Lock|RLock|Event)" server/**/*.py`]

**结论：模块级单例 + `threading` 锁在本仓是既定范式，安全且有 11 处先例。** 计划不需要论证这个选择，直接照 `volar_pool.py` 抄结构即可。

### 关键约束：三类 event loop 并存

| Loop | 来源 |
|---|---|
| ASGI 主循环 | `friday/asgi.py`，uvicorn/daphne |
| `background_runner` 常驻循环 | daemon 线程 `friday-bg-runner`，`asyncio.new_event_loop()` + `run_forever` [VERIFIED: `background_runner.py:74-99`] |
| workflow engine 线程循环 | `workflows/engine/scheduler.py::_run_in_thread`（每次执行起独立 loop）[CITED: `ARCHITECTURE.md`] |

`GraphService` 是**进程级**单例，会被这三类循环共用。因此：

- ❌ `asyncio.Lock` / `asyncio.Event` / `asyncio.Condition` — 全部 loop-bound，不可用。
- ✅ `threading.Lock` / `threading.RLock` / `threading.Event` — loop 无关。

### 推荐实现形态：把临界区整体做成同步

最省心的写法是让「持锁」和「await」在物理上不可能重叠：

```python
# cache.py —— public API 是 async，但整个取图链路是一次 sync_to_async
async def get_graph(self, repository_id: str, branch: str = "", *, user=None) -> CodeGraph:
    await ensure_repository_readable(user, repository_id)       # 唯一的异步前置（ORM 少量查询）
    return await sync_to_async(self._get_graph_sync)(repository_id, branch)

def _get_graph_sync(self, repository_id: str, branch: str) -> CodeGraph:
    """全同步：锁、ORM、networkx 装配都在这里，不存在 await-under-lock 的可能。"""
    ...
```

**为什么 `thread_sensitive=True`（默认）是对的：** 本仓 `lifecycle.py` 明确注释「`thread_sensitive=True`（默认）：在 Django 主线程跑 sync ORM 调用，避免 SQLite 多线程写锁竞争（test_db 单文件锁；prod Postgres 不受影响）」[VERIFIED: `server/code_relations/lifecycle.py:52-55`]。全仓 ORM 调用一致使用默认值，本相位不应例外。

**诚实的代价：** `thread_sensitive=True` 意味着所有此类调用共享同一个执行器线程，一次 2–4 秒的大图装配会**阻塞该执行器上的其他 ORM 工作**。这是真实的、必须写进计划风险栏的取舍。三层缓解：① single-flight 保证同一 key 只建一次；② LRU 保证建过就不重建；③ 超预算大仓走按需子图（这才是大仓不拖垮进程的真正防线，不是可选优化）。

### single-flight 的等待原语

若最终选择「异步等待占位」而非「整体同步」，等待侧必须是：

```python
placeholder: threading.Event = ...            # loop 无关
done = await asyncio.to_thread(placeholder.wait, timeout)   # 不阻塞 event loop
if not done:
    raise GraphBuildTimeout(...)
```

⛔ 不要在协程里直接 `placeholder.wait()`——那会同步阻塞整个 loop 线程。
⛔ 不要用 `asyncio.Event`——见 Pitfall 8。

**超时是必需的**，不是可选：single-flight 的领头请求若被 kill（如 ASGI 断连取消），等待者不能永久挂起。

## Code Examples

### 1. 四类数据的 ORM 查询形状（GRAPH-01）

> 回答 research focus #1。字段名逐一对照 `server/codegraph/models.py` 与 `server/code_relations/models.py` 核实。

```python
# loader.py —— 全部在一个 sync_to_async 包裹的同步函数内执行

# ---- 准入计数（装配前，防 OOM；毫秒级带索引聚合）----
branch_filter = ["", branch] if branch else [""]     # overlay 语义，见 Pitfall 3
n_symbols = Symbol.objects.filter(
    repository_id=rid, branch_name__in=branch_filter
).count()
n_calls = CallEdge.objects.filter(
    repository_id=rid, branch_name__in=branch_filter
).count()

# ---- 节点：Symbol ----
# 索引覆盖：Index(fields=["repository","branch_name","file_path"]) 的前缀 (repository, branch_name)
# ⚠️ 不取 signature —— TextField 可达数 KB，节点属性放它会让内存估算彻底失准
symbol_rows = (
    Symbol.objects
    .filter(repository_id=rid, branch_name__in=branch_filter)
    .values_list(
        "id", "name", "symbol_type", "file_path",
        "start_line", "end_line", "is_async", "chunk_id",
    )
    .iterator(chunk_size=5000)
)

# ---- 边：CallEdge ----
# 索引覆盖：Index(fields=["repository","branch_name","caller_file"]) 的前缀
# ⚠️ FK 一律用 attname（*_id）取列，避免隐式 JOIN
call_rows = (
    CallEdge.objects
    .filter(repository_id=rid, branch_name__in=branch_filter)
    .values_list(
        "caller_symbol_id",     # nullable：模块级调用为 NULL，用 caller_file 兜底
        "callee_symbol_id",     # nullable：NULL ⇒ bare_name 档；非 NULL ⇒ resolved 档
        "caller_file", "callee_name", "callee_file", "callee_qualifier",
        "call_type", "line_number",
    )
    .iterator(chunk_size=5000)
)
# ⚠️ CallEdge 上没有 match_confidence 字段（全仓仅 CrossRepoApiCall 有）。
#    resolved / bare_name 的判据是 callee_symbol_id 是否为 NULL。

# ---- 旁挂证据面：ChunkEdge（不进 MultiDiGraph，见 Pitfall 2）----
# 索引覆盖：idx_chunkedge_branch_fanout (repository, branch_name, source_chunk_id) 前缀
chunk_edge_rows = (
    ChunkEdge.objects
    .filter(repository_id=rid, branch_name__in=branch_filter)
    .values_list(
        "source_chunk_id", "target_chunk_id", "edge_type",
        "weight", "target_repository_id",
    )
    .iterator(chunk_size=5000)
)

# ---- 跨仓边：CrossRepoApiCall（无 repository FK，无 Symbol FK，见 Pitfall 1）----
from django.db.models import Q
cross_rows = (
    CrossRepoApiCall.objects
    .filter(Q(call_site__repository_id=rid) | Q(endpoint__repository_id=rid))
    .values_list(
        "call_site__repository_id",
        "call_site__caller_file",       # ← 只有字符串，需二次解析到 Symbol
        "call_site__caller_function",
        "call_site__line_number",
        "endpoint__repository_id",
        "endpoint__file_path",
        "endpoint__handler_name",       # ← 同上
        "endpoint__http_method",
        "endpoint__url_path",
        "endpoint__branch_name",        # 注意 ApiCallSite 侧没有 branch_name
        "match_confidence",             # 1.0 / 0.7 / 0.4 三档，原值透传不归一化
    )
    .iterator(chunk_size=2000)
)
```

**Source:** 字段清单逐项核对 `server/codegraph/models.py:25-60`（Symbol）、`:121-167`（CallEdge）、`:308-332`（CrossRepoApiCall）、`server/code_relations/models.py:127-190`（ChunkEdge）。`values_list + iterator` 的批量取数范式先例见 `server/services/code_intel/local_provider.py:61`。

### 2. 复合签名（GRAPH-02）

> 回答 research focus #2。**关键发现：本仓有两条互相独立的「边构建」轨，签名必须同时纳入。**

| 轨 | 跟踪对象 | 状态字段 | 时间戳 | 写入方 |
|---|---|---|---|---|
| **A** | `ChunkEdge`（code_relations） | `IndexHistory.graph_build_status`（`GraphBuildStatus`：PENDING/RUNNING/COMPLETED/FAILED/**SKIPPED**） | `IndexHistory.finished_at` / `payload_synced_at` | `code_relations/lifecycle.py::enqueue_edge_build_for_history` |
| **B** | `Symbol`/`CallEdge`/`Endpoint` 抽取 | `Repository.graph_build_status`（`RepositoryGraphStatus`：IDLE/RUNNING/COMPLETED/FAILED/**CANCELLED**，⚠️ **无 PENDING/SKIPPED**） | `Repository.graph_last_built_at`；更细可用 `GraphBuildHistory.finished_at` | `services/graph_builder.py::{reset_repository_graph_progress, mark_repository_graph_terminal}` |

[VERIFIED: `server/repositories/models.py:72-83`（GraphBuildStatus 枚举）、`:114-128`（RepositoryGraphStatus 枚举）、`:258-288`（Repository 图字段）、`:421-445`（IndexHistory 图字段）、`:490-495 区段` 的 `started_at`/`finished_at`/`created_at`；`server/services/graph_builder.py:249-310`]

⚠️ CONTEXT 只提到轨 A（`IndexHistory`）。**只看轨 A 会漏掉「Symbol/CallEdge 被重新抽取但 ChunkEdge 没变」的失效场景**——而 `CallEdge` 恰恰是本相位图的主边源。计划必须两轨都纳入。

`GraphBuildHistory` 是比 `Repository.graph_last_built_at` 更好的轨 B 代数源：它有 `branch_name`、`status`、`started_at`（`default=timezone.now`）、`finished_at`、以及 `symbols_count`/`calls_count`/`endpoints_count`，且 `Meta.ordering = ["-started_at"]` + `Index(fields=["repository","-started_at"])` [VERIFIED: `server/repositories/models.py:516-551, 164-172`]，取最近一条是索引命中的。

```python
def compute_signature(repository_id: str, branch: str) -> str:
    """内存比对用的复合签名。全部为带索引的 COUNT / 单行取值，毫秒级。"""
    parts: list[str] = []

    # ① 水位 —— 注意 RepositoryBranchIndex.branch_name 从不为 ""（见 Pitfall 6）
    bi_qs = RepositoryBranchIndex.objects.filter(repository_id=repository_id)
    bi = (bi_qs.filter(is_base_branch=True) if not branch
          else bi_qs.filter(branch_name=branch)).values_list(
              "last_indexed_commit_sha", "last_indexed_at",
          ).first()
    if bi and bi[0]:
        parts.append(f"wm:{bi[0]}:{bi[1].isoformat() if bi[1] else '-'}")
    else:
        repo_sha = Repository.objects.filter(id=repository_id).values_list(
            "last_indexed_commit_sha", flat=True,
        ).first()
        parts.append(f"wm:{repo_sha or '-'}")

    # ② 轨 A 代数：ChunkEdge 构建（IndexHistory，ordering = ["-created_at"]）
    ih = IndexHistory.objects.filter(repository_id=repository_id).values_list(
        "id", "graph_build_status", "status", "finished_at",
        "payload_synced_at", "edge_count",
    ).first()
    parts.append("ihA:" + ":".join(str(x) for x in (ih or ("-",) * 6)))

    # ③ 轨 B 代数：Symbol/CallEdge 抽取（GraphBuildHistory，ordering = ["-started_at"]）
    gh = GraphBuildHistory.objects.filter(
        repository_id=repository_id, branch_name=branch,
    ).values_list(
        "id", "status", "finished_at", "symbols_count", "calls_count",
    ).first()
    parts.append("ghB:" + ":".join(str(x) for x in (gh or ("-",) * 5)))
    #    兜底（无 history 行的老仓）：
    repo_g = Repository.objects.filter(id=repository_id).values_list(
        "graph_build_status", "graph_last_built_at",
    ).first()
    parts.append(f"repoG:{repo_g}")

    # ④ 计数分量（照 Galaxy 的 count 思路；捕捉 lifecycle 完全没跑的写入）
    bf = ["", branch] if branch else [""]
    parts.append(f"nsym:{Symbol.objects.filter(repository_id=repository_id, branch_name__in=bf).count()}")
    parts.append(f"ncall:{CallEdge.objects.filter(repository_id=repository_id, branch_name__in=bf).count()}")

    # ⑤ exclusion 规则指纹（见 Example 5）
    parts.append(f"excl:{exclusion_rules_fingerprint(repository_id)}")

    return hashlib.sha256("|".join(parts).encode()).hexdigest()
```

**Source:** 结构照 `server/codegraph/galaxy/cache.py:87-104`；字段来自上表逐项核实。

### 3. in-flight 判定（GRAPH-02 最难的一半）

> 回答 research focus #3。必须同时躲开 Pitfall 4（PENDING 长鸣）与 Pitfall 5（RUNNING 孤儿）。

```python
def detect_edge_build_in_flight(repository_id: str, branch: str) -> tuple[bool, str]:
    """返回 (是否在途, 原因)。在途 ⇒ 图元数据打 partial_edges: true。"""
    from django.conf import settings
    from django.utils import timezone
    from datetime import timedelta

    timeout_min = getattr(settings, "GRAPH_BUILD_ORPHAN_TIMEOUT_MINUTES", 30)  # 复用既有语义
    cutoff = timezone.now() - timedelta(minutes=timeout_min)

    # ---- 轨 B：Symbol/CallEdge 抽取（Repository 枚举里 in-flight 只有 RUNNING，无 PENDING）----
    repo = Repository.objects.filter(id=repository_id).values_list(
        "graph_build_status", "index_status",
    ).first()
    if repo and repo[0] == RepositoryGraphStatus.RUNNING:
        recent = GraphBuildHistory.objects.filter(
            repository_id=repository_id,
            status=GraphBuildHistoryStatus.RUNNING,
            started_at__gte=cutoff,          # 超时的 RUNNING 视为孤儿，不算在途
        ).exists()
        if recent:
            return True, "symbol_extraction_running"
    if repo and repo[1] == IndexStatus.INDEXING:
        return True, "indexing"

    # ---- 轨 A：ChunkEdge 构建 ----
    ih = IndexHistory.objects.filter(repository_id=repository_id).values_list(
        "graph_build_status", "status", "started_at",
    ).first()
    if ih:
        gbs, hstatus, started = ih
        # ⚠️ PENDING 是模型默认值，单看它会永久误报（Pitfall 4）——
        #    必须要求 IndexHistory 自身也在跑，且未超时。
        if gbs in (GraphBuildStatus.PENDING, GraphBuildStatus.RUNNING) \
           and hstatus in (IndexHistoryStatus.PENDING, IndexHistoryStatus.RUNNING) \
           and started is not None and started >= cutoff:
            return True, f"chunk_edge_build_{gbs}"

    return False, ""
```

**关键点：** `SKIPPED`（空 dirty 集，`lifecycle.py:250-260` 会写这个值）必须视为**不在途**——它是正常终态。

### 4. LRU + single-flight 的结构（照抄 `volar_pool.py`）

```python
# cache.py 骨架（全同步，由 async 外壳一次性 sync_to_async 包裹）
class GraphService:
    def __init__(self, max_bytes: int, max_graph_bytes: int) -> None:
        self._cache: OrderedDict[tuple[str, str], _Entry] = OrderedDict()
        self._total_bytes = 0
        self._lock = threading.RLock()                       # 只保护 map 本身
        self._inflight: dict[tuple[str, str], threading.Event] = {}
        self._max_bytes = max_bytes
        self._max_graph_bytes = max_graph_bytes

    def _evict_until_within_budget(self) -> None:
        """调用方必须已持 self._lock。"""
        while self._total_bytes > self._max_bytes and self._cache:
            key, entry = self._cache.popitem(last=False)     # LRU 端
            self._total_bytes -= entry.estimated_bytes
            logger.info(                                     # 低频事件，INFO 可接受
                "code_graph_cache_evicted",
                component="code_graph", category="sampling",
                repository_id=key[0], branch=key[1],
                evicted_bytes=entry.estimated_bytes,
                total_bytes=self._total_bytes, reason="budget_exceeded",
            )
```

**Source:** `OrderedDict` + `move_to_end` + 超限逐出 + 逐出结构化事件的完整先例在 `server/codegraph/lsp/volar_pool.py:63-64, 103-109`。

### 5. exclusion 集成与规则指纹（GRAPH-04）

> 回答 research focus #7。

**形态核实** [VERIFIED: `server/services/exclusion.py`]：

| 符号 | 同步/异步 | 行 | 说明 |
|---|---|---|---|
| `build_matcher_for_repo(repository_id)` | **async** | 343 | 内部 `await sync_to_async(_load_specs_from_db)(...)`；60s TTL |
| `_resolve_effective_specs(repository_id)` | **sync** | 271 | 别名 `_load_specs_from_db`（310）；合并 builtin ∪ SystemSetting ∪ per-repo，并应用 global override |
| `ExclusionMatcher(specs, repository_id=…)` | sync 构造 | 157 | 构造期非法 regex 抛 `InvalidExclusionRuleError` |
| `ExclusionMatcher.is_excluded(rel_path)` | **sync** | 209 | 运行期任何异常 → 返回 True（fail-closed）+ 埋点 |
| `normalize_rel_path(path)` | sync | 117 | 越界/绝对路径/空 → `None` |
| `log_exclusion_blocked(...)` | sync | 370 | 事件名 `exclusion.blocked` |
| `invalidate_matcher_cache(repository_id=None)` | sync | 356 | |
| `_matcher_cache` | 裸模块 dict，**无锁** | 34 | 良性竞态（最多重复构造） |

**因为 loader 全同步，直接用同步侧的 `_resolve_effective_specs` 即可**，无需 async 的 `build_matcher_for_repo`：

```python
# access.py
def build_matcher_and_fingerprint(repository_id: str) -> tuple[ExclusionMatcher, str]:
    """同步构造 matcher 并顺带算出规则指纹（loader 已在同步上下文内）。

    fail-closed：构造失败让异常向上冒，由 GraphService 转 GraphAccessDenied 整仓拒绝，
    绝不「降级为不过滤」——那等于把被排除文件泄漏进所有图工具输出。
    """
    from services.exclusion import ExclusionMatcher, _resolve_effective_specs

    specs = _resolve_effective_specs(repository_id)
    # 指纹直接对有效规则集哈希：精确、免费（specs 本就要取），且自动覆盖
    # per-repo 规则 / SystemSetting 全局 JSON / BUILTIN_GLOBAL_DEFAULTS 的代码变更三个来源。
    # ⛔ 不要用 RepoExclusionRule 的 count+MAX(updated_at) —— 漏掉全局默认与内置默认的变更。
    canonical = sorted(
        (s.rule_type, s.pattern, bool(s.enabled), s.source) for s in specs
    )
    fingerprint = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False).encode()
    ).hexdigest()[:16]
    return ExclusionMatcher(specs, repository_id=repository_id), fingerprint
```

**过滤时机（CONTEXT 已锁定，此处只给实现要点）：** 在装配阶段按 `Symbol.file_path` 过滤节点，被排除节点的 id **不进节点集**；随后建边时任一端不在节点集内即整条丢弃。`normalize_rel_path` 返回 `None` 的路径同样视为排除。

⚠️ **`is_excluded` 是每节点一次的热路径调用**（10 万级）。它内部对每条 dir/glob/regex 规则跑一遍匹配。规则多时会显著拖慢装配。优化：按 `file_path` 去重后判定（同一文件的多个符号共享判定结果），用一个 `dict[str, bool]` 缓存——符号数远大于文件数，这个去重通常能省 90% 以上的调用。

**依赖的备选指纹源（若不走上面的方案）：** `RepoExclusionRule` 有 `updated_at = auto_now`（`server/repositories/models.py:892`），`SystemSetting` 有 `updated_at = auto_now` 且 `key` 是主键（`server/system/models.py:16-20`）。但如上所述，时间戳方案覆盖不到 `BUILTIN_GLOBAL_DEFAULTS` 的代码变更。

### 6. 观测埋点形态

```python
logger = structlog.get_logger(__name__)          # 规范强制

# 建图完成 —— 低频关键事件，INFO
logger.info(
    "code_graph_build_completed",
    component="code_graph",      # ⚠️ 需先补进 LOGGING-SPEC §5 注册表
    category="sampling",
    repository_id=repository_id, branch=branch,
    duration_ms=round((time.perf_counter() - started) * 1000, 2),
    node_count=n, edge_count=e,
    estimated_bytes=est, resolution_rate=rate,
    partial_edges=partial, degraded=degraded or "",
    initiated_by_user_id=user_id or "system",
)

# 缓存命中 —— 高频，DEBUG（规范：高频循环禁止 INFO 刷屏）
logger.debug("code_graph_cache_hit", component="code_graph", category="sampling", ...)

# 失败 —— 异常文本必须脱敏
from common.logging import redact_secrets_in_text
logger.warning(
    "code_graph_build_failed",
    component="code_graph", category="sampling",
    repository_id=repository_id,
    error=redact_secrets_in_text(str(exc))[:500],
    error_type=type(exc).__name__,
    duration_ms=...,
)
```

**命名冲突警告：** `services/graph_builder.py` 已占用 `graph_build_started` / `graph_build_completed` / `graph_build_failed`（[VERIFIED: `graph_builder.py:389, 525, 584`]），`galaxy/cache.py` 已占用 `galaxy_cache_*`。CONTEXT 的 `code_graph_*` 前缀与两者都不冲突，**必须保留完整前缀**，不得为了简洁缩写。

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|---|---|---|---|
| Galaxy 图谱：文件缓存 + 签名失效 | 本相位：**内存**缓存 + 签名失效 + 字节 LRU + single-flight + **取图时** in-flight 复校 | 本相位 | Galaxy 只回答「数据变了吗」；本服务额外回答「边建完了吗」——这是 GRAPH-02 相对既有先例的唯一实质增量 |
| 图查询直接打 SQL（`GraphExpansionService` 等） | 一次装配、多次复用的内存图 | 本相位 | 从 per-query N 次 SQL 到 per-(repo,branch) 一次装配 |
| `networkx` 作为 llama-index 传递依赖，应用零使用 | 提升为 `pyproject.toml` 直接依赖 | 本相位 | 防上游停止传递导致运行期 ImportError |

**Deprecated/outdated（本相位相关）:**

- `background_runner` 自 Phase 61 起**已降级**为「仅 SQLite dev fallback / 少量非持久轻任务」，生产 index/graph 走 durable 队列 [VERIFIED: `server/services/background_runner.py:3-14`]。本相位若要挂失效钩子，应挂在 `code_relations/tasks.py:224-229` 与 `services/graph_builder.py:517-521`（两处现成的 `GalaxyGraphCache.refresh_repo` 调用点），**不要**新起 background 任务。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|---|---|---|
| A1 | `tracemalloc` 计量与真实 RSS 的比值接近 1，因此 `NODE_COST=640 / EDGE_COST=560` 对 OOM 准入是安全的 | Byte Estimation | 若真实 RSS 显著更高，准入判据会放行过大的图 → 违反「进程不 OOM」硬约束。**缓解已内建**：相位交付物要求实测最大仓并复校常数，届时应同时记录 RSS |
| A2 | 生产环境的边:节点比接近 3:1（本次基准的假设） | Byte Estimation 预算算术 | 比值更高时单图更贵，`CODE_GRAPH_MAX_GRAPH_BYTES=256MB` 对应的符号数上限会低于 11 万。实测交付物应顺带产出本仓真实比值 |
| A3 | macOS arm64 / CPython 3.14.2 的对象布局与生产 Linux 容器（`python:3.14-slim`）一致，故常数可移植 | Byte Estimation | 指针宽度相同（都是 64 位），差异应当很小，但未在 Linux 上复现。建议实测交付物在容器内跑一次 |
| A4 | workflow engine 的 `_run_in_thread` 确实为每次执行创建独立 event loop | Threading Model | 若实际共用一个 loop，`asyncio.Event` 的禁令会过于保守（但 `threading.Event` 方案在两种情况下都正确，故无风险）。来源是 `ARCHITECTURE.md` 描述，未逐行读 scheduler 源码 |
| A5 | `resolution_rate < 0.6` 是合理的 `low_resolution` 阈值 | （来自 CONTEXT） | CONTEXT 与里程碑调研都标注这是经验值，**本相位的解析率统计交付物正是为了校准它**——计划应把「用实测数据回填/确认阈值」写成显式任务，而不是照抄 0.6 就完事 |

## Open Questions (RESOLVED)

> 四项均已在计划阶段裁定完毕，无遗留待决项。逐项裁决出处见各条末尾的 **Resolved** 行。
> 1 / 2 / 4 由 `121-CONTEXT.md` Area 6 的锁定决策（D-06-5 / D-06-6 / D-06-7）拍板；3 由 `121-09-PLAN.md` Task 2 落地。

1. **`CrossRepoApiCall` 端点解析不上 Symbol 时怎么办？**
   - 已知：两端只有 `(file_path, function_name)` 字符串，无 FK（Pitfall 1）。
   - 不明：解析失败（例如 handler 是类方法而 Symbol 里存的是 `METHOD` 带不同命名）时，是丢弃该跨仓边，还是建一个 `external`/`unresolved` 虚拟节点。
   - Recommendation: **丢弃 + 计数上报**（新增 `cross_repo_unresolved_count` 到图元数据）。建虚拟节点会污染 impact 结果，而计数让 Phase 122 能如实声明「有 N 条跨仓边无法定位」。
   - **Resolved**：采纳。锁定为 `121-CONTEXT.md` Area 6 **D-06-5**（丢弃 + 计数，⛔ 不建虚拟节点）；实现与回归见 `121-09` 之前的 `121-06-PLAN.md` Task 1，验证行见 `121-VALIDATION.md` GRAPH-01 的 `cross_repo_unresolved` 行。

2. **feature 分支 overlay 的符号去重键是什么？**
   - 已知：必须 overlay（Pitfall 3），`Symbol` 的 `unique_together` 是 `(repository, branch_name, file_path, name, start_line)`。
   - 不明：feature 覆盖 base 时按 `(file_path, name, start_line)` 还是仅按 `file_path`（整文件覆盖）去重。行号在分支间会漂移，按 `start_line` 去重会漏。
   - Recommendation: **按 `file_path` 整文件覆盖**——与索引侧「per-file delete+rebuild」的增量语义一致（`CallEdge` docstring 明写 per-file 幂等删除按 `caller_file` 走）。计划应把这条写死并加测试。
   - **Resolved**：采纳。锁定为 `121-CONTEXT.md` Area 6 **D-06-6**（去重键 = 整个 `file_path`）；实现见 `121-05-PLAN.md` Task 1 的 overlay 语义，回归见 `121-VALIDATION.md` GRAPH-01 的 `overlay_dedup` 行。

3. **`invalidate(repository_id)` 钩子挂不挂？**
   - CONTEXT 列为 Claude's Discretion（推荐做）。
   - 现成挂点：`code_relations/tasks.py:224-229` 与 `services/graph_builder.py:517-521`，两处都已有 `await sync_to_async(GalaxyGraphCache.refresh_repo)(repository_id)`，紧邻加一行即可。
   - Recommendation: **挂**。成本是两行代码，收益是「重索引后首查不必等签名比对发现陈旧」。但**主动失效只是优化，不能替代取图时校验**——多 worker 下钩子只对本 worker 生效，正确性必须由签名兜底。这个「钩子非充分条件」的理由应写进代码注释，防止后人误删签名校验。
   - **Resolved**：采纳（Claude's Discretion 项，由计划拍板挂上）。落地见 `121-09-PLAN.md` Task 1（`GraphService.invalidate` + `invalidate_repository`，只驱逐不重建）与 Task 2（两处钩子，经**包根**导入）；「钩子非充分条件」的注释在两处钩子与 `cache.py` 三处留痕，威胁项 `T-121-陈旧图`。

4. **`code_graph` vs 复用既有 `codegraph` 作为 `component` 值？**
   - CONTEXT 锁定 `code_graph`；`LOGGING-SPEC §5` 注册表里只有 `codegraph`。
   - Recommendation: **遵从 CONTEXT，用 `code_graph`，并在计划里加一个任务把它登记进 §5**。两个值并存是有意义的——`codegraph` 是索引/抽取侧，`code_graph` 是查询/服务侧，筛日志时能分开正是好事。
   - **Resolved**：采纳。锁定为 `121-CONTEXT.md` Area 6 **D-06-7**（`component="code_graph"`）；§5 注册见 `121-01-PLAN.md` Task 1，全包契约由 `121-03-PLAN.md` Task 3 的 `test_observability_contract` 机械守护。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|---|---|---|---|---|
| Python | 全部 | ✓ | 3.14.2 | — |
| `networkx` | 图对象与算法 | ✓（venv 内已装，锁文件已有） | 3.6.1 | 无需 fallback |
| `structlog` | 观测埋点 | ✓（全仓在用） | — | — |
| Django ORM / SQLite | loader 取数、测试库 | ✓ | — | — |
| `pytest` + `pytest-django` + `pytest-asyncio` | 测试 | ✓ | 9.0.2 / 4.8 / — | — |
| `slopcheck` | 包合法性审计 | ✗ | — | 已用更强证据替代（见 §Package Legitimacy Audit） |
| Qdrant / Redis / Postgres / Docker | — | 不适用 | — | 本相位纯读关系库 + 进程内存，**不触外部服务** |

**Missing dependencies with no fallback:** 无。
**Missing dependencies with fallback:** `slopcheck` — 已用锁文件哈希 pin + license + 上游 repo + 长期使用史等一手证据替代，结论强于 slopcheck 本可提供的信号。

## Validation Architecture

### Test Framework

| Property | Value |
|---|---|
| Framework | `pytest>=9.0.2` + `pytest-django>=4.8` + `pytest-asyncio`（`asyncio_mode = "auto"`） |
| Config file | `server/pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `cd server && uv run pytest tests/services/code_graph -x -q` |
| Full suite command | `cd server && uv run pytest` |

[VERIFIED: `server/pyproject.toml`]

关键约束（会直接影响用例写法）：

- `addopts = "-v --tb=short --disable-socket --allow-unix-socket -m 'not perf and not integration and not slow and not postgres_queue'"` — **网络默认禁用**（本相位无外呼，无影响）；`perf` 标记默认跳过（正好用于内存实测交付物）。
- `asyncio_mode = "auto"` — `async def test_*` 无需 marker。
- 测试库是 **SQLite 文件库**（`tests/conftest.py::django_db_modify_db_settings` 把默认的共享内存库换成临时文件库并放宽 busy timeout，注释说明是为消除 `database table is locked` flaky）。**这意味着多线程并发写 DB 的测试仍然危险**——见下方 CONC 用例的写法约束。

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|---|---|---|---|---|
| GRAPH-01 | 四类数据装配成 `MultiDiGraph`，节点/边计数与档位正确 | unit | `uv run pytest tests/services/code_graph/test_loader.py -x` | ❌ Wave 0 |
| GRAPH-01 | 首次查询 build 一次、同键再查命中缓存（builder 调用计数 == 1） | unit | `uv run pytest tests/services/code_graph/test_cache.py -k hit -x` | ❌ Wave 0 |
| GRAPH-01 | `CrossRepoApiCall` 按 file+name 解析到符号；解析不上计数上报 | unit | `... test_loader.py -k cross_repo -x` | ❌ Wave 0 |
| GRAPH-01 | feature 分支 overlay（base ∪ feature）且同文件 feature 覆盖 base | unit | `... test_loader.py -k overlay -x` | ❌ Wave 0 |
| GRAPH-02 | 签名对 `last_indexed_commit_sha` 变化敏感 | unit | `... test_signature.py -k watermark -x` | ❌ Wave 0 |
| GRAPH-02 | 签名对**两条**边构建轨各自变化都敏感 | unit | `... test_signature.py -k generation -x` | ❌ Wave 0 |
| GRAPH-02 | 无变更时签名稳定（连算两次相等） | unit | `... test_signature.py -k stable -x` | ❌ Wave 0 |
| GRAPH-02 | 水位推进 + 边构建 RUNNING ⇒ 拒用缓存 + `partial_edges=True` | unit | `... test_cache.py -k partial -x` | ❌ Wave 0 |
| GRAPH-02 | **`graph_build_status=PENDING` 但 IndexHistory 已终态 ⇒ 不判在途**（Pitfall 4 回归） | unit | `... test_cache.py -k pending_not_inflight -x` | ❌ Wave 0 |
| GRAPH-02 | 超时的 RUNNING 孤儿行 ⇒ 不判在途（Pitfall 5 回归） | unit | `... test_cache.py -k orphan -x` | ❌ Wave 0 |
| GRAPH-03 | 字节估算函数为纯函数，给定 n/e 返回确定值 | unit | `... test_cache.py -k estimate -x` | ❌ Wave 0 |
| GRAPH-03 | 超预算时按 LRU 顺序逐出至 ≤ 预算，发 `code_graph_cache_evicted` | unit | `... test_cache.py -k evict -x` | ❌ Wave 0 |
| GRAPH-03 | N 个并发请求同一 key ⇒ builder 只被调用一次 | unit | `... test_cache.py -k single_flight -x` | ❌ Wave 0 |
| GRAPH-03 | 构建失败 ⇒ 所有等待者各自抛，且失败不进缓存 | unit | `... test_cache.py -k build_failure -x` | ❌ Wave 0 |
| GRAPH-03 | 单图估算 > `MAX_GRAPH_BYTES` ⇒ 不进缓存 + `degraded="on_demand_subgraph"` | unit | `... test_cache.py -k degraded -x` | ❌ Wave 0 |
| GRAPH-04 | 命中 exclusion 的 `file_path` 对应符号不在节点集，其邻接边一并消失 | unit | `... test_access.py -k exclusion -x` | ❌ Wave 0 |
| GRAPH-04 | matcher 构造失败 ⇒ 抛 `GraphAccessDenied`，**不返回未过滤的图** | unit | `... test_access.py -k fail_closed -x` | ❌ Wave 0 |
| GRAPH-04 | `index_status != INDEXED` ⇒ 显式抛错，**不返回空图** | unit | `... test_access.py -k not_indexed -x` | ❌ Wave 0 |
| GRAPH-04 | `is_deleted=True` 的仓库 ⇒ 拒绝 | unit | `... test_access.py -k deleted -x` | ❌ Wave 0 |
| GRAPH-04 | exclusion 规则变更 ⇒ 指纹变 ⇒ 签名变 ⇒ 旧图失效 | unit | `... test_signature.py -k exclusion -x` | ❌ Wave 0 |
| 诊断交付物 | 最大仓内存实测 + 解析率统计 | perf（默认跳过） | `uv run pytest -m perf tests/services/code_graph/` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `cd server && uv run pytest tests/services/code_graph -x -q`（新包全部用例，秒级）
- **Per wave merge:** `cd server && uv run pytest tests/services/code_graph tests/codegraph tests/code_relations -q`（含既有图相关套件，验证零回归）
- **Phase gate:** `cd server && uv run pytest` 全绿 + `uv run ruff check .` + `uv run mypy .` 后再进 `/gsd-verify-work`

### 并发/single-flight 用例的确定性写法（关键）

`test_volar_pool.py::test_concurrent_get_no_double_build` 用 `threading.Barrier(4)` + 4 线程 + 断言 factory 只被调一次 [VERIFIED: `server/codegraph/lsp/tests/test_volar_pool.py:233-260`]，是本仓现成的并发测试范式。但**它不碰数据库**——本相位若照抄并让 4 个线程同时打 SQLite，几乎必然 flaky。

两条推荐路径：

1. **同步 single-flight（首选）**：把 `_get_graph_sync` 的 builder 参数化 / patch 成一个纯内存假 builder（内部 `time.sleep(0.05)` 并对调用计数 `+1`），用 `threading.Barrier(N)` 起 N 个线程直接调 `_get_graph_sync`。**全程不碰 DB**，确定性好，且测的正是锁语义本身。
2. **异步 single-flight**：patch loader 为一个 `await` 测试可控 `threading.Event` 的假实现，用 `asyncio.gather(*[svc.get_graph(...) for _ in range(4)])`。**不要用 `asyncio.sleep` 做时序** —— 用测试主动 `set()` 的事件来推进，避免时间竞态。

两种都要断言：builder 调用计数 == 1，且所有返回值 `is` 同一对象。

### Wave 0 Gaps

- [ ] `server/tests/services/code_graph/__init__.py`
- [ ] `server/tests/services/code_graph/conftest.py` — **必须自建** fixture（`tests/codegraph/conftest.py` 跨目录不可见；且其 `graph_repo` 的 `index_status` 是 `NOT_INDEXED`，会被 `ensure_repository_readable` 拒掉）。至少需要：`indexed_repo`（`index_status=INDEXED`）、`branch_index`、`symbols_factory`、`call_edges_factory`、`exclusion_rule_factory`
- [ ] `server/tests/services/code_graph/test_{model,loader,signature,cache,access}.py`
- [ ] `GraphService` 的**测试重置钩子**（模块级单例必须能在用例间清空，否则用例互相污染）。先例：`background_runner._reset_for_tests()`（`background_runner.py:240-257`）、`exclusion.invalidate_matcher_cache()`。建议配 `@pytest.fixture(autouse=True)` 在本目录 conftest 里自动重置
- [ ] 框架安装：**无需**（pytest 全套已在）

## Security Domain

`security_enforcement: true`，`security_asvs_level: 1`，`security_block_on: "high"`（`.planning/config.json`）。

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---|---|---|
| V1 Architecture | yes | 单一读取入口（`GraphService.get_graph`）+ `__init__.py` 不导出 loader/cache，把「绕过校验」从「需要自律」降级为「需要刻意违规」 |
| V2 Authentication | no | 本相位不新增认证面；调用方（Phase 122 的 MCP/对话壳）已有 PAT/JWT 认证 |
| V3 Session Management | no | 无会话 |
| V4 Access Control | **yes（核心）** | `access.py::ensure_repository_readable`：`is_deleted=False` + `index_status == INDEXED` + per-user ACL 扩展点。fail-closed：任何校验异常都拒绝，不降级放行 |
| V5 Input Validation | yes | `repository_id` 走 UUID 解析（非法即拒）；`branch_name` 只用于 ORM 参数化过滤（Django ORM 天然防注入）；`file_path` 一律过 `normalize_rel_path`，`None` 视为排除 |
| V6 Cryptography | no | 仅用 `hashlib.sha256` 做**非安全用途**的缓存签名（不是认证/完整性凭证），无密钥管理 |
| V7 Error Handling & Logging | yes | 异常文本过 `redact_secrets_in_text`；`exclusion.blocked` 审计埋点；观测失败吞掉不反噬 |
| V8 Data Protection | **yes（核心）** | 被排除文件（`.env` / `*.pem` / `id_rsa` / `*credentials*` 等内置默认，见 `BUILTIN_GLOBAL_DEFAULTS`）的符号**不得**出现在任何图输出中 |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---|---|---|
| 经图工具读到被排除文件的符号名/路径/行号 | Information Disclosure | 装配阶段按 `file_path` 过滤节点（**不是**输出阶段过滤）；节点被丢弃后其邻接边一并丢弃 |
| exclusion matcher 构造失败被降级成「不过滤」 | Information Disclosure | fail-closed：整仓抛 `GraphAccessDenied`。先例：`chunk_lookup.py:51-62` 构造失败即返回空 + 埋点 |
| exclusion 规则更新后旧缓存仍在服务被排除内容 | Information Disclosure | 规则指纹进签名（Example 5）；`_matcher_cache` 的 60s TTL **不足以**作为唯一防线 |
| 未索引/已软删仓库返回空图，被上层误读为「无影响」 | Tampering（决策污染） | 显式抛错，⛔ 不返回空图（CONTEXT 明确锁定） |
| 缓存键跨仓/跨分支串图 | Broken Access Control | 键是 `(repository_id, branch_name)` 二元组；`ensure_repository_readable` 在**每次** `get_graph` 都跑，不因缓存命中而跳过 |
| 恶意 regex 排除规则导致 ReDoS 挂死装配热路径 | DoS | 已由 `exclusion.is_redos_risky` 在**构造期**静态拒绝嵌套量词（`exclusion.py:41-78`）；复用即继承 |
| 超大仓装配把 worker 打到 OOM | DoS | 装配**前**用 COUNT 做准入；超 `MAX_GRAPH_BYTES` 走按需子图；字节 LRU 兜底 |
| 并发构建风暴（N 个请求同时冷建同一张大图） | DoS | per-key single-flight |

**一处必须如实记录的残余风险：** 图缓存是 per-worker 进程内存。若某用户的权限在缓存建立**之后**被收回，本进程缓存的图对象本身不会被"撤销"——但因为 `ensure_repository_readable` 在每次 `get_graph` 都执行（不因命中而跳过），实际访问仍会被拦下。真正的残余风险只在「per-user ACL 落地后、精细到符号级的授权」场景，而那已在 CONTEXT 的 Deferred 列表里。计划应把这条写进 `access.py` 的模块 docstring。

## Sources

### Primary (HIGH confidence) — 本仓代码一手核实

- `server/codegraph/models.py` — `Symbol`(12-63) / `ImportEdge`(66-94) / `CallEdge`(97-173) / `Endpoint`(176-215) / `ApiWrapper`(218-260) / `ApiCallSite`(263-294) / `CrossRepoApiCall`(297-338) 全部字段、索引、`unique_together`
- `server/code_relations/models.py:112-190` — `ChunkEdge` 字段、约束、索引
- `server/repositories/models.py` — `IndexStatus`(33-41) / `IndexHistoryStatus`(62-69) / `GraphBuildStatus`(72-83) / `RepositoryGraphStatus`(114-128) / `Repository`(142-330) / `IndexHistory`(390-495) / `GraphBuildHistory`(516-551) / `RepositoryBranchIndex`(734-772) / `RepoExclusionRule`(843-912)
- `server/services/exclusion.py` — 全文（TTL 缓存 34、`normalize_rel_path` 117、`ExclusionMatcher` 150-236、`_resolve_effective_specs` 271、`build_matcher_for_repo` 343、`invalidate_matcher_cache` 356、`log_exclusion_blocked` 370）
- `server/codegraph/galaxy/cache.py` — `_SIGNATURE_SOURCES` 55-63、`compute_signature` 87-104、`refresh_repo` 264-294
- `server/code_relations/lifecycle.py` — 全文（`thread_sensitive` 注释 52-55、SKIPPED 语义 250-260、状态机）
- `server/code_relations/tasks.py:216-232` — 边构建完成钩子点
- `server/services/graph_builder.py` — `_acquire_repo_lock` 87-107、状态机 249-310、事件三件套 389/525/584、Galaxy 刷新 517-521
- `server/services/background_runner.py` — 全文（定位降级声明 3-14、worker loop 64-108、`_reset_for_tests` 240-257）
- `server/services/chunk_lookup.py` — 全文（async service + fail-closed 范式）
- `server/services/code_intel/local_provider.py:55-80` — overlay `branch_filter` 与批量取数范式
- `server/services/branch_utils.py:88-115` — `resolve_branch_for_query`
- `server/codegraph/lsp/volar_pool.py:40-110, 193` — LRU + 锁 + 单例 + 逐出埋点范式
- `server/codegraph/lsp/tests/test_volar_pool.py:226-261` — 单例与并发测试范式
- `server/mcp_tools/views.py:363-381` — `_get_indexed_repo` 语义
- `server/repositories/permissions.py` — 全文（26 行，仅存在性 + 认证）
- `server/tests/codegraph/conftest.py:23-184` — 既有 fixture 清单与其 `index_status` 缺口
- `server/tests/codegraph/test_galaxy_cache.py` — 缓存测试范式
- `server/tests/conftest.py:1-60` — adrf patch、SQLite 文件库 fixture
- `server/friday/settings.py` codegraph 区块 — `ENABLE_CODEGRAPH` / `GALAXY_CACHE_*` / `GRAPH_BUILD_ORPHAN_*` 命名与语义
- `server/pyproject.toml` — pytest / ruff / mypy 配置，`networkx` **不在** dependencies
- `server/uv.lock:1932, 2371-2376` — networkx 3.6.1 传递依赖 + 哈希
- `server/system/models.py:16-22` — `SystemSetting` 字段
- `.planning/observability/LOGGING-SPEC.md` §1/§2/§3/§5 — 原则、category、标准字段、component 注册表
- `.cursor/rules/observability-logging.mdc` — 强制规则

### Primary (HIGH confidence) — 本次实测

- networkx 3.6.1 内存基准（`DiGraph`/`MultiDiGraph` × 属性数 × 4 个规模点，`tracemalloc`）— 本仓 `server/.venv`，CPython 3.14.2
- `DiGraph` 平行边静默覆盖行为验证（3 条 A→B 边 → 1 条，last-write-wins）
- 建图耗时基准（20k/100k/200k 节点）
- `bfs_layers` 切片 vs `depth_limit` 的 1000× 耗时差验证
- networkx 分发元数据（version / license / Project-URL / requires）

### Secondary (MEDIUM confidence)

- `.planning/research/SUMMARY.md` — 里程碑级选型裁决（networkx vs rustworkx / Louvain vs Leiden）与 6 条 Pitfall；本相位继承其结论未重新验证
- `.planning/codebase/TESTING.md` — 测试约定概览（关键项已回原文件核实）
- `ARCHITECTURE.md` — workflow engine `_run_in_thread` 的多 loop 描述（未逐行读 scheduler 源码，见 A4）

### Tertiary (LOW confidence)

- 无。本相位未使用任何未经核实的外部检索结果。

## Metadata

**Confidence breakdown:**

| Area | Level | Reason |
|---|---|---|
| Standard stack | HIGH | 零新增包；networkx 版本/license/可用性在本仓 venv 内直接验证 |
| ORM 查询形状 | HIGH | 全部字段名、索引、`unique_together` 逐行核对模型源码 |
| 签名与 in-flight 判定 | HIGH | 两条边构建轨的状态机与写入方均读了实现代码，非推断 |
| 内存常数与线性模型 | HIGH（模型）/ MEDIUM（绝对值） | 线性关系在 20× 规模跨度上实测验证（误差恒定 −5%）；绝对值受 tracemalloc-vs-RSS 与平台差异影响，见 A1/A3 |
| 并发模型 | HIGH | 11 处本仓先例 + `thread_sensitive` 的既有注释；仅 workflow loop 一处为文档来源（A4，且不影响结论） |
| Exclusion 集成 | HIGH | `exclusion.py` 全文精读，同步/异步形态与 fail-closed 语义逐条核实 |
| Pitfalls | HIGH | 每条都有代码行号或实测数据支撑；无凭印象的条目 |
| 测试策略 | HIGH | pytest 配置、conftest 作用域、并发测试先例均直接核实 |

**Research date:** 2026-08-09
**Valid until:** 2026-09-08（30 天；本相位依赖的全部事实都在本仓内，唯一外部变量 networkx 已锁版本。若期间 `codegraph/models.py` 或 `services/exclusion.py` 有改动，需复核对应章节）
