## ADDED Requirements
### Requirement: System Settings Page
前端项目 SHALL 提供系统设置管理页面，用于配置全局系统参数。
#### Scenario: 访问系统设置页面
- **WHEN** 用户访问 `/settings`
- **THEN** 显示系统设置页面
- **AND** 展示 Claude Code 配置卡片
#### Scenario: 配置 Claude API Key
- **WHEN** 用户在系统设置页面输入 API Key 并保存
- **THEN** 调用 API 更新系统配置
- **AND** 显示保存成功提示
- **AND** API Key 显示为掩码形式
#### Scenario: 配置 Claude Base URL
- **WHEN** 用户输入自定义 Base URL
- **THEN** 验证 URL 格式
- **AND** 保存配置
#### Scenario: 系统设置导航入口
- **WHEN** 用户查看主导航菜单
- **THEN** 显示「系统设置」导航链接
- **AND** 点击后跳转到 `/settings` 页面
---
### Requirement: Settings Store
前端项目 SHALL 使用 Pinia Store 管理系统设置状态。
#### Scenario: 获取系统设置
- **WHEN** 调用 `settingsStore.fetchSettings`
- **THEN** 从 API 获取所有系统设置
- **AND** 更新 Store 状态
#### Scenario: 更新系统设置
- **WHEN** 调用 `settingsStore.updateSetting(key, value)`
- **THEN** 调用 API 更新配置
- **AND** 更新本地状态
---
### Requirement: Project Claude Configuration UI
前端项目 SHALL 在项目管理页面提供 Claude 配置功能。
#### Scenario: 项目详情页 Claude 配置 Tab
- **WHEN** 用户访问项目详情页
- **THEN** 显示「Claude 配置」Tab
- **AND** 展示当前配置状态和来源
#### Scenario: 启用项目专属配置
- **WHEN** 用户勾选「使用项目专属配置」
- **THEN** 显示 API Key 和 Base URL 输入框
- **AND** 允许输入项目专属配置
#### Scenario: 显示配置来源
- **WHEN** 项目未配置专属 Claude 配置
- **THEN** 显示「当前使用：系统配置」
- **WHEN** 项目已配置专属配置
- **THEN** 显示「当前使用：项目配置」
#### Scenario: 清除项目配置
- **WHEN** 用户取消勾选「使用项目专属配置」
- **THEN** 清除项目级 Claude 配置
- **AND** 回退到系统配置
---
### Requirement: Settings API Client
前端项目 SHALL 提供系统设置 API 客户端。
#### Scenario: 获取设置列表
- **WHEN** 调用 `settingsApi.list`
- **THEN** 发起 `GET /api/v1/settings` 请求
- **AND** 返回类型化的设置列表
#### Scenario: 更新设置
- **WHEN** 调用 `settingsApi.update(key, value)`
- **THEN** 发起 `PUT /api/v1/settings/{key}` 请求
- **AND** 返回更新后的设置
## MODIFIED Requirements
### Requirement: Projects Store
前端项目 SHALL 使用 Pinia Store 管理项目状态，包括 Claude 配置管理。
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
#### Scenario: 获取项目 Claude 配置
- **WHEN** 调用 `projectsStore.fetchClaudeConfig(projectId)`
- **THEN** 应从 API 获取项目 Claude 配置
- **AND** 返回配置状态和来源
#### Scenario: 更新项目 Claude 配置
- **WHEN** 调用 `projectsStore.updateClaudeConfig(projectId, config)`
- **THEN** 应调用 API 更新配置
- **AND** 更新本地项目状态
