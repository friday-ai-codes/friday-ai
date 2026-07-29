---
phase: 105-golden-set
plan: 07
subsystem: api
tags: [repo-routing, snapshot, replay, convergence-session-event, redaction, degraded, pytest]

# Dependency graph
requires:
  - phase: 105-golden-set (plan 03)
    provides: "RepoRouteResultV2.degraded 标志 + snapshot Stage 0 材料（最小字段集 node_hits + versions）"
  - phase: 105-golden-set (plan 05)
    provides: "snapshot.stage1 材料（脱敏 prompt/response + prompt_hash + model_id + cache_hit）+ 版本绑定四元组"
provides:
  - "编排链每次路由把完整快照落 ConvergenceSessionEvent：_h_route 组装 payload（candidates+breakdown / stage0 / stage1 / versions / degraded / auto_selected / router_version）整体过 redact_for_ledger 后经 _emit_event 单一入口写入，复用既有 repo.routing 事件名（taxonomy 零改动）"
  - "adapter route() dict 透传 degraded（Phase 107 降级 UI 数据底座）与 snapshot（仅供 _h_route，落 session.routing 前 pop 剔除——session.routing 保持精简）"
  - "离线回放模块 repo_router_replay：replay_route_from_snapshot（快照重建输入 → 纯函数重算 → Stage 1 排列记录重放）+ verify_snapshot_replay（逐字段比对 + diff 文本），零 I/O、与 route()/golden harness 共用同一纯函数"
  - "守护测试 8 用例：有/无 Stage 1 回放同结果、篡改拦截、repo_name 缺失容错、脱敏（sk- 假密钥）、50 hits 满配快照 < 64KB、模块 import 纯度"
affects: [phase-106, phase-107]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Stage 1 排列记录以 payload.candidates 顺序 + 每候选最终 confidence 为载体（stage1 无 skipped_reason 标记 LLM 参与）；回放以最终 confidence 为 hint 重过 apply_llm_adjustment——合法记录恒等复现，违反只降不升的篡改记录被 verify 拦截"
    - "快照 payload 组装集中在 _routing_snapshot_payload 纯 helper（builtin_processes），写入仍只经 _emit_event 单一入口（INV-6）"
    - "replay 模块零 I/O：仅 stdlib + repo_router_scoring，import 纯度由测试源码扫描守护"

key-files:
  created:
    - server/codegraph/services/repo_router_replay.py
    - server/tests/codegraph/test_repo_router_replay.py
  modified:
    - server/services/process_runtime/repo_router_adapter.py
    - server/services/process_runtime/builtin_processes.py
    - server/tests/services/test_repo_router_adapter.py

key-decisions:
  - "Stage 1 排列记录不在 stage1 dict 重复存一份：payload.candidates 顺序即排列、confidence 即只降不升后的最终值——回放以其为 hint 重过 apply_llm_adjustment（min(det, min(det,hint))==min(det,hint) 恒等），并天然获得「low 伪造成 high 的篡改记录必与重算不一致」的校验性质"
  - "replay 重建 hit 时 node_id 必须回填进 payload（计划重建形状未列）：aggregate_and_score 桶内 tie-break 第二键读 payload.node_id，缺失会让等分 hits 顺序不定 → facets 取样漂移"
  - "adapter skipped 路径（无 requirement_text）返回 dict 保持三键不变：无 router 运行 degraded 概念不适用，且既有测试对该 dict 做全等断言"
  - "replay 输出 round 口径与 RepoRouteCandidateV2.to_dict 一致（score 4 位 / breakdown 6 位）——记录值本就是 to_dict 产物，同 round 后比对容差 1e-9 即逐字段相等"

patterns-established:
  - "快照落盘与回放的输入契约：_h_route payload 形状（RESEARCH Pattern 3）即 replay_route_from_snapshot 的唯一输入，测试快照构造走真实 _h_route 组装路径锁生产形状"

requirements-completed: [ROUTE-09]

coverage:
  - id: D1
    description: "编排链每次路由落完整脱敏快照：payload 含 candidates[].breakdown / stage0 / stage1 / versions / degraded，经 redact_for_ledger + _emit_event 单一入口，复用 repo.routing 事件名（taxonomy 零改动）；session.routing 剔除 snapshot 键且携带 degraded"
    requirement: ROUTE-09
    verification:
      - kind: unit
        ref: "server/tests/services/test_repo_router_adapter.py#test_h_route_emits_snapshot_payload_and_strips_snapshot_from_routing / test_adapter_dict_carries_degraded_and_snapshot / test_h_route_without_snapshot_keeps_minimal_payload"
        status: pass
      - kind: unit
        ref: "uv run pytest tests/services/test_event_taxonomy_alignment.py -q（零改动通过）"
        status: pass
    human_judgment: false
  - id: D2
    description: "从快照可离线回放出同一结果（候选顺序/分数/breakdown/confidence 逐字段相等）且全程零网络：有 Stage 1（排列重排 + 只降不升 hint）与无 Stage 1（降级路径）两条路径均覆盖，篡改 confidence 被 verify 拦截"
    requirement: ROUTE-09
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_replay.py#test_replay_matches_recorded_without_stage1 / test_replay_matches_recorded_with_stage1_permutation / test_verify_detects_tampered_confidence（默认 --disable-socket 下 0.09s 全绿）"
        status: pass
    human_judgment: false
  - id: D3
    description: "repo_name 缺失历史快照容错：回放不抛异常，比对键固定 repo_id/score/breakdown/confidence（不含 repo_name），含名/缺名等值输入回放结果逐字段一致"
    requirement: ROUTE-09
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_replay.py#test_replay_tolerates_missing_repo_name / test_replay_result_invariant_to_repo_name_presence"
        status: pass
    human_judgment: false
  - id: D4
    description: "快照 payload 安全与体积护栏：注入 sk- 假密钥经 _h_route 组装路径后序列化文本无明文（T-105-15）；50 node_hits 满配快照 < 64KB（T-105-16）；replay 模块 import 纯度（禁 django/qdrant/langchain）"
    requirement: ROUTE-09
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_replay.py#test_snapshot_payload_redacts_injected_secret / test_snapshot_payload_under_64kb_with_50_hits / test_replay_module_import_purity"
        status: pass
    human_judgment: false

# Metrics
duration: 18min
completed: 2026-07-29
status: complete
---

# Phase 105 Plan 07: 快照落盘与离线回放闭环 Summary

**ROUTE-09 收口：_h_route 把 105-03/105-05 随 RepoRouteResultV2.snapshot 携带的材料组装成完整快照 payload（候选 breakdown / stage0 输入 / 脱敏 stage1 材料 / 版本四元组 / degraded），整体过 redact_for_ledger 后经 _emit_event 复用 repo.routing 事件落 ConvergenceSessionEvent（taxonomy 零改动）；repo_router_replay 从快照重建输入、纯函数重算、零网络逐字段复现同一结果，adapter 同步透传 degraded 进 session.routing**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-07-29T04:59:00Z
- **Completed:** 2026-07-29T05:17:00Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- **快照落盘（写入侧）**：`_h_route` 从 adapter dict pop 出 snapshot 材料，组装 RESEARCH Pattern 3 形状 payload（`candidates[].breakdown` + `stage0.node_hits` 最小字段集 + 脱敏 `stage1` + `versions` 四元组 + `degraded/auto_selected/router_version`），整体经 `redact_for_ledger`（T-105-15 第二重防线）后仍只经 `_emit_event` 单一入口写入（INV-6）——复用既有 `repo.routing` 事件名，event taxonomy 守护测试零改动通过
- **session.routing 保持精简**：snapshot 键落 stage_state 前剔除（防 session 行膨胀），同时新增 `degraded` 透传——Phase 107 降级 UI 的数据底座就绪；snapshot 缺失（stub router / skipped / v1_fallback 无 stage0 材料）时优雅降级为现状精简 payload，既有编排测试零改动通过
- **离线回放（读取侧）**：`replay_route_from_snapshot` 从 `stage0.node_hits` 还原 hit 形状 → `aggregate_and_score` 重算 → Stage 1 参与时按 payload 排列记录重排 + `apply_llm_adjustment`（confidence hint 回放）→ 输出与记录逐字段相等（score 容差 1e-9）；`verify_snapshot_replay` 产出逐候选逐字段 diff 文本，「low 伪造成 high」的篡改记录被拦截
- **零网络与共用纯函数**：replay 模块零 I/O（仅 stdlib + repo_router_scoring，import 纯度由测试源码扫描守护），与 `route()`/golden harness 调同一份 `aggregate_and_score/derive_confidence/apply_llm_adjustment`，8 用例在默认 `--disable-socket` 下 0.09s 全绿——Phase success criterion 3 后半句（快照可离线回放零网络同结果）成立
- **安全与体积护栏**：注入 `sk-` 假密钥走真实 `_h_route` 组装路径后序列化 payload 无明文；50 node_hits 满配快照 < 64KB；`repo_router_v2_snapshot_emitted` debug 观测（payload_bytes + degraded，best-effort try/except，category=sampling/component=process_runtime）
- 收官定向回归：`tests/codegraph + tests/delivery` 全量 684 passed / 20 skipped（golden 门禁零退化）

## Task Commits

Each task was committed atomically:

1. **Task 1: adapter degraded/snapshot 透传 + _h_route 快照 payload 落盘** - `1fd1f36f` (feat)
2. **Task 2 (RED): 快照离线回放守护用例** - `67a641de` (test)
3. **Task 2 (GREEN): 离线回放模块 repo_router_replay** - `4b0f6a8b` (feat)

## Files Created/Modified

- `server/codegraph/services/repo_router_replay.py` - 零 I/O 回放模块：`replay_route_from_snapshot` + `verify_snapshot_replay` + `_rebuild_hits`/`_deterministic_confidence`（复刻 route() rank-1/rank>1 推导顺序，阈值全参数注入无字面量）（214 行 >= 60）
- `server/tests/codegraph/test_repo_router_replay.py` - 回放/篡改拦截/repo_name 容错/脱敏/64KB/import 纯度 8 用例，快照构造走真实 `_h_route` 组装路径（309 行 >= 80）
- `server/services/process_runtime/builtin_processes.py` - `_routing_snapshot_payload` helper + `_h_route` 快照组装/emit/snapshot 键剔除/debug 观测
- `server/services/process_runtime/repo_router_adapter.py` - route() dict 新增 `degraded` 与 `snapshot` 键（candidates 精简三键不变）
- `server/tests/services/test_repo_router_adapter.py` - 追加 degraded/snapshot 透传 + _h_route payload 组装 + 精简降级 3 用例（既有 5 条零改动）

## Decisions Made

- **Stage 1 排列记录载体**：计划要求「payload 含 stage1 排列记录」——实现上排列记录即 `payload.candidates` 顺序 + 每候选最终 confidence（`stage1` 无 `skipped_reason` 标记 LLM 参与），不在 stage1 dict 重复存一份。回放以最终 confidence 为 hint 重过 `apply_llm_adjustment`：合法记录满足 `min(det, min(det, hint)) == min(det, hint)` 恒等必得同值；违反只降不升的记录（篡改）重算必不一致、被 verify 拦截——比重复存排列多出一条完整性校验性质
- **adapter skipped 路径保持三键**：无 requirement_text 时 router 未运行，degraded 概念不适用；既有测试对该 dict 全等断言，保持不变零破坏
- **replay 输出 round 口径对齐 to_dict**：记录候选来自 `RepoRouteCandidateV2.to_dict()`（score round 4 / breakdown round 6），replay 输出同 round——两侧同源浮点同 round 后差恒为 0，1e-9 容差仅防序列化噪声

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - 计划重建形状缺陷] replay 重建 hit 的 payload 必须含 node_id**
- **Found during:** Task 2
- **Issue:** 计划给出的重建形状 `{"id": node_id, "score", "payload": {"repository_id", "node_path", "facets"}}` 未把 node_id 放进 payload——`aggregate_and_score` 桶内 tie-break 第二键读 `payload.node_id`，缺失时等分 hits 桶内顺序不定 → 桶首 hit 漂移 → facets（活跃度）取样漂移，破坏「同输入必同输出」
- **Fix:** `_rebuild_hits` 把 node_id 同时写进 hit 顶层 `id` 与 `payload.node_id`（与生产 Qdrant payload 形状一致）
- **Files modified:** server/codegraph/services/repo_router_replay.py
- **Verification:** 回放相等 4 用例 + repo_name 容错用例全绿
- **Committed in:** `4b0f6a8b`

---

**Total deviations:** 1 auto-fixed（计划重建形状补正，确定性正确性要求）
**Impact on plan:** 零范围蔓延；所有 must_haves truths 均实现并被测试锁定。

说明：Task 2 标注 `tdd="true"` 且本次为真实 RED→GREEN：先提交守护用例（模块缺失、collection error，`67a641de`），再提交实现（8 passed，`4b0f6a8b`）。

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase success criterion 3 完整成立：双跑幂等（105-05）+ 快照落盘 + 离线回放零网络同结果（本 plan）
- Phase 107（降级 UI）：session.routing 已携带 `degraded`，UI 直接读取；trace 事件里有完整快照可做逐候选展开
- Phase 106（公式定版）：快照 versions 携带 weight_set_version——公式演进后 replay 按快照当时版本比对（θ 参数注入，无字面量耦合）
- 105-08（若有）/收官验证可用 `verify_snapshot_replay` 对生产快照抽样审计

## Known Stubs

None

## Self-Check: PASSED

- FOUND: server/codegraph/services/repo_router_replay.py（214 行 >= 60，含 aggregate_and_score/derive_confidence/apply_llm_adjustment 复用）
- FOUND: server/tests/codegraph/test_repo_router_replay.py（309 行 >= 80）
- FOUND: commit 1fd1f36f（Task 1）/ 67a641de（Task 2 RED）/ 4b0f6a8b（Task 2 GREEN）
- 验证命令：`rg -c "EVENT_REPO_ROUTING" builtin_processes.py` = 2（import + 单一 emit 点）；`rg -c "redact_for_ledger"` = 3 >= 1；`uv run pytest tests/codegraph tests/delivery -q` → 684 passed, 20 skipped；`tests/services/test_repo_router_adapter.py + test_event_taxonomy_alignment.py + test_plan_orchestration_engine.py` 全绿

---
*Phase: 105-golden-set*
*Completed: 2026-07-29*
