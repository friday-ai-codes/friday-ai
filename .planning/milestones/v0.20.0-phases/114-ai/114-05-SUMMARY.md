---
phase: 114-ai
plan: 05
requirements: [FLOW-07, CLAR-03, CLAR-04]
provides:
  - "**七端点** `artifacts/<uuid:artifact_id>/blueprint-review/`：GET 快照 / POST `approve/` / `reject/` / `edit-blocks/` / `threads/<uuid:thread_id>/answer/` / **`threads/<uuid:thread_id>/resolve/`** / **`threads/<uuid:thread_id>/dismiss/`**，`name` 为 `blueprint-review-{snapshot,approve,reject,edit-blocks,thread-answer,thread-resolve,thread-dismiss}`"
  - "`bump_revision_round(content) -> tuple[dict, int]` 纯函数（`deepcopy` 后改，**入参不被原地修改**，恒不抛；缺 `meta` / `meta` 非 dict / 旧值非 int 或负数一律按 0 起算）"
  - "`aapprove_blueprint(artifact, *, user=None, initiated_by_user_id='system', session=None, lifecycle_service=None) -> dict` —— 恒定三键 `{status, detail, current_status}`，`status ∈ {confirmed, blocked, conflict, invalid}`"
  - "`areject_blueprint(artifact, *, user=None, comment='', anchor=None, initiated_by_user_id='system', session=None, artifact_service=None, lifecycle_service=None) -> dict` —— 恒定七键 `{status, version_id, version_no, revision_round, thread_id, detail, current_status}`，`status ∈ {rejected, unchanged, invalid, conflict}`"
  - "⭐ `aresolve_finding(thread, *, reason, user=None, initiated_by_user_id='system', lifecycle_service=None) -> dict` / `adismiss_finding(...)` —— 恒定三键 `{status, thread_id, detail}`，`status ∈ {resolved, dismissed, invalid, noop}`；`reason` **必填非空**（空 → `invalid` 且不落库）"
  - "⭐ `aremind_clarification_threads(*, hours=None, now=None, limit=100, initiated_by_user_id='system') -> dict` —— 恒定四键 `{scanned, due, reminded, skipped}`"
  - "`BlueprintThread.last_reminded_at`（可空 `DateTimeField`）+ 全相位**唯一一条** migration `delivery/0033_blueprintthread_last_reminded_at`（单个 `AddField`，依赖 `0032_blueprint_context_entry`）"
  - "`tasks/blueprint_reminder_tasks.aremind_blueprint_clarifications() -> dict[str, int]` 调度壳 + `runapscheduler.remind_blueprint_clarifications_job` wrapper 与一个 `add_job` 注册块（`IntervalTrigger(hours=1)` / `max_instances=1`）"
  - "`blueprint_quality` 三项 DB 统计实装（**同步签名不变**）：`ai_rejection_rate` / `human_edit_volume`（`produced_by_ref__startswith='human_edit:'`）/ `clarification_rounds`；三项**无数据返 `None` 而非 0**"
  - "`produced_by_ref` 第四前缀 `REJECT_PREFIX = 'blueprint_review_reject:'`（与 114-04 的 `human_edit:` / `ai_review_reflow:` / `human_block_restore:` 并列，构成四前缀全集）"
  - "`add_reviewer` 的 `first_action` 取值追加：`review_approve` / `review_reject` / `finding_resolve` / `finding_dismiss` / `thread_answer`（`block_edit` 由 114-04 提供）"
affects:
  - "115（查看器/数据面）：快照端点已给出 findings 分级分组（每条带 `thread_id`）、失锚列表、未决 BLOCKER 清单与 `revision_round`，可直接消费；`blueprint-review/` 与 `blueprint-gate/` 前缀区分阶段 4 与阶段 1"
  - "115/116（通知面）：提醒只记 `blueprint_clarification_reminded` caller 事件并写周期锚点，**渠道投递留给通知面消费**——本相位不新建推送通道、不新增事件常量"
  - "⭐ 全相位：超界出口不再死锁（B2 出口就位）；`aapply_thread_answers` 获得第二个生产调用方（answer 端点）"
key-files:
  created:
    - server/delivery/api/blueprint_review_views.py
    - server/delivery/services/blueprint_review_action.py
    - server/delivery/migrations/0033_blueprintthread_last_reminded_at.py
    - server/tasks/blueprint_reminder_tasks.py
    - server/tests/delivery/test_blueprint_review_views.py
    - server/tests/test_blueprint_pending_reminder.py
  modified:
    - server/delivery/urls.py
    - server/delivery/models/blueprint_thread.py
    - server/delivery/services/blueprint_lifecycle_service.py
    - server/services/process_runtime/blueprint_quality.py
    - server/system/models.py
    - server/agents/management/commands/runapscheduler.py
    - server/tests/services/test_blueprint_quality.py
completed: 2026-07-31
---

# Phase 114 Plan 05: 人审操作面与度量面闭环（相位收口）Summary

**一行结论**：新建 `blueprint_review_views.py`（七端点）与 `blueprint_review_action.py`（六入口），把「AI 审查超界后人审只能驳回、永远无法通过」这条**自带死锁**的出口打通——`resolve/` 与 `dismiss/` 经 `resolve_thread` 把 finding 推到终态，离开 114-01 confirm 守卫判据②的集合，approve 随之放行；死锁解除由一条**全程经真实 REST 端点**的端到端用例证伪（含「只处置一条仍 409」的反向对照），并经**三处变异实测**坐实证伪能力（处置改用作答通道 / 统计换错字段 / 短路周期锚点，各自使对应用例转红）。`blueprint_quality` 三项 DB 统计首次实装且逮住了 111 遗留的 A2 字段名偏差。全相位**恰好一条** migration（`0033`，单个 `AddField`），`makemigrations --check` 退出码 **0**；全量 `pytest tests/ -q` **8507 passed / 1 failed**，唯一失败项是与本 plan 无关的 worktree 环境项 `test_skills_snapshot_guard`（与 114-03 收官时**同一条**，零新增失败）。

## Accomplishments

- **⭐ 超界死锁被打通，且解锁路径可证伪（B2，本 plan 最贵的一条）**。114-03 轮次用尽后蓝图落 `pending_review` 并留下未决 BLOCKER finding，而 114-01 的 confirm 守卫把 `status ∈ {open, answered}` 的 blocker finding 一律判为「不可确认」——**没有处置通道时人审只能驳回**。新增两端点经 `resolve_thread(dismissed=False/True)` 落终态解开它。头号用例 `test_over_bound_deadlock_is_released_only_after_all_blockers_are_disposed` 走完整链路：approve **409**（响应体带未决 `thread_id` 清单）→ 经 `reverse("blueprint-review-thread-resolve")` 处置一条 → **仍 409**（反向对照：放行确由「全部清空」驱动，不是端点副作用）→ 经 `-thread-dismiss` 处置另一条 → approve **200** 且 DB 重读 `confirmed`。
  - ⛔ **绝不用作答通道处置**：`record_answer` 只把线程推到 `answered`，而 `answered` 仍在判据②里。**变异 A 实测**：把处置换成作答通道后，死锁用例与「重复处置不覆盖首次结论」用例**双双转红** —— 这条纪律不是声明，是被测试挡住的。
- **approve 零 TOCTOU，有源码与行为双证**。视图只调 service 并按 `status` 映射码；`aunresolved_blocker_count` 仅用于 GET 快照与 **409 响应体的呈现**（告诉人审「去处置这几条」——那正是死锁的解药入口），绝不作为前置判据。源码扫描断言 View 函数体内不含预查询；行为侧在**守卫查询发生的那一刻**插入一条 `open+blocking` finding，approve 仍 409 且 DB 状态未变（对照组 200 ⇒ 断言非恒真）。114-01 立的 `test_no_out_of_transaction_blocker_check_before_confirm`（扫 `delivery/api/` 全目录）继续绿。
- **reject 先落版本再转状态，`revision_round` 首写可靠**。三步链每次都**重读** current content（不接受调用方传入 content），连续两次驳回各 +1、不会连加两次或不加。半成功状态（版本已落但 CAS 冲突）如实带 `version_no` 回 409，**绝不静默**。
- **⭐ answer 端点让答案真的落地（B1）**。`record_answer` 之后**同一请求内**调 114-04 的 `aapply_thread_answers`（`section_writer` 不传 ⇒ 走生产实现）：断言版本 **+1**、新版本 `decision_log` 含该 `thread_id` 条目且带 `applied_in_version`、线程 DB 重读 `resolved`。**两条对照锁死「不静默」**：回灌返 `noop` 时端点仍 200、版本不变、线程停在 `answered`、`reflow.status == "noop"`；回灌**抛异常**时端点**仍 200**（作答已持久化、不回滚、不回 5xx）且 `reflow.status == "failed"`。
- **⭐ 提醒有真实周期路径（B4）**。判据状态口径是 `needs_clarification`（对齐 SC-4，**不是** `pending_review`——后者是「等人审决策」，提醒它只会制造噪声），正反并列用例锁死该定夺。到期锚点 `last_reminded_at or created_at`，提醒后一次 `bulk_update` 写回（**显式带 `updated_at`**，`bulk_update` 绕过 `auto_now`）。挂**既有 apscheduler** 加一个 job：tick 间隔（每小时）与提醒周期（可配 `pending_reminder_hours`）**分层**，热改周期无需重启 scheduler。**变异 C 实测**：短路周期锚点写回后三条提醒用例转红 ⇒ 「同周期不重复轰炸」确实靠它成立。
- **⭐ 三项统计逮住了 111 的 A2 字段名偏差**。`ArtifactVersion` **没有** `created_by_user_id`：照 111 docstring 写会直接 `FieldError`，而若「绕开」改按别的用户字段过滤则**指标恒为零而测试看起来全绿**。实装用 `produced_by_ref__startswith="human_edit:"`，并把三态并列成用例（无版本 → `None` / 有版本零人工 → `0` / 两条人工版本 → `2`）。**变异 B 实测**：把字段换掉后「有值」用例转红而「零值」用例仍绿——正是那个陷阱的形状，两条并列才逮得住。
- **观测合规**：本 plan 新增的 15 条结构化事件全部带 `category` + `component`，关键生命周期带 `duration_ms`。日志只记 `artifact_id` / `thread_id` / 计数 / `reason_len` 等标量与关联键——**评论正文、block 正文、答案正文、处置理由正文、澄清问题正文一律不进日志**（T-114-36）；异常与上游文本走 `redact_secrets_in_text`。
- **顺带修掉相位的观测欠账**（见下方「携带缺陷修复」）。

## Task Commits

| Task | Commit | 内容 |
| ---- | ------ | ---- |
| 0（携带缺陷） | `6f91f778` | `blueprint_transition_event_persist_failed` 补 `category` / `component` + 异常文本脱敏 |
| 1 | `a0868a9b` | `blueprint_review_action.py` 六入口 + `last_reminded_at` 字段与 `0033` migration + 提醒调度壳 + apscheduler 一个 job + 配置键注释 |
| 2 | `e12cd3f9` | `blueprint_review_views.py` 七端点 + `urls.py` 七条路由 + `blueprint_quality` 三项统计实装 |
| 3 | `bf95cb0b` | 三个测试文件（35 + 15 + 18 = 68 例）+ 三处变异验证 |

## Files

- `server/delivery/api/blueprint_review_views.py`（新建，七端点）
- `server/delivery/services/blueprint_review_action.py`（新建，六入口 + 一纯函数）
- `server/delivery/migrations/0033_blueprintthread_last_reminded_at.py`（新建，**全相位唯一**）
- `server/tasks/blueprint_reminder_tasks.py`（新建，调度壳）
- `server/tests/delivery/test_blueprint_review_views.py`（新建，29 个 `def test_` → **35 例**）
- `server/tests/test_blueprint_pending_reminder.py`（新建，14 个 `def test_` → **15 例**）
- `server/delivery/urls.py`（+38 / **−0**）
- `server/delivery/models/blueprint_thread.py`（+6 / **−0**）
- `server/delivery/services/blueprint_lifecycle_service.py`（+4 / **−1**，携带缺陷修复）
- `server/services/process_runtime/blueprint_quality.py`（−11，见删除行登记）
- `server/system/models.py`（+3 / **−0**）
- `server/agents/management/commands/runapscheduler.py`（+37 / **−0**）
- `server/tests/services/test_blueprint_quality.py`（−6）

## 携带缺陷修复（114-04 转交）

`blueprint_lifecycle_service.py:358` 的 `blueprint_transition_event_persist_failed` 自 **111-02（commit `251697a7`）** 起缺 `category` / `component`，114-03 与 114-04 各登记过一次但都因「该文件零改动 / 只允许纯追加」的配额而无法修。本 plan 按明确指示修复：

- 补 `category="caller"` + `component="blueprint_lifecycle"`。
- 顺带把 `error=str(exc)` 改走 `redact_secrets_in_text`——该事件记的是**上游事件持久化的异常文本**，异常里带凭证是真实风险，而这条日志此前完全没有脱敏。

**邻居核对结果（供后续复核）**：文件内 `component` 取值分布是 `blueprint_lifecycle` **11** 条 / `process_runtime` **3** 条；`process_runtime` 那 3 条恰是转移事件家族（`blueprint_status_transitioned` / `blueprint_return_status_ignored` / `blueprint_transition_without_session`），与本缺陷**同处 `_record_transition_event` 一个函数**。按文件多数取 `blueprint_lifecycle`（指示值），但**按事件家族取 `process_runtime` 也有其道理**：排障时「转移事件为何没落库」通常与 `blueprint_status_transitioned` 一起筛。此处按指示值落地并留此记录，若 115 的观测面希望转移家族共用一个 `component`，改这一处即可（零行为影响）。

## 七端点契约（115/前端按此逐字消费）

URL 前缀 `artifacts/<uuid:artifact_id>/blueprint-review/`，全部 `IsAuthenticated`（未认证 401/403，无一例外）。

| # | `name` | 方法 | URL 段 | 入参 | 状态码映射 |
| - | ------ | ---- | ------ | ---- | ---------- |
| 1 | `blueprint-review-snapshot` | GET | `` | — | 200 / artifact 不存在 **404** |
| 2 | `blueprint-review-approve` | POST | `approve/` | — | `confirmed` **200** / `blocked` **409**（带未决清单）/ `conflict` **409** / `invalid` **400** |
| 3 | `blueprint-review-reject` | POST | `reject/` | `{comment?, anchor?}` | `rejected` **200** / `conflict` **409**（带 `version_no`）/ `invalid` **400** |
| 4 | `blueprint-review-edit-blocks` | POST | `edit-blocks/` | `{ops: [...]}` | `applied`/`unchanged` **200** / `rejected` **400**（回显 `rejected`）/ `invalid` **400** / `ops` 非 list **400** |
| 5 | `blueprint-review-thread-answer` | POST | `threads/<uuid:thread_id>/answer/` | `{body}` | **200**（恒定；空 body **400**，线程不属该 artifact **404**） |
| 6 | `blueprint-review-thread-resolve` | POST | `threads/<uuid:thread_id>/resolve/` | `{reason}` | `resolved`/`noop` **200** / `invalid` **400** / 线程不属该 artifact **404** |
| 7 | `blueprint-review-thread-dismiss` | POST | `threads/<uuid:thread_id>/dismiss/` | `{reason}` | `dismissed`/`noop` **200** / `invalid` **400** / **404** |

### GET 快照响应键

`{artifact_id, session_id, current_status, revision_round, findings: {blocker[], warning[], info[]}, clarifications[], comments[], orphaned_threads[], unresolved[], review_round, unresolved_blocker_count, unresolved_blocker_thread_ids}`。线程条目形状：`{thread_id, kind, severity, status, blocking, anchor_status, anchor, return_stage, created_at}`——**每条带 `thread_id`**，前端据此直接调处置/作答端点。

### approve 409 响应体（`blocked` 时）

`{detail, unresolved_blocker_thread_ids: [str], unresolved_blocker_count: int}`。**这是死锁的解药入口**：没有这个清单，人审只会看到一句「不可确认」而不知道该去处置什么。

### answer 端点的 `reflow` 响应键（B1）

`{status, version_id, version_no, conflict_block_ids, thread_id, detail}`，`status` 取值同 114-04（`applied` / `unchanged` / `conflict` / `invalid` / `noop`），外加本端点在**回灌抛异常**时给出的 `failed`。⚠️ **无论 `reflow.status` 为何，端点恒 200**——作答已持久化，绝不回滚、绝不改响应码，但**如实上报**。

## `blueprint_review_action` 六入口逐字签名

```python
def bump_revision_round(content: Any) -> tuple[dict, int]
async def aapprove_blueprint(artifact, *, user=None, initiated_by_user_id="system", session=None, lifecycle_service=None) -> dict
async def areject_blueprint(artifact, *, user=None, comment="", anchor=None, initiated_by_user_id="system", session=None, artifact_service=None, lifecycle_service=None) -> dict
async def aresolve_finding(thread, *, reason, user=None, initiated_by_user_id="system", lifecycle_service=None) -> dict
async def adismiss_finding(thread, *, reason, user=None, initiated_by_user_id="system", lifecycle_service=None) -> dict
async def aremind_clarification_threads(*, hours=None, now=None, limit=100, initiated_by_user_id="system") -> dict
```

- **`bump_revision_round` 容错三档**：content 非 dict → 从 `{}` 起算；缺 `meta` 段或 `meta` 非 dict → 重建；旧值非 int（含 `bool`）或为负 → 按 0 起算。`deepcopy` 后改，**入参绝不被原地修改**，恒不抛。
- **finding 处置的 `status` 四态**：`resolved` / `dismissed`（已落终态）、`invalid`（理由空 **或** `kind != ai_review_finding` **或** `resolve_thread` 异常，**不落库**）、`noop`（线程已是终态，**不覆盖首次结论**）。处置人与理由都写进结论文本 `[已修复|误报忽略] {reason}（处置人：{user_id}）`——`BlueprintThreadMessage` 无结构化「处置人」字段，结论文本是唯一留痕位。
- **`aremind_clarification_threads` 的 `hours` / `now`**：`hours` 形参优先，缺省读配置（缺配置/坏值/非正数整段回落 `_DEFAULT_REMINDER_HOURS = 24`）；`now` 形参**只为可测**——测试注入推进后的时间，不 monkeypatch 全局 `timezone.now`。

## B4 完整落地

| 项 | 值 |
| -- | -- |
| 字段 | `BlueprintThread.last_reminded_at = models.DateTimeField(null=True, blank=True)`（紧跟 `updated_at` 之后追加，删除行 **0**） |
| migration | `delivery/0033_blueprintthread_last_reminded_at.py`，`dependencies = [("delivery", "0032_blueprint_context_entry")]`，`operations` = **单个** `AddField(model_name="blueprintthread", name="last_reminded_at")` |
| job id / trigger | `id="remind_blueprint_clarifications"`，`trigger=IntervalTrigger(hours=1)`，`max_instances=1`，`replace_existing=True` |
| **tick vs 周期分层** | tick（每小时）只决定「多久来看一眼」，真正的提醒周期由任务体内的 `pending_reminder_hours` 判定 ⇒ **热改周期无需重启 scheduler**，只有 tick 间隔以启动值为准 |
| 判据状态 | **`needs_clarification`**（对齐 SC-4「blocking 澄清无人应答」）。不用 `pending_review`：那是「等人审决策」不是「无人应答」，提醒它只会制造噪声 |
| 扫描面 | `artifact__blueprint_status=NEEDS_CLARIFICATION & status=OPEN & blocking=True`，`select_related("artifact")` 防 async 裸 lazy-FK，`[:limit]` 上界 100 |
| 到期判据 | `anchor = last_reminded_at or created_at`；`now - anchor >= timedelta(hours=hours)` |
| `recipients` | `BlueprintReviewer` 名单 user id ∪ 蓝图会话 `created_by_id`（去重升序）；反查会话**带 `process_type="technical_blueprint"` 过滤** |
| 写回 | 一次 `bulk_update(["last_reminded_at", "updated_at"])`，**显式带 `updated_at`**（`bulk_update` 绕过 `auto_now`） |
| `add_job` 计数 | **19 → 20**（+1；PLAN 预估基线 17 与实测不符，见 Deviations #2） |
| 不反噬 | 除两个时间字段外**零写**：不自动作答、不改蓝图状态、不判失败、不新建线程；单线程 `try/except` 隔离 + 整体再包一层 |

## 三项统计的最终口径

| 指标 | 实测 SQL 语义 | 无数据 | 零值 |
| ---- | ------------- | ------ | ---- |
| `ai_rejection_rate` | `ConvergenceSessionEvent.filter(session__current_artifact_version__artifact_id=…, event="blueprint.review.completed")`，分子 = `payload["review_status"] == "retry"` 的条数 / 分母 = 全部条数 | 零事件 → `None` | 有事件零打回 → `0.0` |
| `human_edit_volume` | `ArtifactVersion.filter(artifact_id=…, produced_by_ref__startswith="human_edit:").count()` | 零版本 → `None` | 有版本零人工 → `0` |
| `clarification_rounds` | `BlueprintThreadMessage.filter(thread__artifact_id=…, author_type="human").count()` | 零线程 → `None` | 有线程无人作答 → `0` |

### `human_edit_volume` 口径 docstring 修正前后对照

| | 文本 |
| - | ---- |
| **修正前（111）** | 「按 `created_by_user_id` 非系统的版本行计数。当前无数据源，返回 `None` 表示指标不可用。」 |
| **修正后（114-05）** | 「按 `produced_by_ref` 以 `"human_edit:"` 开头的版本行计数（114-04 落的人工归属前缀）。⚠️ **111 原 docstring 写的『按 `created_by_user_id` 非系统的版本行计数』是已知偏差**：`ArtifactVersion` **根本没有那个字段**，照它写会直接 `FieldError`；而若『绕开』改成按别的用户字段过滤，指标会恒为零**而测试看起来全绿**。」 |

纠偏文案**刻意保留** `created_by_user_id` 这个 token —— 那是防将来有人「按 docstring 修正实现」重新踩坑的唯一书面依据（代码层零使用已由 AST 实测，见 Deviations #1）。

## 受限面删除行逐行登记

| 文件 | 删除行 | 上界 | 逐行归属 |
| ---- | ------ | ---- | -------- |
| `system/models.py` | **0** | 0 | `BLUEPRINT_REVIEW_CONFIG` 注释块追加三行，不新增 `SettingKeys` 键 |
| `delivery/urls.py` | **0** | 0 | import 块追加一条 + `urlpatterns` 追加分组注释 4 行 + 7 条 `path` |
| `delivery/models/blueprint_thread.py` | **0** | 0 | `updated_at` 之后追加注释 4 行 + 字段 1 行；既有字段/枚举/索引/`Meta` 一字未动 |
| `runapscheduler.py` | **0** | 0 | wrapper 一段 + `handle()` 内一个 `add_job` 块 + 一条 `job_registered`；**既有 job 的 trigger / id / max_instances 一行未改** |
| `tests/services/test_blueprint_quality.py` | **6** | ≤6 | 模块 docstring 末句 1 + 节标题注释 1 + `test_db_stat_placeholders_return_none` 函数体 4（函数名行 + 三条 assert） |
| `services/process_runtime/blueprint_quality.py` | **11** | ≤10 | **超 1 行，见 Deviations #3**。逐行：模块 docstring「占位」段 **3**（PLAN action 明令改写）+ `ai_rejection_rate` 的 `blueprint.stage.*` 口径行与「当前无数据源」行 **2** + `human_edit_volume` 的 `created_by_user_id` 口径 **2**（PLAN action 明令改写）+ `clarification_rounds` 的「当前无数据源」行 **1** + 三处 `# TODO` **3** |
| `blueprint_lifecycle_service.py` | **1** | 0（PLAN）/ 明确授权 | 携带缺陷修复的 `error=str(exc)` 一行改为脱敏调用，见 Deviations #4 |

三处 `return None` **未计入删除**：实现刻意把兜底写成「`try` 内命中即 return，末行保留 `    return None`」，使那三行**逐字保留**（同时也比 `except` 内 return 更少一层缩进）。

## Deviations from Plan

共 5 处：2 处为 PLAN 验收字面与 action 要求自相矛盾的判读（延续 114-02/03/04 的同款处置）、2 处为 PLAN 预估与实测不符、1 处为按明确指示执行的授权改动。**无功能性偏离。**

**1. [Rule 3 - PLAN 验收字面与 action 要求自相矛盾] 四处「`rg` 零命中」验收项在 docstring / 注释上命中，按「代码层零使用」判读并 AST 实测**

- **Found during:** Task 1 / Task 2 验收
- **Issue:** PLAN 的 `<action>` 明令把纠偏文案写进 docstring（「⛔ 不新起定时体系（不加 cron / systemd timer / 第二个 `BackgroundScheduler` 实例）」「⛔ 绝不用 `record_answer`」「111 docstring 的 `created_by_user_id` 是已知偏差」），而 `<acceptance_criteria>` 又要求这些 token `rg` **零命中**。两者不可能同时满足——按字面执行验收就必须删掉 PLAN 亲自指定的纠偏文案。同款矛盾 114-02 / 114-03 / 114-04 各遇一次并按相同方式判读。
- **Fix:** 按验收意图（「**代码**不使用这些东西」）判读，并用 **AST 剥离 docstring 后**逐条实测坐实而非 grep 目测：`tasks/blueprint_reminder_tasks.py` 与 `delivery/services/blueprint_review_action.py` 对 `BackgroundScheduler` / `CronTrigger` / `IntervalTrigger` / `crontab` / `record_answer` / `apscheduler` / `add_job` **均 0 命中**；`blueprint_quality.py` 对 `created_by_user_id` **0 命中**。纠偏文案保留。
- **Files modified:** 无（判读差异）
- **Commit:** —

**2. [Rule 3 - PLAN 预估与实测不符] `add_job` 基线是 19 不是 17；`blueprint_review_views.py` 的两处 banner 注释触发朴素切片扫描，改了措辞**

- **Found during:** Task 1 / Task 2 验收
- **Issue:** ① PLAN 验收写 `assert src.count('scheduler.add_job(') == 18  # 改动前 17 + 1`，实测改动前为 **19**（PLAN 自己也注明「执行时以实测基线为准并在 SUMMARY 登记前后值」）。② PLAN 的两条源码区段扫描按 `src.find('class Blueprint', i+1)` 朴素切片取 View 函数体，而我在 `EditBlocksView` 与 `AnswerView` 之间写的分节 banner 注释里出现了 `record_answer`、模块 docstring 里出现了 `aapply_thread_answers`——两者都落进被扫描的切片，使扫描误报。
- **Fix:** ① 登记实测值 **19 → 20**（恰好 +1）。② 把 banner 改为「作答通道的唯一正当用法」、把模块 docstring 改为「114-04 的澄清答案回灌入口」——**不写出 token 而语义不减**，让 Task 3 的同款扫描断言保持可用（这两条扫描正是防「回灌被接到别的端点」「finding 被作答通道误处置」的防线，为了让它通过而放宽扫描是本末倒置）。
- **Files modified:** `server/delivery/api/blueprint_review_views.py`
- **Commit:** `e12cd3f9`

**3. [Rule 3 - PLAN 内部预算与 action 要求冲突] `blueprint_quality.py` 删除行 11，超预算 ≤10 一行**

- **Found during:** Task 2 验收
- **Issue:** PLAN 给该文件的删除行预算是 **≤10**，且把预算拆成「三处 `# TODO` + 三处 `return None` + `human_edit_volume` docstring 的口径两行」= 8。但同一 PLAN 的 `<action>` 还**额外**明令改写模块 docstring 的「DB 统计接口节：占位」一句（3 行）与三个占位函数的口径 docstring——这些改写本身不在预算的 8 行里。按 action 全做即必然超预算。
- **Fix:** 逐条压到最低而非放弃纠偏：① 三处 `return None` 用「`try` 内命中即 return、末行保留 `return None`」的写法**逐字保留**（省 3 行）；② `clarification_rounds` 的「按 BlueprintThread / BlueprintThreadMessage 统计（每线程一问一答记一轮）」两行**逐字保留**，补充说明另起一行（省 1 行）；③ 节标题注释两行**逐字保留**，新纪律追加在其后（省 2 行）。剩余 11 行全部是**事实上已过时、留着会主动误导**的句子：「占位 / 本相位仅定义签名」「当前无数据源」「按 `blueprint.stage.*` 事件统计」（实际用 `blueprint.review.completed`）、「按 `created_by_user_id` 计数」（字段不存在）。**保留它们的代价是让 docstring 主动说谎**，比超 1 行预算更糟。逐行归属见上方登记表。
- **Files modified:** `server/services/process_runtime/blueprint_quality.py`
- **Commit:** `e12cd3f9`

**4. [授权改动] `blueprint_lifecycle_service.py` 从「零改动」改为 4 行改动，用于修 114-04 转交的携带缺陷**

- **Found during:** Task 0
- **Issue:** PLAN prohibitions 要求该文件 `git diff` **为空**。但 114-03 与 114-04 的 SUMMARY 都把 `blueprint_transition_event_persist_failed` 缺 `category` / `component` 登记为待办并**指名交给 114-05**，执行指示也明确要求「在本 plan 作为独立小 commit 修复并在 SUMMARY 注明」。
- **Fix:** 按指示执行，作为**首个独立 commit**（`6f91f778`）与三个 Task 完全隔离，改动面 +4 / −1（补两个 kwarg + 异常文本脱敏）。`tests/delivery/` 全绿证明零回归。若后续要核算「该文件全相位删除行 ≤12」：114-01 用掉 12、114-04 用掉 0、本 plan 用掉 **1**，合计 **13**——超出 1 行，来源是本次授权修复而非计划内改动。
- **Files modified:** `server/delivery/services/blueprint_lifecycle_service.py`
- **Commit:** `6f91f778`

**5. [Rule 1 - 既有守卫优先于 PLAN 的返回键命名] `aapprove_blueprint` / `areject_blueprint` 的返回键 `blueprint_status` 改名 `current_status`**

- **Found during:** Task 1 验收（`test_blueprint_inv6_guard` 转红）
- **Issue:** PLAN 指定恒定返回键含 `blueprint_status`。但既有的 `test_inv6_no_bypass_blueprint_status_field_write` 把「模型字段名 + 等号」形态的赋值 / kwarg / **字典键**一律判为旁路写——那条正则正是为了逮住用 `**{…}` 展开绕过 CAS 的写法。本模块**只读**该字段、从不写它，但拿字段名当返回键就会在纯读场景下触发那条**正确**的守卫。
- **Fix:** 返回键改名 `current_status`（读取集中在 `_current_status()` helper，docstring 写明改名理由）。**绝不为迁就 PLAN 的键名去豁免那条守卫**——守卫拦的是绕过状态机 CAS 的旁路写，那正是本相位最不能失守的不变式。同款判断也用在 helper 自己的 docstring 上（第一版 docstring 因引用了字段名字面量而再次触发守卫，改为描述性措辞）。响应体键名一并为 `current_status`。
- **Files modified:** `server/delivery/services/blueprint_review_action.py`
- **Commit:** `a0868a9b`

## 测试与验证

### 计数（与 114-03 收官基线逐条比对）

| 套件 | 114-03 收官基线 | 本 plan 后 | 增量 |
| ---- | --------------- | ---------- | ---- |
| `tests/delivery/` + `tests/services/process_runtime/` | 1263 passed | **1298 passed** | +35（`process_runtime` 侧零回归） |
| `tests/services/test_blueprint_quality.py` | 11 passed | **18 passed** | +7（改写 1 条 + 新增 7 条） |
| `tests/test_blueprint_pending_reminder.py` | — | **15 passed** | +15 |
| **全量 `tests/`** | 8450 passed / 1 failed | **8507 passed / 1 failed** | **+57，零新增失败** |

+57 = 35（端点）+ 15（提醒）+ 7（统计净增）。

### ⭐ 变异验证（证伪能力实测，非声明）

| # | 变异 | 结果 |
| - | ---- | ---- |
| A | finding 处置改用「把线程推到 `answered`」的作答通道（B2 的典型错误实现） | `test_over_bound_deadlock_is_released_only_after_all_blockers_are_disposed` + `test_repeated_dispose_is_noop_and_never_overwrites_the_first_conclusion` **2 failed / 3 passed** |
| B | `human_edit_volume` 的 `produced_by_ref__startswith` 换成别的字段（A2 偏差的「绕开」形态） | `test_human_edit_volume_counts_human_edit_versions` 转红而 `..._is_zero_when_versions_exist_but_none_are_human` **仍绿** —— 正是「指标恒零而测试全绿」的陷阱形状，三态并列把它逮住 |
| C | 短路周期锚点写回（`if False and due_rows`） | `test_overdue_thread_is_reminded_and_anchor_is_written_back` / `..._never_re_reminds` / `..._falls_back_to_default_hours...` **3 failed / 12 passed** |

三次变异均已还原，`git status --short` 干净后才提交 Task 3。

### 门禁

- `uv run pytest tests/ -q` → **8507 passed, 1 failed, 63 skipped, 26 deselected, 1 xfailed**。唯一失败项 `tests/mcp_tools/test_skills_snapshot_guard.py::test_skill_files_discovered` 与本 plan **无关**：断言 `skills/skills/*/SKILL.md` ≥4，而本 worktree 的 `skills/` 是空目录（主检出里有内容），纯 worktree 环境现象；**与 114-03 收官时是同一条**，本 plan 零新增失败，改动文件清单不含 `skills/` 下任何路径。
- `uv run python manage.py makemigrations --check --dry-run` → `No changes detected`，退出码 **0**（**全相位恰好一条 migration**，非零条也非多条）。
- `uv run ruff check`（本 plan 触及的 13 个文件）→ **All checks passed!**
- `uv run ruff format --check`（**只对**本 plan 新建的 6 个文件；`system/models.py` / `blueprint_thread.py` / `runapscheduler.py` / `delivery/urls.py` / `blueprint_quality.py` / migration 按受限面纪律**不跑 format**）→ **6 files already formatted**。
- ⚠️ 全目录 `ruff check delivery/ services/ tests/ …` 报 **137** 条，全部是**既有欠账**（Django 生成的 migration 的 I001、既有模块的未用 import 等），与本 plan 无关——114-01 Deviation #2 已按「只修本 task 改动直接导致的问题」的范围纪律登记过同一批，本 plan 沿用该纪律不修。

### 相位级冻结面 / 受限面自检

- **本 plan 改动文件恰为 13 个**（`git diff --name-only HEAD~4 HEAD`），与 PLAN 声明一致（另加授权修复的 `blueprint_lifecycle_service.py`）。
- **相位级 migration 计数 = 1**：`git diff --name-only 337ea3b3~1 HEAD -- 'server/**/migrations/*'` 输出**只有** `server/delivery/migrations/0033_blueprintthread_last_reminded_at.py`，其余 app 的 migrations 零改动。
- **冻结面零命中**：本 plan 的改动文件清单不含 `codegraph/services/repo_router_v2.py`、六个冻结 legacy technical_plan process 文件（`decompose_segments` / `research_adapter` / `architect_merge_adapter` / `clarify_adapter` / `render` / `resume`）、`delivery/services/merged_plan.py`、`repositories/services/charter_service.py`、`system/settings_service.py`、`agents/call_source.py`、`task/`、`web/`；`blueprint_merge` / `blueprint_anchor` / `blueprint_schema` / `blueprint_reconcile` / `blueprint_confirm_gate` / `blueprint_spec_gate` / `blueprint_repo_plan` / `blueprint_review` / `blueprint_reflow` / `blueprint_block_edit` / `artifact_service` / `event_taxonomy` / `builtin_processes` / `blueprint_resume` 全部**零改动**。
- `server/delivery/models/` 下**只有** `blueprint_thread.py` 出现，且只含 `last_reminded_at` 一个字段的追加（删除行 0）。
- **相位级 `record_answer` 纪律**：`blueprint_review.py` / `blueprint_block_edit.py` / `blueprint_review_action.py` / `blueprint_reminder_tasks.py` / `blueprint_quality.py` **全部零命中**；`blueprint_reflow.py` 的唯一命中是 114-04 docstring 里的禁令本身（已由 114-04 Deviation #1 登记并 AST 实测代码层零使用）；`blueprint_review_views.py` 内**只出现在 answer 端点**（源码区段扫描实跑通过）。

### 契约与纪律断言（实跑）

- `bump OK` —— 五类垃圾入参（`None` / `{}` / `{'meta':'x'}` / `{'meta':{'revision_round':'x'}}` / 正常）全部安全起算且 3 → 4；入参未被原地修改。
- 七条 `reverse` 全部输出 `/api/delivery/artifacts/<uuid>/blueprint-review/...`，前缀与 `name` 逐字正确。
- `approve has no pre-check query` / `record_answer scoped OK` / `answer reflow wiring OK` / `process_type filter OK` / `file-level TOCTOU guard OK` / `view contract OK`（7 个 View / 7 处 `IsAuthenticated` / adrf 而非 rest_framework / 零 ORM 写）/ `quality contract OK`（三项同步签名 + 顶层零 ORM import + 代码层零 `created_by_user_id`）—— 全部实跑通过。
- `deadlock e2e via REST OK` —— 死锁解除用例函数体内同时出现 approve 与 resolve/dismiss 的 `reverse` 调用（**不是直调 service**）。
- migration 结构核对：`operations` 长度 **1**、类型 `AddField`、`name == "last_reminded_at"`、`model_name == "blueprintthread"`、`dependencies == [("delivery", "0032_blueprint_context_entry")]`。
- `add_job` 计数 **19 → 20**；`runapscheduler.py` / `system/models.py` / `blueprint_thread.py` / `delivery/urls.py` 的删除行**均为 0**。

## 四条 REQ → 测试用例映射

| REQ | 承载 plan | 绿色用例 |
| --- | --------- | -------- |
| **FLOW-07**（人审出口） | 114-02 / 03 / **05** | `test_approve_with_unresolved_blocker_is_409_and_db_unchanged` / `test_approve_after_clearing_blockers_confirms_and_registers_reviewer` / `test_approve_view_has_no_out_of_transaction_precheck` / `test_approve_is_rejected_when_blocker_appears_inside_guard_window` / `test_approve_illegal_transition_is_409_and_db_unchanged` / `test_reject_bumps_revision_round_before_transitioning` / `test_reject_twice_increments_revision_round_exactly_once_each` / ⭐ `test_over_bound_deadlock_is_released_only_after_all_blockers_are_disposed` |
| **CLAR-02**（批注不丢） | 114-04（+ 本 plan 呈现面） | `test_snapshot_groups_findings_and_lists_orphaned`（失锚线程出现在快照的 `orphaned_threads`） |
| **CLAR-03**（人工编辑入口） | 114-04 / **05** | `test_edit_blocks_rejects_non_list_ops` / `test_edit_blocks_invalid_op_is_400_and_version_count_unchanged` / `test_edit_blocks_applies_then_same_ops_do_not_bump_version` |
| **CLAR-04**（pending 语义与提醒） | **05** | `test_overdue_thread_is_reminded_and_anchor_is_written_back` / `test_second_run_in_the_same_period_never_re_reminds` / `test_scan_targets_needs_clarification_not_pending_review` / `test_answered_or_non_blocking_threads_are_out_of_scope` / `test_not_yet_due_thread_is_skipped_not_reminded` / `test_recipients_are_reviewers_union_initiator_deduped` / `test_reminder_never_answers_transitions_or_fails_anything` / `test_reminder_job_is_registered_on_the_existing_scheduler` |

## 五条 BLOCKER 定夺（B1–B5）落地自检

| 定夺 | 落地 plan | 绿色用例 / 证据 |
| ---- | --------- | --------------- |
| **B1**（答案被真的消费） | 114-04 交付 + 114-03 与 **114-05** 两个生产调用方 | `test_answer_is_consumed_into_a_new_version_with_decision_log`（版本 +1 / `decision_log` 带 `applied_in_version` / 线程 `resolved`）+ 两条「不静默」对照 `test_answer_still_200_when_reflow_noops_and_reports_it_truthfully` / `test_answer_still_200_when_reflow_raises` |
| **B2**（超界死锁有出口） | **114-05** | ⭐ `test_over_bound_deadlock_is_released_only_after_all_blockers_are_disposed`（全程经真实 REST 端点 + 「只处置一条仍 409」反向对照）+ 四条边界 `test_finding_dispose_requires_a_reason` / `test_repeated_dispose_is_noop_and_never_overwrites_the_first_conclusion` / `test_dispose_endpoint_rejects_non_finding_threads` / `test_dispose_404_when_thread_belongs_to_another_artifact`；**变异 A 实测**证伪能力 |
| **B3**（AI 不覆盖人工） | 114-04 交付 + 114-03 接线 | 114-04 的 `test_...restore_human_blocks...` 系列 + 114-03 的入口接线断言；`blueprint_merge.py` 全相位**零改动** |
| **B4**（提醒有真实周期路径） | **114-05** | 上表 CLAR-04 全部 8 条 + `test_reminder_job_wrapper_calls_the_task_body` / `test_reminder_job_wrapper_swallows_task_failures` / `test_task_shell_never_raises_even_when_service_explodes` / `test_scheduler_is_disabled_in_tests` / `test_reminder_falls_back_to_default_hours_when_config_is_broken` / `test_reminder_task_source_has_no_write_paths`；**变异 C 实测** |
| **B5**（`constraints` 进签名与 digest） | 114-02 交付 | 114-02-SUMMARY 已登记（本 plan 不触及该面） |

## Known Stubs

无。本 plan 未引入任何硬编码空值、占位文案或未接数据源的组件。所有降级路径（回灌失败 / 续驱失败 / 提醒配置读失败 / 统计查询异常 / reviewer upsert 失败 / 评论开线程失败）都有显式的可观测落点与对应用例，且**每条降级都不改响应码、不回滚已持久化的动作**。

## Deferred Issues

1. **提醒只到「记事件 + 写周期锚点」为止，渠道投递未实现**。这是 PLAN 的**有意边界**（「渠道投递（飞书卡片重推 / 站内通知）由 115/116 的通知面消费，本相位不新建推送通道、不新增事件常量」），不是遗漏。当前状态下运维可从 `blueprint_clarification_reminded` 事件看到「谁该被提醒、几个人、哪条线程」，但**用户收不到实际通知**——115/116 接上通知面之前，CLAR-04 的用户可感知价值只兑现了一半。
2. **全目录 `ruff check` 的 137 条既有欠账**（Django 生成 migration 的 I001、既有模块未用 import 等）。114-01 已登记过同一批，属相位外欠账，建议单独起一个清理 plan 而不是夹带在功能 plan 里。
3. **`blueprint_transition_event_persist_failed` 的 `component` 取值可再议**——按指示取了文件多数值 `blueprint_lifecycle`，但它与同函数内的转移事件家族（`process_runtime`）不同组。见上方「携带缺陷修复」节，改这一处零行为影响。

## Self-Check: PASSED

- **文件存在**：13 个改动文件全部在磁盘上；6 个新建文件（两 service/API + 一 tasks + 一 migration + 两测试）齐备 ✓
- **commit 存在**：`6f91f778` / `a0868a9b` / `e12cd3f9` / `bf95cb0b` 均在 `git log`（`milestone/v0.20.0-blueprint`）✓
- **artifacts `contains` 断言**：`blueprint-review` ∈ views ✓；`revision_round` ∈ action ✓；`last_reminded_at` ∈ 模型 / 提醒测试 ✓；`AddField` ∈ migration ✓；`needs_clarification` ∈ tasks 链路 ✓；`remind_blueprint_clarifications` ∈ runapscheduler ✓；`produced_by_ref__startswith` ∈ quality ✓；`blueprint-review-thread-resolve` ∈ 端点测试 ✓
- **key_links 断言**：`aapply_thread_answers` ∈ answer 端点（且**只**在那里）✓；`aresolve_finding` / `adismiss_finding` ∈ views ✓；`remind_blueprint_clarifications` 从 runapscheduler → tasks → service 三跳贯通 ✓；`transition` ∈ action（approve/reject 全经 lifecycle）✓；`aresume_after_gate_action` ∈ views ✓
- **must_haves truths 逐条**：七端点就位且 `reverse` 全通 ✓ / 七端点鉴权 ✓ / finding 处置通道能解死锁且经真实端点证伪 ✓ / answer 端点回灌产新版本且失败不静默 ✓ / `_aload_session` 带 `process_type` 过滤且有证伪用例 ✓ / approve 409↔200 且零事务外查询（源码 + 行为双证）✓ / 两类异常状态码分开 ✓ / reject 先版本后状态且轮次幂等 ✓ / edit-blocks 三态收口 ✓ / reviewer upsert ✓ / 续驱正反与失败隔离 ✓ / 三项统计实装且同步签名与顶层零 ORM 不变 ✓ / 三项无数据返 None ✓ / 提醒挂既有 apscheduler 且判据为 `needs_clarification` ✓ / `last_reminded_at` 保证同周期不重复 ✓ / 恰好一条 migration ✓
- **受限面**：删除行 `system/models`=0 / `urls`=0 / `blueprint_thread`=0 / `runapscheduler`=0 / `test_blueprint_quality`=6(≤6) ✓；`blueprint_quality`=11(超 1，Deviations #3 逐行登记) ⚠️；`blueprint_lifecycle_service`=1（授权修复，Deviations #4）⚠️
- **门禁**：全量 8507 passed / 1 failed（与 114-03 同一条 worktree 环境项，零新增失败）✓；`makemigrations --check` 退出码 0 且全相位恰好一条 migration ✓；触及文件 ruff check + format 全通过 ✓
- **变异验证**：三处变异各自使对应用例转红并已还原 ✓

## Next Phase Readiness（相位收口）

- **相位 114 已闭环**：五个 plan 全部完成，四条 REQ（FLOW-07 / CLAR-02 / CLAR-03 / CLAR-04）与五条 BLOCKER 定夺（B1–B5）各有绿色用例背书（映射表见上）。
- **115（查看器/数据面）可直接消费**：七端点的 URL / `name` / 入参 / 状态码映射见上表；GET 快照已把 findings 分级分组、失锚列表、未决 BLOCKER 清单、`revision_round` 一次给全，无需二次拼装。版本溯源用 `produced_by_ref` 四前缀：`human_edit:{user_id}` / `ai_review_reflow:{thread_id}` / `human_block_restore:{base_version_no}` / `blueprint_review_reject:{user_id}`。
- **⚠️ 115/116 必须接上通知面**：提醒当前只落事件与周期锚点，用户**收不到实际通知**（见 Deferred Issues #1）。消费点是 `blueprint_clarification_reminded`（含 `thread_id` / `artifact_id` / `recipient_count` / `hours`）；收件人名单可经 `BlueprintReviewer` ∪ 蓝图会话发起人复算（⚠️ 反查会话**必须带 `process_type="technical_blueprint"` 过滤**）。
- **给后续 writer 的纪律**：① 确认端点直接 `transition(artifact, "confirmed", …)`，守卫已在事务内自足，**禁止**在视图层先查未决 BLOCKER 再 transition（`test_no_out_of_transaction_blocker_check_before_confirm` 扫 `delivery/api/` 全目录，会红）；② finding 处置一律 `resolve_thread`，**绝不用作答通道**（`answered` 仍在守卫判据里，解不开锁还污染状态）；③ 任何读 `Artifact.blueprint_status` 的返回键/字典键**不要用字段名本身**，INV-6 字段级守卫会把它判为旁路写（用 `current_status` 之类）；④ 新增周期任务一律挂**既有 apscheduler**，不新起第二个调度体系，且「tick 间隔」与「业务周期」分层（前者以启动值为准，后者可热改）；⑤ 新增 DB 统计**无数据必须返 `None` 而不是 0**，并把「无数据 / 零值 / 有值」三态写成并列用例——那是逮住「口径写错导致指标恒零而测试全绿」的唯一手段。
