---
phase: 28-workitem-spine
verified: 2026-06-15T05:25:00Z
status: passed
score: 14/14 must-haves verified
overrides_applied: 0
re_verification: # No — initial verification
gaps: []
deferred:
  - truth: "bitable_import / mr_reverse 真实调用方接入"
    addressed_in: "Phase 31 / Phase 32"
    evidence: "CONTEXT Grey Area 7 / Deferred Ideas：本 phase 仅 origin 枚举 + upsert 接受 source；真实调用方归 Phase 31（Bitable）/ Phase 32（MR 反查）"
  - truth: "writeback 字段真实写回飞书流程"
    addressed_in: "later phase"
    evidence: "CONTEXT Deferred Ideas：writeback 留接口位，本 phase 不实现写回（feishu_chat_id mirror 字段已就位但无写回流程）"
  - truth: "prd_body / tech_doc / comments facet 正文摄取"
    addressed_in: "Phase 29 / Phase 30"
    evidence: "CONTEXT Grey Area 4 / Deferred：评论 facet 归 Phase 29、正文 facet 归 Phase 30；本 phase 有意记 missing 不假装 complete"
---

# Phase 28: WorkItem 脊柱 + 单一 upsert 入口 Verification Report

**Phase Goal:** 新建 delivery app，立起 canonical WorkItem + WorkItemService.upsert 单一写入入口（INV-6）+ 三分类刷新（mirror/friday_enhanced/writeback）+ per-facet WorkItemSyncState + WorkItemRelation 派生+占位 + append-only WorkItemStatusEvent。INV-1（三元组唯一）、INV-3（knowledge 投影不被取代）。
**Verified:** 2026-06-15T05:25:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth (来源 Plan) | Status | Evidence |
| --- | --- | --- | --- |
| 1 | delivery app 注册 INSTALLED_APPS，Django 可加载、makemigrations 无报错 (28-01) | ✓ VERIFIED | `server/friday/settings.py:111` `"delivery"`；`makemigrations --check --dry-run` → `No changes detected` |
| 2 | 同三元组唯一一行 WorkItem（DB unique_together 强制 INV-1）(28-01) | ✓ VERIFIED | `work_item.py:82` `unique_together=((feishu_project_key, work_item_type, work_item_id),)`；test_models 重复创建抛 IntegrityError（通过） |
| 3 | WorkItem 字段四组齐备逐项对齐 DOMAIN §12.1 (28-01) | ✓ VERIFIED | `work_item.py:35-76`：mirror（title/status_*/feishu_fields/prd_url/tech_doc_url/is_archived/is_init）、friday_enhanced（business_line/module/internal_note）、writeback（feishu_chat_id）、元数据（field_provenance/last_synced_at/event_time）全在 |
| 4 | SyncState/Relation/StatusEvent 三表含 §12.2/12.3/12.4 字段+choices+unique_together (28-01) | ✓ VERIFIED | `sync_state.py`（facet/status/source choices + unique(work_item,facet)）、`relation.py`（target_external_id 占位 + 四元 unique_together）、`status_event.py`（pre/cur + index(work_item,event_time)） |
| 5 | migrate 后建出 delivery 四张表 (28-01) | ✓ VERIFIED | `0001_initial.py` 存在；makemigrations 干净（已 migrate）；38 个 DB 测试运行通过即证表存在 |
| 6 | upsert 唯一写入入口；同三元组多次/跨 origin 收敛同一行 WIT-01 (28-02) | ✓ VERIFIED | `work_item_service.py` `_get_or_create_locked` select_for_update + origin 仅首次落；test_work_item_service / test_entry_wiring 跨入口收敛测试通过 |
| 7 | 只刷 mirror，friday_enhanced 被保护 WIT-02 (28-02) | ✓ VERIFIED | `_MIRROR_FIELDS` 白名单（service:52-62）；`_refresh_mirror` 显式 update_fields 不含 enhanced/writeback；测试守护通过 |
| 8 | per-facet SyncState（basic_fields/relations）；facet 失败不回滚整体 WIT-03 (28-02) | ✓ VERIFIED | 各 `_record_sync_state` 独立 sync_to_async（独立事务）；回源失败记 MISSING+error 不回滚；测试通过 |
| 9 | 从关联字段派生 Relation，目标未落库 target_external_id 占位 WIT-04 (28-02) | ✓ VERIFIED | `_apply_relations` 复用 `derive_relations_from_fields` + update_or_create + 反向回填；占位/回填测试通过 |
| 10 | 状态变更 append StatusEvent(pre/cur)，非就地改写 WIT-05 (28-02) | ✓ VERIFIED | `_refresh_mirror` 先 append StatusEvent 后改 mirror（service:211-222）；无变更不 append；测试通过 |
| 11 | REST 端点按三元组 manual upsert + 读取（IsAuthenticated）(28-03) | ✓ VERIFIED | `api/views.py` Upsert/Detail View，`permission_classes=[IsAuthenticated]`；`urls.py` + `friday/urls.py:64` 挂载；test_api 6 测试通过 |
| 12 | webhook 工作项事件后台调 upsert(feishu_webhook)，跨入口收敛 WIT-01 (28-03) | ✓ VERIFIED | `feishu/views.py` `_schedule_delivery_upsert` 在 create/status/update 三 handler 接线（L824/867/974）；test_entry_wiring 通过 |
| 13 | INV-6 守护：除 WorkItemService 外无旁路 WorkItem 写表 (28-03) | ✓ VERIFIED | `test_inv6_guard.py` 源码扫描 + 自证 writer 确含写表（精确正则锚定）；2 测试通过 |
| 14 | INV-3 守护：未改 knowledge、webhook ingestion 保留 (28-03) | ✓ VERIFIED | 三 handler 保留 `aschedule_ingestion`（L815/858/964）；guard 断言 delivery 不写 knowledge.models；2 测试通过 |

**Score:** 14/14 truths verified

### Deferred Items

Items not in scope this phase — explicitly addressed in later milestone phases (per CONTEXT).

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | bitable_import / mr_reverse 真实调用方 | Phase 31 / 32 | CONTEXT Grey Area 7：本 phase 仅 origin 枚举 + upsert 接受 source |
| 2 | writeback 真实写回飞书 | later phase | CONTEXT Deferred：留接口位（feishu_chat_id 字段就位，无写回流程） |
| 3 | prd_body/tech_doc/comments facet 正文摄取 | Phase 29 / 30 | CONTEXT Grey Area 4：本 phase 有意记 missing |

### Key Link Verification

| From | To | Via | Status |
| --- | --- | --- | --- |
| `friday/settings.py` | delivery app | INSTALLED_APPS 追加 `"delivery"` | ✓ WIRED (L111) |
| `friday/urls.py` | `delivery.urls` | `include("delivery.urls")` | ✓ WIRED (L64) |
| `work_item_service.py` | `services/feishu.py get_work_item` | fetch 回源 | ✓ WIRED (`_fetch` → `client.get_work_item`) |
| `work_item_service.py` | `services/feishu_parsing.py` | 复用 derive_relations/extract_prd/tech_doc | ✓ WIRED (import L41-45) |
| `feishu/views.py` | `WorkItemService.upsert` | `run_in_background` 后台 upsert | ✓ WIRED (L796-799, 三 handler) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| migrations 干净 | `makemigrations --check --dry-run` | No changes detected | ✓ PASS |
| delivery 全套测试 | `pytest tests/delivery/ -q` | 38 passed | ✓ PASS |
| webhook 接线未破坏既有 ingestion (INV-3) | `pytest tests/test_webhooks.py -q` | 8 passed, 1 xfailed | ✓ PASS |
| knowledge 触发回归 | `pytest tests/knowledge/test_triggers.py -q` | 43 passed, 1 failed (pre-existing, unrelated) | ✓ PASS (见下) |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| WIT-01 | 28-01/02/03 | 三元组幂等收敛唯一 canonical（INV-1） | ✓ SATISFIED | unique_together + 跨入口收敛测试 |
| WIT-02 | 28-01/02 | 只经 upsert，mirror/enhanced/writeback 三分类刷新 | ✓ SATISFIED | _MIRROR_FIELDS 白名单 + 保护测试 |
| WIT-03 | 28-01/02 | per-facet SyncState，部分失败不回滚 | ✓ SATISFIED | 独立事务 + 回源失败测试 |
| WIT-04 | 28-01/02 | 关联字段派生 Relation + target_external_id 占位 | ✓ SATISFIED | _apply_relations + 占位/回填测试 |
| WIT-05 | 28-01/02 | append-only StatusEvent | ✓ SATISFIED | 先 append 后改 mirror + 测试 |

REQUIREMENTS.md Traceability 表已标 WIT-01..05 = Complete / Phase 28，与 PLAN frontmatter requirements 一致，无 orphaned。

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
| --- | --- | --- | --- |
| — | 无未引用的 TBD/FIXME/XXX；无空实现 stub；prd_body/tech_doc/comments 记 missing 为有意设计（非 stub） | ℹ️ Info | 无阻塞 |

### Human Verification Required

无。本 phase 为后端数据层 / service / REST + webhook 接线，全部可观察行为均由自动化测试覆盖（IntegrityError 守护、respx mock 回源、mirror 保护、占位/回填、状态 append、INV-6 源码扫描、跨入口收敛）。无视觉/UX/实时交互需人工验证项。

### Gaps Summary

无 gap。14/14 must-have 全部 VERIFIED，5 条需求（WIT-01..05）全部 SATISFIED，38 个 delivery 测试通过，迁移干净，webhook 回归未破坏既有 knowledge ingestion（INV-3）。

唯一失败测试 `tests/knowledge/test_triggers.py::TestCodingTriggers::test_coding_chat_pr_created_branch_delivers_once` 为任务说明中明确标注的**预存在、与本 phase 无关**的 coding-trigger（PR-created 分支投递）失败，不计入本 phase。bitable_import/mr_reverse 真实调用方与 writeback 写回按 CONTEXT 显式延后至后续 phase，不计为 gap。

---

_Verified: 2026-06-15T05:25:00Z_
_Verifier: Claude (gsd-verifier)_
