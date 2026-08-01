---
phase: 107-layered-presentation
plan: 05
subsystem: api
tags: [repo-router, stage1, retry-budget, rank-swap-budget, convex-combination, model-usage-record, observability]

# Dependency graph
requires:
  - phase: 107-layered-presentation
    provides: "107-01 的 clamp_llm_permutation / blend_ranked_scores / classify_degrade_reason 三个纯函数与总预算·退避两个 settings 键；107-03 的 score_ranked 旁路字段与 _rank_value / _rank_sort_key / _apply_presentation"
  - phase: 105-golden-set
    provides: "degraded / router_version / 确定性 confidence / Stage 1 输入哈希缓存与固定 decode"
  - phase: 106-multi-signal-scoring
    provides: "六信号可拆解打分与 Σbreakdown == score 恒等式（本 plan 一行未动）"
provides:
  - "Stage 1 有界调用：首调 + 1 次重试共享同一个 budget_deadline，per-attempt 超时取 min(per_call, 剩余预算)，预算耗尽即刻降级不发第二次调用"
  - "_is_retryable_stage1_error：与 classify_degrade_reason 同口径的可重试判定（只吃异常类型名）"
  - "_stage1_seconds：秒级时长参数的 fail-safe 读取（非数值/非有限/非正值回退默认，绝不抛）"
  - "K=3 rank-swap 裁剪接线：裁剪产物即候选返回顺序；凸组合结果只写 score_ranked"
  - "stage1_meta 八个新键：attempts / total_budget_seconds / clamped_order / rank_budget_violations / rank_budget_k / alpha / llm_returned_count / stage0_window_count"
  - "_record_stage1_usage：Stage 1 每次上游调用落一行 ModelUsageRecord（call_source=aux_repo_router）"
affects: [107-06, 107-07, 107-08, 107-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "有界重试三件套：deadline 循环外取一次 + per-attempt 超时取 min(per_call, remaining) + 退避睡眠受剩余预算封顶——三者缺一，重试就会把延迟上界撑破"
    - "重试判定复用降级分类：可重试集合 == classify_degrade_reason 归为 timeout/upstream_error 的两类，异常类型名子串表在纯函数模块单一维护"
    - "裁剪产物即返回顺序：约束的产物必须写回主路径，只进快照就只是装饰"
    - "旁路字段纪律延续：凸组合只写 score_ranked，score/breakdown 逐字节不变"
    - "埋点口径写进注释：一次上游调用一行、缓存命中零行、与 SystemLogEntry.duration_ms 是两个口径"

key-files:
  created: []
  modified:
    - server/codegraph/services/repo_router_v2.py
    - server/tests/codegraph/test_repo_router_v2_degraded.py

key-decisions:
  - "裁剪产物写回候选顺序（plan 未明写，按 Rule 2 补齐）：不写回则无分组上下文的调用方拿到的仍是 LLM 无界排列，K 预算只是快照装饰"
  - "只对超时/上游连接类重试；解析错误、参数错误等确定性失败直接上抛——重试结果一样，只会白吃预算并把用户可见降级推迟一个 RTT"
  - "总预算/退避读取走新的 _stage1_seconds 而非 _stage1_conf：非正值必须回退默认，否则 env 写成 0 会让预算耗尽在首调之前、一次调用都不发"
  - "最终顺序类断言一律通过传 grouping_repository_ids=[] 触发 _apply_presentation 的排序分支：本 plan 不新增排序点（WARNING 3），无分组上下文时该函数只截断不重排是 107-03 的既定行为"
  - "测试文件加 autouse fixture 把退避基数压到 0.001s：本文件多数用例注入可重试异常，按默认 2.0s 真睡会给文件平白加十几秒；断言退避上界的用例自行覆盖该值"

patterns-established:
  - "替身捕获实参做上界断言：spy 住 asyncio.wait_for / asyncio.sleep 记录 timeout 与 delay 实参，直接断言「传出去的值」而非间接观察耗时"
  - "钉死 Stage 0 分数的 seam（_install_stage0_candidates）：绕开六信号打分，凸组合取值与最终顺序可以断言精确数值"
  - "K 预算断言的对象是 clamped_order 而非最终扁平列表：后者被凸组合再排一次，位移上界是 2K"

requirements-completed: [RELY-05]

coverage:
  - id: D1
    description: "Stage 1 单次调用有 1 次重试且首调与重试共享同一总延迟上界；预算耗尽即刻降级、不发第二次调用"
    requirement: "RELY-05"
    verification:
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_stage1_retry_recovers_on_second_attempt"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_stage1_retry_exhausted_degrades_after_two_attempts"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_stage1_budget_exhausted_skips_second_call"
        status: pass
    human_judgment: false
  - id: D2
    description: "per-attempt 超时取 min(per_call, 剩余预算)、退避睡眠不超剩余预算——不存在「首调吃满 per-call 后重试无余量」的结构"
    requirement: "RELY-05"
    verification:
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_stage1_per_attempt_timeout_is_capped_by_remaining_budget"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_stage1_retry_backoff_never_exceeds_remaining_budget"
        status: pass
    human_judgment: false
  - id: D3
    description: "缓存命中路径零调用零重试；langchain 内部重试保持关闭（重试只写在受总预算约束的循环里）"
    verification:
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_stage1_cache_hit_skips_call_and_retry"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_stage1_retry_is_not_delegated_to_langchain"
        status: pass
      - kind: other
        ref: "rg -c 'range(2)' != 0 且 rg -v '^[[:space:]]*#' | rg -c 'max_retries=[1-9]' == 0"
        status: pass
    human_judgment: false
  - id: D4
    description: "有界重排：K=3 裁剪的后置条件在 clamped_order 上成立，违规数留痕；LLM 编造的 repo_id 被丢弃"
    requirement: "RELY-05"
    verification:
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_rank_budget_clamps_tail_promotion"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_rank_budget_identity_permutation_has_no_violation"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_llm_fabricated_repo_id_is_dropped"
        status: pass
    human_judgment: false
  - id: D5
    description: "子集常态（LLM 只返回窗口末几位）不被整体丢弃、不膨胀回全量窗口、违规数不虚高"
    requirement: "RELY-05"
    verification:
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_rank_budget_subset_is_not_inflated"
        status: pass
    human_judgment: false
  - id: D6
    description: "「丢弃式提升」可观测：llm_returned_count / stage0_window_count 让「返回数远小于窗口数且违规为 0」这一绕过路径事后可识别"
    verification:
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_rank_budget_dropped_candidates_promotion_is_observable"
        status: pass
      - kind: other
        ref: "rg -c 'llm_returned_count' 与 'stage0_window_count' 于 repo_router_v2.py 均 != 0"
        status: pass
    human_judgment: false
  - id: D7
    description: "凸组合结果只写 score_ranked：score / breakdown 逐键不变、Σbreakdown == score 继续成立，且 breakdown 不含 α 项（D-3 硬约束）"
    verification:
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_score_and_breakdown_unchanged_by_convex_combination"
        status: pass
      - kind: unit
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_score_ranked_is_convex_combination"
        status: pass
      - kind: other
        ref: "rg -c 'score = .*blend_ranked|\\.score = ranked' == 0；rg -n 'breakdown\\[' | rg -c 'llm|alpha|ranked' == 0"
        status: pass
    human_judgment: false
  - id: D8
    description: "钉死 Stage 0 分差后最终顺序 == 按 score_ranked 算出来的顺序；tie 时按 repo_id 升序，排序仍由 _apply_presentation 唯一承载（未新增排序点或等价取值表达式）"
    verification:
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_score_ranked_final_order_with_pinned_stage0_margins"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_presentation_tie_break_is_repo_id_ascending"
        status: pass
      - kind: other
        ref: "rg -c '^def _rank_value' == 1；内联等价回退表达式计数 == 1；本 plan 新增行的 sorted(/.sort( 计数 == 0"
        status: pass
    human_judgment: false
  - id: D9
    description: "Stage 1 降级时 α 按 0 处理（score_ranked 保持 None）、N==1 不除零、confidence 不受凸组合影响（RELY-04 不回退）"
    verification:
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_degraded_path_leaves_score_ranked_none"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_single_candidate_does_not_divide_by_zero"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#test_confidence_is_unaffected_by_convex_combination"
        status: pass
    human_judgment: false
  - id: D10
    description: "Stage 1 每次上游调用落一行 ModelUsageRecord（call_source=aux_repo_router、duration_ms、失败短标签、触发用户），重试两行、缓存命中零行，且埋点 best-effort 不反噬"
    verification:
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#TestStage1ModelUsageRecording::test_stage1_usage_row_on_success"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#TestStage1ModelUsageRecording::test_stage1_usage_row_on_timeout_failure"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#TestStage1ModelUsageRecording::test_stage1_usage_one_row_per_upstream_attempt"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#TestStage1ModelUsageRecording::test_stage1_usage_zero_rows_on_cache_hit"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#TestStage1ModelUsageRecording::test_stage1_usage_write_failure_never_breaks_route"
        status: pass
    human_judgment: false
  - id: D11
    description: "触发用户绑定与不伪造指标：contextvars 有 user_id 取该值、无则 system；token 未知记 0、非流式不填首字延迟"
    verification:
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#TestStage1ModelUsageRecording::test_stage1_usage_binds_triggering_user"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#TestStage1ModelUsageRecording::test_stage1_usage_defaults_user_to_system"
        status: pass
      - kind: integration
        ref: "tests/codegraph/test_repo_router_v2_degraded.py#TestStage1ModelUsageRecording::test_stage1_usage_tokens_default_to_zero_when_unknown"
        status: pass
      - kind: other
        ref: "arecord_llm_usage 窗口内（滤注释行）ttft_ms=<数字> 计数 == 0"
        status: pass
    human_judgment: false
  - id: D12
    description: "打分口径与 golden 门禁零回归：Σbreakdown == score 两条既有断言继续绿、baseline 与离线 harness 零改动、tests/codegraph 全量绿"
    verification:
      - kind: integration
        ref: "cd server && uv run pytest tests/codegraph tests/test_llm_factory.py tests/test_model_usage_call_source.py -q → 586 passed / 20 skipped"
        status: pass
      - kind: other
        ref: "git diff --name-only HEAD~6 HEAD 只含 repo_router_v2.py 与 test_repo_router_v2_degraded.py（无 golden_baseline.json / repo_router_eval.py）"
        status: pass
    human_judgment: false

# Metrics
duration: 35min
completed: 2026-07-30
status: complete
---

# Phase 107 Plan 05: Stage 1 有界调用与有界重排 Summary

**Stage 1 从「单层 `asyncio.wait_for` + 无预算」改造为首调 + 1 次重试共享同一个 `budget_deadline` 的有界调用（per-attempt 超时取 `min(per_call, 剩余预算)`、退避睡眠受剩余预算封顶、预算耗尽不发第二次调用），LLM 排列经 K=3 rank-swap 裁剪后做凸组合并**只**写旁路字段 `score_ranked`，同时补齐 Stage 1 缺失的 `ModelUsageRecord` 埋点——`score` / `breakdown` / `confidence` / golden baseline 四者一行未动。**

## Performance

- **Duration:** 约 35 min
- **Started:** 2026-07-30T06:35:00Z
- **Completed:** 2026-07-30T07:10:00Z
- **Tasks:** 3（全部走 TDD：RED → GREEN，无 REFACTOR 轮）
- **Files modified:** 2

## Accomplishments

- **Stage 1 延迟有硬上界、重试有硬次数上界**：`range(2)` = 首调 + 1 次重试，`budget_deadline` 在循环外取一次由两次调用共享；每次进循环先算 `remaining`，`<= 0` 即记 `repo_router_v2_stage1_budget_exhausted` 后抛出降级——预算耗尽场景下替身只被调用 1 次（可断言，T-107-07 自伤 DoS 同时被挡）。
- **不存在「首调吃满 per-call、重试无余量」的结构**：per-attempt 超时传 `min(timeout_seconds, remaining)`；退避睡眠传 `min(backoff_base, max(0, deadline - now))`。两条上界都用 spy 捕获**实参**断言（per_call=1000/预算=2 → 传出的 timeout <= 2；退避基数=1000/预算=1 → 传出的 sleep <= 1），而不是间接观察耗时。
- **重试只对值得重试的失败生效**：`_is_retryable_stage1_error` 复用 `classify_degrade_reason` 的异常类型名子串口径，可重试集合 == 归为 `timeout` / `upstream_error` 的两类。解析错误、参数错误等确定性失败直接上抛——重试一次结果一样，只会白吃预算并把用户可见降级推迟一个 RTT。`max_retries=0` 原样保留（langchain 内部重试不受我们的预算约束）。
- **K=3 裁剪真正接进主路径**：`clamp_llm_permutation(llm_order, 全量 stage0_order, k=3)` 的产物既写进快照也**写回候选顺序**。子集常态（8 元窗口只返回末三位）下裁剪产物长度恰 3、不膨胀回全量、违规数不虚高；LLM 把第 8 位提到首位时该候选在裁剪产物中不早于第 4 位且违规数留痕。
- **凸组合走旁路字段，可拆解不变量未破**：`blend_ranked_scores` 的结果只写 `score_ranked`，静态断言核验 `score` 未被覆盖、`breakdown` 未被写入 α 项；「同一 Stage 0 输入下开关 Stage 1 两次调用中同一候选的 `score` 与 `breakdown` 逐键相等」是独立命名的机制断言，`Σbreakdown == score` 两条既有 fsum 断言继续绿。
- **「丢弃式提升」被记录下来**：`stage1_meta` 落 `llm_returned_count` / `stage0_window_count`。base rank 取子集内相对位次是必须的，代价是 LLM 靠**少返回候选**拿到的提升不受 K 约束（只返回窗口末位那一个仓即可零违规提到首位）；两个计数让「返回数远小于窗口数且违规为 0」这种模式事后可识别可告警。
- **Stage 1 补齐 `ModelUsageRecord`（Phase 105 遗留的埋点缺口）**：`_record_stage1_usage` 在每次上游调用收尾（成功与失败两条路径）落一行，`call_source` 用枚举而非字面串，失败记短标签 `failure_type` + 数值上游码（绝不落响应体），触发用户从 structlog contextvars 取、无则 `system`。口径写进注释：一次上游调用一行（重试两行）、缓存命中零行，与 `SystemLogEntry.payload.duration_ms`（107-02 的 O-6 数据源）是两个口径。
- **零回归得到验证**：`tests/codegraph tests/test_llm_factory.py tests/test_model_usage_call_source.py` 全量 586 passed / 20 skipped；`golden_baseline.json` 与 `repo_router_eval.py` 未出现在任何提交的改动清单中；两个下游消费方（`test_repo_router_adapter.py` / `test_repository_relevance_tool.py`）25 passed。

## Task Commits

1. **Task 1: 1 次重试 + 共享总预算 deadline** — `69ed63bf` (test, RED) → `d79056a5` (feat, GREEN)
2. **Task 2: K=3 rank-swap 裁剪 + 凸组合写 score_ranked** — `92cf7dd9` (test, RED) → `30c82bb4` (feat, GREEN)
3. **Task 3: Stage 1 ModelUsageRecord 埋点** — `6a0c450d` (test, RED) → `3571b548` (feat, GREEN)

_三个 task 的 REFACTOR 轮均未产生改动（GREEN 实现即最终形态）。_

## Files Created/Modified

- `server/codegraph/services/repo_router_v2.py` — `_STAGE1_DEFAULTS` 补两键 + 新增 `_stage1_seconds` fail-safe 读取；新增 `_is_retryable_stage1_error` / `_stage1_usage_metadata` / `_record_stage1_usage` 三个模块级 helper；`if not cache_hit:` 块内单层 `wait_for` 改为有界循环；`parsed` 消费循环之后接 K 裁剪 + 凸组合 + 违规留痕事件；`stage1_meta` 扩八键；`sorted_scores` 与 `max_retries=0` 两处补因果注释。
- `server/tests/codegraph/test_repo_router_v2_degraded.py` — 新增三节共 26 个用例（有界调用 7 + 有界重排 11 + 埋点 8）；新增 `_FlakyModel` / `_CountingSlowModel` 两个替身、`_spy_wait_for` / `_spy_sleep` 两个实参捕获 helper、`_cand` / `_window` / `_install_stage0_candidates` 三个钉死 Stage 0 分数的 seam、`_llm_order_json` 排列构造器，以及一个把退避基数压到毫秒级的 autouse fixture。

## Decisions Made

- **裁剪产物写回候选顺序**（plan 只要求写进快照）：不写回的话，无分组上下文的调用方（`_apply_presentation` 此时只截断不重排）拿到的仍是 LLM 的**无界**排列，K 预算就只是快照里的一行装饰，RELY-05 的「损害有硬上界」不成立。写回用 `[by_rid[rid] for rid in clamped_order]`，是纯重排、元素集合恒等，不新增排序调用。详见「Deviations」第 1 条。
- **重试判定复用降级分类口径**：`_is_retryable_stage1_error` 调 `classify_degrade_reason("", exc_type_name=...)` 判断是否 ∈ {`timeout`, `upstream_error`}，异常类型名子串表因此只在 `repo_router_ranking` 维护一份。自己再写一份子串表必然与降级原因分类漂移。
- **总预算/退避走新的 `_stage1_seconds` 而非既有 `_stage1_conf`**：`_stage1_conf` 是裸 `getattr`，env 把总预算写成 `0` 或 `""` 会让预算在首调之前就耗尽（一次调用都不发）或直接 `TypeError`。新 helper 对非数值/非有限/非正值一律回退默认且绝不抛，与 `clamp_ranking_params` 的 fail-safe 纪律同款。
- **最终顺序类断言通过传 `grouping_repository_ids=[]` 触发排序分支**：107-03 明确「无分组上下文时 `_apply_presentation` 只做 `[:top_k]` 不重排」，而本 plan 的 WARNING 3 与验收断言都禁止新增排序调用。传空列表即进入有上下文分支（全部记 `global`），排序仍由 `_apply_presentation` 唯一承载。边界见「Explicit Scope Boundaries」。
- **测试文件加 autouse fixture 把退避基数压到 0.001s**：本文件既有的十余个用例注入的都是可重试类异常（`ConnectionError` / `TimeoutError` / `_APIConnectionError`），引入重试后按默认 2.0s 退避真睡会给这一个文件平白加十几秒。断言退避上界的那条用例在 fixture 之后自行覆盖该值，断言强度未放宽。
- **失败路径的 `failure_type` 取短标签枚举**：直接用 `classify_degrade_reason` 的返回值（`timeout` / `upstream_error` / `unknown`），不落异常消息——`failure_type` 是指标维度，吃自由文本既会基数失控又是 T-107-02 的泄漏面。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] 裁剪产物必须写回候选顺序，否则 K 预算对主路径不生效**

- **Found during:** Task 2（K 裁剪接线）
- **Issue:** plan 的 action 只要求把 `clamped_order` 写进 `stage1_meta`。但 `_stage1_llm_reasoning` 返回的 `candidates` 顺序来自 `parsed`（即 LLM 原始排列），而 107-03 的 `_apply_presentation` 在**无分组上下文**时只做 `[:top_k]` 不重排——现有 8 个消费方一个都没传 `grouping_repository_ids`，因此照 plan 字面实现的话，生产路径上最终候选顺序仍是 LLM 的**无界**排列，K 预算完全不生效，RELY-05 的「LLM 重排损害有硬上界」在最常见路径上不成立。
- **Fix:** 在写 `score_ranked` 之前按 `clamped_order` 重排 `candidates`（`by_rid` 查表推导，纯重排、元素集合恒等）。这样无分组上下文时最终顺序 = 裁剪后的 K-有界排列，有分组上下文时再由 `_apply_presentation` 按 `score_ranked` 排一次（相对 Stage 0 的位移上界 2K，与 plan 的说明一致）。
- **Files modified:** server/codegraph/services/repo_router_v2.py
- **Verification:** `test_rank_budget_dropped_candidates_promotion_is_observable` 与 `test_rank_budget_subset_is_not_inflated` 断言最终列表的元素与顺序；验收断言「本 plan 新增行不含 `sorted(` / `.sort(`」仍为 0（列表推导不是排序调用）
- **Committed in:** `30c82bb4`（Task 2 GREEN 提交）

**2. [Rule 2 - Missing Critical] 秒级时长参数需要 fail-safe 读取（plan 写了要求但未指定载体）**

- **Found during:** Task 1（`_stage1_conf` 侧新增读取）
- **Issue:** plan action 步骤 1 要求「非法/非正值回退默认（不抛）」，但既有 `_stage1_conf` 是裸 `getattr` + 调用侧 `float(...)`。env 把 `REPO_ROUTER_STAGE1_TOTAL_BUDGET_SECONDS` 写成 `""` 会 `ValueError` 直接把路由打成降级；写成 `0` 会让首调之前预算就耗尽，Stage 1 变成结构性永不调用。
- **Fix:** 新增 `_stage1_seconds(key)`：`float()` 失败、非有限、`<= 0` 一律回退 `_STAGE1_DEFAULTS`，绝不抛。
- **Files modified:** server/codegraph/services/repo_router_v2.py
- **Verification:** `ruff check` 通过；总预算被 override 为 0.01（合法正值）时行为符合 `test_stage1_budget_exhausted_skips_second_call` 的预期
- **Committed in:** `d79056a5`（Task 1 GREEN 提交）

**3. [Rule 3 - Blocking] 引入重试后既有用例集体变慢，需在测试侧压低退避基数**

- **Found during:** Task 1（RED 阶段跑既有用例）
- **Issue:** `test_repo_router_v2_degraded.py` 里十余个既有用例注入的是可重试类异常，引入重试后每条都会真睡 2.0s 退避（`test_degrade_reason_is_always_in_closed_set` 一条就循环三次可重试异常 = 6s）。
- **Fix:** 加 module 级 autouse fixture 把 `REPO_ROUTER_STAGE1_RETRY_BACKOFF_SECONDS` 设为 0.001；断言退避上界的用例在其后自行覆盖为 1000。未改动任何既有用例的断言。
- **Files modified:** server/tests/codegraph/test_repo_router_v2_degraded.py
- **Verification:** 整文件 50 个用例合计约 19s（其中 8 条是需要 `django_db(transaction=True)` 的埋点用例）
- **Committed in:** `69ed63bf`（Task 1 RED 提交）

---

**Total deviations:** 3 auto-fixed（2 个 missing critical、1 个 blocking）
**Impact on plan:** 第 1 条改变了 plan 未明写的一处行为（裁剪产物进主路径），是 RELY-05 成立的必要条件，且未触碰任何验收断言；第 2、3 条分别是 plan 明写要求的实现载体与测试提速手段。无 scope creep，`repo_router_eval.py` / `golden_baseline.json` / `repo_router_scoring.py` 零改动。

## Explicit Scope Boundaries

- **无分组上下文时凸组合不参与排序。** `_apply_presentation` 的 `grouping_repository_ids is None` 分支按 107-03 的既定行为只做 `[:top_k]` 不重排，因此该路径的最终顺序是**裁剪后的 K-有界 LLM 排列**，`score_ranked` 只作为旁路取值透出（前端与后续 plan 可读）。α 影响顺序的前提是调用方传了分组依据——107-07 会给编排与 chat 两个真实入口接上。本 plan 按 WARNING 3 不新增排序点，此边界如实记录，供 107-07 复核是否需要让无上下文分支也按 `_rank_value` 排序。
- **「丢弃式提升」（T-107-10b）是 accept 而非 mitigate。** base rank 取子集内相对位次是必须的（否则常态下重排被整体丢弃），代价是 LLM 靠少返回候选实现的提升不受 K 约束。缓解手段只有可观测（两个计数进快照），没有阻断。
- **α = 0.35 未经离线校准**（107-01 / D-7 已记录）：离线 harness 结构上不跑 Stage 1，本 plan 也刻意未把凸组合塞进 `repo_router_eval.py`（会污染 `phase106-v2` baseline）。

## Issues Encountered

- **Stage 1 输入哈希缓存会让「同 query 同候选」的相邻用例互相污染**：本文件多条用例共用 `_high_margin_hits()` 与同一 query，第二次调用会命中缓存而不发上游调用。`tests/conftest.py` 的 autouse fixture 每例前后 `django_cache.clear()`，因此跨用例安全；缓存命中的两条用例（`test_stage1_cache_hit_skips_call_and_retry` / `test_stage1_usage_zero_rows_on_cache_hit`）刻意在**同一条用例内**调两次 `route()` 来构造命中。
- **`ruff format` 的既存偏差**：`repo_router_v2.py` 与降级测试文件都有本 plan 之前就存在的可合并换行（窄包裹风格）。按 scope boundary 未修；本 plan 新增的行本身已按 `ruff format --diff` 的输出调平，`ruff check` 全绿。
- **`test_stage1_retry_is_not_delegated_to_langchain` 在 RED 阶段即为绿**：它守护的是「`max_retries=0` 不被重新打开」这一既有事实（action 步骤 4 要求保持不动），性质是回归守护而非新行为，故不视为 RED 失效。同理 Task 2 的 `score`/`breakdown`/`confidence`/降级 `None` 四条也是不变量守护。

## User Setup Required

None — 总预算 120.0 与退避 2.0 两个键在 107-01 已落 settings + `.env.example` 并有代码内默认值；本 plan 未新增任何配置项。既有部署升级后行为变化仅限「快速失败场景多一次重试」与「Stage 1 多落一行 `ModelUsageRecord`」。

## Next Phase Readiness

- **107-06 / 107-09（前端）** 可消费候选的 `score_ranked`（`None` = 未重排，回退 `score`），排序口径与后端 `_rank_value` 一致。
- **107-07（改编排与 chat 两个入口）** 传入 `grouping_repository_ids` 后，凸组合才会真正参与最终排序（见 Explicit Scope Boundaries 第 1 条）；该 plan 需据此复核候选顺序变化的回归守护。
- **107-02 / O-6 实测** 现在有第二条数据源：`ModelUsageRecord` 里 `call_source='aux_repo_router'` 的行可直接走 `system/metrics_query.py` 的既有分位聚合，无需新写查询；注意口径是「每次上游调用一行、缓存命中零行」，与 `SystemLogEntry` 的 `repo_router_v2_stage1_completed.duration_ms` 不同（后者按 route 计一次且受采样配置影响）。
- **107-08（`RepositoryRoutingTrace` 迁移）** 可额外消费快照 `stage1` 节的 `attempts` / `rank_budget_violations` / `clamped_order`。
- 无阻塞项。

## Self-Check: PASSED

- 两个改动文件均在磁盘且改动已提交：`server/codegraph/services/repo_router_v2.py` / `server/tests/codegraph/test_repo_router_v2_degraded.py`
- 六个 task 提交均在 git 历史：`69ed63bf` / `d79056a5` / `92cf7dd9` / `30c82bb4` / `6a0c450d` / `3571b548`
- `git diff --stat HEAD~6 HEAD` 仅两个文件；`golden_baseline.json` / `repo_router_eval.py` / `repo_router_scoring.py` 均未出现
- `STATE.md` / `ROADMAP.md` 未被本 plan 修改
- 无 stub / 无占位实现：三个 task 的行为均由 26 条新用例覆盖，plan-level 验证套 119 passed、`tests/codegraph` 全量 586 passed / 20 skipped

---
*Phase: 107-layered-presentation*
*Completed: 2026-07-30*
