---
phase: 107-layered-presentation
plan: 01
subsystem: api
tags: [repo-router, ranking, block-ranking, rank-swap-budget, convex-combination, settings, golden-set, pure-functions]

# Dependency graph
requires:
  - phase: 105-golden-set
    provides: "确定性 confidence（derive_confidence / apply_llm_adjustment）、degraded / router_version、golden 门禁与 score_case 离线 harness"
  - phase: 106-multi-signal-scoring
    provides: "六信号可拆解打分（weight_set_version=phase106-v2）、Σbreakdown == score 恒等式、cross_group fixture 的 project_scope 字段、repo_router_config 的纯函数 + 参数注入范式"
provides:
  - "repo_router_ranking.py：分组标注 / block_order 迟滞 / rank-swap 预算裁剪 / 凸组合 / 降级原因分类 / 参数 clamp 六个纯函数（零 Django import）"
  - "9 个新 settings + env 键（delta / α / K / Stage 1 总预算与退避 / 澄清超时四键）"
  - "golden 门禁新增跨组置顶机制断言与 delta 上界锁定（gk-008 / gk-009）"
affects: [107-02, 107-03, 107-04, 107-05, 107-06, 107-07, 107-08, 107-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "纯函数 + 参数注入（延续 106 的 repo_router_config 纪律）：判定零 I/O，阈值由 router 层读 settings 后注入"
    - "后置条件式裁剪：算法可换，`|final_rank - base_rank| <= K` 的后置条件、base 的子集相对语义、违规数留痕不可换"
    - "受控闭集 + 空串区分：降级原因恒 ∈ 6 值闭集 ∪ {\"\"}，非降级路径返回空串"

key-files:
  created:
    - server/codegraph/services/repo_router_ranking.py
    - server/tests/codegraph/test_repo_router_ranking.py
  modified:
    - server/friday/settings.py
    - .env.example
    - server/tests/codegraph/test_repo_router_golden.py

key-decisions:
  - "9 个新参数全部走 settings + env，不进 weight_config.constants——避免污染快照 constants 形状与 weight_set_version 的「打分口径版本」语义"
  - "REPO_ROUTER_STAGE1_TIMEOUT_SECONDS 保持 per-call 90.0 不下调，新增总预算 120.0；下调 per-call 须先有 O-6 生产实测（A5）"
  - "clamp_llm_permutation 的 base rank 取「被 LLM 返回子集」内的 Stage 0 相对位次，两侧同集合同长度同下标域；兜底回退 base_order 而非全量 stage0_order"
  - "有项目上下文时 decide_block_order 恒返回长度 2（含两组皆空），长度 1 专门表达「无项目上下文」——前端据此区分两种 all-global 场景"
  - ".env.example 的 9 个新键写成未注释行（而非既有 `# Optional -` 注释风格），使其可被行首锚定断言核验；取值与代码默认一致，行为零变化"

patterns-established:
  - "机制断言优先于结果断言：golden 用「差值 >= 默认 delta」与「上界区间」而非精确等值，权重微调不产生假红"
  - "静态守护测试：按行首正则断言纯函数模块零 Django import（docstring 提及不计入）"
  - "穷举属性测试覆盖子集常态：非空子集 × 子集全排列（1956 例），等长全排列只是 m == n 那一层"

requirements-completed: [ROUTE-01, ROUTE-02, RELY-05]

coverage:
  - id: D1
    description: "本 phase 全部新参数（delta / α / K / Stage 1 总预算与退避 / 澄清超时四键）外置到 settings + env，默认值精确且 per-call Stage 1 超时未被下调"
    verification:
      - kind: unit
        ref: "cd server && uv run python -c '<settings 默认值断言脚本，见 107-01-PLAN.md Task 1 verify>'"
        status: pass
      - kind: other
        ref: "rg -c '^(REPO_ROUTER_GROUP_DELTA|...|CLARIFICATION_TIMEOUT_EXIT_ACTION)=' .env.example == 9"
        status: pass
    human_judgment: false
  - id: D2
    description: "分组标注纯函数：有项目上下文分两组、无项目上下文全部 global 且不抛；返回值不含任何数值（组别绝不进分数的机制守护）"
    requirement: "ROUTE-01"
    verification:
      - kind: unit
        ref: "tests/codegraph/test_repo_router_ranking.py#test_annotate_groups_without_project_context_is_all_global"
        status: pass
      - kind: unit
        ref: "tests/codegraph/test_repo_router_ranking.py#test_annotate_groups_returns_no_float"
        status: pass
    human_judgment: false
  - id: D3
    description: "block_order 迟滞置顶：阈值下不翻转 / 达阈值翻转 / 有上下文恒长度 2 / 幂等"
    requirement: "ROUTE-01"
    verification:
      - kind: unit
        ref: "tests/codegraph/test_repo_router_ranking.py#test_block_order_at_threshold_promotes_global"
        status: pass
      - kind: unit
        ref: "tests/codegraph/test_repo_router_ranking.py#test_block_order_with_project_context_is_always_length_two"
        status: pass
      - kind: unit
        ref: "tests/codegraph/test_repo_router_ranking.py#test_block_order_is_idempotent"
        status: pass
    human_judgment: false
  - id: D4
    description: "rank-swap 预算裁剪的后置条件在「LLM 只返回 Stage 0 子集」的常态下成立，且返回元素集合不膨胀回全量窗口；违规数被返回供留痕"
    requirement: "RELY-05"
    verification:
      - kind: unit
        ref: "tests/codegraph/test_repo_router_ranking.py#test_clamp_postcondition_holds_for_all_subsets_and_permutations"
        status: pass
      - kind: unit
        ref: "tests/codegraph/test_repo_router_ranking.py#test_clamp_llm_returning_only_tail_subset_keeps_subset"
        status: pass
      - kind: unit
        ref: "tests/codegraph/test_repo_router_ranking.py#test_clamp_out_of_budget_move_is_clipped"
        status: pass
    human_judgment: false
  - id: D5
    description: "凸组合 S_ranked =(1-α)·S_final + α·S_llm，α<=0 或 N<=1 恒等返回 S_final（防除零 / Stage 1 降级）"
    requirement: "RELY-05"
    verification:
      - kind: unit
        ref: "tests/codegraph/test_repo_router_ranking.py#test_blend_convex_combination_values"
        status: pass
      - kind: unit
        ref: "tests/codegraph/test_repo_router_ranking.py#test_blend_with_single_candidate_does_not_divide_by_zero"
        status: pass
    human_judgment: false
  - id: D6
    description: "降级原因分类为 6 值受控闭集，非降级路径返回空串；函数结构上只接受异常类型名（脱敏边界）"
    verification:
      - kind: unit
        ref: "tests/codegraph/test_repo_router_ranking.py#test_classify_degrade_reason_return_is_in_controlled_closed_set"
        status: pass
    human_judgment: false
  - id: D7
    description: "参数 clamp fail-safe：越界回落合法域、非有限值与非数值回退默认、绝不抛（T-107-05）"
    verification:
      - kind: unit
        ref: "tests/codegraph/test_repo_router_ranking.py#test_clamp_params_clips_out_of_range_values"
        status: pass
      - kind: unit
        ref: "tests/codegraph/test_repo_router_ranking.py#test_clamp_params_never_raises_on_garbage"
        status: pass
    human_judgment: false
  - id: D8
    description: "「跨组正确仓能被置顶」进 CI 门禁；delta 的可用上界被 gk-008 的组间分差锁住"
    requirement: "ROUTE-02"
    verification:
      - kind: unit
        ref: "tests/codegraph/test_repo_router_golden.py#test_cross_group_cases_trigger_block_order_promotion"
        status: pass
      - kind: unit
        ref: "tests/codegraph/test_repo_router_golden.py#test_cross_group_delta_upper_bound_is_binding"
        status: pass
    human_judgment: false

# Metrics
duration: 15min
completed: 2026-07-29
status: complete
---

# Phase 107 Plan 01: 分层呈现纯函数底座与参数外置 Summary

**新增零 Django 依赖的 `repo_router_ranking` 六个纯函数（分组标注 / delta 迟滞置顶 / rank-swap 预算裁剪 / 凸组合 / 降级原因分类 / 参数 clamp），9 个参数落 settings+env，并把「跨组正确仓被置顶」写成 golden CI 门禁断言——打分口径（`repo_router_scoring.py` 与 `phase106-v2` baseline）一行未动。**

## Performance

- **Duration:** 约 15 min
- **Started:** 2026-07-29T21:13:00Z
- **Completed:** 2026-07-29T21:28:00Z
- **Tasks:** 3（其中 Task 2 走 TDD：RED → GREEN）
- **Files modified:** 5（2 新建 / 3 修改）

## Accomplishments

- **纯函数底座落地**：`server/codegraph/services/repo_router_ranking.py`（263 行）导出 6 个函数 + 6 个常量，零 Django import（静态守护测试按行首正则锁死）。后续 6 个 plan 直接消费这一份实现，同一判定不会在多处各写一遍。
- **子集常态的 base rank 语义被测试锁死**：`clamp_llm_permutation` 的 base rank 取「被 LLM 返回子集」内的 Stage 0 相对位次。穷举「6 元窗口全部非空子集 × 该子集全排列」共 1956 例，逐例断言后置条件成立、返回元素集合恒等于输入子集（不因兜底回退膨胀回全量窗口）、函数不抛。
- **9 个参数不发版可调**：delta 0.15 / α 0.35 / K 3 / Stage 1 总预算 120.0 与退避 2.0 / 澄清超时 24h、扫描 600s、单次上限 200、出口动作 `resume_with_assumptions`。`REPO_ROUTER_STAGE1_TIMEOUT_SECONDS` 仍为 90.0（per-call 语义未被下调，A5 纪律）。
- **golden 门禁多两条机制断言**：gk-008 组间分差 0.1771、gk-009 0.2614，两者均 >= 默认 delta 且 `decide_block_order` 判 `["global", "in_project"]`，正确仓落在被置顶组内；gk-008 的分差另用区间断言锁上界语义（`>= 0.15` 且 `< 0.1772`），delta 调高越界会被 CI 抓住。
- **打分口径冻结得到验证**：`repo_router_scoring.py` 与 `golden_baseline.json` 零改动，`tests/codegraph` 全量 468 passed / 20 skipped。

## Task Commits

1. **Task 1: 本 phase 全部新参数外置（settings + .env.example）** — `3618b41b` (feat)
2. **Task 2: repo_router_ranking.py 六个纯函数 + 单测（TDD）** — `3119a598` (test, RED) → `93bcde76` (feat, GREEN)
3. **Task 3: golden cross_group 机制断言（gk-008 / gk-009 的 delta 与置顶）** — `f0bdafd7` (feat)

_REFACTOR 轮未产生改动（GREEN 实现即为最终形态，无需清理）。_

## Files Created/Modified

- `server/codegraph/services/repo_router_ranking.py`（新建）— 6 个纯函数 + `GROUP_*` / `TRUST_*` / `CROSS_GROUP_NOTE` / `DEGRADE_REASONS` 常量；模块 docstring 写明它是 Phase 106 打分口径的外层包装，绝不改 `score` / `breakdown`。
- `server/tests/codegraph/test_repo_router_ranking.py`（新建）— 47 个用例，覆盖 6 组行为 + 子集穷举属性测试 + 零 Django import 静态守护。
- `server/friday/settings.py` — 三段新增：分组呈现与有界重排（3 键）、Stage 1 延迟有界化（2 键）、澄清必达与超时出口（4 键）。
- `.env.example` — 同步 9 键默认值。
- `server/tests/codegraph/test_repo_router_golden.py` — `_group_tops` helper + 2 个跨组机制断言用例（9 → 11 passed，耗时仍 0.13s）。

## Decisions Made

- **参数载体选 settings + env**（不进 `weight_config.constants`）：`_validate_constants` 的白名单派生自 `DEFAULT_WEIGHT_CONFIG["constants"]`，新键会进快照 `constants` 节并影响 106-07 回放比对与 golden fixture 形状；且 α / K / delta 不改打分口径，混进 `weight_set_version` 会稀释版本语义。
- **per-call Stage 1 超时保持 90.0**：仅新增总预算 120.0（= 90 per-call + 退避余量）。下调 per-call 会把原本 70–89s 能成功的调用变成用户可见降级，须先有 O-6 生产实测（107-02）。重试因此只在快速失败场景生效 → 相对今日行为零回归。
- **两组皆空时 `decide_block_order` 取 `["in_project", "global"]`**：无任何证据支持置顶全局组，取确定默认顺序（plan 允许实现自选但必须恒定）。
- **`clamp_llm_permutation` 兜底回退 `base_order`**（非全量 `stage0_order`）：回退结果的元素集合必须与输入子集一致，否则会凭空引入没有对应候选的 repo_id。
- **`.env.example` 新键写成未注释行**：Task 1 的验收断言行首锚定（注释行不计入），故 9 键必须是生效行；取值与代码默认完全一致，对既有部署行为零影响。这与该文件对可选调参键的 `# Optional -` 注释惯例不同，代价是若将来代码默认值变更，照 `.env.example` 生成的 `.env` 会把旧值钉住。

## Deviations from Plan

None — plan executed exactly as written。

补充两点非偏离的执行细节（均未改动计划语义）：

- **`server/friday/settings.py` 存在预先的 `ruff format` 偏差**（`LLM_CONCURRENCY_LEASE_TTL_SECONDS` / `RESUMABLE_HEARTBEAT_INTERVAL_SECONDS` / `EXTRACTOR_BACKENDS` 等 6 处可被 ruff 合并的换行）。这些与本 plan 改动无关，按 scope boundary 未修；本 plan 新增的行本身 `ruff format --check` 干净。
- **golden 测试文件里对 gk-008 分差的说明写在注释与常量名上**，`assert` 行只出现 `0.15` 与 `0.1772`，因此 Task 3 的「无脆弱结果断言」归零断言为 0，未与 action 要求的因果注释冲突。

## Issues Encountered

- **`ruff` 的 isort 首方分类依赖模块是否已存在于磁盘**：RED 阶段测试文件 import 还不存在的 `repo_router_ranking`，ruff 把 `codegraph` 判为第三方并要求与 `import pytest` 合并成同一 import 块；模块创建后恢复为首方、分块写法通过。处理方式是保留与仓内既有测试一致的分块写法，GREEN 后复核 `ruff check` 通过（RED 提交那一刻该文件的 I001 是这一机制的产物，非风格错误）。

## User Setup Required

None — 9 个新键都有代码内默认值，既有部署无需改 `.env` 即可升级。

## Next Phase Readiness

- **107-03（router 接线）** 可直接消费 `annotate_groups` / `decide_block_order`；分组依据参数（D-1 的 `grouping_repository_ids`）与候选字段仍待该 plan 落地。
- **107-05（Stage 1 有界）** 可直接消费 `clamp_llm_permutation` / `blend_ranked_scores` / `classify_degrade_reason` 与总预算/退避两键；注意凸组合结果必须写旁路字段，绝不覆盖 `score`（D-3）。
- **107-04 / 107-06（澄清必达与超时出口）** 的 4 个配置键已就位（含 D-4 的单一超时口径依据）。
- **107-02（O-6 实测与 107-MEASUREMENTS.md）** 需记录两条已知局限：α=0.35 未经离线校准（离线 harness 结构上不跑 Stage 1）、per-call 超时下调待生产延迟实测。
- 无阻塞项。

## Self-Check: PASSED

- 新建文件均在磁盘：`repo_router_ranking.py` / `test_repo_router_ranking.py` / 本 SUMMARY
- 四个 task 提交均在 git 历史：`3618b41b` / `3119a598` / `93bcde76` / `f0bdafd7`
- `repo_router_scoring.py` 与 `golden_baseline.json` 未出现在任何提交的改动清单中

---
*Phase: 107-layered-presentation*
*Completed: 2026-07-29*
