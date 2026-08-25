# Stack Research

**Domain:** v0.24.0 单仓 graph-aware query（Process 分组混合检索、语言感知调用解析、MCP 契约、可复现评测）
**Researched:** 2026-08-24
**Confidence:** HIGH（GitNexus v1.6.9、MCP 2026-07-28 规范、Qdrant 官方文档与本仓锁文件/源码交叉核验；排序效果仍须由本里程碑 baseline 实测）

## 结论先行

**运行时依赖零新增，现有依赖足够。** 本里程碑应增加的是索引对象、服务层编排、契约单一事实源和 benchmark 资产，不是另一套图数据库、搜索引擎或解析框架。

1. **Process 检索继续用 Qdrant dense+sparse+RRF。** 本仓已锁 `qdrant-client==1.16.2`，已有 named dense/sparse vectors、`Prefetch`、`FusionQuery(RRF)` 和老索引 dense fallback。为 `ProcessTrace` 建独立的全局 `code_graph_processes` collection，以 payload 按 repository/branch 隔离；不要混入 chunk collection，也不加 `rank_bm25`、Elasticsearch、LadybugDB/Kuzu。
2. **Process 继续落 Django `ProcessTrace`，NetworkX 继续负责图遍历。** GitNexus 的价值在“先召回 Symbol，再沿 `STEP_IN_PROCESS` 聚合 Process”，不是它选用哪种图库。本仓已有 `ProcessTrace.steps`、`SymbolCommunity`、`GraphService` 和 `networkx==3.6.1`，无需复制 GitNexus 存储栈。
3. **resolver 演进现有 Protocol + `SymbolIndex`。** 优先补 TS/JS receiver/import alias/re-export 与 Python import/member/receiver；保留 unresolved 和证据原因，禁止全仓同名 fuzzy 兜底。Go 后置。不要把 LSP 默认翻转夹带进本里程碑。
4. **新增一个 canonical `graph_query` 契约，而不是让 agent 编排四个旧工具。** Django service 是唯一实现；Chat、Django MCP、npm MCP、编码容器都由同一 schema/manifest 生成或校验。MCP 返回 `structuredContent` + `outputSchema`，同时保留 JSON text 兼容旧客户端。
5. **评测零新增库即可完成。** `pytest==9.0.2` + JSON/JSONL fixtures + stdlib `statistics`/`random`/`time.perf_counter_ns` 足够计算 Recall@k、MRR、resolved-edge precision/recall、Process step/file:line 命中、impact/trace 命中、延迟与 token。先冻结同仓同 commit 的 v0.22 baseline，再从数据锁门；不预设阈值。

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Django ORM / PostgreSQL（既有） | Django 5.1+；生产 PostgreSQL 17 | `ProcessTrace` canonical 数据、索引水位与构建状态 | 已有模型含 repository/branch/process_key/name/entry/steps/community_class/built_at_sha；保持操作态事实在 SQL，避免向量库成为唯一事实源 |
| Qdrant + qdrant-client | server 锁定 `1.16.2` | Symbol/Process dense+sparse hybrid recall 与 RRF | 本仓 `QdrantService.hybrid_search_by_name` 已是一请求双 prefetch + RRF；官方 Query API 原生支持此模式，且 payload filter 可按 repo/branch/kind/built_at_sha 限定 |
| fastembed | server 锁定 `0.7.4` | Process 文本 dense/sparse 向量 | 已用于现有混合索引，复用同一 encoder 和维度，保证查询向量与索引向量一致；不再引入 GitNexus 的 ONNX/transformers.js 栈 |
| NetworkX | server 锁定 `3.6.1` | Symbol→Process membership、impact/trace 与 Process 步骤装配 | v0.22 已验证；新需求是查询编排与边质量，不是图库性能迁移 |
| tree-sitter + 既有语言 grammar | `tree-sitter>=0.21`（现有 lock） | TS/JS/Python 调用、import、receiver 结构事实采集 | resolver 质量需要 AST 事实和语言规则；算法名不能替代 receiver/import evidence。沿用现有 extractor 避免双 AST |
| MCP Python SDK / TS SDK | Python `mcp>=1.25,<2`；npm `@modelcontextprotocol/sdk ^1.29.0` | 工具发现与调用 | 两端已在依赖树；Python `<2` 是 `claude-agent-sdk` 兼容约束，不能为本里程碑盲升 2.x |
| jsonschema + Pydantic | `jsonschema==4.26.0`；既有 Pydantic 2 | canonical input/output schema 校验 | MCP 2026-07-28 允许 `outputSchema` + `structuredContent`；本仓已有严格 Pydantic tool input 和 schema snapshot，足以建立单一契约 |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `QdrantService.hybrid_search_by_name` / `hybrid_search_multi_by_name` | 本仓现有 | dense+sparse RRF、单/多探针、dense fallback | Process 和 Symbol 两路召回都走这里；不要复制一份 Python RRF，避免 0/1-based rank、tie-break 和 fallback 漂移 |
| `services.query_embedding` / 现有 SparseEncoder | 本仓现有 | 自然语言 query 的 dense/sparse 编码 | Process 文本与查询必须复用相同模型/预处理；将 model id、vector dims 写入 index metadata |
| `GraphService` + `ProcessTrace` + `SymbolCommunity` | v0.22 既有 | graph-aware enrichment | hybrid 候选命中后批量查 membership，一次聚合 Process、Community、步骤和影响摘要；避免逐候选 N+1 |
| `codegraph.resolver.base.ImportResolver` + `SymbolIndex` | 既有 | 按语言替换解析策略 | 扩展 TS/JS/Python resolver；语言差异封装在 strategy，writer 与统计共用统一 `ResolveOutcome` |
| pytest parametrization | `pytest==9.0.2` | 按语言/框架/入口类型运行 golden corpus | 固定 corpus、commit、query、qrels，逐 bucket 输出结果；官方 pytest 支持 fixture/function 动态参数化 |
| Python stdlib `statistics`, `random`, `time`, `json`, `hashlib` | Python 3.14 | 指标、bootstrap CI、计时、manifest/hash | benchmark 规模有限时足够；固定 seed、记录样本数与逐 query 结果，不需 NumPy/SciPy/pandas |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `pytest -m perf` | 离线质量与延迟 benchmark | 仓库已声明 `perf` marker 且默认 CI 排除；质量回归可拆成快速 deterministic gate，墙钟 benchmark 独立运行 |
| JSONL benchmark manifest | 固定 repo、commit、branch、语言、框架、入口类型、query、qrels | manifest 必须包含 index config、embedding model、schema version、seed、机器信息；拒绝拿不同 commit/索引参数做前后对比 |
| schema alignment tests | 保证 Django、Chat、npm MCP、容器工具发现一致 | 扩展现有 `test_schema_snapshot.py` 与 `test_mcp_package_alignment.py`；npm 当前 37 工具中缺 v0.22 图工具，漂移是已证实事实 |
| `RetrievalTrace` / RequestMetric / ModelUsageRecord | 记录召回分层、耗时、token 与调用归因 | 新 graph query 是 `caller`；内部 dense/sparse、membership、impact enrichment 是 `sampling`；观测 best-effort |

## 具体技术选择与集成点

### 1. Process 索引：一等检索对象，不更换存储

推荐生成稳定的 `ProcessDocument` 投影，point id 由 `(repository_id, branch, process_key)` 确定性派生，`built_at_sha` 作为 payload 水位；同分支重建按 repository/branch 过滤删除旧点后批量 upsert，避免旧 SHA 点累积。payload 至少包含：

- `kind="process"`、`repository_id`、`branch_name`、`process_key`、`built_at_sha`
- `name`、HTTP method/path、入口 handler 与入口 `file:line`
- 终点名称与终点 `file:line`
- 有序步骤摘要（name、symbol type、file path；正文严格受 token/字符预算）
- community keys/summary、top modules、业务关键词
- `step_count`、`community_class`、`flags`（cycle/async/truncated）

索引文本应分别保留可解释字段，不把所有内容拼成不可审计大段：

```text
name + endpoint
entry + terminal
ordered step names
module/community summaries
file path tokens
```

**WHY：** GitNexus 当前 `query` 先对符号做 BM25+semantic RRF，再批量沿 `STEP_IN_PROCESS` 查询 Process，并以匹配符号 RRF 分累计和轻量 cohesion boost 排序。这个结构证明“候选→membership→Process 分组”有效，但不证明 Friday 必须采用 LadybugDB。Qdrant 官方支持同一请求 dense/sparse prefetch + RRF；Friday 已有完全相同能力。

推荐两阶段：

1. `symbol_hits` 与 `process_hits` 并行 hybrid recall；
2. 批量补 `symbol→community/process`，按 `process_key` 聚合；
3. 用可拆解信号排序：各召回路排名、命中步骤数、入口/终点命中、Community 命中、staleness/degradation；
4. 返回每个信号的 rank/source，不以未经 benchmark 的 magic weight 隐藏决策。

初版优先 rank fusion，不把 GitNexus 的 `totalScore + cohesion*0.1` 原样搬来。该权重是其实现选择，不是跨项目常数。若 baseline 证明某信号需要权重，再把权重外置并记录版本。

### 2. Process 构建：借鉴边界与确定性，不复制算法品牌

继续使用现有 Endpoint→正向 BFS→`ProcessTrace`。需要调整的是：

- 入口来源从“只有 Endpoint”扩展为可配置 entry classes 时，先由 benchmark 决定；本里程碑至少保留 HTTP Endpoint。
- 保留 depth/branch/frontier/process count ceilings，并把 dropped/truncated 计数写入构建结果与查询 degradation。
- 同 endpoint 多路径不能永远只留“最长一条”而没有证据；至少在 benchmark 中评估 top-N path coverage，再决定持久化条数。
- 所有排序加稳定 tie-break（process_key/symbol_id/file:line），同 commit 重建必须字节级稳定。
- 步骤 `file:line` 来自 Symbol/Endpoint 原始事实；缺失应返回 null + reason，不猜行号。

GitNexus v1.6.9 的 Process processor同样使用 entry-point scoring、受限 DFS、路径去重、entry-terminal 去重、固定 ceilings，并显式记录候选被截断、未遍历入口、深度截断、丢弃分支和丢弃 Process。这些“认识论字段”值得对齐；DFS/BFS 名称本身不构成质量证据。

### 3. 语言感知 resolver：扩展现有 seam

本仓当前已具备：

- `SymbolResolver`：同文件裸名 → import 解析 → Go selector → component 引用；
- `FrontendImportResolver`：相对路径、单个 tsconfig alias、扩展名/index；
- `PythonImportResolver`：相对/绝对 import 到文件；
- `CallEdge.callee_qualifier`：目前主要服务 Go；
- unresolved 留空而非全仓 fuzzy，方向正确。

必须调整：

| 优先级 | 调整 | 复用/新增 |
|--------|------|-----------|
| P0 TS/JS | 捕获 receiver、import local/original binding、default/named/namespace import、re-export；读取多 tsconfig `extends`/`baseUrl`/`paths` 与 workspace package 映射；按 receiver 类型/constructor/return type 解析 method | 复用 tree-sitter、`ImportEdge`、`callee_qualifier`（必要时泛化为 receiver evidence JSON）、`SymbolIndex`；新增语言 strategy 和 evidence/outcome，不加库 |
| P0 Python | 区分 `import a.b`、`from a.b import c`（c 可能是 symbol 或 submodule）、alias、package `__init__` re-export；用 `self`/`cls`、constructor、annotation、显式 return type 解析 member | 复用 `PythonImportResolver`；新增 binding/receiver facts 与确定性优先级，不加 mypy/pyright |
| P1 通用 | `ResolveOutcome` 记录 resolved/unresolved/ambiguous/external，带 reason/evidence/origin/language；按语言出 denominator | 现有 `ResolveResult` 演进；用于 benchmark 与 impact epistemic，不加库 |
| Future Go | go.mod/workspace、selector/receiver、interface dispatch 继续完善 | 本里程碑后置，避免范围扩张 |

GitNexus 当前实现不是一个“万能 resolver”，而是共享 pipeline + 每语言 `ScopeResolver` 配置：TS 读取 tsconfig/workspace，Python提供 namespace import/LEGB/MRO/receiver 规则，并把 constructor、return type、field fallback 等作为明确 capability。这支持 Friday 沿现有 Protocol 演进，而非引入 GitNexus 包或 LSP 默认翻转。

### 4. 统一 graph query 与 MCP 契约

推荐 canonical service：

```text
GraphQueryService.query(repository_id, query, branch?, limits?, include_content?)
  -> GraphQueryResult
```

结果顶层应稳定包含：

- `candidates`: Symbol 候选（uid/name/type/file/start/end、retrieval ranks/sources、resolution）
- `communities`: 命中的 Community 与 summary/member evidence
- `processes`: process_key/name/type/priority/signals/entry/terminal
- `process_steps`: process_key、step_index、symbol_id、name、`file_path`、`line`
- `impact_summary`: seed、risk、by-depth counts、affected processes/modules、epistemic/degradation
- `staleness`: requested branch、index SHA、current SHA（若可得）
- `degradation`/`truncated`/`warnings`
- `timing_ms` 与 token/size 元数据

契约实施：

1. Pydantic/dataclass 定义 canonical DTO；
2. 从同一 DTO 生成/导出 JSON Schema；
3. Django MCP 发布 input/output schema；
4. npm package 构建时消费生成的 manifest，而非手写第二份 `tools.ts`；
5. Chat tool 与 task 容器只做 adapter；
6. schema snapshot 比较工具名、required、properties、enum/default、响应 shape，不只比较 key 列表。

MCP 2026-07-28 规范明确：tool 可声明 `outputSchema`，返回 `structuredContent` 必须符合它；为兼容旧客户端，应同时返回序列化 JSON TextContent。现有 npm SDK `^1.29.0` 与 Python SDK 已足够，不需升级协议库。

### 5. Benchmark：新增资产，不新增统计栈

最小目录建议：

```text
server/tests/benchmarks/code_graph_query/
  manifest.json
  queries.jsonl
  qrels_symbols.jsonl
  qrels_processes.jsonl
  qrels_edges.jsonl
  run_benchmark.py
  metrics.py
  snapshots/
    v0.22.json
    candidate.json
```

必须分桶：language、framework、entry_type、query_type（业务自然语言/符号名/路径/API）、repo size。每个 case 绑定 repo remote/id、commit SHA、branch、index schema/model/config。

指标建议：

- Symbol：Recall@k、MRR；若 qrels 有等级再用 nDCG@k。
- Process：Process Recall@k、首个正确 Process rank、正确步骤覆盖率、步骤顺序一致率、`file:line` 命中率。
- Resolver：按语言分别报告 TP/FP/FN、precision/recall、unresolved/ambiguous/external 分桶；**分母必须固定**。
- impact/trace：golden affected set/path 命中、下界/截断/degradation 比例；不能把 partial 当 clean zero。
- 成本：index wall time、query cold/warm p50/p95、Qdrant/ORM/graph call counts、response bytes、估算 token。

比较规则：

- baseline 与 candidate 必须同仓、同 commit、同 query/qrels、同硬件/进程模式；输出环境 manifest。
- 排名/质量逐 query 保存，汇总之外保留 failure diff。
- 固定随机 seed；若用 bootstrap CI，保存 seed、重复数和样本数。
- 先跑 v0.22 baseline，再根据实测分布和业务容忍度锁 gate；研究阶段不臆造“提升 10%”或“p95 < 500ms”。
- 对“优于 v0.22”的证明至少同时满足：目标质量指标改善、关键 bucket 不回退、误连不增加、延迟/token 无不可接受退化。具体阈值由 baseline 后 requirements 决定。

`ir_measures`/`trec_eval` 是成熟选择，但当前指标少且需要自定义 Process/edge/file:line 指标，引入它们不会减少核心实现；先用透明的 stdlib 公式和 golden tests。若未来接 TREC qrels/run 生态或指标扩展到 MAP/nDCG 大集合，再考虑把 `ir_measures` 作为 **dev-only** 依赖。

## Installation

```bash
# v0.24.0 推荐：运行时与 benchmark 均零新增依赖
cd server
uv sync --locked

# npm MCP 沿用现有依赖，只需同步生成契约并构建
cd ../mcp
npm run build
npm test

# Future：只有决定接入 TREC 格式时才评估（本里程碑不加）
# cd ../server && uv add --dev ir-measures
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| Qdrant Process hybrid index | PostgreSQL FTS + pgvector | 只有部署明确取消 Qdrant、并愿意迁移所有现有 RAG 索引时；本里程碑无此证据 |
| Qdrant RRF | 手写 RRF | 只有需要融合 Qdrant 外的独立排名列表且无法在一次 Query API 表达时；仍须统一 1-based rank 与稳定 tie-break |
| Django `ProcessTrace` canonical + Qdrant 投影 | LadybugDB/Kuzu Process nodes | 只有整体迁移代码图到 property graph DB 时；当前会复制数据、权限、分支/水位和运维体系 |
| 现有 Protocol resolver | LSP/tsserver/pyright 作为默认真源 | 只有同 commit benchmark 证明质量收益覆盖冷启动、内存和部署成本后；默认翻转明确是 future |
| pytest + stdlib metrics | `ir_measures` / `trec_eval` | benchmark 扩成标准 TREC run/qrels、多种 IR 指标且维护成本明显下降时，作为 dev-only |
| canonical schema 生成多 adapter | 手写 Django/Chat/npm/task 四份 schema | 没有合理使用场景；手写多份已造成 npm MCP 漂移 |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `rank_bm25` | 本仓 Qdrant sparse vector 已承担 lexical/BM25 面；再建进程内索引带来刷新、分支、权限与多 worker 一致性问题 | Qdrant named sparse+dense + RRF |
| Elasticsearch/OpenSearch | 仅为 Process BM25 引入新服务，运维和数据同步成本远大于收益 | 现有 Qdrant |
| LadybugDB/Kuzu/Neo4j | GitNexus 的存储选型不是 Friday 功能前提；会形成第二图事实源 | Django ORM + GraphService + NetworkX + Qdrant 投影 |
| GitNexus npm/package 直接嵌入 | GitNexus v1.6.9 为 Node 22+、不同图存储/模型/许可证；Friday 已有同类底座，集成会绕过权限、排除、归因与水位 | 参考其契约/算法结构，落到 Friday service |
| `scikit-learn`/NumPy/SciPy/pandas 只为 benchmark | 现有指标公式简单，重依赖不带来硬收益 | stdlib + pytest |
| LTR/学习排序 | 当前 labeled query 数量未知，小样本易过拟合且难解释；违背“先 baseline 再锁门” | RRF + 可拆解信号；有足量 qrels 后再评估 |
| LLM 生成 Process 名/关键词作为唯一检索文本 | 不可复现、成本高、模型漂移；会让 benchmark 混入模型变化 | 先用确定性字段投影；LLM summary 仅可选信号并记录 model/version |
| 全仓同名 fuzzy resolver | 会提高“resolved 数”同时制造误连，直接污染 Process/impact/trace | 语言 import/receiver evidence；歧义返回候选或 unresolved |
| 只测 resolved rate | 把错误连接也算成功，无法证明边质量 | precision/recall + FP/FN + reason buckets |
| 直接照搬 GitNexus 排序常数 | `k=60`/cohesion 0.1 是实现起点，不是 Friday 数据上的最优证据 | baseline + qrels 后决定并版本化 |

## Stack Patterns by Variant

**如果仓库没有可用 embedding provider 或旧 collection 只有 dense：**
- 保持明确降级：sparse-only/dense-only 仍返回结果，`degradation` 标记缺失 lane。
- 不把“0 Process”解释成“仓库没有相关流程”；先区分索引缺失、stale、召回为空。

**如果 Process 数量小、精确 endpoint/符号查询占主导：**
- SQL 精确命中可作为独立候选 lane，再与 hybrid rank 融合。
- 不因此取消 Process 向量索引；业务自然语言仍需要 semantic lane。

**如果 resolver 无法确定 receiver 类型：**
- 返回 unresolved + reason/evidence，impact 标为 lower-bound/unknown。
- 可建议 grep 二次核验，但不得静默连接同名符号。

**如果 benchmark 后发现 TS/JS 提升明显、Python 无提升：**
- 按语言独立 gate 与发布；不要用总体均值掩盖某语言回退。

**如果未来 LSP 默认翻转：**
- 单独里程碑比较 tree-sitter-only 与 LSP cold/warm 质量、耗时、内存、故障降级。
- 本里程碑只保留 LSP 可选实验 lane，不改变生产默认。

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `qdrant-client==1.16.2` | 现有 Qdrant deployment | 当前代码已使用 `query_points`、`Prefetch`、`FusionQuery(RRF)`；无需升级 |
| `networkx==3.6.1` | Python 3.14 | 已锁定并直接声明 `<4` |
| `fastembed==0.7.4` | 现有 embedding 服务 | 索引与查询必须记录并核对 model/dim，防语义 lane 静默失效 |
| `pytest==9.0.2` | Python 3.14 | 现有 `perf` marker；参数化和 fixture 足够 |
| `jsonschema==4.26.0` | MCP JSON Schema | 可校验 canonical tool output；注意发布时固定 schema draft |
| Python `mcp>=1.25,<2` | `claude-agent-sdk>=0.1.58,<0.2` | 本仓注释明确 SDK 依赖 MCP 1.x lowlevel decorator，禁止盲升 2.x |
| npm `@modelcontextprotocol/sdk ^1.29.0` | Node `>=18`（当前 npm 包） | 足够发布 tools/list/call 与 schema；不需要跟随 GitNexus 的 Node 22 runtime |
| GitNexus `v1.6.9` | 参考实现，不作为依赖 | 最新 release 2026-07-04；其 package 要求 Node `^22.18 || >=24.11` 且是 PolyForm Noncommercial，进一步支持“不嵌入” |

## 明确的“不新增 / 不更换”

- 不新增生产 Python 包。
- 不新增数据库或搜索服务。
- 不更换 NetworkX、Qdrant、Django ORM、tree-sitter。
- 不引入 GitNexus runtime/package。
- 不引入 `rank_bm25`、Elasticsearch/OpenSearch、Neo4j/Kuzu/LadybugDB。
- 不引入 LTR、reranker 或新 embedding model，除非 baseline 给出硬证据。
- 不翻转 LSP 默认值；Go resolver 深化与真实跨仓 impact 留 future。
- 不为 benchmark 引入 NumPy/SciPy/pandas/scikit-learn；`ir_measures` 仅 future dev-only 候选。

## Sources

### GitNexus 官方实现（HIGH）

- https://github.com/abhigyanpatwari/GitNexus/releases/tag/v1.6.9 — 当前 release v1.6.9，2026-07-04。
- https://raw.githubusercontent.com/abhigyanpatwari/GitNexus/main/gitnexus/package.json — v1.6.9 依赖、Node 要求与 PolyForm Noncommercial license。
- https://raw.githubusercontent.com/abhigyanpatwari/GitNexus/main/gitnexus/src/mcp/tools.ts — `query` 契约：process-grouped hybrid search，返回 processes/process_symbols/definitions。
- https://raw.githubusercontent.com/abhigyanpatwari/GitNexus/main/gitnexus/src/mcp/local/local-backend.ts — hybrid 并行召回、批量 `STEP_IN_PROCESS`/Community enrichment、Process 聚合与 phase timing；也显示手写 RRF/常数可能漂移，故不照搬。
- https://raw.githubusercontent.com/abhigyanpatwari/GitNexus/main/gitnexus/src/core/search/hybrid-search.ts — BM25 + semantic + RRF 与 FTS 失败 semantic-only fallback。
- https://raw.githubusercontent.com/abhigyanpatwari/GitNexus/main/gitnexus/src/core/ingestion/process-processor.ts — entry scoring、受限遍历、路径去重、确定性 tie-break、截断统计。
- https://raw.githubusercontent.com/abhigyanpatwari/GitNexus/main/gitnexus/src/core/ingestion/languages/typescript/scope-resolver.ts — tsconfig/workspace/receiver/return type 的语言 capability。
- https://raw.githubusercontent.com/abhigyanpatwari/GitNexus/main/gitnexus/src/core/ingestion/languages/python/scope-resolver.ts — namespace import、LEGB、MRO、constructor/receiver 的语言 capability。
- https://raw.githubusercontent.com/abhigyanpatwari/GitNexus/main/gitnexus/bench/receiver-resolution/BASELINE.md — baseline.json 单一事实源、byte-exact check、按 origin/shape/language 记录 denominator，避免用直觉设阈值。

### 官方协议与检索文档（HIGH）

- https://modelcontextprotocol.io/specification/2026-07-28/server/tools — tools/list/call、`outputSchema`、`structuredContent` 合规要求与 text 兼容建议。
- https://qdrant.tech/documentation/search/hybrid-queries/ — Query API prefetch、RRF/DBSF、weighted RRF；权重应基于 validation set。
- https://qdrant.tech/documentation/search/text-search/hybrid-search/ — semantic + lexical 同请求融合，阈值需按自身数据调优。
- https://docs.pytest.org/en/stable/how-to/parametrize.html — fixture/function/dynamic parametrization。
- https://github.com/usnistgov/trec_eval/blob/master/README — qrels + ranked run 的标准 IR 评测工具与逐 query 输出。
- https://trec.nist.gov/pubs/trec16/appendices/measures.pdf — precision/recall/AP 等检索指标定义。

### 本仓证据（HIGH）

- `server/pyproject.toml` / `server/uv.lock` — qdrant-client 1.16.2、networkx 3.6.1、fastembed 0.7.4、pytest 9.0.2、jsonschema 4.26.0 已存在。
- `server/services/qdrant_service.py` — named dense/sparse、Qdrant RRF、multi-probe、dense fallback 已实现。
- `server/codegraph/models.py` — `ProcessTrace`、`SymbolCommunity`、CallEdge `callee_qualifier` 与 resolved callee 字段。
- `server/services/code_graph/process_trace.py` — Endpoint→Process 现有构建、步骤 `file:line`、硬 ceilings 与 degradation。
- `server/codegraph/resolver/` — 现有 `ImportResolver`/`SymbolIndex`/TS·JS/Python/Go strategy seam。
- `server/mcp_tools/serializers.py`、`server/agents/tools/`、`mcp/src/tools.ts` — 服务端/Chat/npm 多契约现状；npm 37 工具缺 `impact_analysis`、`trace_call_path`、`detect_changes`、`list_processes`、`get_process`，漂移已坐实。
- `server/tests/mcp_tools/test_mcp_package_alignment.py` 与 `test_schema_snapshot.py` — 可扩展的契约守门点。

---
*Stack research for: v0.24.0 单仓图查询对齐 GitNexus*
*Researched: 2026-08-24*
