---
phase: 29-comment-events
plan: 03
subsystem: delivery-wiring
tags: [django, delivery, comment-event, webhook, adrf, rest, inv-6, inv-3, background-runner, respx, pytest-django]

# Dependency graph
requires:
  - phase: 29-comment-events (plan 02)
    provides: CommentEventService.append_webhook_comment / classify_approval_semantic / project_comment_tree(+async)
  - phase: 28-workitem-spine
    provides: WorkItem 三元组身份 + delivery REST/webhook 接线范式（run_in_background / IsAuthenticated / INV-6 grep 守护）
provides:
  - 飞书 webhook 评论事件后台 append CommentEvent 接线（_schedule_comment_append，approval 复用单一来源）
  - 评论树只读 REST 端点 WorkItemCommentTreeView（IsAuthenticated，按三元组投影）
  - CommentTreeNodeSerializer 递归只读序列化器
  - INV-6 评论旁路写表 grep 守护（WorkItemCommentEvent 落库仅经 CommentEventService）
affects: [32 ING 拉取编排, 34 评论入图/反查, v0.7 approval 触发再生成]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "webhook 评论接线沿用 Phase 28 _schedule_delivery_upsert 范式：只投三元组+文本，后台 run_in_background best-effort append，缺料跳过+warning"
    - "approval 关键词单一判定来源 classify_approval_semantic 收口 webhook（is_approved/is_rejected 由 semantic 推导，零行为漂移）"
    - "评论树只读 REST 复用 WorkItemDetailView 三元组校验范式，投影经 aproject_comment_tree（sync_to_async）"
    - "INV-6 评论守护复用 Phase 28 精确锚定 grep（.objects.<write>/实例化/.save + writer 自证），case-sensitive 天然区分事件字符串 WorkitemCommentEvent"

key-files:
  created:
    - server/tests/delivery/test_comment_api.py
    - server/tests/delivery/test_comment_entry_wiring.py
  modified:
    - server/feishu/views.py
    - server/delivery/api/serializers.py
    - server/delivery/api/views.py
    - server/delivery/urls.py
    - server/tests/delivery/test_inv6_guard.py

key-decisions:
  - "approval 判定收口单一来源：_handle_workitem_comment 改为 classify_approval_semantic 推导 is_approved/is_rejected（option a），避免关键词在 webhook 与 service 漂移；既有 FeishuApprovalHandler 行为零回归"
  - "评论 append 在 approval/knowledge 处理之后无条件追加（approval 与否皆记录评论事件，CMT-01）；webhook 主响应不被后台 append 阻塞"
  - "REST 直接用 CommentTreeNodeSerializer 递归序列化 dict 投影（event_time → ISO），只读不旁路 fetch/落库"
  - "comment_id 不臆造：payload 不提供则空 → append_events 跳过+warning（缺去重锚）；author/created_at/thread_parent_id 取可得字段"

patterns-established:
  - "webhook 多投影并存接线：同一 handler 内 approval + knowledge ingestion + delivery comment append 三者 ADD-only 并存（INV-3）"

requirements-completed: [CMT-01, CMT-02]

# Metrics
duration: ~20min
completed: 2026-06-15
---

# Phase 29 Plan 03: 评论事件流接线 + REST + INV-6 守护 Summary

**把 29-02 评论事件流接到两条真实入口：① 飞书 webhook `_handle_workitem_comment` 在保留既有 approval（复用单一判定 `classify_approval_semantic`）+ knowledge 投影（INV-3）的同时，经 `run_in_background` 后台 `append_webhook_comment` 追加 CommentEvent（缺三元组/缺评论跳过+warning）；② 只读 REST `WorkItemCommentTreeView`（IsAuthenticated）按三元组返回 `project_comment_tree` 投影（含线程层级 + approval 语义，不旁路 fetch/落库）；并补 INV-6 评论旁路写表 grep 守护（精确锚定 + writer 自证）——delivery+approval 全套 97 passed，无回归。**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-06-15
- **Tasks:** 3
- **Files created/modified:** 7

## Accomplishments

### Task 1 — webhook 评论事件后台 append
- `server/feishu/views.py _handle_workitem_comment`：approval 判定改为复用 29-02 `classify_approval_semantic`（lazy import），`is_approved = semantic == "approve"` / `is_rejected = semantic == "reject"`——既有 `FeishuApprovalHandler` 调用与 `approved = is_approved and not is_rejected` 取向零行为漂移（关键词单一来源）。
- 新增 `_schedule_comment_append(project, payload)`：沿用 `_schedule_delivery_upsert` 范式，lazy import `CommentEventService` + `run_in_background`，构造 `WorkItemIdentity` 后 best-effort 后台 `append_webhook_comment(source="feishu_webhook")`；缺 `work_item_type_key`/`work_item_id`/`comment` → 跳过 + warning（不构造身份，沿用 INV-1 占位类型分裂防护）。
- 在 approval 处理之后**无条件**追加 append（approval 与否皆记录评论事件，CMT-01）；payload 仅取可得字段（comment_id/author/created_at/thread_parent_id），缺失留空/None 不臆造。
- INV-3：既有 knowledge ingestion / approval handler 完全保留，评论 append 仅 ADD 其后并存。

### Task 2 — 评论树只读 REST 端点
- `serializers.py` 新增 `CommentTreeNodeSerializer`：递归只读透传投影 dict（feishu_comment_id/author/body/event_type/approval_semantic/is_deleted/event_time/thread_parent_id/children），`event_time` 经 `DateTimeField` ISO 序列化，`children` 自引用递归。
- `api/views.py` 新增 `WorkItemCommentTreeView(APIView, IsAuthenticated)`：复用 `WorkItemDetailView` 三元组校验（缺参→400、非整数→400）→ `afirst` 取已落库 WorkItem（不存在→404，只读不旁路 fetch）→ `aproject_comment_tree` 投影 → 返回 `{"work_item_id", "comments"}` 200。
- `urls.py` 新增字面段 `work-items/comments/`（`name="work-item-comment-tree"`，置于 `work-items/` 之前，不冲突）。

### Task 3 — INV-6 评论旁路写表 grep 守护
- `tests/delivery/test_inv6_guard.py` 追加评论守护：精确锚定 `WorkItemCommentEvent.objects.<create|bulk_create|get_or_create|update_or_create>` / 实例化 `WorkItemCommentEvent(` / `WorkItemCommentEvent(...).save(`；排除 tests//migrations//delivery/models/ 与唯一 writer `comment_event_service.py`；命中报 文件:行。case-sensitive 天然区分事件字符串 `WorkitemCommentEvent`（小写 i），零误伤。
- writer 自证：断言 `comment_event_service.py` 确含 `WorkItemCommentEvent.objects.<write>`（守护非空转）。
- INV-3 扩展：断言 `feishu/views.py` 评论 handler 仍保留 `FeishuApprovalHandler` + 新增 `append_webhook_comment` 接线并存；delivery app 不写 knowledge 模型（既有守护覆盖 comment_event_service.py）。

## Task Commits

1. **Task 1: webhook 评论事件后台 append + approval 单一来源** - `70de5dea` (feat)
2. **Task 2: 评论树只读 REST 端点** - `e2fced7d` (feat)
3. **Task 3: INV-6 评论旁路写表 grep 守护** - `257663fa` (test)

## Files Created/Modified
- `server/feishu/views.py` - `_handle_workitem_comment` approval 单一来源 + `_schedule_comment_append` 后台接线
- `server/delivery/api/serializers.py` - `CommentTreeNodeSerializer`（递归只读）
- `server/delivery/api/views.py` - `WorkItemCommentTreeView`（IsAuthenticated）
- `server/delivery/urls.py` - `work-items/comments/` 只读路由
- `server/tests/delivery/test_comment_entry_wiring.py` - 4 个接线守护测试
- `server/tests/delivery/test_comment_api.py` - 6 个 REST 守护测试
- `server/tests/delivery/test_inv6_guard.py` - 追加 2 个评论 INV-6 守护 + INV-3 评论接线断言

## Decisions Made
- **approval 单一来源（option a）**：直接把 webhook 既有关键词识别替换为 `classify_approval_semantic` 推导，而非另起 append 路径独立判定——彻底消除两处关键词漂移风险，且 reject 优先与既有 `approved = is_approved and not is_rejected` 取向一致（互斥推导后等价）。
- **评论 append 无条件追加**：放在 approval if-块之后、handler 末尾，确保所有评论（含非 approval）都进事件流（CMT-01），而非仅 approval 评论。
- **REST 直接序列化 dict 投影**：`CommentTreeNodeSerializer` 递归处理已materialize 的 dict 树（非 ORM），`event_time` 统一 ISO；轻量、显式形状、无需在 view 手工转 datetime。
- **comment_id 不臆造**：payload 不提供 comment_id 则传空 → `append_events` 按"缺去重锚跳过+warning"处理，而非用 work_item_id 等兜底（避免错误去重锚把不同评论折叠/重复事件膨胀）。

## Deviations from Plan
None - plan executed exactly as written（approval 单一来源取 plan 优先项 option a）。

## Issues Encountered
None.

## Verification Results
- `pytest tests/delivery/test_comment_entry_wiring.py -x -q` → **4 passed**。
- `pytest tests/delivery/test_comment_api.py -q` → **6 passed**。
- `pytest tests/delivery/test_inv6_guard.py -q` → **6 passed**（含 2 个新增评论守护）。
- `pytest tests/delivery/ tests/test_feishu_approval_integration.py -q` → **97 passed**（无 28/29-01/02 回归；approval 集成零回归）。
- `ruff check delivery/ feishu/views.py tests/delivery/` → All checks passed；改动文件 `ruff format` 干净（既有 `tests/delivery/test_work_item_service.py` 的格式差异系 Phase 28 遗留，超出本 plan 范围未触）。
- 全程 respx mock + pytest-socket 零真实网络；未改 knowledge app（INV-3）；未新增第三方依赖。

## Threat Mitigations Verified
- **T-29-07（EoP 评论树 REST）**：`permission_classes=[IsAuthenticated]`，`test_comment_tree_unauthenticated_rejected` 守护 401/403；只读端点不旁路 fetch/落库，`test_comment_tree_is_read_only` 守护 GET 前后事件行数不变。
- **T-29-08（Tampering 旁路写表）**：INV-6 grep 守护 `test_inv6_no_bypass_comment_event_write` + writer 自证 `test_inv6_comment_writer_module_actually_writes`。
- **T-29-09（Spoofing 伪造 webhook）**：复用既有 `FeishuWebhookView` token 校验；append 只取三元组+文本，canonical work_item 须已落库否则 service 内跳过。
- **T-29-10（DoS 后台 append 阻塞主响应）**：`run_in_background` 脱离请求生命周期 best-effort；缺料跳过 `test_schedule_comment_append_skips_incomplete_identity` 守护。
- **T-29-11（Integrity knowledge 被改）**：INV-3 守护 `test_inv3_feishu_ingestion_projection_preserved`（approval handler + ingestion + comment append 并存）+ `test_inv3_delivery_does_not_write_knowledge_models`。

## Known Stubs
None - webhook 接线与 REST 均接通真实数据流（append 经 CommentEventService 单一收口，投影经 project_comment_tree）。真实飞书评论 payload 字段名（comment_id/operator_id/create_time/reply_comment_id）正确性 PF-11 仍依赖真实凭证 human-UAT，per CONTEXT。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 评论"webhook 入库 → 事件流投影 → REST 只读消费"闭环就位（CMT-01/CMT-02 可观察兑现）。
- Phase 32 ING 可调 `ingest_comments` 拉取式摄取；Phase 34 评论入图/反查、v0.7 approval 触发再生成可消费 approval 事件边界。

## Self-Check: PASSED
- FOUND: server/tests/delivery/test_comment_api.py
- FOUND: server/tests/delivery/test_comment_entry_wiring.py
- FOUND: server/feishu/views.py (_schedule_comment_append / append_webhook_comment)
- FOUND: server/delivery/api/views.py (WorkItemCommentTreeView)
- FOUND: server/delivery/urls.py (work-items/comments/)
- FOUND: commit 70de5dea
- FOUND: commit e2fced7d
- FOUND: commit 257663fa

---
*Phase: 29-comment-events*
*Completed: 2026-06-15*
