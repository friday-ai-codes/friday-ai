---
phase: 83
slug: feishu-doc-bi-sync-engine
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-26
---

# Phase 83 — Validation Strategy

> 飞书文档双向同步引擎的逐阶段验证契约（执行期反馈采样）。来源：83-RESEARCH.md「Validation Architecture」。

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9 + pytest-asyncio + pytest-django；飞书外呼用 `respx`（httpx mock）；网络隔离 `pytest-socket` |
| **Config file** | `server/pyproject.toml`（`[tool.pytest...]`） |
| **Quick run command** | `cd server && uv run pytest tests/initiatives/test_doc_sync_diff.py tests/initiatives/test_doc_sync_conflict.py -x` |
| **Full suite command** | `cd server && uv run pytest tests/initiatives tests/feishu tests/durable -q` |
| **Estimated runtime** | ~30–90 秒（纯函数核心快；含 DB/respx 用例稍长） |

---

## Sampling Rate

- **After every task commit:** Run `cd server && uv run pytest tests/initiatives/test_doc_sync_diff.py tests/initiatives/test_doc_sync_conflict.py -x`
- **After every plan wave:** Run `cd server && uv run pytest tests/initiatives tests/feishu tests/durable -q`
- **Before `$gsd-verify-work`:** Full suite must be green + `python manage.py makemigrations --check`（若扩字段）+ INV-6 守护
- **Max feedback latency:** 90 秒

---

## Per-Task Verification Map

> Wave 列与已提交 PLAN frontmatter 的 `wave`/`depends_on` 对齐（1-indexed，与 ROADMAP 一致）：W1=83-01∥83-05；W2=83-02（依赖 01/05）；W3=83-03（依赖 02）；W4=83-04（依赖 02/03）；W5=83-06（依赖 02/03/04）。83-03 与 83-04 不同波（83-04 depends_on 含 83-03）。

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 83-01-* | 01 | 1 | SYNC-03/04 | — | 纯函数 diff/三方合并无 IO | unit | `pytest tests/initiatives/test_doc_sync_diff.py -x` | ❌ W0 | ⬜ pending |
| 83-05-* | 05 | 1 | SYNC-05 | — | redis 不可用降级直读 DB | unit | `pytest tests/initiatives/test_doc_sync_cache.py -x` | ❌ W0 | ⬜ pending |
| 83-02-* | 02 | 2 | SYNC-01 | T-83-02-SPOOF | 飞书签名校验 + ProcessedEvent 幂等 + 统一 lock=docsync-{feishu_document_id} | unit | `pytest tests/feishu/test_drive_event_route.py -x` | ❌ W0 | ⬜ pending |
| 83-03-* | 03 | 3 | SYNC-02 | T-83-03-CLOBBER / -DOS | push 只发 block 级增量，永不整篇 replace（respx 断言无全量 PUT）；lock=docsync-{feishu_document_id} 与 pull/poll 同 | unit | `pytest tests/initiatives/test_doc_sync_push.py -x` | ❌ W0 | ⬜ pending |
| 83-04-* | 04 | 4 | SYNC-03/04 | T-83-04-CLOBBER | 三方合并 capture-never-clobber；乐观并发 rebase | unit | `pytest tests/initiatives/test_doc_sync_conflict.py tests/initiatives/test_doc_sync_rebase.py -x` | ❌ W0 | ⬜ pending |
| 83-06-* | 06 | 5 | SYNC-01/06 | T-83-06-DOS / -TAMPER | not-found→broken 重建；归档停同步退订；非成员编辑 fail-soft 归因；限流退避；poll lock=docsync-{feishu_document_id} | unit | `pytest tests/initiatives/test_doc_sync_boundaries.py tests/initiatives/test_doc_sync_poll.py -x` | ❌ W0 | ⬜ pending |
| test_project_doc_inv6_guard | 01 | 1 | INV-6 | — | ProjectDoc/BlockMap/StateApi/BlockRevision 写入只经 ProjectDocService | guard | `pytest tests/initiatives/test_project_doc_inv6_guard.py -x` | ✅ exists（83-01 扩 _MODELS） | ⬜ pending |
| test_doc_sync_inv6_guard | 02 | 2 | INV-6 | — | doc_sync_service.py 不旁路写表（经 ProjectDocService/MemoryService） | guard | `pytest tests/initiatives/test_doc_sync_inv6_guard.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/initiatives/test_doc_sync_diff.py` — 纯函数 block diff + 三方合并（无 IO，覆盖 SYNC-03/04 核心）
- [ ] `tests/initiatives/conftest.py` — ProjectDoc/BlockMap/ProjectMemory + respx 飞书 mock fixtures
- [ ] `tests/feishu/test_drive_event_route.py` — drive 事件 normalizer + durable defer mock（SYNC-01）
- [ ] `tests/initiatives/test_doc_sync_inv6_guard.py` — grep 守护（仿 `test_memory_inv6_guard`/`test_project_doc_inv6_guard`）

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `drive.file.edit_v1` 事件真实字段（file_token/operator_id/event_id） | SYNC-01 | 飞书 API 形态需真机验证（A1 ASSUMED） | 订阅真实 docx → 人工编辑 → 抓 webhook/WS 原始 payload（`record_inbound_webhook` 已落库可查）确认字段 |
| 按文件 subscribe / unsubscribe 端点 | SYNC-01 | 飞书订阅端点未在本仓接入（A3 ASSUMED） | live 注册/退订真实文档，确认端点 + 鉴权 |
| 增量 update_block / delete_blocks 请求体 | SYNC-02 | 仅验证过 children/descendant 写（A4 ASSUMED） | live 改/删真实 block，确认端点 + 请求体 + 错误码 |
| 回拉 blocks 的 block_id 稳定性 + 文档级 revision 形态 | SYNC-03 | 结构化匹配/rebase 依赖（A5 ASSUMED） | live 编辑后回拉，打印 raw 结构确认 block_id 不变 + revision 为整型 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
