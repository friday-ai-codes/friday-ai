# Change: 实现现代化前端架构
## Why
当前前端项目（`web/`）仅有基础的 Vue 3 + Vite 配置，缺乏企业级应用所需的基础设施。为了支持 Friday AI 开发自动化系统的 Web 界面功能，需要建立一套完整的前端技术架构，包括 UI 组件库、状态管理、路由、国际化能力、测试框架等。
## What Changes
### 核心依赖升级
- 集成 **Tailwind CSS v4** 作为原子化样式方案，包含 CSS Reset
- 集成 **shadcn-vue** 作为无头 UI 组件库
- 集成 **Pinia** 作为状态管理方案
- 集成 **Vue Router** 作为路由方案
- 集成 **unplugin-auto-import** 和 **unplugin-vue-components** 实现自动导入
### 国际化能力
- 集成 **vue-i18n** 和 **unplugin-vue-i18n** 预留国际化能力
- 暂不实现具体的多语言功能
### 测试框架
- 集成 **Vitest** 实现单元测试
- 集成 **Playwright** 实现 E2E 测试
### 开发体验增强
- 配置 **VueUse** 提供常用组合式函数
- 配置基于文件系统的路由（unplugin-vue-router）
- 配置布局系统（vite-plugin-vue-layouts）
- 使用 **pnpm catalog** 统一管理依赖版本
- 路径别名 `~` 映射到 `src` 目录
## Impact
- **Affected specs**: 新增 `frontend-architecture` 能力规格
- **Affected code**:
 - `web/package.json` - 依赖更新，使用 pnpm catalog
 - `web/pnpm-workspace.yaml` - 新增 catalog 配置
 - `web/vite.config.ts` - 插件配置
 - `web/src/main.ts` - 应用入口重构
 - `web/src/` - 目录结构重组
 - `web/tsconfig.*.json` - TypeScript 配置调整
 - `web/vitest.config.ts` - 新增测试配置
 - `web/playwright.config.ts` - 新增 E2E 测试配置