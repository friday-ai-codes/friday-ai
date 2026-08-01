---
phase: 107-layered-presentation
plan: 04
subsystem: api
tags: [structlog, event-taxonomy, django-settings, feishu, clarification, observability]

# Dependency graph
requires:
  - phase: 107-01
    provides: "CLARIFICATION_TIMEOUT_HOURS（settings + .env.example，默认 24）—— D-4 单一超时口径的配置载体"
provides:
  - "EVENT_CLARIFICATION_TIMED_OUT / EVENT_CLARIFICATION_DELIVERY_FAILED 两个稳定事件常量（已入 ALL_EVENTS）"
  - "_send_clarify_card 五条送达失败路径的强制留痕（结构化日志 + 会话事件 + container_status 标记），零静默 return"
  - "Clarification.container_status 新取值 delivery_failed（零迁移），供超时扫描做「立即出口」判定"
  - "WorkflowEventSubscription.timeout_at 读 CLARIFICATION_TIMEOUT_HOURS，工作流侧与会话侧同一超时口径"
  - "taxonomy 守护测试的 _PENDING_PRODUCER_EVENTS 待落地豁免机制（带子计划标注、逐行可删）"
affects: [107-06, phase-110-timeline]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "受控枚举 reason 闭集 + best-effort 留痕 helper：日志/事件/DB 标记三件事一次做齐，整体 try/except 吞掉"
    - "事件常量待落地豁免：新常量入 ALL_EVENTS 时，emit 点未落地者走带子计划标注的显式豁免字典，而非放宽 producer 登记断言"
    - "单一超时口径：跨子系统（工作流引擎订阅 / 会话澄清）的到期时间读同一 settings 键，消除矛盾态窗口"

key-files:
  created: []
  modified:
    - server/delivery/services/event_taxonomy.py
    - server/tests/services/test_event_taxonomy_alignment.py
    - server/workflows/nodes/ai/plan_research.py
    - server/tests/workflows/test_plan_research_node.py
    - server/delivery/models/clarification.py
    - server/delivery/services/clarification_service.py

key-decisions:
  - "送达失败标记复用 Clarification.container_status 的新取值 delivery_failed，不新增 ConvergenceSessionStatus 枚举值（零迁移、不撞 30 处 waiting_clarification 分支）"
  - "delivery_failed 只写 container_status，绝不写 answered_at —— pending 判定权威字段始终是 answered_at，写了该轮会被误判已答而永久失去出口"
  - "事件 payload 结构上只含 clarification_id / round_no / channel / 5 值 reason 枚举，异常原文只进已脱敏的系统日志，不进可外读的事件行"
  - "D-4 采纳 OQ-2 推荐取径 (a)：订阅 timeout_at 改读 CLARIFICATION_TIMEOUT_HOURS；timeout_action 保持 fail，会话侧出口留给 107-06 的扫描 job"
  - "容器推进幂等条件从 container_status=\"pending\" 改锚 answered_at__isnull=True（Rule 1 修复，见 Deviations）"

patterns-established:
  - "留痕 helper 模式：_amark_delivery_failed 内部自解析缺省 round_no、自校验 reason 闭集（非法值记 unknown 不抛）、整体 best-effort"
  - "plan 编号只写在会被整行删除的数据结构 value 里，块注释一律不写编号——保证「删豁免」类归零断言删得干净"

requirements-completed: [RELY-02]

coverage:
  - id: D1
    description: "两个新事件常量入 taxonomy 且双向守护（引用值 ∈ ALL_EVENTS + 每个成员有 producer 登记）继续绿"
    requirement: "RELY-02"
    verification:
      - kind: unit
        ref: "tests/services/test_event_taxonomy_alignment.py（3 项：无裸字面量 / 引用值对齐 / 覆盖性反查）"
        status: pass
      - kind: other
        ref: "uv run python -c 'assert 两常量 ∈ ALL_EVENTS 且值逐字匹配'"
        status: pass
    human_judgment: false
  - id: D2
    description: "_send_clarify_card 五条失败路径（no_questions / no_space / no_project / no_chat_id / send_failed）各记日志 + emit clarification.delivery_failed + 标 container_status=delivery_failed，零静默 return"
    requirement: "RELY-02"
    verification:
      - kind: unit
        ref: "tests/workflows/test_plan_research_node.py#test_delivery_failure_path_traced_and_marked（4 参数化）+ #test_delivery_failure_no_questions_traced"
        status: pass
    human_judgment: false
  - id: D3
    description: "送达失败事件 payload 不含异常原文/凭证，键集恰为 4 个受控字段（T-107-02 信息泄漏面）"
    requirement: "RELY-02"
    verification:
      - kind: unit
        ref: "tests/workflows/test_plan_research_node.py#test_delivery_failed_payload_excludes_exception_text"
        status: pass
    human_judgment: false
  - id: D4
    description: "留痕 best-effort 不反噬：emit 抛异常时发卡不抛、节点仍返回 waiting_event 且仍建订阅；成功路径零留痕"
    requirement: "RELY-02"
    verification:
      - kind: unit
        ref: "tests/workflows/test_plan_research_node.py#test_delivery_trace_failure_does_not_backfire_on_suspension + #test_delivery_success_leaves_no_failure_trace"
        status: pass
    human_judgment: false
  - id: D5
    description: "delivery_failed 轮仍被 ahas_pending 判 pending，且标记后仍可正常作答推进到 answered"
    requirement: "RELY-02"
    verification:
      - kind: unit
        ref: "tests/workflows/test_plan_research_node.py#test_delivery_failed_round_still_counts_as_pending + #test_delivery_failed_round_can_still_be_answered"
        status: pass
    human_judgment: false
  - id: D6
    description: "订阅 timeout_at 读 CLARIFICATION_TIMEOUT_HOURS（1/3/24 小时容差 60s）、配置缺失兜底 24h 不抛、timeout_action 仍为 fail；60 分钟字面量消失"
    requirement: "RELY-02"
    verification:
      - kind: unit
        ref: "tests/workflows/test_plan_research_node.py#test_subscription_timeout_at_follows_clarification_hours + #test_subscription_timeout_defaults_to_configured_24_hours + #test_subscription_timeout_falls_back_when_setting_missing + #test_subscription_timeout_action_unchanged"
        status: pass
    human_judgment: false
  - id: D7
    description: "生产存量活跃订阅行仍携带旧 60 分钟 timeout_at —— 本改动只影响新建订阅，存量矛盾态需 107-06 扫描器的纵深条件覆盖后才能端到端确认"
    verification: []
    human_judgment: true
    rationale: "存量行行为要在真实部署上观察（或等 107-06 扫描器落地后做联合验收），单测无法覆盖已存在的 DB 行"

# Metrics
duration: 35min
completed: 2026-07-30
status: complete
---

# Phase 107 Plan 04: 澄清必达留痕与单一超时口径 Summary

**`_send_clarify_card` 的 5 条失败路径从「完全不可见」变为「必留痕 + 有事件 + 有出口信号」，两个 `clarification.*` 事件入稳定 taxonomy，订阅超时改读 `CLARIFICATION_TIMEOUT_HOURS` 消除 23 小时矛盾态窗口**

## Performance

- **Duration:** 约 35 min
- **Started:** 2026-07-29T21:52Z
- **Completed:** 2026-07-29T22:28Z
- **Tasks:** 3（其中 2 个 TDD）
- **Files modified:** 6

## Accomplishments

- **零静默 return**：`no_questions` / `no_space` / `no_project` / `no_chat_id` 四个连 warning 都不记的静默 `return`，加上 `except` 分支共 5 条路径，逐条改为「warning 级结构化日志（带 `initiated_by_user_id`）+ emit `clarification.delivery_failed` + 该轮 `container_status` 标 `delivery_failed`」。这是「无声卡死」发卡侧成因的直接消除。
- **两个事件入稳定 taxonomy**：`clarification.timed_out`（producer 在 107-06）与 `clarification.delivery_failed`（producer 本 plan 已落地）进入 `__all__` / `ALL_EVENTS`，双向守护测试继续绿。为「emit 点未落地」新增带子计划标注的 `_PENDING_PRODUCER_EVENTS` 显式豁免机制，`assert producer is not None` 的登记强制力一字未动。
- **D-4 单一超时口径**：`WorkflowEventSubscription.timeout_at` 从写死 `now + 60min` 改为 `now + CLARIFICATION_TIMEOUT_HOURS`，工作流侧与会话侧同时到期，60 分钟字面量消失。
- **信息泄漏面收紧**：送达失败事件 payload 键集恰为 `{clarification_id, round_no, channel, reason}`，测试注入含 `sk-ant-` 的异常并断言序列化结果无明文。
- **best-effort 不反噬**：留痕 helper 整体 `try/except` 吞掉，emit/DB 写失败时发卡与节点 `waiting_event` + suspension 行为逐字不变。

## Task Commits

1. **Task 1: 两个事件常量入 taxonomy + 守护测试对齐** — `b66d6bfa` (feat)
2. **Task 2: `_send_clarify_card` 五条失败路径留痕 + emit + delivery_failed 标记** (TDD)
   - `56f8fc81` (test — RED，7 项失败)
   - `42d39fdf` (feat — GREEN)
3. **Task 3: D-4 单一超时口径** (TDD)
   - `6b970256` (test — RED，4 项失败)
   - `8f1fe669` (feat — GREEN)
4. **收尾格式** — `b35f3931` (style，仅本 plan 新增区域)

## Files Created/Modified

- `server/delivery/services/event_taxonomy.py` — 两个事件常量（含 producer / payload 形状注释与「为何不复用 `clarification.answered`」的因果），同步 `__all__` 与 `ALL_EVENTS`
- `server/tests/services/test_event_taxonomy_alignment.py` — 登记两个 producer 路径 + 纳入 `_EMIT_FILES` + 新增 `_PENDING_PRODUCER_EVENTS` 豁免（`delivery_failed` 那行在 Task 2 已删，`timed_out` 留给 107-06）
- `server/workflows/nodes/ai/plan_research.py` — `_DELIVERY_FAILURE_REASONS` 闭集、`_amark_delivery_failed` 留痕 helper、5 条路径接线、订阅 `timeout_at` 读统一配置键
- `server/tests/workflows/test_plan_research_node.py` — 新增 13 项用例（8 条送达行为 + 4 项超时口径 + 参数化）
- `server/delivery/models/clarification.py` — `container_status` docstring 补 `delivery_failed` 取值语义（仅注释，零迁移）
- `server/delivery/services/clarification_service.py` — 容器推进幂等条件改锚 `answered_at`（见 Deviations）

## Decisions Made

- **不新增 `ConvergenceSessionStatus` 枚举值**（沿用 plan 假设 A3）：送达失败标记复用既有列 `container_status` 的新取值，零迁移、不撞 30 个文件里的 `waiting_clarification` 分支。
- **`_amark_delivery_failed` 的 DB 写留在节点侧**（plan 逐字指定）。`Clarification` 的 INV-6 grep 守护只覆盖 `Clarification.objects.create`（创建），本处是送达标记的条件 `aupdate`，守护测试全绿；若 107-06 也需要写同一列，建议届时把标记方法上提到 `ClarificationService`，两处共用一个入口。
- **A4 命名空间前置确认已自动化并通过**：`git show main:.planning/technical-blueprint/DESIGN.md | rg -c 'clarification\.(timed_out|delivery_failed)'` = 0，无需改名。
- **`timeout_action` 保持 `"fail"`**：改它属工作流引擎语义面，超出本 phase 韧性边界；会话侧出口由 107-06 扫描 job 驱动。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 容器推进幂等条件被 `delivery_failed` 新取值卡死**

- **Found during:** Task 2（`_send_clarify_card` 五条失败路径留痕）
- **Issue:** `ClarificationService._maybe_advance_container` 的幂等条件是
  `Clarification.objects.filter(id=round_id, container_status="pending")`。一旦本 plan 把某轮标成
  `delivery_failed`，该条件恒不命中 → 「卡没送达但用户从会话面/REST 端点答完了全部子题」的轮，容器
  `answered_at` 永远不会落地。副作用是该轮在按 `answered_at__isnull=True` 取 pending 的查询里
  长期可见（107-06 扫描器正是这个谓词），属于本 plan 引入的新取值直接造成的破坏。
- **Fix:** 幂等条件改锚真正的 pending 权威字段：`filter(id=round_id, answered_at__isnull=True)`。
  幂等性不变（只有未答容器会被推进），且对 `container_status` 的任何展示态取值都健壮。docstring
  同步写明「`container_status` 是送达/展示态，pending 的权威字段始终是 `answered_at`」。
- **Files modified:** `server/delivery/services/clarification_service.py`
- **Verification:** 新增 `test_delivery_failed_round_can_still_be_answered`（标记后答完全部子题 →
  容器 `answered_at` 非空、`ahas_pending` 转 False）；`tests/delivery/test_clarification_service.py`
  与 `tests/delivery` 全套继续绿（1121 passed）。
- **Committed in:** `42d39fdf`（Task 2 GREEN 提交）

**2. [Rule 3 - Blocking] 留痕 helper 需要 `context` 才能绑定触发用户**

- **Found during:** Task 2
- **Issue:** plan 给的签名是 `_amark_delivery_failed(self, session, clarification_id, reason, *, round_no=None)`，
  但同一段 action 又要求日志带 `initiated_by_user_id=self._resolve_initiator(context)` —— 拿不到
  `context` 就无法满足观测规范的「绑定触发用户」硬要求。
- **Fix:** 签名加入 `context: ExecutionContext` 位置参数（`session, context, clarification_id, reason, *, round_no`）。
- **Files modified:** `server/workflows/nodes/ai/plan_research.py`
- **Verification:** 五条路径用例全绿；日志字段含 `initiated_by_user_id` / `category="caller"` / `component="plan_research"`。
- **Committed in:** `42d39fdf`

---

**Total deviations:** 2 auto-fixed（1 bug、1 blocking）
**Impact on plan:** 两项都是正确性必需，未扩大范围。DEPTH 冻结零触碰（`render.py` / `decompose_segments.py` /
`research_adapter.py` / `architect_merge_adapter.py` / `merged_plan.py` / `clarify_adapter.py` /
`spec_generation.py` / `clarification_questions.py` 全部未改，已用 `git diff --name-only` 自检）。

## Issues Encountered

- **Task 3 的 RED 有一项「假绿」风险**：behavior 里 `CLARIFICATION_TIMEOUT_HOURS=1` 恰好等于改动前写死的
  60 分钟，单测该参数在实现前就会通过。处理方式是把该用例参数化为 `[1, 3, 24]`，用 3 与 24 两个值提供真实
  RED 信号（RED 阶段 4 项失败、2 项通过）。
- **`ruff format --check` 在三个改动文件上报 drift**：逐一比对基线（`43fd4950`）确认全部为**既有**格式漂移
  （行号均在本 plan 新增区域之前）。只修正落在新增区域内的一处（`b35f3931`），未对既存区域做无关重排，避免
  污染 diff。

## User Setup Required

None —— 零新增依赖、零迁移、零新增 env 键（`CLARIFICATION_TIMEOUT_HOURS` 已由 107-01 落地并写入 `.env.example`）。

## Next Phase Readiness

- **107-06 可直接消费**：`clarification.timed_out` 常量已在 `ALL_EVENTS`；`_PENDING_PRODUCER_EVENTS` 里仅剩
  `"clarification.timed_out": "107-06"` 一行，创建 `delivery/management/commands/expire_pending_clarifications.py`
  并写入 emit 点后删除该行即可（守护测试的 producer 路径与 `_EMIT_FILES` 已预登记，无需再改注册表）。
  该文件也是 107-06 Task 3「标注归零」断言（`rg -c '107-06|107-04' = 0`）的唯一目标行。
- **107-06 需要接的两个信号**：(1) `container_status == "delivery_failed"` → 立即出口（不等满 24h）；
  (2) 「workflow 已 TIMEOUT + 会话仍 `waiting_clarification`」→ 立即出口，用于兜住生产存量活跃订阅行
  （携带旧 60 分钟 `timeout_at`，本 plan 只影响新建订阅）。
- **Phase 110 时间线**：两个事件都带 `clarification_id` 关联键与可算耗时的量（`waited_seconds` 由 107-06 填），
  按 `clarification.*` 前缀分组即可消费。
- **无阻塞项。**

## Self-Check: PASSED

- 6 个 task 提交哈希全部可在 `git log` 中查到
- 声明的 6 个改动文件全部存在于工作树
- 计划级验收全绿：`tests/workflows tests/delivery tests/services/test_event_taxonomy_alignment.py` = 1121 passed
- `ruff check` 六个改动文件全过；DEPTH 冻结自检零命中
- STATE.md / ROADMAP.md 未改动（本次执行明确要求）

---
*Phase: 107-layered-presentation*
*Completed: 2026-07-30*
