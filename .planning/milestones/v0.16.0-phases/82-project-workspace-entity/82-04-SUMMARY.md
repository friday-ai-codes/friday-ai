# 82-04 Summary — 侧边栏「项目」tab + 列表默认当前空间(localStorage 记忆)

**Status:** Done
**Wave:** 1
**Requirements:** WS-01

## What shipped

- 侧边栏 `mainNavItems` 在「首页」(index 0) 与「空间」之间插入「项目」入口
  `{ to: '/projects', label: '项目', icon: 'lucide--folder-kanban' }`（沿用同数组硬编码中文风格）。
- `/projects` 列表的空间筛选改为 `useLocalStorage<string>('projects-selected-space', ALL)`：
  用户所选空间本地记忆，刷新/重进沿用；默认 `__all__`（全部空间），首次无记忆不破坏现状。
- 既有状态/成员/搜索筛选与下拉绑定不变，无后端偏好接口，无新增依赖（复用 `@vueuse/core`）。

## Files

- `web/src/components/layout/AppSidebar.vue` — 新增 `/projects` 导航项（首页↓空间↑）
- `web/src/pages/projects/index.vue` — spaceFilter 用 `useLocalStorage('projects-selected-space')` 记忆
- `web/src/pages/projects/__tests__/app-sidebar-nav.spec.ts` — 新增：静态读源守护侧边栏顺序
- `web/src/pages/projects/__tests__/projects-list.spec.ts` — 扩充：localStorage 默认空间驱动查询 / 无记忆不带 space_id

## Verification

- `pnpm vitest run src/pages/projects/__tests__/` 全绿（8 例）。
- `pnpm vue-tsc --noEmit` 绿。

## Must-haves

- [x] 侧边栏「项目」入口位于首页之下、空间之上
- [x] /projects 默认按所选空间过滤
- [x] localStorage `projects-selected-space` 本地记忆，刷新沿用
- [x] 状态/成员/搜索筛选不回退
- [x] 全量 zh-CN，vue-tsc 绿
