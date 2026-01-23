# Tasks: Add Dynamic Workflow Engine
> **预计总工时**: 9 周
> **优先级**: P0
> **迁移策略**: 完全迁移到 Workflow（废弃现有 Task 固定流水线）
---
## Phase: 基础框架（2 周）
### 1.1 创建 Django App
- 1.1.1 执行 `python manage.py startapp workflows`
- 1.1.2 配置 `workflows/apps.py` 和注册到 `INSTALLED_APPS`
- 1.1.3 创建目录结构：`models/`, `nodes/`, `engine/`, `hooks/`, `api/`
### 1.2 数据模型
- 1.2.1 实现 `Workflow` 模型（含 `clone`, `to_json`, `from_json`）
- 1.2.2 实现 `WorkflowNode` 模型（含配置验证、克隆）
- 1.2.3 实现 `WorkflowEdge` 模型（含唯一约束）
- 1.2.4 实现 `WorkflowExecution` 模型（含状态管理方法）
- 1.2.5 实现 `NodeExecution` 模型（含审批方法）
- 1.2.6 实现 `WebhookConfig` 和 `WebhookLog` 模型
- 1.2.7 生成并执行迁移 `python manage.py makemigrations workflows`
### 1.3 节点类型系统
- 1.3.1 实现 `BaseNode` 抽象基类（含端口定义、Schema 验证）
- 1.3.2 实现 `NodePort`, `NodeResult`, `ExecutionContext` 数据类
- 1.3.3 实现 `NodeRegistry` 单例（含自动发现机制）
- 1.3.4 实现 `@register_node` 装饰器
### 1.4 核心节点实现
- 1.4.1 实现 `ManualTriggerNode`（触发器）
- 1.4.2 实现 `WebhookTriggerNode`（触发器）
- 1.4.3 实现 `HumanApprovalNode`（审批）
- 1.4.4 实现 `HTTPRequestNode`（集成）
- 1.4.5 实现 `WebhookCallNode`（集成，可调用 n8n）
- 1.4.6 实现 `ConditionNode`（控制流）
### 1.5 DAG 引擎
- 1.5.1 实现 `DAG` 类（构建、验证、拓扑排序）
- 1.5.2 实现 `DAGNode` 包装类
- 1.5.3 实现环路检测算法
- 1.5.4 实现入口节点和后继节点查找
### 1.6 执行引擎
- 1.6.1 实现 `WorkflowEngine` 主调度器
- 1.6.2 实现 `start_execution` 方法
- 1.6.3 实现 `_run_execution` 主循环（并行调度）
- 1.6.4 实现 `_execute_node` 节点执行
- 1.6.5 实现 `_collect_inputs` 输入收集
- 1.6.6 实现 `pause/resume/cancel` 执行控制
- 1.6.7 实现 `approve_node/reject_node` 审批处理
- 1.6.8 实现超时检测机制
### 1.7 生命周期钩子
- 1.7.1 实现 `BaseHook` 抽象类
- 1.7.2 实现 `HookManager` 事件管理器
- 1.7.3 实现 `LoggingHook` 日志钩子
- 1.7.4 实现 `WebSocketBroadcastHook` 广播钩子
- 1.7.5 实现 `NotificationHook` 通知钩子
---
## Phase: API 层（1.5 周）
### 2.1 Serializers
- [x] 2.1.1 实现 `WorkflowSerializer`（含嵌套节点和边）
- [x] 2.1.2 实现 `WorkflowNodeSerializer`
- [x] 2.1.3 实现 `WorkflowEdgeSerializer`
- [x] 2.1.4 实现 `WorkflowExecutionSerializer`（含节点状态）
- [x] 2.1.5 实现 `NodeExecutionSerializer`
- [x] 2.1.6 实现 `NodeTypeSerializer`（用于前端节点面板）
### 2.2 ViewSets
- [x] 2.2.1 实现 `WorkflowViewSet`（CRUD + execute + duplicate + export）
- [x] 2.2.2 实现 `WorkflowExecutionViewSet`（CRUD + pause/resume/cancel）
- [x] 2.2.3 实现 `NodeTypeViewSet`（只读，列出所有节点类型）
- [x] 2.2.4 实现 `WebhookTriggerView`（处理外部 webhook）
- [x] 2.2.5 实现 `NodeCallbackView`（处理外部回调）
- [x] 2.2.6 实现 `NodeApproveView` 和 `NodeRejectView`
### 2.3 权限
- [x] 2.3.1 实现 `WorkflowPermission`（基于项目成员）
- [x] 2.3.2 实现 `ExecutionPermission`
- [x] 2.3.3 实现 `ApprovalPermission`（审批人验证）
### 2.4 URL 配置
- [x] 2.4.1 配置 `workflows/urls.py`
- [x] 2.4.2 注册到主 `urls.py`
- [x] 2.4.3 更新 `drf-spectacular` 文档配置
---
## Phase: WebSocket 实时通信（1 周）
### 3.1 Django Channels 配置
- [x] 3.1.1 安装 `channels` 和 `channels-redis`
- [x] 3.1.2 配置 `ASGI_APPLICATION` 和 `CHANNEL_LAYERS`
- [x] 3.1.3 更新 `asgi.py` 支持 WebSocket
### 3.2 Consumer 实现
- [x] 3.2.1 实现 `WorkflowExecutionConsumer`
- [x] 3.2.2 实现消息类型：`node_started`, `node_completed`, `node_failed`, `execution_completed`
- [x] 3.2.3 配置 `routing.py`
### 3.3 集成测试
- [x] 3.3.1 测试 WebSocket 连接和断开
- [x] 3.3.2 测试执行状态实时推送
- [x] 3.3.3 测试审批通知推送
---
## Phase: 前端编辑器（2 周）
### 4.1 Vue Flow 集成
- 4.1.1 安装 `@vue-flow/core`, `@vue-flow/background`, `@vue-flow/controls`, `@vue-flow/minimap`
- 4.1.2 创建 `useVueFlow` composable 封装
### 4.2 页面
- 4.2.1 创建 `web/src/pages/workflows/index.vue`（列表页）
- 4.2.2 创建 `web/src/pages/workflows/[id].vue`（编辑器页）
- 4.2.3 创建 `web/src/pages/workflows/executions/[id].vue`（执行详情页）
- 4.2.4 配置 Vue Router 路由
### 4.3 编辑器组件
- 4.3.1 创建 `WorkflowCanvas.vue`（Vue Flow 容器）
- 4.3.2 创建 `NodePalette.vue`（左侧节点面板）
- 4.3.3 创建 `NodeConfigPanel.vue`（右侧配置面板）
- 4.3.4 创建 `WorkflowToolbar.vue`（顶部工具栏）
### 4.4 自定义节点组件
- 4.4.1 创建 `BaseNodeComponent.vue`（基础节点渲染）
- 4.4.2 创建 `TriggerNode.vue`（触发器样式）
- 4.4.3 创建 `ActionNode.vue`（动作样式）
- 4.4.4 创建 `ApprovalNode.vue`（审批样式）
- 4.4.5 创建 `ControlNode.vue`（控制流样式）
### 4.5 交互实现
- 4.5.1 实现从面板拖拽到画布
- 4.5.2 实现节点连接（含验证）
- 4.5.3 实现节点选择和配置
- 4.5.4 实现撤销/重做
- 4.5.5 实现保存/加载
### 4.6 状态管理
- 4.6.1 创建 `useWorkflowsStore` Pinia store
- 4.6.2 创建 `useNodeTypesStore`
- 4.6.3 创建 `useExecutionsStore`
- 4.6.4 实现 WebSocket 连接管理
### 4.7 执行监控
- 4.7.1 创建 `ExecutionProgress.vue`（进度展示）
- 4.7.2 实现节点状态颜色映射
- 4.7.3 实现节点日志查看
- 4.7.4 实现审批操作按钮
---
## Phase: 扩展节点（1 周）
### 5.1 Git 节点
- 5.1.1 实现 `CreateBranchNode`
- 5.1.2 实现 `CreatePRNode`
- 5.1.3 实现 `MergePRNode`
### 5.2 AI 节点（迁移现有 Task 逻辑）
- 5.2.1 实现 `AnalyzeRequirementsNode`（需求分析）
- 5.2.2 实现 `AnalyzeBugNode`（Bug 分析）
- 5.2.3 实现 `GeneratePlanNode`（生成技术方案，对应原 PLANNING 状态）
- 5.2.4 实现 `RevisePlanNode`（根据反馈修改方案）
- 5.2.5 实现 `CodeImplementNode`（代码实现，对应原 EXECUTING 状态，复用 Docker 执行器）
### 5.3 集成节点
- 5.3.1 实现 `NotifyFeishuNode`
- 5.3.2 实现 `MCPDeployNode`
### 5.4 控制流节点
- 5.4.1 实现 `DelayNode`
- 5.4.2 实现 `ParallelNode`（Fork/Join）
---
## Phase: Task 迁移（1 周）⚠️ 关键阶段
### 6.1 数据迁移
- 6.1.1 创建默认工作流模板：`[触发] → [生成方案] → [方案审批] → [代码实现] → [代码审批] → [完成]`
- 6.1.2 编写数据迁移脚本：将现有 `Task` 数据转换为 `WorkflowExecution`
- 6.1.3 迁移 `Task.plan_output` → `NodeExecution.output_data`
- 6.1.4 迁移 `Task.status` → 对应 `NodeExecution` 状态
- 6.1.5 迁移 `Task.branch_name`, `commit_sha`, `pr_url` → `WorkflowExecution.context`
- 6.1.6 验证数据完整性
### 6.2 代码重构
- 6.2.1 重构 `TaskScheduler` → 提取 Docker 执行逻辑为 `ContainerExecutor`
- 6.2.2 `CodeImplementNode` 调用 `ContainerExecutor`
- 6.2.3 重构飞书回调：从触发 Task 改为触发 Workflow
- 6.2.4 重构任务详情页：使用 WorkflowExecution 数据
### 6.3 前端迁移
- 6.3.1 更新任务列表页 `/tasks` → 展示 WorkflowExecution
- 6.3.2 更新任务详情页 `/tasks/[id]` → 展示节点执行状态
- 6.3.3 保留原有 UI 体验（状态徽章、日志查看等）
- 6.3.4 添加"查看工作流"入口，跳转到工作流编辑器
### 6.4 API 兼容层（可选，用于过渡）
- 6.4.1 保留 `/api/tasks/` 端点，内部调用 Workflow API
- 6.4.2 实现 Task → WorkflowExecution 的响应转换
- 6.4.3 标记为 Deprecated，计划未来版本移除
### 6.5 废弃清理
- 6.5.1 标记 `tasks/models.py` 为 Deprecated
- 6.5.2 标记 `tasks/views.py` 为 Deprecated
- 6.5.3 更新文档，说明迁移路径
- 6.5.4 保留 Task 表结构（只读，用于历史数据查询）
---
## Phase: 测试和文档（0.5 周）
### 7.1 单元测试
- 7.1.1 创建 `tests/workflows/test_models.py`
- 7.1.2 创建 `tests/workflows/test_dag.py`
- 7.1.3 创建 `tests/workflows/test_engine.py`
- 7.1.4 创建 `tests/workflows/test_nodes.py`
- 7.1.5 创建 `tests/workflows/test_api.py`
### 7.2 集成测试
- 7.2.1 测试完整工作流执行（触发 → 执行 → 审批 → 完成）
- 7.2.2 测试并行执行
- 7.2.3 测试条件分支
- 7.2.4 测试错误处理和重试
- 7.2.5 测试 Webhook 触发
### 7.3 迁移测试
- 7.3.1 测试默认工作流模板与原 Task 流程行为一致
- 7.3.2 测试历史 Task 数据迁移后可正常查看
- 7.3.3 测试飞书触发新工作流执行
### 7.4 文档更新
- 7.4.1 更新导航菜单，添加工作流入口
- 7.4.2 更新 API 文档
- 7.4.3 编写迁移指南
---
## 验收标准
### 功能验收
- 可通过 UI 创建、编辑、保存工作流
- 可拖拽添加节点并连接
- 可手动触发工作流执行
- 可实时查看执行进度（WebSocket）
- 可在审批节点暂停并人工审批
- 可调用外部 Webhook（如 n8n）
- 可通过外部 Webhook 触发工作流
- **默认工作流模板与原 Task 流程体验一致**
### 迁移验收
- **现有 Task 数据成功迁移到 WorkflowExecution**
- **飞书触发改为创建 WorkflowExecution**
- **原任务详情页可正常展示迁移后的数据**
- **Task API 兼容层正常工作（如启用）**
### 性能验收
- 单个工作流支持 50+ 节点
- 支持 10+ 节点并行执行
- WebSocket 延迟 < 500ms
### 兼容性验收
- 历史 Task 数据可查询
- API 兼容层正常工作
- 节点配置支持版本迁移
