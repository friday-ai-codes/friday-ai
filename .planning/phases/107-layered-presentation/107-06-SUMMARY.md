---
phase: 107-layered-presentation
plan: 06
subsystem: infra
tags: [apscheduler, management-command, clarification, convergence-session, structlog, gauge, observability]

# Dependency graph
requires:
  - phase: 107-01
    provides: "CLARIFICATION_TIMEOUT_HOURS / CLARIFICATION_TIMEOUT_EXIT_ACTION / CLARIFICATION_EXPIRY_CHECK_INTERVAL_SECONDS / CLARIFICATION_EXPIRY_SCAN_LIMIT 四个 settings + .env.example"
  - phase: 107-04
    provides: "EVENT_CLARIFICATION_TIMED_OUT 常量与 payload 契约、container_status=delivery_failed 立即出口信号、taxonomy 守护测试的 producer 预登记与待落地豁免"
provides:
  - "expire_pending_clarifications management command：超期 pending 澄清扫描 + 三成因出口 + CAS 幂等 + dry-run/limit/session-id"
  - "stage_state.clarification_exit 会话状态契约（clarification_id/round_no/action/reason/waited_seconds/unclarified_points/at）——「未澄清假设」的唯一落点（D-6）"
  - "clarify policy 的 clarification_exit 短路：出口放行后不会被立刻重新挂起（Pitfall 6）"
  - "apscheduler job expire_pending_clarifications（IntervalTrigger ~10min、max_instances=1、失败不打断主循环）"
  - "backlog.pending_clarifications gauge：超期未答澄清轮数进 sample_gauges（趋势查询与告警阈值可读）"
  - "taxonomy 守护测试恢复无豁免原始形态（_PENDING_PRODUCER_EVENTS 整块删除）"
affects: [107-07, phase-110-timeline]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "定时出口两段式：atomic + select_for_update(skip_locked) 内只做同步读收集，异步出口在事务外 asyncio.run（逐字镜像 check_timeouts.py）"
    - "幂等靠既有状态机 CAS：出口只经 transition，ConcurrentTransitionError 捕获当 no-op，零自建互斥"
    - "出口成因受控枚举（no_answer_timeout / delivery_failed / workflow_timeout）：矛盾态与「等太久」在同一出口里可区分"
    - "gauge 块内独立 try/except + 零值也落：跨 app 采集失败只丢一行；0 是有意义的观测值（趋势图需要连续 0 才能定位积压起点）"

key-files:
  created:
    - server/delivery/management/commands/expire_pending_clarifications.py
    - server/delivery/management/__init__.py
    - server/delivery/management/commands/__init__.py
    - server/tests/delivery/test_expire_pending_clarifications.py
  modified:
    - server/agents/management/commands/runapscheduler.py
    - server/services/process_runtime/clarify_adapter.py
    - server/system/metric_sampling.py
    - server/tests/services/test_engine_clarify.py
    - server/tests/services/test_event_taxonomy_alignment.py
    - server/tests/test_metric_sampling.py
    - server/tests/agents/test_runapscheduler_backfill.py

key-decisions:
  - "出口不新增 ConvergenceSessionStatus 枚举值（A3）：resume 路径 = transition(session, \"clarified\")（→ research/running），fail 路径 = transition(session, \"fail\")；语义名 resumed_with_assumptions / failed_no_answer 只写 stage_state.clarification_exit 与事件 payload"
  - "fail 路径先条件 aupdate 写 stage_state 再 transition：transition 的 fail 特判只写 status/error（不接受 stage_state），反序会留出「已 failed 但未澄清点不可查」的窗口；条件锚 status=waiting_clarification，把「并发已推进却留下误导标注」的面收到最小"
  - "fail 路径额外核对 status 是否真为 failed：_fail 的 CAS 未命中时内部静默返回而非抛 ConcurrentTransitionError，不核对就会在 no-op 上误 emit"
  - "pending 判定锚 answered_at 并补一层「子题已全答则视为已答」的与 ahas_pending 同口径校验（同步版），不按 container_status 过滤（旧行为 NULL、新行可能是 delivery_failed）"
  - "D-4 纵深条件走 node_execution_id → NodeExecution.status / workflow_execution.status；关联缺失（chat/MCP 入口）时条件不成立且不报错"
  - "D-5 边界：chat 协商卡只在收尾统计一条 chat_clarification_unanswered_observed 采样日志，零改动 ConversationIntentTrace 行"
  - "积压进 gauge 而非只进命令汇总日志：只落日志的话趋势查询（gauge:<name>）与告警阈值都读不到，不满足观测规范强制项"

patterns-established:
  - "归零断言友好写法：凡是被 rg 归零断言盯住的字面量（session.updated_at / LangGraph 等）一律只写在 # 注释行，绝不写进 docstring——断言只滤 # 行，写进 docstring 即自我打红"
  - "出口标注与事件 payload 同源：先组一份 exit_marker，stage_state 与 event payload 都由它派生，杜绝两处字段漂移"

requirements-completed: [RELY-02]

coverage:
  - id: D1
    description: "超期未答澄清有出口：到期后按配置走「带未澄清假设继续推进」（research/running）或「如实失败」（failed + clarification_timeout_no_answer），会话不再永久停在 waiting_clarification"
    requirement: "RELY-02"
    verification:
      - kind: unit
        ref: "tests/delivery/test_expire_pending_clarifications.py#test_expired_round_resumes_with_assumptions + #test_exit_action_fail_marks_session_failed_once"
        status: pass
    human_judgment: false
  - id: D2
    description: "出口幂等复用 transition CAS：连跑两次只推进一次只 emit 一次；ConcurrentTransitionError 当 no-op；零自建互斥机制"
    requirement: "RELY-02"
    verification:
      - kind: unit
        ref: "tests/delivery/test_expire_pending_clarifications.py#test_second_scan_is_idempotent + #test_concurrent_transition_conflict_is_noop"
        status: pass
      - kind: other
        ref: "rg -c 'advisory_lock|Redis|threading.Lock' delivery/management/commands/expire_pending_clarifications.py = 0"
        status: pass
    human_judgment: false
  - id: D3
    description: "起算时间取 pending 轮 Clarification.created_at（刷新会话行后仍命中）；旧行 container_status 为 NULL 仍被收集"
    requirement: "RELY-02"
    verification:
      - kind: unit
        ref: "tests/delivery/test_expire_pending_clarifications.py#test_start_time_is_round_created_at_not_session_touch + #test_legacy_round_with_null_container_status_is_collected"
        status: pass
      - kind: other
        ref: "rg -v '^[[:space:]]*#' <command> | rg -c 'updated_at' = 0"
        status: pass
    human_judgment: false
  - id: D4
    description: "边界三条各不动：未到期 / 已答 / 终态（done、failed）"
    requirement: "RELY-02"
    verification:
      - kind: unit
        ref: "tests/delivery/test_expire_pending_clarifications.py#test_not_expired_round_untouched + #test_answered_round_untouched + #test_terminal_session_not_collected（2 参数化）"
        status: pass
    human_judgment: false
  - id: D5
    description: "两条立即出口（不等满超时）：该轮 container_status=delivery_failed；工作流侧已 TIMEOUT 而会话仍等澄清（D-4 纵深防御，含「工作流未超时不误伤」反向用例）"
    requirement: "RELY-02"
    verification:
      - kind: unit
        ref: "tests/delivery/test_expire_pending_clarifications.py#test_delivery_failed_round_exits_immediately + #test_workflow_timeout_exits_immediately + #test_running_workflow_does_not_trigger_immediate_exit + #test_exit_reason_is_controlled_enum"
        status: pass
    human_judgment: false
  - id: D6
    description: "「未澄清假设」只写 stage_state.clarification_exit（含逐条 question_id/question，正文经 redact_secrets_in_text），零触碰 DEPTH 冻结渲染文件"
    requirement: "RELY-02"
    verification:
      - kind: unit
        ref: "tests/delivery/test_expire_pending_clarifications.py#test_unclarified_points_carry_question_id_and_text + #test_unclarified_points_are_redacted"
        status: pass
      - kind: other
        ref: "git diff --name-only | rg 'clarification_questions.py|spec_generation.py|merged_plan.py|architect_merge_adapter.py|render.py|decompose_segments.py|research_adapter.py' → 零命中"
        status: pass
    human_judgment: false
  - id: D7
    description: "出口可归因 + 事务安全：日志/事件带 initiated_by_user_id（无则 system）；transition 调用时不在 atomic 块内；单条失败不影响其余且退出码 0"
    requirement: "RELY-02"
    verification:
      - kind: unit
        ref: "tests/delivery/test_expire_pending_clarifications.py#test_exit_log_binds_initiated_by_user（2 参数化）+ #test_transition_runs_outside_atomic_block + #test_single_session_failure_does_not_block_others"
        status: pass
    human_judgment: false
  - id: D8
    description: "运维开关：--dry-run 零写库零 emit 且 stdout 逐条列出、--limit 截断、--session-id 定向"
    requirement: "RELY-02"
    verification:
      - kind: unit
        ref: "tests/delivery/test_expire_pending_clarifications.py#test_dry_run_has_zero_side_effects + #test_limit_caps_processed_sessions + #test_session_id_targets_single_session"
        status: pass
      - kind: other
        ref: "空库 uv run python manage.py expire_pending_clarifications --dry-run → 「扫描 0 个等待澄清会话，命中 0 个出口目标」，退出码 0"
        status: pass
    human_judgment: false
  - id: D9
    description: "出口后不会被 clarify policy 立刻重新挂起：policy 最前置读 stage_state.clarification_exit 短路（即使 routing 全 low + ambiguous 为真）；无标注时三条既有规则零回归"
    requirement: "RELY-02"
    verification:
      - kind: unit
        ref: "tests/services/test_engine_clarify.py#test_default_policy_short_circuits_after_clarification_exit + #test_default_policy_unchanged_without_clarification_exit（既有 clarify 用例继续绿）"
        status: pass
    human_judgment: false
  - id: D10
    description: "apscheduler job 注册：IntervalTrigger 间隔取 CLARIFICATION_EXPIRY_CHECK_INTERVAL_SECONDS、max_instances=1、replace_existing=True，wrapper 归因 system 且吞异常不打断主循环"
    requirement: "RELY-02"
    verification:
      - kind: unit
        ref: "tests/agents/test_runapscheduler_backfill.py#test_scheduler_registers_expire_pending_clarifications_job + #test_expire_pending_clarifications_job_calls_command + #test_expire_pending_clarifications_job_swallows_error"
        status: pass
    human_judgment: false
  - id: D11
    description: "积压可被快照采集：backlog.pending_clarifications 入 _GAUGE_NAMES 且 sample_gauges 每帧落一行（含零值、labels 恒空），块内失败只丢该行；metrics_query.py 零改动"
    requirement: "RELY-02"
    verification:
      - kind: unit
        ref: "tests/test_metric_sampling.py#test_sample_gauges_counts_expired_pending_clarifications + #test_sample_gauges_writes_zero_backlog_row + #test_sample_gauges_backlog_block_failure_isolated"
        status: pass
      - kind: other
        ref: "git diff --name-only | rg 'system/metrics_query.py' → 零命中；tests/test_metrics_query.py 继续绿"
        status: pass
    human_judgment: false
  - id: D12
    description: "taxonomy 守护测试恢复无豁免形态：_PENDING_PRODUCER_EVENTS 整块删除，clarification.timed_out 由真实 emit 点满足覆盖性反查，producer 登记与 _EMIT_FILES 保留"
    requirement: "RELY-02"
    verification:
      - kind: unit
        ref: "tests/services/test_event_taxonomy_alignment.py（3 项守护全绿）"
        status: pass
      - kind: other
        ref: "rg -c '107-06|107-04' tests/services/test_event_taxonomy_alignment.py = 0 且 rg -c '_PENDING_PRODUCER_EVENTS' = 0 且 assert producer is not None 仍为 1 处"
        status: pass
    human_judgment: false
  - id: D13
    description: "生产存量卡死会话（CONTEXT 记录会话 ccd817d9 等）首次上线的实际影响面——需运维先跑 --dry-run 看清将被批量推进的会话，其中可能有已被人工绕道处理过的轮"
    verification: []
    human_judgment: true
    rationale: "存量数据只存在于生产库，单测无法覆盖；批量推进可能对已被人工绕道处理的会话产生重复产出，必须由运维在真实库上 dry-run 后判断是否分批"

# Metrics
duration: 30min
completed: 2026-07-30
status: complete
---

# Phase 107 Plan 06: 澄清超时出口与积压可观测 Summary

**新增 `expire_pending_clarifications` 扫描命令（两段式事务 + 复用 `transition` CAS 幂等 + 三成因受控出口），会话不再永久停在 `waiting_clarification`；出口标注写 `stage_state.clarification_exit` 并由 clarify policy 短路消费，超期积压进 `backlog.pending_clarifications` gauge**

## Performance

- **Duration:** 约 30 min
- **Started:** 2026-07-29T22:57Z
- **Completed:** 2026-07-29T23:27Z
- **Tasks:** 3（全部 TDD）
- **Files modified:** 11（4 新建 + 7 修改）

## Accomplishments

- **RELY-02 的时间维度出口补齐**：`ConvergenceSession` 停在 `waiting_clarification` 且 pending 轮已超期时，扫描器按 `CLARIFICATION_TIMEOUT_EXIT_ACTION` 走 `transition(session, "clarified")`（→ `research`/`running`）或 `transition(session, "fail")`（→ `failed` + `clarification_timeout_no_answer`）。这断掉了生产事故「无人应答 → 会话永久挂起 → agent 绕道徒手编方案」的前提。
- **幂等零新机制**：出口只经 `ConvergenceSessionService.transition`（INV-6 唯一状态入口），其 `current_stage == from_stage` 条件更新即 CAS；`ConcurrentTransitionError` 捕获当 no-op。收集查询用 `select_for_update(skip_locked=True)` 让并发扫描互不阻塞，`max_instances=1` 防 job 重叠——三层齐备且**零自建锁**。
- **两段式事务纪律**：`atomic()` 块内只做同步读收集，异步出口在事务外 `asyncio.run`（Pitfall 9）。测试用 monkeypatch 在 `transition` 调用点断言 `in_atomic_block is False`，把纪律钉成回归。
- **三条出口成因受控枚举**：`no_answer_timeout`（等满超时）/ `delivery_failed`（卡没送出去，等 24h 无意义）/ `workflow_timeout`（D-4 纵深：工作流已判超时而会话仍在等，兜住携带旧 60 分钟到期时间的存量订阅行）。成因同时进 `stage_state` 与事件 payload，Phase 110 时间线可区分。
- **出口后不再被立刻重挂**：`default_needs_clarification` 最前置读 `stage_state["clarification_exit"]` 短路（Pitfall 6）——即使 routing 候选全 low、`decomposition.ambiguous` 为真也不再追问。改动只有 7 行判定代码，不碰 prompt / schema / 产出结构（D-6）。
- **积压进 gauge 而非只进日志**：`backlog.pending_clarifications` 入 `_GAUGE_NAMES` + `sample_gauges` 块六每帧落一行（零值也落，`labels` 恒空）。`backlog.` 前缀已在查询侧受控前缀内 → `metrics_query.py` 零改动，趋势查询与告警阈值直接可读。
- **运维面**：`--dry-run`（零写库零 emit，逐条列出会话/轮/等待时长/成因）、`--limit`（默认 `CLARIFICATION_EXPIRY_SCAN_LIMIT=200`）、`--session-id`（定向处置）。首次上线的存量影响面由运维先跑 dry-run 看清。
- **taxonomy 恢复无豁免**：`_PENDING_PRODUCER_EVENTS` 整块删除（含 `if event in ...: continue` 分支），`clarification.timed_out` 现由真实 emit 点满足覆盖性反查；107-04 预登记的 producer 路径与 `_EMIT_FILES` 一字未动。

## Task Commits

1. **Task 1: 命令核心（扫描 + 出口 + 幂等 + stage_state + 事件）** (TDD)
   - `5c5dd189` (test — RED，12 项失败)
   - `29468ba6` (feat — GREEN，12 项通过)
2. **Task 2: 边界、两条立即出口与运维开关（含 D-5 观测）** (TDD)
   - `b26fce3c` (test — RED，3 项失败 / 21 项通过)
   - `95f7a15b` (feat — GREEN，24 项通过)
3. **Task 3: job 注册 + policy 短路 + 积压 gauge + 豁免删除** (TDD)
   - `6fda9c93` (test — RED，7 项失败)
   - `c87e27e5` (feat — GREEN，43 项通过)

## Files Created/Modified

- `server/delivery/management/commands/expire_pending_clarifications.py`（新建）— 扫描 + 三成因判定 + 出口 + `stage_state.clarification_exit` + emit + 归因日志 + dry-run/limit/session-id + D-5 观测块
- `server/delivery/management/__init__.py` / `server/delivery/management/commands/__init__.py`（新建）— delivery app 首个 management command 包
- `server/tests/delivery/test_expire_pending_clarifications.py`（新建）— 24 项用例（含 2 组参数化）覆盖出口/幂等/边界/立即出口/开关/归因/事务纪律/脱敏/D-5
- `server/agents/management/commands/runapscheduler.py` — `expire_pending_clarifications_job` wrapper + `IntervalTrigger` 注册（含「改间隔需清 `django_apscheduler_djangojob` 旧行」的部署注释）
- `server/services/process_runtime/clarify_adapter.py` — `default_needs_clarification` 的 `clarification_exit` 短路（+8 行，含因果注释）
- `server/system/metric_sampling.py` — `_GAUGE_NAMES` 追加 `backlog.pending_clarifications` + `sample_gauges` 块六（独立兜底、零值也落）
- `server/tests/services/test_engine_clarify.py` — policy 短路 2 项
- `server/tests/services/test_event_taxonomy_alignment.py` — 删除待落地豁免块与分支，注释同步
- `server/tests/test_metric_sampling.py` — 积压 gauge 3 项 + 既有「不可用源」用例断言收窄
- `server/tests/agents/test_runapscheduler_backfill.py` — job wrapper/注册 3 项

## Decisions Made

- **不新增状态枚举值（沿用 A3）**：`resumed_with_assumptions` / `failed_no_answer` 是语义名，只写 `stage_state.clarification_exit` 与事件 payload。看板上「超时放行」与「正常运行」在 `status` 上不可区分，属本 phase 已知局限（需要新状态或投影层字段，`workflows/lifecycle_projection.py`）。
- **fail 路径的写入顺序**：先条件 `aupdate` 落标注（锚 `status=waiting_clarification`），再 `transition(session, "fail")`。因为 `transition` 的 fail 特判只写 `status`/`error`、不接受 `stage_state`；反序会留出「已进 failed 终态但未澄清点不可查」的窗口（T-107-04 出口必留痕）。
- **fail 路径额外核对终态**：`_fail` 的 CAS 未命中时是内部静默返回（不抛 `ConcurrentTransitionError`），故出口后核对 `status == failed`，否则按 no-op 处理——不核对会在并发场景下误 emit 第二条 `clarification.timed_out`。
- **pending 判定同口径而非同函数**：收集阶段在事务内同步执行，无法调 async 的 `ahas_pending`，故写了同步版同口径判定（`Clarification.answered_at IS NULL` + 「有子题且子题已全答则视为已答」），并在 docstring 里写明与 `ahas_pending` 的对应关系。
- **积压 gauge 口径刻意与出口判定不完全一致**：gauge 只算「等太久」（同一个 `CLARIFICATION_TIMEOUT_HOURS` + `answered_at__isnull=True`），不含两条立即出口条件——`delivery_failed` / `workflow_timeout` 是矛盾态而非积压，混进去会让积压趋势读不出「等待时长」的含义。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] fail 路径缺「CAS 未命中」核对，会在并发下误 emit**

- **Found during:** Task 1（命令核心）
- **Issue:** plan 的骨架统一靠捕获 `ConcurrentTransitionError` 表达幂等 no-op，但 `ConvergenceSessionService._fail` 并**不抛**该异常：CAS 命中 0 行时它 re-fetch 状态后静默 `return session`。照骨架直写会在「并发已推进」的 fail 路径上继续 emit `clarification.timed_out` 并记「已出口」，直接打破 must-have「只推进一次只 emit 一次」。
- **Fix:** fail 路径在 `transition` 之后核对 `session.status == FAILED`；不成立则记 `clarification_timeout_exit_noop_concurrent` 并返回 no-op（与 resume 路径的语义对齐）。
- **Files modified:** `server/delivery/management/commands/expire_pending_clarifications.py`
- **Verification:** `#test_exit_action_fail_marks_session_failed_once`（连跑两次仍只 1 条事件）+ `#test_concurrent_transition_conflict_is_noop`
- **Committed in:** `29468ba6`

**2. [Rule 2 - Missing Critical] pending 判定需补「子题已全答」校验，否则可能对已答轮误出口**

- **Found during:** Task 1
- **Issue:** plan 指定收集查询为 `Clarification.answered_at__isnull=True`。但容器的 `answered_at` 由 `_maybe_advance_container` 推进；若整轮子题已答而容器推进因故未落地（107-04 Deviation 1 修的正是这一类），该轮会被判 pending 并被超时出口——与 `ahas_pending` 的判定相反，等于「用户答完了却被标成无人应答」。
- **Fix:** `_pending_round` 逐轮跳过「有子题且无未答子题」的容器，与 `ahas_pending` 同口径；收集谓词仍是 `answered_at__isnull=True`（不按 `container_status` 过滤，满足验收断言）。
- **Files modified:** `server/delivery/management/commands/expire_pending_clarifications.py`
- **Verification:** `#test_answered_round_untouched`；`tests/delivery/test_clarification_service.py` 全套继续绿
- **Committed in:** `29468ba6`

**3. [Rule 3 - Blocking] 既有 `sample_gauges` 测试与「零值也落」互斥**

- **Found during:** Task 3（积压 gauge）
- **Issue:** `test_sample_gauges_skips_unavailable_sources` 断言两个源都 `available=False` 时 `written == 0` 且 `GaugeSample` 零行。块六恒落一行（plan 明确要求零值也落）后该断言必红。
- **Fix:** 把该用例断言从「零行」收窄为「落库 name 集合恰为 `{backlog.pending_clarifications}`」——原意「不可用源不产 0 噪声」被完整保留且更精确，并在 docstring 写明与积压块的区别。
- **Files modified:** `server/tests/test_metric_sampling.py`
- **Verification:** `tests/test_metric_sampling.py` 全套绿（含新增 3 项）
- **Committed in:** `6fda9c93`（RED 提交内即含该调整）

### Plan-directed adjustments（非缺陷，记录以便追溯）

- **job wrapper/注册测试落在 `tests/agents/test_runapscheduler_backfill.py`**（plan 的 `files_modified` 未列该文件）：`<behavior>` 第 3/4 条要求断言 scheduler job 属性与 wrapper 吞异常，而 MemoryJobStore + `KeyboardInterrupt` 的注册测试脚手架只在该文件里存在；plan 的验收套本身也已包含它。新增 3 项，未改动既有用例逻辑。
- **`runapscheduler.py` 的 job 间隔提取为局部变量** `clarification_expiry_interval`：直接把 `getattr(...)` 内联进 `logger.info` 的 f-string 会超出 100 列并被 `ruff format` 重排到本 plan 之外的区域，提取后新增区域格式干净（该文件存在**既有**格式漂移，基线亦为 `would reformat`，故未对全文件跑 format）。

---

**Total deviations:** 3 auto-fixed（2 missing-critical、1 blocking）
**Impact on plan:** 三项都是正确性/一致性必需，未扩大范围。DEPTH 冻结零触碰（`git diff --name-only` 自检对 7 个冻结文件零命中）；`system/metrics_query.py` 零改动。

## Issues Encountered

- **本地 dev SQLite 未 migrate**（`no such table: delivery_convergence_session`），`manage.py ... --dry-run` 首次冒烟失败。这是工作树环境状态而非命令缺陷：改用临时库（`migrate --run-syncdb` 到一个 /tmp 下的 sqlite 文件）复跑，输出「扫描 0 个等待澄清会话，命中 0 个出口目标」且退出码 0，临时库已删除。
- **归零断言的自引用陷阱**：`updated_at` 与 `LangGraph` 两个字面量都被本 plan 要求写进因果说明，而断言只滤 `#` 注释行。落地时把两处说明都写成 `#` 注释（不进 docstring），两条断言均为 0。
- **`ruff format` 在被改测试文件上有既有漂移**：格式化时顺带规范了本 plan 新增区域之外的既有片段（`test_event_taxonomy_alignment.py` 的一处 dict comprehension、`test_runapscheduler_backfill.py` 的若干 wrap）。纯格式、零语义变化；`runapscheduler.py` 因漂移较多改为只手工保证新增区域格式（用 `ruff format --diff` 核对新增区域零命中）。

## User Setup Required

None —— 零新增依赖、零迁移、零新增 env 键（四个 `CLARIFICATION_*` 键已由 107-01 落地并写入 `.env.example`）。

**运维首次上线建议（非阻塞）**：先在生产执行 `python manage.py expire_pending_clarifications --dry-run` 看清存量卡死会话的影响面（CONTEXT 记录会话 `ccd817d9` 有 2 条），必要时用 `--limit` / `--session-id` 分批处置。

## Next Phase Readiness

- **107-07 / Phase 110 可直接消费**：`stage_state.clarification_exit` 字段集稳定（`clarification_id` / `round_no` / `action` / `reason` / `waited_seconds` / `unclarified_points` / `at`），`clarification.timed_out` 事件 payload 与之同源；按 `clarification.*` 前缀分组即可拉时间线。
- **观测大盘**：`gauge:backlog.pending_clarifications` 即刻可查趋势，可按需配置告警阈值（本 plan 未设阈值）。
- **已知局限（留给后续 phase）**：(1) 「超时放行」在 `status` 上与「正常运行」不可区分，若产品要求看板区分需新状态或投影层字段；(2) chat 单题澄清（`ConversationIntentTrace` + 中断恢复语义）只观测不出口（D-5）；(3) 存量会话首次批量推进的实际影响面须运维 dry-run 后确认（coverage D13）。
- **无阻塞项。**

## Self-Check: PASSED

- 6 个 task 提交哈希全部可在 `git log` 中查到（`5c5dd189` / `29468ba6` / `b26fce3c` / `95f7a15b` / `6fda9c93` / `c87e27e5`）
- 声明的 4 个新建文件与 7 个修改文件全部存在于工作树
- 计划级验收套全绿：`tests/delivery/test_expire_pending_clarifications.py tests/delivery/test_clarification_service.py tests/services/test_engine_clarify.py tests/services/test_event_taxonomy_alignment.py tests/agents/test_runapscheduler_backfill.py tests/test_metric_sampling.py tests/test_metrics_query.py` = 99 passed
- 额外回归：`tests/services/process_runtime/test_clarify_question_builder_order.py tests/services/test_architect_merge_adapter.py tests/workflows/test_plan_research_node.py` = 56 passed
- `ruff check` 9 个改动文件全过；DEPTH 冻结与 `metrics_query.py` 自检零命中；全部归零断言（`updated_at` / `LangGraph` / 自建锁 / `.update(...status` / 豁免标注 / labels 泄漏）实测为 0
- STATE.md / ROADMAP.md 未改动（本次执行明确要求）

---
*Phase: 107-layered-presentation*
*Completed: 2026-07-30*
