---
phase: 20-validation
plan: 01
subsystem: api
tags: [workflow, validation, dag, jsonschema, template-resolver, node-registry, pure-function]

# Dependency graph
requires:
  - phase: 17-template
    provides: template_resolver（_TEMPLATE_VAR_RE / _INDEX_SUFFIX_RE / reason 枚举 / T-17-01 信息泄露防线）
  - phase: 18-engine
    provides: DAG.has_cycle 回退边语义 / routing collect_inputs 扁平合并语义
  - phase: 19-ssot
    provides: NodeRegistry 单一事实源 / NodePort.schema
provides:
  - WorkflowGraphValidator 纯函数校验核心（五类规则唯一事实源，零 ORM / 零 DB）
  - ValidationIssue dataclass（结构化问题：reason/severity/field_path/node_id/edge_id/message）
  - DAG.from_node_edge_dicts() 内存构图（plain dict → DAG，复用回退边语义）
  - VAL-01 全规则 + Pitfall 1/2/8 不误伤单测（test_graph_validator.py，20 例零 DB）
affects: [20-02 写入路径接入, 20-03 前端 dry-run/IssuesPanel, 模板 loader 校验, 模板修复]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "纯函数校验核心：plain dict 入参、零 ORM、pytest 零 DB 可测（仿 template_resolver 范式）"
    - "内存构图复用：DAG.from_node_edge_dicts 照搬 from_workflow + _detect_back_edges，SimpleNamespace 承载 node 三属性"
    - "default/空串 handle 恒合法白名单 + condition 动态输出经 get_dynamic_outputs 并入"

key-files:
  created:
    - server/workflows/validation/graph_validator.py
    - server/workflows/validation/__init__.py
    - server/tests/workflows/test_graph_validator.py
  modified:
    - server/workflows/engine/dag.py

key-decisions:
  - "孤立节点降为 warning（Pitfall 8），避免编辑中途草图误报；cycle/no_entry 为 error"
  - "变量字段层取所有输出端口 schema properties 并集（A2），上游无 schema 时只校验节点存在性、字段层跳过（Pitfall 2 / D-03）"
  - "handle 校验仅对非 default 端口下钻，default/空串恒合法（Pitfall 1，防误伤 ai_coding→ai_code_review default 边）"

patterns-established:
  - "纯函数校验：WorkflowGraphValidator.validate(nodes, edges) → {errors, warnings}，每条 asdict(ValidationIssue)"
  - "复用而非重写：DAG 环检测 / template_resolver 正则 / NodeRegistry 列举类型（list(get_all().keys())，不调不存在的 list_types）"

requirements-completed: [VAL-01]

# Metrics
duration: 10min
completed: 2026-06-13
---

# Phase 20 Plan 01: WorkflowGraphValidator 纯函数核心 + DAG 内存构图 Summary

**新建 `WorkflowGraphValidator` 零 ORM 校验事实源（环/入口/孤立、edge 归属与 handle、config jsonschema、`nodes.*` 变量五类规则）+ `DAG.from_node_edge_dicts()` 内存构图，含 20 例零 DB 单测守护 default 恒合法/无 schema 跳字段/condition 动态 handle/孤立降 warning 等不误伤约束。**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-06-13T11:18:19Z
- **Completed:** 2026-06-13T11:28:30Z
- **Tasks:** 3
- **Files modified:** 4（新建 3 / 修改 1）

## Accomplishments
- `DAG.from_node_edge_dicts(nodes, edges)`：从未持久化 plain dict 构图，照搬 `from_workflow` 装配并调用 `_detect_back_edges()` 保留"条件分支非 default handle 回退边不算环"语义；`SimpleNamespace` 承载 `id/node_type/name` 三属性。
- `WorkflowGraphValidator.validate()`：五类规则（node_type 存在性、config jsonschema、DAG 结构、edge 归属+handle、`nodes.*` 变量静态可解析性）收敛为单一事实源，返回 `{errors, warnings}`。
- `ValidationIssue` dataclass：`reason/severity/field_path/node_id/edge_id/message`，message 只含拓扑/键名/reason，绝不回显 config 取值（T-20-01）。
- `test_graph_validator.py`：20 例纯函数零 DB 单测，命中类与不误伤类全覆盖，全绿；`tests/workflows` 445 例零回归。

## Task Commits

Each task was committed atomically:

1. **Task 1: DAG.from_node_edge_dicts 内存构图** - `f05cbae31` (feat)
2. **Task 2: WorkflowGraphValidator 纯函数核心（五类规则）** - `da1c99008` (feat)
3. **Task 3: test_graph_validator.py 全规则 + 不误伤单测** - `f2a77bc75` (test)

_注：Task 2 标记 tdd="true"，但本仓库 `tdd_mode: false` 且 MVP+TDD 门未启用；实现与测试按计划拆为 Task 2/Task 3 两个独立任务交付，故未走单任务内 RED→GREEN 双提交。_

## Files Created/Modified
- `server/workflows/engine/dag.py` - 新增 `from_node_edge_dicts()` classmethod（内存构图，复用回退边语义）
- `server/workflows/validation/graph_validator.py` - `WorkflowGraphValidator` + `ValidationIssue`，五类规则纯函数核心
- `server/workflows/validation/__init__.py` - barrel 导出 `WorkflowGraphValidator` / `ValidationIssue`
- `server/tests/workflows/test_graph_validator.py` - VAL-01 全规则 + Pitfall 1/2/8 不误伤 + T-20-01 信息泄露单测

## Decisions Made
- **变量字段层并集口径（A2）：** 取上游节点所有输出端口 `NodePort.schema` 非空者的 `properties` 并集做字段校验；并集为空（全 None，如 `http_request`）则只校验节点存在性、字段层跳过。
- **孤立节点 severity（Pitfall 8 / D-05）：** `orphan_node` 归为 warning（不阻断），`cycle`/`no_entry` 归为 error。
- **handle 校验白名单（Pitfall 1）：** `source_handle`/`target_handle` 为 `"default"`（或空串）恒合法跳过；非 default source 校验 ∈ `outputs`（含 `get_dynamic_outputs`），非 default target 校验 ∈ `inputs`。
- **DAG handle 归一化：** `from_node_edge_dicts` 将 `source_handle` 缺省/空串归一到 `"default"`，使 a→b→a 普通环被正确判定为循环（与 `from_workflow` 保留原始 handle 的差异点，更贴合"普通环即循环"的校验语义）。

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- CLI 验证命令 `python -c "from workflows.engine.dag import DAG; ..."` 因 `workflows.engine.__init__` 间接导入 scheduler→models 触发 Django app 加载，需 `DJANGO_SETTINGS_MODULE=friday.settings` + `django.setup()` 后执行（pytest 自动配置，仅手工 CLI 验证需补环境变量）。不影响 validator 本身的零 ORM 纯函数性质。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Wave 0 校验核心就绪：`WorkflowGraphValidator` 可被 20-02 写入路径（bulk-update / 单节点·边 CRUD / import / template loader / dry-run）与 20-03 前端接线直接调用。
- 注意 Pitfall 6（bulk-update short_id 收敛时机）与 Pitfall 4（code_review_pipeline 结构性契约重构、OQ#1 终态语义）属后续计划范围，本计划未触及。

## Self-Check: PASSED

- 创建文件全部存在：`graph_validator.py` / `validation/__init__.py` / `dag.py`（已改） / `test_graph_validator.py` / `20-01-SUMMARY.md`。
- 任务提交全部存在：`f05cbae31` / `da1c99008` / `f2a77bc75`（`git rev-parse` 校验通过）。
- 验证：`test_graph_validator.py` 20 例全绿；`tests/workflows` 445 例零回归；ruff check/format 通过；守护 grep（无 ORM / 无 list_types / 复用 _TEMPLATE_VAR_RE / test 无 django_db）全部满足。

---
*Phase: 20-validation*
*Completed: 2026-06-13*
