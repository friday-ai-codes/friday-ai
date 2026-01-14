# 前端架构实施任务清单
## 1. 依赖管理配置
- [x] 1.1 配置 pnpm catalog
 - 更新根目录 `pnpm-workspace.yaml` 添加 catalog 配置
 - 定义所有前端依赖的统一版本
- [x] 1.2 更新 package.json 使用 catalog
 - 将版本号替换为 `catalog:default`
 - 确保所有依赖通过 catalog 管理
## 2. 基础设施配置
- [x] 2.1 安装并配置 Tailwind CSS v4
 - 安装 `tailwindcss` `@tailwindcss/vite`
 - 创建 `src/styles/main.css`，引入 `@import "tailwindcss"`
 - 更新 `vite.config.ts` 添加 Tailwind 插件
 - 配置 CSS Reset（Tailwind 默认 Preflight）
- [x] 2.2 配置路径别名
 - 更新 `vite.config.ts` 添加 `~` 别名映射到 `src`
 - 更新 `tsconfig.json` 添加路径映射
## 3. 自动导入配置
- [x] 3.1 配置 unplugin-auto-import
 - 安装 `unplugin-auto-import`
 - 配置 Vue、VueUse、Vue Router、Pinia 自动导入
 - 生成 `auto-imports.d.ts` 类型声明
- [x] 3.2 配置 unplugin-vue-components
 - 安装 `unplugin-vue-components`
 - 配置组件自动导入
 - 生成 `components.d.ts` 类型声明
## 4. 路由与布局
- [x] 4.1 配置基于文件的路由
 - 安装 `unplugin-vue-router`
 - 创建 `src/pages/` 目录
 - 配置 typed-router
- [x] 4.2 配置布局系统
 - 安装 `vite-plugin-vue-layouts`
 - 创建 `src/layouts/default.vue`
 - 配置布局自动注册
- [x] 4.3 配置 Vue Router
 - 安装 `vue-router`
 - 创建路由入口配置
 - 更新 `main.ts` 使用路由
## 5. 状态管理
- [x] 5.1 配置 Pinia
 - 安装 `pinia`
 - 创建 `src/stores/` 目录
 - 更新 `main.ts` 使用 Pinia
## 6. 国际化（预留能力）
- [x] 6.1 配置 vue-i18n 基础设施
 - 安装 `vue-i18n`
 - 安装 `unplugin-vue-i18n`
 - 创建 `src/locales/` 目录结构
 - 配置 unplugin-vue-i18n 插件
 - 暂不创建具体翻译文件
## 7. UI 组件库
- [x] 7.1 初始化 shadcn-vue
 - 创建 `components.json` 配置文件
 - 配置 `~` 路径别名
 - 创建 `src/lib/utils.ts` 工具函数
- 7.2 安装基础组件（可选，按需安装）
 - 运行 `npx shadcn-vue@latest add button`
 - 配置组件路径 `src/components/ui/`
- [x] 7.3 配置 VueUse
 - 安装 `@vueuse/core` `@vueuse/head`
 - 配置 `useHead` 用于页面标题管理
## 8. 测试框架
- [x] 8.1 配置 Vitest 单元测试
 - 安装 `vitest` `@vue/test-utils` `happy-dom`
 - 创建 `vitest.config.ts`
 - 配置测试脚本 `pnpm test:unit`
 - 创建示例单元测试
- [x] 8.2 配置 Playwright E2E 测试
 - 安装 `@playwright/test`
 - 创建 `playwright.config.ts`
 - 创建 `tests/e2e/` 目录
 - 配置测试脚本 `pnpm test:e2e`
 - 创建示例 E2E 测试
## 9. 项目结构
- [x] 9.1 创建目录结构
 - `src/components/` - 全局组件
 - `src/components/__tests__/` - 组件测试
 - `src/composables/` - 组合式函数
 - `src/stores/` - Pinia stores
 - `src/types/` - TypeScript 类型
 - `src/assets/` - 资源文件
 - `tests/e2e/` - E2E 测试
- [x] 9.2 创建示例页面
 - 创建首页 `src/pages/index.vue`
 - 创建任务列表页 `src/pages/tasks/index.vue`
 - 验证路由和布局功能
## 10. 构建验证
- [x] 10.1 验证开发环境
 - 运行 `pnpm dev` 确保开发服务器正常
 - 验证 HMR 热更新
 - 验证自动导入和类型提示
- 10.2 验证生产构建（待后续验证）
 - 运行 `pnpm build` 生成产物
 - 运行 `pnpm preview` 预览构建结果
- 10.3 验证测试（待后续验证）
 - 运行 `pnpm test:unit` 确保单元测试通过
 - 运行 `pnpm test:e2e` 确保 E2E 测试通过
- 10.4 更新 Dockerfile（待后续验证）
 - 更新构建命令
 - 验证 Docker 构建
## 11. 文档更新
- [x] 11.1 更新 README
 - 添加前端技术栈说明
 - 添加开发命令说明
 - 添加目录结构说明
 - 添加测试命令说明