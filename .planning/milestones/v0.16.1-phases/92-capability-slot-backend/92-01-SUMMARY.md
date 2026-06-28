---
phase: 92-capability-slot-backend
plan: 01
subsystem: workflow-validation
tags: [workflow, node-port, shape, capability-contract, graph-validator, slot]

# Dependency graph
requires:
  - phase: 20-workflow-validation
    provides: WorkflowGraphValidator 五类静态校验 + ValidationIssue + 5 API 入口同源 validate()
provides:
  - NodePort.shape 能力契约字段（与 port_type 正交，默认 ""=通配，向后兼容零回归）
  - get_schema() inputs/outputs 输出 shape 键（/api/node-types/ 暴露给前端）
  - KNOWN_PORT_SHAPES frozenset 常量集合（7 个能力契约取值，可扩展非闭集）
  - WorkflowGraphValidator._validate_port_shapes 契约兼容规则 + incompatible_port_shape reason
affects: [92-02, 92-03, 93-slot-editor]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "端口契约 = str + 模块级 frozenset 常量集合（非 Enum，取值可扩展）"
    - "validator 第六类规则纯函数：双端非空且不等才报，任一端空即通配短路放行"

key-files:
  created:
    - server/workflows/nodes/shapes.py
    - server/tests/workflows/test_node_schema.py
  modified:
    - server/workflows/nodes/base.py
    - server/workflows/validation/graph_validator.py
    - server/tests/workflows/test_graph_validator.py

key-decisions:
  - "shape 用扁平 str + KNOWN_PORT_SHAPES frozenset，validator 不做闭集拦截（仅靠双端相等判定）"
  - "向后兼容命门：任一端空契约/default 端口/handle 非法/未知节点全部 continue 放行"
  - "本 plan 仅加 shape 字段，不改 dump_node_fixture（_to_fixture_node 不 dump shape），不触 fixture"

patterns-established:
  - "能力契约校验：_validate_port_shapes 串接在 validate() 末尾，5 入口同源生效"

requirements-completed: [SLOT-01]

# Metrics
duration: 12min
completed: 2026-06-27
---

# Phase 92 Plan 01: 端口能力契约字段 + Validator 契约兼容校验 Summary

**NodePort.shape 正交能力契约字段（空=通配向后兼容）+ KNOWN_PORT_SHAPES 常量集合 + get_schema 输出 + WorkflowGraphValidator._validate_port_shapes 契约兼容规则（incompatible_port_shape）**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-06-27T10:24:00Z
- **Completed:** 2026-06-27T10:34:00Z
- **Tasks:** 2（均 TDD）
- **Files modified:** 5（2 created + 3 modified）

## Accomplishments
- `NodePort` 新增与 `port_type` 正交的 `shape: str = ""` 能力契约字段，全仓既有数十处构造零破坏（默认空=通配宽松）。
- `get_schema()` 的 inputs/outputs 各输出 `shape` 键，经 `/api/node-types/` 单向只读流出给前端（Phase 93 磁吸消费）。
- 新建 `workflows/nodes/shapes.py`，`KNOWN_PORT_SHAPES` frozenset 一次性收全 7 个能力契约取值（clarification_request/clarification_answer/feishu_message/technical_plan/coding_assignment/feishu_document/approval_result），可扩展、非闭集。
- `WorkflowGraphValidator` 新增第六类规则 `_validate_port_shapes`：双端契约非空且不等才报 `incompatible_port_shape`（severity=error，带 edge_id/field_path），任一端空/default/handle 非法/未知节点均放行；串接在 `validate()` 末尾，5 个 API 入口同源覆盖。

## Task Commits

每个任务原子提交（TDD：test → feat）：

1. **Task 1 RED: NodePort.shape/KNOWN_PORT_SHAPES/get_schema 失败测试** - `99497b7e4` (test)
2. **Task 1 GREEN: NodePort.shape 字段 + shapes.py + get_schema 输出** - `0631c80dc` (feat)
3. **Task 2 RED: _validate_port_shapes 契约兼容失败测试** - `dd8289925` (test)
4. **Task 2 GREEN: _validate_port_shapes 规则 + validate() 串接 + reason 枚举** - `88ee0fce2` (feat)
5. **Task 2 cleanup: ruff format + mypy-safe node_type 收窄** - `6959b3e43` (style)

## Files Created/Modified
- `server/workflows/nodes/shapes.py` - KNOWN_PORT_SHAPES 能力契约常量集合 + 设计注释（str + frozenset，非 Enum，校验器不闭集拦截）
- `server/workflows/nodes/base.py` - NodePort.shape 字段 + get_schema() inputs/outputs 输出 shape 键
- `server/workflows/validation/graph_validator.py` - _validate_port_shapes 规则 + validate() 串接 + ValidationIssue.reason 枚举补 incompatible_port_shape
- `server/tests/workflows/test_node_schema.py` - NodePort.shape 默认/赋值 + get_schema shape 键 + KNOWN_PORT_SHAPES 成员（4 用例）
- `server/tests/workflows/test_graph_validator.py` - 端口契约兼容 7 用例（不兼容报错/双端相等放行/源端空/目标端空/default 零回归/handle 非法不重复报/message 只含拓扑）

## Decisions Made
- 契约用扁平 `str` + 模块级 `frozenset`（KNOWN_PORT_SHAPES）而非 Enum——CONTEXT 明确「取值应可扩展」，validator 仅靠「双端 shape 非空且相等」判定，不强制取值 ∈ 集合（未知取值不被闭集拦截）。
- 向后兼容命门逐条落实：`if not src_shape or not tgt_shape: continue` 短路放行 + default 端口 shape 恒空，既有合法图用例作零回归红线。
- mypy 安全：`_validate_port_shapes` 用 `src_type/tgt_type` 显式 None 守卫，避免新增 arg-type 误报（与既有 `_validate_edges` subscript 风格不同但更安全）。

## Deviations from Plan

None - plan executed exactly as written.（Task 1/2 行为与 verify 命令全部按 PLAN 落实；唯一额外动作是 Task 2 后补一条 `style` 提交做 ruff format + mypy 收窄，属常规收尾不改行为。）

## Issues Encountered
- **mypy arg-type 误报（新增 2 处）：** `NodeRegistry.get(src.get("node_type"))` 传入 `Any | None` 触发 arg-type。改用 `src_type = src.get(...)` + `if src_type is None: continue` 收窄后消除；文件原有 3 处同类 `.get()` 错误为**既有**（base 同样存在），未在本 plan 范围内修复（scope boundary）。
- **全量 `tests/workflows` 4 个失败（test_execution_concurrency ×2 + test_template_loader ×2）经核实为既有失败：** 已将本 plan 3 个源文件回退至 base 复跑确认 4 个失败完全一致（`field_not_found`/并发计时，与 shape 改动无关），非本 plan 引入。本 plan 新增/相关用例（test_graph_validator + test_node_schema，38 项）全绿。

## User Setup Required
None - 纯仓内 Python 改动，无外部服务配置、无新增依赖、无 DB 迁移。

## Next Phase Readiness
- SLOT-01 完成：端口能力契约字段 + 校验链路就绪，92-02 可在此基础上给 `ai_plan_research` 贴 `clarify`/`resume` 插槽端口（shape=clarification_request/answer），新建边将自动受 `_validate_port_shapes` 约束。
- `KNOWN_PORT_SHAPES` 已铺底全 7 个取值，93 磁吸前端可直接消费 get_schema() 的 shape 键。
- 注意：本 plan 未触 fixture（_to_fixture_node 不含 shape），92-03 新增 clarification_card 节点时需重跑 `pnpm -C web gen:node-fixture`。

## Verification Results
- `uv run pytest tests/workflows/test_graph_validator.py tests/workflows/test_node_schema.py -q` → 38 passed。
- `uv run ruff format --check`（5 文件）+ `ruff check`（All checks passed）。
- `uv run mypy workflows/nodes/shapes.py workflows/validation/graph_validator.py` → 仅 3 个既有 `.get()` arg-type 错误（base 同存），本 plan 零新增。
- `uv run python manage.py makemigrations --check` → No changes detected（无 DB 迁移）。

## Self-Check: PASSED

- 全部 created/modified 文件存在（shapes.py / test_node_schema.py / base.py / graph_validator.py / test_graph_validator.py / 92-01-SUMMARY.md）。
- 全部任务提交存在（99497b7e4 / 0631c80dc / dd8289925 / 88ee0fce2 / 6959b3e43）。

---
*Phase: 92-capability-slot-backend*
*Completed: 2026-06-27*
