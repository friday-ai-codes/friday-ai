## ADDED Requirements
### Requirement: 项目级 Webhook Token 自动生成
系统 SHALL 在创建项目时自动生成一个唯一的 Webhook Token，用于验证飞书项目发送的 Webhook 请求。
#### Scenario: 创建项目时自动生成 Token
- **WHEN** 用户创建新项目
- **THEN** 系统自动生成一个 32 字符的随机 Token
- **AND** 将 Token 保存到 Project 的 webhook_token 字段
- **AND** 在项目创建响应中返回此 Token
#### Scenario: 查看项目详情时显示 Token
- **WHEN** 用户查看项目详情
- **THEN** 系统返回项目的 webhook_token 字段
- **AND** 前端显示 Token 及复制按钮
### Requirement: Webhook Token 刷新功能
系统 SHALL 支持用户主动刷新项目的 Webhook Token，生成新的随机 Token。
#### Scenario: 刷新 Webhook Token
- **WHEN** 用户调用 POST /api/projects/{id}/refresh-webhook-token
- **THEN** 系统生成新的 32 字符随机 Token
- **AND** 更新 Project 的 webhook_token 字段
- **AND** 返回新的 Token
#### Scenario: 前端刷新确认
- **WHEN** 用户点击「刷新 Token」按钮
- **THEN** 系统显示确认对话框，提示刷新后需要更新飞书项目配置
- **AND** 用户确认后调用刷新接口
### Requirement: Webhook Token 自定义功能
系统 SHALL 支持用户自定义 Webhook Token，但限制最大长度为 32 个字符。
#### Scenario: 自定义 Webhook Token
- **WHEN** 用户调用 PUT /api/projects/{id}/webhook-token
- **AND** 请求体包含 token 字段（最大 32 字符）
- **THEN** 系统更新 Project 的 webhook_token 字段
- **AND** 返回更新后的 Token
#### Scenario: Token 长度验证
- **WHEN** 用户提交超过 32 字符的 Token
- **THEN** 系统返回 400 错误
- **AND** 提示 Token 长度不能超过 32 个字符
#### Scenario: 前端自定义 Token 输入
- **WHEN** 用户在输入框中输入自定义 Token
- **THEN** 前端验证长度不超过 32 个字符
- **AND** 用户点击保存后调用更新接口
### Requirement: Webhook Token 安全提示
系统 SHALL 在前端显示 Webhook Token 时提供安全警告，告知用户此 Token 的用途和安全注意事项。
#### Scenario: 显示安全警告
- **WHEN** 前端显示 Webhook Token
- **THEN** 在 Token 下方显示安全警告
- **AND** 警告内容包含：「此 Token 用于验证飞书项目 Webhook 请求的来源，请勿泄露给他人」
- **AND** 说明在飞书项目自动化规则中配置 Webhook 时需要填入此 Token
## MODIFIED Requirements
### Requirement: 项目级飞书凭证配置
Project 模型 SHALL 仅包含飞书集成配置，不再包含 Git 配置。Webhook Token 独立于插件凭证进行管理。
#### Scenario: 配置飞书插件凭证
- **WHEN** 用户调用设置飞书配置接口
- **THEN** 系统更新 Project 的飞书凭证字段（plugin_id、plugin_secret）
- **AND** 不影响 webhook_token 字段
- **AND** 不影响任何 Git 仓库配置
#### Scenario: 查看飞书配置状态
- **WHEN** 用户获取飞书配置
- **THEN** 系统返回 plugin_id、has_plugin_secret、is_configured
- **AND** 不返回 webhook_token 相关信息（由项目接口返回）
### Requirement: 前端飞书配置管理
系统 SHALL 提供前端界面用于管理项目的飞书集成配置。Webhook Token 在项目级别管理，不在飞书配置表单中。
#### Scenario: 查看飞书配置状态
- **WHEN** 用户访问项目详情页
- **THEN** 页面显示飞书配置状态卡片
- **AND** 显示「已配置」或「未配置」状态
- **AND** 显示各字段配置状态指示器（不包含 Webhook Token）
#### Scenario: 配置飞书凭证
- **WHEN** 用户点击「配置飞书集成」按钮
- **AND** 填写 Plugin ID、Plugin Secret
- **AND** 点击提交
- **THEN** 前端调用 POST /api/projects/{id}/feishu-config
- **AND** 成功后显示成功提示
- **AND** 更新配置状态显示
#### Scenario: 测试飞书凭证
- **WHEN** 用户点击「测试凭证」按钮
- **THEN** 前端调用 POST /api/projects/{id}/feishu-config/test
- **AND** 显示测试结果（成功/失败）
- **AND** 显示详细消息
#### Scenario: 删除飞书配置
- **WHEN** 用户点击「删除配置」按钮
- **AND** 确认删除操作
- **THEN** 前端调用 DELETE /api/projects/{id}/feishu-config
- **AND** 成功后更新配置状态显示
- **AND** 不影响 Webhook Token
### Requirement: 前端类型定义
前端项目 SHALL 定义飞书配置相关的 TypeScript 类型。Webhook Token 类型独立于飞书配置类型。
新增类型：
- `FeishuConfig` - 配置状态响应（不含 webhook_token）
- `FeishuConfigCreate` - 配置创建请求（不含 webhook_token）
- `FeishuConfigTestResult` - 凭证测试结果
- `WebhookTokenUpdate` - Webhook Token 更新请求
#### Scenario: 类型安全的 API 调用
- **WHEN** 前端调用飞书配置 API
- **THEN** 请求和响应均有正确的类型定义
- **AND** TypeScript 编译器能检查类型错误
