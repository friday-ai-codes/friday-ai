---
phase: 29-comment-events
reviewed: 2026-06-15T14:40:00Z
depth: deep
files_reviewed: 13
files_reviewed_list:
  - server/delivery/models/comment_event.py
  - server/delivery/models/__init__.py
  - server/delivery/migrations/0002_workitemcommentevent.py
  - server/delivery/services/comment_event_service.py
  - server/delivery/services/comment_projection.py
  - server/delivery/services/__init__.py
  - server/delivery/api/views.py
  - server/delivery/api/serializers.py
  - server/delivery/urls.py
  - server/feishu/views.py
  - server/tests/delivery/test_inv6_guard.py
  - server/tests/delivery/test_comment_event_service.py
  - server/tests/delivery/test_comment_projection.py
findings:
  critical: 0
  warning: 2
  info: 3
  total: 5
status: clean
resolution:
  fixed: [WR-01, WR-02]
  deferred: [IN-01, IN-02, IN-03]
  resolved_at: 2026-06-15T15:10:00Z
---

# Phase 29: Code Review Report

**Reviewed:** 2026-06-15T14:40:00Z
**Depth:** deep
**Files Reviewed:** 13
**Status:** clean（两项 Warning 已修复，三项 Info 经评估 deferred）

## Resolution（2026-06-15 修复回填）

- **WR-02 已修复**：`WorkItemCommentEvent` 增 DB 级唯一约束 `uniq_comment_event_anchor`
  （迁移 `0003`），`append_events` 捕获并发竞态 `IntegrityError` 视作"已追加"，幂等在
  并发/跨路径下由 DB 兜底。新增测试覆盖重复直插 IntegrityError + 同锚预存在 append 返回 0。
- **WR-01 已修复**：`_schedule_comment_append` 改为按候选键有序探测评论 id
  （`comment_id` / `comment_id_str` / `comm_id`，刻意排除顶层 `id`=work_item_id），全缺时
  显式 `comment_append_missing_comment_id` warning 且 fail-soft 投递；代码注释标注真实键名
  仍需 live-Feishu 人工验证（PF-11）。新增备选键命中 + 全缺 warning 两条测试。
- **Info 全部 deferred（不阻塞，理由如下）**：
  - **IN-01**（author 跨路径语义不一致）：属字段建模取舍，本 phase 不扩 `author_id`/`author_name`
    字段；webhook/拉取 author 表示差异为已知限制，留待后续统一。
  - **IN-02**（重拉不反映 body 编辑）：符合 CONTEXT "edited 信号 deferred" 取舍，预期内行为，
    待真实 edited 信号可得时再接入。
  - **IN-03**（评论树 REST 无分页）：性能项，不在 v1 review 正确性范围，当前评论量级无需处理。

## Summary

评论事件流（CMT-01/CMT-02）的核心不变量基本守住：append-only 没有就地改写（模型层无业务写、投影 `project_comment_tree` 读时计算且测试断言行数不变）；INV-6 单一写入入口由 grep 守护测试覆盖（含 `WorkItemCommentEvent` 旁路写表扫描）；INV-3 webhook 既有 approval/knowledge 投递保留并有守护；approval 语义抽成 `classify_approval_semantic` 单一判定来源，reject 优先取向与 webhook 一致；凭证脱敏复用 28-02 `_redact_secrets`，`SyncState.error` 落库前抹凭证并有测试断言；降配（缺 project / 缺 work_item / 回源失败）不抛不回滚 WorkItem，测试覆盖完整。

无 Critical 级缺陷（无崩溃、无凭证泄漏、无 INV 破坏）。两项 Warning 均关乎"幂等去重 / webhook 接线在真实环境是否真正生效"——投影按 `feishu_comment_id` 归并，使读出的评论树在大多数异常下仍正确，但事件行层面的幂等性在并发/跨路径下不被保证，且 webhook 取评论 id 的字段名未经真实 payload 校验。

## Warnings

### WR-01: webhook 评论 id 取自未校验的 payload 字段，缺失则整条 webhook 评论被静默丢弃

**File:** `server/feishu/views.py:922`
**Issue:** `_schedule_comment_append` 用 `comment_id = str(payload.get("comment_id") or "")` 取去重锚所需的 `feishu_comment_id`。代码库其他处理评论的逻辑（`_handle_workitem_comment`）只读 `payload.get("id")`（work item id）与 `payload.get("comment")`（正文），并无任何证据表明飞书评论 webhook payload 含 `comment_id` / `reply_comment_id` / `operator_id` / `create_time` 这些字段。若飞书实际不提供 `comment_id`，则 `comment_id=""` → `append_events` 命中 "缺 feishu_comment_id 跳过" 分支（`comment_event_service.py:107`）→ **每条 webhook 评论都被静默跳过，29-03 webhook append 路径在生产中实为空操作**。代码本身防御正确（跳过而非写脏数据），但 CMT-01 的 webhook 入库目标可能未真正达成。这与 PF-11（评论端点真实正确性需人工验收）相关，但 webhook payload 形状是可在接线前确认的。
**Fix:** 在真实飞书评论 webhook payload 上确认评论 id / 父评论 id / 时间戳 / 操作人字段的真实键名，校正 `payload.get(...)` 的键；并补一条"webhook payload 缺 comment_id"的显式 warning 日志（区别于 service 内的 `comment_event_skip_missing_id`），便于生产侧发现接线失效：

```python
comment_id = str(payload.get("comment_id") or "")
if not comment_id:
    logger.warning("comment_append_missing_comment_id", work_item_id=work_item_id)
    # 仍可投递（service 会跳过），但日志显式暴露字段名不匹配
```

### WR-02: 去重锚无 DB 级唯一约束，并发 / 跨路径摄取可产生重复事件行（幂等仅顺序保证）

**File:** `server/delivery/services/comment_event_service.py:128`, `server/delivery/migrations/0002_workitemcommentevent.py:14`
**Issue:** 去重靠 `WorkItemCommentEvent.objects.get_or_create(work_item, feishu_comment_id, event_type, event_time, ...)`，但模型/迁移**只建了 `(work_item, event_time)` 普通索引，没有对去重锚 `(work_item, feishu_comment_id, event_type, event_time)` 的唯一约束**。`get_or_create` 在无 DB 唯一约束时存在 check-then-insert 竞态（Django 官方明确警示），两条后台任务（webhook append 与 `ingest_comments` 经 `run_in_background` 并发，或同评论的多条 webhook 快速到达）可双双判定"不存在"→ 各插一行，产生重复事件。此外去重锚含 `event_time`：webhook 用 `create_time`、拉取用评论 `created_at`，**同一评论经两条路径若时间戳不完全相等则锚不同 → 重复行**。Review 焦点明确把"concurrent/repeated ingest 的幂等正确性"列为关注点，当前实现只在**顺序、同源**下幂等（已有测试覆盖），并发/跨路径不保证。

缓解：`project_comment_tree` 按 `feishu_comment_id` 归并，重复行会折叠回单节点，故**读出的评论树不被污染**——这把影响从"正确性"降为"事件表膨胀 + `appended` 计数不准 + 事件流审计含冗余行"，因此定为 Warning 而非 Blocker。
**Fix:** 为去重锚加 DB 级唯一约束，让 `get_or_create` 在并发下落到唯一索引兜底（Django 会捕获 IntegrityError 并回退到 get）：

```python
class Meta:
    constraints = [
        models.UniqueConstraint(
            fields=["work_item", "feishu_comment_id", "event_type", "event_time"],
            name="uniq_comment_event_anchor",
        ),
    ]
```

注意：`event_time` 可空，Postgres 下 NULL 互不相等，对 `event_time IS NULL` 的事件唯一约束不生效——可考虑 `event_time` 缺失时用稳定占位（或对 NULL 走 `UniqueConstraint(..., condition=Q(event_time__isnull=False))` + 单独的 NULL 分支处理）；至少跨路径应统一时间戳来源以减少锚漂移。

## Info

### IN-01: author 跨摄取路径语义不一致（webhook 用 operator_id，拉取用作者名）

**File:** `server/feishu/views.py:923`
**Issue:** webhook 路径 `author = str(payload.get("operator_id") or payload.get("author") or "")` 落入的是**用户 id**；而拉取路径经 `parse_comments` 落入的是 `author.name`（人类显示名，`feishu_parsing.py:531`）。同一作者经两条路径产生不同 author 值，下游展示/统计会出现"同人两名"。
**Fix:** 统一 author 表示（都存 id 或都存显示名，或拆 `author_id` / `author_name` 两字段）；本 phase 若不扩字段，至少在 docstring 标注该不一致为已知限制。

### IN-02: 内容编辑在重拉时被去重静默丢弃，投影 body 可能过期

**File:** `server/delivery/services/comment_event_service.py:128`
**Issue:** service 当前只合成 created/replied/approval，从不产 `edited`。若用户改了评论正文但 approval 语义/线程父/飞书 `created_at` 均未变，重拉时去重锚完全相同 → `get_or_create` 命中既有行、`defaults` 里的新 `body` 被忽略 → 投影继续展示**旧正文**。这符合 CONTEXT "edited 信号 deferred" 的取舍，但当前路径下"重拉不反映编辑"是个易被误解的隐含行为。
**Fix:** 属预期内 deferred 行为，建议在 `append_events` docstring 显式注明"同锚重拉不更新 body（edited 待真实信号）"，避免后续误判为 bug。

### IN-03: 评论树 REST 端点无分页，全量加载工作项全部评论事件

**File:** `server/delivery/api/views.py:128`, `server/delivery/services/comment_projection.py:44`
**Issue:** `project_comment_tree` 一次性 `list(...filter(work_item=...))` 取出该 work item 全部事件并在内存投影，REST 端点无上限/分页。评论量极大的工作项会一次性载入。（性能问题不在 v1 review 范围，仅作信息项记录，因其不构成正确性缺陷。）
**Fix:** 后续若评论量级上来，可对投影加上限或按线程分页；当前规模无需处理。

---

_Reviewed: 2026-06-15T14:40:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
