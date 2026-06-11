# Project Research Summary

**Project:** Friday AI — v0.3.0 交付知识图谱（需求/缺陷 ↔ 方案 ↔ 代码 GraphRAG 关联）
**Domain:** 交付知识图谱 / 工程记忆（brownfield 增量，集成到既有 Django + Postgres + Qdrant 栈）
**Researched:** 2026-06-11
**Confidence:** HIGH（Stack/Architecture 基于本仓库实读 + 官方文档核实；Features 对标产品行为 MEDIUM-HIGH；Pitfalls 多数有官方 issue / 本仓库历史事故佐证）

## Executive Summary

本里程碑是典型的「工作流副产品型知识库」：对标 Linear Similar Issues、Glean engineering MCP、Zep/Graphiti 的共同结论是——关联与摄取必须是现有工作流的自动副产品（用户零额外维护成本），检索答案必须带出处与时间限定（"这个结论现在还作数吗"）。GitHub Copilot Workspace 被砍并入 Coding Agent 的教训进一步确认：不要做独立产品形态，而是把知识图谱长在 Friday 既有的方案生成 / 编码 / 飞书 / chat 流程里。Friday 的独特优势是实体全部来自结构化业务数据（飞书工作项三元组、CodingPlan UUID、TaskResult/MR），完全不需要 LLM 实体抽取——比 Graphiti/LightRAG 便宜且确定。

技术路线已高度收敛：**几乎零新依赖**（仅 `unidiff==0.7.5` 必加，`django-cte` 可选不推荐首期引入），全部复用既有栈——Postgres 17 递归 CTE（raw SQL，收口在 GraphStore 接口内）承载 bi-temporal 边与 1–3 跳遍历，Qdrant 新增单一 `delivery_knowledge` collection（dense+sparse hybrid，scalar int8 量化 + on_disk 应对 2560 维），`EmbeddingService`/`QdrantService`/`background_runner`/`GitPlatformClient` 直接消费零修改。新代码收敛为一个新 Django app `server/knowledge/`（4 张表 + ingestion/graph_store/search/diff_archiver 四个 service），对既有代码的修改仅为 6 处摄取 hook（每处 3–10 行）。

最大风险不在选型而在**一致性语义**：版本下线（旧方案被检索到 = 正确性事故，必须 `is_latest` filter 兜底而非依赖删除）、bi-temporal 的时区/有效性过滤/失效级联三连坑、摄取的幂等与异步边界（本仓库有 `CurrentThreadExecutor` 历史事故）、以及检索权限下沉（compat 层有 IDOR 前科）。这些全部要求在数据模型与摄取管线 phase 第一天就做对——事后回填 payload 权限字段或修复重复实体的成本是 HIGH。

## Key Findings

### Recommended Stack

本里程碑几乎不需要新增运行时依赖，核心是复用与拼装。新增项只有 `unidiff==0.7.5`（diff 解析，纯 Python 零传递依赖）；`django-cte>=3.0.0` 列为备选（仅当图遍历需与 RBAC QuerySet 深度组合时引入），首选 raw SQL `WITH RECURSIVE`（`connection.cursor()`），零依赖且 bi-temporal 谓词、深度上限、`path` 数组防环直写最清晰。

**Core technologies:**
- Django ORM + Postgres 17: bi-temporal 边模型 + 递归 CTE 1–3 跳遍历 — 沿用 `ChunkEdge` 模式（UUID 柔性引用 + CheckConstraint + 部分索引 `WHERE expired_at IS NULL`）；八引擎基准 PG 反超 Neo4j（22.5K vs 14.5K RPS）
- qdrant-client 1.16.2（锁定版，**无需升级**）: 新 collection 向量化/hybrid 检索/版本化下线 — Query API、scalar 量化、datetime payload index、filter delete、`batch_set_payload` 全部已含
- `EmbeddingService` + `sparse_encoder`（fastembed BM25）: 需求/方案/diff 文本向量化 — 系统配置远程 API（当前 doubao-embedding-text 2560 维），不绑定模型
- `unidiff==0.7.5`（**唯一必加**）: git diff 解析 → per-file/per-hunk 切块 + 元数据 — API 冻结稳定，自研不值得
- Python 3.14 stdlib `compression.zstd` + PG TOAST lz4: 全量 diff 归档压缩 — `TextField` + `ALTER COLUMN SET COMPRESSION lz4` 为主，超大 diff（>5–10MB）stdlib zstd 兜底，省掉 `zstandard` 包
- 长文本 chunking: 自研 markdown 标题感知分块（~100 行）— **确定性**是硬要求（同输入同切分 → `uuid5` point ID 幂等），排除 langchain/llama-index splitter

**明确排除**：图数据库（neo4j）、graphiti-core、Microsoft GraphRAG / LightRAG、pgvector、networkx、Celery、qdrant-client 升级。

### Expected Features

用户期望的统一画像：「我提一个新需求（任意入口），系统自动告诉我以前做过类似的吗、当时方案是什么、最后代码怎么改的、那个方案现在还作数吗——零维护成本，答案带出处和时间限定。」

**Must have (table stakes):**
- 统一实体/边模型（requirement/defect、technical_plan、code_change 四类实体 + 关系边）— 一切的地基，traceability 双向链共识
- 工作流自动摄取（方案生成/编码完成即入图）— Copilot 教训：用户不会手动建链
- 知识向量化入 Qdrant + 相似需求召回（top-K 历史需求 + 关联方案/MR）— Linear Similar Issues 已是行业基线
- 实体关联查看（需求→方案→diff→MR 双向遍历）+ 历史迭代轨迹查询（方案 v1→v2→v3 时间线）
- 检索命中最新版（旧版本向量下线，默认不召回失效内容）— 召回过期方案是负价值
- 至少一个程序化入口（MCP 工具优先）— agent 时代知识库先服务 agent

**Should have (competitive):**
- Bi-temporal 边 + 过时标记（四时间戳，失效信号来自结构化事件而非 LLM 检测）— 比 Graphiti 更便宜更确定
- 版本链（SUPERSEDES，prev/next 指针即可）
- diff→chunk 关联（与 `ChunkRegistry` 打通，"这个函数被哪些需求改过"）— 市面产品基本停留在文件级，潜在最深差异化；**唯一 HIGH 复杂度项，可降级为文件级**
- 时间感知混合检索（fused score = α·sim + recency；过时硬过滤而非降权；稳定事实不衰减）
- 多入口暴露（MCP / chat tools / workflow 节点 / npm skill 四形态共享同一 service 层）— workflow 节点让 ai_plan_generation 自动引用历史方案，是飞轮
- 检索结果带出处与时间限定 — 成本低收益高，建议直接并入 table stakes

**Defer (v2+):**
- LLM 相似度复评（"重复/相关/无关"分级）— 触发条件：向量召回精度不足
- diff→chunk 符号级精确对齐 + 漂移追踪、前端只读子图/时间线可视化、as-of 查询暴露
- 跨需求洞察报表、检索权重自适应

**Anti-features（明确不做）**：飞书双向同步（只单向摄取快照）、LLM 自由文本实体抽取、全图算法分析（社区发现/PageRank）、图谱可视化编辑器、对话全量记忆化（仅摄取"成为需求"的对话节点）、旧版本物理删除（失效不删除）、强一致同步索引（一律异步摄取）。

### Architecture Approach

新增一个 Django app `server/knowledge/` 作为独立 bounded context，包含 4 张表（`KnowledgeEntity` / `KnowledgeEntityVersion` / `KnowledgeEdge` / `CodeChangeArchive`）与四个 service（`ingestion.py` 统一摄取 + `sources/` normalizer、`graph_store.py` GraphStore Protocol + PG 实现、`search.py` 时间感知检索、`diff_archiver.py`）。引用策略双层：组织维度（project/repository）用 FK，跨域源对象用弱引用 `(source_kind, source_id)`（飞书工作项无本地模型可 FK；源删除不应抹掉知识历史），edge 两端 app 内 FK，code_change→chunk 弱引用 + reconcile 兜底。摄取经 6 处 hook（plan_generation / plan_approval / callbacks `_handle_completed` / mcp technical_plan_service / chat `CodingPlan` 模型方法 / feishu webhook）统一调 `ingestion` 公开函数，`transaction.on_commit` + `run_in_background` fire-and-forget。检索新建 `KnowledgeSearchService` 与 `HybridSearchService` **平行**（不扩展后者——它深耦合代码 chunk 语义且有 byte-equal 守门测试），复用底层件；diff 归档由 server 侧经 `GitPlatformClient.compare_branches`/`get_merge_request_diff` 拉全量（容器回传仅摘要级，不可用作归档源）。

**Major components:**
1. `knowledge` app（models + migrations）— bi-temporal 实体/版本/边 + diff 归档表
2. `KnowledgeIngestionService` + `sources/` normalizer — 多入口统一摄取，幂等 upsert + 版本翻转 + 向量写入
3. `GraphStore`（Protocol + PostgresGraphStore）— 图访问唯一收口，内置有效性过滤/深度上限/防环
4. `DiffArchiver` — git platform 拉全量 diff + `CodeChangeArchive` + `MODIFIES_CHUNK` 边
5. `KnowledgeSearchService` — Qdrant 召回（`is_latest` filter）∥ 图扩散 → 时间衰减 re-rank → 轨迹渲染
6. 四入口薄封装 — MCP `McpToolView` 子类 / chat `@tool` / workflow `BaseNode` / npm skill 文档

Qdrant 侧：单一 `delivery_knowledge` collection（知识实体量级比 chunk 低 2–3 个数量级，且相似召回天然跨项目），payload filter 隔离（`entity_kind`/`project_id`/`repository_id`/`is_latest`/`valid_at` 等全建 index）。

### Critical Pitfalls

1. **P1 版本下线漏删 = 旧方案被检索（正确性事故）** — 检索侧 `is_latest=true` filter 是第一道防线，删除只是优化；写入顺序 upsert 新 → `set_payload` tombstone 旧 → 按 point id 异步物理删（PG 记 point_id 列表为 source of truth）；删除失败必须响亮（不沿用 `return False` 静默语义）+ reconcile 对账命令。注意 Qdrant 默认 weak ordering 的 delete/upsert 竞态（qdrant#6556），`wait=True` 必加。
2. **P2 bi-temporal 三连坑（naive datetime / 忘加有效性过滤 / 失效不级联）** — 模型层 CheckConstraint + 写入口拒绝 naive datetime；有效性过滤**埋进 GraphStore 接口**而非靠约定；`invalidate_entity_version` 同事务级联失效实体 + 出入边，写 2–3 跳不可达测试。
3. **P3 摄取阻塞请求路径 + 重试重复摄取** — 所有入口只写摄取请求记录 + `transaction.on_commit(run_in_background)`；幂等键 `(source_system, source_event_id, content_hash)` 唯一约束（复用 feishu `ProcessedEvent` 模式）；本仓库有 `CurrentThreadExecutor` 历史事故，严禁请求循环里 `asyncio.create_task`。
4. **P6 检索越权（IDOR）** — 权限解析下沉检索 service 内部（签名强制 `user`，调用方参数只能收窄）；payload 第一天就含 `project_id`/`repository_id`（事后回填 HIGH 成本）；四入口全部 fail-closed，复用 v0.2.0 PAT 基建；compat 层有同款前科勿复制。
5. **P8 collection"维度不匹配即删库重建"语义** — 知识 collection 的 ensure 检测到不匹配必须拒绝并响亮报错（提供显式 `reembed_knowledge` 命令），绝不沿用 `create_collection` 的自动删重建。
6. **P10 召回面/轨迹面语义分裂** — 显式分两个查询面：召回走向量（只查 latest），轨迹按 natural key 走 DB 版本链（不依赖 Qdrant）——这反过来简化 P1（旧向量可安全物理删除）。

其余：P4 多入口重复实体（uuid5 natural key + chat 入口相似候选建 `relates_to` 边而非自动合并）、P5 异构语料召回偏置（分路召回 + re-rank + 20–50 条评测集）、P7 万行级大 diff（file→hunk 分层切块 + 生成文件 glob 跳过 + batch upsert + token 预算裁剪）、P9 GraphStore 形同虚设（边表 raw SQL 仅允许存在于 GraphStore 实现内）。

## Implications for Roadmap

研究三方（FEATURES 依赖图、ARCHITECTURE 构建顺序、PITFALLS phase 映射）高度一致，建议 5 个 phase：

### Phase 1: 数据模型 + GraphStore + collection 生命周期
**Rationale:** 一切功能依赖实体/边 schema；GraphStore 接口必须先行（第一个调用方就走接口，否则逃生门焊死 — P9）；payload 权限字段与 natural key 规则必须第一天定（P6/P4 回填成本 HIGH）。
**Delivers:** `knowledge` app 4 张表 + migrations、bi-temporal 约束（CheckConstraint + 部分索引）、GraphStore Protocol + PG 递归 CTE 实现（内置有效性过滤/max_hops≤3/防环）、`delivery_knowledge` collection 管理（拒绝自动删重建 + 维度校验）、payload schema 常量。
**Addresses:** 统一实体/边模型（table stakes 地基）。
**Avoids:** P2（约束 + 接口语义）、P6（payload 权限字段）、P8（collection 生命周期）、P9（接口收口）、P10（查询面边界决策）。

### Phase 2: 统一摄取服务 + 版本化机制（首批 2 触发点）
**Rationale:** 版本翻转/向量下线/幂等是摄取的内建语义而非后置功能，必须随 ingestion 核心一起落地；先接 2 个形态最稳定的触发点（chat `CodingPlan` 模型方法、MCP `technical_plan_service`）验证管线。
**Delivers:** `ingestion.py`（幂等 upsert + content_hash 短路 + 版本翻转 + tombstone 协议）+ `sources/coding_plan.py` / `sources/mcp_technical_plan.py` + 2 处 hook（`on_commit` + `run_in_background`）+ reconcile 对账命令。
**Uses:** EmbeddingService / SparseEncoder / QdrantService `*_by_name` / background_runner（全部零修改复用）。
**Avoids:** P1（tombstone + is_latest + point_id registry）、P3（幂等表 + 异步边界）、P4（natural key uuid5 + chat 相似候选策略）。

### Phase 3: 其余触发点 + 全量 diff 归档
**Rationale:** 依赖 Phase 2 的 ingestion 核心；diff 归档是全链路闭环（需求→方案→代码）的必需件，且是 6 触发点中最重的（git API + unidiff 切块 + chunk 关联）。
**Delivers:** callbacks `_handle_completed` / plan_generation / plan_approval / feishu webhook 4 处 hook；`DiffArchiver`（`compare_branches`/`get_merge_request_diff` 拉全量 → `CodeChangeArchive`（TOAST lz4）→ unidiff per-file/hunk 切块向量化 → `MODIFIES_CHUNK` 弱引用边）。chunk 级对齐为 stretch，文件级起步即可。
**Uses:** `unidiff==0.7.5`（本里程碑唯一新增依赖）、GitPlatformClient、ChunkRegistry `(repository, branch, file_path)` 索引。
**Avoids:** P7（分层切块 + 生成文件跳过 + batch + 10k 行 diff 夹具）、diff secret 脱敏。

### Phase 4: 时间感知混合检索
**Rationale:** 依赖 1–3 有数据可检；是里程碑的差异化承诺（fused score + 过时硬过滤 + 轨迹渲染）。
**Delivers:** `KnowledgeSearchService`（wave0 Qdrant hybrid 召回 `is_latest` filter ∥ wave1 GraphStore 1–2 跳扩散 → 时间衰减 re-rank（仅 top-N 候选）→ 轨迹 markdown/JSON，结果带 version/valid 区间/来源）；轨迹查询面（DB 版本链，不走向量）；与代码图谱桥接（`MODIFIES_CHUNK` → `HybridSearchService.find_related`）；20–50 条评测集（含中文 query → 英文 diff 用例）。
**Avoids:** P5（分路召回配额 + 评测集替代盲调）、P2（图扩散有效性审计）、P10（双查询面分别实现）。

### Phase 5: 多入口暴露
**Rationale:** 四入口共享同一 service 层，service 稳定前做入口是返工；薄封装层，四入口可并行。
**Delivers:** MCP 工具 2–3 个（`search_delivery_knowledge` / `get_entity_timeline` / `get_related_entities`，`McpToolView` PAT fail-closed）、chat `@tool`、workflow 检索节点（`BaseNode` 子类 + node-definitions.json，方案生成自动引用历史 = 飞轮）、npm skill 文档；每入口越权用例（A 用户 PAT 查 B 项目 → 空结果）。
**Avoids:** P6（四入口逐一鉴权 + 越权测试）、P3（入口只接线不各写触发逻辑）。

可选收尾（并入 Phase 5 或独立小 phase）：apscheduler 补偿扫描 job、`MODIFIES_CHUNK` reconcile 命令增强。

### Phase Ordering Rationale

- **严格串行依赖链**：实体模型 → 摄取（版本化内建）→ diff 归档 → 检索 → 入口。FEATURES 依赖图与 ARCHITECTURE 构建顺序独立推导出同一结论。
- **"第一天做对"项全部压到 Phase 1–2**：payload 权限字段、natural key、tombstone 协议、GraphStore 收口——PITFALLS 的 Recovery Strategies 表明这些事后修复成本为 HIGH。
- **diff→chunk 符号级对齐是唯一可降级项**：文件级起步不阻塞任何其他功能，符号级留 stretch/v1.x。
- **每 phase 可独立验证**：Phase 1 单测递归 CTE 遍历；Phase 2 幂等/版本翻转测试；Phase 3 大 diff 夹具；Phase 4 评测集基线；Phase 5 越权用例。

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 4（时间感知检索）：** 时间衰减参数（α/half-life）与 re-rank 策略需小范围调研/实验；跨语言（中文 query ↔ 英文 diff）召回质量未经本项目验证，依赖评测集。

Phases with standard patterns (skip research-phase):
- **Phase 1/2/3/5：** 全部为本仓库既有模式的拼装（ChunkEdge 模型范式、indexer 摄取范式、McpToolView/BaseNode 入口范式），标准实现即可。

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | 关键版本经 PyPI/官方文档核实，与 `server/uv.lock` 及现有代码逐一对照；唯一风险点 unidiff 维护活跃度低（已标注：~1k 行可 fork 兜底） |
| Features | MEDIUM-HIGH | 对标产品行为来自官方文档/工程博客（HIGH）；用户期望推断与复杂度评级为 MEDIUM |
| Architecture | HIGH | 核心结论全部基于本仓库代码实读验证（文件:函数级）；Graphiti bi-temporal 借鉴为 MEDIUM |
| Pitfalls | HIGH | Qdrant 行为有官方 issue 佐证；多个坑直接来自本仓库历史事故注释（qdrant_service timeout、background_runner、compat IDOR TODO） |

**Overall confidence:** HIGH

### Gaps to Address

- **跨语言检索质量（中文 query ↔ 英文 diff）**：doubao-embedding-text 的多语言对齐未经本项目实测 — Phase 4 评测集必须包含该用例；摄取 diff 时生成中文摘要双路嵌入作为对冲。
- **时间衰减参数**：无评测集前只能暂定 — Phase 2/3 末期开始积累真实摄取数据，Phase 4 调参看指标不看感觉。
- **chat 自然语言需求去重阈值**：相似候选建边策略的阈值需真实数据校准 — MVP 接受"新建 + relates_to 边"，REQUIREMENTS 阶段需显式决策交付知识是否默认全局共享（建议：是，方案/diff 本就是团队资产，但对话原文不入图）。
- **本地 SQLite 开发路径**：递归 CTE 防环的 PG 数组语法不兼容 SQLite — GraphStore 留 vendor 分支或测试限定 PG，Phase 1 落地时定。

## Sources

### Primary (HIGH confidence)
- 本仓库实读：`server/services/qdrant_service.py`、`server/code_relations/models.py`、`server/services/retrieval/hybrid_search.py`、`server/services/background_runner.py`、`server/subagent/api/callbacks.py`、`server/mcp_tools/`、`server/chat/models.py`、`server/feishu/views.py`、`server/services/git_platform/base.py`、`server/uv.lock`、`docker-compose.yaml`
- `.planning/PROJECT.md` v0.3.0 已定决策（PG+Qdrant 双栈 / GraphStore 接口 / 不做 LLM 抽取 / 八引擎基准）
- Qdrant 官方文档（quantization / points / low-latency search）+ qdrant/qdrant#6556（delete/upsert 竞态）
- Zep/Graphiti bi-temporal 模型（官方文档 + arXiv:2501.13956）
- PyPI/GitHub：django-cte 3.0.0、qdrant-client 1.16.2/1.18.0、unidiff 0.7.5；Python 3.14 stdlib `compression.zstd`（PEP 784）；docker-library/postgres lz4 编译
- Linear（Similar Issues / Triage Intelligence 工程博客）、Glean MCP 官方文档、GitHub Copilot Workspace→Coding Agent 官方 blog

### Secondary (MEDIUM confidence)
- Traceability 实践（Jama suspect links、ContextGit、tracey staleness 检测）
- 时间衰减检索文献（arXiv:2509.19376 fused score α≈0.7 half-life 14d、Hindsight recency-wins）
- Git 语义检索开源工具（GitLore、spelungit、diwa）
- OpenAI Cookbook temporal agents（失效级联实践）

### Tertiary (LOW confidence)
- doubao-embedding-text 中英跨语言对齐质量 — 需 Phase 4 评测集实测验证

---
*Research completed: 2026-06-11*
*Ready for roadmap: yes*
