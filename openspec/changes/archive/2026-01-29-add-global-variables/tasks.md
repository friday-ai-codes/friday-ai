# Tasks: Add Global Variables System
## 1. Backend - Global Variables Infrastructure
- [x] 1.1 在 `WorkflowExecution.context` 中定义 `global_variables` 结构
 - 存储位置：`context['global_variables']`
 - 每个变量包含：`key`, `name`, `desc`, `value`, `required`, `source_node`
- [x] 1.2 定义 `GlobalVariable` TypedDict 数据结构 (`server/workflows/nodes/base.py:15`)
- [x] 1.3 扩展 `ExecutionContext` 类，添加方法：
 - `set_global_variable(key, name, value, desc=None, required=False)`
 - `get_global_variable(key) -> Optional[Any]`
 - `get_all_global_variables -> dict`
- [x] 1.4 更新 `render_template` 方法，确保 `{{ global.xxx }}` 语法正确解析全局变量
- [x] 1.5 添加 `jsonpath-ng` 依赖到 `pyproject.toml`
## 2. Backend - Variable Extractor Node
- [x] 2.1 创建 `VariableExtractorNode` 节点类 (`server/workflows/nodes/data/variable_extractor.py`)
- [x] 2.2 定义节点元数据：
 - `node_type`: `variable_extractor`
 - `category`: `DATA`
 - `inputs`: 接收上游节点输出
 - `outputs`: 输出提取的变量摘要
- [x] 2.3 定义 `config_schema`
- [x] 2.4 实现 `execute` 逻辑：
 - 使用 `jsonpath-ng` 解析 JSONPath 表达式
 - 从 `input_data` 中提取值
 - 调用 `context.set_global_variable` 注册变量
- [x] 2.5 实现 required 校验：必填变量为空时抛出 `NodeExecutionError`
- [x] 2.6 注册节点到 `NodeRegistry`
## 3. Backend - AI Variable Extractor Node
- [x] 3.1 创建 `AIVariableExtractorNode` 节点类 (`server/workflows/nodes/ai/variable_extractor.py`)
- [x] 3.2 定义节点元数据：
 - `node_type`: `ai_variable_extractor`
 - `category`: `AI`
- [x] 3.3 定义 `config_schema`
- [x] 3.4 实现 AI 提示词模板：
 - 要求返回 JSON 格式 `{"variables": {"key": "value"}}`
 - 包含变量描述指导 AI 提取
- [x] 3.5 实现 `execute` 逻辑：
 - 调用 LLM 解析输入文本
 - 解析 JSON 响应
 - 注册提取的变量到全局变量
- [x] 3.6 实现错误处理：AI 返回格式异常时的降级策略
- [x] 3.7 注册节点到 `NodeRegistry`
## 4. Backend - Event Schema Definitions
- [x] 4.1 创建飞书事件 Schema 定义文件 (`server/workflows/schemas/__init__.py`)
- [x] 4.2 定义各事件类型的 JSON Schema：
 - `WorkitemCreateEvent`: `id`, `name`, `work_item_type_key`, `fields`
 - `WorkitemStatusEvent`: `cur_work_item_status`, `pre_work_item_status`
 - `WorkFlowNodeStatusEvent`: `status_change_type`
 - `WorkitemCommentEvent`: `comment`
 - `WorkitemUpdateEvent`: `changed_fields`
- [x] 4.3 创建 API 端点返回事件 Schema (`get_event_schema`, `get_all_event_schemas`)
- [x] 4.4 定义常用字段快捷映射（基于 `KeyFields`）：
 - 需求文档: `$.payload.fields[?(@.key=='field_bcff9b')].value`
 - 技术方案: `$.payload.fields[?(@.key=='field_3f6667')].value`
 - 描述: `$.payload.fields[?(@.key=='description')].value`
## 5. Frontend - Type Definitions
- [x] 5.1 更新 `web/src/types/workflow/schemas.ts`：
 - 添加 `VariableExtractorNodeConfig` 类型
 - 添加 `AIVariableExtractorNodeConfig` 类型
 - 添加 `GlobalVariable` 类型
 - 添加 `ExtractionRule` 类型
- [x] 5.2 更新 `web/src/types/workflow/registry.ts`，注册新节点组件
- [x] 5.3 添加飞书事件 Schema 类型定义
## 6. Frontend - Variable Extractor Config (可视化路径选择器)
- [x] 6.1 创建 `VariableExtractorConfig.vue` 配置面板
- [x] 6.2 实现帮助文档对话框（JSONPath 语法说明）
- [x] 6.3 实现事件类型选择器（预设选项）
- [x] 6.4 实现右侧提取规则表单：
 - 变量名 (name) 输入框
 - Key 输入框（自动根据 name 生成建议）
 - 路径显示（只读，由左侧点击生成）
 - 描述 (desc) 输入框
 - 必填 (required) 开关
- [x] 6.5 实现常用字段快捷选项面板：
 - 需求文档、技术方案、描述、工作项名称、工作项ID
 - 一键添加到提取规则
- [x] 6.6 支持多条提取规则：添加/删除
## 7. Frontend - AI Variable Extractor Config
- [x] 7.1 创建 `AIVariableExtractorConfig.vue` 配置面板
- [x] 7.2 实现输入源选择：
 - 选择上游节点输出路径
 - 或直接输入模板字符串
- [x] 7.3 实现目标变量列表表单：
 - 添加/删除变量定义
 - 每个变量：key, name, desc (必填), required
- [x] 7.4 添加额外提取指导 (additional_prompt) 文本区域
## 8. Frontend - Variable Picker
- [x] 8.1 创建可复用的 `VariablePicker.vue` 组件
- [x] 8.2 实现变量列表展示：
 - 显示 `name` 和 `desc`
 - 按来源分组（trigger/global/input/nodes）
- [x] 8.3 实现插入逻辑：选择后插入 `{{ path.to.value }}`
- [x] 8.4 支持预设常用变量（无上下文时显示）
## 9. Frontend - Node Components
- [x] 9.1 创建 `VariableExtractorNode.vue` 节点展示组件
 - 显示已配置的变量列表摘要
 - 显示必填变量标识
- [x] 9.2 创建 `AIVariableExtractorNode.vue` 节点展示组件
 - 显示 AI 图标
 - 显示目标变量数量
