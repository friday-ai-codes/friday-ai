# workflow-nodes Specification
## Purpose
TBD - created by archiving change add-workflow-event-trigger. Update Purpose after archive.
## Requirements
### Requirement: Feishu Event Trigger Node
系统 SHALL 提供飞书事件触发节点 (`feishu_event_trigger`)，作为工作流的入口节点。
#### Scenario: Trigger node extracts event data
- **GIVEN** 工作流以 `feishu_event_trigger` 节点开始
- **WHEN** 飞书 Webhook 触发工作流执行
- **THEN** 节点输出包含:
 - `event_type`: 事件类型
 - `work_item_id`: 工作项 ID
 - `work_item_name`: 工作项名称
 - `project_key`: 项目 Key
 - `payload`: 完整 Webhook payload
#### Scenario: Trigger node configuration
- **GIVEN** 用户配置触发节点
- **WHEN** 设置 `event_types: ["WorkitemStatusEvent"]`
- **THEN** 节点仅响应 WorkitemStatusEvent 事件
---
### Requirement: Fetch Work Item Node
系统 SHALL 提供获取工作项详情节点 (`fetch_work_item`)，从飞书获取工作项完整信息。
#### Scenario: Fetch work item details
- **GIVEN** 节点配置 `work_item_id: "{{input.work_item_id}}"`
- **WHEN** 节点执行
- **THEN** 调用 FeishuClient.get_work_item 获取详情
- **AND** 输出包含工作项名称、描述、状态、字段
#### Scenario: Extract preset fields
- **GIVEN** 节点配置 `extract_fields: ["prd_url", "description", "tech_doc_url"]`
- **WHEN** 节点执行成功
- **THEN** 输出包含预设字段的值:
 - `prd_url`: 需求文档链接
 - `description`: 需求描述
 - `tech_doc_url`: 技术方案文档链接
#### Scenario: Include repositories
- **GIVEN** 节点配置 `include_repositories: true`
- **WHEN** 节点执行成功
- **THEN** 输出包含项目关联的所有仓库信息:
 - `repositories`: 仓库列表，每个包含 id, name, git_url, description
#### Scenario: Set global params
- **GIVEN** 节点配置 `set_global_params: true`
- **WHEN** 节点执行成功
- **THEN** 将提取的字段设置为工作流全局参数
- **AND** 后续节点可通过 `{{global.prd_url}}` 访问
---
### Requirement: AI Prompt Node
系统 SHALL 提供 AI Prompt 节点 (`ai_prompt`)，调用 LLM 生成文本响应。
#### Scenario: Execute AI prompt
- **GIVEN** 节点配置:
 - `system_prompt: "You are a helpful assistant."`
 - `user_prompt: "分析以下需求: {{global.description}}"`
 - `model: "claude-3-sonnet"`
- **WHEN** 节点执行
- **THEN** 调用 LLM 服务
- **AND** 输出包含 `response` (AI 生成的文本) 和 `usage` (token 使用量)
#### Scenario: Template variable rendering
- **GIVEN** `user_prompt` 包含模板变量 `{{global.description}}`
- **WHEN** 节点执行
- **THEN** 模板变量被替换为实际的全局参数值
#### Scenario: AI prompt failure handling
- **GIVEN** LLM 服务调用失败
- **WHEN** 节点执行
- **THEN** 输出到 `error` 端口
- **AND** 包含错误信息
---
### Requirement: AI Coding Dispatcher Node
系统 SHALL 提供 AI 编码指派器节点 (`ai_coding_dispatcher`)，分析需求并创建编码任务。
#### Scenario: Analyze requirements and create tasks
- **GIVEN** 全局参数包含 `prd_url`, `description`, `repositories`
- **WHEN** 节点执行
- **THEN** 节点:
 1. 抓取需求文档内容
 2. 获取各仓库的描述信息
 3. 调用 LLM 分析需求，判断涉及哪些仓库
 4. 为每个相关仓库生成编码任务 Prompt
 5. 创建 CodingTask 记录
#### Scenario: Limit max tasks
- **GIVEN** 节点配置 `max_tasks: 5`
- **WHEN** LLM 分析出 10 个潜在任务
- **THEN** 只创建优先级最高的 5 个任务
#### Scenario: Auto assign repositories
- **GIVEN** 节点配置 `auto_assign_repos: true`
- **WHEN** 节点执行
- **THEN** 每个 CodingTask 自动关联到最相关的仓库
#### Scenario: Include test tasks
- **GIVEN** 节点配置 `include_tests: true`
- **WHEN** 节点执行
- **THEN** 生成的任务包含测试编写任务
---
### Requirement: Node Registration
所有新节点 SHALL 使用 `@register_node` 装饰器注册到 NodeRegistry。
#### Scenario: Node auto-discovery
- **GIVEN** 节点类使用 `@register_node` 装饰器
- **WHEN** 系统启动
- **THEN** 节点自动注册到 NodeRegistry
- **AND** 可通过 `GET /api/workflows/nodes/schemas/` 获取节点 Schema
#### Scenario: Node schema includes all metadata
- **WHEN** 调用 `node.get_schema`
- **THEN** 返回包含:
 - `node_type`: 节点类型标识
 - `display_name`: 显示名称
 - `description`: 描述
 - `icon`: 图标名称
 - `category`: 分类
 - `config_schema`: 配置 JSON Schema
 - `inputs`: 输入端口列表
 - `outputs`: 输出端口列表
