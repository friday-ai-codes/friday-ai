# Phase 100: 知识收敛基座（learning case 入图 + 检索切换 + MCP 产物入图） - Context

**Gathered:** 2026-07-15
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous — 推荐值自动采纳）

<domain>
## Phase Boundary

统一知识库成立：用户与自动链路产出的 learning case、MCP 链路产物（coding plan / 仓库分析 / 执行 trace）全部进入既有 `KnowledgeEntity` + Qdrant `delivery_knowledge`，经 `DeliveryKnowledgeSearchService` 单一检索面可召回；`search_learning_cases` 底层从 token 打分切换为向量检索且对外契约不变。**不新建存储、不新建 Qdrant collection、不做平行检索服务。** 需求：KNOW-01 / KNOW-02 / KNOW-03。

</domain>

<decisions>
## Implementation Decisions

### Natural key 规则表（P7 前置，本 phase 首个 task）
- 扩 `generate_entity_id` docstring 规则表，新增 4 个 source_kind：
  - `learning_case` → source_id = `str(McpLearningCase.id)`（UUID）
  - `mcp_coding_plan` → source_id = `str(McpCodingPlan.id)`
  - `mcp_repository_analysis` → source_id = `str(McpRepositoryAnalysis.id)`
  - `mcp_execution_trace` → source_id = `str(McpCodingExecutionTrace.id)`
- Chat `coding_plan` 与 MCP plan 保持**不同实体 + 边显式关联**（RELATES_TO），不做硬去重（bridge 拷贝时序坑，STATE 已定版）。
- work_item 锚照抄 `knowledge/sources/mcp_plan.py` 的双事件模式（`feishu_work_item` source_kind + `{project_key}:{type}:{id}` source_id），禁止自造锚格式；锚料缺失时降级单事件（无 work_item 边）。

### EntityKind 扩展
- 新增 `EntityKind.LEARNING_CASE = "learning_case"`（CharField max_length=20 足够，不改字段）。
- Migration 照抄 Phase 79 先例 `knowledge/migrations/0007`：RemoveConstraint → AlterField choices → AddConstraint（`kentity_kind_valid`）。
- MCP plan / analysis / trace 实体 kind 复用既有值：plan→`tech_plan`、analysis→`document`、trace→`code_change`（不为它们扩新 kind——kind 语义按内容归类，来源经 source_kind 区分）。

### 检索分路修复（KNOW-02 的隐藏前置）
- `vector_recall.py` 的 `_DEMAND_KINDS` 加入 `LEARNING_CASE`；同时修复"传入 kinds 与白名单交集为空 → 回退全量"的吞参行为：显式传入 `entity_kinds` 时必须真过滤（交集为空返回空结果，不回退）。
- `search_similar(entity_kinds=["learning_case"])` 必须只返回 learning_case 实体（专项测试断言）。

### search_learning_cases 契约保持
- 底层切 `DeliveryKnowledgeSearchService.search_similar(entity_kinds=["learning_case"])`，命中后按 entity `source_id` 回捞 `McpLearningCase` 行，渲染**既有 `learning_case_payload` 外形**（case_id/title/…/score）。
- `TOOL_SCHEMA_SNAPSHOT` 的 `search_learning_cases` request/response 键集**完全不动**。
- score 语义定版：payload `score` = 向量融合分（`SearchResultDTO.score`，0–1 浮点），在 schema 描述中显式写明语义变更。
- hint 参数（repo_hints/file_hints/symbol_hints/work_item_type）不做摆设：作为查询增强（拼入查询文本）+ 结果层 rerank（命中 hint 的 case 提权），不静默丢弃。
- token 打分实现直接退役删除，**不留 fallback 开关**（golden set 对照测试作为验收门兜底；保留开关会造成双路径维护负担，与"单一检索面"目标冲突）。
- Qdrant 不可用时 fail-soft：`search_learning_cases` 捕获检索异常返回空 results 不 500（在 MCP service 层 catch）。

### MCP 三类产物入图（KNOW-03）
- 三个 normalizer：`knowledge/sources/mcp_coding_plan.py` / `mcp_repository_analysis.py` / `mcp_execution_trace.py`，注册进 `_NORMALIZERS`。
- 写入点投递：`views.py` AnalyzeRepositoryView / CreateCodingPlanView / ExecuteCodingPlanView 与 `work_item_execution_service.py` 的对应 acreate 后挂 `aschedule_ingestion`（on_commit 语义已内建，异常吞掉）。
- 边：plan→execution（HAS_PLAN 反向即 execution REFERENCES plan，按既有 EdgeSpec 语义选用 IMPLEMENTED_BY/REFERENCES 中与 `task_result.py` 一致的先例）；execution→PR 信息入 payload；plan 若有 work_item 三元组则走双事件锚。plan 实体与 chat `coding_plan` 实体经 RELATES_TO 边关联（如可反查到同 work_item）。
- 端到端断言：从 plan 实体沿边可达 execution 与 work_item（自动化测试）。

### Backfill
- 新建 management command `backfill_learning_cases`（照抄 `rebuild_project_context` 范式）：`async for` 遍历 `McpLearningCase` → `IngestionRequest(source_kind="learning_case", ...)` → `aschedule_ingestion`，幂等（重复摄取实体数不变、版本翻转正确）。
- MCP 三类产物存量同样纳入该命令（或姊妹命令）回填，避免"切换当天检索全空"。

### 观测（P8 内嵌验收）
- `search_learning_cases` 新召回路径继续经 `McpToolView._record` 写 `RetrievalTrace`（FILE trace 含 score/case_id），MCP 链 + Chat 链两条覆盖（Chat 链本 phase 只需保证 service 层可复用，白名单接入在 Phase 102）。
- 上报召回条数/耗时/score；事件 `category=caller`（MCP 入口）/`sampling`（内部检索步骤）。

### Golden set 验收门
- 建 golden set 对照测试（含路径/symbol 类查询）：以既有 `test_learning_cases.py` 用例 + 若干真实形态 query（路径命中、symbol 命中、中文问题描述）断言向量检索召回集合非空且目标 case 在 top-N。作为 KNOW-02 验收门。

### Claude's Discretion
- normalizer 内 content 拼装格式（title/problem/root_cause/solution/outcome 的 markdown 组装）
- backfill 命令的批次大小/进度输出
- 测试文件组织（沿用 server/tests/knowledge 与 server/tests/mcp_tools 既有布局）

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/knowledge/sources/mcp_plan.py` — 双事件 work_item 锚 + HAS_PLAN 边范本
- `server/knowledge/sources/coding_plan.py` / `task_result.py` — 单事件与 IMPLEMENTED_BY 边先例
- `server/knowledge/ingestion.py` — `IngestionRequest` / `aschedule_ingestion(initiated_by_user_id=...)`，normalize 返回 `list[IngestionEvent]`（kind/origin/source_kind/source_id/title/content/payload/edges/vectorize）
- `server/knowledge/models.py` L34–50 EntityKind、L101–114 `generate_entity_id` docstring 规则表、L178–181 CHECK 约束
- `server/knowledge/migrations/0007_*.py` — 扩枚举 migration 范本
- `server/knowledge/management/commands/rebuild_project_context.py` — backfill 范本
- `server/knowledge/retrieval.py` L33–109 `search_similar` 签名；`server/knowledge/exposure.py` `serialize_search_result`
- `server/interactions/ledger.py` `arecord_retrieval_trace`；`server/mcp_tools/views.py` L313–318/L1722–1733 trace 写入示例

### Established Patterns
- 入图唯一入口 `aschedule_ingestion`（INV-6）；on_commit + background runner，异常 warning 不上抛
- normalizer 注册表 `knowledge/sources/__init__.py` `_NORMALIZERS`（惰性 import）
- async ORM 一律 `sync_to_async` / async ORM API
- 快照测试 `server/tests/mcp_tools/test_schema_snapshot.py` 整表断言

### Integration Points / 已知坑
- `server/knowledge/vector_recall.py` L27–32/L213–223：`_DEMAND_KINDS` 白名单 + 交集为空回退全量——必须修，否则 `entity_kinds=["learning_case"]` 无效
- `search_learning_cases` 现实现 `server/mcp_tools/learning_case_service.py` L213–245（token 打分，最近 200 条窗口）
- `create_learning_case_from_technical_plan` L87–210 当前**不投递摄取**——KNOW-01 接线点
- 写点：`McpRepositoryAnalysis` views.py L1778；`McpCodingPlan` views.py L1894/1903 + work_item_execution_service L239/247；`McpCodingExecutionTrace` views.py L2083 + work_item_execution_service L301
- `McpLearningCase` 字段全集见 models.py L494–553（embedding_text 已有，作向量文本主料）

</code_context>

<specifics>
## Specific Ideas

- 核心思路"优雅好用"：不留双路径、不留摆设参数——hint 参数要真起作用，kind 过滤要真过滤。
- 检索切换三件套（normalizer + backfill + 读切换）必须同 phase 闭环上线，避免"切换当天全空"。

</specifics>

<deferred>
## Deferred Ideas

- Chat 白名单接入 `search_learning_cases`（Phase 102 KNOW-05）
- 编排召回扩 kinds（Phase 102 KNOW-04）
- 检索层关联簇去重（Chat plan 与 MCP plan 同簇只出最优一条）——如实测噪音明显再做，本 phase 只建边不做簇去重

</deferred>
