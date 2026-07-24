# Phase 28: WorkItem 脊柱 + 单一 upsert 入口 - Context

**Gathered:** 2026-06-15
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — recommendations auto-accepted)

<domain>
## Phase Boundary

新增 Django `delivery` app，立起 v0.6.0 操作态脊柱：唯一 canonical `WorkItem`（飞书三元组身份）+ `WorkItemService.upsert` 单一写入入口（INV-6）+ source-of-truth 三分类（mirror/friday_enhanced/writeback）+ `WorkItemSyncState`（按 facet 来源完整度）+ `WorkItemRelation`（从关联字段派生）+ `WorkItemStatusEvent`（append-only 状态事件流）。

本 phase **建脊柱本体 + service + 模型 + migration + 至少一条真实入口（manual/by-ID 与 webhook）**。`bitable_import`（Phase 31）、`mr_reverse`（Phase 32）作为 `origin` 枚举值与 upsert 入参先就位，真实调用方后续 phase 接入。评论事件流摄取（Phase 29）、Document/REFERENCES（Phase 30）、评论入图/反查（Phase 34）不在本 phase。

覆盖需求：WIT-01（三元组幂等收敛唯一 canonical）、WIT-02（只经 upsert，三分类刷新）、WIT-03（per-facet SyncState，部分失败不回滚）、WIT-04（从关联字段派生 Relation + 占位）、WIT-05（append-only StatusEvent）。
不变量：INV-1（三元组唯一）、INV-3（knowledge 是投影非事实源）、INV-6（落库只经 upsert）。
</domain>

<decisions>
## Implementation Decisions

### delivery app 结构与注册（Grey Area 1）
- 新建 `server/delivery/` app，遵循"Django app = bounded context"约定：`models/`（包，按实体拆分 + `__init__.py` 再导出）、`services/`、`api/`（views/serializers，REST 暴露按需最小）、`migrations/`、`urls.py`、`apps.py`。
- 注册到 `server/friday/settings.py` `INSTALLED_APPS`（在 `knowledge`/`feishu`/`projects` 之后追加 `"delivery"`）。
- `models/` 拆分：`work_item.py`、`sync_state.py`、`relation.py`、`status_event.py`；`models/__init__.py` 统一 re-export（curated API 约定）。
- 本 phase REST API 面**最小**：提供"按三元组/URL 手动 upsert + 读取 WorkItem"的最小端点即可（IsAuthenticated）；不做完整 CRUD 后台（非本里程碑核心价值）。

### WorkItem 模型字段（Grey Area 2，严格对齐 DOMAIN §12.1 / §1.3）
- `id = UUIDField(primary_key, default=uuid4)`。
- 自然键三元组 `feishu_project_key(CharField64)` / `work_item_type(CharField32)` / `work_item_id(BigIntegerField)`，**`unique_together`** 强制 INV-1。
- `feishu_project_simple_name(CharField128, blank)`、`project = FK(projects.Project, null, SET_NULL)`、`origin(choices: feishu_webhook|manual|bitable_import|mr_reverse)`。
- mirror：`title`、`status_state_key`、`status_sub_stage`、`status_display_name`、`is_archived_state`/`is_init_state(Bool)`、`feishu_fields(JSONField default=list)`（完整 fields[] 对象数组，复用 Phase 27 helper）、`prd_url`/`tech_doc_url(URLField blank)`。
- friday_enhanced：`business_line_normalized`/`module_normalized(CharField blank)`、`internal_note(TextField blank)`。
- writeback：`feishu_chat_id(CharField blank)`。
- 元数据：`field_provenance(JSONField default=dict)`、`last_synced_at(DateTimeField null)`、`created_at`/`updated_at(auto)`、`event_time(DateTimeField)`。
- 索引：`unique_together(feishu_project_key, work_item_type, work_item_id)`、`index(project, work_item_type)`、`index(status_state_key)`。

### WorkItemService.upsert 单一入口与事务语义（Grey Area 3，INV-6）
- 签名：`async def upsert(identity: WorkItemIdentity, source: str, *, fetch: bool = True) -> WorkItem`。`WorkItemIdentity` = dataclass/`(project_key, work_item_type, work_item_id)`。
- **唯一写入入口**：所有路径（webhook/manual/bitable/mr_reverse）都经此；模型层不在别处直接 create/save WorkItem（INV-6 守护，可加测试 grep 断言）。
- 步骤（对齐 DOMAIN §13.1）：
  1. 按三元组 `select_for_update` 取/建 WorkItem（幂等键，INV-1）。async 经 `sync_to_async` 包裹 `transaction.atomic` 同步块（项目既有 async ORM 约定）。
  2. `fetch=True` → 调 Phase 27 修好的 `get_work_item`（真实 type，完整 feishu_fields）；按 facet 记 `WorkItemSyncState`。
  3. 刷新 **mirror** 字段；**绝不动 friday_enhanced**；writeback 仅由专门流程改（本 phase 不实现写回，留接口位）。
  4. 解析 `feishu_fields` 派生：`prd_url`（别名 prd_url/field_000001）、`tech_doc_url`、`status_display_name`（取 current_nodes/state_times，免映射 API）、关联字段 → `WorkItemRelation`（复用 Phase 27 `derive_relations_from_fields`）。
  5. 写 `field_provenance` + `last_synced_at`；发 `work_item.synced` 事件（复用既有事件/信号机制，best-effort）。
  6. 失败：部分 facet 失败不回滚整体 WorkItem；落 `WorkItemSyncState.error` + 重试标记，缺料降配继续（对齐 knowledge/sources normalizer 范式）。
- 幂等：同三元组多次 upsert 收敛同一行；不同 origin 进入也收敛（WIT-01 关键测试）。

### WorkItemSyncState（Grey Area 4，WIT-03）
- 字段对齐 DOMAIN §12.2：`work_item FK(CASCADE)`、`facet(choices: basic_fields|prd_body|tech_doc|comments|relations)`、`status(choices: complete|partial|missing|stale)`、`source(choices)`、`last_synced_at(null)`、`error(TextField blank)`。`unique_together(work_item, facet)`。
- 本 phase 实际记录的 facet：`basic_fields`、`relations`（PRD/技术方案正文 facet 由 Phase 30 文档摄取补；comments 由 Phase 29 补）——未摄取的 facet 记 `missing`，不假装 complete。
- MR 反查/webhook/Bitable 各自的 completeness 语义按 §1.4 表（manual by-ID 通常 basic_fields=complete）。

### WorkItemRelation 派生与占位（Grey Area 5，WIT-04）
- 复用 Phase 27 `derive_relations_from_fields(feishu_fields) -> [RelationSpec]` 派生 belongs_to_project/sprint/version/related。
- 持久化 `WorkItemRelation`（DOMAIN §12.3）：`source_work_item FK`、`target_work_item FK(null)`、`target_external_id(BigIntegerField null)`（目标未 upsert 时占位）、`relation_type(choices)`、`source_field_key(CharField64)`、`origin(choices: feishu_field|feishu_relation_api|friday，主路径 feishu_field)`。`unique_together(source_work_item, relation_type, target_external_id, source_field_key)`。
- 目标后续 upsert 落库后，可回填 `target_work_item`（best-effort，可在 upsert 时反向连接已存在占位）。

### WorkItemStatusEvent append-only（Grey Area 6，WIT-05）
- 字段：`work_item FK`、`pre_state_key`/`cur_state_key`、`pre_sub_stage`/`cur_sub_stage`、`operator`、`event_time`。索引 `(work_item, event_time)`。
- upsert 时：若 incoming `status_state_key` 与库内当前不同 → append 一条 StatusEvent（pre=旧、cur=新），同时更新 WorkItem.status_* mirror。**状态变更记事件，非就地覆盖历史**。
- 回填：当飞书响应带 `work_item_status.history[]` 时，可补建历史 StatusEvent（去重按 (work_item, cur_state_key, event_time)）。

### 入口接线范围（Grey Area 7）
- 本 phase 必接：① manual by-ID（控制台/服务调用 upsert 落库并读取）；② feishu webhook 工作项事件 → 现有 `server/feishu/` / `workflows/triggers/handlers/feishu.py` 接线投三元组 → 调 upsert（取材后台，沿用既有"webhook 只投 ID，正文后台拉"范式）。
- `bitable_import`(Phase 31)/`mr_reverse`(Phase 32)：仅作为 `origin` 枚举 + upsert 接受该 source，**不在本 phase 实现真实调用方**。
- knowledge 投影（INV-3）：delivery 是操作态事实源；本 phase **不改 knowledge app、不重建投影**；现有 `knowledge/sources/feishu_work_item.py` normalizer 保持，后续 Phase 34 接 work_item 反查。避免双写事实。

### 异步 / ORM / 测试（Claude's Discretion 范围内）
- async-first：service `async def`，ORM 访问经 `sync_to_async` 桥接；`select_for_update` 放在 `transaction.atomic` 同步函数内再 `sync_to_async`。
- 测试：`pytest-django` + `factory-boy`（WorkItem/Relation factory）+ `respx`（mock get_work_item 回源）+ `pytest-socket`（网络隔离）。
- 核心守护测试：① 同三元组不同 origin 多次 upsert → 唯一行（INV-1/WIT-01）；② 只刷 mirror、enhanced 字段被保护（WIT-02）；③ 某 facet 回源失败 → 该 facet SyncState=error/missing、WorkItem 不整体回滚（WIT-03）；④ 从 field_000008=[id] 派生 belongs_to_project + 目标未落库走 target_external_id 占位（WIT-04）；⑤ 状态变更 append StatusEvent、非就地改写（WIT-05）；⑥ INV-6 守护：grep 断言无旁路 WorkItem 写表。

### Claude's Discretion
- `WorkItemIdentity` 的具体形状（dataclass vs NamedTuple）、service 文件拆分粒度、`work_item.synced` 事件的具体投递机制（Django signal vs 既有事件总线）、REST 端点的确切路径与 serializer 字段集、migration 是否拆多个 —— 由实现按既有约定决定。
- `status_display_name` 派生的取值优先级细节（current_nodes 优先还是 state_times）—— 取能稳定拿到人类名者。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- Phase 27 `server/services/feishu_parsing.py`：`build_feishu_fields`/`derive_relations_from_fields`/`extract_prd_url`/`extract_tech_doc_url`/`parse_comments` —— upsert 派生逻辑直接复用，不重写。
- Phase 27 `server/services/feishu.py` `get_work_item`（真实 type、完整 feishu_fields、relation 端点降级）—— upsert 回源调用。
- `services.feishu.create_feishu_client_for_project(project)` —— 从 Project 加密凭证建 client（零 env）。
- `server/knowledge/sources/feishu_work_item.py` —— 既有飞书工作项 normalizer，natural key 三元组同口径（`{project_key}:{work_item_type}:{work_item_id}`），降级范式可借鉴；INV-3 下保持投影、不被 delivery 取代。
- `projects.Project`（含 feishu_project_key/plugin 凭证）—— WorkItem.project FK + 凭证来源。
- 既有 app 模式（如 `knowledge`、`repositories`）的 models/ 包 + api/ + migrations 结构作模板。

### Established Patterns
- async DRF（adrf）+ channels；ORM 异步经 `sync_to_async`（CLAUDE.md 架构约束）。
- app 注册在 `server/friday/settings.py` INSTALLED_APPS（bare app 名）。
- 结构化日志 structlog；中文 docstring；ruff format line 100；snake_case 模块；PascalCase 模型 + str/Enum choices。
- knowledge normalizer 的"部分缺料降配不 raise + warning"失败范式（与 WIT-03 一致）。

### Integration Points
- `server/friday/settings.py` INSTALLED_APPS（注册 delivery）。
- feishu webhook / `workflows/triggers/handlers/feishu.py` —— 工作项事件接线调 upsert。
- 后台取材：复用既有 background runner 范式（webhook 只投三元组，正文后台拉）。
- 下游消费（后续 phase）：Phase 29 CommentEvent FK WorkItem、Phase 30 Document.work_item FK + REFERENCES、Phase 31 ReleaseRecord.work_item FK、Phase 32 ING 编排经 upsert、Phase 34 反查/评论入图。
</code_context>

<specifics>
## Specific Ideas

- DOMAIN §12.1/§12.2/§12.3/§12.4 字段表是建模权威；§13.1 是 upsert 步骤权威；§16/§1.5 实测字段（story 1000000002：field_000008=[1000000004] 派生 belongs_to_project；issue 1000000006）作 fixture。
- INV-1 由 DB `unique_together` 强制；INV-6 由"只经 upsert"+ 守护测试强制；INV-3 由"不改 knowledge"守住。
- 容器型工作项真实 type_key 未知（URL 段 project ≠ API type）→ 目标占位用 target_external_id，不强行解析容器型。
</specifics>

<deferred>
## Deferred Ideas

- 评论事件流摄取 `WorkItemCommentEvent`（comments facet）—— Phase 29。
- Document/DocumentVersion + REFERENCES 边 + prd_body/tech_doc facet 正文摄取 —— Phase 30。
- ReleaseBatch/Record/Artifact —— Phase 31。
- bitable_import / mr_reverse 真实调用方 —— Phase 31 / 32（本 phase 仅枚举 + upsert 接受 source）。
- 评论入图 / 片段→需求反查 / knowledge 投影接 WorkItem —— Phase 34。
- writeback 字段真实写回飞书流程 —— 留接口位，本 phase 不实现。
- TechnicalPlan / PlanVersion（§12.7）—— v0.7。
</deferred>

---

*Phase: 28-workitem-spine*
*Context gathered: 2026-06-15 via smart discuss (autonomous)*
