---
phase: 84-project-workbench-ui
plan: 02
subsystem: ui
tags: [vue3, vue-query, tailwind, reka-ui, i18n, project-workbench]

requires:
  - phase: 82-project-pages
    provides: 「项目」sidebar tab + projects/index.vue 列表 + projects/[id]/index.vue 详情
  - phase: 84-01
    provides: 工作区 REST serializer wire 契约（doc content / human-blocks / feature-list / work-items 含状态 / search / state-apis）
provides:
  - WorkbenchShell 工作台外壳（左导航 + 右主区 split + activeSection 状态机 + #hash 双向同步）
  - OverviewSection 大盘（概览 + 人员带身份 PM/开发负责人/开发者/测试 + 状态栏 + 重建工作区派发→轮询）
  - projectWorkspaceApi 工作区数据层（docs/doc-content/human-blocks/rebuild/state-apis/feature-list/work-items/search）+ TS 接口（契约单一来源）
  - projects.workbench.* 全量 zh-CN i18n keys
  - Docs/FeatureList/Dependencies 占位 section（Wave 2/3 补全）
affects: [84-03, 84-04, 84-05]

tech-stack:
  added: []
  patterns:
    - "工作台 in-page section 切换（非子路由、非锚点滚动）+ #hash 深链"
    - "API 客户端注释顶部固化 snake_case wire 契约清单（前后端单一基准，守护测试无法捕获漂移）"
    - "派发→轮询：重建工作区 useMutation + listDocs refetchInterval(sync_status==='syncing')"

key-files:
  created:
    - web/src/api/projectWorkspace.ts
    - web/src/components/project/workbench/WorkbenchShell.vue
    - web/src/components/project/workbench/OverviewSection.vue
    - web/src/components/project/workbench/DocsSection.vue
    - web/src/components/project/workbench/FeatureListSection.vue
    - web/src/components/project/workbench/DependenciesSection.vue
    - web/src/pages/projects/__tests__/workbench-shell.spec.ts
  modified:
    - web/src/api/index.ts
    - web/src/locales/zh-CN.json
    - web/src/pages/projects/[id]/index.vue

key-decisions:
  - "WorkbenchShell 通过默认作用域插槽 {active} 暴露当前区块，父级用 v-if + defineAsyncComponent 懒加载各 section"
  - "状态栏 status 用 Badge（variant 按状态映射）而非 StatusBadge——后者 type 枚举不含 project"
  - "人员身份映射：PM=pm、开发负责人=owner(crown)、开发者=frontend+backend、测试=qa"

patterns-established:
  - "工作区 section 卡头 px-5 py-3.5 border-b + 卡体 p-5；区块间距 space-y-6"
  - "守护测试 mock vue-router（reactive route.hash + replace spy）验证 hash 同步"

requirements-completed: [WB-01]

duration: ~20min
completed: 2026-06-27
---

# Phase 84 (Plan 02): 项目工作台前端基座 + 大盘概览 Summary

**把 projects/[id] 从 reka-ui 6 标签升级为「左导航 + 右主区」工作台外壳，落地 WB-01 大盘（概览 + 人员带身份 + 状态栏 + 重建工作区轮询），并建立工作区数据层与 i18n 契约基座。**

## Accomplishments
- `WorkbenchShell.vue`：左 `w-48 sticky top-22` 导航轨（active 指示条 + badge）+ 右 `flex-1 space-y-6` 主区；窄屏折叠为顶部 `Select`；`activeSection` 与 `route.hash` 双向同步，支持深链书签；非子路由、非锚点滚动。
- `OverviewSection.vue`（WB-01）：复用 `OverviewTab` 概览 + 人员（按 ProjectRole 映射 PM/开发负责人/开发者/测试 身份徽章，owner 带 crown）+ 状态栏（项目状态 Badge + docs `sync_status` 概要 + 重建工作区按钮，派发后 `refetchInterval` 轮询）。
- `projectWorkspace.ts`：封装 84-01 全部工作区端点 + TS 接口，文件顶部固化 snake_case wire 契约清单作为前后端单一基准；barrel 导出。
- `projects.workbench.*` 全量 zh-CN keys（nav/overview/docs/feature/deps/search/section）。
- 占位 section（Docs/FeatureList/Dependencies）：卡头 + 「建设中」占位，供 Wave 2/3 补全。
- 守护测试 6 例全绿（左导航 4 项文案、section 切换 + hash、深链直达、人员身份徽章、空态、错误态）。

## Files Created/Modified
见 frontmatter `key-files`。`web/src/components.d.ts` 由 unplugin 自动重生成（新增组件声明）。

## Decisions Made
见 frontmatter `key-decisions`。

## Deviations from Plan
None - 按 plan 执行；唯一微调：状态栏用 `Badge` 而非 `StatusBadge`（后者 type 枚举不含 project status，使用会需额外 status config）。

## Verification
- `pnpm vue-tsc --noEmit`：0 error。
- `pnpm vitest run src/pages/projects/__tests__/workbench-shell.spec.ts`：6/6 通过。
- 基线 `projects-list.spec.ts`：6/6 仍绿。
- ESLint：tailwind `min-w-[1.25rem]` → `min-w-5` 已修正，无遗留告警。

## Section Stubs Left for Later Waves
- `DocsSection.vue` → WB-03（5 文件查看/编辑，84-03）
- `FeatureListSection.vue` → WB-02（feature 树 + 进度灯，84-04）
- `DependenciesSection.vue` → WB-04（外部依赖/关联，84-04）
- 搜索（WB-05）为列表页职责，未纳入工作台 4 区块。

## Next Phase Readiness
- 外壳 + 数据层 + i18n 契约就位；Wave 2/3 plan 只需补全各自 section 组件文件，零共享文件冲突。
- 后端端点未就绪时，`projectWorkspaceApi` 已按 84-01 serializer 字段 typed；前端 best-effort 空/错兜底，不阻塞。

---
*Phase: 84-project-workbench-ui (plan 02)*
*Completed: 2026-06-27*
