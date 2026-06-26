# Phase 85: 项目上下文可读 + 分支绑定 - Research

**Researched:** 2026-06-27
**Domain:** 后端检索/知识图谱物化（Django 5.1 adrf async + Qdrant/delivery_knowledge + Interaction Ledger）+ 分支↔项目绑定模型
**Confidence:** HIGH（全部基于 live `server/` 代码核实；唯一 MEDIUM 项为"独立 collection"决策的物理实现口径，见 Assumptions Log A1）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions（必须遵守，不可重议）

**上下文物化存储**
- 项目 5 文件/记忆/工件物化进**独立「项目上下文」collection**（与**代码 RAG collection** 分离），scope/visibility 隔离（随项目 visibility 决定可召回范围）。
- 不复用代码 RAG collection 作虚拟仓库（避免与排除规则/仓库权限口径串味）。

**物化/索引触发**
- **写时增量物化 + 兜底定时全量重建**：5 文件/记忆变更时增量更新向量；定时（或归档/手动）全量重建兜底防漂移。
- 写时增量经 durable 任务，带 `initiated_by_user_id`；失败 fail-soft 不阻断业务。

**知识图谱沉淀（CTX-02）**
- 项目（5 文件/记忆/工件）沉淀进交付知识图谱（复用 `KnowledgeEntity`/`KnowledgeEdge`），可索引 + 关联扩充。
- 全局+RAG 搜索能定位上下文所属仓库/项目。
- 新增召回写 `RetrievalTrace` + 条数/分层耗时/score（MCP + AI 对话两条链都覆盖）。

**分支绑定（BIND-01/02）**
- 新增 `ProjectBranch`（project FK + repository FK + branch_name + source(manual/plan/coding) + 时间戳，唯一 (project,repository,branch_name)）——一项目多分支、前端可绑。
- 分支↔看板结合。
- 扩展 `lookup_project_by_branch` 支持显式多绑定，多/无命中 fail-soft 返回候选列表，不抛、不阻断编码。

### Claude's Discretion（可自行决策并给建议）
- 独立 collection 的物理实现口径（新建物理 collection vs 复用 `delivery_knowledge` 作为"项目上下文专属、非代码 RAG"collection）——**见 A1，本研究给出强烈倾向**。
- 新 EntityKind/source_kind 命名；grep/file-read 端点的具体形态（MCP 工具粒度）。
- ProjectBranch 写入收口 service 的归属（initiatives）。

### Deferred Ideas（OUT OF SCOPE）
- 结构化记忆 + 时效降权 + 矛盾消解（PROJX-02，v2）。
- UI 稿多模态 / figma 正文召回（PROJX-01）。
- 记忆全自动写入无需人工确认（PROJX-03）。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CTX-01 | 项目上下文物化为可 RAG + 可 grep + 可 file-read，任意来源（前端 AI 对话 / MCP / skills）均可读取项目全部信息 | RAG 走 `delivery_knowledge` + `DeliveryKnowledgeSearchService`（已被 packer/project_search 复用）；grep 走 `ProjectSearchService` SQL `icontains` 关键词链（已落地，扩 ProjectDoc 内容）；file-read 走 `DocContentService.get_doc_render`（已落地，含 block 分区）；MCP 三家来源需新增/扩 MCP 工具暴露 |
| CTX-02 | 项目沉淀进交付知识图谱可索引 + 关联扩充；全局+RAG 定位所属仓库/项目；新增召回写 RetrievalTrace（MCP+对话两链） | 复用 `knowledge.ingestion.aschedule_ingestion` + 新 normalizer（镜像 `sources/artifact.py`）；`KnowledgeEntity` 已带 `space`(项目)/`repository` FK + `ProjectKnowledgeGraphService` 项目节点 + REFERENCES 边；locator 已在 `ProjectSearchService` 返回；`arecord_retrieval_trace`(run 可空) 覆盖两链 |
| BIND-01 | ProjectBranch 多绑定模型 + 分支↔看板结合 | initiatives 迁移 0008（紧跟 0007）；Repository/Project 均 UUID PK；看板引用已在 `Project.feishu_board_id`/`feishu_project_key`；写收口 service（INV-6）+ 前端绑定 REST |
| BIND-02 | 扩展 `lookup_project_by_branch` 显式多绑定，多/无命中 fail-soft 返回候选 | `LookupProjectByBranchView` 已有 candidates/fail-soft 契约；当前仅按 `parse_work_item_id_from_branch`→`ProjectWorkItemLink` 反查，需叠加 `ProjectBranch` 显式绑定查询 |
</phase_requirements>

## Summary

本期是 Wave 2 上下文闭环的"读 + 绑"地基，**几乎全部是组合既有地基、极少净新**。三套核心基础设施都已就绪：(1) 交付知识图谱 `delivery_knowledge`（独立于 per-repo 代码 RAG 的 Qdrant collection）+ `aschedule_ingestion` 摄取管线 + normalizer 注册表；(2) 召回收口 `DeliveryKnowledgeSearchService`（已 visibility 感知，`access_scope` 已把 `public_org` 项目并入可读集）+ `project_context_packer`（grep+RAG+token 预算+RetrievalTrace 全有）+ Phase 84 `ProjectSearchService`（关键词 grep + 知识兜底 + locator）+ `DocContentService`（5 文件 file-read）；(3) MCP `LookupProjectByBranchView`（已有 candidates + fail-soft 契约）+ `branch_parsing`。

**关键判断（A1）**：locked decision 说"独立项目上下文 collection（与代码 RAG collection 分离）"。代码侧"代码 RAG collection"= per-repo `code_index_{repository_id}`（`QdrantService.get_collection_name`）；`delivery_knowledge` 本就是与之物理分离的专属知识 collection，且 CTX-02 明确要求复用 `KnowledgeEntity`/`KnowledgeEdge`（即写入 `delivery_knowledge`）。若 CTX-01 另起第三个物理 collection，会与 CTX-02 形成**双重向量化**（同一份 5 文件/记忆既进 `delivery_knowledge` 又进新 collection），既无收益又翻倍成本。**强烈建议把 `delivery_knowledge` 当作"项目上下文专属 collection"**——它满足"与代码 RAG 分离"、visibility 隔离（`access_scope`）、可索引可关联（图谱）全部约束；用**新 source_kind（`project_doc`/`project_memory`，artifact 已存在）+ 复用 `EntityKind.DOCUMENT`** 做逻辑隔离。该口径需在 plan/discuss 与用户确认（A1）。

**Primary recommendation:** 以 `delivery_knowledge` 为项目上下文 collection，新增 `knowledge/sources/project_doc.py` + `project_memory.py` normalizer（镜像 `artifact.py`），在 `MemoryService` / `ProjectDocService` / `DocSyncService.pull` 写后挂 `aschedule_ingestion` 写时增量钩子（durable on_commit + background_runner，带 `initiated_by_user_id`，fail-soft）；新增 management command + apscheduler job 做兜底全量重建。grep/file-read 经扩 `ProjectSearchService` + `DocContentService` 并以新 MCP 工具暴露。BIND 加 `ProjectBranch` 模型（迁移 0008）+ 写收口 service + 前端绑定 REST，并在 `LookupProjectByBranchView` 叠加显式绑定查询（保持现有 fail-soft/candidates 契约）。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 项目上下文向量物化（RAG 入库） | API/Service 层（`knowledge.ingestion` + 新 normalizer） | DB/Storage（Qdrant `delivery_knowledge` + PG `KnowledgeEntityVersion`） | 摄取是后台 durable 任务，向量库与 PG 版本链是存储 |
| 写时增量触发 | Service 层钩子（`MemoryService`/`ProjectDocService`/`DocSyncService`） | 后台（`background_runner` / durable in-process） | 业务写收口处挂 `aschedule_ingestion`，best-effort 不反噬 |
| 兜底定时全量重建 | scheduler（apscheduler job）+ management command | API/Service（ingestion.revectorize） | 镜像 `rebuild_delivery_knowledge` / `poll_*` 范式 |
| 召回（RAG/grep/file-read） | API/Service（`DeliveryKnowledgeSearchService`/`ProjectSearchService`/`DocContentService`） | DB/Storage（Qdrant + PG）+ Interaction Ledger（RetrievalTrace） | 召回收口已存在，scope 过滤在 service 层（P6） |
| 多来源暴露（前端/MCP/skills） | API 层（REST + MCP `McpToolView`） | Service（packer/search/doc_content） | 前端走 REST/chat，MCP/skills 走 MCP 工具 |
| 分支↔项目绑定 | DB/Model（`ProjectBranch`）+ Service（写收口 INV-6） | API（前端 bind REST + MCP lookup） | 模型为真相源，写收口单一 service |
| 分支名反查 | API（MCP `LookupProjectByBranchView`） | Service（`branch_parsing` + ProjectBranch 查询） | 读路径，fail-soft 候选列表 |

## Standard Stack

> 本期**不引入任何新外部依赖**——全部复用既有栈。下表是"必须使用的既有模块"，非新装包。

### Core（既有模块，必须复用）
| 模块 | 路径 | 用途 | 为什么是标准 |
|------|------|------|------|
| 摄取管线 | `server/knowledge/ingestion.py` (`aschedule_ingestion`/`IngestionRequest`/`IngestionEvent`/`EdgeSpec`) | 写时增量物化唯一入口（on_commit + 后台 + 六步版本翻转 + 幂等 + 边） | 全仓唯一摄取收口，幂等可重入，已被 5 个 source 复用 |
| normalizer 注册表 | `server/knowledge/sources/__init__.py` (`get_normalizer`) + `sources/artifact.py`（范式样板） | 新增 `project_doc`/`project_memory` 投影 | 惰性注册解耦，新触发点只登记 + 加模块 |
| collection 生命周期 | `server/knowledge/collection.py` (`ensure_delivery_knowledge_collection`/`DELIVERY_KNOWLEDGE_COLLECTION`) | 项目上下文 collection（建议复用 delivery_knowledge，见 A1） | hybrid dense+sparse + payload index + 配置不匹配响亮拒绝 |
| 召回收口 | `server/knowledge/retrieval.py` (`DeliveryKnowledgeSearchService.search_similar`) | RAG 召回（visibility 感知） | Phase 15 唯一检索 service，已被 packer/project_search/MCP 四入口复用 |
| scope 过滤 | `server/knowledge/access_scope.py` (`resolve_allowed_project_ids`) | visibility 隔离（已并入 `public_org`） | fail-closed + public_org 读放宽，CTX-02"随 visibility 决定召回范围"已就绪 |
| 上下文打包器 | `server/services/project_context_packer.py` (`pack_project_context`) | grep(SQL)+RAG+图谱+token 预算降级 + RetrievalTrace（AI 对话链） | RECALL-01/03 已落地，含 visibility 读半逻辑 |
| 项目搜索 | `server/initiatives/services/project_search_service.py` (`ProjectSearchService`) | grep 关键词链 + 知识兜底 + `locator`（属哪个 repo/project）+ RetrievalTrace | WB-05 已落地，CTX-02 locate 半成品 |
| 文件读取 | `server/initiatives/services/doc_content_service.py` (`DocContentService.get_doc_render`) | file-read：单文档渲染 markdown + block 分区 | WB-03 已落地，读 `last_synced_snapshot` + 渲染缓存 |
| 知识图谱投影 | `server/initiatives/services/knowledge_graph.py` (`ProjectKnowledgeGraphService`) | 项目/仓库/空间参考节点 + KLINK 边（REFERENCES/RELATES_TO） | KLINK-01/02 已落地，新 normalizer 复用 `ensure_project_node` 做 REFERENCES 边目标 |
| MCP 基类 | `server/mcp_tools/views.py` (`McpToolView` + `LookupProjectByBranchView`) | MCP 工具入口（run/tool-call/RetrievalTrace helper） | token 认证 + `_record` 自动写 RetrievalTrace/RequestMetric |
| Ledger 写入 | `server/interactions/ledger.py` (`arecord_retrieval_trace`，run 可空) | RetrievalTrace（MCP + 对话两链） | best-effort + `redact_for_ledger`，user/source 从 contextvars 取 |
| 后台任务 | `server/services/background_runner.py` (`run_in_background(..., initiated_by_user_id=)`) | 写时增量 fail-soft 后台执行 + 归因 re-bind | durable in-process fallback；worker 入口 `bind_task_context` |
| 分支解析 | `server/services/branch_parsing.py` (`parse_work_item_id_from_branch`) | 分支名→work_item_id（fail-soft 纯函数） | BIND-02 反查的现有半边 |

### Supporting（按需复用）
| 模块 | 路径 | 用途 |
|------|------|------|
| 全量重建命令范式 | `server/knowledge/management/commands/rebuild_delivery_knowledge.py` | 兜底全量重建 management command 样板（删建 + 从 PG latest 重嵌入） |
| 调度范式 | `server/agents/management/commands/runapscheduler.py` (`poll_project_docs_revisions_job` / `_with_scheduler_log_context`) | 兜底定时任务注册样板（CronTrigger + `run_async_task` + system 归因） |
| debounce 推送范式 | `server/initiatives/services/doc_push_scheduler.py` (`schedule_doc_push`) | 写后 fail-soft 调度的现成范式（材料化钩子可参照其 fail-soft 写法） |
| 嵌入/稀疏 | `server/services/embedding.py` / `sparse_encoder.py` | normalizer 不直接调（摄取内部已用），仅了解 `call_source=embedding` 既有 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 复用 `delivery_knowledge` 作项目上下文 collection（推荐） | 新建第三个物理 Qdrant collection `project_context` | 新建 = 与 CTX-02 双重向量化 + 新建 collection 生命周期/召回/scope 全套重写；收益仅"物理隔离"而 visibility 隔离 `delivery_knowledge` 已具备。**不推荐**，但需用户确认（A1） |
| 新 source_kind + 复用 `EntityKind.DOCUMENT`（推荐） | 新增 `EntityKind.PROJECT_DOC` / `PROJECT_MEMORY` 枚举值 | 新 EntityKind 进 `generate_entity_id` uuid5 派生空间 + check 约束，是锁定契约扩展；DOCUMENT + source_kind 已足够区分（`source_kind` 已是过滤维度）。新 kind 仅在确需按 kind 过滤召回时才值得 |
| 写时增量经 `background_runner` in-process（推荐，沿用 ingestion 现状） | 走 Procrastinate durable 队列 | ingestion 现状即 `on_commit`→`run_in_background`（见 `aschedule_ingestion`）；项目上下文量级低，沿用零回归。durable 仅在需跨重启持久化时才必要 |

**Installation:** 无新依赖。

**Version verification:** N/A（不新增包）。所有引用模块经 live `server/` 代码核实存在。

## Architecture Patterns

### System Architecture Diagram

```text
                ┌─────────────────────── 写路径（CTX-01/02 物化）────────────────────────┐
                │                                                                          │
  [前端/飞书/会话] 写 5 文件/记忆/工件                                                      │
        │                                                                                  │
        ▼                                                                                  │
  MemoryService.append/edit/supersede/confirm_draft  ──┐                                   │
  ProjectDocService.write_human_block / state_api      ─┤  写后挂材料化钩子                 │
  DocSyncService.pull（飞书→Friday 正文回写）          ─┘  (best-effort, fail-soft)         │
        │                                                                                  │
        ▼  aschedule_ingestion(IngestionRequest(source_kind="project_doc"/"project_memory"))│
  transaction.on_commit → run_in_background(initiated_by_user_id=…)                         │
        │                                                                                  │
        ▼  get_normalizer → sources/project_doc.py / project_memory.py（镜像 artifact.py）  │
  ingest_events → 六步版本翻转 → KnowledgeEntity(DOCUMENT) + REFERENCES→项目节点边           │
        │                          + 向量 upsert 进 delivery_knowledge (A1)                 │
        ▼                                                                                  │
  delivery_knowledge (Qdrant, 独立于 code_index_{repo})  +  KnowledgeEntity/Edge (PG)       │
        ▲                                                                                  │
        │  兜底：apscheduler job → management command（从 PG project source 全量重嵌入）     │
        └──────────────────────────────────────────────────────────────────────────────────┘

                ┌─────────────────────── 读路径（CTX-01 任意来源）─────────────────────────┐
  [前端 AI 对话] ──► pack_project_context (RAG+grep+图谱) ──► RetrievalTrace(对话链, 已有)   │
  [MCP/skills]   ──► 新/扩 MCP 工具:                                                         │
                     - search_project_context (RAG)  ─► DeliveryKnowledgeSearchService       │
                     - grep_project (SQL icontains)  ─► ProjectSearchService 关键词链         │
                     - read_project_doc (file-read)  ─► DocContentService.get_doc_render       │
                     全部经 McpToolView._record → RetrievalTrace(MCP 链)                       │
                     scope: access_scope(visibility) fail-closed / public_org 放行             │
                └──────────────────────────────────────────────────────────────────────────┘

                ┌─────────────────────── 分支绑定（BIND-01/02）────────────────────────────┐
  前端绑定 REST / plan·coding 流水线(Phase 89) ─► ProjectBranchService（写收口 INV-6）        │
                                                  ─► ProjectBranch(project,repository,branch)  │
  [IDE hook / Phase 86] ─► MCP lookup_project_by_branch                                        │
        │  ① parse_work_item_id_from_branch → ProjectWorkItemLink → Project（既有）            │
        │  ② ProjectBranch.filter(branch_name[, repository]) → Project（本期新增显式绑定）     │
        ▼  合并去重 → 单命中: pack_project_context 召回 ; 多/无命中: candidates 列表(fail-soft)│
                └──────────────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure（净新增/改动落点）
```
server/
├── knowledge/sources/
│   ├── project_doc.py        # 净新：5 文件正文 → DOCUMENT 投影 + REFERENCES→项目节点
│   └── project_memory.py     # 净新：active 记忆 → DOCUMENT 投影 + REFERENCES→项目节点
├── knowledge/sources/__init__.py   # 改：注册 project_doc / project_memory
├── knowledge/management/commands/
│   └── rebuild_project_context.py  # 净新：兜底全量重建（镜像 rebuild_delivery_knowledge）
├── initiatives/
│   ├── models/project_branch.py    # 净新：ProjectBranch 模型
│   ├── models/__init__.py          # 改：导出 ProjectBranch + BranchSource
│   ├── migrations/0008_project_branch.py  # 净新：CreateModel（紧跟 0007）
│   ├── services/project_branch_service.py # 净新：写收口（INV-6）+ 审计 + 归因
│   ├── services/memory_service.py         # 改：append/edit/supersede/confirm 写后挂 ingestion 钩子
│   ├── services/project_doc_service.py    # 改：write_human_block / state_api 写后挂钩子
│   └── services/doc_sync_service.py       # 改：pull 回写正文后挂钩子
├── mcp_tools/
│   ├── views.py             # 改：LookupProjectByBranchView 叠加 ProjectBranch 查询 +（可选）新增 grep/file-read/search 工具
│   ├── serializers.py       # 改：新工具请求/响应序列化
│   └── urls.py              # 改：注册新工具路由
└── agents/management/commands/runapscheduler.py  # 改：注册 rebuild_project_context 定时 job
```

### Pattern 1: 写时增量材料化钩子（fail-soft）
**What:** 在业务写收口 service 方法尾部挂 `aschedule_ingestion`，与既有 `schedule_doc_push` 并列。
**When to use:** MemoryService / ProjectDocService / DocSyncService 任何改变项目可召回内容的写。
**Example:**
```python
# Source: 镜像 server/knowledge/ingestion.py::aschedule_ingestion + sources/artifact.py
# 在 MemoryService.append 尾部（与既有 _schedule_doc_push 并列）：
from knowledge.ingestion import aschedule_ingestion, IngestionRequest
try:
    await aschedule_ingestion(
        IngestionRequest(
            source_kind="project_memory",
            source_id=str(memory.id),
            trigger="project_memory_created",
        )
    )
except Exception:  # noqa: BLE001 — 材料化 best-effort，绝不反噬记忆写主流程
    pass
# aschedule_ingestion 内部已 on_commit + run_in_background + 吞异常；
# 此处外层 try 仅为双保险（与既有 best-effort 纪律一致）。
```
**关键**：`aschedule_ingestion` 已自带 `transaction.on_commit` + 异常全吞，但它**不带 `initiated_by_user_id`**（当前签名只接 `IngestionRequest`）。CTX-02 要求后台任务带发起用户——**研究发现**：需扩 `aschedule_ingestion`/`run_in_background` 调用透传 `initiated_by_user_id`，或在 normalizer 投递前 `bind_task_context`。`run_in_background` 已支持 `initiated_by_user_id=` 参数（best-effort re-bind），但 `aschedule_ingestion` 内部硬编码 `run_in_background(lambda: ingest(request), name=...)` 未透传——**plan 须改 `aschedule_ingestion` 签名增加可选 `initiated_by_user_id` 并透传**（见 Pitfall 1）。

### Pattern 2: normalizer 投影（镜像 artifact.py）
**What:** `async def normalize(request) -> list[IngestionEvent]`，产 `KnowledgeEntity(DOCUMENT)` + `EdgeSpec(REFERENCES → 项目节点)`。
**When to use:** project_doc / project_memory 两个新 source。
**Example:**
```python
# Source: server/knowledge/sources/artifact.py（逐行可参照）
event = IngestionEvent(
    kind=EntityKind.DOCUMENT,                 # 复用 DOCUMENT，不新增 EntityKind（A1/备选）
    origin=EntityOrigin.PROJECT,              # 已有枚举值
    source_kind="project_memory",             # 新 source_kind（natural key 规则表需补登记）
    source_id=str(memory.id),
    title=...,
    content=redact_secrets_in_text(body),     # 脱敏不可绕过
    payload={"project_id": str(project.id), "doc_type": ...},
    space_id=str(project.space_id) if project.space_id else None,  # 注意：payload project_id ← space_id（命名遗留）
    repository_id=None,
    event_time=...,
    edges=(EdgeSpec(relation=EdgeRelation.REFERENCES, target_entity_id=project_node_id),),
)
```
**关键命名陷阱**：`KnowledgeEntity.space` FK 实际承载"项目"维度（v0.15.0 Project→Space 重构遗留）；`vector_ops.build_knowledge_points` 把 `entity.space_id` 写进 payload 字段名 `project_id`，`access_scope.resolve_allowed_project_ids` 也按此过滤。新 normalizer 必须把**项目 id 填进 `space_id`**（`IngestionEvent.space_id`），否则 visibility scope 过滤失效。

### Pattern 3: 分支反查叠加显式绑定（fail-soft 不变）
**What:** `LookupProjectByBranchView` 现仅 `parse_work_item_id_from_branch → ProjectWorkItemLink`；叠加 `ProjectBranch.filter(branch_name=…)` 显式绑定。
**When to use:** BIND-02。
**Example:**
```python
# Source: server/mcp_tools/views.py::LookupProjectByBranchView（保持 output_data 契约不变）
# work_item 反查（既有）∪ ProjectBranch 显式绑定（新增），合并去重：
projects = set(await self._lookup_projects(work_item_id))          # 既有
projects |= set(await self._lookup_by_branch_binding(branch_name)) # 新增 ProjectBranch
# len==1 → pack_project_context + matched=True；否则 candidates 列表（fail-soft，绝不抛）
```
**关键**：`ProjectBranch` 唯一键含 `repository`，但分支名跨仓可能重名。`lookup_project_by_branch` 当前**只收 `branch_name`**（无 repository）。BIND-02 多命中本就 fail-soft 返回候选——若同名分支跨多仓多项目，返回候选列表正是设计意图。建议序列化器**可选**接 `repository_id` 收窄（Phase 86 IDE hook 通常知道当前 repo）。

### Anti-Patterns to Avoid
- **把项目上下文塞进 `code_index_{repo}` 代码 collection**：locked decision 明确禁止（权限口径/排除规则串味）。
- **双重物理 collection 向量化**：若另起 `project_context` collection 又同时 CTX-02 写 `delivery_knowledge` = 同内容两份向量（见 A1）。
- **裸 async ORM**：所有 ORM 访问经 `sync_to_async`（adrf/MCP 异步路径强制）。
- **材料化失败阻断业务写**：必须 `except: pass` best-effort（观测/材料化绝不反噬主流程）。
- **`KnowledgeEntity.space_id` 误填仓库**：project 维度走 `space_id`，repository 走 `repository_id`（命名遗留陷阱）。
- **新增 EntityKind 随手改字面值**：`kind` 进 `generate_entity_id` uuid5 派生，改名即数据迁移。

## Don't Hand-Roll

| 问题 | 别自己造 | 用现成 | 为什么 |
|------|----------|--------|--------|
| 向量摄取/版本翻转/幂等/边 | 自写 upsert + 版本管理 | `knowledge.ingestion.aschedule_ingestion` + ingest_events | 六步事务序 + 四层幂等 + 确定性 point id + tombstone，已经过 Phase 13/14 加固 |
| collection 建表/校验 | 自写 create_collection | `ensure_delivery_knowledge_collection`（或复用） | hybrid + payload index + 配置不匹配响亮拒绝（P8 防线） |
| visibility scope 过滤 | 自写权限过滤 | `access_scope.resolve_allowed_project_ids` | 已含 public_org 读放宽 + fail-closed + caller 收窄语义 |
| RetrievalTrace 写入 | 自写 ORM create | `arecord_retrieval_trace`（run 可空） | 内置 `redact_for_ledger` + user/source contextvars + best-effort |
| 后台任务 + 归因 | 自写线程/asyncio.create_task | `run_in_background(initiated_by_user_id=)` | 解决 CurrentThreadExecutor 失效 + worker 入口 re-bind 归因 |
| grep/关键词召回 | 自写搜索 | `ProjectSearchService._keyword_search` | 已带 locator + RetrievalTrace + 多实体类型 |
| file-read 渲染 + 分区 | 自写文档读取 | `DocContentService.get_doc_render` | 已读 snapshot + 渲染缓存 + block system/human 分区 |
| 分支名解析 | 自写正则 | `parse_work_item_id_from_branch` | 严格 + 宽松兜底 + fail-soft 纯函数 |
| 兜底全量重建 | 自写脚本 | 镜像 `rebuild_delivery_knowledge` + apscheduler `*_job` 范式 | 删建 + 从 PG latest 重嵌入 + 单实例 flock + system 归因 |

**Key insight:** 本期 90% 工作是"挂钩子 + 加 normalizer + 加模型 + 叠加查询"，几乎没有需要从零构建的算法/基础设施。最大风险不是实现而是**架构口径决策（A1）**与**命名遗留陷阱（space=project）**。

## Common Pitfalls

### Pitfall 1: `aschedule_ingestion` 不透传 `initiated_by_user_id`
**What goes wrong:** CTX-02 要求"写时增量经 durable 任务带 `initiated_by_user_id`"，但 `aschedule_ingestion(request)` 当前签名只接 `IngestionRequest`，内部 `run_in_background(lambda: ingest(request), name=...)` 未传 `initiated_by_user_id`，后台摄取归因为空/默认。
**Why:** 既有 5 个 source 触发点都没归因需求；项目上下文是首个强制归因的摄取源。
**How to avoid:** plan 增加 `aschedule_ingestion(request, *, initiated_by_user_id=None)` 可选参数并透传给 `run_in_background`（该函数已支持），保持既有调用零回归（默认 None）。
**Warning signs:** 后台 `knowledge_ingest_*` 日志 `user_id=system` 而非触发用户。

### Pitfall 2: `space_id` vs `project_id` 命名遗留
**What goes wrong:** 把项目 id 填进 `IngestionEvent.repository_id` 或漏填 `space_id`，导致 `access_scope` 按 project 过滤时召回为空 / 跨项目泄漏。
**Why:** v0.15.0 Project→Space 重构后，`KnowledgeEntity.space` FK 承载"项目"维度，payload 字段名却叫 `project_id`。
**How to avoid:** normalizer 中 `space_id=str(project.space_id)`？——**注意**：`artifact.py` 用 `space_id=str(project.space_id)`（即项目所属 Space），但 `ProjectKnowledgeGraphService.ensure_project_node` 用 `space_id=project.space_id`。需在 plan 明确：召回过滤维度是"项目"还是"Space"。`access_scope.resolve_allowed_project_ids` 实际查 `projects.Space` + `initiatives.Project.visibility`——**核对**：`_public_org_project_ids` 查 `initiatives.Project`，但 `resolve_allowed_project_ids` 主体查 `PermissionService.get_user_projects`（返回 Space）。这是一个**真实的口径不一致风险**，plan 须 live 验证 packer/project_search 当前召回项目内容是否真按 `initiatives.Project.visibility` 过滤（见 Open Question 2）。
**Warning signs:** 非成员能召回 members_only 项目内容，或成员召回不到自己项目内容。

### Pitfall 3: 物化触发风暴 / 重复摄取
**What goes wrong:** 飞书双向同步（Phase 83）pull 回写正文 → 触发材料化 → 若 push/pull 回声又触发，造成摄取风暴。
**Why:** DocSyncService.pull 写 ProjectMemory/正文时，`MemoryService.sync_edit` 已有 `_skip_doc_push` 防回声；材料化钩子需同样防重复。
**How to avoid:** 摄取自带 content_hash 短路（`_persist_sync` hash 相同 skip，不产新版本不重嵌入），所以重复触发是幂等的，**成本仅一次预读**。但仍应在高频 pull 路径用 debounce 或仅在内容真变时触发。
**Warning signs:** `knowledge_ingest_skipped` 日志高频刷屏（说明触发过密，但正确性无损）。

### Pitfall 4: ProjectBranch 迁移序与唯一约束
**What goes wrong:** 迁移号撞车（最新 initiatives 迁移是 `0007_doc_sync_engine`）；unique(project,repository,branch_name) 在 SQLite/PG 行为差异。
**How to avoid:** 迁移命名 `0008_project_branch`，依赖 `0007`；纯 `CreateModel` 无回填。UUID PK（Project/Repository 均 UUID）。
**Warning signs:** `makemigrations` 产生冲突分支。

### Pitfall 5: lookup_project_by_branch 多命中召回成员闸
**What goes wrong:** 单命中走 `pack_project_context` 召回，但 packer 内 fail-closed——调用用户非成员且项目 members_only 时返回空 context。多命中只回候选不召回。
**Why:** 这是**设计正确行为**（不泄漏），但 IDE hook 用户若非项目成员会拿到空上下文。
**How to avoid:** 文档化此预期；public_org 项目非成员仍可召回（packer 已处理）。Phase 86 须知此约束。

## Runtime State Inventory

> 本期含新模型 + 向量库写入，含运行态盘点。

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `delivery_knowledge` Qdrant collection（新增 project_doc/project_memory 来源的 points + payload `source_kind`）；PG `KnowledgeEntity`/`Version`/`Edge`（新增 DOCUMENT 实体 + REFERENCES 边） | 写时增量 + 兜底重建均写这两处；无历史回填（净新内容） |
| Live service config | apscheduler 新增 `rebuild_project_context` job（注册态在 DjangoJobStore，非 git）；首次部署需注意 jobstore 残留（参照 `poll_repository_updates` Pitfall 4 注释） | runapscheduler 启动自动 `replace_existing=True` 重建；部署文档提示 |
| OS-registered state | 无（不涉及 OS 级注册） | None — 已核对 |
| Secrets/env vars | 无新增密钥；复用既有 embedding/Qdrant/飞书凭证（DB 加密） | None — 已核对 |
| Build artifacts | 无（纯 Python 模块，无编译产物/egg-info 改名） | None — 已核对 |

**新增 collection（若按 A1 复用 delivery_knowledge）**：不新建物理 collection，零运行态新增。**若另起物理 collection**：需新增 collection 元信息 SystemSetting + 全量重建入口 + reconcile，运行态显著增加。

## Code Examples

### 兜底全量重建 management command（按 project source 过滤重嵌入）
```python
# Source: 镜像 server/knowledge/management/commands/rebuild_delivery_knowledge.py::_rebuild
# 与全量删建不同：项目上下文兜底应"按 source_kind 重新摄取"而非删整库（delivery_knowledge 含
# work_item/tech_plan/code_change 等其他来源，不可连带删）。推荐遍历项目 active 内容重 aschedule：
async def _rebuild_project_context() -> tuple[int, int]:
    from initiatives.models import Project, ProjectMemory, ProjectMemoryStatus, ProjectDoc
    from knowledge.ingestion import aschedule_ingestion, IngestionRequest
    scheduled = 0
    async for mem in ProjectMemory.objects.filter(status=ProjectMemoryStatus.ACTIVE).aiterator():
        await aschedule_ingestion(IngestionRequest("project_memory", str(mem.id), "rebuild_project_context"))
        scheduled += 1
    # 同理 ProjectDoc（含正文）...
    return scheduled, 0
```
**关键**：兜底重建**不可**复用 `rebuild_delivery_knowledge --yes`（它删整个 delivery_knowledge）。content_hash 短路保证重 `aschedule_ingestion` 对未变内容是幂等空操作（只重嵌入真变的）。

### apscheduler 注册兜底 job（镜像现有范式）
```python
# Source: server/agents/management/commands/runapscheduler.py
@_with_scheduler_log_context
def rebuild_project_context_job():
    from django.core.management import call_command
    log = logger.bind(job="rebuild_project_context")
    log.info("job_start")
    try:
        call_command("rebuild_project_context")
        log.info("job_complete")
    except Exception as e:
        log.exception("job_error", error=str(e))
# scheduler.add_job(rebuild_project_context_job, CronTrigger(hour=6, minute=0), id="rebuild_project_context", max_instances=1, replace_existing=True)
```

### MCP file-read/grep 工具（镜像 SearchDeliveryKnowledgeView）
```python
# Source: server/mcp_tools/views.py::SearchDeliveryKnowledgeView（_record 自动写 RetrievalTrace）
class ReadProjectDocView(McpToolView):
    tool_name = "read_project_doc"
    async def post(self, request):
        run, err = await self._begin(request); ...
        from initiatives.services.doc_content_service import DocContentService
        result = await DocContentService().get_doc_render(project_id=..., doc_type=...)
        # 权限：DocContentService 读不校验成员（public_org 可读）；members_only 须叠加 access_scope 校验
        await self._record(run, ..., traces=[(RetrievalTrace.Kind.FILE, {...})], started_at=...)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 项目上下文仅 chat 链召回（packer） | 任意来源（前端/MCP/skills）可 RAG/grep/file-read | 本期 CTX-01 | 需把 packer/search/doc_content 经 MCP 工具暴露 |
| 项目仅作图谱参考节点（无内容版本，不进向量） | 5 文件/记忆/工件正文进 `delivery_knowledge` 可召回 | 本期 CTX-02 | 新 normalizer + 写时钩子；项目节点仍是 REFERENCES 边目标 |
| 分支反查仅 work_item_id（ProjectWorkItemLink） | 叠加 ProjectBranch 显式多绑定 | 本期 BIND | LookupProjectByBranchView 叠加查询 |
| 后台摄取无归因 | 写时增量带 initiated_by_user_id | 本期（Pitfall 1） | 扩 aschedule_ingestion 签名 |

**Deprecated/outdated:** 无（本期纯增量构建在 v0.15.0 + Phase 82/83/84 之上）。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | [ASSUMED] "独立项目上下文 collection" = 复用 `delivery_knowledge`（它本就与 per-repo 代码 RAG 物理分离 + visibility 隔离），而非另起第三个物理 Qdrant collection | Summary / Standard Stack / Alternatives | HIGH。若用户坚持要独立物理 collection，plan 需 +1 套 collection 生命周期/召回/scope/重建，工作量显著上升且与 CTX-02 双重向量化。**必须在 plan/discuss 与用户确认** |
| A2 | [ASSUMED] 新内容复用 `EntityKind.DOCUMENT` + 新 `source_kind`（project_doc/project_memory），不新增 EntityKind 枚举 | Pattern 2 / Alternatives | LOW-MEDIUM。若后续需按 kind 精确过滤项目内容召回，可能要新增 kind（数据迁移成本） |
| A3 | [ASSUMED] visibility 召回过滤维度口径一致（`access_scope` 按 `initiatives.Project.visibility` 生效于项目内容） | Pitfall 2 / Open Question 2 | MEDIUM。`resolve_allowed_project_ids` 混用 Space（PermissionService）+ Project（public_org），需 live 验证项目内容召回是否真按项目 visibility 过滤 |
| A4 | [ASSUMED] source=coding 自动绑定由 coding/plan 流水线（Phase 89）写入 ProjectBranch，本期不接 git push webhook（现有 git webhook 仅处理 MR 状态，无 push 事件） | Open Question 3 | LOW。本期只需提供 ProjectBranchService 写入方法 + 手动 REST；push 自动绑属 Phase 89 |
| A5 | [ASSUMED] 兜底重建按 source 重新 `aschedule_ingestion`（幂等 content_hash 短路），不删整个 delivery_knowledge | Code Examples | LOW。删整库会连带删 work_item/tech_plan 等其他来源 |

## Open Questions

1. **独立 collection 物理实现（A1）**
   - What we know: locked decision 要求"与代码 RAG 分离"；CTX-02 要求复用 KnowledgeEntity/Edge（= delivery_knowledge）；delivery_knowledge 已物理独立于 code_index_*。
   - What's unclear: 用户说的"专属 collection"是否特指一个全新物理 collection。
   - Recommendation: 复用 delivery_knowledge（满足全部约束、避免双重向量化）；在 discuss/plan 显式确认，若坚持独立物理 collection 则 plan 扩 collection 生命周期套件。

2. **visibility 召回过滤口径（A3 / Pitfall 2）**
   - What we know: `access_scope.resolve_allowed_project_ids` 混用 `PermissionService.get_user_projects`（Space 维度）+ `_public_org_project_ids`（`initiatives.Project.visibility`）。
   - What's unclear: 项目内容（space_id=项目 Space）经此过滤时，members_only 项目对非成员是否真正零召回。
   - Recommendation: plan 加一条 live 验证/对称守护测试（成员/非成员 × public_org/members_only × 项目内容召回），与 `test_project_context_packer` 同款。

3. **source=coding/plan 绑定写入时机（A4）**
   - What we know: 现有 git webhook（`initiatives/webhook_views.py`）仅 MR 状态，无 push；coding 节点 `workflows/nodes/ai/coding.py::_generate_candidate_branch` 单向生成分支名。
   - What's unclear: 本期是否需在分支生成处即写 ProjectBranch(source=coding)。
   - Recommendation: 本期提供 `ProjectBranchService.bind(source=…)` 写收口 + 手动 REST（source=manual）；coding/plan 自动绑定留 Phase 89 调用该 service（本期可加一处 best-effort 调用作为 seam）。

4. **lookup_project_by_branch 是否接 repository 收窄**
   - What we know: 当前序列化器只收 `branch_name`；ProjectBranch 唯一键含 repository。
   - Recommendation: 序列化器加**可选** `repository_id`，多命中时收窄；不传则跨仓返回候选（fail-soft 不变）。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Qdrant | delivery_knowledge 向量读写 | ✓（既有，docker-compose `qdrant/qdrant`） | 既有 | dev 可降级（ensure 失败响亮拒绝，非静默） |
| fastembed / EmbeddingService | 摄取嵌入 | ✓（既有，摄取内部已用） | 既有 | embedding None → 整批 abort（既有防线） |
| PostgreSQL/SQLite | KnowledgeEntity/Version/Edge + ProjectBranch | ✓ | 既有 | SQLite dev fallback |
| apscheduler / django-apscheduler | 兜底定时重建 job | ✓（既有 runapscheduler） | 既有 | 无 scheduler 时手动 management command |
| 飞书凭证（DB 加密） | DocSyncService.pull 正文（材料化源） | ✓（项目级） | 既有 | 缺凭证 fail-soft（artifact.py 已示范降级空正文） |

**Missing dependencies with no fallback:** 无。
**Missing dependencies with fallback:** 无新增。

## Validation Architecture

> Nyquist validation 已启用（config.json `workflow.nyquist_validation: true`）。

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.x + pytest-asyncio + pytest-django + respx（httpx mock）+ pytest-socket（网络隔离） |
| Config file | `server/pyproject.toml`（`[tool.pytest.ini_options]`）；`server/tests/conftest.py`（adrf monkeypatch 必须在 Django 加载前） |
| Quick run command | `cd server && uv run pytest tests/initiatives/ tests/services/test_project_context_packer.py -x -q` |
| Full suite command | `cd server && uv run pytest -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CTX-01 | RAG 召回项目内容（成员/非成员×visibility 对称） | unit | `pytest tests/services/test_project_context_packer.py -x` | ✅（扩充） |
| CTX-01 | grep（关键词命中 ProjectDoc/记忆/工件） | unit | `pytest tests/initiatives/test_project_search_*.py -x` | ❌ Wave 0（扩 ProjectSearch 测试） |
| CTX-01 | file-read（单文档渲染 + block 分区） | unit | `pytest tests/initiatives/test_doc_content_*.py -x` | ❌ Wave 0 |
| CTX-01 | MCP 工具暴露（search/grep/read_project_doc） | unit | `pytest tests/mcp_tools/ -x` | ✅（新增工具测试） |
| CTX-02 | 写时增量材料化触发（钩子调 aschedule_ingestion） | unit | `pytest tests/knowledge/test_project_doc_source.py -x` | ❌ Wave 0（镜像 artifact source 测试） |
| CTX-02 | normalizer 产 DOCUMENT 实体 + REFERENCES 边 | unit | `pytest tests/knowledge/test_project_memory_source.py -x` | ❌ Wave 0 |
| CTX-02 | RetrievalTrace 两链覆盖（MCP + 对话） | unit | `pytest tests/mcp_tools/test_retrieval_trace.py tests/test_rag_metrics_trace.py -x` | ✅（扩充） |
| CTX-02 | 兜底全量重建命令幂等 | unit | `pytest tests/knowledge/test_rebuild_project_context.py -x` | ❌ Wave 0 |
| BIND-01 | ProjectBranch 模型 + 唯一约束 + 写收口 INV-6 | unit | `pytest tests/initiatives/test_project_branch_*.py -x` | ❌ Wave 0 |
| BIND-02 | lookup 叠加显式绑定 + 多/无命中 fail-soft 候选 | unit | `pytest tests/mcp_tools/test_lookup_project_by_branch.py -x` | ✅（扩充） |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/<改动模块> -x -q`
- **Per wave merge:** `cd server && uv run pytest tests/initiatives/ tests/knowledge/ tests/mcp_tools/ tests/services/ -q`
- **Phase gate:** `cd server && uv run pytest -q` 全绿 + `uv run ruff check` + `uv run mypy`（项目惯例）后 `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/knowledge/test_project_doc_source.py` — 覆盖 CTX-02 project_doc normalizer（镜像既有 artifact source 测试）
- [ ] `tests/knowledge/test_project_memory_source.py` — 覆盖 project_memory normalizer
- [ ] `tests/initiatives/test_project_branch_model.py` + `test_project_branch_service.py` — BIND-01 模型/写收口/INV-6 grep 守护
- [ ] `tests/initiatives/test_project_branch_inv6_guard.py` — 旁路写表 grep 守护（镜像 `test_project_doc_inv6_guard`）
- [ ] `tests/knowledge/test_rebuild_project_context.py` — 兜底重建幂等
- [ ] 材料化钩子触发断言（在既有 memory/doc service 测试中加 `aschedule_ingestion` 被调断言，mock 摄取）
- [ ] visibility 对称守护扩充（成员/非成员 × public_org/members_only × 项目内容召回，Pitfall 2/A3）

*现有测试基础设施（`tests/initiatives/conftest.py`、respx 飞书 mock、`test_retrieval_trace`、`test_project_context_packer`）覆盖大部分 seam，Wave 0 主要补新 source/model/service 测试。*

## Security Domain

> `security_enforcement: true`，`security_asvs_level: 1`，`security_block_on: high`。

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | MCP 工具 `AccessTokenAuthentication`/`CookieJWTAuthentication`（McpToolView 基类已有）；前端 REST 经既有 DRF 认证 |
| V4 Access Control | **yes（核心）** | 召回 scope `access_scope.resolve_allowed_project_ids`（fail-closed + public_org 读放宽）；packer 内 members_only fail-closed；ProjectBranch 写仅成员（复用 ProjectMember）；file-read/grep MCP 工具必须叠加 visibility 校验（members_only 非成员不可读） |
| V5 Input Validation | yes | DRF serializer 校验 branch_name/project_id/doc_type；MCP `_validate` 统一 400 |
| V6 Cryptography | yes（不 hand-roll） | 凭证经既有 Fernet（不在本期改）；token_fingerprint 用 hash_token |
| V7 Logging（脱敏） | **yes（强制）** | 正文入图/留痕经 `redact_secrets_in_text`（normalizer 入图前）+ `redact_for_ledger`（RetrievalTrace）；日志只记 id/计数，绝不记正文/token |
| V8 Data Protection | yes | members_only 项目内容不进非成员召回结果（IDOR 防线，payload project_id 维度） |

### Known Threat Patterns for Friday（Django adrf + Qdrant + MCP）
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 跨项目召回泄漏（非成员读 members_only 内容） | Information Disclosure | `access_scope` service 层过滤（payload `project_id`），plan 须对称守护测试（A3） |
| 凭证/正文进向量库或日志明文 | Information Disclosure | `redact_secrets_in_text` 入图前 + `redact_for_ledger` 留痕；artifact.py 已示范 |
| 分支反查注入/越权 | Tampering/Elevation | branch_name 经纯函数解析（无 SQL 拼接）；召回经 packer fail-closed |
| 材料化触发反噬业务写 | Denial of Service | best-effort `except: pass` + content_hash 幂等短路 |
| MCP 工具未绑触发用户 | Repudiation | McpToolView `_begin` 绑 user + RetrievalTrace 透传 user_id |

## Sources

### Primary (HIGH confidence) — live `server/` 代码（全部本会话核实）
- `server/knowledge/ingestion.py` / `collection.py` / `vector_ops.py` / `retrieval.py` / `access_scope.py` / `models.py` / `sources/__init__.py` / `sources/artifact.py` — 摄取/召回/图谱基础设施
- `server/services/project_context_packer.py` / `background_runner.py` / `branch_parsing.py` — 打包/后台/解析
- `server/initiatives/services/{project_doc_service,doc_content_service,memory_service,project_search_service,knowledge_graph}.py` — 写收口 + 读 + 搜索 + 图谱
- `server/initiatives/models/{project,project_doc,memory}.py` + `webhook_views.py` — 模型 + git webhook（MR-only）
- `server/mcp_tools/views.py`（`McpToolView`/`LookupProjectByBranchView`/`SearchDeliveryKnowledgeView`） + `server/interactions/ledger.py` — MCP + Ledger
- `server/agents/call_source.py` / `agents/management/commands/runapscheduler.py` / `knowledge/management/commands/rebuild_delivery_knowledge.py` — call_source 枚举 + 调度 + 重建范式
- `server/repositories/models.py`（Repository UUID PK）/ `services/qdrant_service.py`（`get_collection_name=code_index_{repo}`）

### Primary (HIGH) — 规划/规范文档
- `.planning/phases/85-context-read-branch-binding/85-CONTEXT.md`（locked decisions）
- `.planning/REQUIREMENTS.md`（CTX/BIND）、`.planning/ROADMAP.md`（Phase 85 SC）、`.planning/project-workspace/MILESTONE-PROPOSAL.md`（§6/§7/§9/§12）
- `.cursor/rules/observability-logging.mdc` + `.planning/observability/LOGGING-SPEC.md`（§4.1 call_source 22 值 / §5 component 清单 / §10 事件目录）

### Secondary / Tertiary
- 无外部 WebSearch（本期纯内部代码组合，无需外部库调研）。

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 全部既有模块、签名经 live 代码核实
- Architecture: HIGH（实现路径）/ MEDIUM（A1 collection 口径需用户确认）
- Pitfalls: HIGH — 命名遗留(space=project)、归因透传缺口、scope 口径不一致均经代码核实
- Validation: HIGH — 既有测试基础设施 + Wave 0 gap 明确

**Research date:** 2026-06-27
**Valid until:** 2026-07-27（内部代码基线稳定，30 天）；A1/A3 决策点应在 plan 前确认
