---
phase: 20-validation
plan: 02
subsystem: api
tags: [workflow, validation, dry-run, bulk-update, serializer, dag, security]

# Dependency graph
requires:
  - phase: 20-validation
    provides: WorkflowGraphValidator 纯函数核心 + DAG.from_node_edge_dicts（20-01）
provides:
  - 五写入路径接入 validator（bulk-update / 单节点·边 CRUD / import / dry-run；template loader 由 20-03 接）
  - 非法图写库前结构化 400 + 事务回滚（VAL-02）；合法图保存零变化（不误拒）
  - dry-run 双端点 POST /api/workflows/{id}/validate/（detail=True）与 POST /api/workflows/validate/（detail=False），同源 validator
  - WorkflowNodeCreateSerializer config jsonschema 校验缺口闭合 + NodeRegistry.list_types() 误用修复（Pitfall 7）
  - graph_validator 兼容 {{nodes.<uuid>.*}} 形式引用（修复 UUID 引用误判 node_not_found）
affects: [20-03 前端 dry-run/IssuesPanel 接线]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "写库前统一校验：transaction.atomic 内、short_id 收敛/引用重写之后、commit 之前调 WorkflowGraphValidator（Pitfall 6）"
    - "config 校验单一事实源：bulk 路径 serializer 传 skip_config_validation context，校验交由 graph validator 产出结构化 {errors}"
    - "dry-run 双形态同源：detail=True 取草图或 DB 现状、detail=False 仅校请求体，均不写库（Pitfall 5）"

key-files:
  created: []
  modified:
    - server/workflows/api/serializers.py
    - server/workflows/api/views.py
    - server/workflows/validation/graph_validator.py
    - server/tests/workflows/test_api.py

key-decisions:
  - "bulk-update 的 config 校验改由 WorkflowGraphValidator 统一产出 {errors:[{reason:config_schema_invalid,...}]}，per-node serializer 传 skip_config_validation context 让位（单节点 node_detail/create 路径校验不变）"
  - "单边 CRUD 用整图 validator 过滤 edge 相关 reason（edge_node_missing/invalid_source_handle/invalid_target_handle），不引入第二套 handle 校验逻辑"
  - "graph_validator 变量校验兼容 short_id 与 UUID 双空间，避免 {{nodes.<uuid>.*}} 误判（合法不误拒）"

requirements-completed: [VAL-01, VAL-02]

# Metrics
duration: ~20min
completed: 2026-06-13
---

# Phase 20 Plan 02: 写入路径接入 WorkflowGraphValidator + dry-run 双端点 Summary

**把 20-01 的 `WorkflowGraphValidator` 接入 bulk-update / 单节点·边 CRUD / import / dry-run 全部后端写入路径：非法图在写库前被结构化 400 + 事务回滚（VAL-02），合法图保存零变化；新增 dry-run 双端点与真实保存同源；顺手闭合 `WorkflowNodeCreateSerializer` 的 config jsonschema 缺口与 `NodeRegistry.list_types()` 误用（Pitfall 7），并修复 validator 对 `{{nodes.<uuid>.*}}` 引用的误判。**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-06-13T11:32:08Z
- **Completed:** 2026-06-13T11:51:14Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- **serializers.py（Task 1）**：`WorkflowNodeCreateSerializer` 增 `validate()`，复用 `BaseNode.validate_config` 闭合 create 路径 config jsonschema 缺口；两处 `NodeRegistry.list_types()` 误用改为 `get_all().keys()`（未知 node_type 走 400 而非 500，T-20-07）。
- **views.py（Task 2）**：
  - bulk-update 在 `_bulk_update_nodes_and_edges` 内、`_resolve_short_ids` + 引用重写之后、commit 之前用**最终落库状态**调 `WorkflowGraphValidator`（节点 dict 同带 UUID id 与最终 short_id），error 非空 → `raise ValidationError({"errors", "warnings"})` → atomic 回滚 → DRF 400（Pitfall 6）。
  - import_workflow 在 `afrom_json` 前用解析出的 nodes/edges 调同一 validator，非法 → 400 不入库。
  - 单边 POST/PUT/PATCH 补 handle 子集校验（`_check_edge_handles` 复用整图 validator，仅取 edge 相关 reason）。
  - 新增 dry-run 双端点：`validate`（detail=True，取草图或 DB 现状）+ `validate_draft`（detail=False，仅校请求体），均返回 200 `{errors,warnings}` 不写库（D-04 / Pitfall 5）。
- **graph_validator.py（Task 3 修复）**：变量校验兼容 short_id 与 UUID 双空间，修复对 `{{nodes.<uuid>.*}}` 的 node_not_found 误判（合法不误拒）。
- **test_api.py（Task 3）**：`TestWorkflowValidationAPI` 8 例集成测试覆盖 400 路径（坏 config/坏 handle/不可解析变量）+ 事务回滚 + 合法不误拒 + 单节点 create 缺口 + dry-run 双端点 + dry-run 与 bulk-update 同源。

## Task Commits

1. **Task 1: serializers config 缺口 + list_types 修复** - `028287e63` (fix)
2. **Task 2: 写入路径接入 validator + dry-run 双端点** - `b1025aad5` (feat)
3. **Task 2/3 接入收尾: bulk config 校验让位 validator + UUID 引用修复** - `9c637a05f` (fix)
4. **Task 3: VAL-02 写入路径集成测试** - `b79d711be` (test)

## Files Created/Modified
- `server/workflows/api/serializers.py` - Create 路径 config 校验 + `skip_config_validation` context（bulk 让位）+ `list_types` 修复
- `server/workflows/api/views.py` - 写入路径接入 validator（bulk/import/单边）+ dry-run 双端点 + 3 个 helper（`_node_to_validator_dict`/`_edge_to_validator_dict`/`_check_edge_handles`）
- `server/workflows/validation/graph_validator.py` - 变量校验兼容 UUID 形式节点引用
- `server/tests/workflows/test_api.py` - `TestWorkflowValidationAPI` 8 例 VAL-02 集成测试

## Decisions Made
- **bulk-update config 校验单一事实源（偏离细节，见下）：** per-node serializer 在 bulk 路径传 `skip_config_validation` context，把 config jsonschema 校验让给 `WorkflowGraphValidator`，使坏 config 产出结构化 `{errors:[{reason:config_schema_invalid, node_id, field_path}]}`（满足 must-have 错误形态），而非 serializer 的 `{"config":[...]}`。单节点 `node_detail` create/update 路径不传该 context，行为零变化。
- **单边 handle 校验复用整图 validator：** `_check_edge_handles` 调 `WorkflowGraphValidator().validate(两端节点, [该边])` 并仅保留 `edge_node_missing`/`invalid_source_handle`/`invalid_target_handle`，避免单边路径误报环/入口/孤立，也不重写第二套 handle 逻辑（Pitfall 1 default 恒合法白名单天然继承）。
- **dry-run 入参形态：** detail=True 二者皆缺省时取 DB 现状（走 WorkflowPermission + 作用域过滤，T-20-05），detail=False 仅校请求体不读库（无越权面）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - 缺失关键功能] bulk-update config 校验让位机制（serializer skip_config_validation context）**
- **Found during:** Task 2/Task 3
- **Issue:** per-node serializer（含 Task 1 新增的 Create.validate 与既有 WorkflowNodeSerializer.validate）会在 graph validator 之前以 `{"config":[...]}` 形态拦截坏 config，导致 bulk-update 无法产出 must-have 要求的 `{errors:[{reason:config_schema_invalid,...}]}` 结构。
- **Fix:** 给两个 serializer 的 `validate()` 增 `skip_config_validation` context 分支；bulk-update 创建/更新节点时传该 context，config 校验统一由 graph validator 承担。单节点路径不传 → 校验照常（Task 1 缺口闭合不受影响）。
- **Files modified:** server/workflows/api/serializers.py, server/workflows/api/views.py
- **Commit:** 9c637a05f

**2. [Rule 1 - Bug] graph_validator 对 `{{nodes.<uuid>.*}}` 引用误判 node_not_found**
- **Found during:** Task 3（既有 `test_bulk_update_short_id.py::test_invariant_save_implies_resolvable` 回归）
- **Issue:** 20-01 validator 变量校验仅在 short_id 空间查找，`{{nodes.<uuid>.field}}` 形式引用（运行态与 bulk-update 引用重写均支持）被误判为 `node_not_found`，违反"合法不误拒"。
- **Fix:** `_validate_variables` 同时构建 short_id 与 UUID 两套查找表，命中任一即视为存在。
- **Files modified:** server/workflows/validation/graph_validator.py
- **Commit:** 9c637a05f

## Threat Surface
本计划为输入校验强化，与 STRIDE 注册表对齐：
- T-20-04（非法图绕过校验落库）：bulk-update/import/单边 写库前/事务内调同一 validator，error→400+回滚 ✅
- T-20-05（dry-run detail=True 越权）：复用 WorkflowPermission + 作用域过滤（aget_object）；detail=False 不读库 ✅
- T-20-06（400 体回显上游值）：仅透传 ValidationIssue 键名/路径/reason，不含 config 值（测试断言结构化字段）✅
- T-20-07（未知 node_type 500）：list_types 修复，未知类型走 400 结构化分支 ✅

## Verification
- `cd server && uv run pytest tests/workflows/test_api.py -k "bulk or validate or node" -x -q` → 18 passed。
- `cd server && uv run pytest tests/workflows -q` → 453 passed（零回归）。
- grep 守护：views.py 接入 `WorkflowGraphValidator`（bulk/import/单边/dry-run）、`grep -c 'url_path="validate"'` == 2、serializers.py `list_types` == 0。
- `ruff check` 全部改动文件通过；`server/uv.lock` 无无关 diff（uv 重排已 `git checkout` 还原）。

## State Sync Note
按本次执行约束（sequential / 不改阶段级字段），未运行 STATE.md / ROADMAP.md 的 advance-plan / update-progress 等状态写入；仅交付代码、测试与本 SUMMARY。

## Self-Check: PASSED

- 创建/修改文件全部存在：serializers.py / views.py / graph_validator.py / test_api.py / 20-02-SUMMARY.md。
- 任务提交全部存在：028287e63 / b1025aad5 / 9c637a05f / b79d711be。
- 验证：写入路径集成测试 18 例绿；tests/workflows 453 例零回归；grep 守护满足；ruff 通过。

---
*Phase: 20-validation*
*Completed: 2026-06-13*
