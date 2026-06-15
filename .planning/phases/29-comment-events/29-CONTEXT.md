# Phase 29: 评论事件流 - Context

**Gathered:** 2026-06-15
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — recommendations auto-accepted)

<domain>
## Phase Boundary

工作项评论以 append-only `WorkItemCommentEvent` 流式入库（created/replied/edited/deleted/approval），再投影出当前评论树（线程结构）——为灰区讨论/方案再生成（v0.7 消费）提供清晰事件边界，而非快照。

本 phase 建：`WorkItemCommentEvent` 模型 + migration（delivery app）+ 评论摄取入口（经 Phase 27 `parse_comments` 拉取 + 接 webhook 评论事件）+ 当前评论树投影（查询/视图，非另一张事实表）+ approval 语义记录。

覆盖需求：CMT-01（append-only 评论事件流，含 approval）、CMT-02（从事件流投影当前评论树，编辑/删除作为事件不就地改写）。
依赖：Phase 27（FIX-03 get_comments/parse_comments）、Phase 28（WorkItem 脊柱 + comments facet）。
INV-1/INV-3/INV-6 延续：评论事件挂 canonical WorkItem；knowledge 不被取代；落库经 delivery 服务入口。
</domain>

<decisions>
## Implementation Decisions

### WorkItemCommentEvent 模型（Grey Area 1，对齐 DOMAIN §2 / §12.4）
- 落在 `server/delivery/models/comment_event.py`，re-export 于 `models/__init__.py`。
- 字段：`id(UUID pk)`、`work_item FK(CASCADE)`、`feishu_comment_id(CharField)`、`thread_parent_id(CharField blank)`（线程父，根评论为空）、`event_type(choices: created|replied|edited|deleted|approval)`、`author(CharField)`、`body(TextField)`、`attachments(JSONField default=list)`、`approval_semantic(choices: none|approve|reject, default none)`、`event_time(DateTimeField)`、`ingested_at(DateTimeField auto_now_add)`。
- 索引 `(work_item, event_time)`。append-only：编辑/删除是**新事件**（event_type=edited/deleted），不就地改写既有行（CMT-02）。
- 去重锚：`(work_item, feishu_comment_id, event_type, event_time)` 防重复摄取（同评论多次拉取不产生重复事件）；幂等可重入。

### 评论摄取入口与单一写入（Grey Area 2，CMT-01）
- 摄取经 delivery service（如 `CommentEventService.ingest(work_item, comments)` 或并入 `WorkItemService` 的评论 facet 流程），**append-only 写入唯一收口**（延续 INV-6 精神：评论事件落库只经该入口，禁旁路写表，可加守护测试）。
- 拉取复用 Phase 27 `services/feishu.py get_comments`（真实 type，防御解析 fail-soft）+ `services/feishu_parsing.parse_comments`——不重写解析。
- 摄取后按 facet 记 `WorkItemSyncState(facet=comments, status=complete|partial|missing)`（对齐 Phase 28 SyncState 机制）；拉取失败降配（comments=missing/error + warning），不抛、不回滚 WorkItem。

### 事件类型映射与 approval 语义（Grey Area 3）
- `created`：根评论（无 thread_parent）首次出现；`replied`：带 thread_parent 的回复；`edited`/`deleted`：飞书评论被改/删时作为新事件追加（若飞书 API 提供编辑/删除信号；不可得则本 phase 仅落 created/replied，edited/deleted 留枚举位 + 后续接入）。
- `approval`：审批语义评论。`approval_semantic` 由评论内容/审批字段判定（approve/reject），复用 webhook `_handle_workitem_comment` 既有 approval 关键词识别逻辑作判定来源（中文「通过/批准/lgtm」→approve，「驳回/拒绝/不通过」→reject），其余 none。审批语义作为**事件**记录，为 v0.7「评论触发方案再生成」提供触发边界（本 phase 不实现再生成，仅记录边界）。

### 接线范围（Grey Area 4）
- webhook 评论事件 `_handle_workitem_comment`（`server/feishu/views.py`）：在保留既有 approval 处理的同时，**追加**后台 append CommentEvent（与 Phase 28 delivery upsert 接线同范式：webhook 投三元组/评论 payload → 后台经 service append），缺三元组/缺 work item 跳过 + warning。INV-3：不改 knowledge。
- 拉取式摄取：提供 `ingest_comments(identity)` 路径（拉 get_comments → append events），供 manual/编排（Phase 32 ING）调用；本 phase 至少接通"按 work item 拉评论入库"。

### 当前评论树投影（Grey Area 5，CMT-02）
- 投影是**查询/视图，非事实表**：提供 `project_comment_tree(work_item) -> nodes` 服务函数，从事件流计算当前评论树：按 feishu_comment_id 归并同一评论的事件序列（created→replied→edited→deleted 取最新有效态），deleted 标记为已删除节点（保留占位以维持线程结构或按策略剔除），按 thread_parent_id 组装线程层级，按 event_time 排序。
- 编辑取最新 edited body；删除按 event_type=deleted 标记。**绝不就地改写事件行**——投影在读时计算。
- 最小 REST 只读端点（IsAuthenticated）：按 work item 三元组返回当前评论树投影（与 Phase 28 delivery REST 同风格），便于验证与下游消费。

### 异步 / 测试（Claude's Discretion 范围内）
- async-first，ORM 经 `sync_to_async`；摄取 best-effort 后台（沿用 run_in_background 范式）。
- 测试：pytest-django + factory-boy + respx（mock get_comments）+ pytest-socket。守护：① 评论 append-only（编辑/删除产生新事件、不改旧行，CMT-01/02）；② 重复摄取幂等不产生重复事件；③ 投影从事件流正确还原线程树 + 编辑取最新 + 删除标记（CMT-02）；④ approval 语义事件正确记录 approve/reject；⑤ 拉取失败 comments facet=missing/error 不回滚。

### Claude's Discretion
- CommentEventService 是独立 service 还是并入 WorkItemService、投影函数放 service 还是 selector 模块、deleted 节点在树中保留占位还是剔除、attachments 解析深度 —— 由实现按既有约定决定。
- edited/deleted 事件若飞书 webhook/API 不提供对应信号，则本 phase 仅落 created/replied/approval，edited/deleted 保留枚举位（标注 deferred 至真实信号可得）。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- Phase 27 `services/feishu.py get_comments`（防御解析 fail-soft）+ `services/feishu_parsing.parse_comments`（解析 id/content/created_at/author/线程父）—— 摄取直接复用。
- Phase 28 `server/delivery/`（WorkItem 模型 + WorkItemService + WorkItemSyncState + REST/webhook 接线范式 + run_in_background 后台投递）—— CommentEvent 复用 app 结构、SyncState facet、接线范式。
- `server/feishu/views.py _handle_workitem_comment`（既有 approval 关键词识别 + FeishuApprovalHandler）—— approval_semantic 判定来源 + 追加 append 接线点。
- Phase 28 INV-6 grep 守护测试范式 —— 复用为评论 append-only 单一入口守护。

### Established Patterns
- delivery app models/ 包 + service + api + migration 结构（Phase 28 立的模板）。
- async DRF（adrf）+ sync_to_async ORM；webhook 只投 ID、后台权威回源；缺料降配不 raise + warning（knowledge normalizer / Phase 28 范式）。
- ruff line 100、中文 docstring、structlog、snake_case 模块、PascalCase 模型 + str/Enum choices。

### Integration Points
- `server/delivery/models/` + `migrations/`（新增 comment_event）。
- `server/feishu/views.py _handle_workitem_comment`（追加后台 append）。
- 下游：Phase 32 ING 摄取调评论拉取；Phase 34 评论入图（knowledge 投影）+ 反查；v0.7 评论触发方案再生成（消费 approval 事件边界）。
</code_context>

<specifics>
## Specific Ideas

- DOMAIN §2 / §12.4 是 CommentEvent 建模权威；approval 事件挂 created|replied|approval 提供 v0.7 触发边界。
- 编辑/删除作为事件、不就地改写（CMT-02 关键）。当前评论树 = 对事件流的投影（读时计算）。
- 真实评论端点正确性（PF-11）仍依赖真实飞书凭证人工验收（Phase 27 已修解析容错，端点正确性 human-UAT）；本 phase 以"解析/投影/append 行为单测 + 防御不崩"为可自动验证标准。
</specifics>

<deferred>
## Deferred Ideas

- 评论入图（knowledge 投影）+ 片段→需求反查 —— Phase 34。
- 评论触发方案再生成 —— v0.7（本 phase 仅记录 approval 事件边界）。
- edited/deleted 事件真实信号接入（若飞书 webhook/API 不提供）—— 留枚举位，后续补。
- 评论端点真实正确性人工验收 —— human-UAT（需真实飞书凭证）。
</deferred>

---

*Phase: 29-comment-events*
*Context gathered: 2026-06-15 via smart discuss (autonomous)*
