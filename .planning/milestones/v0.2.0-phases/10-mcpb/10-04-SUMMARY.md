---
phase: 10-mcpb
plan: 04
subsystem: frontend
tags: [vue, pinia, tool-binding, access-token, profile, no-plaintext, green]

# Dependency graph
requires:
  - phase: 10-mcpb
    plan: 01
    provides: 前端 RED spec ToolBindingSettings.spec.ts（绑定 UI 行为锁名）
  - phase: 10-mcpb
    plan: 03
    provides: /api/tools/bindings/ + /api/tools/bindable/ 端点（运行期消费；本 plan 仅前端，端点未落地不阻塞编译/单测）
provides:
  - toolBindings types/api/store（list/bindable/upsert/unbind，元数据-only）
  - ToolBindingSettings/Table/Dialog 三组件（mirror accessTokens 范式）
  - profile.vue「工具令牌绑定」卡片
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "镜像 accessTokens 设置区范式：types↔serializer 一一对应 + setup-store 元数据-only 缓存 + Settings/Table/Dialog 三件套"
    - "下拉仅列 is_valid===true 令牌（Pitfall 5）：computed filter，杜绝绑到吊销/过期令牌"
    - "无明文姿态：BoundTokenDto 仅 name/prefix/suffix/is_valid；浏览器 client 零 /tools/execute 引用"

key-files:
  created:
    - web/src/types/toolBinding.ts
    - web/src/api/toolBindings.ts
    - web/src/stores/toolBindings.ts
    - web/src/components/toolBindings/ToolBindingTable.vue
    - web/src/components/toolBindings/ToolBindDialog.vue
    - web/src/components/toolBindings/ToolBindingSettings.vue
  modified:
    - web/src/pages/profile.vue

key-decisions:
  - "[10-04] upsertBinding 就地按 remote_tool 替换（unique(user, remote_tool) 语义），无重复行；命中则替换否则前插"
  - "[10-04] ToolBindDialog 始终挂载于 Settings（受控 open），令牌下拉随 accessTokens store 渲染，满足 spec findComponent + 文本断言"
  - "[10-04] api 注释去除字面 /tools/execute/，浏览器 client grep 零执行端点引用（T-10 边界）"

requirements-completed: [MCPB-01, MCPB-03]

# Metrics
duration: 6min
completed: 2026-06-10
---

# Phase 10 Plan 04: 前端工具令牌绑定管理 UI Summary

**镜像 access tokens 设置区范式落地 toolBindings types/api/store + Settings/Table/Dialog 三组件 + profile 绑定卡片：用户可列出可绑定 mcp/skill 工具及当前绑定令牌、从有效令牌下拉绑定/换绑、二次确认解绑；明文零进 store/渲染，10-01 前端 RED spec 全 5 条转 GREEN，typecheck 清白**

## Performance

- **Duration:** ~6 min
- **Completed:** 2026-06-10
- **Tasks:** 3
- **Files modified:** 7（6 新建 + 1 改）

## Accomplishments

- `types/toolBinding.ts`：`BoundTokenDto`（name/prefix/suffix/is_valid，与后端 BoundTokenSerializer 白名单一一对应，零明文/hash）+ `ToolBindingDto` + `BindableToolDto` + `ToolBindingUpsertPayload`。
- `api/toolBindings.ts`：`list`/`bindable`/`upsert`/`unbind` 走 `/tools/bindings/`、`/tools/bindable/`、`/tools/bindings/${id}/`（末尾 /，复用 client get/post/del + extractList 兼容分页）；**零 `/tools/execute` 引用**。
- `stores/toolBindings.ts`：`useToolBindingStore`（setup 风格，mirror accessTokens）暴露 `bindings`/`bindableTools`/`loading`/`lastError` + `fetchBindings`/`fetchBindable`/`upsertBinding`/`unbindBinding`；upsert 就地按 remote_tool 替换，unbind 移除；错误统一 re-throw；仅缓存元数据。
- `ToolBindingTable.vue`：按工具渲染（名/描述 + 来源标签 + 当前绑定令牌 name+prefix…suffix 指纹或「未绑定」），emit `bind`(tool) / `unbind`(binding)。
- `ToolBindDialog.vue`：从 `useAccessTokenStore` 读令牌，**仅列 is_valid===true**（computed filter）；Select 选项展示 name+指纹；确认 emit `submit`({remote_tool, access_token})。
- `ToolBindingSettings.vue`：onMounted 并行 `fetchBindable`+`fetchBindings`+`fetchTokens`；渲染 Table；`bind` 开 Dialog，`submit`→`upsertBinding`+toast，`unbind`→AlertDialog 二次确认→`unbindBinding`；错误经 useErrorHandler。
- `profile.vue`：Access Tokens 卡片下方新增同款「工具令牌绑定」卡片（lucide--link 图标 + 副标题），body 渲染 `<ToolBindingSettings />`，既有卡片零改动。

## Task Commits

1. **Task 1: types + api + store** — `71dc131f` (feat)
2. **Task 2: ToolBindingTable + ToolBindDialog + ToolBindingSettings** — `9ffbef86` (feat)
3. **Task 3a: api 注释去字面 execute 路径** — `9a8baa50` (chore)
4. **Task 3b: profile.vue 绑定卡片** — `f24a3dbd` (feat)

## Files Created/Modified

- `web/src/types/toolBinding.ts` — 绑定相关 DTO（零明文字段）。
- `web/src/api/toolBindings.ts` — 绑定 CRUD API 客户端（/tools/bindings/ + /tools/bindable/）。
- `web/src/stores/toolBindings.ts` — useToolBindingStore（元数据-only）。
- `web/src/components/toolBindings/ToolBindingTable.vue` — 工具+当前绑定令牌指纹列表。
- `web/src/components/toolBindings/ToolBindDialog.vue` — 仅有效令牌下拉的绑定对话框。
- `web/src/components/toolBindings/ToolBindingSettings.vue` — 绑定管理区容器（mirror AccessTokenSettings）。
- `web/src/pages/profile.vue` — 新增 import + 「工具令牌绑定」卡片。

## Verification Results

- `pnpm vitest run src/components/toolBindings` → **5 passed**（lists_bindable_mcp_skill_tools / bind_dropdown_only_lists_valid_tokens / bind_calls_store_upsert_with_tool_and_token / unbind_calls_store_unbind / never_renders_token_plaintext 全 GREEN）。
- `pnpm vue-tsc --noEmit` → **清白**（无类型错误输出）。
- `rg "friday_pat_" web/src/stores/toolBindings.ts web/src/components/toolBindings web/src/api/toolBindings.ts`（排除 __tests__）→ 仅 spec mock 命中，生产代码零明文驻留。
- `rg "tools/execute" web/src/` → 零命中（浏览器 client 不引用执行端点）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - 安全] 移除 api/toolBindings.ts 注释中的字面 `/tools/execute/`**
- **Found during:** Task 3 收尾验证
- **Issue:** Task 1 写入的注释以否定语气提及字面路径 `/tools/execute/`，使 `rg "tools/execute" web/src` 命中浏览器 client，违背「浏览器零执行端点引用」边界。
- **Fix:** 注释改写为「工具执行端点（PAT-only 容器回调）」描述，去除字面路径 token。
- **Files modified:** web/src/api/toolBindings.ts
- **Commit:** `9a8baa50`

## Known Stubs

无。三组件均连真实 store/api（端点由 10-03 落地后运行期联通；前端契约与 spec mock + 后端 DTO 形状对齐）。

## Issues Encountered

无。

## Threat Flags

无新增信任边界外的安全面：绑定管理纯展示，明文绝不进浏览器（BoundTokenDto 白名单），下拉仅列 is_valid 令牌，client 不引用执行端点。

## Self-Check: PASSED

- Files: toolBinding.ts / toolBindings.ts(api) / toolBindings.ts(store) / ToolBindingTable.vue / ToolBindDialog.vue / ToolBindingSettings.vue / profile.vue — all FOUND.
- Commits: 71dc131f / 9ffbef86 / 9a8baa50 / f24a3dbd — all FOUND.
- Specs 5/5 GREEN; typecheck clean.

---
*Phase: 10-mcpb*
*Completed: 2026-06-10*
