---
phase: 91-clarification-outlets-resume
plan: 02
subsystem: api
tags: [clarification, feishu_card, workflow_node, waiting_event, subscription, async, sync_to_async, observability, inv6]

# Dependency graph
requires:
  - phase: 90-02
    provides: ClarificationService.create_round / answer_round / ahas_pending（结构化澄清写入 + 统一 pending 谓词）
  - phase: 89-01
    provides: PlanDeepenNode 发卡 + WorkflowEventSubscription 范式（_resolve_initiator / _send_clarify_card / _asend_card）
  - phase: 87-04
    provides: board_split_review._resolve_space / _aresolve_project（群解析 helper）
provides:
  - "build_clarification_card(..., *, clarification_id='')：form_submit value.action='plan_clarify_answer' + value.clarification_id（新前缀隔离 GroupChatQuestion 路由）"
  - "ai_plan_research._maybe_suspend CLARIFYING：工作流入口发飞书澄清卡 + 建 WorkflowEventSubscription(event_type='PlanClarifyCallback')"
  - "WR-03 收口：plan_research.py / plan_research_tools.py / plan_deepen.py 三处 pending 存在性判定经 ClarificationService.ahas_pending"
  - "新订阅事件键 PlanClarifyCallback（91-03 飞书回调消费）"
affects: [91-03 飞书澄清回调, 91-04 会话端续推 endpoint]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "工作流节点发卡 + 订阅 mirror plan_deepen：取 pending 轮子题（按 order）→ build_clarification_card（携 clarification_id）→ ProjectService.resolve_or_create_group + FeishuIMService.send_card → WorkflowEventSubscription 超时兜底；发卡 best-effort 不反噬挂起"
    - "pending 存在性判定单一谓词收口 ahas_pending（判存在用谓词、取内容用查询，结构化子题轮不误判）"
    - "卡片回调路由前缀隔离：新 action 前缀 plan_clarify_ 与既有 chat_question_answer 物理不交叉（CardCallbackView startswith 匹配）"

key-files:
  created: []
  modified:
    - server/feishu/cards/chat_question_card.py
    - server/workflows/nodes/ai/plan_research.py
    - server/agents/tools/plan_research_tools.py
    - server/workflows/nodes/integrations/plan_deepen.py
    - server/tests/workflows/test_plan_research_node.py

key-decisions:
  - "_maybe_suspend 增 context 参数（替代另起发卡方法）：发卡 + 订阅在 CLARIFYING 分支内聚一处，mirror plan_deepen execute 结构；chat 入口（无 workflow_execution/node_execution）天然短路不发卡"
  - "发卡 best-effort try/except 包裹（T-91-02-05）；订阅 acreate 不包裹（超时兜底是可靠性机制，guard 已确保 FK 有效，失败应 surface）"
  - "WR-03 plan_deepen 收口在 _apending_clarification_question 内加 ahas_pending 前置门（零回归既有发卡：有 pending 才查内容，无则返回空——与原 clar None 返回空等价）"
  - "卡片文件 + 节点文件首次 ruff format（两文件历史从未 format-clean，本次改动行自身被 flag，故对受改文件整体 format，仅空白机械变更）"

patterns-established:
  - "Pattern: 工作流澄清出口面 = 发卡（best-effort 脱敏 + initiated_by 归因）+ 订阅（PlanClarifyCallback 超时 fail）+ waiting_event（output 携 clarification_id 供回调/重入定位）"
  - "Pattern: 索引↔question_id 映射固化——发卡按 order_by('order') 枚举 q{i}，测试断言字段名集合，便于 91-03 回调对齐"

requirements-completed: [CLARIFY-05, WR-03]

# Metrics
duration: ~18min
completed: 2026-06-27
---

# Phase 91 Plan 02: 工作流澄清发卡 + 订阅 + WR-03 收口 Summary

**工作流入口 `ai_plan_research` 在 CLARIFYING 挂起时把结构化澄清子题（按 order）发成飞书交互卡到项目群（复用扩展后的 `build_clarification_card`，携 `clarification_id` + 新 action `plan_clarify_answer`）并建 `WorkflowEventSubscription(PlanClarifyCallback)` 超时兜底；三处裸 pending 读法收口到 `ahas_pending`。**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-06-27T08:11:00Z
- **Completed:** 2026-06-27T08:29:00Z
- **Tasks:** 3
- **Files modified:** 5（4 源 + 1 测试）

## Accomplishments
- **WR-03 三处 pending 存在性收口 ahas_pending**：`plan_research.py` / `plan_research_tools.py` 的 `_maybe_suspend` CLARIFYING 分支、`plan_deepen.py` 的 `_apending_clarification_question`——存在性判定改用 `ClarificationService().ahas_pending(session.id)`（结构化子题轮：容器 answered_at 仍空但子题已答 / 反之均不误判），取问题内容仍用显式查询（分工：判存在用谓词、取内容用查询）。
- **`build_clarification_card` 扩展（CLARIFY-05 / Pitfall 1）**：新增 keyword 入参 `clarification_id: str = ""` 写进 form_submit `value`；`value.action` 由 `chat_question_answer` 改为新前缀 `plan_clarify_answer`（与工作流 GroupChatQuestion 既有路由物理不交叉，CardCallbackView 前缀 startswith 匹配）。字段命名 `q{i}`/`qt{i}` 不变，回调据 `order=i` 映射子题。
- **节点发卡 + 订阅（CLARIFY-05 / mirror plan_deepen）**：`_maybe_suspend` 增 `context` 参数，工作流入口（有 `workflow_execution`/`node_execution`）CLARIFYING 挂起时：取 pending 轮 + 其未答子题（`order_by("order")`，脱敏正文）→ `build_clarification_card(..., clarification_id=..., round_no=...)` → `_resolve_space`/`_aresolve_project` + `ProjectService().resolve_or_create_group` 解析项目群 → `FeishuIMService.send_card`；建 `WorkflowEventSubscription(event_type="PlanClarifyCallback", timeout_at=now+60min, timeout_action="fail")`。chat 入口（无 execution）不发卡、不订阅（走 91-04 会话出口面），零回归。
- **威胁缓解落实**：T-91-02-01 新前缀隔离 + 服务端权威 clarification_id；T-91-02-02 卡片正文经 `redact_secrets_in_text` 脱敏 + 日志仅记 session_id 标量；T-91-02-03 `_resolve_initiator` 带 `initiated_by_user_id`（缺记 system）；T-91-02-04 订阅 60min 超时 + fail 兜底；T-91-02-05 发卡 best-effort try/except 失败仍返回 waiting_event。

## Task Commits

Each task was committed atomically:

1. **Task 1: WR-03 三处 pending 存在性收口 ahas_pending** - `897eb78b2` (refactor)
2. **Task 2: build_clarification_card 携 clarification_id + 新 action** - `5385345bd` (feat)
3. **Task 3: ai_plan_research CLARIFYING 发卡 + PlanClarifyCallback 订阅** - `34dbde356` (feat)

**Plan metadata:** (final docs commit)

## Files Created/Modified
- `server/feishu/cards/chat_question_card.py` - `build_clarification_card` 加 `clarification_id` 入参 + form_submit `value.action="plan_clarify_answer"` + 并列 `clarification_id`（含首次 ruff format）
- `server/workflows/nodes/ai/plan_research.py` - `_maybe_suspend` 增 context + WR-03 ahas_pending 收口 + 新增 `_send_clarify_card` / `_acollect_round_questions` / `_resolve_initiator` 发卡订阅 helper（含首次 ruff format）
- `server/agents/tools/plan_research_tools.py` - chat 工具 `_maybe_suspend` CLARIFYING 存在性收口 ahas_pending
- `server/workflows/nodes/integrations/plan_deepen.py` - `_apending_clarification_question` 加 ahas_pending 前置门（零回归取内容查询）
- `server/tests/workflows/test_plan_research_node.py` - 新增 WR-03 结构化轮守护 + 卡片 action/clarification_id 守护 + 发卡订阅集成 + 发卡失败 best-effort（共 +6 用例）

## Decisions Made
- **发卡 + 订阅内聚 `_maybe_suspend`（增 context 参数）**：mirror plan_deepen 的 execute 结构，避免在 execute 再拆一层；chat 入口 context.workflow_execution 为 None 天然短路，零回归 `test_clarifying_suspends_waiting_event`。
- **订阅 acreate 不包 try/except**：发卡是 best-effort（失败不致命），但订阅是超时兜底的可靠性机制；前置 guard `if context.workflow_execution and context.node_execution` 已确保 FK 有效，失败应当 surface 而非吞掉。
- **WR-03 plan_deepen 取内容查询保留**：`_apending_clarification_question` 只加 `ahas_pending` 前置门，确认有 pending 才走既有 `order_by("-created_at")` 查询；无 pending 返回空与原 `clar None → ""` 等价，既有发卡用例零回归。
- **受改两文件首次 ruff format**：`chat_question_card.py` 与 `plan_research.py` 历史从未 `ruff format`-clean，本次改动行自身被 formatter flag；plan 验收明列 `ruff format --check` 须过，故对受改文件整体 format（纯空白机械变更，零行为）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 受改文件 ruff format 未达标致 `ruff format --check` 失败**
- **Found during:** Task 2 / Task 3 验收（plan 明列 `ruff format --check feishu/cards/chat_question_card.py workflows/nodes/ai/plan_research.py`）
- **Issue:** 两文件历史从未经 `ruff format`（全文件 `append({...})` 紧凑风格），且本次新增的 form_submit value / 发卡 helper 代码块自身也被 formatter flag，`--check` 失败。
- **Fix:** 对**受改的两个文件**整体 `uv run ruff format`（仅空白机械变更，无任何逻辑/行为改动），重跑测试零回归。未触碰其他未改文件（SCOPE BOUNDARY）。
- **Files modified:** server/feishu/cards/chat_question_card.py, server/workflows/nodes/ai/plan_research.py
- **Verification:** `ruff format --check` + `ruff check` + `mypy` 三者干净；`test_plan_research_node.py` 12 passed、`test_chat_question_card.py` 零回归。
- **Committed in:** `5385345bd`（Task 2）/ `34dbde356`（Task 3）

---

**Total deviations:** 1 auto-fixed（blocking，格式门禁）
**Impact on plan:** 仅为通过 plan 明列的 `ruff format --check` 门禁的空白机械调整，无逻辑变更、无 scope creep。

## Issues Encountered
- **10 个既有失败（与本 plan 无关，war-room 在制品）**：`tests/workflows tests/delivery -q` 出现 10 failed / 1032 passed。逐一回归基线（`git checkout 6e75293cb -- <本 plan 4 文件>` 后运行同 10 测）确认**在我改动前已 100% 同样失败**，恢复后我的文件无回归：
  - `test_execution_concurrency.py`(2)：STATE.md 已记「既有并发测试欠债」。
  - `test_template_loader.py`(2)：`generate_plan`(ai_plan_generation) 节点输出缺 `plan_markdown` 字段——属未提交 war-room（node-definitions / template）债，与本 plan 触碰的 `ai_plan_research` 无关。
  - `test_comment_entry_wiring.py`(3) / `test_entry_wiring.py`(1) / `test_inv6_guard.py::feishu_chat_id`(1) / `test_technical_plan_inv6_guard.py::canonical_plan`(1)：90-03 SUMMARY 已记的 6 项 war-room（comment-wiring / canonical-plan）失败。
  - 均源于工作区大量未提交 war-room 变更（`server/chat/`、`server/initiatives/`、`server/services/plan_orchestration/clarification_questions.py`、`web/` 等），非本 plan 引入，记 deferred-items.md。

## Threat Surface Scan
threat_model 五项 mitigate 全落实（见 Accomplishments 威胁缓解段）。无新增网络端点 / 认证路径 / schema 变化（`makemigrations --check` 无变化）；新订阅事件键 `PlanClarifyCallback` 由 91-03 服务端回调消费，卡片 value 仅携服务端权威 `clarification_id`（回调侧按 round 取轮，不信任客户端）。无新威胁面。

## Known Stubs
None - 本 plan 落地工作流出口面发卡 + 订阅 + WR-03 收口，无 UI 渲染、无 mock 数据。回调续推（消费 `PlanClarifyCallback` + `aanswer_round_and_resume`）由 91-03 接（按 ROADMAP 规划，非 stub）。

## User Setup Required
None - no external service configuration required.（飞书发卡走既有 `FeishuIMService` / `ProjectService` 凭证链，无新增配置。）

## Next Phase Readiness
- 工作流澄清出口面就绪：CLARIFYING 挂起 → 发卡（携 clarification_id + 新 action）到项目群 + 建 `PlanClarifyCallback` 订阅 + waiting_event。
- 91-03 飞书回调可注册 `@register_card_callback("plan_clarify_")`，据 `value.clarification_id` 取轮、`q{i}`(order=i) 映射子题 → 调 91-01 `aanswer_round_and_resume` 同源续推；订阅 `PlanClarifyCallback` 由回调/超时消费。
- WR-03 三处 pending 存在性单一谓词收口，结构化子题轮不误判。
- 本 plan 验收：`-k "clarif or subscription or pending"` 35 passed；`test_plan_research_node.py` 12 passed；ruff format/check + mypy 干净；`makemigrations --check` 无变化。

---
*Phase: 91-clarification-outlets-resume*
*Completed: 2026-06-27*

## Self-Check: PASSED
- FOUND: server/feishu/cards/chat_question_card.py
- FOUND: server/workflows/nodes/ai/plan_research.py
- FOUND: server/agents/tools/plan_research_tools.py
- FOUND: server/workflows/nodes/integrations/plan_deepen.py
- FOUND: server/tests/workflows/test_plan_research_node.py
- FOUND: .planning/phases/91-clarification-outlets-resume/91-02-SUMMARY.md
- FOUND commit 897eb78b2 (Task 1 WR-03)
- FOUND commit 5385345bd (Task 2 卡片扩展)
- FOUND commit 34dbde356 (Task 3 节点发卡 + 订阅)
