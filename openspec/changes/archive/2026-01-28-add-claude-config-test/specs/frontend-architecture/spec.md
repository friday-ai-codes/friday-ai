## ADDED Requirements
### Requirement: Claude Test Dialog Component
前端项目 SHALL 提供可复用的 Claude 配置测试对话框组件。
#### Scenario: 打开测试对话框
- **WHEN** 用户点击「测试」按钮
- **THEN** 弹出测试对话框
- **AND** 显示测试输入框，默认值为「你基于什么模型？」
- **AND** 显示已选择的模型名称
#### Scenario: 执行测试
- **WHEN** 用户点击对话框中的「发送」按钮
- **THEN** 调用 Chat API 发送测试请求
- **AND** 显示加载状态
- **AND** 完成后在结果区域显示 LLM 响应
#### Scenario: 结果 Markdown 渲染
- **WHEN** LLM 返回响应
- **THEN** 结果区域使用 Markdown 渲染响应内容
- **AND** 保持与其他页面一致的样式
#### Scenario: 测试失败处理
- **WHEN** 测试请求失败
- **THEN** 显示错误提示信息
- **AND** 允许用户修改输入后重试
---
### Requirement: Model Selection in Claude Configuration
前端项目 SHALL 在 Claude 配置位置提供模型选择功能。
#### Scenario: 自动获取模型列表
- **WHEN** 用户填写完 API Key 和 Base URL
- **AND** 输入框失焦
- **THEN** 自动调用 API 获取可用模型列表
- **AND** 显示加载状态
#### Scenario: 模型列表展示
- **WHEN** 成功获取模型列表
- **THEN** 显示模型选择下拉框
- **AND** 默认选中第一个模型
- **AND** 显示「测试」按钮
#### Scenario: 获取模型失败
- **WHEN** 获取模型列表失败
- **THEN** 显示错误提示
- **AND** 提供手动输入模型名称的选项
---
### Requirement: System Settings Claude Test Integration
系统设置页面 SHALL 集成 Claude 配置测试功能。
#### Scenario: 系统设置测试按钮
- **WHEN** 用户在系统设置页面配置了 Claude API Key
- **THEN** 显示模型选择下拉框
- **AND** 显示「测试」按钮
#### Scenario: 系统设置测试流程
- **WHEN** 用户点击系统设置的「测试」按钮
- **THEN** 打开 Claude 测试对话框
- **AND** 使用系统配置进行测试
---
### Requirement: Project Claude Config Test Integration
项目 Claude 配置 Tab SHALL 集成测试功能。
#### Scenario: 项目配置测试按钮
- **WHEN** 用户在项目 Claude 配置 Tab 启用了项目专属配置
- **AND** 填写了 API Key
- **THEN** 显示模型选择下拉框
- **AND** 显示「测试」按钮
#### Scenario: 项目配置测试流程
- **WHEN** 用户点击项目配置的「测试」按钮
- **THEN** 打开 Claude 测试对话框
- **AND** 使用项目配置进行测试
---
### Requirement: Chat API Client
前端项目 SHALL 提供 Chat API 客户端。
#### Scenario: 获取模型列表
- **WHEN** 调用 `chatApi.getModels(source, projectId?)`
- **THEN** 发起 `GET /api/v1/chat/models` 请求
- **AND** 返回类型化的模型列表
#### Scenario: 发送对话请求
- **WHEN** 调用 `chatApi.completions(request)`
- **THEN** 发起 `POST /api/v1/chat/completions` 请求
- **AND** 返回 LLM 响应结果
