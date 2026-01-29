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
### Requirement: Global Variables Storage
系统 SHALL 在工作流执行上下文中维护一个全局变量存储区域，用于存放用户定义的变量。
每个全局变量 SHALL 包含以下元数据：
- `key`: 变量的唯一标识符，用于在模板中引用（必填）
- `name`: 变量的显示名称，用于 UI 展示（必填）
- `desc`: 变量的描述信息（选填）
- `value`: 变量的实际值（必填）
- `required`: 是否为必填变量（默认 false）
- `source_node`: 定义该变量的节点 ID（系统自动填充）
#### Scenario: Variable stored successfully
- **WHEN** 变量提取节点成功提取一个值
- **THEN** 该变量 SHALL 被存储到 `context.global_variables` 中
- **AND** 后续节点 SHALL 能够通过 `{{ global.<key> }}` 语法引用该变量
#### Scenario: Variable override
- **WHEN** 两个节点定义了相同 key 的变量
- **THEN** 按拓扑执行顺序，后执行的节点定义的值 SHALL 覆盖先前的值
- **AND** 系统 SHALL 记录一条 warning 日志
---
### Requirement: Variable Extractor Node
系统 SHALL 提供「变量提取」节点类型，允许用户从上游节点的 JSON/YAML 输出中提取指定字段并注册为全局变量。
节点配置 SHALL 包含：
- `extractions`: 提取规则列表，每条规则包含：
 - `source_path`: JSONPath 表达式（如 `$.data.fields.description` 或 `$.fields[?(@.key=='title')].value`）
 - `key`: 变量标识符
 - `name`: 变量显示名称
 - `desc`: 变量描述（选填）
 - `required`: 是否必填（默认 false）
#### Scenario: Extract single variable
- **WHEN** 用户配置提取规则 `source_path=$.data.title, key=taskTitle, name=任务标题`
- **AND** 上游节点输出 `{"data": {"title": "实现登录功能"}}`
- **THEN** 系统 SHALL 创建全局变量 `taskTitle`，值为 `实现登录功能`
#### Scenario: Extract nested field
- **WHEN** 用户配置提取规则 `source_path=$.work_item.fields.custom_field_1`
- **AND** 上游节点输出包含该嵌套路径
- **THEN** 系统 SHALL 正确提取嵌套字段的值
#### Scenario: Extract from array with filter
- **WHEN** 用户配置提取规则 `source_path=$.fields[?(@.key=='description')].value`
- **AND** 上游节点输出 `{"fields": [{"key": "title", "value": "标题"}, {"key": "description", "value": "需求描述"}]}`
- **THEN** 系统 SHALL 提取值 `需求描述`
#### Scenario: Required variable missing
- **WHEN** 提取规则标记为 `required=true`
- **AND** 指定路径在输入数据中不存在或值为空
- **THEN** 节点执行 SHALL 失败
- **AND** 错误信息 SHALL 明确指出缺失的变量名称
#### Scenario: Optional variable missing
- **WHEN** 提取规则标记为 `required=false`
- **AND** 指定路径在输入数据中不存在
- **THEN** 节点执行 SHALL 继续
- **AND** 该变量 SHALL 不被注册到全局变量中
---
### Requirement: AI Variable Extractor Node
系统 SHALL 提供「AI 变量提取」节点类型，使用 AI 从非结构化文本中智能提取变量。
节点配置 SHALL 包含：
- `input_source`: 输入文本的来源（上游节点输出路径或直接文本）
- `variables`: 目标变量定义列表，每个变量包含：
 - `key`: 变量标识符
 - `name`: 变量显示名称
 - `desc`: 变量描述，用于指导 AI 提取（必填）
 - `required`: 是否必填
- `additional_prompt`: 额外的提取指导（选填）
#### Scenario: AI extract from description
- **WHEN** 用户配置目标变量 `key=techStack, desc=文本中提到的技术栈列表`
- **AND** 输入文本为 `本项目使用 Vue 3 和 Django 开发，数据库采用 PostgreSQL`
- **THEN** AI SHALL 提取并返回 `Vue 3, Django, PostgreSQL` 作为 `techStack` 变量值
#### Scenario: AI extraction failure
- **WHEN** AI 无法从输入文本中提取指定变量
- **AND** 该变量标记为 `required=true`
- **THEN** 节点执行 SHALL 失败
- **AND** 错误信息 SHALL 包含 AI 的原始响应以便调试
#### Scenario: AI partial extraction
- **WHEN** AI 成功提取部分变量但未能提取其他变量
- **AND** 未提取到的变量均为 `required=false`
- **THEN** 节点执行 SHALL 成功
- **AND** 仅成功提取的变量 SHALL 被注册
---
### Requirement: Global Variable Template Syntax
系统 SHALL 在所有支持模板语法的节点配置字段中解析 `{{ global.<key> }}` 语法。
#### Scenario: Use variable in AI Prompt
- **WHEN** AI Prompt 节点的 system_prompt 配置为 `请根据以下需求描述编写代码：{{ global.requirementsDescription }}`
- **AND** 全局变量 `requirementsDescription` 值为 `实现用户登录功能`
- **THEN** 实际发送给 AI 的 prompt SHALL 为 `请根据以下需求描述编写代码：实现用户登录功能`
#### Scenario: Reference undefined variable
- **WHEN** 模板中引用了未定义的全局变量 `{{ global.undefined_var }}`
- **THEN** 系统 SHALL 保留原始模板字符串 `{{ global.undefined_var }}`
- **AND** 系统 SHALL 记录一条 warning 日志
---
### Requirement: Variable Autocomplete in Frontend
前端 SHALL 在支持模板语法的输入框中提供全局变量自动补全功能。
#### Scenario: Trigger autocomplete
- **WHEN** 用户在配置输入框中输入 `{{`
- **THEN** 系统 SHALL 显示可用的全局变量列表
- **AND** 列表 SHALL 显示变量的 `name` 和 `desc`
#### Scenario: Insert variable
- **WHEN** 用户从自动补全列表中选择一个变量
- **THEN** 系统 SHALL 在光标位置插入 `{{ global.<key> }}` 语法
