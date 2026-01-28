## ADDED Requirements
### Requirement: Chat Service
系统 SHALL 提供通用的 LLM 对话服务，支持配置验证和模型列表获取。
#### Scenario: 获取可用模型列表
- **WHEN** 调用 `GET /api/v1/chat/models` 并指定配置来源
- **THEN** 系统使用对应的 Claude 配置调用 `/v1/models` 端点
- **AND** 返回可用模型列表
#### Scenario: 使用系统配置获取模型
- **WHEN** 请求参数 `source=system`
- **THEN** 使用系统级 Claude API Key 和 Base URL
#### Scenario: 使用项目配置获取模型
- **WHEN** 请求参数 `source=project` 且提供 `project_id`
- **THEN** 使用项目级 Claude 配置
- **AND** 如项目未配置则返回错误
#### Scenario: 发送对话请求
- **WHEN** 调用 `POST /api/v1/chat/completions` 并提供消息和配置来源
- **THEN** 系统使用对应的 Claude 配置转发请求
- **AND** 返回 LLM 响应结果
#### Scenario: 对话请求格式
- **WHEN** 发送对话请求
- **THEN** 请求体包含 `model`、`messages`、`source` 字段
- **AND** `messages` 为 OpenAI 格式的消息数组
#### Scenario: 临时配置测试
- **WHEN** 请求中包含 `api_key` 和 `base_url` 参数
- **THEN** 系统使用临时配置而非存储的配置
- **AND** 允许测试未保存的配置
