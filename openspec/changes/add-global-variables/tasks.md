# Tasks: Add Global Variables System
## 1. Backend - Global Variables Infrastructure
- 1.1 在 `WorkflowExecution.context` 中定义 `global_variables` 结构
 - 存储位置：`context['global_variables']`
 - 每个变量包含：`key`, `name`, `desc`, `value`, `required`, `source_node`
- 1.2 定义 `GlobalVariable` TypedDict 数据结构 (`server/workflows/models/types.py`)
- 1.3 扩展 `ExecutionContext` 类，添加方法：
 - `set_global_variable(key, name, value, desc=None, required=False)`
 - `get_global_variable(key) -> Optional[Any]`
 - `get_all_global_variables -> dict`
- 1.4 更新 `render_template` 方法，确保 `{{ global.xxx }}` 语法正确解析全局变量
- 1.5 添加 `jsonpath-ng` 依赖到 `pyproject.toml`
## 2. Backend - Variable Extractor Node
- 2.1 创建 `VariableExtractorNode` 节点类 (`server/workflows/nodes/data/variable_extractor.py`)
- 2.2 定义节点元数据：
 - `node_type`: `variable_extractor`
 - `category`: `DATA`
 - `inputs`: 接收上游节点输出
 - `outputs`: 输出提取的变量摘要
- 2.3 定义 `config_schema`：
 ```json
 {
 "extractions": [{
 "source_path": "JSONPath 表达式",
 "key": "变量标识符",
 "name": "显示名称",
 "desc": "描述（选填）",
 "required": false
 }]
 }
 ```
- 2.4 实现 `execute` 逻辑：
 - 使用 `jsonpath-ng` 解析 JSONPath 表达式
 - 从 `input_data` 中提取值
 - 调用 `context.set_global_variable` 注册变量
- 2.5 实现 required 校验：必填变量为空时抛出 `NodeExecutionError`
- 2.6 注册节点到 `NodeRegistry`
## 3. Backend - AI Variable Extractor Node
- 3.1 创建 `AIVariableExtractorNode` 节点类 (`server/workflows/nodes/ai/variable_extractor.py`)
- 3.2 定义节点元数据：
 - `node_type`: `ai_variable_extractor`
 - `category`: `AI`
- 3.3 定义 `config_schema`：
 ```json
 {
 "input_source": "输入文本来源路径",
 "variables": [{
 "key": "变量标识符",
 "name": "显示名称",
 "desc": "提取描述（指导 AI）",
 "required": false
 }],
 "additional_prompt": "额外提取指导（选填）"
 }
 ```
- 3.4 实现 AI 提示词模板：
 - 要求返回 JSON 格式 `{"variables": {"key": "value"}}`
 - 包含变量描述指导 AI 提取
- 3.5 实现 `execute` 逻辑：
 - 调用 LLM 解析输入文本
 - 解析 JSON 响应
 - 注册提取的变量到全局变量
- 3.6 实现错误处理：AI 返回格式异常时的降级策略
- 3.7 注册节点到 `NodeRegistry`
## 4. Backend - Event Schema Definitions
- 4.1 创建飞书事件 Schema 定义文件 (`server/workflows/schemas/feishu_events.py`)
- 4.2 定义各事件类型的 JSON Schema：
 - `WorkitemCreateEvent`: `id`, `name`, `work_item_type_key`, `fields`
 - `WorkitemStatusEvent`: `cur_work_item_status`, `pre_work_item_status`
 - `WorkFlowNodeStatusEvent`: `status_change_type`
 - `WorkitemCommentEvent`: `comment`
 - `WorkitemUpdateEvent`: `changed_fields`
- 4.3 创建 API 端点返回事件 Schema (`GET /api/workflows/schemas/events/{event_type}/`)
- 4.4 定义常用字段快捷映射（基于 `KeyFields`）：
 - 需求文档: `$.payload.fields[?(@.key=='field_bcff9b')].value`
 - 技术方案: `$.payload.fields[?(@.key=='field_3f6667')].value`
 - 描述: `$.payload.fields[?(@.key=='description')].value`
## 5. Frontend - Type Definitions
- 5.1 更新 `web/src/types/workflow/schemas.ts`：
 - 添加 `VariableExtractorNodeConfig` 类型
 - 添加 `AIVariableExtractorNodeConfig` 类型
 - 添加 `GlobalVariable` 类型
 - 添加 `ExtractionRule` 类型
- 5.2 更新 `web/src/types/workflow/registry.ts`，注册新节点组件
- 5.3 添加飞书事件 Schema 类型定义
## 6. Frontend - Variable Extractor Config (可视化路径选择器)
- 6.1 创建 `VariableExtractorConfig.vue` 配置面板
- 6.2 实现左侧数据结构树形预览组件 `JsonSchemaTree.vue`：
 - 递归渲染 JSON 结构
 - 支持展开/折叠
 - 点击字段生成 JSONPath
 - 数组字段显示 `[数组]` 标识
- 6.3 实现事件类型选择器：
 - 下拉选择触发事件类型
 - 切换时加载对应 Schema
- 6.4 实现右侧提取规则表单：
 - 变量名 (name) 输入框
 - Key 输入框（自动根据 name 生成建议）
 - 路径显示（只读，由左侧点击生成）
 - 描述 (desc) 输入框
 - 必填 (required) 开关
- 6.5 实现数组过滤条件配置弹窗：
 - 选择过滤字段（如 `key`）
 - 选择操作符（`==`, `!=`, `contains`）
 - 输入过滤值
 - 生成 `[?(@.key=='xxx')]` 语法
- 6.6 实现常用字段快捷选项面板：
 - 需求文档、技术方案、描述、工作项名称、工作项ID
 - 一键添加到提取规则
- 6.7 实现实时预览功能：
 - 调用 API 获取历史执行数据
 - 显示 JSONPath 提取结果预览
- 6.8 支持多条提取规则：添加/删除/排序
## 7. Frontend - AI Variable Extractor Config
- 7.1 创建 `AIVariableExtractorConfig.vue` 配置面板
- 7.2 实现输入源选择：
 - 选择上游节点输出路径
 - 或直接输入模板字符串
- 7.3 实现目标变量列表表单：
 - 添加/删除变量定义
 - 每个变量：key, name, desc (必填), required
- 7.4 添加额外提取指导 (additional_prompt) 文本区域
- 7.5 实现 AI 提取预览（可选）：测试提取效果
## 8. Frontend - Variable Autocomplete
- 8.1 创建可复用的 `VariableAutocomplete.vue` 组件
- 8.2 实现触发逻辑：输入 `{{` 时弹出变量选择器
- 8.3 实现变量列表展示：
 - 显示 `name` 和 `desc`
 - 按来源节点分组
- 8.4 实现插入逻辑：选择后插入 `{{ global.<key> }}`
- 8.5 集成到 `AIPromptConfig.vue` 的 system_prompt 和 user_prompt 输入框
- 8.6 集成到其他支持模板语法的配置组件
## 9. Frontend - Node Components
- 9.1 创建 `VariableExtractorNode.vue` 节点展示组件
 - 显示已配置的变量列表摘要
 - 显示必填变量标识
- 9.2 创建 `AIVariableExtractorNode.vue` 节点展示组件
 - 显示 AI 图标
 - 显示目标变量数量
## 10. Integration & Testing
- 10.1 编写 `VariableExtractorNode` 单元测试：
 - 简单路径提取
 - 嵌套路径提取
 - 数组条件过滤
 - 必填变量缺失
 - 可选变量缺失
- 10.2 编写 `AIVariableExtractorNode` 单元测试：
 - 正常提取
 - AI 返回格式异常
 - 部分提取成功
- 10.3 编写 `ExecutionContext` 全局变量方法测试
- 10.4 编写 `render_template` 全局变量解析测试
- 10.5 编写端到端测试：飞书工作项 → 变量提取 → AI Prompt 完整链路
- 10.6 前端组件测试：`JsonSchemaTree`, `VariableAutocomplete`
## 11. Documentation & Migration
- 11.1 更新 API 文档：新增节点类型说明
- 11.2 更新工作流编辑器使用文档
- 11.3 添加 JSONPath 语法参考文档
- 11.4 生成并应用数据库迁移脚本（如有 model 变更）
