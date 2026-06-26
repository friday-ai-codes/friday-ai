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

### 备注

- 归因（`resolve_feishu_user(open_id)`，未映射 `system`）、durable 串行 lock（`docsync-{feishu_document_id}`）、
  幂等键（`docpull:{file_token}:{event_id}`）、fail-soft（归档/broken/not-found 跳过或置 broken 不抛）、
  脱敏（`redact_secrets_in_text`）、INV-6 写收口（ProjectDocService/MemoryService）均已实现并经
  respx/单测覆盖，**不依赖** live 飞书。
- 真三方合并冲突编排（SYNC-04）/ push（83-03）/ TTL 轮询兜底（83-06）/ 订阅退订生命周期为后续 plan，本期 pull 编辑分支以「飞书优先覆盖快照 + capture 留痕（never-drop）」+ `TODO(83-04)` 占位。
