---
phase: 105-golden-set
plan: 01
subsystem: api
tags: [repo-routing, scoring, pure-function, determinism, confidence, pytest]

# Dependency graph
requires: []
provides:
  - "零 I/O 纯函数打分核心 server/codegraph/services/repo_router_scoring.py（router / replay / golden harness 三方共用）"
  - "ScoredCandidate / aggregate_and_score / derive_confidence / apply_llm_adjustment / PHASE105_WEIGHTS / WEIGHT_SET_VERSION 导出契约"
  - "confidence 阈值 REPO_ROUTER_CONF_THETA_ABS/MARGIN/MED settings+env 外置（默认 0.55/0.08/0.35）"
  - "INV-R1/R3 + 乱序确定性 + margin 规则 + 只降不升的性质测试守护（30 用例）"
affects: [105-03, 105-04, 105-05, 105-07, phase-106]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "打分/confidence 推导集中在零 Django 依赖的纯函数模块，θ 阈值由调用方读 settings 后参数注入"
    - "稳定 tie-break：先 round(·,6) 量化再比较，第二键用不可变 repo_id；求和一律 math.fsum"
    - "缺失信号走权重重归一化（breakdown 无该键），不补 0"

key-files:
  created:
    - server/codegraph/services/repo_router_scoring.py
    - server/tests/codegraph/test_repo_router_scoring.py
  modified:
    - server/friday/settings.py
    - .env.example

key-decisions:
  - "score 直接取 math.fsum(breakdown.values())，使 Σbreakdown == score 按构造精确成立（INV-R3 无浮点余差）"
  - "活跃度 facet 值不在 ACTIVITY_ENUM_MAP 或非字符串 → 信号不可用（重归一化），坏 JSON facets 容错为空 dict（T-105-01）"
  - "自定义 weights 缺键按权重 0 处理；denom<=0 时防御性输出 score=0、breakdown 空"

patterns-established:
  - "repo_name 容错契约：payload.get('repo_name') or repo_id，快照最小字段集重建与完整 payload 走同一路径"
  - "breakdown key 固定 SIGNAL_TEXT/SIGNAL_BREADTH/SIGNAL_ACTIVITY 常量，前端映射表与之对齐禁止改名"

requirements-completed: [RELY-04, ROUTE-07, ROUTE-09]

coverage:
  - id: D1
    description: "纯函数打分核心：分桶聚合 + query-local max 归一 + 三信号加性合成 + 缺失重归一化，任意候选 0<=score<=1 且 Σbreakdown==score"
    requirement: ROUTE-07
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_scoring.py#TestInvariants"
        status: pass
    human_judgment: false
  - id: D2
    description: "确定性保证：乱序输入 100 seed 逐字段同结果、round(·,6) 量化 tie-break 按 repo_id 升序、repo_name 缺失不影响分数与排序"
    requirement: ROUTE-09
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_scoring.py#TestDeterminism"
        status: pass
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_scoring.py#TestRepoNameFallback"
        status: pass
    human_judgment: false
  - id: D3
    description: "确定性 confidence 推导（margin 规则，θ 参数注入）与 LLM 只降不升调节；阈值经 settings/env 外置默认 0.55/0.08/0.35"
    requirement: RELY-04
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_scoring.py#TestMarginRule"
        status: pass
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_scoring.py#TestLlmAdjustment"
        status: pass
    human_judgment: false

# Metrics
duration: 9min
completed: 2026-07-29
status: complete
---

# Phase 105 Plan 01: 纯函数打分核心 Summary

**零 I/O 打分核心 `repo_router_scoring.py`：三信号（text/breadth/activity）加性合成 + 缺失重归一化 + fsum/量化 tie-break 确定性，margin 规则 confidence 推导与 LLM 只降不升，θ 阈值 settings/env 外置，30 条性质测试全绿**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-07-29T03:33:25Z
- **Completed:** 2026-07-29T03:42:00Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- 建立全 phase 的接口契约层：`aggregate_and_score`（dict in → dataclass out，零 Django/ORM/网络依赖），105-03 接线、105-04 golden harness、105-07 离线 replay 调同一份函数
- 现有三信号重构为可拆解加性形式：text（query-local max 归一后的桶内 max）、breadth（`min(hits-1,5)/5`）、activity（枚举映射 + 废弃封顶 `min(A, 0.10)` 取代乘性 `score *= 0.5`）
- INV-R1（S∈[0,1] 无截断）与 INV-R3（Σbreakdown==score，重归一化后仍成立）按构造成立并被测试锁定
- `derive_confidence` margin 规则（`S(1)>=θ_abs 且 margin>=θ_margin → high`）+ `apply_llm_adjustment` 只降不升，θ 三阈值经 `REPO_ROUTER_CONF_THETA_*` settings/env 外置（默认 0.55/0.08/0.35）
- 30 条性质测试：不变量、乱序 100 seed 确定性、tie-break 量化、margin 边界（含等号）、只降不升 3×3+None 穷举、废弃封顶机制级断言、repo_name 容错

## Task Commits

Each task was committed atomically:

1. **Task 1: 创建纯函数打分核心模块 + 阈值 settings 外置** - `1995f8a1` (feat)
2. **Task 2: 不变量与确定性性质测试** - `06d43dca` (test)

## Files Created/Modified

- `server/codegraph/services/repo_router_scoring.py` - 纯函数打分核心（常量、ScoredCandidate、aggregate_and_score、derive_confidence、apply_llm_adjustment），246 行
- `server/tests/codegraph/test_repo_router_scoring.py` - 性质测试 30 用例（含 INV-R1/INV-R3 字面、`range(100)` 乱序循环），278 行
- `server/friday/settings.py` - 新增 REPO_ROUTER_CONF_THETA_ABS/MARGIN/MED（env.float，紧跟 STAGE1 段落同风格）
- `.env.example` - 补三个同名变量与中文说明

## Decisions Made

- **score = fsum(breakdown.values())**：与「先算总分再拆」数学等价，但让 Σbreakdown == score 按构造精确成立，INV-R3 不依赖浮点容差
- **facets 容错边界**：非字符串活跃度值 / 枚举外值 → 信号不可用；坏 JSON → 空 dict（threat model T-105-01 mitigate：异常输入不抛）
- **defensive denom guard**：自定义 weights 全 0 或缺键时 denom<=0 → score=0、breakdown 空，防除零

## Deviations from Plan

None - plan executed exactly as written.

说明：Task 2 标注 `tdd="true"`，但其被测行为即 Task 1 产物（计划刻意先建实现再补性质测试守护），故无独立 RED 阶段——测试首跑即绿（30 passed, 0.94s），符合计划任务顺序而非偏差。

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.（新增 env 变量均带默认值，缺失不破坏。）

## Next Phase Readiness

- 105-03（RepoRouterV2 接线）可直接消费 `aggregate_and_score` / `derive_confidence` / `apply_llm_adjustment`，θ 从 settings 读后注入
- 105-04 / 105-07（harness / replay）依赖的 repo_name 容错契约与确定性契约已被测试锁定
- 观测埋点（router 层）与快照落盘按计划归 105-03 / 105-07，纯函数模块保持无日志

## Self-Check: PASSED

- FOUND: server/codegraph/services/repo_router_scoring.py（249 行 >= 120）
- FOUND: server/tests/codegraph/test_repo_router_scoring.py（277 行 >= 100）
- FOUND: commit 1995f8a1（Task 1）
- FOUND: commit 06d43dca（Task 2）
- 验证命令：`uv run pytest tests/codegraph/test_repo_router_scoring.py -q` → 30 passed；`uv run ruff check` 两文件全绿

---
*Phase: 105-golden-set*
*Completed: 2026-07-29*
