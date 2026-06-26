# Phase 83: 飞书文档双向同步引擎 - Context

**Gathered:** 2026-06-26
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous) — 用户逐 Wave 选定

<domain>
## Phase Boundary

实现 5 文件的飞书↔Friday 双向近实时同步，且用户在飞书编辑绝不被系统写入冲掉；覆盖全部边界/失败模式。飞书→Friday 走 `drive.file.edit_v1` subscribe + 回拉 + TTL 兜底；Friday→飞书 block 级增量、永不整篇覆盖；block_id 结构化匹配 + 三方合并 + capture-never-clobber + 编辑感知延迟写。

交付需求：SYNC-01~06。
</domain>

<decisions>
## Implementation Decisions

### 同步落地顺序
- **5 文件齐头并进**：同步引擎对 5 类 `ProjectDoc` 统一抽象（区段所有权分区 + block_id 映射表通用），一次性把 MEMORY/STATE/MILESTONES/RESEARCH/PREFLIGHT 全部接入双向同步。
- 引擎按 doc_type 配置"系统区/人工区"切分与 Agent 写法（MEMORY=append 条目、STATE/MILESTONES=系统派生区+人工补充段、RESEARCH/PREFLIGHT=AI 待确认区+人工正文），但同步机制单一实现，不为某文件单独造链路。

### Friday→飞书 推送策略
- **debounce 合并后批量 block 推送**：DB 写不逐条即时推，合并静默窗口内的多次写后批量 block 级增量更新（`docx blocks` API），抗飞书频控。
- per-doc 串行队列 + 限流退避；create_folder/文档块写不并发。
- 永不整篇 replace（硬约束）。

### 防"编辑被冲掉"四机制（锁定，全部叠加）
1. 永不整篇覆盖，只写 block 级（飞书 OT 合并不同块并发）。
2. 区段所有权分区：系统只写系统区、人只写人工区，物理不相交。
3. Agent 写一律 append 新 block，绝不就地改既有 block。
4. 编辑感知延迟写：推送前探测文档近 N 秒是否有人编辑（drive 事件/last-edit），活跃则入队、静默窗口再落；带乐观并发（last-synced revision 校验，变了先 rebase 再写）。

### diff 策略（锁定）
- block_id 结构化逐块匹配（新增/编辑/删除）+ last-synced 快照 + 映射表，**代替整篇文本 diff**。
- 真同块冲突 → 三方合并（base=last-synced/theirs=飞书/ours=DB）；不相交自动并、相交 capture-never-clobber（落败方存 revision + 标记 + 飞书评论提示），绝不静默丢。
- block_id 漂移边角 → 就近匹配 + capture，不丢内容。

### 缓存（SYNC-05）
- redis read-through，写时/收事件失效，TTL 兜底；redis 不可用降级直读 DB（best-effort）。

### 边界/失败模式全覆盖（SYNC-06，fail-soft 不反噬）
- 漏事件 → 进行中项目 TTL 轮询比对 revision 兜底。
- 文档被删/移 → 回拉 not-found → 标 broken + 通知 + 一键重建。
- 项目归档/终止 → 停双向同步 + 停 subscribe，文档转只读快照入 DB。
- 非成员在飞书编辑 → fail-soft 接受 + 归因（operator→resolve_feishu_user，未映射 system）。
- 飞书限流 → 退避 + per-doc 串行队列。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/feishu/`（views/client/websocket_client/事件链路）：现有飞书事件路由，新增 `drive.file.edit_v1` 路由分支。
- `server/services/feishu_doc.py`：`get_document_content` blocks / docx blocks 增量写 API。
- `server/initiatives/models`（Phase 82 产出）：`ProjectDoc`/`ProjectDocBlockMap`/`ProjectStateApi` + last_synced_revision/snapshot。
- `server/resumable/`(durable 队列)：per-doc 串行队列 + 推送任务 durable 化。
- `server/common/logging.py`：`redact_secrets_in_text` 脱敏飞书正文。
- `server/initiatives/services/memory_service.py`：飞书编辑落 `ProjectMemoryRevision`。

### Established Patterns
- 飞书事件经 normalizer → handler 投三元组 ID（取材在 normalizer），失败降级缺段快照 + warning（Phase 14 范式）。
- durable 任务 at-least-once + 幂等去重 + fencing（v0.12.0）。
- best-effort 观测吞异常、绝不反噬主流程。

### Integration Points
- 飞书事件回调单一地址多路复用，按 event_type 路由。
- 写入收口 service（INV-6）；新增召回/写入埋点。

</code_context>

<specifics>
## Specific Ideas

- 用户选 5 文件齐头并进（非 MEMORY 先行）——引擎须先把通用抽象（区段分区 + block_id 映射 + 三方合并）做扎实，再按 doc_type 配置差异，避免 5 套链路。

</specifics>

<deferred>
## Deferred Ideas

- 飞书文档跨系统亚秒级 OT 实时协同（Out-of-Scope，按秒级最终一致交付）。

</deferred>

<canonical_refs>
## Canonical References

- `.planning/project-workspace/MILESTONE-PROPOSAL.md` — §4 同步引擎详设（4.1 链路 / 4.2 四机制 / 4.3 block_id 匹配 / 4.4 五文件形态）、§9 边界失败模式、§10 调研结论
- `.planning/REQUIREMENTS.md` — SYNC-01~06
- `.planning/ROADMAP.md` — Phase 83 Success Criteria
- `.cursor/rules/observability-logging.mdc` — 脱敏/归因/采样强制项

</canonical_refs>
