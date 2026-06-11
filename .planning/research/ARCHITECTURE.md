# Architecture Research

**Domain:** 交付知识图谱（需求/缺陷 ↔ 技术方案 ↔ 代码 diff 的 GraphRAG 关联）— brownfield 集成架构
**Researched:** 2026-06-11
**Confidence:** HIGH（核心结论全部基于实读本仓库代码验证；外部模式参考 Graphiti bi-temporal 设计为 MEDIUM）

> 本文回答：v0.3.0 新能力如何与现有 Friday AI 架构集成。所有"现有代码"引用均已实读验证（文件:函数/行号）。
> 下游消费者：roadmapper 划分 phase。重点输出集成点、新增 vs 修改、数据流、构建顺序。

## Standard Architecture

### System Overview（新增组件在现有架构中的位置）

```
                      ┌──────────────── 摄取入口（全部为既有代码路径埋 hook）────────────────┐
                      │                                                                      │
  workflow:           │  chat:                    MCP HTTP:                  飞书:           │
  plan_generation.py  │  agents/tools/            mcp_tools/                 feishu/views.py │
  plan_approval.py    │  coding_tools.py          technical_plan_service.py  Workitem*Event  │
  (approved port)     │  (create/update_          (acreate 落库点)                            │
                      │   coding_plan @tool)                                                  │
  subagent/api/       │                                                                      │
  callbacks.py        │                                                                      │
  (_handle_completed) │                                                                      │
        │             └───────────────┬──────────────────────────────────────────────────────┘
        │                             │ fire-and-forget（services/background_runner.run_in_background）
        ▼                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  NEW: server/knowledge/  （新 Django app = 新 bounded context）              │
│                                                                              │
│  ingestion.py        KnowledgeIngestionService（统一摄取，多入口复用）        │
│  diff_archiver.py    server 侧经 GitPlatformClient 拉全量 diff 并归档        │
│  graph_store.py      GraphStore 接口（PG 递归 CTE 实现，留换引擎逃生门）      │
│  search.py           KnowledgeSearchService（时间感知混合检索，与             │
│                      HybridSearchService 平行，复用底层件）                   │
│  models.py           KnowledgeEntity / KnowledgeEntityVersion /              │
│                      KnowledgeEdge（bi-temporal）/ CodeChangeArchive         │
└──────────┬──────────────────────────────────────┬────────────────────────────┘
           │ ORM                                  │ 向量
           ▼                                      ▼
   ┌───────────────┐                     ┌──────────────────────────┐
   │ Postgres      │                     │ Qdrant                   │
   │ knowledge_* 表 │                     │ NEW: delivery_knowledge  │
   │（与 chunk_*    │                     │ （单 collection，hybrid   │
   │  edges 并存，  │                     │  dense+sparse，payload    │
   │  不迁移）      │                     │  filter 隔离 project）    │
   └───────────────┘                     └──────────────────────────┘
           ▲                                      ▲
           │ MODIFIES 边弱引用 chunk_id            │ 复用 EmbeddingService /
   ┌───────┴────────┐                             │ SparseEncoder / QdrantService
   │ code_relations │                     ┌───────┴───────────┐
   │ ChunkRegistry  │                     │ services/         │
   │ ChunkEdge      │                     │ embedding.py 等    │
   │（保持不动）     │                     └───────────────────┘
   └────────────────┘

  暴露出口（复用既有四种入口模式，全部为新增文件、零修改框架）：
  - MCP HTTP tool   → mcp_tools/views.py McpToolView 子类模式（PAT 认证 + interactions 审计）
  - chat agent tool → agents/tools/ 新增 @tool（langchain_adapter 自动适配）
  - workflow node   → workflows/nodes/<category>/ 放 BaseNode 子类即自动注册
  - npm skill       → mcp/ 包（cli.js）+ skills 文档，指导外部 agent 调上述 MCP tool
```

### Component Responsibilities

| Component | Responsibility | 新增/修改 | 位置 |
|-----------|----------------|-----------|------|
| `knowledge` app | 实体/边/版本模型 + migrations，bounded context | **新增** | `server/knowledge/` |
| KnowledgeIngestionService | 统一摄取：实体 upsert + 版本翻转 + 向量写入 + 建边 | **新增** | `server/knowledge/ingestion.py` |
| GraphStore | 图访问唯一收口（1–3 跳扩散 PG 递归 CTE），接口化 | **新增** | `server/knowledge/graph_store.py` |
| DiffArchiver | 全量 diff 拉取（git platform）+ 归档 + 向量化 + chunk 打通 | **新增** | `server/knowledge/diff_archiver.py` |
| KnowledgeSearchService | 向量召回 + 图扩散 + 时间衰减/过时标记 | **新增** | `server/knowledge/search.py` |
| 摄取 hook（6 处） | 在既有路径调 ingestion（见下文清单） | **修改**（每处 3–10 行） | 见 §摄取触发点清单 |
| `delivery_knowledge` collection | 知识向量存储（dense+sparse hybrid） | **新增**（Qdrant 内） | 经 `QdrantService.create_collection_by_name` |
| MCP tool / chat tool / workflow node / npm skill | 多入口暴露 | **新增**（各入口新文件） | 见 §Integration Points |

## Recommended Project Structure

```
server/knowledge/                  # 新 Django app（沿用 "app 即 bounded context" 惯例）
├── __init__.py
├── apps.py
├── models.py                      # KnowledgeEntity / KnowledgeEntityVersion / KnowledgeEdge / CodeChangeArchive
├── migrations/
├── ingestion.py                   # KnowledgeIngestionService（统一摄取入口，幂等）
├── sources/                       # 各来源 payload → 统一实体 DTO 的 normalizer
│   ├── coding_plan.py             #   chat.CodingPlan → entity
│   ├── mcp_technical_plan.py      #   McpWorkItemTechnicalPlan → entity
│   ├── work_item.py               #   飞书工作项（McpWorkItemContext / webhook payload）→ entity
│   └── task_result.py             #   TaskResult/CodingSession 完成 → code_change entity
├── diff_archiver.py               # 全量 diff 获取 + 归档 + chunk 关联
├── graph_store.py                 # GraphStore Protocol + PostgresGraphStore 实现
├── search.py                      # KnowledgeSearchService（时间感知混合检索）
├── qdrant.py                      # delivery_knowledge collection 管理 + payload schema 常量
├── api/                           # （可选）管理/调试 REST views
└── urls.py

server/agents/tools/knowledge_tools.py        # chat @tool（search_delivery_knowledge 等）
server/workflows/nodes/ai/knowledge_retrieval.py  # workflow 节点（自动注册）
server/mcp_tools/views.py                     # 追加 McpToolView 子类（或拆 knowledge 专属 service 文件）
```

### Structure Rationale

- **app 内 service 而非 `server/services/`**：`mcp_tools/*_service.py`、`chat/coding_session_service.py` 已确立"领域 service 放 app 内"的先例；`server/services/` 留给跨域基础设施（embedding、qdrant、git_platform）。knowledge 是新领域，service 收口在 app 内，依赖方向单向（knowledge → services/*，其他 app → knowledge.ingestion 仅经一个公开函数）。
- **`sources/` normalizer 拆分**：6 个触发点 payload 形态差异大（NodeResult dict / Django model / webhook JSON），normalizer 各自独立可测，ingestion 核心只认统一 DTO——这是"多入口复用统一摄取服务"的关键结构。
- **`graph_store.py` 接口化**：已定决策"图访问收敛 GraphStore 接口，留换引擎逃生门"。Protocol + 单一 PG 实现，knowledge 内任何图遍历不得绕过。

## Architectural Patterns

### Pattern 1: 模型设计 — FK 与弱引用混用（双层引用原则）

**What:** KnowledgeEntity/KnowledgeEdge 对"组织维度"用 FK，对"跨域内容对象"用弱引用（kind + id 二元组）。

**仓库内已验证的两种先例：**
- FK 风格：`mcp_tools/models.py` 全部用 FK（`run`/`repository`/`project`，跨 app 可 FK）；
- 弱引用风格：`code_relations/models.py` `ChunkEdge.source_chunk_id/target_chunk_id` 显式不做 FK（"允许跨仓/chunk 未写入 ChunkRegistry 时柔性引用，孤儿引用由 reconcile 命令兜底"）。

**取舍建议（opinionated）：**

| 引用对象 | 方式 | 理由 |
|---------|------|------|
| `project` / `repository` | FK（`on_delete=CASCADE` 或 `SET_NULL`） | 组织维度稳定，需要按项目过滤索引；与 `McpWorkItemContext.project` 同款 |
| 源业务对象（CodingPlan / McpWorkItemTechnicalPlan / TaskResult / 飞书工作项…） | **弱引用** `source_kind: CharField(choices)` + `source_id: CharField` | ① 来源横跨 4 个 app（chat/mcp_tools/subagent/feishu），FK 会让 knowledge 反向耦合所有上游 app 的迁移与删除语义；② 飞书工作项根本没有本地模型 FK 可指（`feishu_project_key + work_item_type + work_item_id` 三元组）；③ 源对象删除不应级联抹掉知识历史（bi-temporal 的"历史可查"要求）。不用 GenericForeignKey——contenttypes 框架在本仓库零使用先例，且 GFK 无法表达飞书三元组 |
| KnowledgeEdge 两端 | FK → KnowledgeEntity（同 app 内，强一致没有代价） | 与 ChunkEdge 不同：知识实体一定先落库再建边，无"柔性引用"需求 |
| code_change → chunk | 弱引用 `target_chunk_id: UUIDField`（不 FK 到 ChunkRegistry） | 沿用 ChunkEdge 同一原则；chunk 重切分会换 id，孤儿边走 reconcile（见 Pattern 5） |

**字段草案（供 roadmapper 评估规模，非最终 contract）：**

```python
class KnowledgeEntity(models.Model):
    # kind: requirement / defect / technical_plan / code_change
    id = UUIDField(pk); kind = CharField(choices, db_index=True)
    project = FK("projects.Project", null=True); repository = FK("repositories.Repository", null=True)
    source_kind = CharField(choices)   # coding_plan / mcp_technical_plan / mcp_work_item / feishu_webhook / task_result ...
    source_id = CharField(max_length=200)  # UUID str 或 feishu 三元组拼接
    title = CharField; summary = TextField   # 检索展示用
    current_version = PositiveIntegerField(default=1)
    is_active = BooleanField(default=True)  # 源对象被删除/作废
    created_at / updated_at
    # 唯一约束 (kind, source_kind, source_id) —— 重摄取幂等 upsert 的锚点

class KnowledgeEntityVersion(models.Model):
    entity = FK(KnowledgeEntity, related_name="versions")
    version = PositiveIntegerField()
    content = TextField               # 该版本全文（embedding 输入）
    content_hash = CharField(64)      # sha256，内容未变跳过重摄取（CodingPlan.aget_or_create_for_conversation 同款手法）
    payload = JSONField               # 结构化原文快照
    qdrant_point_ids = JSONField(default=list)  # 该版本写入的向量点，下线时按 id 删
    is_latest = BooleanField(db_index=True)
    valid_at = DateTimeField          # 业务有效起点（bi-temporal: valid time）
    invalidated_at = DateTimeField(null=True)  # 被新版本替代的时刻
    created_at                         # 系统记录时间（bi-temporal: transaction time）
    # UniqueConstraint(entity, version)；部分索引 (entity) WHERE is_latest

class KnowledgeEdge(models.Model):
    # relation: PLANNED_BY / IMPLEMENTED_BY / SUPERSEDES / MODIFIES_CHUNK / RELATES_TO ...
    id = UUIDField(pk)
    source_entity = FK(KnowledgeEntity, related_name="out_edges")
    target_entity = FK(KnowledgeEntity, null=True, related_name="in_edges")
    target_chunk_id = UUIDField(null=True, db_index=True)  # MODIFIES_CHUNK 专用，弱引用 ChunkRegistry
    relation = CharField(choices); weight = FloatField(validators 0..1)
    metadata = JSONField(default=dict)
    valid_at = DateTimeField; invalidated_at = DateTimeField(null=True, db_index=True)  # bi-temporal 边
    created_at; expired_at = DateTimeField(null=True)      # transaction time 对
    # CheckConstraint: target_entity 与 target_chunk_id 二选一非空
    # UniqueConstraint(source_entity, target_entity, relation) WHERE invalidated_at IS NULL（活跃边唯一）
    # 索引：(source_entity, relation)、(target_entity)、(target_chunk_id) —— 对齐 ChunkEdge fanout/target 索引模式
```

**When to use:** bi-temporal 双时间对（valid_at/invalidated_at + created_at/expired_at）借鉴 Graphiti；检索默认 `invalidated_at IS NULL`，历史回溯按时间点过滤。
**Trade-offs:** 弱引用需要 reconcile 兜底（已有 `code_relations` reconcile 命令先例可仿）；版本表全文存储有冗余，但换来"旧版本向量精确下线 + 历史可查"，符合已定决策。

### Pattern 2: 统一摄取服务 + fire-and-forget 后台执行

**What:** 所有触发点只做一件事——组装最小上下文调用 `ingest_*` 公开函数；真正的 normalize/embed/写库/建边在 `background_runner` 的常驻 worker loop 中执行。

**Why 选 background_runner 而非 apscheduler（已验证两者实现）：**
- `services/background_runner.py`：进程级 daemon 线程 + 常驻 event loop，专为"脱离请求生命周期的耗时 coroutine"设计（indexer 已在用）。摄取含远程 embedding API 调用（`EmbeddingService` 走系统配置的 remote API），耗时百 ms～秒级，绝不能同步阻塞回调/webhook 响应。
- apscheduler（`agents/management/commands/runapscheduler.py`，BackgroundScheduler + DjangoJobStore）是周期 job 基础设施，跑在独立管理命令进程里，不适合事件驱动摄取；但适合加一个**低频补偿扫描 job**（如每小时扫 `updated_at > last_ingested_at` 的源对象）兜底 hook 漏触发——可作为后期增强，非首期必须。

**摄取必须幂等**：以 `(kind, source_kind, source_id)` upsert + `content_hash` 短路。理由：`_handle_completed` 自身已有幂等防御（TaskResult aexists 检查），重复回调/重试是既有事实。

**Example（hook 形态，以 callbacks 为例）：**

```python
# server/subagent/api/callbacks.py::_handle_completed 末尾追加（与
# _update_agent_session_cross_repo_relevance 同款"永不阻塞主流程"模式）
from services.background_runner import run_in_background
run_in_background(
    lambda: ingest_task_completion(session_id=session.session_id),
    name=f"knowledge-ingest-{session.session_id}",
)
```

**Trade-offs:** fire-and-forget 失败只留日志 → 需要 `last_error` 落在实体上或依赖补偿扫描；可接受，知识摄取非关键路径。

### Pattern 3: 检索 — 平行服务复用底层件，不扩展 HybridSearchService

**What:** 新建 `KnowledgeSearchService`，与 `services/retrieval/hybrid_search.py::HybridSearchService` 平行，不继承不修改。

**Why（实读 hybrid_search.py 后的结论）：** HybridSearchService 深度耦合代码 chunk 语义——wave 编排里 hop1 直读 Qdrant payload `related_chunks` + `ChunkRegistry.in_bulk`、hop2 走 `ChunkEdge` ORM、输出是 `## Graph Context` 代码邻居 markdown、预算按 rag/graph 60/40 切。知识检索的图扩散对象是 KnowledgeEdge、排序要叠加时间衰减、输出是"需求→方案→diff 轨迹"——共享的只有底层件而非编排。强行扩展会把两套实体模型搅进一个类（hybrid_search.py 已 660 行）。

**复用清单（全部直接 import，零修改）：**
- `services/embedding.py::EmbeddingService` — query/文档向量化
- `services/sparse_encoder.py` — sparse 向量（与 code_index hybrid 同款）
- `services/qdrant_service.py::QdrantService.hybrid_search_by_name / create_collection_by_name / batch_set_payload` — 已支持任意 collection 名 + dense/sparse RRF 融合 + 老 collection 降级
- `services/retrieval/token_budget.py::estimate_tokens / trim_to_budget` — 输出预算裁剪
- wave 编排手法（`asyncio.gather(return_exceptions=True)` + 差异化降级 + structlog wave 日志）作为代码模式参照

**检索编排（建议）：** wave0 = Qdrant `delivery_knowledge` hybrid 召回（filter: `is_latest=true` + project/kind）∥ 可选关键词过滤；wave1 = GraphStore 沿 KnowledgeEdge 1–2 跳扩散（活跃边 `invalidated_at IS NULL`）；打分 = 向量分 × 时间衰减因子（`exp(-λ·age)`，λ 可配）+ 过时标记（命中非 latest 版本时显式标注）；输出 = 轨迹化 markdown（需求 → 各版本方案 → code_change → 受影响 chunk）。

**衔接代码图谱：** 命中 code_change 实体后，沿 `MODIFIES_CHUNK` 边拿 chunk_id，可直接调 `HybridSearchService.find_related(chunk_id, ...)`（实读确认该方法不依赖 GraphCapableProvider 守卫，任何 provider 可用）做代码侧续扩——两套图在检索层桥接，存储层互不迁移。

### Pattern 4: diff 归档 — server 侧拉全量，容器回传仅作摘要

**What:** completed 后由 server 经 git platform API 拉全量 diff 归档；不依赖容器回传。

**实读证据：**
- 容器回传链路现状：`TaskResult.modified_files` 仅文件名列表（callbacks.py `_handle_completed`）；`CodingSession.diff_summary` 来自 `orchestration/coding_graph.py` 冲突预检节点的 compare 调用，**带 truncated 标记**（`test_diff_summary_view.py` 有 truncated=True 用例）；`McpCodingExecutionTrace.last_diff` 同源（`mcp_tools/execution_service.py:286` 取 `output.diff_summary`，`merge_request_service.py:119` 写 branch compare 结果）。三者都是摘要级，不可作全量归档源。
- server 侧拉取能力已具备：`services/git_platform/base.py::GitPlatformClient` 抽象已有 `get_merge_request_diff(...)` 与 `compare_branches(...)`，GitHub/GitLab 双实现；凭证按仓库加密存库（既有约束，不走 env）。

**归档流程：** `_handle_completed` hook → 后台任务读 `TaskResult.branch_name/commit_sha` + 关联 repository → `compare_branches(target_branch, branch_name)`（或 MR 已建则 `get_merge_request_diff`）→ 全量 per-file diff 落 `CodeChangeArchive`（PG 大文本，FK → code_change 实体的 version）→ per-file diff 文本向量化入 `delivery_knowledge` → 按 file_path 查 `ChunkRegistry`（已有 `idx_chunkreg_repo_branch_file` 复合索引，branch 维度可先落 base `""` 分支）建 `MODIFIES_CHUNK` 边。
**Trade-offs:** 巨型 diff 需上限保护（per-file 截断 + 文件数上限，参照 `payload_sync.py` 的 5KB 阶梯截断手法）；git platform API 失败需重试（仓库已有 `tenacity` 先例）。

### Pattern 5: 孤儿引用 reconcile

**What:** chunk 重切分/重索引后 chunk_id 变化，`MODIFIES_CHUNK` 边目标失效。沿用 `code_relations` 的 reconcile 管理命令模式：定期或手动按 `(repository, file_path)` 重解析 chunk_id、修复或标记失效边。首期可只标记（边 `invalidated_at`），不强制修复。

## Data Flow

### 摄取触发点清单（hook 埋点，全部为"修改既有文件"项）

| # | 触发事件 | 埋点位置（文件 :: 函数，已实读验证） | 摄取产物 | 执行方式 |
|---|---------|--------------------------------------|----------|---------|
| 1 | workflow 技术方案生成 | `server/workflows/nodes/ai/plan_generation.py`（AIPlanGenerationNode 产出经 `validate_technical_plan` 的方案 JSON 后） | technical_plan 实体（草稿态）+ 与 requirement 边 | hook 同步入队，后台执行 |
| 2 | workflow 方案审批通过 | `server/workflows/nodes/ai/plan_approval.py::PlanApprovalNode`（`approved` 输出 port 路径） | 方案实体状态确认/版本固化 | 同上 |
| 3 | 编码任务完成回传 | `server/subagent/api/callbacks.py::_handle_completed`（TaskResult 创建 + `amark_completed` 之后；该函数已有 repo_summary / cross_repo_relevance 两个同位 hook 先例） | code_change 实体 + diff 归档（Pattern 4 全流程）+ IMPLEMENTED_BY 边 | 同上（**必须**后台，含 git API + embedding） |
| 4 | MCP 技术方案落库 | `server/mcp_tools/technical_plan_service.py`（`McpWorkItemTechnicalPlan.objects.acreate`，~L491；更新路径含 retry_state 续跑） | technical_plan 实体 + requirement（来自关联 `McpWorkItemContext`）+ 边 | 同上 |
| 5 | chat 方案创建/更新 | 收敛到模型层：`server/chat/models.py::CodingPlan.aget_or_create_for_conversation`（created=True 分支）与 `CodingPlan.aupdate_plan` —— 比在 `agents/tools/coding_tools.py` 的 `create_coding_plan`/`update_coding_plan` @tool 埋点更优：模型方法是所有写路径（@tool、未来 API）的必经收口 | technical_plan 实体；update → 新版本 + 旧版失效 | 同上 |
| 6 | 飞书工作项创建/更新 | `server/feishu/views.py`（事件分发 ~L656–665：`WorkitemCreateEvent` → 创建 requirement 实体；`WorkitemUpdateEvent` → `_handle_workitem_update` 处追加重摄取） | requirement/defect 实体 + 版本翻转 | 同上 |

**同步 vs 后台裁决：** 6 处一律 hook 内同步组装 ID 级最小参数 → `run_in_background` 异步执行。理由：①回调/webhook 都有响应时延约束（飞书 webhook 有重试机制，慢响应会放大重复事件）；②embedding 为远程 API；③`background_runner` 正是为此场景建的基础设施（indexer 同款）。apscheduler 仅作可选补偿扫描。

**版本化重摄取流（触发点 4/5/6 的 update 分支）：**

```
源对象更新 → ingest(source_kind, source_id, new_content)
  → content_hash 相同？ → 跳过（no-op）
  → 不同：entity.current_version += 1
       ├─ 旧 version: is_latest=False, invalidated_at=now
       │    └─ 按 qdrant_point_ids 删除/降级旧向量（旧版本向量下线）
       ├─ 新 version 落库 + embed → upsert 新向量（payload.is_latest=true）
       └─ 受影响的 KnowledgeEdge: invalidated_at=now，重建新边（SUPERSEDES 链）
```

### Qdrant collection 设计

**裁决：单一 `delivery_knowledge` collection，payload filter 隔离，不按 project 分片。**

理由（对照现状）：代码轨 `code_index_{repo_id}` per-repo 分片（`QdrantService.get_collection_name`）是因为 chunk 体量大（单仓十万级）且生命周期随仓库整体删除；知识实体量级低 2–3 个数量级（每需求个位数实体 + 十数 diff 块），且核心场景"召回相似历史需求"天然要跨项目查——分片反而要 fan-out 多 collection 查询。Qdrant payload index + filter 足够（既有 `create_branch_payload_index` 先例证明 payload 索引是项目惯用法）。仓库删除时按 `repository_id` filter 批量删点即可。

**创建方式：** 复用 `QdrantService.create_collection_by_name("delivery_knowledge", vector_size, hybrid=True)` —— named vectors `dense` + `sparse`，RRF 融合检索走 `hybrid_search_by_name`，零新基础设施。`vector_size` 从 `SystemSetting(EMBEDDING_DIMENSION)` 读（indexer 同款，当前部署 2560）。

**Payload schema：**

| 字段 | 类型 | 用途 |
|------|------|------|
| `entity_id` / `version_id` | str(UUID) | 回查 PG；版本下线按 version 删点 |
| `entity_kind` | str | requirement / defect / technical_plan / code_change（filter + payload index） |
| `project_id` / `repository_id` | str | 范围过滤（payload index） |
| `source_kind` / `source_id` | str | 溯源 |
| `version` / `is_latest` | int / bool | **检索默认 filter `is_latest=true`**（payload index） |
| `valid_at` | ISO str | 时间衰减计算输入 |
| `chunk_kind` | str | 整体摘要 / diff-file 块（code_change 一实体多点） |
| `file_path` | str | diff 块定位 + 与 ChunkRegistry 解析 |
| `text` | str | 命中展示摘要（截断，参照 5KB 纪律） |
| `embedding_model` | str | 换模型/维度重建时识别旧点 |

### Key Data Flows

1. **摄取流：** 业务事件（6 触发点）→ hook 最小参数入队 → background worker：normalizer → 实体/版本 upsert（PG）→ embed（EmbeddingService + SparseEncoder）→ upsert 向量（Qdrant delivery_knowledge）→ 建边（GraphStore）。
2. **diff 归档流：** `_handle_completed` → GitPlatformClient `compare_branches`/`get_merge_request_diff` → CodeChangeArchive（PG）→ per-file 向量化 → `MODIFIES_CHUNK` 边（弱引用 chunk_id，经 ChunkRegistry `(repository, branch_name, file_path)` 解析）。
3. **检索流：** 任意入口（MCP/chat/workflow/skill→MCP）→ KnowledgeSearchService → Qdrant 召回（is_latest filter）∥ GraphStore 1–2 跳扩散 → 时间衰减重排 + 过时标记 → 轨迹 markdown / 结构化 JSON；可选经 `MODIFIES_CHUNK` → `HybridSearchService.find_related` 续扩代码邻居。

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 当前（单实例自托管，需求量 <10⁴/项目） | 上述设计直接成立：PG 递归 CTE（基准 22.5K RPS @1–3 跳）、单 collection、background_runner 单 worker loop 均无瓶颈 |
| 需求量 10⁵+ 或多年累积 | KnowledgeEdge 活跃边部分索引（`WHERE invalidated_at IS NULL`）是关键；版本全文表可按年归档分区 |
| 团队级并发摄取 | background_runner 是进程级单 loop——若摄取排队成为问题，迁到 apscheduler job 队列或独立 worker；接口（ingest 公开函数）不变 |

### Scaling Priorities

1. **第一瓶颈：** 远程 embedding API 延迟/限流（摄取串行化）→ 批量 embed + 失败重试（tenacity），不阻塞业务路径所以体感钝化。
2. **第二瓶颈：** diff 归档体量（巨型 MR）→ per-file 上限 + 文件数上限 + 仅向量化文本 diff（二进制跳过）。

## Anti-Patterns

### Anti-Pattern 1: 复用/改造 ChunkEdge 承载知识边

**What people do:** 看到 ChunkEdge 已有 8 类边 + weight + metadata，想加 `REQUIREMENT_OF` 之类边型塞进去。
**Why it's wrong:** ChunkEdge 两端语义是 chunk_id（UUID 弱引用 ChunkRegistry），知识实体不是 chunk；branch_name 唯一约束、payload_sync 的 `related_chunks` 聚合、hop2_expander 都会把知识边当代码邻居漏进代码检索上下文。已定决策也明确"现有 ChunkEdge 不迁移"。
**Do this instead:** KnowledgeEdge 独立表；与 chunk 的交点只有 `MODIFIES_CHUNK.target_chunk_id` 单向弱引用。

### Anti-Pattern 2: hook 内同步做 embedding / git API 调用

**What people do:** 在 `_handle_completed` / webhook handler 里直接 await embed + Qdrant 写入。
**Why it's wrong:** 回调响应被拖慢；更致命的是 ASGI 请求结束后 `CurrentThreadExecutor` 关闭，遗留 `sync_to_async` 调用直接抛 `RuntimeError`（`background_runner.py` 模块 docstring 记载的真实事故模式）。
**Do this instead:** hook 只传 ID，`run_in_background(coro_factory, name=...)`；任何异常 `logger.warning` 不上抛（对齐 `_update_agent_session_cross_repo_relevance` 的"永不阻塞主流程"纪律）。

### Anti-Pattern 3: 在各触发点各写一套摄取逻辑

**What people do:** workflow 节点里写一份"方案入库 + embed"，MCP service 里再写一份。
**Why it's wrong:** 版本翻转/向量下线/幂等逻辑有状态机性质，多份实现必然漂移（检索命中旧版本=里程碑核心目标失败）。
**Do this instead:** 全部入口经 `knowledge/ingestion.py` 的少数公开函数；触发点差异收敛在 `sources/` normalizer。

### Anti-Pattern 4: 直接 import 改 HybridSearchService 编排

**What people do:** 给 `HybridSearchService.search` 加 `include_knowledge=True` 参数。
**Why it's wrong:** 该类是代码检索 contract（chat/MCP/workflow 多 callsite + byte-equal 守门测试），混入知识检索会破坏既有 zero-drift 承诺与 token 预算语义。
**Do this instead:** 平行 `KnowledgeSearchService`；需要联合检索时在更高层（tool/节点）各调一次再拼装。

### Anti-Pattern 5: LLM 自由文本实体抽取

已定决策排除。实体/关系全部来自结构化业务对象的稳定 ID（工作项三元组、CodingPlan UUID、TaskResult 等），摄取确定性、可幂等。

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Qdrant | `QdrantService.create_collection_by_name` / `upsert_vectors_by_name` / `hybrid_search_by_name`（全部既有 classmethod） | sync SDK，沿用 indexer 的 `@sync_to_async` 包装纪律；timeout 已调优勿动 |
| Embedding 远程 API | `services/embedding.py::EmbeddingService`（系统配置，不绑定模型） | payload 记 `embedding_model`，换模型需 collection 重建预案 |
| GitHub/GitLab | `services/git_platform/base.py::GitPlatformClient.get_merge_request_diff / compare_branches` | 凭证按仓库加密存库；通用 Git（无平台 API）仓库降级为本地 `git diff`（GitPython 已在依赖中）或仅存容器摘要 |
| 飞书 | `server/feishu/views.py` 事件分发（webhook/长连接均过同一分发） | 摄取 hook 放事件分发处，不动签名校验/TriggerLog |

### Internal Boundaries（新 ↔ 旧，含依赖方向）

| Boundary | Communication | 方向与约束 |
|----------|---------------|-----------|
| 6 触发点 → knowledge | 各文件 import `knowledge.ingestion` 单一公开入口，lazy import 防循环（callbacks.py 内 lazy import 是既有惯例） | 上游 app → knowledge 单向；knowledge 不 import chat/mcp_tools 的 service（只在 normalizer 内 lazy 读其 model） |
| knowledge → code_relations | 仅两点：读 `ChunkRegistry`（解析 file_path→chunk_id）+ 检索层调 `HybridSearchService.find_related` | knowledge 不写 chunk_* 表 |
| knowledge → services/* | EmbeddingService / SparseEncoder / QdrantService / background_runner / git_platform | 纯消费，零修改 |
| MCP 入口 | `mcp_tools/views.py` 新增 `McpToolView` 子类（PAT/JWT 双认证 + `begin_interaction_run` 审计已由基类承担） | 修改 `mcp_tools/urls.py` 注册路由 |
| chat 入口 | `agents/tools/knowledge_tools.py` 新增 `@tool`（registry 自动发现 + langchain_adapter 自动适配） | 纯新增文件 |
| workflow 入口 | `workflows/nodes/ai/knowledge_retrieval.py` 放 `BaseNode` 子类 + `web/.../node-definitions.json` 补 UI schema | NodeRegistry 包扫描自动注册 |
| npm skill 入口 | `mcp/` 包（dist/cli.js）扩充 skill 文档，指导外部 agent 调新 MCP tool | 不新增服务端面 |

## 建议构建顺序（供 roadmapper 划 phase）

依赖驱动，每步可独立验证：

1. **数据模型 + GraphStore**（`knowledge` app、4 张表 + migrations、GraphStore Protocol + PG 实现、Qdrant collection 管理）。一切的地基；可单测（含递归 CTE 遍历）。
2. **统一摄取服务（首批 2 触发点）**：ingestion 核心（幂等 upsert + 版本翻转 + 向量写入）+ `sources/coding_plan.py` + `sources/mcp_technical_plan.py`，hook 进 `CodingPlan` 模型方法与 `technical_plan_service.py`。版本化机制在此一并落地（它是摄取的内建语义，不是后置功能）。
3. **其余触发点 + diff 归档**：callbacks/_handle_completed hook、plan_generation/plan_approval hook、feishu webhook hook；DiffArchiver（git platform 拉全量 diff + CodeChangeArchive + MODIFIES_CHUNK 边）。依赖 2 的 ingestion 核心。
4. **时间感知混合检索**：KnowledgeSearchService（向量召回 + 图扩散 + 时间衰减/过时标记 + 轨迹渲染）。依赖 1–3 有数据可检。
5. **多入口暴露**：MCP tool + chat @tool + workflow 节点 + npm skill 文档。薄层，依赖 4；四入口可并行做。
6. **（可选收尾）** apscheduler 补偿扫描 job + MODIFIES_CHUNK reconcile 命令。

**Phase 研究标记建议：** 4（时间衰减参数与重排策略需要小范围调研/实验）；其余均为本仓库既有模式的拼装，标准实现即可。

## Sources

- 本仓库实读（HIGH）：`server/code_relations/models.py`、`server/code_relations/payload_sync.py`、`server/services/retrieval/hybrid_search.py`、`server/services/retrieval/rag_search.py`、`server/services/qdrant_service.py`、`server/services/indexer.py`、`server/services/embedding.py`、`server/services/background_runner.py`、`server/services/git_platform/base.py`、`server/subagent/api/callbacks.py`、`server/mcp_tools/models.py`、`server/mcp_tools/technical_plan_service.py`、`server/mcp_tools/execution_service.py`、`server/mcp_tools/merge_request_service.py`、`server/mcp_tools/views.py`、`server/chat/models.py`（CodingPlan/CodingSession）、`server/agents/tools/coding_tools.py`、`server/workflows/nodes/ai/plan_generation.py`、`server/workflows/nodes/ai/plan_approval.py`、`server/feishu/views.py`、`server/orchestration/coding_graph.py`、`server/agents/management/commands/runapscheduler.py`
- `.planning/PROJECT.md` v0.3.0 已定决策（Postgres+Qdrant 双栈 / GraphStore 接口 / 不做 LLM 抽取 / 借鉴 Graphiti bi-temporal / PG 递归 CTE 基准结论）（HIGH，项目权威输入）
- Graphiti bi-temporal 边模型（valid time + transaction time 双时间对）— 设计借鉴，已由项目前期选型调研确认（MEDIUM，未在本轮重新核对上游文档）

---
*Architecture research for: Friday AI v0.3.0 交付知识图谱（brownfield 集成）*
*Researched: 2026-06-11*
