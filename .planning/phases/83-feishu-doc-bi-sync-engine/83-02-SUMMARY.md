# 83-02 SUMMARY — drive.file.edit_v1 订阅 + 路由 + 回拉 pull pipeline（SYNC-01）

**Status:** 完成（live-Feishu 检查点 PASSED-with-deferred-live-verification，见 83-UAT.md）

## 交付

打通飞书→Friday 拉取链路：飞书编辑 docx → `drive.file.edit_v1` 经现有 webhook 入口路由 →
归因（`resolve_feishu_user`，未映射 `system`）→ durable `durable_doc_sync_pull` 回拉正文 →
`doc_sync_diff` 结构化分类 → 写收口（MEMORY 经 `MemoryService` / 其余经 `ProjectDocService`）→
CAS 推进 `last_synced_revision` → 失效渲染缓存。handler 不阻塞回拉（取材在后台）；per-doc 串行
lock 统一 `docsync-{feishu_document_id}`（与 83-03 push / 83-06 poll 一致）；全链路 fail-soft。

## 文件改动

**新增**
- `server/initiatives/services/doc_sync_service.py` — `DocSyncService.pull`（回拉 + diff + 写收口 + CAS + 失效缓存 + fail-soft + 归因 + MEMORY 独立 sync 路径 `_skip_member_check`/非成员 capture）
- `server/tests/feishu/test_drive_event_route.py` — normalizer + handler defer mock 单测（7）
- `server/tests/initiatives/test_doc_sync_inv6_guard.py` — DocSyncService 不旁路写表守护（4）
- `server/tests/initiatives/test_doc_sync_pull.py` — respx mock 回拉流水线/归因/编辑 capture/fail-soft（6）
- `.planning/phases/83-feishu-doc-bi-sync-engine/83-UAT.md` — A1/A2/A3/A5 deferred 清单

**修改**
- `server/durable/queues.py` — `QUEUE_DOC_SYNC = "doc_sync"`（+ ALL_QUEUES/__all__）
- `server/durable/tasks.py` — `durable_doc_sync_pull` procrastinate 包壳
- `server/durable/tasks_impl.py` — `run_doc_sync_pull`（worker 入口 `bind_task_context(component="doc_sync")`）
- `server/durable/handlers.py` — in-process fallback 注册 `durable_doc_sync_pull`
- `server/services/feishu_doc.py` — `FeishuDocClient.subscribe_file`（A3 [ASSUMED]，fail-soft 返回 bool）
- `server/feishu/views.py` — `drive.file.edit_v1` 路由分支 + `_handle_drive_file_edit` + `_normalize_drive_edit_event`
- `server/feishu/websocket_client.py` — WS register A2 [ASSUMED] 注释（HTTP-only）
- `server/initiatives/services/project_doc_service.py` — `advance_sync_revision`（CAS）+ `clear_block_map`（INV-6 白名单 writer）；provision 建文件后按文件 `subscribe_file`（fail-soft）

## 测试

- `pytest tests/feishu/test_drive_event_route.py tests/initiatives tests/durable -q` → **246 passed, 13 deselected**（postgres_queue）。
- 含 INV-6 双守护（`test_doc_sync_inv6_guard` + `test_project_doc_inv6_guard`）全绿；ruff 通过。
- provision 回归（`test_project_doc_service.py`）零回归（subscribe 接线不破坏既有断言）。

## 关键决策 / 偏离

- **drive 路由位置**：drive 事件不携带 `project_key`、走开放平台标准 schema（`header`+`event`），
  若进入看板项目解析分支会被「缺 space_key」提前拒。故路由分支置于 idempotency 检查之后、
  project 解析之前（按 `event_type` 直接处理），并传完整 `data` 给 normalizer 防御性取字段。
  与 plan「event_type 块加 elif」意图一致（按 event_type 路由），位置为正确性必要调整。
- **CAS 水位**：`get_document_content` 暂不返回飞书 revision（A5 待 live），本期用 `expected+1`
  单调推进 + 条件 update 实现乐观并发（Pitfall 3），不依赖 durable doing 锁。
- **MEMORY OQ-1**：飞书新增块经 `MemoryService.append(_skip_member_check=True)`（独立 sync 路径，
  保持 MEM-02 对前端贡献仍 fail-closed）；编辑块成员可改、非成员/异常 → `capture_block_revision`
  留痕（never-drop）。真三方合并留 `TODO(83-04)`。
- **subscribe 接线**：plan Task 1 仅要求加 `subscribe_file` 方法；按用户任务把它接入 provision
  建文件后的 best-effort 订阅（bool 强制 + fail-soft，不破坏 Phase 82 provision 测试）。

## [ASSUMED] 契约（deferred 至 83-UAT.md，无 live 飞书凭证）

- **A1** `drive.file.edit_v1` 事件字段名（`file_token`/`operator_id_list[0].open_id`/`event_id`）。
- **A2** WS 长连是否支持 `register_p2_drive_file_edit_v1`（当前 HTTP-only）。
- **A3** 按文件订阅端点 `POST /drive/v1/files/{file_token}/subscribe?file_type=docx`。
- **A5** 回拉 block 稳定标识键 `block_id` + 文档 `revision` 整型形态。

## 后续

- 83-03 push（block 级增量 + debounce + 编辑感知延迟写 + rebase）；83-04 真三方合并冲突编排；
  83-06 TTL 轮询兜底 + 订阅退订生命周期。
