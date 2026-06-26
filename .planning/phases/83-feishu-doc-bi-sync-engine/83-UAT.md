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

### 备注

- 归因（`resolve_feishu_user(open_id)`，未映射 `system`）、durable 串行 lock（`docsync-{feishu_document_id}`）、
  幂等键（`docpull:{file_token}:{event_id}`）、fail-soft（归档/broken/not-found 跳过或置 broken 不抛）、
  脱敏（`redact_secrets_in_text`）、INV-6 写收口（ProjectDocService/MemoryService）均已实现并经
  respx/单测覆盖，**不依赖** live 飞书。
- 真三方合并冲突编排（SYNC-04）/ TTL 轮询兜底（83-06）/ 订阅退订生命周期为后续 plan，本期 pull 编辑分支以「飞书优先覆盖快照 + capture 留痕（never-drop）」+ `TODO(83-04)` 占位。
- 83-03 push：debounce 合并（`run_at=now+DOC_SYNC_DEBOUNCE_SECONDS`、`idempotency_key=docpush:{doc_id}`）、per-doc 串行 lock（`docsync-{feishu_document_id}`，与 pull/poll 同值）、限流退避（client `@retry`）、防回声（飞书镜像写 `_skip_doc_push=True`）、只写 section==SYSTEM、**永不整篇 replace**、fail-soft 置 broken、INV-6 写收口均已实现并经 respx/单测覆盖，**不依赖** live 飞书。本期系统区渲染器仅覆盖 MEMORY/STATE；MILESTONES/RESEARCH/PREFLIGHT 系统派生区渲染留后续（无渲染器即 `skipped`，绝不对空期望态盲删既有块）。编辑感知延迟写 + 乐观并发 rebase + 同块三方合并留 83-04。
