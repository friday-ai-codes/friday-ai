---
phase: 17-varref
fixed_at: 2026-06-12T18:00:00Z
review_path: .planning/phases/17-varref/17-REVIEW.md
iteration: 1
findings_in_scope: 7
fixed: 7
skipped: 0
status: all_fixed
---

# Phase 17: Code Review Fix Report（变量引用链路修复）

**Fixed at:** 2026-06-12T18:00:00Z
**Source review:** .planning/phases/17-varref/17-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 7（1 Critical + 2 Warning + 4 Info）
- Fixed: 7
- Skipped: 0

## Fixed Issues

### CR-01: 非法客户端 short_id 进入重写映射，会静默篡改指向其他合法节点的引用

**Files modified:** `server/workflows/api/views.py`, `server/tests/workflows/test_bulk_update_short_id.py`
**Commit:** 7b5e0bba
**Applied fix:** `_resolve_short_ids` 重写候选纳入逻辑改为：仅 `client_valid` 时以客户端值为旧标识符；否则当 update 节点最终值脱离 DB 旧值时以 `db_value` 为旧标识符（覆盖重命名与非法值重生成两类场景）。新增 3 条回归测试：非法值（含 `.`）不得改写指向合法节点的文本匹配引用；update 节点送非法值重生成后旧 DB short_id 引用被重写；合法重命名后旧值引用同步重写。

### WR-01: `{{global.*}}` 解析源从 DB 持久字段切换为 context 内存镜像，恢复执行场景存在回归

**Files modified:** `server/workflows/nodes/base.py`, `server/tests/workflows/test_template_resolver.py`
**Commit:** 72f9e5a7
**Applied fix:** `_get_global_values` 先读 `WorkflowExecution.global_params` 模型字段兜底，再以 context 镜像覆盖（同进程内最新值优先）。新增 2 条测试：模型字段有值 + 镜像为空（resume 场景）仍可解析；镜像有最新值时覆盖模型字段。

### WR-02: VariablePicker 的 UUID/short_id 双键去重依赖对象引用相等，跨 JSON 边界必然失效

**Files modified:** `web/src/components/workflow/VariablePicker.vue`
**Commit:** f51767bd
**Applied fix:** 去重改为按 `JSON.stringify` 序列化内容判等。选择修复而非删除该分支（commit message 已记录决策理由）：保留运行时变量展示能力，待后端 snapshot 真正输出 node_outputs 时即可正确去重——双键序列化自服务端同一对象，键序一致，stringify 稳定。

### IN-01: on_error=retry 会对确定性的 TemplateResolutionError 照常重试

**Files modified:** `server/workflows/engine/scheduler.py`
**Commit:** 27b39ff0
**Applied fix:** 引入 `_deterministic_error` 标志位（except 块的 as 变量在块外不可用，不能直接 isinstance），TemplateResolutionError 置 True，重试判定短路直接转最终失败。

### IN-02: `_SHORT_ID_RE` 白名单（1-12 位）比生成器约束（3-12 位）更宽

**Files modified:** `server/workflows/api/views.py`, `server/tests/workflows/test_bulk_update_short_id.py`
**Commit:** 4990455b
**Applied fix:** 白名单收紧为 `^[A-Za-z][A-Za-z0-9]{2,11}$`，与 `generate_unique_short_id` 及测试 `GENERATED_SHORT_ID_RE` 对齐；非法值参数化用例补充 `"a"`、`"ab"`。

### IN-03: bulk-update payload 的 nodes 列表元素未做类型防御，畸形 payload 报 500 而非 400

**Files modified:** `server/workflows/api/views.py`, `server/tests/workflows/test_bulk_update_short_id.py`
**Commit:** 28b8a8e6
**Applied fix:** `_resolve_short_ids` 入口校验 `nodes_data` 为 list 且元素均为 dict，否则抛 DRF `ValidationError`（400）。新增 2 条测试覆盖元素非 dict 与 nodes 非 list。

### IN-04: 引用重写正则不覆盖"标识符后直接跟 `[`"的 JSONPath 形式

**Files modified:** `server/workflows/templates/loader.py`, `server/tests/workflows/test_template_loader.py`
**Commit:** a6739626
**Applied fix:** 尾断言由 `(\.)` 放宽为 `([.\[])`，替换中回填捕获组。新增测试覆盖 `{{$nodes.xY9[0].v}}` / `{{nodes.xY9[2]}}` / `{{$.nodes.xY9[*].name}}` 及前缀部分匹配（`xY9z`）不受影响。

## Verification

- 后端：`cd server && uv run pytest tests/workflows/ -q` → **368 passed**
- 前端：`cd web && pnpm vitest run src/utils/__tests__` → **17 passed**（VariablePicker 无既有测试文件，改动经 lint 与 util 套件验证）
- 修改文件均通过 lint，无新增告警

---

_Fixed: 2026-06-12T18:00:00Z_
_Fixer: gsd-code-fixer_
_Iteration: 1_
