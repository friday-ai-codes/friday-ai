# 83-04 执行总结 — 三方合并 + capture-never-clobber + 编辑感知延迟写 + 乐观并发 rebase

**Plan:** 83-04-PLAN.md（SYNC-03/04）
**Status:** ✅ 完成（live-Feishu 契约项 deferred，见 83-UAT.md A4-comment / A5-merge-base）
**Date:** 2026-06-26

## 交付内容

把「防冲突」从机制承诺落成可测代码：pull 同块冲突走真三方合并接管 83-02 的 TODO，push 前插编辑感知延迟写 + 乐观并发 rebase 两道 gate，保证「用户在飞书编辑中系统写入绝不冲掉用户内容」。

### Task 1 — capture-never-clobber 落点 + MEMORY 受限 sync 入口 + pull 三方合并接管

- `ProjectDocService.capture_block_revision`：content 入库前 `redact_secrets_in_text` 脱敏（T-83-04-INFO）；新增 `touch_feishu_edit(doc_id, *, at)`（更新 `last_feishu_edit_at`，编辑感知探测源 OQ-3）。
- `MemoryService.sync_edit`：飞书镜像编辑受限入口（OQ-1）——成员落 active + revision（飞书优先，旧态留 revision 链）；非成员**不抛**、把飞书内容 append 为 `ProjectMemoryRevision` 留痕但**不进 active**，归因 `system`/`unmapped`。前端贡献 `MemoryService.edit` 仍 MEM-02 fail-closed 不变。
- `DocSyncService` pull：把 83-02 pull edit TODO 替换为三方合并——
  - 非 MEMORY：解析 ours（STATE 按 db_ref 渲染 `ProjectStateApi`）→ `three_way_merge(base/theirs=飞书/ours=DB)`；相交冲突 DB 取飞书侧 merged、落败系统侧 `capture_block_revision`(source=system, reason=conflict_loser) + best-effort 飞书评论；不相交自动并不产 revision；ours 不可解析退回 83-02「飞书优先 + 留痕」（never-drop）。
  - MEMORY：走 `sync_edit`；非成员 capture 不进 active + 归因日志 `doc_nonmember_edit_captured` + 评论；异常兜底 capture 飞书内容。
  - base 正文未逐块持久化 → `_base_for_merge` 用「ours 指纹==base 指纹 → base 即 ours，否则占位符」驱动归并（`three_way_merge` 仅相等比较，块级整体合并满足 capture-never-clobber）。

### Task 2 — push 编辑感知延迟写 + 乐观并发 rebase + 飞书评论

- gate ①（编辑感知延迟写，OQ-3）：`_is_active_edit`（距 `last_feishu_edit_at` < `DOC_SYNC_ACTIVE_EDIT_WINDOW`=15s 判活跃）→ `_defer_push` 重排 `defer(... run_at=now+DOC_SYNC_DEFER_SECONDS=10s, lock=docsync-{document_id}, key=docpush:{doc_id})` 后返回 `deferred`，**绝不抢写 block**。
- gate ②（乐观并发 rebase，Pitfall 3）：`_push_with_rebase` —— `_push_apply` 内 CAS 推进 `last_synced_revision` 落空（并发改过）→ `self.pull` rebase + 重读最新水位/重渲染 → 重试，`_MAX_PUSH_REBASE_ATTEMPTS`=3 防死循环；不依赖真实 durable doing lock。
- `FeishuDocClient.add_comment`（+ `_add_comment_request`）：镜像 `subscribe_file` 的 fail-soft 包壳（限流 @retry 退避，失败返回 False 绝不抛），A4 [ASSUMED]。

## 修改文件

- `server/initiatives/services/project_doc_service.py` — capture 脱敏 + `touch_feishu_edit`
- `server/initiatives/services/memory_service.py` — `sync_edit` 受限入口 + `_capture_sync_revision_locked`
- `server/initiatives/services/doc_sync_service.py` — pull 三方合并接管 + push 两道 gate（编辑感知延迟 + rebase）+ 评论/归因/冲突日志
- `server/services/feishu_doc.py` — `add_comment` / `_add_comment_request`
- `server/tests/initiatives/test_doc_sync_conflict.py`（新）— 三方合并 capture-never-clobber + 非成员 fail-soft 归因 + 脱敏 + 前端 fail-closed
- `server/tests/initiatives/test_doc_sync_rebase.py`（新）— 编辑感知延迟写 defer + revision 漂移 rebase + 有限重试防死循环
- `.planning/phases/83-feishu-doc-bi-sync-engine/83-UAT.md` — 83-04 [ASSUMED]（A4-comment / A5-merge-base）

## 测试结果

- `tests/initiatives/test_doc_sync_conflict.py` + `test_doc_sync_rebase.py` + `test_doc_sync_inv6_guard.py`：**14 passed**
- `tests/initiatives tests/durable`：**269 passed**（无回归）
- ruff：All checks passed

## LOCKED 遵守

- 复用 83-01 `three_way_merge`（base/theirs/ours，飞书优先）+ 83-02/03 service；capture-never-clobber 绝不静默丢；编辑感知延迟写（活跃则 defer）；乐观并发 rebase（CAS 落空先 pull，不依赖 doing lock）；INV-6 写收口（`ProjectDocService`/`MemoryService`，guard 绿）。

## Deferred（live-Feishu，不阻断）

- A4-comment：`add_comment` 端点/请求体 live 验证后回填 [VERIFIED]（整段 fail-soft）。
- A5-merge-base：取到真实文档 `revision` 后可选改逐块 base 精确字符级合并（当前块级整体合并已满足 SYNC-04）。
