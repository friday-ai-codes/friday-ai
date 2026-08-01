---
phase: 105-golden-set
plan: 03
subsystem: api
tags: [repo-routing, confidence, degraded, breakdown, snapshot, clarify-policy, pytest]

# Dependency graph
requires:
  - phase: 105-golden-set (plan 01)
    provides: "纯函数打分核心 aggregate_and_score / derive_confidence / apply_llm_adjustment / WEIGHT_SET_VERSION + θ 阈值 settings 外置"
provides:
  - "RepoRouterV2 接线纯函数打分核心：去截断（两处 min(score,1.0) 与 DEPRECATED_PENALTY 全删）、候选携带 breakdown（进 to_dict）"
  - "确定性 confidence：margin 规则推导（rank-1 derive_confidence / rank>1 θ_med 分档），LLM 输出经 apply_llm_adjustment 只降不升"
  - "auto_selected 由确定性 confidence 驱动，Stage 1 可用/不可用两条路径语义一致——失联不再卡死编排（RELY-04）"
  - "RepoRouteResultV2.degraded 标志（v2_stage0_only / v1_fallback 为 True）+ snapshot Stage 0 快照材料（最小字段集 node_hits + weight_set_version/index_version）"
  - "三种失联情形 + 静默 None 路径 + 只降不升 的行为守护测试（10 用例）"
  - "clarify policy 层降级路由回归（3 用例）：margin 达标编排自动推进、全 low 仍澄清、confidence=high 不建澄清轮不 emit clarification.asked"
affects: [105-04, 105-05, 105-06, 105-07, phase-106, phase-107]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "confidence 推导只在 scoring 模块一处：router 经 _deterministic_confidence 集中调 derive_confidence/apply_llm_adjustment，不散落调用方"
    - "快照材料随 RepoRouteResultV2.snapshot 携带（router 无 session 依赖），落 ConvergenceSessionEvent 由编排链 _h_route 处理（105-07）"
    - "Stage 1 失败注入测试 seam：patch agents.llm_factory.build_chat_model（函数内 lazy import）+ services.provider_config.aget_claude_code_runtime_config"

key-files:
  created:
    - server/tests/codegraph/test_repo_router_v2_degraded.py
  modified:
    - server/codegraph/services/repo_router_v2.py
    - server/tests/services/test_engine_clarify.py

key-decisions:
  - "rank>1 候选 confidence 用 score >= θ_med → medium else low（high 仅 rank-1 可得——margin 语义只对首位有定义，写进 _deterministic_confidence docstring）"
  - "repo_router_v2_scored 观测事件在各路径出口统一记录（debug 级 + degraded 字段），helper 内 try/except 吞异常（观测 best-effort）"
  - "index_version = sha256(参与候选各仓 built_at 按 repo_id 排序拼接)；node_hits 快照只存 node_id/repository_id/score/node_path/activity_facet 最小字段集"
  - "超时用例真走 asyncio.wait_for（settings fixture 把 REPO_ROUTER_STAGE1_TIMEOUT_SECONDS 调到 0.05 + fake ainvoke sleep），非直接 raise TimeoutError"

patterns-established:
  - "降级统一出口 _stage0_only_result：finalize + auto_selected(首位 high) + degraded=True + snapshot + 观测，use_llm=False 与失联共用"
  - "clarify policy 回归以 session.routing 产物形状（candidates[].confidence + router_version=v2_stage0_only）构造，断言 policy/adapter 返回值而非 router 内部状态"

requirements-completed: [RELY-04, ROUTE-07, ROUTE-09]

coverage:
  - id: D1
    description: "Stage 1 三种失联情形（网关 400 / 连接错误 / 超时）+ provider_missing / unparsable_llm_output 下 route() 仍产出确定性 high/medium/low 分级，degraded=True，margin 达标即 auto_selected=True"
    requirement: RELY-04
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_v2_degraded.py#test_gateway_400/connection_error/timeout/provider_missing/unparsable_llm_output_degrades_to_deterministic_high"
        status: pass
    human_judgment: false
  - id: D2
    description: "LLM confidence 只降不升（high→medium 降级生效、low→high 升级被拒），auto_selected 由确定性最终 confidence 驱动；degraded=False 仅在 v2 路径"
    requirement: RELY-04
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_v2_degraded.py#test_llm_downgrade_high_to_medium_applies / test_llm_upgrade_low_to_high_rejected"
        status: pass
    human_judgment: false
  - id: D3
    description: "去截断 + 候选携带 breakdown 且 Σ贡献==score；8 个消费方 stub 构造测试零改动通过（新字段全带默认值）"
    requirement: ROUTE-07
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_v2_degraded.py#test_use_llm_false_semantics_match_degraded_path（Σbreakdown==score 断言）"
        status: pass
      - kind: integration
        ref: "uv run pytest tests/services/test_repo_router_adapter.py tests/knowledge/test_artifact_repo_routing.py tests/initiatives/test_repo_association_service.py tests/mcp_tools/test_route_repositories.py -q（32 passed，零改动）"
        status: pass
    human_judgment: false
  - id: D4
    description: "稳定排序贯穿（_aggregate_by_repo 桶内 (-round(score,6), node_id)）+ Stage 0 快照材料随结果携带（stage0 最小字段集 + versions）"
    requirement: ROUTE-09
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_v2_degraded.py#test_provider_missing_degrades_to_deterministic_high（snapshot 断言）"
        status: pass
    human_judgment: false
  - id: D5
    description: "clarify 默认 policy：失联降级 + margin 达标 → 无需澄清自动推进；确定性 confidence=high 时不建澄清轮、不 emit clarification.asked（强制确认不无差别触发）"
    requirement: RELY-04
    verification:
      - kind: integration
        ref: "server/tests/services/test_engine_clarify.py#test_default_policy_degraded_routing_* / test_clarify_adapter_degraded_routing_high_conf_no_forced_confirmation"
        status: pass
    human_judgment: false

# Metrics
duration: 21min
completed: 2026-07-29
status: complete
---

# Phase 105 Plan 03: RepoRouterV2 接线 Summary

**RepoRouterV2 全路径改确定性 margin 分级：去两处截断与乘性废弃惩罚、候选带 breakdown、LLM 只降不升、失联降级仍可 auto_selected（degraded=True）并携带 Stage 0 快照材料；13 条行为/集成测试锁定 RELY-04 生产事故链修复**

## Performance

- **Duration:** ~21 min
- **Started:** 2026-07-29T04:04:30Z
- **Completed:** 2026-07-29T04:25:30Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- **编排解锁（RELY-04）**：Stage 1 三种失联情形（网关 400 / 连接错误 / 超时）与两条静默 None 路径（provider_missing / unparsable_llm_output）下，route() 均产出按分数 margin 确定性推导的分级；margin 达标即 `auto_selected=True`——直接解开「失联 → 恒 low → auto_selected 恒 false → 编排卡死」事故链（会话 ccd817d9）
- **分数可拆解（ROUTE-07）**：删 `_finalize_stage0` / Stage 1 两处 `min(score,1.0)` 截断与 `DEPRECATED_PENALTY` 乘性惩罚，Stage 0 打分换为 `aggregate_and_score` 薄封装；每候选 `to_dict()` 携带 breakdown（round 6）且 Σ贡献==score
- **只降不升防线（T-105-06/07）**：LLM confidence 不再直接采信——先按 stage0 排序位置算确定性分级，再 `apply_llm_adjustment`；测试锁定 low→high 升级被拒，LLM 无法把任何候选推成 auto_selected
- **数据底座（ROUTE-09）**：`_aggregate_by_repo` 桶内稳定排序 `(-round(score,6), node_id)`；`RepoRouteResultV2.snapshot` 携带 stage0 最小字段集 node_hits + `weight_set_version`/`index_version`（sha256 of 参与候选各仓 built_at）
- **下游自动解锁验证（Pitfall 1）**：clarify policy 零改动——3 条行为级用例证明「降级 + margin 达标 → 编排自动推进」「confidence=high → 不建澄清轮、不 emit clarification.asked」贯穿 policy/adapter 层
- 消费方零破坏：新增 dataclass 字段全带默认值，repo_router_adapter / artifact_repo_routing / repo_association_service / route_repositories 等 stub 构造测试零改动通过；定向回归 239 passed

## Task Commits

Each task was committed atomically:

1. **Task 1: Stage 0 接线打分核心 + 数据结构扩展** - `749efd65` (feat)
2. **Task 2: 三种失联情形行为测试** - `34a44582` (test)
3. **Task 3: clarify policy 行为级集成测试** - `95e1c123` (test)

## Files Created/Modified

- `server/codegraph/services/repo_router_v2.py` - 接线打分核心：dataclass 扩展（breakdown/degraded/snapshot）、`_conf_thresholds`、`_deterministic_confidence`、`_stage0_only_result` 降级统一出口、`_build_snapshot`、`repo_router_v2_scored` debug 观测（692 行）
- `server/tests/codegraph/test_repo_router_v2_degraded.py` - 失联降级行为守护 10 用例（335 行 >= 120）
- `server/tests/services/test_engine_clarify.py` - 追加 3 条 degraded_routing policy/adapter 回归（既有 14 条零改动）

## Decisions Made

- **rank>1 分级规则**：`score >= θ_med → medium else low`，high 仅 rank-1 可得（margin 语义只对首位有定义）——写进 `_deterministic_confidence` docstring
- **观测事件落点**：`repo_router_v2_scored` 在 v2 / v2_stage0_only 两路径出口统一记（debug 级 + degraded 字段），helper 吞异常保证观测不反噬业务；既有 stage1_completed/failed/skipped 事件保持
- **超时用例走真实 wait_for 路径**：settings fixture 缩小超时 + fake ainvoke sleep，而非直接 raise TimeoutError——覆盖生产实际代码路径

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - 计划文本笔误] Task 3 中 `ClarifyAdapter.run` 实为 `ClarifyAdapter.clarify`**
- **Found during:** Task 3
- **Issue:** 计划文本引用 `ClarifyAdapter.run(session)`，但该类唯一入口方法为 `clarify(session)`（满足 ClarifyProtocol）
- **Fix:** 测试调用 `adapter.clarify(session)`，断言语义与计划一致（返回 `{"needs_clarification": False}`、create_round 未调用、无 clarification.asked emit）
- **Files modified:** server/tests/services/test_engine_clarify.py
- **Verification:** 3 条新用例全绿
- **Committed in:** `95e1c123`

---

**Total deviations:** 1 auto-fixed（计划文本笔误校正，无行为偏差）
**Impact on plan:** 零范围蔓延；所有 must_haves truths 均被实现与测试锁定。

说明：Task 2 标注 `tdd="true"`，但其被测行为即 Task 1 产物（计划刻意先接线再补行为守护，同 105-01 先例）——无独立 RED 阶段，测试首跑即绿（10 passed, 0.17s），符合计划任务顺序而非偏差。

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 105-04（golden harness）可直接消费确定性分级 + breakdown 的候选结构与 `WEIGHT_SET_VERSION`
- 105-05（Stage 1 幂等三件套）在 `_stage1_llm_reasoning` 上叠加 decode 参数固定与输入哈希缓存；snapshot["stage1"] 材料留位
- 105-07（快照落库 + replay）从 `RepoRouteResultV2.snapshot` 取材料经 `_h_route` emit——router 已无 session 依赖
- 前端最小展开（105-06）可从 `to_dict()["breakdown"]` 透传

## Known Stubs

None——`snapshot["stage1"]` 材料按计划由 105-05 补充（计划明示本 plan 只保证 Stage 0 材料随结果携带），非 stub。

## Self-Check: PASSED

- FOUND: server/codegraph/services/repo_router_v2.py（含 `from codegraph.services.repo_router_scoring import`）
- FOUND: server/tests/codegraph/test_repo_router_v2_degraded.py（335 行 >= 120）
- FOUND: commit 749efd65（Task 1）/ 34a44582（Task 2）/ 95e1c123（Task 3）
- 验证命令：`rg -n "min\(.*, 1\.0\)|DEPRECATED_PENALTY" server/codegraph/services/repo_router_v2.py` 无输出；`uv run pytest tests/codegraph tests/services/test_repo_router_adapter.py tests/services/test_engine_clarify.py -q` → 239 passed, 20 skipped

---
*Phase: 105-golden-set*
*Completed: 2026-07-29*
