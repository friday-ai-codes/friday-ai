---
phase: 94-entrypoint-unify
plan: 05
subsystem: api
tags: [plan_orchestration, clarification, chat, marker, unify, single-source, async]

# Dependency graph
requires:
  - phase: 91-04
    provides: runtime pending_plan_clarification（结构化轮 questions[]）+ 会话端 plan 澄清专路由 POST /conversations/{id}/plan-clarification/answer/ → aanswer_round_and_resume（收答续推单一来源）
  - phase: 42-01
    provides: start_plan_research chat 入口薄封装 + _maybe_suspend CLARIFYING/RESEARCHING 挂起映射
provides:
  - plan 编排澄清挂起独立渲染 marker PLAN_CLARIFICATION_RENDER_MARKER="plan_clarification"（导出，仅前端渲染信号）
  - _maybe_suspend CLARIFYING 分支切独立 marker + 携 session_id/clarification_id（物理隔离 chat 单题 ask_clarification 路径）
  - 二义消除守护测试（后端 marker 独立性 + 不被 _extract_pending_clarification 捕获 + chat 单题对照零回归；前端 plan 卡 runtime 驱动 + marker 字面非依赖）
affects: [94-03 MCP delegate, 94 入口统一收口]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "挂起表示单一来源收口：plan 澄清挂起/续推权威唯一在 delivery.Clarification + PlanSession，marker 降级为纯前端渲染信号（去耦表示与权威）"
    - "marker 物理隔离：plan 澄清用独立常量值（!= ask_clarification）使 chat graph _extract_pending_clarification 双条件（name + marker）必不命中，杜绝误路由进 chat 单题 interrupt"

key-files:
  created: []
  modified:
    - server/agents/tools/plan_research_tools.py
    - server/tests/agents/test_start_plan_research_tool.py
    - web/src/stores/__tests__/chat.clarification.spec.ts

key-decisions:
  - "marker 取独立字面值 plan_clarification（非新增结构字段）即足以物理隔离——chat graph 双条件 name+marker 任一不命中即返回 None，无需改动 graph._extract_pending_clarification"
  - "Task 3 不改 chat.ts 生产代码：91-04 已以 runtime pending_plan_clarification（session_id/clarification_id/questions）驱动 plan 卡，本来就不读 marker 字面值；仅补断言固化该不变量"
  - "前端 ② 用例显式切 legacy parts 协议（localStorage chat-parts-protocol=legacy）覆盖 ask_clarification tool_use_* 解析分支的 marker 双条件（new 协议下走 part_* 路径）"

patterns-established:
  - "Pattern: 挂起/续推权威与渲染信号去耦——marker 仅渲染、权威落领域模型 + 专路由，改 marker 名不触权威链"
  - "Pattern: 跨链路误路由防护用独立字面值常量 + 双条件过滤，物理隔离优于运行时分支判断"

requirements-completed: [UNIFY-05]

# Metrics
duration: ~12min
completed: 2026-06-27
---

# Phase 94 Plan 05: 对话方案澄清挂起单一来源收口 Summary

**`start_plan_research._maybe_suspend` 的 CLARIFYING 分支改用独立渲染 marker `PLAN_CLARIFICATION_RENDER_MARKER="plan_clarification"`（不再复用 chat 单题 `ask_clarification`），携 `session_id`+`clarification_id` 让前端走 plan 多题卡；挂起/续推权威唯一收敛到 `delivery.Clarification`+`PlanSession`+91-04 专路由，marker 降级为纯前端渲染信号——彻底切断「marker 偷渡进 chat 单题 `_extract_pending_clarification` → 写 `ConversationIntentTrace` → 不续推 PlanSession」误路由（T-94-05-MARKER）。**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-06-27T15:21:00Z
- **Completed:** 2026-06-27T15:33:00Z
- **Tasks:** 3
- **Files modified:** 3（1 生产 + 2 测试）

## Accomplishments
- **plan 澄清独立渲染 marker（UNIFY-05 收口）**：`plan_research_tools.py` 顶定义 `PLAN_CLARIFICATION_RENDER_MARKER: Final[str] = "plan_clarification"`（docstring 注明仅前端渲染信号、权威在 delivery.Clarification+PlanSession、收答经 91-04 专路由），`_maybe_suspend` CLARIFYING 分支**移除** `from agents.tools.clarification import CLARIFICATION_PENDING_MARKER` 复用、`marker` 改用独立常量，保留 `session_id`/`clarification_id`/`pending`/`question`/`options`/`allow_freeform`。RESEARCHING 分支（`__blocking_task__` + register_blocking_task）逐字零回归。常量导出 `__all__`。
- **二义消除守护测试（后端，Wave 0 缺口）**：① CLARIFYING 挂起 `_maybe_suspend` 输出 `marker=="plan_clarification"` 且携 session_id+clarification_id；② 包成 `_extract_pending_clarification` 入参（`{"tc1":{"name":"start_plan_research","result":<output>}}`）断言返回 None，纵深含「名字被错填成 ask_clarification 但 marker 不命中仍 None」的 marker 单独隔离断言；③ chat 单题 `ask_clarification` 工具 output marker 仍 `=="ask_clarification"` 且能被 `_extract_pending_clarification` 捕获（对照零回归）。
- **前端零回归守护（WARNING 3）**：`chat.clarification.spec.ts` ① 经真实 `restoreConversationRuntime`（mock `getConversationRuntime` 返回不含任何 marker 字段的 `pending_plan_clarification` runtime）断言 plan 卡按 `clarification_id` 渲染成功（证明 marker 字面非渲染依赖）+ conversation 维度绑定 + 未误入 chat 单题 Map；旁证 questions 为空不进 plan 面；② chat 单题路径仍仅认 `marker==='ask_clarification'`——renamed `plan_clarification` marker 不被误认单题卡，对照 `ask_clarification` 仍认（legacy parts 协议下覆盖 marker 双条件）。

## Task Commits

Each task was committed atomically:

1. **Task 1: plan 澄清挂起改用独立渲染 marker** - `d4edb83c5` (feat)
2. **Task 2: 二义消除守护测试（后端）** - `69bef698a` (test)
3. **Task 3: 前端零回归守护——plan 澄清卡不依赖 marker 字面值** - `ee69076ee` (test)

**Plan metadata:** (final docs commit)

## Files Created/Modified
- `server/agents/tools/plan_research_tools.py` - 新增 `PLAN_CLARIFICATION_RENDER_MARKER` 常量 + `_maybe_suspend` CLARIFYING 分支切独立 marker（去 chat 单题 marker 复用）+ `__all__` 导出
- `server/tests/agents/test_start_plan_research_tool.py` - 新增 3 守护用例（plan marker 独立性 / 不被 chat 单题 extractor 捕获 + marker 单独隔离纵深 / chat 单题对照零回归）
- `web/src/stores/__tests__/chat.clarification.spec.ts` - 新增 4 守护用例（plan 卡 runtime 驱动 marker 字面非依赖 / questions 空不进面 / renamed plan marker 不被 chat 单题误认 / ask_clarification 仍认零回归）

## Decisions Made
- **marker 取独立字面值即足够物理隔离**：`_extract_pending_clarification` 已是 `name=="ask_clarification"` AND `marker=="ask_clarification"` 双条件，plan 工具 name 本就是 `start_plan_research`、marker 改独立值后两条件均不命中——无需改动 graph 代码、无需新增结构字段。
- **Task 3 不改生产代码**：91-04 落地的 `restoreConversationRuntime` 已据 `runtime.pending_plan_clarification`（clarification_id/round_no/questions）调 `upsertPlanClarification`，回灌路径**不读 marker**；本任务确认该不变量成立并补断言固化（plan 预期：若暴露生产依赖 marker 则回 Task 1，实测未触发）。
- **前端 ② 用例切 legacy parts 协议**：`ask_clarification` 工具结果的 marker 双条件解析在 legacy `tool_use_*` 分支（`'new'` 协议下走 `part_*`），测试显式 `localStorage.setItem('chat-parts-protocol','legacy')`（生产灰度同机制，见 `useChatPartsProtocol`）覆盖该分支，afterEach 清理。

## Deviations from Plan
None - plan executed exactly as written.

观测豁免成立：仅改 marker 字面 + 字段透传，无新增调用入口 / LLM 调用 / 召回 / 队列 / webhook，无需新埋点（plan Task 1 已注明）。

## Issues Encountered
- **前端 chat 单题 ②对照用例首跑断言失败（expected undefined to be defined）**：`_dispatchSSE` 在默认 `'new'` parts 协议下直接 `return` 掉 `tool_use_start`/`tool_use_result`（line 1504），ask_clarification marker 解析在 legacy 分支。解决：用例内 `localStorage.setItem('chat-parts-protocol','legacy')` 切 legacy 协议覆盖该路径（与生产灰度同机制），afterEach 清理；plan 卡 runtime 测试不经 SSE 故不受影响。
- **vue-tsc：PlanClarificationPayload → Record<string,unknown> 直转报 TS2352**：plan 卡断言 `marker` 字段不存在时直转触发「类型不充分重叠」。解决：先 `as unknown as Record<string, unknown>` 再断言（test-only，不影响生产类型）。

## User Setup Required
None - no external service configuration required.

## Threat Surface Scan
threat_model 三项均落实：
- **T-94-05-MARKER（Tampering 澄清 marker 二义）**：独立 `plan_clarification` marker，物理不被 chat graph `_extract_pending_clarification`（双条件 name+marker）捕获——后端测试 ② 直证返回 None（含 marker 单独隔离纵深）；前端测试 ② 直证 renamed marker 不被 chat 单题误认；收答唯一经 91-04 专路由 → aanswer_round_and_resume。
- **T-94-05-ELEV（Elevation 跨用户/跨会话续推）**：复用 91-04 既有 owner gate（created_by_id + has_project_access，无 superuser bypass），本 plan 不新建收答入口、不绕过——未触及收答 view。
- **T-94-05-SC（依赖安装）**：本 plan 无 npm/pip 安装（仅改 marker 常量 + 测试），无供应链面。

无新增网络端点 / auth 路径 / 文件访问 / schema 变化（`makemigrations --check` 无新迁移）；新威胁面已全部登记在 threat_model 内。

## Known Stubs
None - 本 plan 落地 marker 单一来源收口 + 三维度守护测试，无 mock 数据、无未接线 UI（plan 澄清卡渲染由 91-04/91-05 runtime 链路驱动，本 plan 仅固化其 marker 字面非依赖不变量）。

## Next Phase Readiness
- UNIFY-05 闭环：对话方案澄清挂起表示单一来源成立（marker 仅渲染信号、权威在 delivery.Clarification+PlanSession），三入口统一收口的「澄清二义」隐患消除。
- 验收全绿：`tests/agents/test_start_plan_research_tool.py`(9) + `tests/test_ask_clarification_tool.py`(15) + `tests/test_plan_clarification_answer_endpoint.py`(13) 全 37 passed；`chat.clarification.spec.ts`(20) 全绿；ruff format/check + mypy(plan_research_tools.py) 干净、vue-tsc --noEmit 通过、受改文件 eslint 干净、无新迁移。
- 下游 Wave 2/3：94-03（MCP create_feishu_technical_plan delegate）/ 94-04（create_coding_plan delegate）待执行。

---
*Phase: 94-entrypoint-unify*
*Completed: 2026-06-27*

## Self-Check: PASSED
- FOUND: server/agents/tools/plan_research_tools.py（PLAN_CLARIFICATION_RENDER_MARKER + _maybe_suspend 独立 marker）
- FOUND: server/tests/agents/test_start_plan_research_tool.py（3 守护用例）
- FOUND: web/src/stores/__tests__/chat.clarification.spec.ts（4 守护用例）
- FOUND: .planning/phases/94-entrypoint-unify/94-05-SUMMARY.md
- FOUND commit d4edb83c5 (Task 1 feat)
- FOUND commit 69bef698a (Task 2 test)
- FOUND commit ee69076ee (Task 3 test)
- 验收：backend 37 passed + frontend 20 passed；ruff/mypy/vue-tsc/eslint 干净；无新迁移
