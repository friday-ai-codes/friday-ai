---
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  gap_snapshot: "unknown::scenarios=0"
---

# Phase 83 — live-Feishu UAT 待验证清单（deferred）

> 本里程碑实现环境**无 live 飞书凭证**，drive 事件/订阅端点/回拉 block 形态以 `[ASSUMED]`
> 实现、respx mock 覆盖单测。下列契约项须在有真机凭证时按「how-to-verify」校验后，把代码内
> `[ASSUMED]` 改为 `[VERIFIED]` 并回填真实字段/端点。检查点本期按
> **PASSED-with-deferred-live-verification** 处理，不阻断后续 plan。

## 83-02（SYNC-01 飞书→Friday 回拉链路）

| ID | 契约假设 [ASSUMED] | 代码位置 | how-to-verify（真机） | 回填动作 |
|----|--------------------|----------|------------------------|----------|
| A1 | `drive.file.edit_v1` 事件走开放平台标准 schema（`header` + `event`），字段：`event.file_token`（即 docx 的 `feishu_document_id`）、`event.operator_id_list[0].open_id`、`header.event_id` | `server/feishu/views.py::_normalize_drive_edit_event` | 订阅一个真实 docx 并人工编辑 → 经 `record_inbound_webhook` 查原始 payload，确认 `file_token`/`operator_id*`/`event_id` 真实键名与容器（`event` vs `payload`） | 回填 `_normalize_drive_edit_event` 候选键；改 [VERIFIED] |
| A2 | 飞书 WS 长连暂不确定支持 `register_p2_drive_file_edit_v1`；drive 事件仅经 HTTP webhook 入口路由 | `server/feishu/websocket_client.py::_build_event_handler` | 检查 lark-oapi SDK 是否有 drive.file.edit_v1 WS 注册器；真机确认事件经 HTTP 回调到达 | 若 WS 可用则在此注册；否则保留 HTTP-only 注释为 [VERIFIED] |
| A3 | 按文件订阅端点 `POST /drive/v1/files/{file_token}/subscribe?file_type=docx`（tenant_token 鉴权，`data.code==0` 即成功）；app 即文件 owner 可订 | `server/services/feishu_doc.py::FeishuDocClient._subscribe_file_request` | 用真实凭证对一个真实 docx 调订阅，确认端点路径 + 鉴权 + 返回体；确认订阅后人工编辑能收到事件 | 回填端点/请求形态；改 [VERIFIED] |
| A5 | 回拉 blocks 每块稳定标识键为 `block_id`（改文字 id 不变）；文档 `revision` 为整型（可入 `BigIntegerField`） | `server/initiatives/services/doc_sync_service.py::_normalize_theirs_blocks` / `_pull_apply`（CAS 推进水位） | `get_document_content` 打印 raw blocks，确认 `block_id` 键名与稳定性；确认能取到整型 `revision`（当前用单调 +1 推进，未取真实 revision） | 回填 block_id 键名；若取到真实 revision，改 `_pull_apply` 用真实 revision 作 CAS 期望/新值；改 [VERIFIED] |

## 83-03（SYNC-02 Friday→飞书 block 级增量推送链路）

| ID | 契约假设 [ASSUMED] | 代码位置 | how-to-verify（真机） | 回填动作 |
|----|--------------------|----------|------------------------|----------|
| A4-update | `update_block`=PATCH `/docx/v1/documents/{document_id}/blocks/{block_id}`，请求体形如 `{"update_text_elements": {"elements": [{"text_run": {"content": ...}}]}}`，`data.code==0` 即成功 | `server/services/feishu_doc.py::FeishuDocClient.update_block` + `DocSyncService._render_block_update` | 对一个真实 docx 改一个系统区 block，确认 PATCH 端点 + 请求体（block 内容结构）+ 成功响应码 | 回填真实端点/请求体；改 [VERIFIED] |
| A4-delete | `delete_blocks`=children batch_delete：`DELETE /docx/v1/documents/{document_id}/blocks/{document_id}/children/batch_delete`，body `{"start_index": s, "end_index": e}`（删根块下 `[s,e)` 子块） | `server/services/feishu_doc.py::FeishuDocClient.delete_blocks` + `DocSyncService._push_delete`（按既有块相对位序定 index） | 按 index 范围删一个真实 block，确认端点 + index 语义（含 push 侧 index 推算是否与飞书一致）+ 响应 | 回填端点/index 语义；改 [VERIFIED] |
| A4-children | `create_children`=POST `/docx/v1/documents/{document_id}/blocks/{document_id}/children`，body `{"children": [...], "index": -1}`，返回 `data.children[].block_id`（用于落 block_map） | `server/services/feishu_doc.py::FeishuDocClient.create_children` + `DocSyncService._render_block` | 在真实 docx append 一个系统区 block，确认返回体含新建 `block_id` 的键路径 | 回填返回体解析键；改 [VERIFIED] |
| A4-codes | block 写错误码分类与 `get_document_content` 一致：限流 `99991400`、`NOT_FOUND_CODES`、`PERMISSION_CODES` | `server/services/feishu_doc.py::FeishuDocClient._raise_for_block_error` | 真机触发限流/无权限/不存在，确认 block 写 API 错误码与读 API 同集合 | 回填差异码；改 [VERIFIED] |

> A4 同组的 `add_comment`（83-04 capture 评论提示）一并 live 验证端点/请求体后回填。

## 83-04（SYNC-04 三方合并 + capture-never-clobber + 编辑感知延迟写 + 乐观并发 rebase）

| ID | 契约假设 [ASSUMED] | 代码位置 | how-to-verify（真机） | 回填动作 |
|----|--------------------|----------|------------------------|----------|
| A4-comment | `add_comment`=POST `/docx/v1/documents/{document_id}/comments`，body 含 `block_id` + `reply_list.replies[].content.elements[].text_run.text`，`data.code==0` 即成功 | `server/services/feishu_doc.py::FeishuDocClient._add_comment_request` + `DocSyncService._best_effort_comment` | 对真实 docx 的某 block 发评论，确认端点路径 + 请求体（评论内容结构）+ 成功响应码 | 回填真实端点/请求体；改 [VERIFIED]（整段 fail-soft，回填前评论失败不影响 capture/同步） |
| A5-merge-base | 三方合并 base 正文未逐块持久化（仅存 `ProjectDocBlockMap.content_hash` + 整篇 `last_synced_snapshot`）；`three_way_merge` 用「ours 指纹==base 指纹 → base 即 ours，否则占位符」驱动归并判定（仅做相等比较，base 真实正文不影响 disjoint/相交结论） | `server/initiatives/services/doc_sync_service.py::_base_for_merge` | 取到真实文档 `revision` 后，可选改为持久化逐块 base 正文做精确字符级合并（当前块级整体合并已满足 SYNC-04 capture-never-clobber 语义） | 若需字符级合并再回填逐块 base 存储；当前块级整体合并标 [VERIFIED] |

## 83-06（SYNC-06 边界/失败模式全收口 + SYNC-01 TTL 轮询兜底）

| ID | 契约假设 [ASSUMED] | 代码位置 | how-to-verify（真机） | 回填动作 |
|----|--------------------|----------|------------------------|----------|
| A3-unsubscribe | 按文件退订端点 `DELETE /drive/v1/files/{file_token}/subscribe?file_type=docx`（tenant_token 鉴权，`data.code==0` 即退订成功）；镜像 `subscribe_file`（A3）同资源 DELETE 语义 | `server/services/feishu_doc.py::FeishuDocClient._unsubscribe_file_request` | 对一个已订阅 docx 调退订，确认端点路径 + HTTP method（DELETE vs POST cancel）+ 鉴权 + 返回体；确认退订后人工编辑不再收到事件 | 回填真实端点/method/请求形态；改 [VERIFIED] |
| A5-poll-revision | TTL 轮询用回拉正文归一化指纹（`block_content_hash(markdown)`）作 revision 代理比对 `last_synced_snapshot` 指纹判漂移（真实飞书整型 `revision` 未取，与 83-02 A5 同源） | `server/tasks/doc_sync_poll.py::_check_and_defer` | 取到真实文档整型 `revision` 后，可改为直接比对 `last_synced_revision`（更精确、免回拉正文）；当前指纹代理已满足"漂移即兜底 pull、未变不 defer" | 取到真实 revision 后改 poll 用整型 revision 比对（免全文回拉）；改 [VERIFIED] |

### 83-06 备注

- TTL 兜底轮询（`tasks/doc_sync_poll.py::poll_project_docs_revisions`）：apscheduler 单实例
  `IntervalTrigger(DOC_SYNC_POLL_INTERVAL_SECONDS=120)`、`max_instances=1`；遍历进行中项目
  READY doc 比对 revision 漂移 → `defer durable_doc_sync_pull`（`lock=docsync-{feishu_document_id}`
  与 83-02 pull / 83-03 push 同文档同值，`idempotency_key=docpull:{token}:poll:{revision}` 去重）；
  归因 `system`；单 doc try/except 隔离、结构化 `{checked, triggered}` 返回。归档/broken doc
  天然被 `project__status=developing` + `sync_status=READY` gate 过滤，不被反复触发（T-83-06-DOS）。

- 边界全收口（fail-soft 不反噬主流程）：
  - 归档/终止 → pull/push 入口 gate `_stop_sync_on_archived`：best-effort `unsubscribe_file`
    释放配额 + `subscribed` 置 False（INV-6 经 ProjectDocService）+ 只读快照保留
    （`last_synced_snapshot` 不清不刷新）；记 `doc_sync_archived_stopped`(unsubscribed)。

  - 文档被删/移 → 回拉 `DocumentNotFoundError` → `set_sync_status(broken)` + 记
    `doc_sync_doc_not_found`(rebuild=rebuild_workspace) 供一键重建（复用 Phase 82 `rebuild_workspace`）。

  - 非成员飞书编辑 → operator 未映射 → 归因 `system`（contributor None，`_resolve_user` 取不到），
    fail-soft 接受不拒绝（与 83-04 受限 sync 入口一致）。

  - 飞书限流 → client `@retry` 指数退避 + per-doc 串行 lock；退避耗尽 → 记 `doc_sync_rate_limited`
    (sampling) + 返回 `failed/rate_limited`，**不置 broken**（瞬态可恢复，留下次事件/poll 兜底），
    绝不抛回 webhook / 编辑主流程。

- 均不依赖 live 飞书：退订端点（A3-unsubscribe）/ poll revision 代理（A5-poll-revision）以
  respx / fake client 覆盖单测；真机校验后回填上表。

### 83-04 备注

- 同块三方合并（base=last-synced / theirs=飞书 / ours=DB）+ capture-never-clobber：相交冲突 DB 取飞书侧 merged，落败系统侧落 `ProjectDocBlockRevision`(source=system, reason=conflict_loser)、MEMORY 非成员落 `ProjectMemoryRevision` 不进 active、飞书评论提示 best-effort；不相交自动并。
- 编辑感知延迟写（`last_feishu_edit_at` < `DOC_SYNC_ACTIVE_EDIT_WINDOW`=15s → 重排 `run_at=now+DOC_SYNC_DEFER_SECONDS`，不抢写）+ 乐观并发 rebase（CAS 推进 `last_synced_revision` 落空 → `pull` rebase 再重试，`_MAX_PUSH_REBASE_ATTEMPTS`=3 防死循环，不依赖真实 durable doing lock）均已实现并经 respx/单测覆盖，**不依赖** live 飞书。
- MEMORY 非成员飞书编辑 fail-soft 归因（OQ-1）：受限 sync 入口 `MemoryService.sync_edit`（成员落 active+revision；非成员 capture revision 不进 active，归因 system/unmapped）；前端贡献 `MemoryService.edit` 仍 MEM-02 fail-closed 不变。
- capture content 入库经 `redact_secrets_in_text`（`ProjectDocService.capture_block_revision`）；冲突/非成员日志只记 `loser_len`/`attribution` 计数，绝不记正文（T-83-04-INFO）；INV-6 写收口（`ProjectDocService`/`MemoryService`）。

### 备注

- 归因（`resolve_feishu_user(open_id)`，未映射 `system`）、durable 串行 lock（`docsync-{feishu_document_id}`）、
  幂等键（`docpull:{file_token}:{event_id}`）、fail-soft（归档/broken/not-found 跳过或置 broken 不抛）、
  脱敏（`redact_secrets_in_text`）、INV-6 写收口（ProjectDocService/MemoryService）均已实现并经
  respx/单测覆盖，**不依赖** live 飞书。

- 真三方合并冲突编排（SYNC-04）/ TTL 轮询兜底（83-06）/ 订阅退订生命周期为后续 plan，本期 pull 编辑分支以「飞书优先覆盖快照 + capture 留痕（never-drop）」+ `TODO(83-04)` 占位。
- 83-03 push：debounce 合并（`run_at=now+DOC_SYNC_DEBOUNCE_SECONDS`、`idempotency_key=docpush:{doc_id}`）、per-doc 串行 lock（`docsync-{feishu_document_id}`，与 pull/poll 同值）、限流退避（client `@retry`）、防回声（飞书镜像写 `_skip_doc_push=True`）、只写 section==SYSTEM、**永不整篇 replace**、fail-soft 置 broken、INV-6 写收口均已实现并经 respx/单测覆盖，**不依赖** live 飞书。本期系统区渲染器仅覆盖 MEMORY/STATE；MILESTONES/RESEARCH/PREFLIGHT 系统派生区渲染留后续（无渲染器即 `skipped`，绝不对空期望态盲删既有块）。编辑感知延迟写 + 乐观并发 rebase + 同块三方合并留 83-04。
