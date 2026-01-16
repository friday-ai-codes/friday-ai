# frontend-architecture Specification
## Purpose
TBD - created by archiving change add-frontend-architecture. Update Purpose after archive.
## Requirements
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
### Requirement: API 服务层
前端项目 SHALL 提供统一的 API 服务层，封装所有后端 API 调用。
1. API 客户端位于 `src/api/client.ts`
2. 各业务模块 API 位于 `src/api/{module}.ts`
3. 提供类型安全的请求方法
4. 统一处理错误响应
#### Scenario: 发起 GET 请求
- **WHEN** 前端调用 `projectsApi.list`
- **THEN** 应发起 `GET /api/projects` 请求
- **AND** 返回类型化的项目列表
#### Scenario: 发起 POST 请求
- **WHEN** 前端调用 `projectsApi.create(data)`
- **THEN** 应发起 `POST /api/projects` 请求
- **AND** 请求体为 JSON 格式
- **AND** 返回创建的项目对象
#### Scenario: API 错误处理
- **WHEN** 后端返回错误响应
- **THEN** API 客户端应抛出 ApiError 异常
- **AND** 包含状态码和错误消息
---
### Requirement: Projects Store
前端项目 SHALL 使用 Pinia Store 管理项目状态。
1. Store 定义位于 `src/stores/projects.ts`
2. 管理项目列表、当前项目、加载状态
3. 提供 CRUD 操作方法
4. 支持凭证管理操作
#### Scenario: 获取项目列表
- **WHEN** 调用 `projectsStore.fetchProjects`
- **THEN** 应从 API 获取项目列表
- **AND** 更新 `projects` 状态
- **AND** 管理 `loading` 和 `error` 状态
#### Scenario: 创建项目
- **WHEN** 调用 `projectsStore.createProject(data)`
- **THEN** 应调用 API 创建项目
- **AND** 将新项目添加到列表
- **AND** 返回创建的项目
---
### Requirement: Tasks Store
前端项目 SHALL 使用 Pinia Store 管理任务状态。
1. Store 定义位于 `src/stores/tasks.ts`
2. 管理任务列表、当前任务、过滤条件
3. 提供任务 CRUD 和状态转换方法
4. 提供任务执行控制方法
#### Scenario: 获取任务列表
- **WHEN** 调用 `tasksStore.fetchTasks(filters)`
- **THEN** 应从 API 获取任务列表
- **AND** 支持 project_id 和 status 过滤
#### Scenario: 任务状态转换
- **WHEN** 调用 `tasksStore.transitionTask(taskId, newStatus)`
- **THEN** 应调用 API 转换状态
- **AND** 更新本地任务状态
#### Scenario: 执行任务
- **WHEN** 调用 `tasksStore.executeTask(taskId, mode)`
- **THEN** 应调用 API 启动任务执行
- **AND** 返回容器 ID
---
### Requirement: 项目管理页面
前端项目 SHALL 提供完整的项目管理界面。
1. 项目列表页 `/projects`
2. 新建项目页 `/projects/new`
3. 项目详情页 `/projects/:id`
4. 编辑项目页 `/projects/:id/edit`
5. 飞书配置页 `/projects/:id/feishu`
项目详情页 SHALL 移除直接的 Git 配置展示，改为展示关联的仓库列表。
#### Scenario: 项目列表页
- **WHEN** 用户访问 `/projects`
- **THEN** 应显示项目表格
- **AND** 每行显示项目名称
#### Scenario: 项目详情页
- **WHEN** 用户访问项目详情页
- **THEN** 显示"基本信息"（飞书配置）
- **AND** 显示"关联仓库"列表
- **AND** 提供关联/解除关联仓库的操作
#### Scenario: 新建项目页
- **WHEN** 用户访问 `/projects/new`
- **THEN** 应显示项目创建表单
- **AND** 验证必填字段
#### Scenario: 飞书配置页
- **WHEN** 用户访问 `/projects/:id/feishu`
- **THEN** 应显示飞书集成配置表单
- **AND** 支持配置应用凭证
### Requirement: 任务管理页面
前端项目 SHALL 提供完整的任务管理界面。
1. 任务列表页 `/tasks`
2. 任务详情页 `/tasks/:id`
#### Scenario: 任务列表页
- **WHEN** 用户访问 `/tasks`
- **THEN** 应显示任务表格
- **AND** 支持按项目和状态过滤
- **AND** 每行显示任务标题、状态、创建时间
#### Scenario: 任务详情页
- **WHEN** 用户访问 `/tasks/:id`
- **THEN** 应显示任务完整信息
- **AND** 显示状态流转步骤条
- **AND** 显示计划输出内容
- **AND** 显示 Git 信息
---
### Requirement: 任务执行控制
前端项目 SHALL 提供任务执行的控制界面。
1. 启动 Plan 模式执行
2. 启动 Execute 模式执行
3. 停止正在执行的任务
4. 实时查看任务日志
#### Scenario: 启动 Plan 模式
- **WHEN** 任务状态为 PENDING
- **AND** 用户点击 "启动规划"
- **THEN** 应调用执行 API
- **AND** 显示容器启动成功提示
- **AND** 开始轮询任务日志
#### Scenario: 查看任务日志
- **WHEN** 任务正在执行
- **THEN** 应每 2 秒轮询日志 API
- **AND** 在日志区域显示最新日志
- **AND** 自动滚动到底部
#### Scenario: 停止任务
- **WHEN** 用户点击 "停止任务"
- **THEN** 应显示确认对话框
- **AND** 确认后调用停止 API
- **AND** 任务状态更新为 FAILED
---
### Requirement: 任务状态可视化
前端项目 SHALL 提供直观的任务状态展示。
1. 使用 Badge 组件显示任务状态
2. 使用 Stepper 组件显示状态流转
3. 不同状态使用不同颜色
#### Scenario: 状态 Badge 显示
- **WHEN** 渲染任务状态
- **THEN** 应根据状态显示对应颜色
 - PENDING: 灰色
 - PLANNING: 蓝色 + 动画
 - PLAN_REVIEW: 黄色
 - EXECUTING: 蓝色 + 动画
 - CODE_REVIEW: 黄色
 - MERGED: 绿色
 - FAILED: 红色
#### Scenario: 状态步骤条
- **WHEN** 渲染任务详情页
- **THEN** 应显示横向步骤条
- **AND** 当前状态高亮
- **AND** 已完成状态显示对勾
---
### Requirement: 通知系统
前端项目 SHALL 提供统一的通知机制。
1. 使用 Toast 显示操作结果
2. 支持成功、错误、警告类型
3. 自动消失或手动关闭
#### Scenario: 操作成功通知
- **WHEN** 创建项目成功
- **THEN** 应显示绿色成功 Toast
- **AND** 3 秒后自动消失
#### Scenario: 操作失败通知
- **WHEN** API 调用失败
- **THEN** 应显示红色错误 Toast
- **AND** 显示错误消息
- **AND** 可手动关闭
---
### Requirement: 仪表盘首页
前端项目 SHALL 提供概览仪表盘。
1. 显示项目和任务统计
2. 显示最近任务列表
3. 提供快速操作入口
#### Scenario: 统计卡片
- **WHEN** 用户访问首页
- **THEN** 应显示项目总数
- **AND** 显示各状态任务数量
- **AND** 数据实时从 API 获取
#### Scenario: 最近任务
- **WHEN** 用户访问首页
- **THEN** 应显示最近 5 个任务
- **AND** 点击可跳转到详情页
### Requirement: Repository Management UI
系统 SHALL 提供仓库管理界面。
#### Scenario: Repository List Page
- **WHEN** 用户访问 `/repositories`
- **THEN** 显示所有已配置的 Git 仓库列表
#### Scenario: Create/Edit Repository
- **WHEN** 用户创建或编辑仓库
- **THEN** 提供表单输入 git_url, name, default_branch, claude_md_path 等信息
### Requirement: Project-Repository Linking UI
系统 SHALL 在项目详情页提供仓库关联管理功能。
#### Scenario: Link Repository
- **WHEN** 在项目详情页点击“关联仓库”
- **THEN** 弹出对话框选择已有仓库进行关联
#### Scenario: Unlink Repository
- **WHEN** 在已关联仓库列表中点击“移除”
- **THEN** 解除该仓库与当前项目的关联
### Requirement: Repository Navigation Entry
系统 SHALL 在主导航菜单中提供仓库管理的独立入口。
#### Scenario: Repository Navigation Link
- **WHEN** 用户查看主导航菜单
- **THEN** 显示"仓库"导航链接
- **AND** 点击后跳转到 `/repositories` 仓库列表页
### Requirement: Repository-Project Association Display
系统 SHALL 在仓库详情页展示关联的项目列表。
#### Scenario: Repository Detail Shows Associated Projects
- **WHEN** 用户访问仓库详情页 `/repositories/:id`
- **THEN** 显示"关联项目"卡片
- **AND** 列出所有与该仓库关联的项目
- **AND** 每个项目提供跳转到项目详情的链接
#### Scenario: No Associated Projects
- **WHEN** 仓库没有关联任何项目
- **THEN** 显示"暂无关联项目"的空状态提示
### Requirement: Repositories Store Projects Support
仓库 Store SHALL 支持管理仓库关联的项目数据。
#### Scenario: Fetch Repository With Projects
- **WHEN** 调用 `repositoriesStore.fetchRepository(id)`
- **THEN** 返回的仓库数据应包含 `projects` 字段
- **AND** `projects` 字段包含关联项目的基本信息（id、name）
