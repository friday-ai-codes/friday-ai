---
phase: 106-multi-signal-scoring
plan: 07
subsystem: codegraph-routing
tags: [repo-router, replay, snapshot, scoring, tdd]

requires:
  - phase: 106-01
    provides: aggregate_and_score 六信号新签名（weights/repo_meta/constants/now）与 PHASE105_WEIGHTS/DEFAULT_WEIGHT_CONFIG
  - phase: 106-06
    provides: 快照新节 weight_config（生效全值）/ repo_meta（per-候选 ≤12）/ stage0.scored_at；legacy 回退不写空节
provides:
  - replay_route_from_snapshot 双版本分流：新格式从快照读 weight_config/repo_meta/scored_at 注入纯函数（自包含回放）；旧格式（缺 weight_config 节 / 节残缺）回退 legacy 三信号不抛
  - ReplayResult(list) 返回值契约：向后兼容 list[dict] + weight_set_version/legacy_snapshot 元信息
  - LEGACY_SNAPSHOT_NOTE 常量：legacy 快照 verify diff 头部标注「旧版本快照（phase105-v1），按当时版本比对」
  - 守护测试 10 条：新格式等值/权重自包含/scored_at 锚点/篡改拦截/64KB 复核/旧快照回退三态
affects: [106-08 golden 版本 bump 与 gk-001 翻转, 107 权重调参回放底座]

tech-stack:
  added: []
  patterns:
    - "双版本回放分流以「缺 weight_config 节」识别 legacy——无需版本嗅探，残缺/类型错误一律按 legacy 容错（T-106-18）"
    - "list 子类携带回放元信息（ReplayResult）——扩展返回值契约而不破坏既有 list 消费方"

key-files:
  created: []
  modified:
    - server/codegraph/services/repo_router_replay.py
    - server/tests/codegraph/test_repo_router_replay.py

key-decisions:
  - "legacy 回放的 weight_set_version 恒标 phase105-v1（plan 锁定）——不读 versions 节嗅探，与「缺节即 legacy」判定一致"
  - "LEGACY_SNAPSHOT_NOTE 仅在存在 diff 时插入头部——无差异时 verify 仍返回 (True, \"\")，既有 legacy 等值用例零改动"
  - "非候选仓不参与比对的边界按 plan 落 docstring：快照 repo_meta 只存候选仓（≤12），回放时非候选分桶仓重算分数可能与录制时不同，verify 比对键只含候选（既有语义）"

patterns-established:
  - "新格式快照测试构造走真实组装路径：_stage0_candidates（新路径参数注入）→ _stage0_only_result/_build_snapshot → _h_route 落盘捕获——不手写 payload 字面量"

requirements-completed: [ROUTE-06]

coverage:
  - id: D1
    description: "新格式快照（weight_config + repo_meta + scored_at）零网络自包含回放：候选顺序/score/breakdown（含 domain/stack 键）/confidence 与记录逐字段相等；权重来自快照而非环境默认；活跃度衰减锚点取快照 scored_at 而非系统时钟"
    requirement: ROUTE-06
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_replay.py#TestMultiSignalReplay::test_new_snapshot_replay_matches_recorded + test_new_snapshot_with_stage1_permutation_matches"
        status: pass
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_replay.py#TestMultiSignalReplay::test_replay_weights_come_from_snapshot_not_environment + test_replay_activity_anchor_is_snapshot_scored_at"
        status: pass
    human_judgment: false
  - id: D2
    description: "105 旧快照（缺 weight_config 节 / 节残缺类型错误）回放不抛：PHASE105_WEIGHTS legacy 三信号重算与记录等值，返回值 legacy_snapshot=True + weight_set_version=phase105-v1，verify diff 头部标注旧版本快照——版本不同即不可比（SC-4 回放侧）"
    requirement: ROUTE-06
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_replay.py#TestLegacySnapshotFallback（3 条：no_error_and_flags / version_note / malformed_weight_config）"
        status: pass
      - kind: unit
        ref: "既有 8 条 legacy 守护用例零改动全绿（uv run pytest tests/codegraph/test_repo_router_replay.py -q → 18 passed）"
        status: pass
    human_judgment: false
  - id: D3
    description: "篡改拦截延续到新信号键：新格式快照篡改 breakdown[domain] 被 verify 逐信号 diff 拦截（T-106-17）"
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_replay.py#TestMultiSignalReplay::test_verify_detects_tampered_domain_breakdown"
        status: pass
    human_judgment: false
  - id: D4
    description: "64KB 体积护栏在新字段下复核通过（50 hits + 12 候选满配 repo_meta + weight_config 全值）；replay 模块零 I/O import 纯度保持（仅 stdlib + repo_router_scoring）"
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_replay.py#TestMultiSignalReplay::test_new_snapshot_payload_under_64kb_with_full_meta + test_replay_module_import_purity"
        status: pass
    human_judgment: false

duration: ~13min
completed: 2026-07-29
status: complete
---

# Phase 106 Plan 07: 回放兼容（双版本 replay）Summary

**replay_route_from_snapshot 双版本分流落地：新格式快照从 payload 读 weight_config/repo_meta/scored_at 注入纯函数零网络逐字段回放，105 旧快照回退 PHASE105_WEIGHTS legacy 路径并以 LEGACY_SNAPSHOT_NOTE 标注「按当时版本比对」**

## Performance

- **Duration:** ~13 min
- **Started:** 2026-07-29T14:44Z 前后（RED 用例写作起）
- **Completed:** 2026-07-29T14:56Z
- **Tasks:** 2（TDD：RED → GREEN）
- **Files modified:** 2

## Accomplishments

- **新格式自包含回放（ROUTE-09 既有性质 × ROUTE-06 版本绑定）**：`weight_config.weights/constants`（含快照当时生效 n_bar）、`repo_meta`（per-候选）、`stage0.scored_at`（衰减时间锚点）全部从快照读取注入 `aggregate_and_score` 新路径——把 `DEFAULT_WEIGHT_CONFIG` monkeypatch 成另一组值回放结果不变（快照自包含被测试锁定）。
- **105 旧快照回退**：缺 `weight_config` 节（106-06 锁定的识别方式）或节残缺/类型错误 → `aggregate_and_score(hits)` legacy 三信号路径重算不抛（T-106-18）；verify diff 存在差异时头部加 `LEGACY_SNAPSHOT_NOTE`——版本不同即不可比，不做跨版本换算（research §6.2-9）。
- **返回值契约扩展零破坏**：`ReplayResult(list)` 子类携带 `weight_set_version`（本次回放采用版本）与 `legacy_snapshot` 布尔——既有 8 条用例一行未改全绿。
- **守护测试 10 条**（文件 728 行 ≥ min_lines 380）：新格式等值（降级出口 + Stage 1 排列两路径）/ 权重环境无关 / scored_at 锚点直算断言（last_commit 距锚点 5 天 → 衰减系数恒 1.0，误用真实时钟必现偏差）/ 返回值契约 / breakdown[domain] 篡改拦截 / 64KB 满配复核 / 旧快照回退三态。

## Task Commits

1. **Task 1 (RED): 双版本回放守护用例** - `addeb240` (test) — 10 条新增用例中 9 条对现行实现失败（RED 证据在提交信息注明），既有 8 条保持全绿
2. **Task 2 (GREEN): replay 双版本实现** - `4e7e2aa6` (feat) — 18/18 全绿

## Files Created/Modified

- `server/codegraph/services/repo_router_replay.py` - 双版本分流 + ReplayResult + LEGACY_SNAPSHOT_NOTE + 模块/函数 docstring 双版本契约与非候选仓边界记录（零 I/O import 纯度保持：仅 stdlib + repo_router_scoring）
- `server/tests/codegraph/test_repo_router_replay.py` - 追加 TestMultiSignalReplay（7 条）/ TestLegacySnapshotFallback（3 条）；新格式快照构造走真实 `_stage0_candidates`/`_build_snapshot`/`_h_route` 组装路径

## Decisions Made

- **legacy 版本标注恒为 "phase105-v1"**（plan 锁定语义）：分流判定只看 weight_config 节有无/合法性，不做 versions 嗅探——判定单一来源，残缺节容错路径与旧快照路径合一。
- **注标只在有 diff 时插入**：无差异时 verify 仍返回 `(True, "")`，既有 legacy 等值断言（`diff == ""`）零改动成立。
- **测试文件既有格式漂移不触碰**：`ruff format` 对 HEAD 版本本就非 clean（存量漂移，scope boundary），仅保证新增代码 format 干净；`ruff check`（plan 验证要求）两文件全过。

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - 无外部服务配置需求。

## Next Phase Readiness

- 106-08（golden 版本 bump 与 gk-001 翻转）：回放侧双版本闭环就绪——golden baseline 重建后新版本快照可零网络回归；`WEIGHT_SET_VERSION` bump 与 baseline 重建同步进行的纪律不受本 plan 影响（replay 不再读该模块常量）。
- Phase 107+ 权重调参回放底座就绪：历史快照按各自记录的权重版本离线重算，不混口径。

## Self-Check: PASSED

- `server/codegraph/services/repo_router_replay.py` 存在且含双版本实现（`rg -c "phase105-v1"` = 5 ≥ 1）✓
- `server/tests/codegraph/test_repo_router_replay.py` 728 行 ≥ min_lines 380 ✓
- 提交存在：`addeb240`（test）→ `4e7e2aa6`（feat）——TDD 门序 RED→GREEN 成立 ✓
- import 纯度：模块 import 仅 `__future__`/`typing`/`codegraph.services.repo_router_scoring` ✓
- Task 1 验收：新增 10 条 ≥ 7，RED 时 9 条失败 ≥ 3，既有 8 条全绿 ✓
- Task 2 验收：`uv run pytest tests/codegraph/test_repo_router_replay.py -q` → 18 passed ✓
- Plan 级验证：`uv run pytest tests/codegraph tests/delivery tests/services/test_repo_router_adapter.py -q` → 837 passed / 20 skipped；`uv run ruff check`（2 文件）All checks passed ✓

---
*Phase: 106-multi-signal-scoring*
*Completed: 2026-07-29*
