---
phase: 18-engine
plan: 01
subsystem: api
tags: [workflow-engine, routing, dag, deadlock, target-handle, pure-functions, pytest]

# Dependency graph
requires:
  - phase: 17-variables
    provides: template_resolver 纯函数 + 零 DB 可测策略 + 结构化 error_message 约定（routing.py 逐项照抄）
provides:
  - "routing.py 纯函数路由核心：边感知就绪判定 / handle 后继选择 / skipped fixpoint 级联 / 结构化死锁诊断 / target_handle 非破坏性输入归集"
  - "DAGNode.incoming_edges 入边明细 (source_id, source_handle, target_handle)，双构建器对称收集"
  - "engine 包 barrel 导出 routing 公开 API（RoutingState 及五函数）"
  - "三个零 DB 单测文件 + 一个 django_db 入边明细测试类（test_engine_routing/deadlock/inputs）"
  - "_build_dag 测试 helper（test_engine_routing.py 模块级，供 deadlock/inputs 复用）"
affects: [18-02, 18-03, 18-04, 18-05, 19-engine, 20-engine, 21-engine]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "纯函数路由核心（DAG + plain dict 入参，零 ORM，零 DB 单测）——主循环与回调续跑唯一语义源"
    - "RoutingState dataclass 由调用方填充 statuses/handles，纯函数不感知内存/DB 来源（封堵双来源不对称）"
    - "结构化诊断只含拓扑元数据（名称/short_id/状态/handle），函数签名不接收 node_outputs（V5 信息泄露防线）"

key-files:
  created:
    - server/workflows/engine/routing.py
    - server/tests/workflows/test_engine_routing.py
    - server/tests/workflows/test_engine_deadlock.py
    - server/tests/workflows/test_engine_inputs.py
  modified:
    - server/workflows/engine/dag.py
    - server/workflows/engine/__init__.py

key-decisions:
  - "diagnose_deadlock 与 collect_inputs 实现随 Task 2 同模块（routing.py）落地，Task 3 仅补齐其零 DB characterization 测试——同文件不拆分实现，避免半成品提交"
  - "_build_dag 测试 helper 用有序 dict 收集 node_ids（源先于目标），保证 _detect_back_edges 的 DFS 起点确定、反馈环识别稳定"
  - "collect_inputs 对非 dict 上游输出仍按端口键归集（防御性，现状 _collect_inputs 仅处理 dict）"

patterns-established:
  - "routing 四类判定纯函数：evaluate_node_readiness / select_successors / compute_skippable / diagnose_deadlock / collect_inputs"
  - "边感知就绪四枚举闭集：ready / skip_failed / skip_unselected / blocked"
  - "default 回退选中规则：源 next_handle 不在 outgoing 任何桶时 default 边视为选中（characterization，与 scheduler.py:1411-1420 等价）"

requirements-completed: [ENG-02, ENG-04, ENG-05]

# Metrics
duration: ~35min
completed: 2026-06-13
---

# Phase 18 Plan 01: 工作流引擎路由纯函数核心 + DAGNode 入边明细 Summary

**routing.py 边感知就绪/级联/死锁/target_handle 归集四类纯函数核心 + DAGNode.incoming_edges 入边明细，零 DB 单测全绿，为 18-02..05 主循环与回调续跑提供唯一语义源**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-06-13T06:19Z（约）
- **Completed:** 2026-06-13T06:30Z（约）
- **Tasks:** 3
- **Files modified/created:** 6（2 修改 + 4 新建）

## Accomplishments
- `routing.py` 纯函数路由核心：`evaluate_node_readiness`（边感知就绪四枚举）、`select_successors`（handle 命中 + default 回退）、`compute_skippable`（fixpoint 级联）、`diagnose_deadlock`（结构化诊断）、`collect_inputs`（target_handle 非破坏性归集），全部不 import Django ORM、零 DB 可测
- `DAGNode.incoming_edges` 入边明细字段 + `from_workflow`/`afrom_workflow` 双构建器对称收集（逐字符一致）
- CONTEXT 锁定语义全部落地并单测覆盖：菱形汇合一活一死判 ready、双支全 skip 级联、前置失败 ANY skip_failed、tolerated 算选中、back-edge 不阻塞、死锁三条件、归集四规则
- 全量 `tests/workflows/` 397 例绿（368 基线 + 29 新增），零回归

## Task Commits

Each task was committed atomically:

1. **Task 1: DAGNode 增加入边明细 incoming_edges（双构建器对称）** - `ca0f0adfe` (feat)
2. **Task 2: routing.py 就绪判定/后继选择/级联纯函数 + __init__ 导出 + 单测** - `5f0ef59c6` (feat)
3. **Task 3: diagnose_deadlock + collect_inputs characterization 单测** - `66cba775b` (test)

_注：Task 2 / Task 3 采用本机 RED→GREEN 验证（写测试见红 → 写实现转绿）后单提交，未拆分独立 test/feat 提交——见下方 TDD Gate Compliance。_

## Files Created/Modified
- `server/workflows/engine/routing.py`（新建）- 路由/级联/死锁/输入收集纯函数，主循环与回调续跑唯一语义源
- `server/workflows/engine/dag.py`（修改）- DAGNode.incoming_edges 字段 + 双构建器收集
- `server/workflows/engine/__init__.py`（修改）- barrel 导出 RoutingState 及五函数，扩 `__all__`
- `server/tests/workflows/test_engine_routing.py`（新建）- 入边明细 django_db 类 + 就绪/后继/级联零 DB 单测 + `_build_dag` helper
- `server/tests/workflows/test_engine_deadlock.py`（新建）- 死锁三条件 + 信息泄露防线 characterization
- `server/tests/workflows/test_engine_inputs.py`（新建）- plan/coding_result 两条真实节点链归集 characterization

## routing 公开 API 最终签名（18-02/03/04/05 消费）

```python
@dataclass
class RoutingState:
    statuses: dict   # node_id -> STATUS_* 字面值
    handles: dict    # node_id -> next_handle（缺省 "default"）

evaluate_node_readiness(dag, node_id, state) -> str
    # "ready" | "skip_failed" | "skip_unselected" | "blocked"
select_successors(dag, node_id, next_handle) -> list[DAGNode]
compute_skippable(dag, state, pending) -> dict[node_id, 原因]
diagnose_deadlock(dag, state, pending) -> dict | None
    # {"reason": "deadlock", "pending": [{"node","short_id","waiting_on":[{"node","short_id","status","handle"}]}]}
collect_inputs(dag, node_id, node_outputs) -> dict
```

模块常量：`STATUS_COMPLETED/SKIPPED/FAILED/TOLERATED/WAITING/RUNNING/PENDING`；终态集合 `_RESOLVED_STATUSES = {completed, skipped, tolerated}`、选中集合 `_SELECTABLE_STATUSES = {completed, tolerated}`（私有）。

`_build_dag(edges, extra_nodes=None)` 测试 helper 位于 `server/tests/workflows/test_engine_routing.py` 模块级，签名 `edges: list[(source_id, target_id, source_handle, target_handle)]`，deadlock/inputs 测试经 `from tests.workflows.test_engine_routing import _build_dag` 复用。

## Decisions Made
- **diagnose_deadlock / collect_inputs 实现随 Task 2 落地**：二者与 Task 2 的三函数同属 routing.py 单文件，为避免提交"半成品模块"，实现一次性写入 Task 2 提交（`5f0ef59c6`），Task 3 仅新增两个测试文件补齐 characterization。功能与验证完整，仅提交边界与计划的逐任务实现切分略有不同。
- **_build_dag 用有序 dict 收集节点**：`_detect_back_edges` 的 DFS 起点依赖 `dag.nodes` 字典顺序；无序集合会让反馈环（back-edge）识别非确定。改为"源先于目标"的插入顺序后 back-edge 用例稳定通过（与 ORM 创建顺序一致）。
- **collect_inputs 防御非 dict 上游**：现状 `_collect_inputs` 仅 `inputs.update(dict)`；新实现对非 dict 上游输出仍按端口键归集（不 update），更稳健且不影响现状 dict 路径。

## Deviations from Plan

### 结构性偏差（非缺陷）

**1. [实现切分] diagnose_deadlock + collect_inputs 实现并入 Task 2 提交**
- **Found during:** Task 2（routing.py 创建时单文件写入全部五函数）
- **Issue:** 计划将 diagnose_deadlock/collect_inputs 列为 Task 3 实现项；但它们与 Task 2 的三函数同属 routing.py，分两次提交会在 Task 2 后留下"被引用但未实现"或半成品模块
- **Fix:** Task 2 一次性写入并导出全部五函数；Task 3 专注新增 test_engine_deadlock.py / test_engine_inputs.py 两个 characterization 测试文件
- **Files modified:** server/workflows/engine/routing.py（Task 2 内）
- **Verification:** Task 3 两测试文件 + 全量 tests/workflows/ 397 例全绿；diagnose 函数体 `node_outputs` 零命中
- **Committed in:** `5f0ef59c6`（实现）、`66cba775b`（测试）

---

**Total deviations:** 1 结构性（提交边界），0 功能性
**Impact on plan:** 无功能偏差、无范围蔓延；所有 must_haves truths/artifacts 均已实现并测试覆盖。RESEARCH Pattern 3（边感知判定）与 Pattern 5（非破坏性归集）逐项照实现，无语义偏离。

## TDD Gate Compliance

计划任务标记 `tdd="true"`，但本次为顺序执行 + 每任务原子提交。Task 1/2/3 均采用"先写测试本机见红 → 写实现转绿 → 单次提交（test+impl）"的务实 TDD，未拆分独立的 `test(...)`→`feat(...)` 红绿提交对。Task 3 因实现已在 Task 2 落地，其提交为纯 `test(...)`。功能正确性由 RED→GREEN 本机验证 + 全量 397 例回归保证。

## Issues Encountered
- `uv run` 偶发重排 `server/uv.lock`：本计划零新依赖，已按执行约定每次提交前 `git checkout -- server/uv.lock` 还原，最终 uv.lock 无 diff。
- back-edge 用例首跑失败（_build_dag 节点集合无序导致 DFS 起点不定）→ 改有序 dict 收集后稳定通过。

## Threat Surface
- T-18-01（死锁诊断信息泄露）已缓解：`diagnose_deadlock` 签名不接收 node_outputs，函数体 `node_outputs` 零命中；test_engine_deadlock.py::test_diagnosis_serializable_without_output_values 断言序列化串不含输出值。
- 无新增网络端点/鉴权路径/schema 变更（纯内存纯函数 + 测试）。

## Next Phase Readiness
- 18-02/03（主循环改造）与 18-04/05（回调续跑）可直接 `from workflows.engine import ...` 消费五函数，无需任何语义再设计。
- conftest 工作流工厂夹具（branch/waiting/deadlock workflow）仍待 18-02 落地（本计划未涉及，按 PATTERNS 归属 18-02）。
- 已知缺口（RESEARCH 记录，非本计划范围）：scheduler 主循环/回调续跑尚未接入 routing；trigger_data 注入（ENG-03）、waiting_event 挂起（ENG-01）属后续计划。

## Self-Check: PASSED

- 全部 6 个源文件 + SUMMARY.md 存在于磁盘
- 三个任务提交 `ca0f0adfe` / `5f0ef59c6` / `66cba775b` 均可达
- `tests/workflows/` 397 例全绿（含 29 新增）；routing/deadlock/inputs ruff format + check 通过；`server/uv.lock` 无 diff

---
*Phase: 18-engine*
*Completed: 2026-06-13*
