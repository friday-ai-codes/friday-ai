---
phase: 29-comment-events
verified: 2026-06-15T14:30:00Z
status: human_needed
score: 12/12 must-haves verified
overrides_applied: 0
human_verification:

  - test: "用真实飞书凭证向某工作项发评论（含审批语「通过/驳回」），观察 webhook 入库 + 评论树投影"
    expected: "评论以 WorkItemCommentEvent 入库；GET work-items/comments/ 返回正确线程层级与 approval 语义；payload 字段名（comment_id/operator_id/create_time/reply_comment_id）映射正确"
    why_human: "PF-11 真实飞书评论端点正确性依赖真实凭证；webhook payload 真实字段名无法离线验证（CONTEXT deferred / human-UAT）"

  - test: "在飞书编辑/删除一条已入库评论，观察事件流是否追加 edited/deleted 事件"
    expected: "若飞书 webhook/API 提供编辑/删除信号，应追加 event_type=edited/deleted 新事件（不就地改写）；投影按最新态折叠"
    why_human: "edited/deleted 真实信号本 phase 留枚举占位（deferred）；是否可得需真实飞书环境验证（CONTEXT Grey Area 3 / deferred）"
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: human_needed
---

# Phase 29: 评论事件流 Verification Report

**Phase Goal:** append-only WorkItemCommentEvent 流式入库 + 从事件流投影当前评论树（读时计算，编辑/删除作为事件不就地改写）+ approval 语义记录。CMT-01, CMT-02。INV-3/INV-6。
**Verified:** 2026-06-15T14:30:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | WorkItemCommentEvent 表存在，可落 created/replied/edited/deleted/approval 五种事件类型 | ✓ VERIFIED | `comment_event.py` `CommentEventType` 五值；migration `0002` 建表 + 索引；`makemigrations --check`→No changes detected；模型单测绿 |
| 2 | append-only：编辑/删除是新事件行，模型层无就地改写既有行（CMT-02） | ✓ VERIFIED | 模型无 create/save 业务方法；投影 `project_comment_tree` 读时计算不写库；`test_comment_event_models` 守护 created/edited 两行并存旧行不改 |
| 3 | approval_semantic 可记 none/approve/reject，默认 none | ✓ VERIFIED | 模型 `ApprovalSemantic` 三值 + `default=NONE`；migration 默认 "none"；单测读回默认值 |
| 4 | 评论事件落库经 CommentEventService 单一 append 入口（INV-6 精神） | ✓ VERIFIED | `append_events` 为唯一收口，`ingest_comments`/`append_webhook_comment` 皆收敛于此；INV-6 grep 守护 `test_inv6_guard` 绿 |
| 5 | 重复摄取幂等：同评论多次拉取不产生重复事件 | ✓ VERIFIED | 去重锚 `(work_item, feishu_comment_id, event_type, event_time)` `get_or_create`；`test_comment_event_service` 幂等用例绿（2→0） |
| 6 | approval_semantic 由内容判定 approve/reject/none（单一来源） | ✓ VERIFIED | `classify_approval_semantic` 纯函数，reject 优先；webhook `_handle_workitem_comment` lazy import 复用同一函数（零漂移） |
| 7 | 拉取失败 comments facet 记 missing/error，不抛、不回滚 WorkItem（WIT-03） | ✓ VERIFIED | `ingest_comments` try/except + `_record_sync_state(COMMENTS, MISSING)`；`test_comment_event_service` 降配用例绿 |
| 8 | project_comment_tree 投影：编辑取最新 body、删除标记、thread_parent 组装线程、event_time 排序 | ✓ VERIFIED | `comment_projection.py` 折叠/线程/排序逻辑完整；`test_comment_projection` 8 用例绿（含只读断言） |
| 9 | webhook 评论事件后台 append CommentEvent，保留 approval/knowledge（INV-3） | ✓ VERIFIED | `_schedule_comment_append` 经 `run_in_background` 调 `append_webhook_comment`，置于 approval 处理之后无条件追加；`test_comment_entry_wiring` + `test_webhooks` 绿 |
| 10 | 缺三元组 / 缺 canonical work item → 跳过 append + warning，不抛 | ✓ VERIFIED | `_schedule_comment_append` 缺料早返回 + warning；`append_webhook_comment` 缺 work_item 返回 0；接线测试守护 |
| 11 | 最小只读 REST 端点按三元组返回当前评论树投影（IsAuthenticated） | ✓ VERIFIED | `WorkItemCommentTreeView` IsAuthenticated + 三元组校验 + 404 + `aproject_comment_tree`；`urls.py` 挂 `work-items/comments/`；`test_comment_api` 6 用例绿 |
| 12 | CommentEvent 落库只经 CommentEventService（INV-6 grep 守护，无旁路写表） | ✓ VERIFIED | `test_inv6_guard` 精确锚定 + writer 自证，全套绿 |

**Score:** 12/12 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/delivery/models/comment_event.py` | 模型 + 两枚举 | ✓ VERIFIED | 逐字段对齐 DOMAIN §12.4；无 save 业务方法 |
| `server/delivery/migrations/0002_workitemcommentevent.py` | 建表迁移 + 索引 | ✓ VERIFIED | 含 `(work_item, event_time)` 索引；`--check` 干净 |
| `server/delivery/models/__init__.py` | re-export 三项 | ✓ VERIFIED | 已加入 `__all__` |
| `server/delivery/services/comment_event_service.py` | CommentEventService + classify | ✓ VERIFIED | append/ingest/webhook + 幂等 + 降配 |
| `server/delivery/services/comment_projection.py` | project_comment_tree | ✓ VERIFIED | 读时投影 + async 包装 |
| `server/delivery/services/__init__.py` | re-export | ✓ VERIFIED | 4 项 re-export |
| `server/feishu/views.py` | webhook 接线 | ✓ VERIFIED | `_schedule_comment_append` + approval 单一来源 |
| `server/delivery/api/views.py` | CommentTreeView | ✓ VERIFIED | IsAuthenticated + 只读 |
| `server/delivery/api/serializers.py` | CommentTreeNodeSerializer | ✓ VERIFIED | 递归只读透传 dict |
| `server/delivery/urls.py` | 评论树路由 | ✓ VERIFIED | `work-items/comments/` 字面段 |

### Key Link Verification

| From | To | Via | Status |
| ---- | -- | --- | ------ |
| `comment_event.py` | `delivery.WorkItem` | FK CASCADE related_name=comment_events | ✓ WIRED |
| `comment_event_service.py` | `services.feishu.get_comments` | `_fetch_comments` 复用 Phase 27 | ✓ WIRED |
| `comment_event_service.py` | `WorkItemSyncState(facet=COMMENTS)` | `_record_sync_state` | ✓ WIRED |
| `feishu/views.py` | `CommentEventService.append_webhook_comment` | `run_in_background` lazy import | ✓ WIRED |
| `api/views.py` | `project_comment_tree` | `aproject_comment_tree` | ✓ WIRED |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| CMT-01 | 29-01/02/03 | append-only 评论事件流（含 approval），保留可追溯历史 | ✓ SATISFIED | 模型 + 单一 append 入口 + webhook/ingest 路径 + approval 语义记录 |
| CMT-02 | 29-01/02/03 | 从事件流投影当前评论树，编辑/删除作为事件不就地改写 | ✓ SATISFIED | `project_comment_tree` 读时投影 + append-only 守护 + 投影测试 |

### Behavioral Spot-Checks / Test Execution

| Check | Command | Result | Status |
| ----- | ------- | ------ | ------ |
| delivery 全套件 | `uv run pytest tests/delivery/ -q` | 90 passed | ✓ PASS |
| webhook + approval 回归 | `uv run pytest tests/test_webhooks.py tests/test_feishu_approval_integration.py -q` | 15 passed, 1 xfailed | ✓ PASS |
| migration 干净 | `manage.py makemigrations --check --dry-run` | No changes detected | ✓ PASS |

> 全程 respx mock + pytest-socket 零真实网络。已知与本 phase 无关的 `tests/knowledge/test_triggers.py` 预存失败未计入。

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
| ---- | ------- | -------- | ------ |
| (none) | — | — | 未发现 TBD/FIXME/XXX 调试标记或 stub；edited/deleted 为有意枚举占位（CONTEXT deferred，docstring 注明），非未实现 stub |

### Human Verification Required

1. **真实飞书评论端点正确性（PF-11）** — 用真实凭证发评论，验证 webhook 入库 + 评论树投影 + payload 字段名映射。无法离线验证。
2. **edited/deleted 真实信号** — 在飞书编辑/删除评论，验证是否追加 edited/deleted 事件。本 phase 留枚举占位（deferred），需真实环境确认信号可得性。

### Gaps Summary

无阻断性 gap。12/12 可观察 truth 在代码中验证通过，CMT-01/CMT-02 兑现，INV-3/INV-6 守护就位，全套自动化测试绿、迁移干净。剩余两项为 CONTEXT 明确标注的 human-UAT / deferred 项（真实飞书端点正确性、edited/deleted 真实信号），按要求计为 human_needed，非 gap。

---

_Verified: 2026-06-15T14:30:00Z_
_Verifier: Claude (gsd-verifier)_
