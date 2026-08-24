# Project Research Summary

**Project:** Friday AI — 里程碑 v0.24.0 单仓图查询对齐 GitNexus
**Domain:** brownfield 增量 — 单仓 graph-aware query（Process 一等混合检索、语言感知调用解析、统一工具契约、同仓同 commit 评测）
**Researched:** 2026-08-24
**Confidence:** HIGH（GitNexus 主线源码、MCP/Qdrant 官方规范、本仓锁文件与实现交叉核验；排序权重与回归阈值必须 baseline 后锁定，研究阶段不定目标值）

> **范围纪律：** 本文只综合本里程碑**新增**能力。v0.22.0 已交付的 GraphService、impact/trace、Community、Process 构建、权限/exclusion、Qdrant hybrid 基础设施视为既有底座，不重复立项。跨仓 impact、PDG/CFG、rename apply、以 Leiden 替换现有社区算法、引入 GitNexus runtime / 新图库 / 新搜索服务，均 out-of-scope。

## Executive Summary

v0.24.0 要交付的不是「再造一套代码图」，而是在既有 Django ORM + Qdrant + NetworkX 上，把 GitNexus 已验证的 **process-grouped hybrid query** 落到 Friday 的单仓、多消费面、可核验证据场景。专家做法是：索引期写好语言感知的调用边与 Process 投影；查询期只编排、不猜边；消费面只做协议适配。Friday 的差异化不是换存储，而是把 **Process 做成可独立召回的一等检索对象**（GitNexus 当前主线仍是先搜 Symbol 再沿 `STEP_IN_PROCESS` 归组），并一次返回可解释排序、步骤级 `file:line` 与有界 impact 摘要。

推荐路线：**运行时零新增 Python/生产依赖**。Process 继续以 Django `ProcessTrace` 为事实源，Qdrant 独立 collection 做 dense+sparse+RRF 投影；resolver 沿现有 Protocol + `SymbolIndex` 扩展 TS/JS receiver/import alias/re-export 与 Python import/member/receiver，Go 后置，禁止全仓同名 fuzzy，不翻转 LSP 默认。在线唯一编排入口为 `GraphQueryService`（STACK 所称 canonical `graph_query` / `GraphQueryService.query`，同一编排层），由 ToolContractRegistry 生成 Django MCP / Chat / npm MCP / 编码容器契约，消灭已证实的 npm 工具漂移。

关键风险不在「能不能检索」，而在**评测与契约不可复现**：混 commit 的 `file:line` 是伪证据；从被测图表反导 gold 会自我打分；overall 会掩盖语言/入口退化；先调权重再补 baseline 会把旧缺陷固化；MCP 只比工具名会让 schema 继续分叉。缓解是硬顺序：**先冻结同仓同 commit 的 v0.22.0 baseline 与 evaluator 口径 → 再改 resolver/索引/查询 → baseline 后单独 review 锁阈值**；观测 best-effort 且脱敏，权限/exclusion fail-closed。研究明确**不臆造** Recall/延迟/token 目标值。

## Key Findings

### Recommended Stack

详见 [STACK.md](./STACK.md)。结论先行：**现有依赖足够，本里程碑增加的是索引对象、服务编排、契约单一事实源和 benchmark 资产，不是另一套图数据库或解析框架。**

**Core technologies:**
- Django ORM / PostgreSQL（既有）：`ProcessTrace` canonical 事实、索引水位与构建状态 — 避免向量库成为唯一事实源
- Qdrant + `qdrant-client`（锁 1.16.2）：Symbol/Process named dense+sparse、`Prefetch` + `FusionQuery(RRF)`、payload 按 repo/branch/`built_at_sha` 过滤 — 复用 `hybrid_search_by_name`，不手写第二份 RRF
- fastembed（锁 0.7.4）：Process 文本与查询共用同一 encoder/维度 — 不引入 GitNexus ONNX/transformers.js
- NetworkX（锁 3.6.1）：membership / impact / trace / 步骤装配 — 新需求是编排与边质量，不是换图库
- tree-sitter + 既有 grammar：TS/JS/Python 调用、import、receiver 结构事实 — 算法名不能替代证据；不加 LSP 为默认真源
- MCP Python SDK（`mcp>=1.25,<2`）与 npm `@modelcontextprotocol/sdk ^1.29.0`：工具发现与 `outputSchema`/`structuredContent` — Python 不得盲升 2.x（`claude-agent-sdk` 约束）
- jsonschema + Pydantic、pytest 9.0.2 + stdlib `statistics`/`random`/`time`：契约校验与评测 — **不为 benchmark 引入 NumPy/SciPy/pandas/`ir_measures`**

**运行时零新增依赖（硬约束）：** 不新增生产 Python 包；不新增数据库或搜索服务；不更换 NetworkX/Qdrant/Django ORM/tree-sitter；不嵌入 GitNexus npm/package（Node 22+ 且 PolyForm Noncommercial）；不引入 `rank_bm25`、ES/OpenSearch、Neo4j/Kuzu/LadybugDB、LTR/新 embedding、全仓 fuzzy resolver。

### Expected Features

详见 [FEATURES.md](./FEATURES.md)。GitNexus `query` 是 BM25+semantic 并行 → RRF 合并 Symbol → 沿步骤归入 Process；Process **当前不是直接检索对象**。Friday 必须把 Process 名称/入口/终点/步骤摘要/模块/业务词纳入混合检索，这是可验证差异化，不是照抄。

**Must have（本里程碑 table stakes / MVP）：**
- 单一 graph-aware 入口：一次返回 Symbol 候选、Community、Process 分组、步骤证据、有界 impact；空 query 拒绝
- Process 一等 BM25/embedding 召回 + Symbol 间接映射双路合流（「业务词只在流程摘要」仍能命中）
- 可解释确定性排序：lane rank、RRF/图增强贡献、稳定 tie-break、排序版本；不照搬 GitNexus `cohesion*0.1`
- 步骤级 1-based `file:line` + 同一 index commit；重名消歧后才算 impact
- schema-preserving 预算裁剪与 lane 级降级（`partial`/unavailable 可见）；禁止 JSON 中段字符串截断
- 五消费面同一 canonical manifest（服务端、Chat、Django MCP、npm MCP、编码容器）
- 单仓同 commit benchmark：先记 v0.22 baseline，**后**锁门槛
- 权限/exclusion fail-closed + 可观测约束（触发用户、脱敏、`RetrievalTrace`）

**Should have（相对 GitNexus 的差异化，仍在 v0.24 内）：**
- Process 直接检索文档，不只 enrichment 标签
- NL→证据→有界影响面一次返回（完整闭包仍 drill-down）
- 完整排序账本可离线回放
- 证据一致性硬约束：混水位不得静默拼接

**Defer（v2+ / 本里程碑不做）：**
- 跨仓 query/impact；PDG/CFG；rename apply；Leiden 替换 Louvain；学习排序 / LLM 当最终分
- `task_context`/`goal` 真正入排序（GitNexus schema 有字段但单仓实现未消费；Friday 须独立增益对照后才启用）
- Process LLM 摘要作为唯一检索文本；query 分页 cursor（仅当 top-N 语义裁剪被 benchmark 证伪）
- 翻转 LSP 默认；Go resolver 深化；真实跨仓 impact

### Architecture Approach

详见 [ARCHITECTURE.md](./ARCHITECTURE.md)。**不替换** ORM、Qdrant、NetworkX。Canonical 图仍是 `Symbol` / `CallEdge` / `SymbolCommunity` / `ProcessTrace`；Qdrant 是可重建 Process 投影；NetworkX 是按需分析投影。

**Major components:**
1. **语言感知 resolver（索引期）** — 抽取只记语法 hint；全仓 `wiring` 按 `(repository, branch)` 批量裁决；TS/JS → Python → Go 后置；`unresolved` 留空 + reason，禁止同名 fuzzy
2. **Process 一等投影** — `ProcessTrace.steps` 为步骤事实；确定性 `ProcessDocument`；独立 collection（勿混 chunk）；point id 由 `(repository_id, branch, process_key)` 派生；generation/`built_at_sha` 过滤，禁止新旧混排
3. **`GraphQueryService`** — 入口无关唯一编排：权限/exclusion/水位门 → Symbol lane ∥ Process lane → RRF + Process 分组 + Community → 有界 impact → 统一响应（含 `degradation`/`staleness`/`timing`）
4. **ToolContractRegistry** — Pydantic + versioned manifest 单一事实源；adapter 只鉴权/注入/协议映射；npm `tools.ts` 改为生成物
5. **ImpactSummaryAssembler** — 有限种子复用现有 `run_impact`；空结果不得解释为安全；默认不新增 LLM 调用

查询不得在线补边。resolver 回填必须贯穿 `branch_name`。durable 链：resolution → invalidate → Community → Process → Qdrant sync；均携带 `initiated_by_user_id`。

### Critical Pitfalls

详见 [PITFALLS.md](./PITFALLS.md)。阈值**不得**在研究阶段填写。

1. **「同仓」却不同 commit** — `commit_sha == indexed_commit_sha == gold.commit_sha`，否则 run **INVALID**；`file:line` 只从该 commit blob 核验，不读工作树
2. **分母/命中规则未锁** — 空 gold 不算 Recall=1；无预测 precision=`N/A`；Process 禁止名称模糊命中；edge gold 来自独立 callsite 抽样，不从被测 `CallEdge` 反导
3. **overall 掩盖分桶退化** — 必报语言/框架/入口；受保护桶回退不可被 overall 抵消；稀疏桶 `INSUFFICIENT_DATA`
4. **先调算法再保存 baseline** — 必须先跑未修改的 v0.22.0；dev/locked_test/holdout 分组切分；阈值单独提交 review；禁止测试失败自动刷新 baseline
5. **MCP 只对齐工具名** — 比完整 input/output schema、错误枚举、构建产物（npm tarball / task 镜像）；缺失 fail 不 skip；`structuredContent` + 兼容 JSON text

## Implications for Roadmap

相位代号与 PITFALLS 对齐：**B0 基准协议** → 改算法；ARCHITECTURE 的 A–H 映射到同一条依赖链。Process hybrid **依赖**较高质量 resolved edge，否则只是把错误调用链向量化。消费面收敛必须在内核稳定之后，避免把半成品放大到四个入口。

### Phase 1: B0 基准协议、v0.22 baseline 与契约骨架
**Rationale:** 任何回填/权重/门禁若发生在冻结 baseline 之前，后续「提升」不可证明。
**Delivers:** 同仓同 commit manifest；evaluator 分母与 identity 规则；dev/locked/holdout 切分；v0.22.0 逐 case/逐桶原始结果（**无阈值**）；`GraphQueryService` request/response 与 ToolContractRegistry 骨架。
**Addresses:** FEATURES TS-14 / MVP-01 骨架 / BENCH-01 的冻结协议；TS-12 的 schema 雏形。
**Avoids:** Pitfall 1/2/4；「先改看起来更好再补 baseline」。
**Uses:** pytest + stdlib metrics；既有 `test_schema_snapshot` / alignment 测试扩展点。

### Phase 2: B1 调用边质量 — TS/JS resolver（P0）
**Rationale:** 语言感知解析是 Process/impact/trace 的上游事实；TS/JS receiver + import alias/re-export 是本里程碑优先缺口。
**Delivers:** additive `CallEdge` evidence 字段；extractor `resolution_hints`；TS/JS strategy；按 language×call_shape 的 resolved/unresolved/ambiguous 统计；dry-run 对比后再写 FK。
**Addresses:** FEATURES 对 resolved edge 分语言度量；STACK resolver P0 TS/JS。
**Avoids:** Pitfall 5（自我评测）；全仓 fuzzy；在线 query 补边。
**Implements:** `codegraph/resolver` plugin + branch-aware `wiring`。

### Phase 3: B1 续 — Python import/member/receiver（P0）；Go 后置
**Rationale:** 与 TS 共用 `ResolveOutcome` 契约，但必须**分开验收**，避免 Python 样本淹没 TS 回退。
**Delivers:** Python binding/receiver 确定性优先级；不分母漂移的 per-language 报告。Go selector/interface **不阻塞**统一契约与 harness。
**Addresses:** STACK P0 Python；FEATURES「按语言独立测」。
**Avoids:** Pitfall 3；用总体 resolution rate 代替分桶。
**Uses:** 现有 `PythonImportResolver` 扩展，不加 mypy/pyright。

### Phase 4: B2 Process 一等索引
**Rationale:** 没有独立 Process 检索文档，就仍是 GitNexus 式 Symbol→Process enrichment，无法验收「摘要词命中流程」。
**Delivers:** 确定性 Process 文档字段（name/entry/terminal/ordered steps/module/keywords，受 token 预算）；独立 Qdrant collection；generation 对账；重建字节级稳定 tie-break。
**Addresses:** FEATURES TS-03 / MVP-02 / PROC-01/02。
**Avoids:** 把 Qdrant 当事实源；混入 chunk collection；照搬 GitNexus 排序常数。
**Uses:** 既有 hybrid_search + fastembed；`ProcessTrace` 仍 canonical。

### Phase 5: B3 统一 `GraphQueryService` 与证据
**Rationale:** 双 lane 与分组依赖 Process 投影与边质量；在线只消费索引期事实。
**Delivers:** Symbol∥Process 并发召回、RRF、Process 嵌套结果、`standalone_symbols`、`why_matched`/breakdown、`as_of`、schema-preserving 截断、lane `retrieval_status`。
**Addresses:** FEATURES TS-01/02/04/05/09/10/11 / MVP-03/05。
**Avoids:** Pitfall 1 的响应侧（无 `as_of`）；字符串 maxTokens 截 JSON；静默 BM25-only。
**Implements:** `services/code_graph_query/`。

### Phase 6: B3 续 — 有界 impact 摘要
**Rationale:** 消歧与稳定分组先于 impact；未消歧不得包装成确定影响面。
**Delivers:** 有限种子 + 现有 GraphService；structured impact_summary + coverage/truncation；稳定错误枚举；负路径（不可达/歧义/stale/exclusion）。
**Addresses:** FEATURES TS-07/08 / IMPACT-01 / DISAMB-01。
**Avoids:** 空数组当安全；用生产 BFS 当 impact gold。
**Implements:** `impact_summary.py` assembler，不把 MR formatter 当 canonical。

### Phase 7: B4 五消费面契约收敛
**Rationale:** 内核未稳就铺四入口会重演 npm 漂移；契约必须从同一 manifest 生成。
**Delivers:** Django MCP / Chat 薄适配；npm generated client + tarball conformance；task 镜像 allowed-tools 交集 + schema hash 门；`outputSchema` + `structuredContent` + JSON text 兼容；`listChanged` 纪律。
**Addresses:** FEATURES TS-12 / MVP-06 / CONTRACT-01 / DISCOVER-01。
**Avoids:** Pitfall 8；只比工具名；CI skip 缺失子模块。
**Uses:** 现有 MCP SDK 版本，不升协议大版本。

### Phase 8: B5 回归门、观测与（可选）Go
**Rationale:** 阈值只能在 baseline 分布与产品风险评审后锁定；Go 仅在 TS/JS、Python 达标后扩展。
**Delivers:** threshold policy **单独提交**；受保护桶门禁；冷/热延迟与 token 同分母规则；caller/sampling 事件与 `RetrievalTrace`；必要时 Go receiver 增量。
**Addresses:** FEATURES TS-13/14 / MVP-07/08 / OBS-01 / BENCH-02（阈值字段在采集前不得伪造）。
**Avoids:** 臆造「提升 10%」或「p95 < 500ms」；自动刷新 baseline；观测反噬主查询。

### Phase Ordering Rationale

- **评测协议先于算法：** 同 commit 冻结与分母锁定是所有质量声明的前提（PITFALLS B0）。
- **边 → Process 索引 → 统一查询 → impact → 消费面：** 与 ARCHITECTURE A–G 及 FEATURES 依赖图一致。
- **语言分开验收、Go 后置：** 防止 overall 掩盖；不让 interface dispatch 阻塞契约与 harness。
- **阈值后置：** 研究只定义指标维度与冻结协议，不定义数值门。

### Research Flags

规划阶段建议加深研究（`/gsd-plan-phase --research-phase`）：
- **Phase 2–3（resolver）：** TS receiver/tsconfig workspace 与 Python import/MRO 的本仓缺口对照 GitNexus ScopeResolver capability，需对着 extractor 现状逐条映射
- **Phase 4（Process 文档与融合信号）：** 文档字段与 rank fusion 信号集合需对照真实 Process 文本长度/截断；**权重仍待 baseline，本阶段不得锁 magic weight**
- **Phase 8（阈值）：** 必须用 B0 实测分布 + 评审，不能在计划里预填目标值

可跳过专项调研、按既有模式落地：
- **Phase 1 的 pytest harness / JSONL manifest：** 本仓已有 per-case macro 与 schema snapshot 模式
- **Phase 5 的 Qdrant RRF 调用：** `QdrantService.hybrid_search_by_name` 已是官方 Query API 形态
- **Phase 7 的 MCP 薄适配：** 规范与 SDK 已锁定；工作量在生成链与产物测试，不在换协议

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | 锁文件、本仓 hybrid/RRF 实现、MCP 1.x 约束、GitNexus 存储选型「只参考不嵌入」均有一手证据；融合权重待测 |
| Features | HIGH | GitNexus `query` 分组/截断/降级以源码为准（文档旧说「step count 归一化」已否决）；Process 直接检索的**增益幅度** MEDIUM，须 BENCH 实测 |
| Architecture | HIGH | 接缝来自本仓 codegraph/services/mcp 路径；入口命名以 `GraphQueryService` + registry 为准 |
| Pitfalls | HIGH | IR 分母、call-graph 无完备 GT、MCP schema 漂移均有官方/论文/本仓测试佐证；**阈值故意未定** |

**Overall confidence:** HIGH（方向与约束）；MEDIUM（Process 双路召回的实际 lift、具体回归数值）

### Gaps to Address

- **回归阈值与排序权重：** 研究禁止填写。规划/执行必须先跑 v0.22 baseline，再单独 PR/review 锁门。处理：Phase 1 只交原始分布；Phase 8 才写 policy。
- **Process 直接检索增益未知：** 机制补 GitNexus 间接映射缺口，幅度未知。处理：Phase 4 fixture「词只在 Process 文档」作能力验收；是否提高 Recall 看 BENCH，失败则降级为 enrichment-only 并显式 `degradation`。
- **GitNexus `task_context`/`goal` 未入排序：** 公开 schema 有字段、实现未消费。处理：v0.24 不广告这些参数有效；P2 需独立 A/B。
- **同 endpoint 多路径持久化条数：** 现有「最长一条」可能丢证据。处理：benchmark 评估 top-N coverage 后再决定条数，不在研究中拍板。
- **研究文件内部命名：** STACK 使用 `GraphQueryService.query` / collection 名；ARCHITECTURE 使用 `GraphQueryService` 与 `ProcessSearchIndex`。roadmap 以 **`GraphQueryService` + Process 独立 Qdrant collection + Django `ProcessTrace` canonical** 为准，计划阶段统一符号名。
- **MCP spec 日期：** STACK 引 2026-07-28，PITFALLS 引 2025-06-18 tools 页。处理：实现跟本仓已锁 SDK；`outputSchema`/`structuredContent`/`listChanged` 以官方 tools 规范为准，计划时核对当前 spec URL。

## Out of Scope（再次钉死）

- 跨仓 graph-aware query / group impact
- 自研或扩展 PDG/CFG/语句级数据流
- rename apply；社区算法替换（Leiden）
- 引入 GitNexus 包、新图库、新搜索服务、生产新 Python 依赖
- 默认翻转 LSP；本里程碑深化 Go resolver（可留 phase 尾部可选）
- LTR / LLM 最终排序分 / LLM 生成 Process 检索正文作为唯一文本
- **任何在 baseline 前写死的 Recall@k、延迟、token 数值目标**

## Observability Constraints（横切，每相位必守）

完整规范见仓库可观测性文档；本里程碑增量：

| 层 | category | 要点 |
|----|----------|------|
| 外部 graph query | `caller` | started/completed/failed、actor、source、repo、`duration_ms`、result/degradation count |
| resolver 批任务 | job=`caller`；边汇总=`sampling` | language、call_shape、resolved/ambiguous/unresolved、`resolver_version` |
| Process 重建/投影 | lifecycle=`caller`；stage=`sampling` | Process 数、截断、DB/Qdrant 对账、generation |
| hybrid lanes | `sampling` | 各路耗时与候选数、RRF overlap；**不记 query 正文** |
| impact | `sampling` | seed/depth/截断/graph degradation |
| MCP + AI 对话 | ledger | 两条链写 `RetrievalTrace`，用 request/run/conversation id 关联 |

- 后台必须显式 `initiated_by_user_id`（无用户为 `system`），worker 入口 re-bind。
- 日志只记长度/hash/计数/闭集枚举；凭证与异常走 `redact_secrets_in_text`；入库走 `redact_for_ledger`。
- 观测、ledger、对账 **best-effort，失败不反噬主查询**；权限/exclusion **fail-closed**。
- 禁止高频循环 INFO；resolver 质量按语言与 call shape 分桶。

## Sources

### Primary (HIGH confidence)

- GitNexus v1.6.9 / 主线 `11a60e6`：`local-backend.ts`（并行召回、RRF、Process 分组、cohesion、tie-break）、`tools.ts`、`hybrid-search.ts`、`process-processor.ts`、TS/Python `scope-resolver.ts`、MCP resources/output-budget
- [MCP Tools specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools) 与 STACK 所引 2026-07-28 tools 页：`outputSchema`、`structuredContent`、`listChanged`
- [Qdrant hybrid Query API](https://qdrant.tech/documentation/search/hybrid-queries/)：prefetch + RRF；权重须 validation set，非跨项目常数
- 本仓：`server/pyproject.toml`/`uv.lock`；`qdrant_service.py`；`ProcessTrace`/`codegraph/resolver/`；`test_mcp_package_alignment.py`（目前主要比工具名，漂移已坐实）；`.planning/PROJECT.md` v0.24.0 目标与边界
- CodeSearchNet（去近重复、按仓切分）；Helm et al. 静态调用图 GT 不可完备；GitNexus receiver-resolution `BASELINE.md`（先 baseline.json 再设阈值）

### Secondary (MEDIUM confidence)

- Agent Retrieval Bench / SWE-Explore（2026）：冻结 commit、行级 GT、正负 retrieval — **只作设计参照，不照搬其目标值**
- GitNexus Process 直接检索对 Friday 的召回增益：机制成立，幅度待 BENCH

### Tertiary (LOW confidence)

- 无。排序常数（如 GitNexus `k=60`、cohesion 0.1）明确标为**不可迁移的实现选择**，不是证据。

---
*Research completed: 2026-08-24*
*Ready for roadmap: yes*
*Synthesized from: STACK.md, FEATURES.md, ARCHITECTURE.md, PITFALLS.md*
