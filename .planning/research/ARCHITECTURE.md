# Architecture Research

**Domain:** Friday AI v0.24.0 单仓 graph-aware query 对齐 GitNexus
**Researched:** 2026-08-24
**Confidence:** HIGH（架构接缝来自当前仓库源码；GitNexus 目标形态来自其当前 MCP `query` 契约）

> 结论先行：不替换 Django ORM、Qdrant、NetworkX，也不另建图数据库。应把现有
> `Symbol` / `CallEdge` / `SymbolCommunity` / `ProcessTrace` 继续作为 canonical
> 图索引，把 Qdrant 作为可重建的 Process 检索投影，把 NetworkX 作为按需分析投影；
> 新增一个入口无关的 `GraphQueryService`，由所有消费面做薄适配。

## Standard Architecture

### System Overview

```
┌────────────────────────────────────────────────────────────────────────────┐
│ 消费面（只做鉴权、上下文注入、协议适配）                                      │
│ Django MCP │ Chat Agent │ npm @friday-ai-codes/mcp │ task 编码容器          │
└────────────┬─────────────┬──────────────────────────┬───────────────────────┘
             └─────────────┴──────────────┬───────────┘
                                         ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ ToolContractRegistry（NEW，工具契约单一事实源）                              │
│ Pydantic request/response + manifest + contract_version                    │
└──────────────────────────────────────┬─────────────────────────────────────┘
                                       ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ GraphQueryService（NEW，入口无关的唯一查询编排）                             │
│  1. access/exclusion/watermark gate                                        │
│  2. Symbol lane ───────────────┐                                           │
│  3. Process hybrid lane ───────┼─ RRF/解释分数 → process-grouped assembler │
│  4. Community enrichment ──────┤                                           │
│  5. bounded impact ────────────┘ → deterministic impact summary            │
└──────────────┬──────────────────────────────┬──────────────────────────────┘
               ▼                              ▼
┌──────────────────────────────┐ ┌───────────────────────────────────────────┐
│ GraphService / NetworkX      │ │ ProcessSearchIndex（NEW projection）      │
│ impact / trace / staleness   │ │ Qdrant dense+sparse，按 repo/branch/SHA   │
└──────────────┬───────────────┘ └───────────────────┬───────────────────────┘
               └──────────────────────┬──────────────┘
                                      ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ Canonical Django models                                                    │
│ Symbol / ImportEdge / CallEdge / SymbolCommunity / ProcessTrace / Endpoint │
└────────────────────────────────────────────────────────────────────────────┘

索引链：
AST 单趟抽取 → raw graph rows → language-aware resolution → Graph cache invalidate
→ Community rebuild → Process rebuild → Process Qdrant projection sync
```

### Component Responsibilities

| Component | 状态 | Responsibility | Implementation |
|-----------|------|----------------|----------------|
| `codegraph/extractors/base.py::CallData` | MODIFIED | 携带 receiver/member 的可解析 hint | 增加结构化 `resolution_hints`，不存源码正文 |
| `codegraph/models.py::CallEdge` | MODIFIED | 保存解析结果及可度量证据 | 增加 `resolution_kind/confidence/resolver_version/resolution_evidence`；保留现有 nullable FK |
| `codegraph/resolver/` | MODIFIED | 语言分派、候选生成与确定性裁决 | 通用 orchestrator + TS/JS、Python、Go plugin |
| `codegraph/resolver/wiring.py` | MODIFIED | 全仓 raw 写完后的唯一 resolution 入口 | 按 `(repository, branch)` 建上下文，批量回填 |
| `ProcessTrace` | MODIFIED | Process canonical 读模型 | 增派生检索字段、schema/version/generation；`steps` 仍是步骤事实源 |
| `services/process_search_index.py` | NEW | Process 检索文档构建、Qdrant 同步、混合召回 | 确定性 point id；dense+sparse；SHA/generation 过滤 |
| `services/code_graph_query/` | NEW | graph-aware query 编排与统一响应 | async service；各 lane 并发；有界 impact |
| `services/code_graph/impact_summary.py` | NEW | 结构化影响面摘要 | 复用 `run_impact` 与 `assemble_affected_processes`，确定性组装 |
| `tools/contracts/` | NEW | 工具 manifest 与模型单一事实源 | Pydantic JSON Schema；server/npm/container 从 manifest 投影 |
| MCP/Chat/npm/task adapters | MODIFIED | 鉴权、注入、协议映射 | 不重复查询算法、排序权重或响应字段定义 |

## Recommended Project Structure

```
server/
├── codegraph/
│   ├── models.py                         # MODIFIED：CallEdge / ProcessTrace additive fields
│   ├── extractors/
│   │   ├── base.py                       # MODIFIED：resolution_hints
│   │   └── calls.py                      # MODIFIED：member chain / receiver hints
│   └── resolver/
│       ├── symbol_resolver.py            # MODIFIED：只负责编排和裁决
│       ├── frontend_receiver.py          # NEW：TS/JS import alias + receiver
│       ├── python_member.py              # NEW：Python import/member
│       ├── go_selector.py                # NEW/LATER：Go selector
│       ├── scoring.py                    # NEW：闭集 resolution_kind 与置信度
│       └── wiring.py                     # MODIFIED：branch-aware bulk backfill
├── services/
│   ├── code_graph_query/
│   │   ├── service.py                    # 唯一 graph-aware query 入口
│   │   ├── planner.py                    # query probes / budgets
│   │   ├── ranking.py                    # lane 内分数 + RRF
│   │   ├── assembler.py                  # process-grouped response
│   │   └── types.py                      # 内部纯 dataclass
│   ├── process_search_index.py           # Process → Qdrant projection
│   └── code_graph/impact_summary.py      # 结构化影响摘要
├── tools/contracts/
│   ├── registry.py                       # canonical tool registry
│   ├── graph_query.py                    # request/response Pydantic models
│   └── manifest.py                       # versioned JSON manifest
├── mcp_tools/                            # MODIFIED：薄 HTTP adapter
└── agents/tools/                         # MODIFIED：薄 Chat adapter

mcp/src/generated/tools.ts                # GENERATED：由 manifest 生成，禁止手写 schema
task/...                                  # MODIFIED：策略白名单与同 manifest hash 守门
```

### Structure Rationale

- **resolver 留在 `codegraph/`：** 它属于索引构建，不属于在线 GraphService；在线查询不得临时猜调用边。
- **query service 放 `services/`：** 它需要 async ORM、Qdrant、GraphService、权限与 ledger，不能污染纯图算法包。
- **Process DB 与 Qdrant 分层：** `ProcessTrace` 是事实源，向量点只是可重建投影；Qdrant 故障不能删除或改写 Process。
- **contract 独立于入口：** 现有 DRF serializer、Chat Pydantic、`TOOL_SCHEMA_SNAPSHOT`、npm `tools.ts` 四处手写已产生漂移，新增入口不能继续复制。

## Architectural Patterns

### Pattern 1: 两阶段语言感知解析

**What:** 抽取阶段只记录语法事实；全仓阶段结合 import 表、符号表和作用域 hint 做解析。

```
Call AST
  → raw: callee_name + qualifier/member_chain + receiver hint
  → language plugin 生成候选
  → exact scope/import/type evidence 裁决
  → callee_symbol + resolution_kind/confidence/version
  → unresolved 留 NULL（禁止同名 fuzzy 硬连）
```

TS/JS 首批顺序：

1. 同文件函数/类/方法。
2. named/default/namespace import 与 alias；`api.fetch()` 先把 `api` 解析为 import binding。
3. `this.method()` 与 class scope。
4. `const service = new Service()`、显式类型标注、构造参数注入等 receiver hint。
5. 动态属性、复杂链、类型不足时留 unresolved。

Python 首批顺序：

1. `from a import b as c` 的 direct call。
2. `import a.b as m; m.fn()` 的 module member。
3. `self.method()` / `cls.method()` 的 class scope。
4. `obj = ClassName()` 与显式 annotation 的 member。
5. star import、monkey patch、动态 `getattr` 留 unresolved。

Go 后置：沿用现有 import qualifier → package dir → symbol；待 TS/Python contract 和 benchmark 稳定后再扩 method receiver/interface。不要让 Go 的接口派发复杂度阻塞前两种语言。

**Trade-offs:** 会增加少量 additive 字段和整仓回填成本，但解析可解释、可按语言/形态度量；比在线 query 时按名字猜边安全。

### Pattern 2: Process 一等对象，投影而非第二事实源

**What:** `ProcessTrace.steps`、`entry_endpoint` 是 canonical；检索文档由确定性 builder 派生：

```
name + HTTP method/path
+ entry handler/file
+ terminal symbol/file
+ ordered step names
+ community/module summaries
+ path/module-derived business keywords
```

建议给 `ProcessTrace` 增加：

- `entry_symbol_id`、`terminal_symbol_id`：软引用，加速分组与影响交集。
- `module_keys`、`business_keywords`：派生 JSON，闭集/受长度限制。
- `search_text`、`search_schema_version`：确定性可回放文档。
- `resolver_version`、`index_generation`：定位数据代际。

Qdrant point 使用 `hash(repository_id, branch, process_key)` 的稳定 id，payload 至少含
`document_kind=process/repository_id/branch/process_key/built_at_sha/index_generation`。
同步顺序为“upsert 新 generation → 标记 DB projection ready → 删除旧 generation”；
在线查询强制过滤当前 `built_at_sha + generation`，因此中途失败只会显式 unavailable/stale，
不会把旧、新 Process 混排。

### Pattern 3: process-grouped hybrid query

**What:** 查询不是“找若干 chunk 后附带 Process”，而是 Symbol 与 Process 两条 lane 并发，
最终以 Process 为主要分组。

1. query 只生成一次 dense embedding 与一次 sparse encoding。
2. Symbol lane：精确/别名符号 + 既有代码 chunk hybrid。
3. Process lane：Process `search_text` dense+sparse hybrid。
4. 各 lane 内保留原始分数；跨 lane 用 Reciprocal Rank Fusion，禁止直接相加异构分数。
5. Process 命中直接建 group；Symbol 命中通过 `steps.symbol_id` 倒排归入 Process。
6. 不属于任何 Process 的高质量 Symbol 放 `standalone_symbols`，不得硬塞进某个流程。
7. 每组返回 `why_matched`、lane rank、步骤 `file:line`、Community 和 freshness。

响应建议固定为：

```
query/repository/branch/as_of
processes[] {
  process_key/name/score/explanation
  entry/terminal/steps[]
  matched_symbols[]/communities[]
  impact_summary
}
standalone_symbols[]
definitions[]
degradation/staleness/metrics
```

这与当前 GitNexus `query` 的“processes + process_symbols + definitions”目标形态一致，
但保留 Friday 已有的权限、排除规则、分支水位和影响面声明。

### Pattern 4: 有界影响摘要，不把空结果解释为安全

**What:** `ImpactSummaryAssembler` 对 top Process 的 entry、命中步骤和高分 standalone
symbol 选有限种子（建议总计 3–5），批量调用现有 `run_impact`，再复用
`assemble_affected_processes` 交叉映射。

- 返回结构化 `direct_callers/depth_groups/affected_processes/risk/degradation`。
- “未索引、图构建失败、解析率低、预算截断”必须显式声明，不能折成空数组。
- markdown、Chat 文本、MCP JSON 都从同一结构化结果渲染。
- 不复用 MR `impact_report.py` 作为 canonical；它是展示 formatter，且容错语义是 MR fail-soft。
- v0.24.0 默认确定性摘要，不新增 LLM 调用；若后续加自然语言摘要，只能消费结构化结果并保留原事实。

### Pattern 5: Tool Contract Registry + 生成式适配

**What:** 以 Pydantic request/response model 和 tool metadata 建 registry：

- Django MCP view 从 registry 取 schema，DRF 只承担 HTTP 校验/状态码映射。
- Chat SDK MCP adapter 从同 registry 注册，自动注入 `conversation_id/user`。
- `/api/mcp/tools/manifest/` 返回授权后可见工具、schema、annotations、`contract_version`。
- npm MCP 启动时读取 manifest；网络不可用时使用仓内 generated snapshot，并校验 hash。
- task 容器只取 manifest 与任务策略白名单的交集，不能因 server 新增工具而自动获得写能力。

`TOOL_SCHEMA_SNAPSHOT` 降为从 registry 生成的测试快照；`mcp/src/tools.ts` 改 generated 文件。
CI 同时校验工具名、输入 schema、响应 schema、manifest hash，而不只比较名称集合。

## Data Flow

### Index / Rebuild Flow

```
Indexer parse_file_dual
  → GraphWriter per-file raw rows（branch-aware transaction）
  → backfill_symbol_resolution(repo, branch, repo_path)
       ├─ TS/JS resolver
       ├─ Python resolver
       └─ Go resolver（现状；增强后置）
  → GraphService.invalidate(repo, branch)
  → durable_community_rebuild
  → durable_process_rebuild
  → durable_process_projection_sync
  → current generation ready
```

关键修改：当前 `backfill_symbol_resolution()` 和 `SymbolResolver.backfill()` 只按
`repository_id` 查询，必须把 `branch_name` 贯穿 `SymbolIndex`、`ImportEdge`、`CallEdge`
过滤；否则 feature 分支回填可能读到 base facts。三个 durable job 均继续携带
`initiated_by_user_id`，worker 入口重新 bind。

### Request Flow

```
MCP / Chat / npm / task
  → adapter authentication + actor injection
  → GraphQueryRequest validation
  → ensure_repository_readable + exclusion matcher + branch/watermark resolution
  → asyncio.gather(Symbol lane, Process lane)
  → RRF + process grouping + Community enrichment
  → bounded GraphService impact
  → GraphQueryResponse
  → RetrievalTrace + caller metric（best-effort）
  → protocol-specific render
```

权限与 exclusion 必须发生在 embedding、取图、ORM 候选查询之前；matcher 构造失败即
fail-closed。Qdrant 返回点、Process steps、Community members 和 impact nodes 在出墙前
各自再做一次路径过滤，防历史脏投影回流。

## Migration and Backfill

### Additive Schema Migration

1. `CallEdge` 新增 nullable/default 字段；旧 reader 不受影响。
2. `ProcessTrace` 新增 nullable/JSON default 字段与 `(repository, branch, built_at_sha)` 索引。
3. 新建 projection status/checkpoint（可放 Repository facet 或独立小表），不要把 Qdrant 状态塞进 `flags`。
4. 先发布兼容 writer，再启动回填；最后才开放新 query 工具。

### Backfill Plan

1. **先冻结 baseline：** 同仓同 commit 记录 v0.22 resolved edge、Symbol/Process recall、impact/trace、延迟/token。
2. **resolver dry-run：** 新 resolver 只产对比报告，不写 FK；按 language × call shape 统计 gained/lost/conflict。
3. **分语言回填：** TS/JS → Python → Go；每批 `(repo, branch)` 幂等，使用 resolver version。
4. **失效与重建：** resolver 成功后才 invalidate GraphService，再链式 Community → Process。
5. **Process projection：** 新 generation upsert 并核对 DB count/Qdrant count，再切 ready。
6. **灰度 query：** feature flag 按仓开启；旧 impact/list_processes 工具继续可用。
7. **全量切换后：** 保留旧字段和工具至少一个里程碑，禁止同批 destructive cleanup。

失败恢复以每仓每分支 checkpoint 重跑；不要做全局巨事务。Process DB 全删全建继续放在单个
`transaction.atomic()` 内，Qdrant 用 generation 隔离弥补跨存储无事务。

## Observability

| Layer | Category | Required signals |
|-------|----------|------------------|
| 外部 graph query | `caller` | started/completed/failed、actor、source、repo、duration、result/degradation count |
| resolver batch/job | job lifecycle `caller`；边级汇总 `sampling` | language、call_shape、total/resolved/ambiguous/unresolved/conflict、resolver_version、duration |
| Process rebuild/projection | lifecycle `caller`；内部 stage `sampling` | Process 数、零步骤/截断数、DB/Qdrant 对账、generation、queue lag |
| hybrid lanes | `sampling` | dense/sparse/BM25 各耗时与候选数、RRF overlap、group coverage、top score；不记 query 正文 |
| impact assembly | `sampling` | seed 数、depth、affected 数、预算截断、graph degradation、duration |
| MCP/Chat retrieval | ledger | 两条链都写 `RetrievalTrace`，以 request/run/conversation id 关联 |

规则：

- 后台 payload 显式带 `initiated_by_user_id`，无用户为 `system`；worker 用 `bind_task_context`。
- 日志只记 query 长度/hash、计数和闭集枚举；禁止 query、源码、路径清单逐条 INFO。
- 所有异常文本经 `redact_secrets_in_text`；ledger payload 经 `redact_for_ledger`。
- 观测、ledger、projection 对账均 best-effort，不得反噬主查询；权限/exclusion 失败则相反，必须 fail-closed。
- resolver 质量指标按语言和 call shape 分桶，不能只报一个全仓 resolution rate。

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 小仓 / Process <100 | 同 collection 逻辑 namespace，单次 hybrid + bounded impact |
| 10 万边 / Process ≤300 | 保持现有 NetworkX LRU；Process 预建倒排；lane 并发；top-N 后才 impact |
| 超大单仓 | 强制 seed 子图、Process/impact 分预算；按 generation 分批 projection；不提高返回上限 |
| 多 worker 高并发 | Qdrant/DB 共用 canonical 水位；NetworkX 仍 per-worker，不引入远程图库 |

第一瓶颈会是 resolver 后全图重建与冷图内存，而不是 Process 数量；第二瓶颈是每次 query
对多个种子跑 impact。优先做 generation、cache hit、seed budget，不做图库迁移。

## Anti-Patterns

### 在线查询时补解析边

**错误：** query 根据同名或 embedding 临时连 caller/callee。
**后果：** 相同 commit 的结果不可复现，benchmark 无法归因。
**替代：** resolver 只在索引/回填阶段写 versioned evidence；在线只消费。

### 把 Qdrant Process 点当事实源

**错误：** 只写向量点，不落/不核对 `ProcessTrace`。
**后果：** projection 漂移后无法解释步骤和水位。
**替代：** DB canonical，Qdrant 可删可重建且按 generation 过滤。

### 在四个消费面复制 schema 和排序

**错误：** DRF、Chat、npm、task 各维护一次参数和默认值。
**后果：** 重演 npm MCP 漂移；同一 query 在不同入口得到不同结果。
**替代：** registry + manifest + generated adapters；入口只注入上下文。

### 把 GraphError 吞成空影响面

**错误：** 图不可用时返回 `affected=[]`。
**后果：** agent 会把“未知”误读为“安全”。
**替代：** 保留 error/degradation/staleness；空结果仅表示成功查询且确无命中。

### 为对齐 GitNexus 整体换图库

**错误：** 引入 Neo4j/Memgraph 等重写存储。
**后果：** 双写、权限、分支、水位、exclusion、部署复杂度全面放大。
**替代：** 对齐其 query contract 和 Process 检索/分组能力；现有 NetworkX 对单仓有界图足够。

## Integration Points

### New vs Modified

| Type | Components |
|------|------------|
| NEW | `services/code_graph_query/`、`process_search_index.py`、`impact_summary.py` |
| NEW | `tools/contracts/` 与 versioned manifest |
| NEW | TS/JS receiver、Python member、后置 Go selector plugin |
| MODIFIED | `CallData`、`CallEdge`、`SymbolResolver`、`resolver/wiring.py` |
| MODIFIED | `ProcessTrace`、process durable chain、Qdrant projection lifecycle |
| MODIFIED | MCP URL/view、Chat whitelist/adapter、npm generated tools、task policy intersection |
| UNCHANGED | GraphService/NetworkX 内核、Qdrant 基础设施、现有 impact/trace 算法、权限/exclusion 单一入口 |

### Recommended Build Order

```
Phase A  Baseline + contract
  ├─ 同仓同 commit v0.22 baseline
  ├─ GraphQuery request/response model
  └─ ToolContractRegistry / manifest skeleton

Phase B  Resolver facts + TS/JS
  ├─ additive CallEdge migration
  ├─ extractor hints
  └─ TS/JS import alias + receiver resolver + per-shape metrics

Phase C  Python resolver
  └─ import/member/self/class/constructor hints；复用 B 的 evidence contract

Phase D  Process first-class index
  ├─ ProcessTrace derived fields/version/generation
  ├─ deterministic document builder
  └─ Qdrant projection + migration/backfill/reconciliation

Phase E  Unified query
  ├─ Symbol + Process concurrent lanes
  ├─ RRF + process grouping + Community
  └─ structured response + freshness/degradation

Phase F  Impact summary
  └─ bounded seeds + existing GraphService + affected Process mapping

Phase G  Consumption convergence
  ├─ Django MCP + Chat thin adapters
  ├─ npm manifest/generated client
  └─ task/container policy intersection + schema hash gates

Phase H  Benchmark gate + Go
  ├─ 锁定按语言/框架/入口类型阈值
  └─ 仅在 TS/JS、Python 达标后扩 Go receiver/interface
```

顺序理由：baseline 必须先于任何回填；TS/JS 与 Python 共用数据契约但应分开验收；Process
hybrid 依赖较高质量 resolved edge，否则只是把错误调用链向量化；统一 query 依赖 Process
projection；影响摘要依赖稳定分组；最后再切消费面，避免未成熟内核同时放大到四个入口。

## Sources

- `.planning/PROJECT.md`（v0.24.0 目标、既有能力与约束）
- `server/codegraph/models.py`（Symbol/ImportEdge/CallEdge/SymbolCommunity/ProcessTrace canonical schema）
- `server/codegraph/extractors/{base.py,calls.py}`（现有 qualifier 捕获能力与缺口）
- `server/codegraph/resolver/{symbol_resolver.py,wiring.py,frontend_import.py,python_import.py}`（现有语言分派与 branch 缺口）
- `server/codegraph/services/graph_writer.py`（per-file 原子写、async ORM 线程隔离）
- `server/services/code_graph/{process_trace.py,affected_processes.py,impact_report.py}`（Process 构建、影响交集、formatter 边界）
- `server/services/retrieval/{hybrid_search.py,types.py}`（既有 dense+sparse/graph enrichment 与返回类型）
- `server/services/{community_enqueue.py,process_enqueue.py}`、`server/durable/tasks_impl.py`（durable 链与用户上下文）
- `server/agents/tools/{graph_tools.py,schemas/graph_tools.py}`、`server/agents/chat_runner.py`（Chat 薄壳与白名单）
- `server/mcp_tools/serializers.py::TOOL_SCHEMA_SNAPSHOT`、`mcp/src/tools.ts`、`test_mcp_package_alignment.py`（契约漂移现状）
- GitNexus MCP `query` 当前工具契约（process-grouped hybrid query、process symbols、definitions、RRF）

---
*Architecture research for: Friday AI v0.24.0 单仓图查询对齐 GitNexus*
*Researched: 2026-08-24*
