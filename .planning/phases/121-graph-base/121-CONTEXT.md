# Phase 121: 内存图服务基座 - Context

**Gathered:** 2026-08-09
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous，用户授权全量采纳推荐答案）

<domain>
## Phase Boundary

本相位交付 **一个新包 `server/services/code_graph/`** 作为 v0.22.0 全部图分析工具的共同地基：给定 `(repository, branch)` 返回一张装配好的 networkx `DiGraph`（节点 = `Symbol`，边 = `CallEdge` / `ChunkEdge` / `CrossRepoApiCall`），并把三条横切纪律**做进地基**，让上层工具天然继承：

1. **缓存四件套**：水位签名失效 + 字节预算 LRU + per-key single-flight 建图锁 + **取图时**（非仅建图时）水位复校。
2. **边准入与置信度契约**：解析边 / 裸名边 / 跨仓边三档 `confidence` 枚举 + `reason`，裸名边默认不参与扩散。
3. **读取层 fail-closed 收口**：exclusion 过滤与仓库可访问性校验统一在图读取层拦截，排除文件在任何上层工具输出中不可见。

**IN SCOPE（GRAPH-01~04）:**
- `server/services/code_graph/` 新包：`loader.py`（ORM 独占）/ `cache.py`（`GraphService` 单例 + LRU + 锁）/ `model.py`（图/节点/边数据契约与 confidence 枚举）/ `access.py`（exclusion + 权限收口）
- 水位与失效信号：`Repository.last_indexed_commit_sha` / `RepositoryBranchIndex.last_indexed_commit_sha` + 边构建代数（本相位需自建，见决策）
- 字节预算 LRU 逐出、single-flight 锁、超预算大仓降级路径（不缓存 / 按需子图）
- 新增 settings 配置项与 structlog 观测事件
- 一次性诊断指标：本仓最大仓的内存实测 + `callee_symbol` 解析率统计（研究 Gaps 要求）
- 单元 + 集成测试（缓存命中/失效/并发/逐出/降级/exclusion 拦截）

**OUT OF SCOPE（后续相位）:**
- impact / trace / detect_changes / rename_preview 等上层工具与其 MCP·对话双面壳（Phase 122–124、126）
- 社区检测、模块摘要、执行流、Semgrep、LSP（Phase 125–127）
- 新的持久化模型（本相位零新表，纯读既有表）
- 前端任何改动（本相位无 UI）

</domain>

<decisions>
## Implementation Decisions

### Area 1: 缓存键、失效信号与一致性

- **缓存键**：`(repository_id, branch_name)` 二元组，`branch_name` 沿用既有模型语义（`""` = 基线分支），不做归一化别名。跨仓 impact 在 Phase 122 通过「按需再取对端仓的图」组合，**不做多仓合并大图**——合并图会让失效面与内存放大同时失控。
- **失效信号 = 复合签名**（仿 `codegraph/galaxy/cache.py::compute_signature` 范式，但在内存中比对、不落盘）：
  `sha256(last_indexed_commit_sha ‖ edge_build_generation ‖ symbol_count ‖ call_edge_count)`。
  - `last_indexed_commit_sha` 从 `RepositoryBranchIndex` 取，缺失时回落 `Repository.last_indexed_commit_sha`。
  - **`edge_build_generation` 本仓不存在**（scout 确认），本相位以既有信号合成而非新增字段：取 `IndexHistory` 中该仓最近一条 `graph_build_status == COMPLETED` 记录的 `id + finished_at`（无则用 `Repository.graph_last_built_at`）作为「代数」分量。⛔ 不新增迁移、不改既有表。
  - 计数分量用 `.count()` 聚合，与 Galaxy 的 `count + Max(timestamp)` 同款思路，成本可接受（毫秒级）。
- **半新图防护（GRAPH-02 硬要求）**：`get_graph()` 返回前**必须**复算签名并与缓存条目的 `built_signature` 比对；不一致直接丢弃重建。同时若该仓存在**进行中**的边构建（`graph_build_status ∈ {PENDING, RUNNING}`）而水位已推进，则判定为「水位已更新但边未建完」，**拒绝使用缓存并按当前落库状态重建 + 在返回结果上打 `partial_edges: true` 标记**，由上层工具透出，绝不静默返回半新图。
- **不落盘**：与 Galaxy 的文件缓存不同，本服务是 **per-worker 纯内存**缓存（多 worker 各持一份是已知且接受的代价，靠字节预算约束）。理由：图对象无法廉价序列化，落盘反而引入一致性第二源。

### Area 2: 内存预算、逐出与降级

- **预算按字节，不按条目数**：新增 settings `CODE_GRAPH_CACHE_MAX_BYTES`（默认 **512MB**，环境变量可覆盖），`CODE_GRAPH_MAX_GRAPH_BYTES`（单图上限，默认 **256MB**）。默认值在本相位交付「本仓最大仓实测报告」后可调，**先落保守值不盲设大**。
- **字节估算方式**：不用 `sys.getsizeof` 递归（对 networkx 不准且慢），采用**确定性线性估算** `nodes * NODE_COST + edges * EDGE_COST`，两个常数由本相位的实测标定并写进常量注释；估算函数单独可测。
- **LRU**：`collections.OrderedDict` + `threading.RLock`，`move_to_end` 记访问序；插入后循环逐出直到总字节 ≤ 预算。逐出发结构化事件（含被逐 key、字节、原因）。
- **single-flight**：per-key `threading.Event` 占位法——首个请求放占位、其余等待同一结果；构建失败时唤醒所有等待者并让其各自失败（不做失败缓存，避免毒化）。锁粒度 = per (repo, branch)，全局锁只保护 map 本身。
- **超预算大仓降级**：单图估算 > `CODE_GRAPH_MAX_GRAPH_BYTES` 时**不进缓存**，改走「按需子图」——只装配以查询种子符号为中心、半径 = 调用方指定 depth + 1 的诱导子图（loader 层用 SQL 侧多跳收敛，而非先全量再裁剪）。返回结果标 `degraded: "on_demand_subgraph"`，上层工具须透出。
- **进程不 OOM 是硬约束**：预算检查在**装配前**用行数估算做准入（`Symbol.count + CallEdge.count`），避免「先 OOM 再逐出」。

### Area 3: 边准入与置信度契约（本相位定型，全里程碑复用）

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

### Area 4: 读取层鉴权与 exclusion 收口（fail-closed）

- **单一入口**：所有图访问必须经 `GraphService.get_graph(repository_id, branch, *, user=None, ...)`，**loader 与 cache 均不对外导出**（`__init__.py` 只 re-export `GraphService` 与数据契约类型）。上层工具直连 loader 视为架构违规，在 plan-checker/code-review 明确列为红线。
- **exclusion**：复用既有 `server/services/exclusion.py` 的 `build_matcher_for_repo(repository_id)`，在**装配阶段**按 `Symbol.file_path` 过滤节点（被排除节点连同其所有邻接边一并丢弃），而非在输出阶段过滤——保证「排除文件在所有图分析工具输出中不可见」。matcher 失败时 **fail-closed**：整仓不返回图并抛 `GraphAccessDenied`。
  - **缓存与 exclusion 规则的一致性**：exclusion 规则版本纳入缓存签名分量（取 matcher 的规则指纹；`invalidate_matcher_cache` 已有 60s TTL，签名再加一层保险），规则改动后旧图自动失效。
- **权限**：当前仓库层只有 `RepositoryPermission`（存在性 + 认证）这一层，本相位**不发明新的 ACL 模型**，但把校验点收口成 `code_graph/access.py::ensure_repository_readable(user, repository_id)` 单一函数（内部先做 `is_deleted=False` + 索引态校验，预留 per-user ACL 扩展点）。Phase 122 的跨仓 impact 每穿一仓复核一次，未授权整仓折叠为 `redacted_repository`，该折叠语义在本相位的返回契约里先定义好。
- **未索引仓**：`index_status != INDEXED` 时不建图，抛显式错误（沿用 `_get_indexed_repo` 的语义），不返回空图——空图会被上层误读为「没有影响」。

### Area 5: 观测埋点（遵循 `.cursor/rules/observability-logging.mdc`）

- `component = "code_graph"`；缓存/建图属高频内部步骤 → `category = "sampling"`，**建图完成**这类低频关键事件用 INFO，缓存命中用 DEBUG（禁止 INFO 刷屏）。
- 事件名：`code_graph_build_started` / `code_graph_build_completed`（带 `duration_ms` / `node_count` / `edge_count` / `estimated_bytes` / `resolution_rate`）/ `code_graph_build_failed` / `code_graph_cache_hit` / `code_graph_cache_evicted` / `code_graph_stale_watermark` / `code_graph_degraded_subgraph` / `code_graph_access_denied`。
- 触发用户绑定：走既有中间件注入的 contextvars；后台/预热路径显式 `initiated_by_user_id="system"`。
- 观测代码 best-effort，异常吞掉，绝不反噬取图主流程。

### Area 6: 调研回灌的补充裁决（2026-08-09，RESEARCH.md 提出的三个 open question，已裁决为锁定决策）

调研（`121-RESEARCH.md`）推翻/补充了 Area 1–5 的三处，以下裁决**优先级高于**上文对应条目：

- **D-01 — 图对象用 `MultiDiGraph` 而非 `DiGraph`** （推翻 Area 3 的隐含假设）。实测确认 `DiGraph` 对同一符号对的第二条边是**静默覆盖**，而四档边契约要求同一对符号间多档边并存。接受 +44%（≈ +224 字节/边）内存代价，`EDGE_COST` 常数按 MultiDiGraph 标定。
- **D-02 — 「边构建代数」必须取两条轨的合成** （补强 Area 1）。本仓边构建是两条互相独立的轨：`IndexHistory.graph_build_status` 跟踪的是 **ChunkEdge**，而 `Symbol`/`CallEdge`/`Endpoint` 的抽取由 `Repository.graph_build_status` + `GraphBuildHistory` 跟踪，写入方是完全不同的代码路径。`CallEdge` 是本相位图的主边源，**只看 `IndexHistory` 一条轨会漏失效**——签名的代数分量必须同时纳入两条轨的终态标识。
- **D-03 — in-flight 判定不得直接用 `graph_build_status == PENDING`** （修正 Area 1 的半新图防护）。`IndexHistory.graph_build_status` 的**模型默认值就是 `PENDING`**，且只有走 `enqueue_edge_build_for_history` 才推进；照字面实现会让「从未触发过边构建」的仓库**永久**带 `partial_edges: true`，降级标记长鸣即等于失效。正确判定 = 存在一条**本轮索引产生的、状态为 `RUNNING`（或 PENDING 且有对应在途任务凭证）**的记录，且其水位新于缓存图的水位；无法确证在途时**不打标记**（宁可不报也不长鸣）。具体判据由执行方按 `lifecycle.py` 实际状态机确定并写进测试。
- **D-04 — single-flight 用 `threading.Event`，不用 `asyncio.Event`** （补强 Area 2）。本仓并存三类 event loop（ASGI 主 loop / workflow 引擎 `_run_in_thread` 自建 loop / durable worker），`asyncio.Event` 跨 loop 无法 await。等待方走 `asyncio.to_thread` 包裹阻塞等待；**绝不能持锁 await**。
- **D-05 — 跨仓边端点解析不上 `Symbol` 时丢弃 + 计数上报** （open question 1 裁决）。`CrossRepoApiCall` 两端指向 `ApiCallSite`（`caller_file` + `caller_function` 字符串）与 `Endpoint`（`file_path` + `handler_name`），**都没有 `Symbol` 外键，自身也没有 repository / branch_name 字段**——需要一段「文件路径 + 名字」二次解析把它挂到符号节点上。解析失败的边**直接丢弃**（不建虚拟节点），并在图元数据上报 `cross_repo_unresolved_count`，由上层工具在输出中声明。理由：虚拟节点会污染 impact 的深度分组与计数，且无法给出 file:line，对 agent 无行动价值。
- **D-06 — feature 分支 overlay 去重键取整文件** （open question 2 裁决），与索引侧 per-file 删建重建的既有语义一致，不含行号。
- **D-07 — `component` 值登记为 `code_graph` 并补 LOGGING-SPEC 注册** （open question 3 裁决）。`LOGGING-SPEC §5` 现有的是 `codegraph`（无下划线，指既有 app），本服务是新的 service 层组件，用 `code_graph` 区分；**计划中必须含一个把 `code_graph` 写进 `LOGGING-SPEC §5` 组件清单的任务**，否则违反强制规范。
- **D-08 — `reason` 字符串输出时现推、不存进边属性** （调研的免费优化）。边属性 1–3 个成本完全相同（CPython 小字典预分配），第 4 个才跳一级；把 `reason` 移出边属性可省约 7MB/大图且零功能损失。反之调研已证伪两个直觉优化：字符串驻留只省 4%、int 键替代 UUID 字符串实测**更费** 12.5MB——**都不要做**。

### Claude's Discretion

- 具体模块拆分粒度与私有函数命名、字节估算常数的标定方法、测试用例的组织方式（`server/tests/services/code_graph/` 下的文件切分）、是否额外抽 `signature.py`——均由执行方按本仓既有 service 写法自行决定。
- 是否为 `GraphService` 提供显式 `invalidate(repository_id)` 钩子并挂到 `code_relations/lifecycle.py` 的边构建完成点（推荐做，但形式自定；即便不挂，取图时水位校验也能兜住正确性）。
- 一次性诊断指标（内存实测 + 解析率统计）以什么形态交付——管理命令、pytest 标记用例或脚本均可，只要结果写进 SUMMARY。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/codegraph/galaxy/cache.py::GalaxyGraphCache` — 签名失效范式先例（`compute_signature` 用 7 张表的 `count + Max(timestamp)` 拼 SHA256；`refresh_repo` 主动失效；`GALAXY_CACHE_ENABLED` 逃生开关）。**本相位照抄思路但改为内存缓存 + 加锁 + 加字节预算**。
- `server/services/exclusion.py` — `build_matcher_for_repo(repository_id)`（60s TTL 缓存）/ `ExclusionMatcher.is_excluded(rel_path)`（fail-closed）/ `normalize_rel_path` / `log_exclusion_blocked` / `invalidate_matcher_cache`。**唯一 exclusion 事实来源，必须复用。**
- `server/repositories/permissions.py::RepositoryPermission` — 现状仅「认证 + 仓库存在且未删」；`server/mcp_tools/views.py::_get_indexed_repo`（L363-381）额外要求 `index_status == INDEXED`。
- `server/services/graph_builder.py` — service 层写法范式：`structlog.get_logger(__name__)`、`_acquire_repo_lock` 的 `sync_to_async` 包裹、`graph_build_started/completed/failed` 事件三件套。
- `server/services/chunk_lookup.py` — 轻量 async service 范式：public API 全 async，ORM 集中在 `sync_to_async` 包裹的私有函数里，复用 exclusion helper。
- `server/services/code_intel/local_provider.py` — `sync_to_async(list)(Symbol.objects.filter(...))` 的批量取数写法。

### Established Patterns
- **模型位置**：`Symbol` / `CallEdge` / `Endpoint` / `CrossRepoApiCall` / `ImportEdge` / `ApiCallSite` / `ApiWrapper` 全在**单文件** `server/codegraph/models.py`（不是 `models/` 包）；`ChunkEdge` / `ChunkRegistry` 在 `server/code_relations/models.py`。
- **分支语义**：`Symbol` / `CallEdge` / `Endpoint` / `ChunkEdge` 均有 `branch_name`（`default=""` 表示基线分支）。
- **关键字段**：`Symbol` 有 `start_line` / `end_line` / `file_path` / `chunk_id`(软引用)；`CallEdge` 有 `caller_symbol`(FK, nullable, SET_NULL) / `callee_symbol`(FK, nullable) / `callee_name` / `callee_file` / `callee_qualifier` / `line_number`，**`CallEdge` 上没有 `match_confidence`**；`match_confidence`(Float) 只在 `CrossRepoApiCall` 上（1.0 / 0.7 / 0.4 三档）。
- **水位**：`Repository.last_indexed_commit_sha`（`models.py:233`）与 `RepositoryBranchIndex.last_indexed_commit_sha`（L747）；写入方在 `server/services/indexer.py`。
- **边构建状态**：`IndexHistory.graph_build_status` / `edge_count` / `cross_repo_built_at`；`Repository.graph_build_status` / `graph_last_built_at`；生命周期驱动在 `server/code_relations/lifecycle.py::enqueue_edge_build_for_history`。
- **settings 命名**：功能开关 `ENABLE_*`；预算/比例 `*_BUDGET_RATIO`；缓存 `*_CACHE_*`（`GALAXY_CACHE_ENABLED` / `GALAXY_CACHE_DIR` / `GALAXY_CACHE_WARM_ON_STARTUP`）；均在 `server/friday/settings.py` 的 codegraph 区块（L809-895）。
- **networkx 3.6.1 已在 `server/uv.lock`（L2371）但为 llama-index 传递依赖，应用代码零使用**——本相位需把它提升为 `server/pyproject.toml` 的**直接依赖**（版本约束 `>=3.6,<4`），否则上游一旦不再传递就会断。

### Integration Points
- 新包位置：`server/services/code_graph/`（**当前不存在**；`server/services/code_intel/` 是同层兄弟，可作包结构参照）。
- 失效钩子候选：`server/code_relations/tasks.py`（~L224 调 `GalaxyGraphCache.refresh_repo` 处）与 `server/services/graph_builder.py`（~L519）——同一位置可顺带 invalidate 本服务。
- 测试位置：`server/tests/codegraph/conftest.py` 已有 `graph_repo` / `seed_symbol` / `caller_symbol` / `callee_symbol` / `outgoing_call_edge` / `incoming_call_edge` / `second_hop_edge` / `repo_endpoints` 等 fixture，**直接复用**；本相位测试落 `server/tests/services/code_graph/`，可在其 conftest 中 import 复用上述 fixture 或按需另建。
- 参考的既有缓存测试：`server/tests/codegraph/test_galaxy_cache.py`（签名稳定性 / 命中 / 失效）。

</code_context>

<specifics>
## Specific Ideas

- 研究文档 `.planning/research/SUMMARY.md` 的「Pitfall 1 裸名边假阳性灾难」与「Pitfall 2 缓存四件套」是本相位的**验收内核**——两者都必须在本相位落齐，不允许留到上层工具相位再补（后补必然漏接）。
- `.planning/research/` 三份 Gaps 要在本相位内出数据：
  1. 本仓最大仓的 networkx 内存实测（用于标定 `CODE_GRAPH_CACHE_MAX_BYTES` 默认值）；
  2. per repo / per language 的 `callee_symbol` 解析率（决定 `low_resolution` 阈值是否合理）；
  两项结果写进 121-SUMMARY.md，供 Phase 122 的输出文案与 Phase 125 的容量规划复用。
- 「取图时水位复校」是与 `GalaxyGraphCache` 的显式差异点：Galaxy 只在读时比签名，本服务额外要看**边构建是否在途**，这是 GRAPH-02 里「绝不返回半新图」的直接落点。

</specifics>

<deferred>
## Deferred Ideas

- **rustworkx 图引擎升级** — 触发条件已在 REQUIREMENTS Future 段登记（单仓 >50 万边 / impact p95 >2s / 缓存 >2GB）。本相位只需保证 `model.py` 的图契约不泄漏 networkx 具体类型到上层（留 adapter seam），不做任何实现。
- **跨进程共享图缓存**（Redis / 共享内存） — 多 worker 各持一份是本相位接受的代价；若实测内存不可接受再单独立项。
- **per-user 仓库 ACL** — 本仓当前不存在，本相位只收口校验点并预留扩展位，不发明模型。
- **`purge_file` 从五面扩到六面**（研究 Pitfall 6 提到） — 属于删除链路的收口，与本相位读取层收口不同轨，留待有实际删除需求时处理。
- **图缓存预热**（仿 `GALAXY_CACHE_WARM_ON_STARTUP`） — 冷启动首查慢是可接受的；预热会在启动期制造内存尖峰，与本相位「进程不 OOM」目标冲突，不做。

</deferred>
