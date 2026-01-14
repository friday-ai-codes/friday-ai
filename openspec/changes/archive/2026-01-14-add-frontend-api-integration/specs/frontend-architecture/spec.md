## ADDED Requirements
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
2. 创建项目页 `/projects/new`
3. 项目详情页 `/projects/:id`
4. 编辑项目页 `/projects/:id/edit`
5. 凭证管理页 `/projects/:id/credential`
#### Scenario: 项目列表页
- **WHEN** 用户访问 `/projects`
- **THEN** 应显示所有项目的卡片列表
- **AND** 每个卡片显示项目名称、仓库 URL、凭证状态
- **AND** 提供新建项目按钮
#### Scenario: 创建项目
- **WHEN** 用户在创建页面提交表单
- **THEN** 应验证表单数据
- **AND** 调用 API 创建项目
- **AND** 成功后跳转到项目详情页
#### Scenario: 凭证管理
- **WHEN** 用户访问凭证管理页
- **THEN** 应显示当前凭证类型
- **AND** 提供 SSH 密钥上传或 Access Token 设置选项
- **AND** 提供删除凭证功能
---
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