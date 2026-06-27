---
phase: 91-clarification-outlets-resume
plan: 04
subsystem: api
tags: [plan_orchestration, clarification, chat, resume, owner_gate, contextvars, async, inv6, observability]

# Dependency graph
requires:
  - phase: 91-01
    provides: aanswer_round_and_resume（入口无关「作答 + 续推」共享回流 helper）
  - phase: 90-02
    provides: ClarificationService.ahas_pending / answer_round / create_round（结构化澄清写入 + 统一 pending 谓词）
  - phase: 43-03
    provides: _schedule_chat_plan_resume（chat 入口 plan_research 全终态 → engine 续驱 + barrier 回灌）
provides:
  - runtime 新键 pending_plan_clarification（结构化轮 questions[]，供前端 91-05 渲染）
  - 会话端 plan 澄清专属路由 POST /api/chat/conversations/{id}/plan-clarification/answer/（PlanClarificationAnswerView + PlanClarificationAnswerSerializer）
  - 会话侧 CLARIFY-04/06 闭环：runtime 暴露轮 → 专路由收答 → 同源 helper 续推
affects: [91-05 前端 ClarificationCard 渲染, 94 入口统一]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "出口面专路由物理隔离：plan 编排结构化澄清独占 endpoint + runtime key，与既有 chat 单题澄清（ConversationIntentTrace）完全独立，零污染既有回归"
    - "会话端续推与飞书回调同源调用 aanswer_round_and_resume（不造两套）；入口私有重调度（chat barrier 回灌）由既有 _schedule_chat_plan_resume 接管"
    - "owner gate 落 API 层 mirror ClarificationAnswerView（created_by_id + has_project_access，无 superuser bypass，404 隐藏存在性）"

key-files:
  created:
    - server/tests/test_plan_clarification_answer_endpoint.py
  modified:
    - server/chat/conversation_service.py
    - server/chat/serializers.py
    - server/chat/views.py
    - server/chat/urls.py

key-decisions:
  - "runtime 仅暴露结构化轮（含子题）；ahas_pending 兼容的旧单题行（无子题）不渲染 plan 澄清卡（questions 为空时保持 None）"
  - "view 不直接调用 _schedule_chat_plan_resume（其签名要 SubAgentSession）；helper 的 adrive 续驱 + 既有调研全终态回调链负责 chat barrier 回灌，符合 91-01「入口私有重调度留各调用方」"
  - "越界 question_id 取 400 拒绝（不静默丢弃），落库/续推前阻断（T-91-04-02）"
  - "ConversationRuntimeSerializer 增字段透传：DRF Serializer 丢弃未声明 key，不加字段则 runtime dict 的 pending_plan_clarification 不会出 API（Rule 2 补齐）"

patterns-established:
  - "Pattern: 出口面专路由 + runtime 独立 key 物理隔离既有澄清链，不复用既有 endpoint 避免回归面扩大"
  - "Pattern: 会话端 fire-and-forget 续推 task 用 asyncio.create_task(coro, context=contextvars.Context()) 干净上下文启动（Pitfall 3 防 CurrentThreadExecutor already quit）+ _BACKGROUND_TASKS 强引用"

requirements-completed: [CLARIFY-04, CLARIFY-06]

# Metrics
duration: ~12min
completed: 2026-06-27
---

# Phase 91 Plan 04: 会话端 plan 澄清出口面 + 回流 Summary

**runtime 暴露 plan 结构化澄清轮 `pending_plan_clarification`（多题 questions[]，与 chat 单题澄清物理隔离）+ 新建会话端专属路由 `POST /api/chat/conversations/{id}/plan-clarification/answer/` 收结构化 answers[]，owner gate + 经同源 helper `aanswer_round_and_resume` 写 delivery + 续推 PlanSession，会话侧 CLARIFY-04/06 端到端闭环。**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-06-27T08:45:00Z
- **Completed:** 2026-06-27T08:57:00Z
- **Tasks:** 2
- **Files modified:** 4（1 新建测试 + 3 改）

## Accomplishments
- **runtime 暴露结构化轮（CLARIFY-04 数据传输）**：`get_conversation_runtime` 检测本会话软引用关联的最近 `PlanSession`，若 `ClarificationService.ahas_pending` 为真则取 pending `Clarification` 轮 + 按 `order` 序列化 `ClarificationQuestion` 子题 → `runtime["pending_plan_clarification"] = {clarification_id, round_no, questions[{question_id,question,qtype,options,recommended,selected,freeform_text}]}`。与既有 `pending_clarification`（chat 单题，ConversationIntentTrace）**完全独立**，只读 best-effort（异常吞为 None 不反噬 runtime），async 全程 `*_id` 标量过滤防裸 lazy-FK。
- **plan 澄清专属路由（CLARIFY-04 收答 / CLARIFY-06 会话侧）**：新 `PlanClarificationAnswerView` + `PlanClarificationAnswerSerializer`（`answers: ListField(DictField)`，结构校验非空 + 每条含 question_id）+ 新路由注册（物理隔离既有 `clarifications/<id>/answer/`）。
- **owner gate + 归属/越界防护**：mirror `ClarificationAnswerView`——`conversation.created_by_id != user.id` 跨用户 404、非 superuser 再 `PermissionService.has_project_access` 跨项目 404（均落库/续推前，隐藏存在性）；每个 `question_id` 经 `acount` 比对必属该 session pending 轮，越界 400（T-91-04-02）。
- **同源续推 + 干净 contextvars**：取 pending 轮 id → 后台 `asyncio.create_task(_answer_and_resume(), context=contextvars.Context())`（Pitfall 3 防 CurrentThreadExecutor already quit、run 永卡）+ `_BACKGROUND_TASKS` 强引用，task 内经 `aanswer_round_and_resume` 写 delivery + 续驱 PlanSession（与飞书回调 91-03 同源、不造两套；INV-6 写入只经 helper→answer_round）。chat barrier 回灌由既有 `_schedule_chat_plan_resume`（调研全终态回调链）接管。
- **观测**：`plan_clarification_answer_recorded`（category=caller、component=chat、duration_ms）+ 越权/越界 warning 仅记 conversation_id/clarification_id 标量；续推失败 `plan_clarification_answer_resume_failed` best-effort 吞掉不反噬主响应。

## Task Commits

Each task was committed atomically:

1. **Task 1: runtime 暴露 plan 结构化澄清轮 pending_plan_clarification** - `c4a7eae1b` (feat)
2. **Task 2: plan 澄清专属路由收 answers[] + owner gate + 同源续推** - `d682183c5` (feat)

**Plan metadata:** (final docs commit)

## Files Created/Modified
- `server/chat/conversation_service.py` - `get_conversation_runtime` 新增 `pending_plan_clarification` 默认 None + 结构化轮序列化块（best-effort 只读）
- `server/chat/serializers.py` - `ConversationRuntimeSerializer` 增 `pending_plan_clarification` 透传字段 + 新 `PlanClarificationAnswerSerializer`（结构化 answers[] 校验）
- `server/chat/views.py` - 新 `PlanClarificationAnswerView`（owner gate + 归属校验 + 干净 contextvars 后台续推）+ serializer 导入
- `server/chat/urls.py` - 注册 `conversations/<uuid>/plan-clarification/answer/` 专路由 + view 导入
- `server/tests/test_plan_clarification_answer_endpoint.py` - 新建 10 用例（runtime 3：暴露结构化轮 / 无 session None / 已答 None；endpoint 7：404 unknown / 400 空 answers / 409 无 pending / 404 无 session / 400 越界 question_id / 200 同源 helper 被调 / 跨用户 404）

## Decisions Made
- **runtime 仅暴露结构化轮**：`ahas_pending` 对旧单题行（无子题容器）也判 pending，但 plan 澄清卡只渲染结构化轮——`questions` 为空时保持 `pending_plan_clarification = None`，旧单题行不误进 plan 澄清面。
- **view 不直接驱动 `_schedule_chat_plan_resume`**：该函数签名要 `SubAgentSession`（取 `last_output["plan_session_id"]`），会话 endpoint 无天然 SubAgentSession。helper 的 `adrive_plan_session_to_pause_or_terminal` 续驱 + 既有调研全终态回调链（43-03）负责 chat barrier 回灌，符合 91-01「入口私有重调度留各调用方」设计——不在 view 重复造。
- **越界 question_id 取 400 而非静默丢弃**：plan 二选一明确「400/丢弃越界」，选显式 400 拒绝、落库/续推前阻断，避免部分成功的模糊语义（answer_round 内再按 id + answered_at IS NULL no-op 作纵深）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] ConversationRuntimeSerializer 增 pending_plan_clarification 字段**
- **Found during:** Task 1（runtime 暴露）
- **Issue:** plan Task 1 的 `files_modified` 未列 `serializers.py`，但 `ConversationRuntimeView` 走 `ConversationRuntimeSerializer` 输出——DRF `Serializer` 丢弃未声明 key，不加字段则 runtime dict 写入的 `pending_plan_clarification` 永远不会出现在 API 响应里，前端拿不到数据，CLARIFY-04「数据传输」失效。
- **Fix:** `ConversationRuntimeSerializer` 增 `pending_plan_clarification = serializers.JSONField(allow_null=True, required=False)` 透传字段。
- **Files modified:** server/chat/serializers.py
- **Verification:** runtime 测试经 `get_conversation_runtime` 直读 dict 通过；字段为 API 出参必要条件，ruff/mypy 干净。
- **Committed in:** `c4a7eae1b`（Task 1 commit）

---

**Total deviations:** 1 auto-fixed（1 missing critical）
**Impact on plan:** 仅补齐数据真正出 API 的必要透传字段，无 scope creep；归入 Task 1 runtime 暴露语义。

## Issues Encountered
- **后台 fire-and-forget task 在 async_to_sync 测试上下文不确定性运行**：会话 endpoint 设计为后台 `create_task` 续推，但 sync APIClient 经 `async_to_sync` 跑完 view 后事件循环可能在后台 task 跑完前收束，「helper 被调」断言会 flaky。解决：测试用 `run_bg_inline` fixture 把 `asyncio.create_task` 替成同步 step 驱动协程（helper 已 mock 为无真实 await），使「同源 helper 被调 + 按 pending 轮 id 调用」可确定性断言。生产路径不受影响（真实 ASGI 事件循环长存）。

## Threat Surface Scan
threat_model 五项 mitigate 均落实：
- **T-91-04-01（Elevation 跨会话/跨用户）**：owner gate（`created_by_id` + `has_project_access`，无 superuser bypass）落库/续推前 404，`test_cross_user_returns_404` 守护（断言 helper 未被调）。
- **T-91-04-02（Tampering 越界 question_id）**：`acount` 比对该 session pending 轮子题集合，不全等 → 400，`test_400_question_id_not_in_round` 守护；answer_round 按 id + answered_at IS NULL no-op 纵深。
- **T-91-04-03（DoS 续推 contextvars 崩）**：`asyncio.create_task(coro, context=contextvars.Context())` 干净启动（Pitfall 3）。
- **T-91-04-04（Tampering 旁路写 delivery）**：写入只经 `aanswer_round_and_resume`→`answer_round`（INV-6），view 无 delivery 模型 `.objects.create/.update/.save`。
- **T-91-04-05（Info Disclosure 异常/正文泄密）**：日志仅记 conversation_id/clarification_id/计数标量；续推异常 best-effort 吞掉（`logger.exception` 不外泄正文给响应）。

新增请求入口 `plan-clarification/answer/` 已纳入观测（`plan_clarification_answer_recorded`，duration_ms）。无新增 schema 变化，新威胁面已全部登记在 threat_model 内。

## Known Stubs
None - 本 plan 落地会话端 runtime 暴露 + 收答续推后端闭环，无 mock 数据、无 UI（前端 ClarificationCard 渲染由 91-05 消费本 plan 的 `pending_plan_clarification` 与专路由）。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 会话侧 CLARIFY-04/06 闭环就绪：runtime 暴露结构化轮 → 91-05 前端可据 `pending_plan_clarification.questions[]` 渲染多题澄清卡 → 提交到 `POST conversations/{id}/plan-clarification/answer/`。
- 续推单一来源：会话端与飞书回调（91-03）同源调用 `aanswer_round_and_resume`，不造两套。
- 验收全绿：`tests/test_plan_clarification_answer_endpoint.py`(10) 全 pass；既有 `tests/test_clarification_answer_endpoint.py`(8) + INV-6 守护无回归；ruff/mypy（chat/views.py, conversation_service.py）干净。

---
*Phase: 91-clarification-outlets-resume*
*Completed: 2026-06-27*

## Self-Check: PASSED
- FOUND: server/chat/conversation_service.py（pending_plan_clarification runtime）
- FOUND: server/chat/serializers.py（字段 + PlanClarificationAnswerSerializer）
- FOUND: server/chat/views.py（PlanClarificationAnswerView）
- FOUND: server/chat/urls.py（plan-clarification/answer/ 路由）
- FOUND: server/tests/test_plan_clarification_answer_endpoint.py
- FOUND: .planning/phases/91-clarification-outlets-resume/91-04-SUMMARY.md
- FOUND commit c4a7eae1b (Task 1 feat)
- FOUND commit d682183c5 (Task 2 feat)
- 验收：tests/test_plan_clarification_answer_endpoint.py 10 passed；ruff/mypy 干净；既有 chat 单题澄清 + INV-6 守护无回归
