---
phase: 83
plan: 06
type: summary
status: complete
requirements: [SYNC-01, SYNC-06]
---

# 83-06 SUMMARY — TTL 轮询兜底 + 边界/失败模式全收口（fail-soft）

## 目标达成

交付 SYNC-06 边界/失败模式全集 + 强化 SYNC-01 漏事件兜底，**全部 fail-soft 绝不反噬主流程**：

1. **TTL 兜底轮询**（SYNC-01 强化）：apscheduler 单实例 job 周期遍历进行中项目 READY doc，
   比对飞书 revision 漂移即 `defer durable_doc_sync_pull`，兜底订阅/事件丢失。
2. **边界全收口**（SYNC-06）：归档→停同步+退订+只读快照；not-found→broken+一键重建；
   非成员→归因 system fail-soft；限流→退避不置 broken；redis down→降级直读 DB（复用 83-05）。

## 文件改动

| 文件 | 改动 |
|------|------|
| `server/friday/settings.py` | NEW `DOC_SYNC_POLL_INTERVAL_SECONDS=120` |
| `server/tasks/doc_sync_poll.py` | NEW `poll_project_docs_revisions() -> {checked, triggered}`（进行中项目 READY doc 比对 revision→defer pull，单 doc try/except 隔离，归因 system） |
| `server/agents/management/commands/runapscheduler.py` | NEW `poll_project_docs_revisions_job`(@_with_scheduler_log_context) + `add_job(IntervalTrigger, max_instances=1, replace_existing=True)` |
| `server/services/feishu_doc.py` | NEW `unsubscribe_file()` + `_unsubscribe_file_request()`（镜像 subscribe_file，fail-soft 布尔，A3 [ASSUMED]） |
| `server/initiatives/services/doc_sync_service.py` | pull/push 入口归档 gate→`_stop_sync_on_archived`（退订+subscribed=False+只读快照）；not-found→broken+`_log_doc_not_found`（rebuild 入口）；限流→`_log_rate_limited`(sampling) **不置 broken**；helper `_mark_broken_soft` |
| `server/tests/initiatives/test_doc_sync_poll.py` | NEW 轮询单测（漂移→defer/lock/key/system、未变不 defer、归档+broken 不进 poll、单 doc 异常隔离） |
| `server/tests/initiatives/test_doc_sync_boundaries.py` | NEW 边界单测（not-found→broken+rebuild、归档→停同步+unsubscribe+只读、退订失败 fail-soft、非成员→system、限流→不 broken） |
| `.planning/phases/83-feishu-doc-bi-sync-engine/83-UAT.md` | 追加 83-06 [ASSUMED]（A3-unsubscribe / A5-poll-revision）+ 备注 |

## 关键设计决策

- **lock 三处统一**：poll→pull 与事件→pull、push 对同一 `feishu_document_id` 共用
  `lock=docsync-{feishu_document_id}` 串行；poll 用 `idempotency_key=docpull:{token}:poll:{revision}`
  去重（断言严格相等）。
- **revision 代理**：真机整型 revision 未取（A5），poll 用回拉正文归一化指纹
  `block_content_hash(markdown)` 比对 `last_synced_snapshot` 指纹判漂移（[ASSUMED]，真机回填）。
- **限流瞬态不置 broken**：限流是可恢复的，置 broken 会停后续同步（T-83-06-DOS）；改为记
  `doc_sync_rate_limited`(sampling) + 保留 READY 待下次事件/poll 兜底。这是相对 83-02/03 的
  行为微调（permanent 错误仍置 broken）。
- **归档退订幂等**：仅 `subscribed && feishu_document_id` 才退订并标 `subscribed=False`，避免对
  已停同步 doc 反复退订；只读快照 = DB 保留 `last_synced_snapshot` 不刷新（由 gate skip 保证）。
- **broken/归档 doc 天然不进 poll**：`project__status=developing` + `sync_status=READY` 过滤，
  不被反复触发 pull。

## 观测埋点

- `doc_sync_poll_started/_completed`（caller, +checked/triggered/duration_ms, initiated_by=system）
- `doc_sync_poll_no_drift` / `doc_sync_poll_drift_deferred` / `doc_sync_poll_doc_failed`（sampling，高频纪律）
- `doc_sync_archived_stopped`（caller, unsubscribed） / `doc_sync_unsubscribe_failed`（caller）
- `doc_sync_doc_not_found`（caller, rebuild=rebuild_workspace） / `doc_sync_rate_limited`（sampling）
- `feishu_file_unsubscribe` / `feishu_file_unsubscribe_failed`（caller）
- 全部仅记 doc_id/doc_type/计数/op，**绝不**记 token/正文（INV-6 guard `test_doc_sync_service_logs_no_token_plaintext` 绿）。

## 测试结果

- `tests/initiatives/test_doc_sync_poll.py`（4）+ `test_doc_sync_boundaries.py`（6）+ `test_doc_sync_inv6_guard.py`：全绿。
- Phase gate `tests/initiatives tests/feishu tests/durable`：**316 passed, 13 deselected**。
- `makemigrations --check --dry-run`：No changes detected（干净，无模型改动）。
- ruff（6 改动文件）：All checks passed；scheduler/poll/client 导入无错，`DOC_SYNC_POLL_INTERVAL_SECONDS=120`。

## [ASSUMED] deferred（真机验证记 83-UAT.md）

- **A3-unsubscribe**：退订端点 `DELETE /drive/v1/files/{file_token}/subscribe?file_type=docx`（镜像 A3 subscribe）。
- **A5-poll-revision**：poll 用正文指纹代理 revision 比对漂移（真机取整型 revision 后可改直接比对 `last_synced_revision`，免全文回拉）。

## 验收对照（LOCKED）

- [x] TTL poll 兜底漏事件（进行中项目），单实例，归因 system，单条隔离 fail-soft。
- [x] 所有边界 fail-soft 不反噬：归档→停同步+退订+只读快照；not-found→broken+一键重建；非成员→system；限流→退避不 broken；redis down→降级 DB（83-05）。
- [x] broken/归档 doc 不被 poll 反复触发；poll→pull 与事件→pull 经同 lock + idempotency 幂等。
- [x] 复用既有 scheduler/durable/cache/service；INV-6 写收口（ProjectDocService/MemoryService）。
