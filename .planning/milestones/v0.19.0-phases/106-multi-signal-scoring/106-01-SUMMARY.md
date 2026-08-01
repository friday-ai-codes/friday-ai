---
phase: 106-multi-signal-scoring
plan: 01
subsystem: codegraph-routing
tags: [repo-router, scoring, maxp, pivoted-normalization, exponential-decay, tie-break]

# Dependency graph
requires:
  - phase: 105-golden-set
    provides: 纯函数打分核心骨架（分桶/归一/重归一化/排序）、golden 门禁（14 条 + baseline）、30 条性质测试底座
provides:
  - 六信号纯函数打分核心：aggregate_and_score(node_hits, *, weights, repo_meta, constants, now)
  - DEFAULT_WEIGHT_CONFIG（phase106-v1 五信号权重 + 全部常数 + 关键程度锚点）——全 phase 唯一默认配置来源
  - SIGNAL_DOMAIN / SIGNAL_STACK / SIGNAL_TEAM breakdown key 常量
  - ScoredCandidate.criticality 旁路字段 + 同分带（crit_band 量化桶）tie-break 排序
  - repo_meta 键契约（docstring 权威定义：n_r/last_commit_at/dense_cos_max/facet_scores/criticality_value）
  - INV-R1~R4 六信号性质测试 + 活跃度真值表 + legacy 路径逐字段守护（62 条全绿）
affects: [106-02, 106-03, 106-04, 106-05, 106-06, 106-07, 106-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "resolver（I/O，router 层）→ scorer（纯函数）分层：T2 余弦/DB 聚合以数据形式注入 repo_meta"
    - "时间锚点 now 参数注入（模块内禁读系统时间，回放/golden 确定性）"
    - "constants 与默认 merge + 非法值防御回退（严格校验归 106-02 loader/view 层）"
    - "breakdown text/breadth 拆两扁平键表示 λ 合成（INV-R3 与机制断言同时成立，前端零结构改动）"

key-files:
  created: []
  modified:
    - server/codegraph/services/repo_router_scoring.py
    - server/tests/codegraph/test_repo_router_scoring.py

key-decisions:
  - "关键程度实现为排序 tie-break（CONTEXT 裁决）：量化桶 band_bucket=floor(round(score,6)/crit_band)，排序键 (-band, -crit_rank, -score, repo_id)；跨桶边界邻近对不触发 tie-break 是 |ΔS|<0.03 字面语义的近似——显式带内两两比较会破坏排序键全序性"
  - "criticality 缺失按 0.4 居中（与「一般」同档，不奖不罚）"
  - "facet score 越界值 clip 至 [0,1]（trust boundary 容错），类型错误 → 信号不可用"
  - "rrf_max<=0 全零退化时 n_eff=0 → breadth=0（无有效命中证据）"

patterns-established:
  - "DEFAULT_WEIGHT_CONFIG 单点默认值：106-02 loader 回退、106-07 replay 兜底、106-08 harness 默认全部 import 它，禁止复制字面量"
  - "WEIGHT_SET_VERSION 保持 phase105-v1，bump 与 golden baseline 重建同步归 106-08（旁注释已标注）"

requirements-completed: [ROUTE-03, ROUTE-04, ROUTE-05]

coverage:
  - id: D1
    description: "六信号纯函数打分核心：MaxP dense 余弦校准 + pivoted-size-normalized 对数饱和 breadth + domain/stack/team 元数据消费 + 活跃度指数衰减 + 关键程度 tie-break；legacy 路径（repo_meta=None）逐字段零破坏"
    requirement: ROUTE-03
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_scoring.py#TestSizeBiasMechanism/TestMultiSignalInvariants"
        status: pass
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_golden.py（golden 门禁，版本未 bump 全绿）"
        status: pass
    human_judgment: false
  - id: D2
    description: "元数据三信号（domain/stack/team）消费 resolver 注入匹配分，缺失重归一化不压分"
    requirement: ROUTE-04
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_scoring.py#test_inv_r3_breakdown_sums_to_score_across_meta_combinations / test_missing_facets_degenerate_to_text_breadth"
        status: pass
    human_judgment: false
  - id: D3
    description: "活跃度连续化：指数衰减 H=180d/offset=14d/floor=0.05 + 枚举回退 + 疑似废弃封顶跨来源（真值表四行）"
    requirement: ROUTE-05
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_scoring.py#TestActivityDecay"
        status: pass
    human_judgment: false

# Metrics
duration: 14min
completed: 2026-07-29
status: complete
---

# Phase 106 Plan 01: 六信号打分核心扩展 Summary

**`aggregate_and_score` 从三信号扩展为六信号纯函数（repo_meta/constants/now 参数注入）：MaxP+pivoted breadth 消除尺寸偏置、domain/stack/team 元数据入分、活跃度指数衰减连续化、关键程度同分带 tie-break；legacy 路径逐字段不变，golden 门禁全绿**

## Performance

- **Duration:** ~14 min
- **Started:** 2026-07-29T07:33:11Z
- **Completed:** 2026-07-29T07:47:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- 六信号新路径落地：`repo_meta is not None` 时走 MaxP（dense 余弦 affine clip，缺失回退 RRF s_hat）+ pivoted-size-normalized 对数饱和 breadth（§2.4 数值复现：study-app breadth 0.083 < onion-learning 0.114）+ 元数据三信号 + 活跃度衰减 + 缺失重归一化。
- `DEFAULT_WEIGHT_CONFIG` 成为全 phase 唯一默认配置来源（phase106-v1、五信号权重、14 个常数、四档关键程度锚点、crit_weight_reserved 开关位、t2_disabled_facets/embedding_model_id/calibrated_at 校准元数据位）。
- 关键程度不进加性和：`ScoredCandidate.criticality` 旁路字段 + 量化桶 tie-break 排序（取舍已写进代码注释）；Σbreakdown == score 恒等式无 criticality 键。
- 62 条测试全绿（既有 30 + 新增 32），`tests/codegraph` 全量 275 passed / 20 skipped——golden 门禁与 replay 零改动通过，WEIGHT_SET_VERSION 保持 `phase105-v1`。

## Task Commits

Each task was committed atomically:

1. **Task 1: 六信号打分核心扩展** - `8dd4618e` (feat)
2. **Task 2: 六信号不变量与机制性质测试** - `3811ccd5` (test)

## Files Created/Modified

- `server/codegraph/services/repo_router_scoring.py` - 六信号纯函数核心（627 行）：新常量 + repo_meta 契约 docstring + `_score_legacy`/`_score_with_meta` 双路径 + 常数 merge 防御 + ISO/UTC 解析
- `server/tests/codegraph/test_repo_router_scoring.py` - 903 行：新增 `_make_meta` helper 与 5 个测试类（TestMultiSignalInvariants / TestActivityDecay / TestCriticalityTieBreak / TestSizeBiasMechanism / TestNewPathDeterminismAndLegacy）

## Decisions Made

- 量化桶 tie-break（`floor(round(score,6)/crit_band)`）而非显式带内两两比较：后者比较不可传递、破坏排序键全序性；代价是跨桶边界的邻近对（如 0.0299 vs 0.0301）不触发 tie-break，属 |ΔS|<0.03 字面语义的受控近似。
- facet score 越界数值 clip 至 [0,1]（trust boundary 容错，保 INV-R1 构造性成立）；类型错误（str 等）→ 信号不可用。
- 新路径 rrf_max<=0 全零退化时 n_eff=0 → breadth=0（无有效命中证据，与 legacy 全零分数语义一致）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - 测试构造修正] floor 生效天数与 plan behavior 文字不符**
- **Found during:** Task 2（活跃度衰减测试）
- **Issue:** plan behavior 写「730 天时 floor=0.05 生效」，但公式字面值 0.5^((730-14)/180) ≈ 0.063 > 0.05——floor 实际约 792 天后才绑定（公式权威 ROUTING-RANKING §3.5 优先于 plan 描述文字）
- **Fix:** floor 路径用 1500 天构造并断言 == 0.05；730 天保留在严格递减序列中并额外断言 > floor（曲线连续性佐证）
- **Files modified:** server/tests/codegraph/test_repo_router_scoring.py
- **Verification:** test_floor_applies_at_extreme_age 通过
- **Committed in:** 3811ccd5

**2. [Rule 3 - 门禁冲突] 验收 grep 与 docstring 字面冲突**
- **Found during:** Task 1（acceptance criteria 自检）
- **Issue:** docstring 里「禁止 datetime.now()」的说明文字命中验收断言 `rg -c "datetime\.now\(\)" == 0`
- **Fix:** 改写为「禁止读取系统当前时间」，语义不变
- **Files modified:** server/codegraph/services/repo_router_scoring.py
- **Committed in:** 8dd4618e

**3. [Rule 3 - 格式门禁] ruff format 重排既有测试折行**
- **Found during:** Task 2（`ruff format --check` 验证步骤）
- **Issue:** 既有测试文件存在未按当前 ruff 配置折行的多行表达式，`ruff format --check`（plan verification 要求）不通过
- **Fix:** 执行 ruff format——仅折行合并，既有 30 条用例逻辑/断言零改动
- **Files modified:** server/tests/codegraph/test_repo_router_scoring.py
- **Committed in:** 3811ccd5

---

**Total deviations:** 3 auto-fixed（1 测试构造修正、2 门禁冲突处理）
**Impact on plan:** 全部为正确性/门禁一致性修正，无 scope creep；公式与锁定语义未受影响。

## TDD Gate Compliance

Task 2 标记 `tdd="true"`，但按 plan 任务编排实现先落在 Task 1（feat `8dd4618e`）、测试后落 Task 2（test `3811ccd5`）——RED 阶段不可构造（被测行为已存在）。测试作为验证层一次通过，plan-level `type: execute`（非 tdd plan），无 RED/GREEN gate 序列要求。

## Issues Encountered

None——除上述 deviations 外，plan 按写执行；62 条测试首跑即绿。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 接口契约层就绪：106-02（config loader 默认值）、106-03（resolver 输出契约 = repo_meta.facet_scores 形状）、106-06（router 注入）、106-07（replay 透传）、106-08（golden harness + WEIGHT_SET_VERSION bump/baseline 重建）全部可基于本 plan 签名构建。
- s_top_c_lo/c_hi 与 t2_c_lo/c_hi 为 O-2 校准初值，生产回填 deferred（已在 DEFAULT_WEIGHT_CONFIG 注释标注）。
- n_bar 默认 None（denom_size=1.0 降级路径）——N_r/N̄ 快照写入归 106-04。

## Self-Check: PASSED

- FOUND: server/codegraph/services/repo_router_scoring.py
- FOUND: server/tests/codegraph/test_repo_router_scoring.py
- FOUND: commit 8dd4618e（feat）
- FOUND: commit 3811ccd5（test）

---
*Phase: 106-multi-signal-scoring*
*Completed: 2026-07-29*
