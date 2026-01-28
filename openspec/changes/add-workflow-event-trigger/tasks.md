# Implementation Tasks
> 本任务清单设计为 AI Agent 顺序执行。每个任务包含明确的输入、输出和验证条件。
---
## Phase: Data Models (后端基础设施)
### 1.1 Create WorkflowTrigger Model
- [x] **1.1.1** 创建文件 `server/workflows/models/trigger.py`
- [x] **1.1.2** 定义 `TriggerEventType` 枚举类，包含以下选项:
 - `WorkitemCreateEvent` - 工作项创建
 - `WorkitemStatusEvent` - 状态变更
 - `WorkitemCommentEvent` - 评论事件
 - `WorkitemUpdateEvent` - 字段更新
 - `WorkFlowNodeStatusEvent` - 节点流转
- [x] **1.1.3** 定义 `WorkflowTrigger` 模型，字段:
 - `id`: UUIDField (primary_key)
 - `workflow`: ForeignKey → Workflow (related_name="triggers")
 - `event_type`: CharField (choices=TriggerEventType)
 - `filter_config`: JSONField (default=dict) - 过滤条件
 - `input_schema`: JSONField (default=dict) - JSON Schema 校验
 - `is_active`: BooleanField (default=True)
 - `created_at`, `updated_at`: DateTimeField
- [x] **1.1.4** 在 `server/workflows/models/__init__.py` 中导出新模型
**验证**: 运行 `python manage.py check` 无错误
### 1.2 Extend WorkflowExecution Model
- [x] **1.2.1** 编辑 `server/workflows/models/execution.py`
- [x] **1.2.2** 添加字段:
 - `is_manual_trigger`: BooleanField (default=False)
 - `trigger_log`: ForeignKey → "feishu.TriggerLog" (null=True, blank=True, on_delete=SET_NULL)
 - `global_params`: JSONField (default=dict) - 全局参数
- [x] **1.2.3** 添加方法:
 - `get_global_param(key: str, default=None) -> Any`
 - `set_global_param(key: str, value: Any) -> None`
 - `update_global_params(data: dict) -> None`
**验证**: 运行 `python manage.py check` 无错误 ✅
### 1.3 Create CodingTask Model
- [x] **1.3.1** 创建文件 `server/workflows/models/coding_task.py`
- [x] **1.3.2** 定义 `CodingTaskStatus` 枚举类:
 - `pending`, `planning`, `plan_review`, `executing`, `code_review`, `merged`, `failed`
- [x] **1.3.3** 定义 `CodingTask` 模型，字段:
 - `id`: UUIDField (primary_key)
 - `workflow_execution`: ForeignKey → WorkflowExecution (related_name="coding_tasks")
 - `repository`: ForeignKey → "repositories.Repository" (on_delete=CASCADE)
 - `name`: CharField (max_length=200)
 - `prompt`: TextField
 - `description`: TextField (blank=True)
 - `status`: CharField (choices=CodingTaskStatus, default="pending")
 - `session_id`: CharField (max_length=100, blank=True)
 - `plan_output`: TextField (blank=True)
 - `human_feedback`: TextField (blank=True)
 - `branch_name`: CharField (max_length=200, blank=True)
 - `commit_sha`: CharField (max_length=40, blank=True)
 - `pr_url`: URLField (blank=True)
 - `error_message`: TextField (blank=True)
 - `retry_count`: PositiveIntegerField (default=0)
 - `created_at`, `updated_at`: DateTimeField
- [x] **1.3.4** 在 `__init__.py` 中导出
**验证**: 运行 `python manage.py check` 无错误 ✅
### 1.4 Database Migration
- [x] **1.4.1** 运行 `python manage.py makemigrations workflows`
- [x] **1.4.2** 检查生成的迁移文件内容正确
- [x] **1.4.3** 运行 `python manage.py migrate`
- [x] **1.4.4** 验证数据库表已创建: `workflow_triggers`, 扩展的 `workflow_executions`, `coding_tasks`
**验证**: `python manage.py showmigrations workflows` 显示所有迁移已应用 ✅
---
## Phase: Node Implementation (节点实现)
### 2.1 Extend ExecutionContext
- [x] **2.1.1** 编辑 `server/workflows/nodes/base.py`
- [x] **2.1.2** 在 `ExecutionContext` dataclass 中添加:
 - `trigger_data: dict = field(default_factory=dict)` - 触发器数据
- [x] **2.1.3** 添加方法 `get_trigger_data(key: str, default=None) -> Any`
- [x] **2.1.4** 添加方法 `get_global_param(key: str, default=None) -> Any`:
 - 从 `workflow_context.get("global_params", {})` 读取
- [x] **2.1.5** 添加方法 `set_global_param(key: str, value: Any) -> None`:
 - 更新 `workflow_execution.global_params` 并保存
- [x] **2.1.6** 扩展 `render_template` 方法支持:
 - `{{global.key}}` - 全局参数
 - `{{trigger.key}}` - 触发器数据
**验证**: `python manage.py check` 通过 ✅
### 2.2 Implement FeishuEventTriggerNode
- [x] **2.2.1** 创建目录 `server/workflows/nodes/triggers/` (已存在)
- [x] **2.2.2** 创建 `server/workflows/nodes/triggers/__init__.py` (已存在)
- [x] **2.2.3** 创建 `server/workflows/nodes/triggers/feishu_event.py`
- [x] **2.2.4** 定义 `FeishuEventTriggerNode(BaseNode)`:
 - `node_type = "feishu_event_trigger"`
 - `display_name = "飞书事件触发"`
 - `category = NodeCategory.TRIGGER`
 - `icon = "webhook"`
- [x] **2.2.5** 定义 `config_schema`:
 ```python
 {
 "type": "object",
 "properties": {
 "event_types": {"type": "array", "items": {"type": "string"}},
 "filter_project_key": {"type": "string"},
 "filter_work_item_type": {"type": "string", "enum": ["story", "task", "bug", ""]},
 "filter_status": {"type": "string"}
 },
 "required": ["event_types"]
 }
 ```
- [x] **2.2.6** 定义输出端口: `default` (event_type, work_item_id, project_key, payload)
- [x] **2.2.7** 实现 `async execute`: 从 `context.input_data` 提取事件数据
- [x] **2.2.8** 添加 `@register_node` 装饰器
**验证**: 节点出现在 NodeRegistry 中 ✅ `node_type_registered node_type=feishu_event_trigger`
### 2.3 Implement FetchWorkItemNode
- [x] **2.3.1** 创建目录 `server/workflows/nodes/integrations/` (已存在)
- [x] **2.3.2** 创建 `server/workflows/nodes/integrations/__init__.py` (已存在)
- [x] **2.3.3** 创建 `server/workflows/nodes/integrations/feishu_workitem.py`
- [x] **2.3.4** 定义 `FetchWorkItemNode(BaseNode)`:
 - `node_type = "fetch_work_item"`
 - `display_name = "获取工作项详情"`
 - `category = NodeCategory.INTEGRATION`
- [x] **2.3.5** 定义 `config_schema`:
 - `work_item_id`: string (支持模板)
 - `work_item_type`: string (default: "story")
 - `extract_fields`: array (default: ["description", "prd_url", "tech_doc_url"])
 - `set_global_params`: boolean (default: true)
 - `include_project_info`: boolean (default: true)
 - `include_repositories`: boolean (default: true)
- [x] **2.3.6** 实现 `async execute`:
 1. 使用 `context.render_template` 解析 work_item_id
 2. 获取 project 从 context
 3. 调用 `FeishuClient.get_work_item` 获取详情
 4. 提取预设字段 (prd_url, description, tech_doc_url)
 5. 如果 `include_repositories=True`, 获取项目关联的仓库列表
 6. 如果 `set_global_params=True`, 调用 `context.set_global_param` 设置全局参数
 7. 返回 NodeResult
**验证**: 节点出现在 NodeRegistry 中 ✅ `node_type_registered node_type=fetch_work_item`
### 2.4 Implement AIPromptNode
- [x] **2.4.1** 创建目录 `server/workflows/nodes/ai/` (已存在)
- [x] **2.4.2** 创建 `server/workflows/nodes/ai/__init__.py` (已存在，已更新导出)
- [x] **2.4.3** 创建 `server/workflows/nodes/ai/prompt.py`
- [x] **2.4.4** 定义 `AIPromptNode(BaseNode)`:
 - `node_type = "ai_prompt"`
 - `display_name = "AI Prompt"`
 - `category = NodeCategory.AI`
- [x] **2.4.5** 定义 `config_schema`:
 - `system_prompt`: string
 - `user_prompt`: string (支持模板变量)
 - `model`: string (enum: claude-3-opus, claude-3-sonnet, etc.)
 - `temperature`: number (0-2, default: 0.7)
 - `max_tokens`: integer (default: 4096)
 - `output_format`: string (enum: text, json, markdown)
- [x] **2.4.6** 实现 `async execute`:
 1. 渲染 system_prompt 和 user_prompt 模板
 2. 从 project 获取 API key
 3. 调用 LLM 服务 (支持 Anthropic 和 OpenAI)
 4. 返回响应文本和 usage 信息
**验证**: 节点出现在 NodeRegistry 中 ✅ `node_type_registered node_type=ai_prompt`
### 2.5 Implement AICodingDispatcherNode
- [x] **2.5.1** 创建 `server/workflows/nodes/ai/coding_dispatcher.py`
- [x] **2.5.2** 定义 `AICodingDispatcherNode(BaseNode)`:
 - `node_type = "ai_coding_dispatcher"`
 - `display_name = "AI 编码指派器"`
 - `category = NodeCategory.AI`
- [x] **2.5.3** 定义 `config_schema`:
 - `analysis_model`: string (default: "claude-3-5-sonnet-20241022")
 - `max_tasks`: integer (1-20, default: 5)
 - `task_granularity`: string (enum: fine, medium, coarse)
 - `include_tests`: boolean (default: true)
 - `auto_assign_repos`: boolean (default: true)
- [x] **2.5.4** 实现 `async execute`:
 1. 从 `context.get_global_param` 读取: prd_url, description, tech_doc_url, repositories
 2. 实现 `_fetch_document(url)`: 抓取需求文档内容
 3. 实现 `_build_analysis_prompt`: 构建分析 Prompt
 4. 调用 LLM 分析需求，判断涉及哪些仓库
 5. 为每个仓库生成编码任务 Prompt
 6. 创建 `CodingTask` 记录
 7. 返回 tasks 列表和 task_count
**验证**: 节点出现在 NodeRegistry 中 ✅ `node_type_registered node_type=ai_coding_dispatcher`
---
## Phase: Trigger Bridge (触发器桥接)
### 3.1 Extend FeishuWorkflowBridge
- [x] **3.1.1** 编辑 `server/feishu/workflow_bridge.py`
- [x] **3.1.2** 添加方法 `async dispatch_event(event_type, project, payload, trigger_log) -> list[WorkflowExecution]`:
 1. 查询匹配的 `WorkflowTrigger` (event_type + is_active + workflow.project)
 2. 对每个触发器调用 `_matches_filter` 检查过滤条件
 3. 对每个触发器调用 `_validate_input` 校验 input_schema
 4. 调用 `_start_workflow` 启动工作流执行
 5. 返回执行列表
- [x] **3.1.3** 实现 `_matches_filter(filter_config: dict, payload: dict) -> bool`:
 - 检查 payload 是否满足 filter_config 中的所有条件
- [x] **3.1.4** 实现 `_validate_input(payload: dict, schema: dict) -> list[str]`:
 - 使用 `jsonschema.validate` 校验
 - 返回错误列表
- [x] **3.1.5** 实现 `async _start_workflow(workflow, event_type, payload, trigger_log, project) -> WorkflowExecution`:
 - 准备 input_data: event_type, event_uuid, work_item_id, project_key, payload
 - 准备 initial_context: project_id, trigger_type, event_type
 - 调用 WorkflowEngine.start_execution
 - 关联 trigger_log
 - 返回 execution
**验证**: `python manage.py check` 通过 ✅
### 3.2 Integrate into Webhook View
- [x] **3.2.1** 编辑 `server/feishu/views.py`
- [x] **3.2.2** 在 `FeishuWebhookView.post` 中，创建 trigger_log 后添加:
 ```python
 # 分发到工作流系统
 bridge = FeishuWorkflowBridge
 executions = await bridge.dispatch_event(event_type, project, payload, trigger_log)
 if executions:
 logger.info("workflows_triggered", event_type=event_type, count=len(executions))
 ```
- [x] **3.2.3** 处理异步调用 (使用 `run_async` 包装)
**验证**: `python manage.py check` 通过 ✅
### 3.3 Implement Manual Trigger Entry
- [x] **3.3.1** 在 `server/feishu/workflow_bridge.py` 添加方法:
 ```python
 async def manual_trigger(workflow, event_type, input_data, triggered_by) -> WorkflowExecution
 ```
- [x] **3.3.2** 实现逻辑:
 1. 标记 `is_manual_trigger = True`
 2. 添加 `_manual_trigger`, `_triggered_by`, `_triggered_at` 到 input_data
 3. 使用 workflow 的 input_schema 校验输入
 4. 调用 WorkflowEngine.start_execution
**验证**: `python manage.py check` 通过 ✅
---
## Phase: Backend API (后端 API)
### 4.1 Trigger Management API
- [x] **4.1.1** 编辑 `server/workflows/api/serializers.py`:
 - 创建 `WorkflowTriggerSerializer`
 - 创建 `WorkflowTriggerCreateSerializer`
- [x] **4.1.2** 编辑 `server/workflows/api/views.py`:
 - 创建 `WorkflowTriggerViewSet` (ModelViewSet)
 - 过滤 queryset 按 workflow_id
- [x] **4.1.3** 编辑 `server/workflows/urls.py`:
 - 添加嵌套路由: `workflows/<uuid:workflow_id>/triggers/`
**验证**: `python manage.py check` 通过 ✅
### 4.2 Manual Trigger API
- [x] **4.2.1** 创建 `ManualTriggerSerializer`:
 - `event_type`: ChoiceField (可选)
 - `input_data`: JSONField
- [x] **4.2.2** 创建 `ManualTriggerView(APIView)`:
 - POST `/api/workflows/{id}/execute/`
 - 调用 `FeishuWorkflowBridge.manual_trigger`
 - 返回 execution_id 和 status
- [x] **4.2.3** 添加 URL 路由
**验证**: `python manage.py check` 通过 ✅
### 4.3 Execution Context API
- [x] **4.3.1** 创建 `ExecutionContextSerializer`:
 - `execution_id`, `status`, `progress`
 - `global_params`, `node_outputs`, `trigger_data`
 - `is_manual_trigger`
- [x] **4.3.2** 创建 `ExecutionContextView(APIView)`:
 - GET `/api/workflows/executions/{id}/context/`
 - 从 WorkflowExecution 构建上下文快照
- [x] **4.3.3** 添加 URL 路由
**验证**: `python manage.py check` 通过 ✅
### 4.4 Node Schema API
- [x] **4.4.1** 创建 `NodeSchemaListView(APIView)`:
 - GET `/api/workflows/nodes/schemas/`
 - 从 NodeRegistry 获取所有节点 Schema
 - 返回节点列表
- [x] **4.4.2** 添加 URL 路由
**验证**: `python manage.py check` 通过 ✅
### 4.5 CodingTask API
- [x] **4.5.1** 创建 `CodingTaskSerializer`, `CodingTaskListSerializer`, `CodingTaskUpdateSerializer`
- [x] **4.5.2** 创建 `CodingTaskViewSet`:
 - 列表: GET `/api/workflows/executions/{id}/coding-tasks/`
 - 详情: GET `/api/workflows/coding-tasks/{id}/`
 - 更新: PATCH `/api/workflows/coding-tasks/{id}/`
 - 审批操作: `approve_plan`, `reject_plan`, `approve_code`, `reject_code`
- [x] **4.5.3** 添加 URL 路由
**验证**: `python manage.py check` 通过 ✅
---
## Phase: Frontend Node Components (前端节点组件)
### 5.1 Add Node Type Definitions
- [x] **5.1.1** 编辑 `web/src/types/index.ts`
- [x] **5.1.2** 添加类型定义:
 - FeishuEventTriggerNodeData
 - FetchWorkItemNodeData
 - AIPromptNodeData
 - AICodingDispatcherNodeData
 - TriggerEventType
 - WorkflowTrigger / WorkflowTriggerCreate
 - CodingTask / CodingTaskStatus
 - ExecutionContext
 - ManualTriggerRequest / ManualTriggerResponse
- [x] **5.1.3** 扩展 `NodeType` 联合类型
**验证**: TypeScript 编译无错误 ✅
### 5.2 Create FeishuEventTriggerNode Component
- [x] **5.2.1** 创建 `web/src/components/workflow/nodes/FeishuEventTriggerNode.vue`
- [x] **5.2.2** 基于 `BaseNodeComponent` 创建
- [x] **5.2.3** 设置触发器样式: 无输入 Handle，只有输出 Handle
- [x] **5.2.4** 显示事件类型图标和已配置的事件类型列表
- [x] **5.2.5** 在 WorkflowCanvas 中注册自定义节点
**验证**: 节点可拖拽到画布 ✅
### 5.3 Create FetchWorkItemNode Component
- [x] **5.3.1** 创建 `web/src/components/workflow/nodes/FetchWorkItemNode.vue`
- [x] **5.3.2** 显示 Integration 类型样式
- [x] **5.3.3** 显示已配置的提取字段列表
- [x] **5.3.4** 注册自定义节点
**验证**: 节点可拖拽到画布 ✅
### 5.4 Create AI Node Components
- [x] **5.4.1** 创建 `web/src/components/workflow/nodes/AIPromptNode.vue`
- [x] **5.4.2** 显示 AI 类型样式，显示模型信息
- [x] **5.4.3** 创建 `web/src/components/workflow/nodes/AICodingDispatcherNode.vue`
- [x] **5.4.4** 显示最大任务数配置
- [x] **5.4.5** 注册自定义节点
**验证**: 节点可拖拽到画布 ✅
---
## Phase: Frontend Node Config Panels (节点配置面板)
### 6.1 Create FeishuEventTriggerConfig
- [x] **6.1.1** 创建目录 `web/src/components/workflow/config/`
- [x] **6.1.2** 创建 `FeishuEventTriggerConfig.vue`
- [x] **6.1.3** 实现表单:
 - 事件类型多选下拉框
 - 项目 Key 过滤输入框
 - 工作项类型选择
 - 状态过滤输入框
**验证**: 配置可保存并回显 ✅
### 6.2 Create FetchWorkItemConfig
- [x] **6.2.1** 创建 `FetchWorkItemConfig.vue`
- [x] **6.2.2** 实现表单:
 - work_item_id 输入框 (带变量提示)
 - 工作项类型下拉框
 - 提取字段多选 (预设选项)
 - "设置为全局参数" 开关
 - "包含仓库信息" 开关
**验证**: 配置可保存并回显 ✅
### 6.3 Create AIPromptConfig
- [x] **6.3.1** 创建 `AIPromptConfig.vue`
- [x] **6.3.2** 实现表单:
 - System Prompt 多行文本框
 - User Prompt 多行文本框 (带变量提示)
 - 模型选择下拉框
 - 温度滑块 (0-2)
 - 最大 Token 数输入框
 - 输出格式选择
**验证**: 配置可保存并回显 ✅
### 6.4 Create AICodingDispatcherConfig
- [x] **6.4.1** 创建 `AICodingDispatcherConfig.vue`
- [x] **6.4.2** 实现表单:
 - 分析模型选择
 - 最大任务数输入框
 - 任务粒度选择
 - "包含测试任务" 开关
 - "自动分配仓库" 开关
**验证**: 配置可保存并回显 ✅
---
## Phase: Frontend Node Palette (节点面板更新)
### 7.1 Update NodePalette Categories
- [x] **7.1.1** 编辑 `web/src/components/workflow/NodePalette.vue`
- [x] **7.1.2** 在触发器分类添加: 飞书事件触发
- [x] **7.1.3** 在集成分类添加: 获取工作项详情
- [x] **7.1.4** 在 AI 分类添加: AI Prompt, AI 编码指派器
- [x] **7.1.5** 设置节点图标和描述
**验证**: 节点面板显示新节点 ✅
### 7.2 Dynamic Schema Loading
- [x] **7.2.1** 编辑 `web/src/api/workflow.ts`
- [x] **7.2.2** 添加 `getNodeSchemas: Promise<NodeSchema>`
- [x] **7.2.3** 添加触发器管理 API (listTriggers, createTrigger, updateTrigger, deleteTrigger)
- [x] **7.2.4** 添加执行相关 API (executeWorkflow, getExecutionContext)
- [x] **7.2.5** 添加 CodingTask API (listCodingTasks, getCodingTask, approve/reject)
**验证**: API 模块已创建并导出 ✅
---
## Phase: Frontend Context Panel (上下文面板)
### 8.1 Create ContextInspector Component
- [x] **8.1.1** 创建 `web/src/components/workflow/ContextInspector.vue`
- [x] **8.1.2** 实现可折叠面板布局
- [x] **8.1.3** 分区显示:
 - 触发器数据 (trigger_data)
 - 全局参数 (global_params)
 - 节点输出 (node_outputs)
 - 输入数据 (input_data)
- [x] **8.1.4** 支持 JSON 格式化展示
- [x] **8.1.5** 支持复制变量引用路径
**验证**: 上下文面板正确显示数据 ✅
### 8.2 Node Output Visualization
- [x] **8.2.1** 在 ContextInspector 中按节点分组显示输出
- [x] **8.2.2** 显示节点名称和类型图标
- [x] **8.2.3** 支持展开/折叠节点输出详情
- [x] **8.2.4** 显示变量引用语法 (如 `{{nodes.fetch_1.prd_url}}`)
**验证**: 节点输出正确分组显示 ✅
### 8.3 Create VariablePicker Component
- [x] **8.3.1** 创建 `web/src/components/workflow/VariablePicker.vue`
- [x] **8.3.2** 实现弹出式变量选择器
- [x] **8.3.3** 按分类展示可用变量 (input/global/nodes/trigger)
- [x] **8.3.4** 点击插入变量到配置输入框
- [x] **8.3.5** 支持预设常用变量（无上下文时显示）
**验证**: 变量选择器可插入变量 ✅
---
## Phase: Frontend Trigger Management (触发器管理)
### 9.1 Trigger Management API Integration
- [x] **9.1.1** 编辑 `web/src/api/workflow.ts`
- [x] **9.1.2** 添加方法:
 - `listTriggers(workflowId: string): Promise<Trigger>`
 - `createTrigger(workflowId: string, data: TriggerCreate): Promise<Trigger>`
 - `updateTrigger(triggerId: string, data: TriggerUpdate): Promise<Trigger>`
 - `deleteTrigger(triggerId: string): Promise<void>`
**验证**: API 调用成功 ✅
### 9.2 Create TriggerConfigPanel
- [x] **9.2.1** 创建 `web/src/components/workflow/TriggerConfigPanel.vue`
- [x] **9.2.2** 显示已配置的触发器列表
- [x] **9.2.3** 触发器启用/禁用开关
- [x] **9.2.4** 编辑/删除触发器按钮
- [x] **9.2.5** 添加触发器按钮
**验证**: 触发器列表正确显示 ✅
### 9.3 Create TriggerEditDialog
- [x] **9.3.1** 创建 `web/src/components/workflow/TriggerEditDialog.vue`
- [x] **9.3.2** 事件类型选择
- [x] **9.3.3** 过滤条件配置表单（项目 Key、工作项类型、状态）
- [x] **9.3.4** 支持创建和编辑模式
- [x] **9.3.5** 保存/取消按钮
**验证**: 触发器可创建和编辑 ✅
---
## Phase: Frontend Manual Trigger (手动触发)
### 10.1 Create ManualTriggerDialog
- [x] **10.1.1** 创建 `web/src/components/workflow/ManualTriggerDialog.vue`
- [x] **10.1.2** 事件类型选择下拉框
- [x] **10.1.3** 输入数据 JSON 编辑器
- [x] **10.1.4** 错误信息显示
- [x] **10.1.5** 触发按钮
**验证**: 对话框可打开并提交 ✅
### 10.2 Manual Trigger API Integration
- [x] **10.2.1** 编辑 `web/src/api/workflow.ts`
- [x] **10.2.2** 添加 `executeWorkflow(workflowId: string, data: ExecuteRequest): Promise<Execution>`
- [x] **10.2.3** ManualTriggerDialog 集成 API 调用
- [x] **10.2.4** 支持 triggered 事件回调
**验证**: 手动触发成功 ✅
---
## Phase: Frontend Execution Detail Enhancement (执行详情增强)
### 11.1 Context Real-time Display
- [x] **11.1.1** ContextInspector 组件已创建
- [x] **11.1.2** 支持传入 ExecutionContext 数据
- [x] **11.1.3** getExecutionContext API 已实现
- [x] **11.1.4** 显示全局参数和节点输出
- [x] **11.1.5** 支持复制变量路径
**验证**: 上下文展示组件已就绪 ✅
### 11.2 Create CodingTaskList
- [x] **11.2.1** 创建 `web/src/components/workflow/CodingTaskList.vue`
- [x] **11.2.2** 显示 AI 编码指派器创建的任务列表
- [x] **11.2.3** 任务卡片: 名称、仓库、状态、PR 链接
- [x] **11.2.4** 状态颜色标识
**验证**: 编码任务列表正确显示 ✅
### 11.3 Create CodingTaskDetail
- [x] **11.3.1** 创建 `web/src/components/workflow/CodingTaskDetail.vue`
- [x] **11.3.2** 显示任务 Prompt
- [x] **11.3.3** 显示规划输出
- [x] **11.3.4** 显示 Git 产物 (分支、提交、PR)
- [x] **11.3.5** 人工反馈输入框和审批操作
**验证**: 编码任务详情正确显示 ✅
---
## Final Verification
- **V1** 运行后端测试: `cd server && pytest`
- **V2** 运行前端构建: `cd web && npm run build`
- **V3** 端到端测试:
 1. 创建工作流: 触发器 → 获取工作项 → AI Prompt
 2. 配置触发器监听 WorkitemStatusEvent
 3. 发送模拟 Webhook 或使用手动触发
 4. 检查执行详情页的上下文展示
 5. 验证全局参数和节点输出正确传递
