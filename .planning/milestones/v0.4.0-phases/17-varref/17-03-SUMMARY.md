---
phase: 17-varref
plan: 03
subsystem: workflow-frontend
tags: [var-ref, short-id, variable-picker, vitest, vue]

# Dependency graph
requires:
  - phase: 17-varref
    plan: 02
    provides: "服务端 bulk-update short_id 落库与重写（前端上送 short_id 是其生效前提）"
provides:
  - "统一引用构造 util web/src/utils/variableRef.ts（buildNodePath/buildNodeRef/buildPrefixPath/buildPrefixRef/isLikelyUuid）"
  - "三入口（picker/SmartInput 共用 useDesignTimeVariables、端口复制 NodePortsDisplay、schema 展示 useNodeSchema）全部经统一 util 生成 short_id 形式引用，UUID 与 slice(0,8) 兜底绝迹"
  - "toBackendNodes 上送 short_id（VAR-01 前端半边，与 17-02 服务端闭环）"
  - "运行时变量选择器 node_outputs UUID/short_id 双键去重"
affects: [17-04, phase-20-validation, phase-21-error-display]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "引用字符串单一构造点：全部生成入口 import variableRef，禁止手写拼接"
    - "shortId 缺失零回退：跳过生成/禁用并 toast，绝不产 UUID 形式引用"

key-files:
  created:
    - web/src/utils/variableRef.ts
    - web/src/utils/__tests__/variableRef.test.ts
  modified:
    - web/src/stores/useWorkflowsStore.ts
    - web/src/composables/useDesignTimeVariables.ts
    - web/src/components/workflow/NodePortsDisplay.vue
    - web/src/components/workflow/node-config/composables/useNodeSchema.ts
    - web/src/components/workflow/VariablePicker.vue

key-decisions:
  - "NodePortsDisplay 单点收口：组件内经 useWorkflowsStore 由 UUID 查权威 shortId，Props 接口与全部使用方零改动（RESEARCH §3 建议，改动面最小）"
  - "shortId 缺失处置分层：useDesignTimeVariables 跳过 nodes.* 生成（input.* 照常）；NodePortsDisplay 点击 toast 报错；useNodeSchema 展示空串——三处均零 UUID 回退"
  - "运行时双键去重以引用相等（===）判定同一 outputs 对象，仅 UUID 键无 short_id 对应时保留展示（存量执行兼容）"

patterns-established:
  - "isLikelyUuid 整串匹配 UUID 形态（不区分大小写），用于运行时双键归类"
  - "VariablePrefix 类型约束非节点前缀为 'input' | 'trigger' | 'global' | 'context' | 'config'"

requirements-completed: [VAR-03, VAR-01]

# Metrics
duration: ~10min
completed: 2026-06-13
---

# Phase 17 Plan 03: 前端引用生成统一收口 Summary

**新建 variableRef 单一构造 util 收口全部引用生成点（三入口 + schema 展示 + picker 前缀字面量），消灭 UUID 与 id.slice(0,8) 兜底；toBackendNodes 上送 short_id 补齐 VAR-01 前端半边；运行时 picker 双键去重。**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-06-12T16:48:00Z
- **Completed:** 2026-06-12T16:58:00Z
- **Tasks:** 3/3
- **Files modified:** 7（新建 2 + 修改 5）

## Accomplishments

- 新建 `web/src/utils/variableRef.ts`：buildNodePath/buildNodeRef/buildPrefixPath/buildPrefixRef 四个纯函数 + isLikelyUuid 辅助判定，JSDoc 明确统一格式契约 `{{nodes.<short_id>.<field.path>}}`、禁止 UUID 形式；17 个 vitest 单测覆盖嵌套 dict 路径、list 数字索引透传与 UUID 判定边界
- VAR-01 前端半边：`toBackendNodes` 上送 `short_id: node.shortId`，17-02 服务端"客户端权威值落库"逻辑自此生效
- 三入口收口（VAR-03）：
  - `useDesignTimeVariables`（picker/SmartInput 共用）：删除 `id.slice(0, 8)` 兜底，shortId 缺失时跳过该节点 nodes.* 变量生成（直接上游的 input.* 照常）；2 处 nodes 拼接改 buildNodePath、2 处 input 拼接改 buildPrefixPath
  - `NodePortsDisplay`（端口复制）：组件内经 store 由 props.nodeId（UUID）查权威 shortId，copyVariablePath 改 buildNodeRef；查不到时 toast「节点缺少 short_id，请先保存工作流」拒绝生成；模板展示同步改 shortId 形式（缺失显示「保存工作流后可用」）；Props 与全部使用方零改动
  - `useNodeSchema`（schema 展示）：getOutputPath 删除 `|| selectedNodeId` UUID 兜底（缺失返回空串），getInputPath 改 buildPrefixRef；directPredecessorOutputs 的 nodeShortId 不再截断 UUID
- VariablePicker 运行时分支：node_outputs UUID/short_id 双键以引用相等判定去重（跳过有 short_id 对应的 UUID 键），仅 UUID 键时保留展示（存量执行兼容）；运行时 trigger/global/input 动态 3 处与预设字面量 8 处全部收口 buildPrefixPath，nodes 路径改 buildNodePath
- 全量校验：vitest 984 个测试全绿、`vue-tsc --noEmit` 通过、受影响 5 文件 eslint 无 error

## Task Commits

Each task was committed atomically:

1. **Task 1: variableRef 统一构造 util + 单测 + toBackendNodes 上送 short_id（TDD）**
   - RED: `1e41887f` (test) — 失败测试先行（模块不存在）
   - GREEN: `e51b7ed3` (feat) — util 实现 + short_id 上送，11 用例全绿
2. **Task 2: 三入口改造——删除 UUID/slice(0,8) 兜底** - `560924e9` (feat)
3. **Task 3: VariablePicker 双键去重 + 前缀收口 + 整体校验** - `dc62fa58` (feat)

## Files Created/Modified

- `web/src/utils/variableRef.ts` - 统一引用构造 util：4 个构造函数 + isLikelyUuid + VariablePrefix 类型；模块 docstring 写明格式契约与收口范围
- `web/src/utils/__tests__/variableRef.test.ts` - 17 个单测：构造函数行为、嵌套路径透传不转义、UUID 判定（整串/大小写/截断/空串）
- `web/src/stores/useWorkflowsStore.ts` - toBackendNodes 增加 short_id 字段（VAR-01 前端半边）
- `web/src/composables/useDesignTimeVariables.ts` - 删兜底 + 缺失跳过 + 4 处拼接收口
- `web/src/components/workflow/NodePortsDisplay.vue` - UUID→shortId store 查表、buildNodeRef 复制、缺失 toast 拒绝、展示同步
- `web/src/components/workflow/node-config/composables/useNodeSchema.ts` - getOutputPath/getInputPath 收口、nodeShortId 去截断
- `web/src/components/workflow/VariablePicker.vue` - 运行时双键去重 + 11 处前缀生成点收口

## Deviations from Plan

### 计划验证标准的范围澄清（非偏差修复）

计划 `<verification>` 中"全仓 grep `rg -n "id\.slice\(0, 8\)" web/src/` 无结果"在字面上不成立：仓内仍有 7 处匹配（`pages/runners/`、`pages/executions/`、`pages/spaces/`、`pages/logs/`、`useToolDisplay.ts`、`ChatMessageBubble.vue`），但它们全部是 runner/执行/空间/工具调用 ID 的**纯展示截断**，与变量引用生成无关（验证标准的意图是"必坏引用生成点绝迹"）。全部引用生成点（useDesignTimeVariables、useNodeSchema、NodePortsDisplay、VariablePicker）已零 slice 残留。按 scope boundary 不改动这些无关文件。

其余执行与计划完全一致。

## Verification

- `cd web && pnpm vitest run src/utils/__tests__/variableRef.test.ts` → 17 passed
- `cd web && pnpm vitest run` → 983 passed | 1 skipped（全量无回归）
- `cd web && npx vue-tsc --noEmit` → 通过（项目无 typecheck script，直接调用）
- `cd web && npx eslint <受影响 5 文件>` → 无 error
- `rg -c "short_id: node.shortId" web/src/stores/useWorkflowsStore.ts` → 1
- `rg -c "slice\(0, 8\)"` useDesignTimeVariables.ts / `rg 'path: \`(trigger|global|input)\.\$'` VariablePicker.vue / `rg 'nodes\.\$\{props\.nodeId\}'` NodePortsDisplay.vue → 均零匹配（兜底与手写拼接绝迹）
- `rg -c "buildPrefixPath" web/src/components/workflow/VariablePicker.vue` → 12

## Known Stubs

None — 无占位/stub，全部逻辑已接线并有测试覆盖。

## Threat Flags

无新增安全面：T-17-20（short_id 伪造）维持 transfer 处置（17-02 服务端白名单已覆盖，前端不重复防御）；T-17-21（运行时值预览）维持 accept，getValuePreview 行为零改动；零新依赖。

## Next Phase Readiness

- VAR-01 前后端闭环完成：保存 payload 含客户端权威 short_id，服务端校验落库 + 引用重写已就绪（17-02）
- 17-04（解析器专项测试/收尾）可直接以"三入口只产 short_id 形式"为前提
- Phase 20（保存校验）可复用 variableRef util 与 isLikelyUuid 做引用格式校验

## Self-Check: PASSED

- FOUND: web/src/utils/variableRef.ts
- FOUND: web/src/utils/__tests__/variableRef.test.ts（86 行 ≥ 40）
- FOUND: .planning/phases/17-varref/17-03-SUMMARY.md
- FOUND: commit 1e41887f / e51b7ed3 / 560924e9 / dc62fa58
