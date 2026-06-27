---
phase: 93
slug: capability-slot-editor
nyquist_compliant: true
test_stack: vitest + @vue/test-utils + happy-dom
created: 2026-06-27
---

# Phase 93 — Nyquist Validation Map（插槽编辑器·前端）

每个 plan 的 task 至少有一个 `<automated>` 测试入口；前端测试栈 vitest + @vue/test-utils + happy-dom（`web/vitest.config.ts`）；93-00 为后端 plan，测试栈 pytest（`cd server && uv run pytest`）。i18n 守护沿用 Phase 24/91 范式（真实 `zh-CN.json` 作 createI18n messages）。

## Per-task test map

| Plan | Task | 自动化测试 | 覆盖断言 |
|------|------|-----------|---------|
| 93-00 | T1 serializer+API（后端，BLOCKER 修复） | `cd server && uv run pytest tests/workflows/test_node_schema.py -x -q` | NodePortSerializer 补 shape；GET /api/node-types/ 集成断言 ai_plan_research.clarify / clarification_card 回传 shape=clarification_request（非剥离）+ 通用 default 端口 shape="" 零回归 |
| 93-01 | T1 portShapes | `pnpm -C web vitest run portShapes` | 空通配/相等/不等/缺失四态 + NodePort.shape? 类型 |
| 93-01 | T2 validator + i18n | `pnpm -C web vitest run useConnectionValidator` | 契约第 4 条不等拒/空通配放行 + 既有三规则零回归 + 真实 zh-CN.json 锁「形状不兼容」 |
| 93-02 | T1 dragState | `pnpm -C web vitest run useConnectionDragState` | start/end + isCompatibleTarget 兼容/不兼容/空通配 + 单例联动 |
| 93-02 | T2 portSnap | `pnpm -C web vitest run usePortSnap` | 阈值内最近命中 + 不兼容跳过 + zoom 换算 + SNAP_THRESHOLD=5 不动 |
| 93-03 | T1 store attach | `pnpm -C web vitest run useWorkflowsStore.attach` | attach/detach + removeNode 级联删子 + metadata 往返 + 普通节点零回归 |
| 93-03 | T2 transform parent | `pnpm -C web vitest run useWorkflowTransform.parent` | parentNode+extent 映射 + **数据契约（WARNING 1）：top-level parentNode 与 data.metadata.parentNodeId 同源并存** + 父先子排序 + autoLayout 排除子节点 + 无父子图零回归 |
| 93-04 | T1 palette+visuals | `pnpm -C web vitest run node-sync` | palette ⊆ fixture（含 clarification_card）+ 幽灵守护 + 视觉非 FALLBACK |
| 93-05 | T1 imCapability | `pnpm -C web vitest run useImCapability` | 有源/无源/非 IM 节点门控判定 |
| 93-05 | T2 BaseWorkflowNode | `pnpm -C web vitest run BaseWorkflowNode` | 方形/圆形 handle + shape 着色 + 拖拽兼容/禁止态 + IM 锁徽标 + 附着徽标（**读 props.data.metadata.parentNodeId，与 93-03 契约同源，WARNING 1**）+ 既有渲染零回归 |
| 93-06 | T1 canvas magnetism | `pnpm -C web vitest run WorkflowCanvas.slot` | connect-start/end 驱动态 + 吸附端点 + 不兼容 Toast 拒 + 既有连线零回归 |
| 93-06 | T2 grouping | `pnpm -C web vitest run WorkflowCanvas.slot` | clarify 附着 attachChild + **编组容器（WARNING 2）：附着后 .slot-attach-group 元素存在 + .slot-attach-connector 渲染，基线无附着图则不存在** + 删父级联确认 + 解除确认 + 子下接发群兼容 |
| 93-06 | T3 human-verify | （人工 checkpoint） | 画布交互观感端到端 |

## Phase gate

- 后端（93-00）：`cd server && uv run pytest tests/workflows/test_node_schema.py -x -q` 全绿（含 GET /api/node-types/ shape 集成断言）；`uv run ruff check` 受改后端文件干净。
- `pnpm -C web vitest run` 全量绿（新增 spec + 既有零回归，尤其 node-sync / BaseWorkflowNode / useAlignmentGuides / ClarificationCard）。
- `pnpm -C web vue-tsc --noEmit` 通过；受改文件 `pnpm -C web eslint` 干净。
- 既有工作流编辑器/连线/单选卡零回归（人工验收 + 既有 vitest 覆盖）。
