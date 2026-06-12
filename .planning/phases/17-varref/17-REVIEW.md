---
phase: 17-varref
reviewed: 2026-06-12T17:45:52Z
depth: standard
files_reviewed: 18
files_reviewed_list:
  - server/workflows/engine/template_resolver.py
  - server/workflows/nodes/base.py
  - server/workflows/engine/scheduler.py
  - server/workflows/templates/loader.py
  - server/workflows/api/views.py
  - server/workflows/nodes/ai/code_review.py
  - server/workflows/nodes/ai/plan_generation.py
  - server/tests/workflows/test_template_resolver.py
  - server/tests/workflows/test_bulk_update_short_id.py
  - server/tests/workflows/test_error_handling.py
  - server/tests/workflows/test_template_loader.py
  - web/src/utils/variableRef.ts
  - web/src/utils/__tests__/variableRef.test.ts
  - web/src/components/workflow/VariablePicker.vue
  - web/src/components/workflow/NodePortsDisplay.vue
  - web/src/components/workflow/node-config/composables/useNodeSchema.ts
  - web/src/composables/useDesignTimeVariables.ts
  - web/src/stores/useWorkflowsStore.ts
findings:
  critical: 1
  warning: 2
  info: 4
  total: 7
findings_status:
  CR-01: fixed  # 7b5e0bba
  WR-01: fixed  # 72f9e5a7
  WR-02: fixed  # f51767bd
  IN-01: fixed  # 27b39ff0
  IN-02: fixed  # 4990455b
  IN-03: fixed  # 28b8a8e6
  IN-04: fixed  # a6739626
status: issues_fixed
fixed_at: 2026-06-12T18:00:00Z
---

# Phase 17: Code Review Report（变量引用链路修复）

**Reviewed:** 2026-06-12T17:45:52Z
**Depth:** standard
**Files Reviewed:** 18
**Status:** issues_fixed（全部 7 项已修复，见 frontmatter findings_status 与各 fix(17) 提交）

## Summary

评审范围为 Phase 17 全部四个 plan 的已提交变更（commit `a015dc8c..6cf49744`，排除工作区中无关的未提交改动）。整体实现质量较高：resolver 核心为纯函数、错误分类完整、available 候选不泄露上游输出值（T-17-01 落实）、重写正则对 id_map 键做了 `re.escape`（T-17-10）、重写范围严格限定本 workflow（T-17-11），后端 105 个相关测试与前端 17 个 variableRef 测试全部通过。

但发现 1 个已实测复现的 Critical 问题（非法 short_id 污染引用重写映射，会静默篡改指向其他合法节点的引用）和 2 个 Warning（`{{global.*}}` 在"参数仅持久化到模型字段、context 镜像丢失"场景下的语义回归，已实测复现；VariablePicker 运行时双键去重依赖跨 JSON 边界不可能成立的引用相等）。

注：review 任务说明中提到的 `web/src/components/workflow/smart-input/*` 在 Phase 17 提交范围内实际无改动（SmartInput 的引用生成经 `useDesignTimeVariables` 统一收口），不构成遗漏。

## Critical Issues

### CR-01: 非法客户端 short_id 进入重写映射，会静默篡改指向其他合法节点的引用

**File:** `server/workflows/api/views.py:207-208`（`_resolve_short_ids` 尾部）
**Issue:** `rewrite_candidates` 的纳入条件只检查 `client_value` 非空且 `final != client_value`，**不要求 `client_valid`**。当客户端为某节点传入非法 short_id（如 `"a.b"`，含点号；白名单校验只决定是否采纳，不决定是否进入重写映射）时，该值被重生成为新值（如 `Qx7`），同时 `{"a.b": "Qx7"}` 进入 id_map。`rewrite_template_refs` 对 id_map 键做 `re.escape` 后整体匹配，`{{nodes.a.b.c}}`——本是对合法节点 `a` 的字段 `b.c` 的引用——会被命中并改写。已实测验证：

```python
rewrite_template_refs({'prompt': '{{nodes.a.b.c}}'}, {'a.b': 'Qx7'})
# => {'prompt': '{{nodes.Qx7.c}}'}   # 对节点 a 的引用被静默破坏
```

`final_owned` 防卫过滤无法拦截（`"a.b"` 不可能是任何节点的 short_id）。后果：同事务内其他节点 config 被静默改写为指向不存在的标识符，且严格语义下（VAR-02）下一次执行直接 fail-fast——属于数据破坏。`_SHORT_ID_RE` 允许 1 位 ID（见 IN-02），单字母节点 ID 合法存在，触发面并非纯理论。

相关联的次级缺陷：当 update 节点的客户端值非法（或为空串 `""`）而其 DB 现值被重生成替换时，对该节点**旧 DB short_id** 的存量引用不会被重写（rewrite_candidates 以 client_value 为 key，而真正的旧身份是 db_value），产生悬挂引用，违反函数 docstring 宣称的不变式"保存成功 ⇒ config 中全部 nodes.* 引用都属于该工作流的 short_id 或 UUID 集合"。

测试 `TestInvalidFormatRegeneration` 只断言了"非法值被重生成"，未断言"非法值不触发重写/旧 DB 值的引用得到处理"，故未暴露。

**Fix:**

```python
# _resolve_short_ids 循环内，替换现有 rewrite_candidates 纳入逻辑：
if client_valid and final != client_value:
    # 客户端提供了合法值但被冲突重生成 → 候选重写 client_value
    rewrite_candidates[client_value] = final
elif db_value is not None and final != db_value:
    # update 节点的最终值脱离了 DB 旧值（非法值/空串被重生成等）
    # → 旧身份是 db_value，存量引用应重写到新值
    rewrite_candidates[db_value] = final
```

并在 `test_bulk_update_short_id.py` 补两条用例：(1) 非法值（含 `.`）不得改写恰好文本匹配的他节点引用；(2) update 节点送非法值导致重生成后，对其旧 DB short_id 的引用被重写。

## Warnings

### WR-01: `{{global.*}}` 解析源从 DB 持久字段切换为 context 内存镜像，恢复执行场景存在回归

**File:** `server/workflows/nodes/base.py:500-512`（`_get_global_values`，由 `_build_resolution_sources` 传入 resolver）
**Issue:** Phase 17 之前，`render_template` 的 `global.` 分支经 `get_global_variable_value` → `get_global_param`，后者在有 `workflow_execution` 时直接读模型字段 `WorkflowExecution.global_params`（`set_global_param` 持久化的目标）。重构后统一走 `_get_global_values()`，global params 只读 `workflow_context.get("global_params", {})` 内存镜像——而 `set_global_param`/`aset_global_param` 只持久化模型字段，**从不持久化 context**。一旦 execution 从 DB 重新加载（`resume_execution`、`approve_node`、等待事件续跑等 API 路径都会 `aget` 新对象），镜像为空，渲染回空串。已实测验证：

```python
we = WorkflowExecution(global_params={'x': 'persisted-value'}, context={})
ctx = ExecutionContext(..., workflow_context=we.context, workflow_execution=we)
ctx.render_template('val={{global.x}}')   # 'val='（新）；旧路径返回 'persisted-value'
```

当前仓库内所有节点都经 `set_global_variable`（其模型方法整存 context，顺带持久化了 `global_variables`），因此现有测试未暴露；但 `ExecutionContext.set_global_param` / `update_global_params` 是面向节点作者的公开 API，且 Phase 17 契约明确"`global.` 前缀字段缺失**维持现状**"——此处语义实际收窄了。
**Fix:** `_get_global_values` 的 params 来源补回模型字段兜底：

```python
def _get_global_values(self) -> dict:
    result = {}
    if self.workflow_execution is not None:
        result.update(self.workflow_execution.global_params or {})
    result.update(self.workflow_context.get("global_params", {}))
    for key, var in self.get_all_global_variables().items():
        ...
```

并补一条"模型字段有值 + context 镜像为空 → `{{global.x}}` 仍可解析"的回归测试。

### WR-02: VariablePicker 的 UUID/short_id 双键去重依赖对象引用相等，跨 JSON 边界必然失效

**File:** `web/src/components/workflow/VariablePicker.vue:164-172`
**Issue:** 去重逻辑 `nonUuidOutputs.has(outputs)` 基于 `Set` 的引用相等，注释断言"scheduler 对同一节点输出以 UUID 与 short_id 双键写入同一对象（引用相等）"。该不变式只在服务端 Python 进程内存中成立；`context` prop 的数据形态来自 `ExecutionContextSerializer`（`get_context_snapshot()` → JSON 响应），`JSON.parse` 后 UUID 键与 short_id 键必然指向两个不同对象，去重静默失效、字段重复展示。另外两点加重了这段代码的死代码嫌疑：(1) 仓库内所有 `<VariablePicker>` 使用点均未传 `context` prop；(2) 服务端 `get_context_snapshot` 读取 `self.context.get("node_outputs", {})`，但全仓库没有任何代码向 `execution.context["node_outputs"]` 写入——运行时分支当前拿到的恒为空 dict。
**Fix:** 改为按键名去重，不依赖引用：对每个 UUID 键，若存在任一非 UUID 键的输出与之深相等（或由后端在 snapshot 中直接只输出 short_id 键），则跳过。最小修改：

```ts
const nonUuidKeys = entries.filter(([k]) => !isLikelyUuid(k))
entries.forEach(([nodeKey, outputs]) => {
  if (isLikelyUuid(nodeKey)
    && nonUuidKeys.some(([, o]) => JSON.stringify(o) === JSON.stringify(outputs)))
    return
  ...
})
```

更彻底的方案是在后端 `get_context_snapshot` 输出 node_outputs 时只保留 short_id 键（无对应 short_id 才保留 UUID 键），前端无需去重。

## Info

### IN-01: on_error=retry 会对确定性的 TemplateResolutionError 照常重试

**File:** `server/workflows/engine/scheduler.py:1014-1031, 1046-1069`
**Issue:** 模板解析失败是配置错误，重试结果必然相同，但 retry 策略下仍会按指数退避重试（单次延迟最长 300s），延迟失败上报。属存量行为（旧 `ValueError` 同样被重试），Phase 17 的严格语义使其更易触发。
**Fix:** 在重试判定处对 `TemplateResolutionError` 短路：`if attempt < max_attempts and on_error == "retry" and not isinstance(_exc, TemplateResolutionError)`。

### IN-02: `_SHORT_ID_RE` 白名单（1-12 位）比生成器约束（3-12 位）更宽，与注释自述不符

**File:** `server/workflows/api/views.py:84-86`
**Issue:** 注释称"与 common/short_id.py 生成约束一致"，但 `generate_unique_short_id` 最短 3 位，而白名单 `{0,11}` 接受 1-2 位客户端值。单字符节点 ID（如 `a`）合法落库后，会放大 CR-01 的引用误改面，也更易与字段路径片段产生文本歧义。
**Fix:** 收紧为 `^[A-Za-z][A-Za-z0-9]{2,11}$`，与生成器及测试中 `GENERATED_SHORT_ID_RE` 对齐。

### IN-03: bulk-update payload 的 nodes 列表元素未做类型防御，畸形 payload 报 500 而非 400

**File:** `server/workflows/api/views.py:178-196`
**Issue:** `_resolve_short_ids` 直接对列表元素调用 `nd.get(...)`，若元素不是 dict（如字符串），抛 `AttributeError` → 500。属系统边界输入校验缺失（存量模式，本次新增代码成为首个触点）。
**Fix:** 入口处校验 `nodes_data` 元素均为 dict，否则抛 DRF `ValidationError`（400）。

### IN-04: 引用重写正则不覆盖"标识符后直接跟 `[`"的 JSONPath 形式

**File:** `server/workflows/templates/loader.py:81-83`
**Issue:** pattern 要求标识符后必须是 `\.`，`{{$nodes.xY9[0].v}}` / `{{nodes.xY9[0]}}` 这类"ident 后直接下标"的引用在 short_id 重生成时不会被重写，留下悬挂引用。此形态在现有模板与测试中未出现，影响面极小，仅作记录。
**Fix:** 将尾断言放宽为 `([.\[])` 并在替换中回填捕获组。

---

## 评审过的关键正面结论（供后续阶段参考）

- **resolver 错误分类正确**：`node_not_found` / `field_not_found`（含嵌套断路点 `traversed`）/ `unknown_prefix` / `missing_field_path` 四类语义与定界文档一致；`available` 候选只含键名，未泄露上游输出值。
- **legacy 宽松语义保持**：`input./trigger.` 嵌套下钻缺失返回 None→空串，`context./config./global.` 扁平 key 查找（WR-01 的 params 来源切换除外），`$` 家族（`{{$.key}}`、`{{$}}`、含 `[` 的 JSONPath、`{{$nodes...}}` 无 `[` 保留字面量）逐一与旧实现核对无回归。
- **scheduler 结构化 error_message**：最后一行可 `json.loads`，四键齐全（`reference/reason/available/template`），有集成测试锁定。
- **前端引用生成统一**：四个生成入口（VariablePicker / NodePortsDisplay / useDesignTimeVariables / useNodeSchema）均改走 `variableRef` util，UUID 前 8 位截断回退已全部移除，shortId 缺失时按锁定决策跳过/提示而非回退。
- **测试**：后端 105 个相关用例、前端 17 个 util 用例全部通过。

---

_Reviewed: 2026-06-12T17:45:52Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
