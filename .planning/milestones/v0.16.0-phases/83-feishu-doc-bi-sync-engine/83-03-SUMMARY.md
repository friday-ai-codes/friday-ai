# 83-03 SUMMARY — SYNC-02 Friday→飞书 block 级增量推送

**Plan:** 83-03 · **Wave:** 3 · **Requirement:** SYNC-02 · **Status:** done（checkpoint = PASSED-with-deferred-live-verification）

## 交付内容

DB **系统区**写 → debounce 合并 → per-doc 串行 → 飞书 **block 级增量**推送（children 新增 / update_block 改 / delete_blocks 删），**永不整篇 replace**；限流退避、防回声、fail-soft 全程不反噬。

链路：`ProjectDocService.upsert/remove_state_api` / `MemoryService.append/edit/supersede`（系统区写）→ `schedule_doc_push`（先解析 `feishu_document_id` → `DurableTaskService.defer("durable_doc_sync_push", {"doc_id"}, lock=docsync-{feishu_document_id}, idempotency_key=docpush:{doc_id}, run_at=now+DEBOUNCE)`）→ `run_doc_sync_push`（bind_task_context component=doc_sync）→ `DocSyncService.push`（系统区期望态 → `diff_blocks` 比对 block_map(section=system) → children/update/delete 增量外呼 → `upsert_block_map`/`clear_block_map` + CAS `advance_sync_revision` → 失效缓存）。

## 文件改动

| 文件 | 改动 |
|------|------|
| `server/services/feishu_doc.py` | 新增 `FeishuDocClient.update_block`（PATCH）/`create_children`（children, 返回新 block_id）/`delete_blocks`（batch_delete by index）+ `_raise_for_block_error` 错误码分类，全部 `@retry` 退避，永不整篇 |
| `server/initiatives/services/doc_sync_service.py` | 新增 `push` + `_push_apply`/`_push_one`/`_push_delete` + 系统区渲染（MEMORY/STATE）+ `_load_system_block_rows`(仅 SYSTEM) + `_render_block`/`_render_block_update` + push 日志；MEMORY 镜像写 `_skip_doc_push=True` 防回声 |
| `server/initiatives/services/doc_push_scheduler.py`（新增） | `schedule_doc_push` + `DOC_SYNC_DEBOUNCE_SECONDS=5`（系统区写后 debounce defer push，共用 lock，fail-soft） |
| `server/initiatives/services/memory_service.py` | append/edit/supersede 加 `_skip_doc_push` 形参 + 系统区写后 `_schedule_doc_push`（MEMORY） |
| `server/initiatives/services/project_doc_service.py` | `upsert_state_api`/`remove_state_api` 加 STATE 系统区写后 `schedule_doc_push` |
| `server/durable/tasks.py` | `durable_doc_sync_push` 包壳（queue=QUEUE_DOC_SYNC） |
| `server/durable/tasks_impl.py` | `run_doc_sync_push` 任务体（bind_task_context） |
| `server/durable/handlers.py` | 注册 in-process `durable_doc_sync_push` handler |
| `server/tests/initiatives/test_doc_sync_push.py`（新增） | 24 条 respx 单测 |

## LOCKED 约束落地

- **永不整篇 replace**：仅 PATCH/children/batch_delete；测试 `_assert_no_full_replace` 显式断言无 PUT、所有外呼打在 `/blocks/` 或 token 端点。
- **debounce 合并**：`run_at=now+DEBOUNCE` + `idempotency_key=docpush:{doc_id}`（同 doc 多次写合并一份 todo）。
- **per-doc 串行**：`lock=docsync-{feishu_document_id}`，单测断言严格等于 pull（83-02）/poll（83-06）同文档值。
- **复用 83-01/83-02**：push 复用 `diff_blocks`（按 db_ref 键）+ 续写在同一 `DocSyncService`。
- **INV-6**：push 写 block_map/水位经 `ProjectDocService`，无旁路写表（`test_doc_sync_inv6_guard` 绿）。
- **只写系统区**：`_load_system_block_rows` 仅 `section==SYSTEM`，人工区不进 diff/不被删。
- **防误删**：无渲染器（MILESTONES/RESEARCH/PREFLIGHT）→ `skipped`，绝不对空期望态盲删既有块。

## 测试结果

- `tests/initiatives/test_doc_sync_push.py` + `test_doc_sync_inv6_guard.py`：**24 passed**。
- 回归 `tests/initiatives tests/durable`：**259 passed, 13 deselected**。
- ruff check 全绿；新增 LLM 调用点 = 无。mypy：仅 1 处**预存**（83-02 pull `diff_blocks` 入参 invariance，HEAD 既有），本计划**零新增** mypy 错误。

## [ASSUMED] 延迟 live 验证（记入 83-UAT.md）

飞书 block 写端点/请求体/响应（A4：`update_block` PATCH、`delete_blocks` children batch_delete by index、`create_children` 返回 block_id、错误码集合）按 MILESTONE-PROPOSAL §10 + 既有 `feishu_doc.py` 约定实现 + respx mock 覆盖；真机验证后 `[ASSUMED]`→`[VERIFIED]` 回填。checkpoint 按 **PASSED-with-deferred-live-verification** 继续。

## 后续（不在本计划）

编辑感知延迟写 + 乐观并发 rebase + 同块三方合并 + `add_comment` 评论提示（83-04）；TTL 轮询兜底（83-06）；MILESTONES/RESEARCH/PREFLIGHT 系统派生区渲染。
