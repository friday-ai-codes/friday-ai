---
phase: 17-varref
plan: 02
subsystem: workflow-api
tags: [short-id, bulk-update, var-ref, ref-rewrite, pytest]

# Dependency graph
requires:
  - phase: 17-varref
    plan: 01
    provides: "解析核心与双键兼容语义（本计划建立的不变式由其消费）"
provides:
  - "bulk-update 保存路径 short_id 收敛：客户端权威落库 / 工作流内唯一性 / 缺失冲突非法时服务端重生成"
  - "公共重写引擎 workflows/templates/loader.rewrite_template_refs（旧私有 _rewrite_template_refs 公共化）"
  - "核心不变式『保存成功 ⇒ 引用可解析』及其专项集成测试"
affects: [17-03, 17-04, phase-20-validation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "short_id 解析独立纯逻辑函数 _resolve_short_ids（payload 顺序先到先得），与落库循环解耦"
    - "id_map 防卫规则：仅客户端显式提供、最终值变化、且客户端值最终无归属时才重写"
    - "刻意不动 serializer（short_id 保留 read_only_fields），视图函数显式读 payload 处理，隔离单节点 PUT 路径"

key-files:
  created:
    - server/tests/workflows/test_bulk_update_short_id.py
  modified:
    - server/workflows/api/views.py
    - server/workflows/templates/loader.py
    - server/tests/workflows/test_template_loader.py

key-decisions:
  - "场景 5（冲突重生成+全工作流重写）的测试构造采用 delete_orphans=True 删除冲突既有节点——这是同时满足『与既有节点冲突』与防卫规则（客户端值最终无归属才重写）的唯一一致构造"
  - "update 节点客户端值非法/冲突时按计划走重生成（不回退 DB 现值）；缺失时保留 DB 现值"
  - "重生成避让集合 = 全部 DB 现值 ∪ payload 合法客户端值 ∪ 已分配值，避免随机值与未处理节点撞车"

patterns-established:
  - "_SHORT_ID_RE = ^[A-Za-z][A-Za-z0-9]{0,11}$ 作为 short_id 服务端白名单（T-17-10, ASVS V5）"
  - "重写范围严格限定 workflow.nodes 并有跨工作流隔离测试（T-17-11）"

requirements-completed: [VAR-01]

# Metrics
duration: ~20min
completed: 2026-06-13
---

# Phase 17 Plan 02: bulk-update short_id 收敛 Summary

**bulk-update 事务内实现客户端 short_id 权威落库 + 工作流内先到先得唯一性 + 缺失/冲突/非法时服务端重生成并全工作流重写 config 引用（复用公共化的 rewrite_template_refs），15 个集成测试锁定"保存成功 ⇒ 引用可解析"不变式。**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-06-12T16:32:00Z
- **Completed:** 2026-06-12T16:52:00Z
- **Tasks:** 2/2
- **Files modified:** 4（新建 1 + 修改 3）

## Accomplishments

- `loader.py` 的 `_rewrite_template_refs` 公共化为 `rewrite_template_refs`，docstring 通用化（模板 ID→short_id 与旧 short_id→新 short_id 两类重写共用），`server/workflows/` 下旧私有名零残留
- `views.py` 新增 `_resolve_short_ids` 纯逻辑函数 + `_bulk_update_nodes_and_edges` 事务内集成：
  - 白名单 `^[A-Za-z][A-Za-z0-9]{0,11}$` 拒绝注入模板语法/重写正则的字符（T-17-10）
  - 先到先得按 payload 顺序采纳客户端值；update 节点对自身 DB 现值不算冲突；payload 缺失时保留现值（存量行为不回退）；存量重复（A2）走同一重生成路径自愈
  - id_map 三重防卫：客户端显式提供 + 最终值变化 + 客户端值落库后无归属（用落库后 DB 实际 short_id 集合过滤，天然涵盖 delete_orphans 释放的值）
  - id_map 非空时对该工作流全部节点（含本次未改动的）config 执行重写，范围严格限定本 workflow（T-17-11）
- serializer 零改动：short_id 留在 `read_only_fields`，单节点 `node_detail` PUT/PATCH 路径行为零变化（规避 RESEARCH Pitfall 5）
- 新增 15 个集成测试覆盖计划全部 8 类场景 + 非法格式参数化（7 种注入/越界值），含 `test_invariant_save_implies_resolvable` 不变式专项与跨工作流越权防护
- 全量回归：`tests/workflows/` 358 个测试全绿

## Task Commits

Each task was committed atomically:

1. **Task 1: 公共化重写引擎 + bulk-update 事务内 short_id 解析/唯一性/重写** - `50796a3c` (feat)
2. **Task 2: VAR-01 集成测试——落库/重写/不变式/越权防护** - `56f2cba6` (test)

## Files Created/Modified

- `server/workflows/api/views.py` - 新增 `_SHORT_ID_RE`、`_resolve_short_ids`；`_bulk_update_nodes_and_edges` 集成 short_id 落库与引用重写；docstring 记录不变式与"不动 serializer"的设计取舍
- `server/workflows/templates/loader.py` - `rewrite_template_refs` 公共化（含 `$nodes.` JSONPath 形式与 re.escape 双保险说明）
- `server/tests/workflows/test_bulk_update_short_id.py` - VAR-01 集成测试（直接调用同步事务函数，绕开 HTTP 鉴权噪音；响应契约用 WorkflowSerializer 断言）
- `server/tests/workflows/test_template_loader.py` - 跟随公共化改名同步更新导入与调用（Rule 3）

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 同步更新 test_template_loader.py 的旧私有名引用**
- **Found during:** Task 1
- **Issue:** 计划 files 列表未含该测试文件，但 `_rewrite_template_refs` 改名后其 import 必然失败，阻塞验收标准"既有 test_template_loader.py 全绿"
- **Fix:** import 与 3 处调用点同步改为 `rewrite_template_refs`，类 docstring 同步
- **Files modified:** server/tests/workflows/test_template_loader.py
- **Commit:** 50796a3c（随 Task 1 一并提交）

### 测试构造澄清（计划场景 5 的一致化解读）

计划场景 5 要求"客户端值与既有节点冲突 → 重生成后全工作流重写"，同时 Task 1 防卫规则要求"客户端值最终无归属才重写"。两者同时成立的唯一构造是冲突既有节点在同次保存中被 `delete_orphans=True` 删除（值被释放）——测试按此构造，实现端用"落库+删孤后 DB 实际 short_id 集合"做归属过滤，两条规则一致满足。

### 范围外发现（未修复，已记录 deferred-items.md）

- `test_template_loader.py` 存量 ruff F401（HEAD 即存在，与本计划无关）
- 工作区存在其他进程产生的无关改动（`codegraph/`、`repositories/` 等），未纳入本计划任何提交

## Verification

- `cd server && uv run pytest tests/workflows/test_bulk_update_short_id.py tests/workflows/test_api.py tests/workflows/test_template_loader.py -q` → 89 passed
- `cd server && uv run pytest tests/workflows/ -q` → 358 passed（全量无回归；首跑 test_engine 出现 1 个偶发 teardown error，隔离运行与全量复跑均全绿，确认与本改动无关）
- `cd server && uv run ruff check workflows/api/views.py workflows/templates/loader.py tests/workflows/test_bulk_update_short_id.py` → All checks passed（含 ruff format）
- `rg "_rewrite_template_refs" server/workflows/` → 零匹配（旧私有名清除）
- `git diff` serializers.py → 零改动（验收标准）

## Known Stubs

None — 无占位/stub，全部逻辑已接线并有测试覆盖。

## Threat Flags

无新增安全面：T-17-10（白名单 + re.escape 双保险）与 T-17-11（跨工作流隔离）均已实现并有显式测试断言；T-17-12/T-17-SC 维持 accept 处置，零新依赖、权限层零改动。

## Next Phase Readiness

- 服务端半边收敛完成；17-03（前端 `toBackendNodes` 发送 short_id + 三入口统一）接上后链路闭合
- 响应契约已锁定：bulk-update 返回的 `WorkflowSerializer` 数据含重写后 config 与最终权威 short_id，前端 `saveWorkflow` 既有的响应覆盖逻辑（Pitfall 4）可直接生效
- 导入路径（`Workflow.from_json`）漂移为已知缺口，移交 Phase 20（已记录 deferred-items.md）

## Self-Check: PASSED

- FOUND: server/tests/workflows/test_bulk_update_short_id.py（289 行 ≥ 120，含 test_invariant_save_implies_resolvable）
- FOUND: server/workflows/templates/loader.py 含 `def rewrite_template_refs`
- FOUND: .planning/phases/17-varref/17-02-SUMMARY.md
- FOUND: commit 50796a3c / 56f2cba6
