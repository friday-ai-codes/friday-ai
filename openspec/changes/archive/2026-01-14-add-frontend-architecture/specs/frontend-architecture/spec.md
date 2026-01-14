## ADDED Requirements
### Requirement: Tailwind CSS 样式系统
前端项目 SHALL 使用 Tailwind CSS v4 作为样式方案，并包含以下配置：
1. 原子化 CSS 类支持
2. CSS Reset（Preflight）
3. 响应式设计断点
4. 暗色模式支持（可选启用）
#### Scenario: Tailwind 样式应用
- **WHEN** 开发者在 Vue 组件中使用 Tailwind 类名
- **THEN** 样式应正确编译并应用到元素上
- **AND** 未使用的样式应被 Tree-shaking 移除
#### Scenario: CSS Reset 生效
- **WHEN** 页面加载时
- **THEN** 浏览器默认样式应被重置为一致的基础样式
---
### Requirement: shadcn-vue UI 组件库
前端项目 SHALL 集成 shadcn-vue 作为 UI 组件库，组件代码直接存储在项目中。
1. 组件位于 `src/components/ui/` 目录
2. 使用 Radix Vue 作为无头组件基础
3. 支持按需引入组件
#### Scenario: 添加新组件
- **WHEN** 开发者运行 `npx shadcn-vue@latest add button`
- **THEN** Button 组件代码应被添加到 `src/components/ui/button/` 目录
- **AND** 组件应可在页面中直接使用
#### Scenario: 组件自动导入
- **WHEN** 开发者在 SFC 中使用 `<Button>` 组件
- **THEN** 组件应被自动导入，无需手动 import 语句
---
### Requirement: Vue Router 路由系统
前端项目 SHALL 使用 Vue Router 和基于文件系统的路由。
1. 页面文件位于 `src/pages/` 目录
2. 文件路径自动映射为路由路径
3. 支持动态路由参数（使用 `[param]` 语法）
4. 支持嵌套路由
#### Scenario: 文件路由映射
- **GIVEN** 文件 `src/pages/tasks/[id].vue` 存在
- **WHEN** 用户访问 `/tasks/123`
- **THEN** 该页面组件应被渲染
- **AND** 路由参数 `id` 应为 `123`
#### Scenario: 类型安全的路由
- **WHEN** 开发者使用 `router.push` 导航
- **THEN** TypeScript 应提供路由名称和参数的类型提示
---
### Requirement: Pinia 状态管理
前端项目 SHALL 使用 Pinia 作为状态管理方案。
1. Store 定义位于 `src/stores/` 目录
2. 支持 Composition API 风格的 Store 定义
3. 与 Vue DevTools 集成
#### Scenario: 创建和使用 Store
- **GIVEN** 定义了一个 `useTaskStore`
- **WHEN** 在组件中调用 `useTaskStore`
- **THEN** 应返回响应式的 store 实例
- **AND** store 状态变化应触发组件重渲染
#### Scenario: Store 持久化
- **WHEN** Store 配置了持久化选项
- **THEN** 状态应在页面刷新后保持
---
### Requirement: 国际化能力预留
前端项目 SHALL 预留 vue-i18n 国际化能力，暂不实现具体功能。
1. 安装 vue-i18n 和 unplugin-vue-i18n 依赖
2. 创建 `src/locales/` 目录结构
3. 配置 i18n 插件
4. 暂不创建具体的翻译文件
#### Scenario: i18n 插件已配置
- **WHEN** 开发者需要启用国际化功能
- **THEN** 基础设施已就绪，只需添加翻译文件
- **AND** 无需修改构建配置
---
### Requirement: 自动导入
前端项目 SHALL 配置自动导入以减少样板代码。
1. Vue 核心 API（ref, computed, watch 等）自动可用
2. VueUse 组合式函数自动可用
3. Vue Router API 自动可用
4. Pinia API 自动可用
5. 组件自动导入
#### Scenario: Vue API 自动导入
- **WHEN** 开发者在 `<script setup>` 中使用 `ref`
- **THEN** 无需手动导入 `import { ref } from 'vue'`
- **AND** TypeScript 类型应正确推断
#### Scenario: 组件自动导入
- **WHEN** 开发者在模板中使用 `<RouterLink>`
- **THEN** 组件应自动导入并渲染
- **AND** 无需手动 import 语句
---
### Requirement: 布局系统
前端项目 SHALL 支持可复用的布局组件。
1. 布局组件位于 `src/layouts/` 目录
2. 页面可通过路由 meta 指定布局
3. 默认布局为 `default.vue`
#### Scenario: 应用默认布局
- **GIVEN** 存在 `src/layouts/default.vue`
- **WHEN** 页面未指定布局
- **THEN** 应使用默认布局渲染
#### Scenario: 自定义布局
- **GIVEN** 页面配置了 `layout: 'admin'`
- **WHEN** 页面渲染时
- **THEN** 应使用 `src/layouts/admin.vue` 布局
---
### Requirement: 路径别名
前端项目 SHALL 使用 `~` 作为 `src` 目录的路径别名。
1. Vite 配置 resolve.alias
2. TypeScript 配置 paths 映射
3. 所有源码导入使用 `~` 前缀
#### Scenario: 别名解析
- **WHEN** 开发者使用 `import X from '~/components/X.vue'`
- **THEN** 应正确解析到 `src/components/X.vue`
- **AND** TypeScript 应识别别名路径
#### Scenario: IDE 支持
- **WHEN** 开发者在 IDE 中使用 `~` 路径
- **THEN** IDE 应提供正确的路径补全
- **AND** 跳转到定义功能应正常工作
---
### Requirement: pnpm catalog 依赖管理
前端项目 SHALL 使用 pnpm catalog 统一管理依赖版本。
1. 在 `pnpm-workspace.yaml` 中定义 catalogs
2. `package.json` 使用 `catalog:default` 引用版本
3. 所有依赖版本在 catalog 中集中定义
#### Scenario: 依赖版本统一
- **GIVEN** catalog 中定义 `vue: ^3.5.24`
- **WHEN** package.json 使用 `"vue": "catalog:default"`
- **THEN** 安装时应使用 catalog 中定义的版本
#### Scenario: 版本升级
- **WHEN** 需要升级某个依赖版本
- **THEN** 只需在 catalog 中修改一处
- **AND** 所有引用该依赖的包都会使用新版本
---
### Requirement: 单元测试框架
前端项目 SHALL 使用 Vitest 作为单元测试框架。
1. 与 Vite 配置共享
2. 支持 Vue 组件测试
3. 测试文件位于 `src/**/__tests__/` 目录
4. 配置 `pnpm test:unit` 命令
#### Scenario: 运行单元测试
- **WHEN** 开发者运行 `pnpm test:unit`
- **THEN** 应执行所有 `*.test.ts` 或 `*.spec.ts` 文件
- **AND** 输出测试结果和覆盖率
#### Scenario: 组件测试
- **GIVEN** 存在 `src/components/__tests__/Button.test.ts`
- **WHEN** 测试运行时
- **THEN** 应能渲染和断言 Vue 组件行为
---
### Requirement: E2E 测试框架
前端项目 SHALL 使用 Playwright 作为 E2E 测试框架。
1. 测试文件位于 `tests/e2e/` 目录
2. 支持多浏览器测试
3. 配置 `pnpm test:e2e` 命令
#### Scenario: 运行 E2E 测试
- **WHEN** 开发者运行 `pnpm test:e2e`
- **THEN** 应启动开发服务器
- **AND** 在浏览器中执行测试用例
- **AND** 输出测试结果
#### Scenario: 跨浏览器测试
- **WHEN** 配置了多个浏览器
- **THEN** 测试应在 Chromium、Firefox、WebKit 中运行
---
### Requirement: 开发体验
前端项目 SHALL 提供优秀的开发体验。
1. 热模块替换（HMR）支持
2. TypeScript 完整类型支持
3. Vue DevTools 集成
4. 路径别名支持（`~` 指向 `src/`）
#### Scenario: 热更新
- **WHEN** 开发者修改 Vue 组件代码
- **THEN** 浏览器应自动更新而不刷新页面
- **AND** 组件状态应保持
#### Scenario: 类型检查
- **WHEN** 代码中存在类型错误
- **THEN** IDE 应即时显示错误
- **AND** 构建时应报告类型错误