# Phase 79: 工件/依赖项（可配置类型 + 实例 + RAG）+ 知识关联 - Context

**Gathered:** 2026-06-25
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous，elegant defaults；后端 + API 为主，富前端留 Phase 81）

<domain>
## Phase Boundary

把"需求文档/feature list/研发 Spec/UI 稿/UI 评审/埋点文档/埋点评审/复盘"等外部依赖统一抽象为**可配置类型的工件**，挂到项目、可在线查看、文字载体进 RAG，并把项目纳入交付知识图谱关联。

**In scope（ARTIFACT-01~05, KLINK-01/02）:**
- `ArtifactType` 可配置注册表（内置 8 类，后台增删禁用）
- `Artifact` 实例（多载体）+ `ArtifactService` 单一写入（INV-6）
- 工件在线查看的**后端读取/渲染 API**（飞书 doc/表格读取、外链元数据、md/内部可编辑内容）
- 工件 RAG 摄取（文字载体全文进 `delivery_knowledge`，UI 稿仅元数据）
- 项目↔知识实体多对多 + 项目↔仓库/空间/项目/知识经 `KnowledgeEdge` 统一建模（可查询）

**Out of scope:**
- **工件查看器 / 工件类型后台管理页等富前端 UI** → Phase 81（UI-03）。本期只交付后端 + REST API（含读取/渲染数据），避免与 81 工作台返工。
- 记忆 / MR / 召回接入会话 → Phase 80（本期只做 RAG 摄取入库，不接 chat runner）。
</domain>

<decisions>
## Implementation Decisions

### 模型落点
- `ArtifactType` + `Artifact` + `ArtifactService` 落 **`initiatives` app**（与 `Project` 聚合根同域）。FK 字符串引用 `"initiatives.Project"`/`"accounts.User"`。

### 工件类型注册表（ARTIFACT-01/05）
- `ArtifactType`：`key`(唯一 slug) / `name` / `carrier`(默认载体语义) / `ragable`(bool) / `enabled`(bool) / `builtin`(bool) / 时间戳。
- **内置 8 类经 data migration seed**（builtin=True，不可删只可禁用）：需求文档 / feature list / 研发 Spec / UI 稿 / UI 评审 / 埋点文档 / 埋点评审 / 复盘。其中"UI 稿/UI 评审"默认 `ragable=False`（图形），文字类 `ragable=True`。
- 后台（超管）CRUD：新增/禁用/删除自定义类型；**禁用类型不可新建实例、既有实例只读保留**（ArtifactService 校验）；**删除受既有实例约束保护**（`on_delete=PROTECT` 或 service 预检，有实例则拒删）。builtin 类型禁删（只可禁用）。

### 工件实例（ARTIFACT-02/03）
- `Artifact`：`project`(FK) / `type`(FK→ArtifactType) / `carrier`(feishu_doc/feishu_bitable/external_link/markdown/repo_file) / `title` / `url`(外链/飞书链接) / `content_ref`(md/内部内容或仓库文件引用) / `version` / `contributor`(FK→User) / 时间戳。
- **`ArtifactService` 单一写入入口（INV-6）**：create/update/version/disable-aware 校验全收口；模型层无业务方法；INV-6 grep 守护。
- 在线查看（**后端 API**，前端留 81）：飞书 doc/表格经既有 `feishu_doc`/`feishu_bitable` service 读取渲染为结构化/文本；外链返回元数据 + 跳转 url；md/内部工件 `content_ref` 可读可写（编辑经 ArtifactService）。

### 工件 RAG 摄取（ARTIFACT-04）
- 新增 knowledge source（如 `server/knowledge/sources/artifact.py`，**镜像 `sources/feishu_document.py` 范式**）：`ragable=True` 且文字载体（飞书 doc/表格/md/研发 Spec）→ 全文摄取进 `delivery_knowledge`（复用 `knowledge/ingestion.py` + chunking + 向量），产 `KnowledgeEntity` + 工件→REFERENCES→知识出边。
- **UI 稿（figma/mastergo）等图形外链仅存元数据**（`ragable=False`），**不强行 RAG 正文**（多模态留 v2 PROJX-01）。
- 摄取前**脱敏不可绕过**（飞书正文经 `redact_secrets_in_text`）；摄取失败 fail-soft 降级（缺段不缺实体，warning），不阻断工件创建。
- 新增摄取路径上观测：started/completed/failed + duration_ms + 条数（category=sampling 或 caller 视触发，component=knowledge/initiatives）。

### 知识关联（KLINK-01/02）
- **复用 `KnowledgeEntity/KnowledgeEdge` 脊柱，不另起炉灶**（proposal §5 倾向）。把 `Project` 纳入交付知识图谱：新增 `EntityKind` 值（如 `project`）+ `generate_entity_id` 派生，项目作为图谱节点。
- **KLINK-01 项目↔知识多对多**：经 `KnowledgeEdge`（项目实体 ↔ 知识实体，relation 如 `RELATES_TO`/`REFERENCES`，可扩展 `EdgeRelation`）。一个知识可属多项目、一个项目关联多知识。
- **KLINK-02 项目↔仓库/空间/项目/知识统一**：均经 `KnowledgeEdge` 建模，可查询（REST/MCP 查询 API）；前端可视化留 Phase 81。Phase 77 的 `ProjectRelation`、Phase 78 的 `ProjectWorkItemLink` 保持为**操作态源**，KnowledgeEdge 作为**统一可查询/可视图层**；plan-phase 决定是否写穿（bridge），默认不双写、KnowledgeEdge 经 service 由操作态派生/补建。
- 复用既有 `knowledge/graph_store.py` 多跳查询、`generate_entity_id` 命名约定（kind 进 uuid5 PK，改名即迁移——锁死枚举字面值）。

### 观测与异步
- 新增 REST 入口纳入指标；ArtifactService/类型变更经 `AuditService` 审计（component=initiatives）；新增 RAG 摄取上报条数/耗时并视需要写 `RetrievalTrace`（**摄取**侧主要是 ingestion 埋点；召回接 chat 留 80）。
- async ORM 走 `sync_to_async`；脱敏 `redact_*` 不可绕过。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/knowledge/`：`models.py`（`KnowledgeEntity`/`KnowledgeEntityVersion`/`KnowledgeEdge`/`EntityKind`/`EdgeRelation`，bi-temporal/版本/边）、`ingestion.py`（摄取入口）、`sources/feishu_document.py`（**工件 RAG 范式模板**）、`graph_store.py`（多跳查询）、`chunking.py`/`vector_ops.py`、`generate_entity_id`。
- `server/services/feishu_doc*`/`feishu_bitable.py`：飞书文档/表格读取（在线查看 + 摄取取材）。
- `server/initiatives/`（Phase 77/78）：`Project`/`ProjectService`/`ProjectWorkItemLink`。
- `server/audit/`：`AuditService.aemit`。
- 既有 `knowledge/migrations/0006_rename_project_to_space.py` 确认 Phase 76 已贯通。

### Established Patterns
- 知识实体 kind 枚举字面值锁死（kind 进 uuid5 PK 派生）；hash 相等不产生新版本；边幂等可重入（apply_edge_specs）。
- 单一写入 service（INV-6）+ data migration seed 内置数据。

### Integration Points
- 工件文字载体 → `knowledge/ingestion.py` → `delivery_knowledge`（向量 + 图谱实体）。
- 项目作为知识图谱节点（新 EntityKind）↔ 知识/仓库/空间/项目（KnowledgeEdge）。
</code_context>

<specifics>
## Specific Ideas

- 内置 8 类的 `ragable`/`carrier` 默认：文字类（需求文档/feature list/研发 Spec/埋点文档/UI 评审文字/复盘）`ragable=True`；UI 稿（figma/mastergo 图形链接）`ragable=False` 仅元数据。
- 删除工件类型受既有实例保护（PROTECT），builtin 禁删只可禁用——硬约束。
- KnowledgeEdge 作为统一可查询图层，不与 Phase 77/78 操作态表双写（service 单向派生）。
</specifics>

<deferred>
## Deferred Ideas

- 工件查看器 / 类型后台管理 / 知识关系图可视化**前端** → Phase 81（UI-03）。
- 召回接入 chat runner / context packer → Phase 80（RECALL）。
- UI 稿多模态/figma API 正文召回 → v2（PROJX-01）。
- 真实飞书文档/表格凭证下的在线查看与摄取人工验收 → 里程碑级。
</deferred>
