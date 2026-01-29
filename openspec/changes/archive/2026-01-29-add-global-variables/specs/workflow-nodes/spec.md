# Workflow Nodes - Global Variables
## ADDED Requirements
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
