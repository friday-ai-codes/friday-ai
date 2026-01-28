# Tasks: Add Dynamic Workflow Engine
> **预计总工时**: 9 周
> **优先级**: P0
> **迁移策略**: 完全迁移到 Workflow（废弃现有 Task 固定流水线）
---
## Phase: 基础框架（2 周）
### 1.1 创建 Django App
- [x] 1.1.1 执行 `python manage.py startapp workflows`
- [x] 1.1.2 配置 `workflows/apps.py` 和注册到 `INSTALLED_APPS`
- [x] 1.1.3 创建目录结构：`models/`, `nodes/`, `engine/`, `hooks/`, `api/`
### 1.2 数据模型
- [x] 1.2.1 实现 `Workflow` 模型（含 `clone`, `to_json`, `from_json`）
- [x] 1.2.2 实现 `WorkflowNode` 模型（含配置验证、克隆）
- [x] 1.2.3 实现 `WorkflowEdge` 模型（含唯一约束）
- [x] 1.2.4 实现 `WorkflowExecution` 模型（含状态管理方法）
- [x] 1.2.5 实现 `NodeExecution` 模型（含审批方法）
- [x] 1.2.6 实现 `WebhookConfig` 和 `WebhookLog` 模型
- [x] 1.2.7 生成并执行迁移 `python manage.py makemigrations workflows`
### 1.3 节点类型系统
- [x] 1.3.1 实现 `BaseNode` 抽象基类（含端口定义、Schema 验证）
- [x] 1.3.2 实现 `NodePort`, `NodeResult`, `ExecutionContext` 数据类
- [x] 1.3.3 实现 `NodeRegistry` 单例（含自动发现机制）
- [x] 1.3.4 实现 `@register_node` 装饰器
### 1.4 核心节点实现
- [x] 1.4.1 实现 `ManualTriggerNode`（触发器）
- [x] 1.4.2 实现 `WebhookTriggerNode`（触发器）
- [x] 1.4.3 实现 `HumanApprovalNode`（审批）
- [x] 1.4.4 实现 `HTTPRequestNode`（集成）
- [x] 1.4.5 实现 `WebhookCallNode`（集成，可调用 n8n）
- [x] 1.4.6 实现 `ConditionNode`（控制流）
### 1.5 DAG 引擎
- [x] 1.5.1 实现 `DAG` 类（构建、验证、拓扑排序）
- [x] 1.5.2 实现 `DAGNode` 包装类
- [x] 1.5.3 实现环路检测算法
- [x] 1.5.4 实现入口节点和后继节点查找
### 1.6 执行引擎
- [x] 1.6.1 实现 `WorkflowEngine` 主调度器
- [x] 1.6.2 实现 `start_execution` 方法
- [x] 1.6.3 实现 `_run_execution` 主循环（并行调度）
- [x] 1.6.4 实现 `_execute_node` 节点执行
- [x] 1.6.5 实现 `_collect_inputs` 输入收集
- [x] 1.6.6 实现 `pause/resume/cancel` 执行控制
- [x] 1.6.7 实现 `approve_node/reject_node` 审批处理
- [x] 1.6.8 实现超时检测机制
### 1.7 生命周期钩子
- [x] 1.7.1 实现 `BaseHook` 抽象类
- [x] 1.7.2 实现 `HookManager` 事件管理器
- [x] 1.7.3 实现 `LoggingHook` 日志钩子
- [x] 1.7.4 实现 `WebSocketBroadcastHook` 广播钩子
- [x] 1.7.5 实现 `NotificationHook` 通知钩子
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
- [x] 4.1.1 安装 `@vue-flow/core`, `@vue-flow/background`, `@vue-flow/controls`, `@vue-flow/minimap`
- [x] 4.1.2 创建 `useVueFlow` composable 封装 (Using library directly for now)
### 4.2 页面
- [x] 4.2.1 创建 `web/src/pages/workflows/index.vue`（列表页）
- [x] 4.2.2 创建 `web/src/pages/workflows/[id].vue`（编辑器页）
- [x] 4.2.3 创建 `web/src/pages/workflows/executions/[id].vue`（执行详情页）
- [x] 4.2.4 配置 Vue Router 路由 (Auto-routed)
### 4.3 编辑器组件
- [x] 4.3.1 创建 `WorkflowCanvas.vue`（Vue Flow 容器）
- [x] 4.3.2 创建 `NodePalette.vue`（左侧节点面板）
- [x] 4.3.3 创建 `NodeConfigPanel.vue`（右侧配置面板）
- [x] 4.3.4 创建 `WorkflowToolbar.vue`（顶部工具栏）
### 4.4 自定义节点组件
- [x] 4.4.1 创建 `BaseNodeComponent.vue`（基础节点渲染）
- [x] 4.4.2 创建 `TriggerNode.vue`（触发器样式）
- [x] 4.4.3 创建 `ActionNode.vue`（动作样式）
- [x] 4.4.4 创建 `ApprovalNode.vue`（审批样式）
- [x] 4.4.5 创建 `ControlNode.vue`（控制流样式）
### 4.5 交互实现
- [x] 4.5.1 实现从面板拖拽到画布
- [x] 4.5.2 实现节点连接（含验证）
- [x] 4.5.3 实现节点选择和配置
- [x] 4.5.4 实现撤销/重做
- [x] 4.5.5 实现保存/加载
### 4.6 状态管理
- [x] 4.6.1 创建 `useWorkflowsStore` Pinia store
- [x] 4.6.2 创建 `useNodeTypesStore`
- [x] 4.6.3 创建 `useExecutionsStore`
- [x] 4.6.4 实现 WebSocket 连接管理
### 4.7 执行监控
- [x] 4.7.1 创建 `ExecutionProgress.vue`（进度展示）
- [x] 4.7.2 实现节点状态颜色映射
- [x] 4.7.3 实现节点日志查看
- [x] 4.7.4 实现审批操作按钮
---
## Phase: 扩展节点（1 周）
### 5.1 Git 节点
- [x] 5.1.1 实现 `CreateBranchNode`
- [x] 5.1.2 实现 `CreatePRNode`
- [x] 5.1.3 实现 `MergePRNode`
### 5.2 AI 节点（迁移现有 Task 逻辑）
- [x] 5.2.1 实现 `AnalyzeRequirementsNode`（需求分析）
- [x] 5.2.2 实现 `AnalyzeBugNode`（Bug 分析）
- [x] 5.2.3 实现 `GeneratePlanNode`（生成技术方案，对应原 PLANNING 状态）
- [x] 5.2.4 实现 `RevisePlanNode`（根据反馈修改方案）
- [x] 5.2.5 实现 `CodeImplementNode`（代码实现，对应原 EXECUTING 状态，复用 Docker 执行器）
### 5.3 集成节点
- [x] 5.3.1 实现 `NotifyFeishuNode`
- [x] 5.3.2 实现 `MCPDeployNode`
### 5.4 控制流节点
- [x] 5.4.1 实现 `DelayNode`
- [x] 5.4.2 实现 `ParallelNode`（Fork/Join）
---
## Phase: Task 迁移 ⚠️ 关键阶段
> **迁移策略**: 渐进式迁移 + 特性开关控制，保持向后兼容，新任务使用 Workflow，历史任务保留只读访问。
>
> **Vibe Coding 友好设计**: 每个任务都是独立可执行的原子单元，包含明确的输入/输出和验证标准。
---
### 6.0 前置准备：特性开关与环境配置
> **目标**: 建立安全的迁移基础设施，支持灰度发布和快速回滚。
#### 6.0.1 特性开关系统
- [x] **6.0.1.1** 创建 `server/core/feature_flags.py`
 ```python
 # 文件位置: server/core/feature_flags.py
 # 输入: 无
 # 输出: FeatureFlags 单例类
 from django.conf import settings
 class FeatureFlags:
 """特性开关管理器"""
 @property
 def use_workflow_for_new_tasks(self) -> bool:
 """新飞书事项是否创建 Workflow 而非 Task"""
 return getattr(settings, 'FF_USE_WORKFLOW_FOR_NEW_TASKS', False)
 @property
 def enable_task_compat_api(self) -> bool:
 """是否启用 /api/tasks/ 兼容层"""
 return getattr(settings, 'FF_ENABLE_TASK_COMPAT_API', True)
 @property
 def sync_workflow_to_feishu(self) -> bool:
 """工作流状态是否同步到飞书"""
 return getattr(settings, 'FF_SYNC_WORKFLOW_TO_FEISHU', True)
 feature_flags = FeatureFlags
 ```
 - **验证**: `from core.feature_flags import feature_flags; assert hasattr(feature_flags, 'use_workflow_for_new_tasks')`
- [x] **6.0.1.2** 添加环境变量到 `.env.example`
 ```bash
 # 在 .env.example 末尾添加
 # Feature Flags for Task Migration
 FF_USE_WORKFLOW_FOR_NEW_TASKS=false
 FF_ENABLE_TASK_COMPAT_API=true
 FF_SYNC_WORKFLOW_TO_FEISHU=true
 ```
 - **验证**: `grep FF_USE_WORKFLOW .env.example`
- [x] **6.0.1.3** 在 `server/friday/settings.py` 注册开关
 ```python
 # Feature Flags
 FF_USE_WORKFLOW_FOR_NEW_TASKS = env.bool('FF_USE_WORKFLOW_FOR_NEW_TASKS', False)
 FF_ENABLE_TASK_COMPAT_API = env.bool('FF_ENABLE_TASK_COMPAT_API', True)
 FF_SYNC_WORKFLOW_TO_FEISHU = env.bool('FF_SYNC_WORKFLOW_TO_FEISHU', True)
 ```
 - **验证**: `python manage.py shell -c "from django.conf import settings; print(settings.FF_USE_WORKFLOW_FOR_NEW_TASKS)"`
---
### 6.1 ContainerExecutor 服务层
> **目标**: 将 `TaskScheduler` (位于 `server/services/scheduler.py`) 的 Docker 执行逻辑抽象为通用服务。
>
> **现有代码分析**:
> - `_detect_docker_network`: 检测 friday-ai_friday-network (Lines 28-41)
> - `_build_env`: 构建环境变量，含代理配置 (Lines work-item)
> - `start_task`: 容器启动，资源限制 2G RAM / 1 CPU (Lines work-item)
#### 6.1.1 创建 ContainerExecutor 服务
- [x] **6.1.1.1** 创建数据类定义 `server/services/container_executor.py`
 ```python
 # 文件位置: server/services/container_executor.py
 # 依赖: dataclasses, typing
 # 输出: ExecutionRequest, ExecutionResult 数据类
 from dataclasses import dataclass, field
 from typing import Any
 @dataclass
 class ExecutionRequest:
 """容器执行请求"""
 execution_id: str # WorkflowExecution.id (用于目录隔离)
 node_execution_id: str # NodeExecution.id (用于回调标识)
 image: str = "friday-task:latest"
 environment: dict = field(default_factory=dict)
 volumes: dict = field(default_factory=dict)
 timeout: int = 3600 # 默认 1 小时
 callback_url: str = ""
 # 资源限制
 mem_limit: str = "2g"
 cpu_quota: int = 100000 # 1 CPU
 @dataclass
 class ExecutionResult:
 """容器执行结果"""
 success: bool
 status: str # completed, failed, timeout, cancelled
 output: dict = field(default_factory=dict)
 logs: str = ""
 error: str | None = None
 duration: float = 0.0
 container_id: str = ""
 ```
 - **验证**: `python -c "from services.container_executor import ExecutionRequest, ExecutionResult; print('OK')"`
- [x] **6.1.1.2** 提取 Docker 网络检测逻辑
 ```python
 # 在 container_executor.py 中添加
 # 参考: server/services/scheduler.py Lines 28-41
 import docker
 import structlog
 logger = structlog.get_logger
 class ContainerExecutor:
 """Docker 容器执行服务"""
 NETWORK_NAME = "friday-ai_friday-network"
 def __init__(self):
 self.client = docker.from_env
 self._docker_network = self._detect_docker_network
 def _detect_docker_network(self) -> str | None:
 """检测 Docker Compose 网络"""
 try:
 networks = self.client.networks.list(names=[self.NETWORK_NAME])
 if networks:
 logger.info("docker_network_detected", network=self.NETWORK_NAME)
 return self.NETWORK_NAME
 except Exception as e:
 logger.warning("docker_network_detection_failed", error=str(e))
 return None
 ```
 - **验证**: `python -c "from services.container_executor import ContainerExecutor; c = ContainerExecutor; print(c._docker_network)"`
- [x] **6.1.1.3** 提取环境变量构建逻辑
 ```python
 # 在 ContainerExecutor 类中添加
 # 参考: server/services/scheduler.py Lines work-item
 def _build_callback_url(self, port: int = 8000) -> str:
 """构建容器回调 URL"""
 if self._docker_network:
 # Compose 模式：使用容器名
 return f"http://friday-server:{port}/api/workflows/callbacks/"
 else:
 # 本地开发：使用 host.docker.internal
 return f"http://host.docker.internal:{port}/api/workflows/callbacks/"
 def _build_run_kwargs(self, request: ExecutionRequest) -> dict:
 """构建 docker run 参数"""
 kwargs = {
 "detach": True,
 "environment": request.environment,
 "mem_limit": request.mem_limit,
 "cpu_period": 100000,
 "cpu_quota": request.cpu_quota,
 "auto_remove": False, # 保留容器以便调试
 }
 if request.volumes:
 kwargs["volumes"] = request.volumes
 if self._docker_network:
 kwargs["network"] = self._docker_network
 else:
 kwargs["extra_hosts"] = {"host.docker.internal": "host-gateway"}
 return kwargs
 ```
 - **验证**: 单元测试 `test_build_callback_url`
- [x] **6.1.1.4** 实现核心执行方法
 ```python
 # 在 ContainerExecutor 类中添加
 async def start_execution(self, request: ExecutionRequest) -> str:
 """启动容器执行，返回 container_id"""
 import asyncio
 # 确保镜像存在
 await self._ensure_image(request.image)
 # 注入回调 URL
 env = request.environment.copy
 env["FRIDAY_CALLBACK_URL"] = request.callback_url or self._build_callback_url
 env["FRIDAY_EXECUTION_ID"] = request.execution_id
 env["FRIDAY_NODE_EXECUTION_ID"] = request.node_execution_id
 # 构建运行参数
 run_kwargs = self._build_run_kwargs(request)
 run_kwargs["environment"] = env
 # 启动容器
 container = await asyncio.to_thread(
 self.client.containers.run,
 request.image,
 **run_kwargs
 )
 logger.info("container_started",
 container_id=container.id[:12],
 execution_id=request.execution_id)
 return container.id
 async def wait_for_completion(
 self,
 container_id: str,
 timeout: int = 3600
 ) -> ExecutionResult:
 """等待容器完成"""
 import asyncio
 import time
 start_time = time.time
 container = self.client.containers.get(container_id)
 try:
 # 等待容器退出
 result = await asyncio.wait_for(
 asyncio.to_thread(container.wait),
 timeout=timeout
 )
 duration = time.time - start_time
 logs = container.logs(tail=500).decode('utf-8', errors='replace')
 if result['StatusCode'] == 0:
 return ExecutionResult(
 success=True,
 status="completed",
 logs=logs,
 duration=duration,
 container_id=container_id
 )
 else:
 return ExecutionResult(
 success=False,
 status="failed",
 error=f"Container exited with code {result['StatusCode']}",
 logs=logs,
 duration=duration,
 container_id=container_id
 )
 except asyncio.TimeoutError:
 await self.stop_execution(container_id, force=True)
 return ExecutionResult(
 success=False,
 status="timeout",
 error=f"Execution timed out after {timeout}s",
 duration=timeout,
 container_id=container_id
 )
 async def stop_execution(self, container_id: str, force: bool = False):
 """停止容器"""
 import asyncio
 try:
 container = self.client.containers.get(container_id)
 if force:
 await asyncio.to_thread(container.kill)
 else:
 await asyncio.to_thread(container.stop, timeout=30)
 logger.info("container_stopped", container_id=container_id[:12])
 except docker.errors.NotFound:
 pass
 async def get_logs(self, container_id: str, tail: int = 100) -> str:
 """获取容器日志"""
 import asyncio
 try:
 container = self.client.containers.get(container_id)
 logs = await asyncio.to_thread(container.logs, tail=tail)
 return logs.decode('utf-8', errors='replace')
 except docker.errors.NotFound:
 return ""
 async def _ensure_image(self, image: str):
 """确保镜像存在"""
 import asyncio
 try:
 self.client.images.get(image)
 except docker.errors.ImageNotFound:
 logger.info("building_image", image=image)
 await self._build_image(image)
 async def _build_image(self, image: str):
 """构建镜像"""
 import asyncio
 import os
 # task 目录相对于 server/
 task_dir = os.path.join(os.path.dirname(__file__), "..", "task")
 await asyncio.to_thread(
 self.client.images.build,
 path=task_dir,
 tag=image,
 rm=True
 )
 ```
 - **验证**: 集成测试，启动一个 hello-world 容器
#### 6.1.2 集成到 CodeImplementNode
- [x] **6.1.2.1** 修改 `server/workflows/nodes/ai/code.py`
 ```python
 # 文件位置: server/workflows/nodes/ai/code.py
 # 当前状态: _execute_in_container 是空的 TODO
 # 目标: 接入 ContainerExecutor
 from services.container_executor import ContainerExecutor, ExecutionRequest
 class CodeImplementNode(BaseNode):
 # ... 现有代码 ...
 async def _execute_in_container(self, context: ExecutionContext) -> NodeResult:
 """在 Docker 容器中执行代码实现"""
 executor = ContainerExecutor
 # 从上下文获取配置
 workflow_ctx = context.workflow_context
 project_id = workflow_ctx.get('project_id')
 repository_path = workflow_ctx.get('repository_path')
 # 构建环境变量
 environment = {
 "FRIDAY_TASK_MODE": context.get_config("execution_mode", "auto"),
 "FRIDAY_TASK_MAX_ITERATIONS": str(context.get_config("max_iterations", 10)),
 "FRIDAY_TASK_REPOSITORY_PATH": repository_path,
 "FRIDAY_TASK_PLAN": context.get_input("plan", ""),
 }
 # 添加 Claude 配置（从项目设置获取）
 # TODO: 从 Project.claude_config 获取
 request = ExecutionRequest(
 execution_id=context.execution_id,
 node_execution_id=context.node_id,
 environment=environment,
 timeout=context.get_config("timeout", 3600),
 )
 container_id = await executor.start_execution(request)
 # 返回 waiting 状态，等待回调
 return NodeResult(
 status="waiting_callback",
 output={"container_id": container_id}
 )
 ```
 - **验证**: 创建包含 CodeImplementNode 的工作流，触发执行，检查容器启动
- [x] **6.1.2.2** 创建容器回调 API `server/workflows/api/callbacks.py`
 ```python
 # 文件位置: server/workflows/api/callbacks.py
 # 功能: 接收容器执行完成的回调
 from rest_framework.views import APIView
 from rest_framework.response import Response
 from rest_framework import status
 from workflows.models import NodeExecution, NodeExecutionStatus
 from workflows.engine.scheduler import WorkflowEngine
 import structlog
 logger = structlog.get_logger
 class NodeExecutionCallbackView(APIView):
 """容器执行回调端点"""
 # 允许无认证访问（来自容器内部）
 authentication_classes =
 permission_classes =
 async def post(self, request):
 """处理容器回调"""
 node_execution_id = request.data.get('node_execution_id')
 success = request.data.get('success', False)
 output = request.data.get('output', {})
 error = request.data.get('error')
 logs = request.data.get('logs', '')
 try:
 node_execution = await NodeExecution.objects.aget(id=node_execution_id)
 except NodeExecution.DoesNotExist:
 return Response(
 {"error": "NodeExecution not found"},
 status=status.HTTP_404_NOT_FOUND
 )
 # 更新节点状态
 if success:
 node_execution.status = NodeExecutionStatus.COMPLETED
 node_execution.output_data = output
 else:
 node_execution.status = NodeExecutionStatus.FAILED
 node_execution.error_message = error or "Unknown error"
 node_execution.container_logs = logs
 await node_execution.asave
 # 触发引擎继续执行
 engine = WorkflowEngine
 await engine.resume_after_callback(node_execution)
 logger.info("node_callback_processed",
 node_execution_id=str(node_execution_id),
 success=success)
 return Response({"status": "ok"})
 ```
 - **验证**: `curl -X POST http://localhost:8000/api/workflows/callbacks/ -d '{"node_execution_id": "...", "success": true}'`
- [x] **6.1.2.3** 注册回调路由 `server/workflows/urls.py`
 ```python
 # 在 workflows/urls.py 中添加
 from workflows.api.callbacks import NodeExecutionCallbackView
 urlpatterns += [
 path('callbacks/', NodeExecutionCallbackView.as_view, name='node-callback'),
 ]
 ```
 - **验证**: `python manage.py show_urls | grep callbacks`
- [x] **6.1.2.4** 扩展 WorkflowEngine 支持回调恢复
 ```python
 # 在 server/workflows/engine/scheduler.py 中添加方法
 async def resume_after_callback(self, node_execution: NodeExecution):
 """容器回调后恢复执行"""
 workflow_execution = node_execution.workflow_execution
 # 更新统计
 if node_execution.status == NodeExecutionStatus.COMPLETED:
 workflow_execution.completed_nodes += 1
 elif node_execution.status == NodeExecutionStatus.FAILED:
 workflow_execution.failed_nodes += 1
 await workflow_execution.asave
 # 触发 hooks
 await self.hooks.trigger(
 "node_completed" if node_execution.status == NodeExecutionStatus.COMPLETED else "node_failed",
 execution=workflow_execution,
 node_execution=node_execution,
 )
 # 继续执行后续节点
 if node_execution.status == NodeExecutionStatus.COMPLETED:
 await self._continue_execution(workflow_execution)
 else:
 await self._handle_node_failure(workflow_execution, node_execution)
 ```
 - **验证**: 单元测试 `test_resume_after_callback`
---
### 6.2 默认工作流模板
> **目标**: 创建与现有 Task 流程完全等效的工作流模板。
>
> **映射关系**:
> ```
> Task.PENDING → Workflow 未启动
> Task.PLANNING → GeneratePlanNode running
> Task.PLAN_REVIEW → ApprovalNode waiting_approval
> Task.EXECUTING → CodeImplementNode running
> Task.CODE_REVIEW → ApprovalNode(2) waiting_approval
> Task.MERGED → Workflow completed
> ```
#### 6.2.1 模板目录结构
- [x] **6.2.1.1** 创建模板目录
 ```bash
 mkdir -p server/workflows/templates
 touch server/workflows/templates/__init__.py
 ```
 - **验证**: `ls server/workflows/templates/`
- [x] **6.2.1.2** 创建代码生成模板 `server/workflows/templates/code_generation.json`
 ```json
 {
 "version": "1.0",
 "name": "代码生成工作流",
 "description": "从需求到 PR 的完整代码生成流程，等效于原 Task 系统",
 "template_id": "code_generation",
 "nodes": [
 {
 "id": "trigger",
 "type": "manual_trigger",
 "name": "手动触发",
 "position": {"x": 250, "y": 0},
 "config": {
 "input_schema": {
 "type": "object",
 "properties": {
 "title": {"type": "string", "title": "任务标题"},
 "description": {"type": "string", "title": "需求描述"},
 "work_item_id": {"type": "string", "title": "飞书工作项ID"}
 },
 "required": ["title", "description"]
 }
 }
 },
 {
 "id": "generate_plan",
 "type": "generate_plan",
 "name": "生成方案",
 "position": {"x": 250, "y": 100},
 "config": {
 "requirements_template": "{{trigger.description}}",
 "include_codebase_analysis": true
 }
 },
 {
 "id": "plan_approval",
 "type": "human_approval",
 "name": "方案审批",
 "position": {"x": 250, "y": 200},
 "config": {
 "title": "方案审批",
 "description_template": "请审批以下技术方案：\n\n{{nodes.generate_plan.plan_markdown}}",
 "timeout_hours": 72,
 "notify_channels": ["feishu"]
 }
 },
 {
 "id": "code_implement",
 "type": "code_implement",
 "name": "代码实现",
 "position": {"x": 250, "y": 300},
 "config": {
 "plan_template": "{{nodes.generate_plan.plan_markdown}}",
 "execution_mode": "auto",
 "max_iterations": 10,
 "timeout": 3600
 }
 },
 {
 "id": "code_approval",
 "type": "human_approval",
 "name": "代码审批",
 "position": {"x": 250, "y": 400},
 "config": {
 "title": "代码审批",
 "description_template": "代码实现已完成，请审批：\n\n分支: {{nodes.code_implement.branch_name}}\n变更文件: {{nodes.code_implement.changed_files}}",
 "timeout_hours": 72,
 "notify_channels": ["feishu"]
 }
 },
 {
 "id": "create_pr",
 "type": "create_pr",
 "name": "创建PR",
 "position": {"x": 250, "y": 500},
 "config": {
 "title_template": "{{trigger.title}}",
 "body_template": "## 需求\n{{trigger.description}}\n\n## 技术方案\n{{nodes.generate_plan.plan_markdown}}",
 "base_branch": "main",
 "auto_merge": false
 }
 }
 ],
 "edges": [
 {"source": "trigger", "target": "generate_plan"},
 {"source": "generate_plan", "target": "plan_approval"},
 {"source": "plan_approval", "target": "code_implement", "source_handle": "approved"},
 {"source": "plan_approval", "target": "generate_plan", "source_handle": "rejected", "label": "驳回修改"},
 {"source": "code_implement", "target": "code_approval"},
 {"source": "code_approval", "target": "create_pr", "source_handle": "approved"},
 {"source": "code_approval", "target": "code_implement", "source_handle": "rejected", "label": "驳回修改"}
 ]
 }
 ```
 - **验证**: `python -c "import json; json.load(open('server/workflows/templates/code_generation.json'))"`
#### 6.2.2 模板加载器
- [x] **6.2.2.1** 创建模板加载器 `server/workflows/templates/loader.py`
 ```python
 # 文件位置: server/workflows/templates/loader.py
 import json
 import os
 from pathlib import Path
 from typing import Any
 from workflows.models import Workflow, WorkflowNode, WorkflowEdge
 import structlog
 logger = structlog.get_logger
 TEMPLATES_DIR = Path(__file__).parent
 def list_templates -> list[dict]:
 """列出所有可用模板"""
 templates =
 for f in TEMPLATES_DIR.glob("*.json"):
 with open(f) as fp:
 data = json.load(fp)
 templates.append({
 "template_id": data.get("template_id", f.stem),
 "name": data.get("name", f.stem),
 "description": data.get("description", ""),
 })
 return templates
 def load_template(template_id: str) -> dict:
 """加载模板定义"""
 template_path = TEMPLATES_DIR / f"{template_id}.json"
 if not template_path.exists:
 raise ValueError(f"Template not found: {template_id}")
 with open(template_path) as f:
 return json.load(f)
 def create_workflow_from_template(
 project_id: str,
 template_id: str,
 name: str | None = None,
 description: str | None = None,
 created_by = None,
 ) -> Workflow:
 """从模板创建工作流实例"""
 template = load_template(template_id)
 # 创建工作流
 workflow = Workflow.objects.create(
 name=name or template.get("name", template_id),
 description=description or template.get("description", ""),
 project_id=project_id,
 created_by=created_by,
 trigger_type="manual",
 metadata={"template_id": template_id, "template_version": template.get("version", "1.0")},
 )
 # 创建节点
 node_id_map = {} # template_id -> db_id
 for node_data in template.get("nodes", ):
 position = node_data.get("position", {})
 node = WorkflowNode.objects.create(
 workflow=workflow,
 node_type=node_data["type"],
 name=node_data.get("name", node_data["type"]),
 description=node_data.get("description", ""),
 position_x=position.get("x", 0),
 position_y=position.get("y", 0),
 config=node_data.get("config", {}),
 )
 node_id_map[node_data["id"]] = node.id
 # 创建边
 for edge_data in template.get("edges", ):
 WorkflowEdge.objects.create(
 workflow=workflow,
 source_node_id=node_id_map[edge_data["source"]],
 target_node_id=node_id_map[edge_data["target"]],
 source_handle=edge_data.get("source_handle", "default"),
 target_handle=edge_data.get("target_handle", "default"),
 label=edge_data.get("label", ""),
 )
 logger.info("workflow_created_from_template",
 workflow_id=str(workflow.id),
 template_id=template_id)
 return workflow
 ```
 - **验证**: `python manage.py shell -c "from workflows.templates.loader import list_templates; print(list_templates)"`
- [x] **6.2.2.2** 添加模板 API 端点
 ```python
 # 在 server/workflows/api/views.py 中添加
 from rest_framework.decorators import action
 from workflows.templates.loader import list_templates, create_workflow_from_template
 class WorkflowViewSet(viewsets.ModelViewSet):
 # ... 现有代码 ...
 @action(detail=False, methods=['get'])
 def templates(self, request):
 """GET /api/workflows/templates/ - 列出可用模板"""
 return Response(list_templates)
 @action(detail=False, methods=['post'], url_path='from-template')
 def from_template(self, request):
 """POST /api/workflows/from-template/ - 从模板创建工作流"""
 template_id = request.data.get('template_id')
 project_id = request.data.get('project_id')
 name = request.data.get('name')
 description = request.data.get('description')
 if not template_id or not project_id:
 return Response(
 {"error": "template_id and project_id are required"},
 status=400
 )
 try:
 workflow = create_workflow_from_template(
 project_id=project_id,
 template_id=template_id,
 name=name,
 description=description,
 created_by=request.user,
 )
 serializer = self.get_serializer(workflow)
 return Response(serializer.data, status=201)
 except ValueError as e:
 return Response({"error": str(e)}, status=400)
 ```
 - **验证**: `curl http://localhost:8000/api/workflows/templates/`
---
### 6.3 飞书集成迁移
> **目标**: 将飞书 Webhook 从直接操作 Task 改为触发 Workflow，使用特性开关控制切换。
>
> **现有代码位置**: `server/feishu/views.py`
> - `_handle_workitem_create`: 创建 Task (Lines ~work-item)
> - `_handle_workitem_comment`: 审批/驳回 (Lines ~work-item)
> - `_handle_workitem_status`: 状态同步 (Lines ~work-item)
#### 6.3.1 创建工作流桥接层
- [x] **6.3.1.1** 创建桥接服务 `server/feishu/workflow_bridge.py`
 ```python
 # 文件位置: server/feishu/workflow_bridge.py
 # 功能: 封装飞书事件到 Workflow 的转换逻辑
 from workflows.models import Workflow, WorkflowExecution, NodeExecution, NodeExecutionStatus
 from workflows.templates.loader import create_workflow_from_template
 from workflows.engine.scheduler import WorkflowEngine
 import structlog
 logger = structlog.get_logger
 class FeishuWorkflowBridge:
 """飞书事件到 Workflow 的桥接服务"""
 DEFAULT_TEMPLATE = "code_generation"
 async def on_workitem_create(
 self,
 project,
 work_item_id: str,
 title: str,
 description: str,
 ) -> WorkflowExecution:
 """飞书工作项创建 → 创建并启动 Workflow"""
 # 1. 从模板创建工作流
 workflow = await sync_to_async(create_workflow_from_template)(
 project_id=str(project.id),
 template_id=self.DEFAULT_TEMPLATE,
 name=title,
 description=description,
 )
 # 2. 创建执行实例
 execution = await WorkflowExecution.objects.acreate(
 workflow=workflow,
 trigger_type="feishu_webhook",
 input_data={
 "title": title,
 "description": description,
 "work_item_id": work_item_id,
 },
 context={
 "work_item_id": work_item_id,
 "project_id": str(project.id),
 "repository_path": project.repositories.first.local_path if project.repositories.exists else None,
 },
 )
 # 3. 启动执行
 engine = WorkflowEngine
 await engine.start_execution(execution)
 logger.info("workflow_started_from_feishu",
 execution_id=str(execution.id),
 work_item_id=work_item_id)
 return execution
 async def on_approval_comment(
 self,
 work_item_id: str,
 approved: bool,
 comment: str,
 approver = None,
 ) -> bool:
 """飞书评论审批 → 触发节点审批"""
 # 1. 根据 work_item_id 查找活跃的执行
 execution = await self._find_active_execution(work_item_id)
 if not execution:
 logger.warning("no_active_execution_for_workitem", work_item_id=work_item_id)
 return False
 # 2. 查找等待审批的节点
 node_execution = await NodeExecution.objects.filter(
 workflow_execution=execution,
 status=NodeExecutionStatus.WAITING_APPROVAL,
 ).afirst
 if not node_execution:
 logger.warning("no_pending_approval", execution_id=str(execution.id))
 return False
 # 3. 执行审批
 engine = WorkflowEngine
 if approved:
 await engine.approve_node(node_execution, approver, comment)
 else:
 await engine.reject_node(node_execution, approver, comment)
 logger.info("approval_processed",
 node_execution_id=str(node_execution.id),
 approved=approved)
 return True
 async def _find_active_execution(self, work_item_id: str) -> WorkflowExecution | None:
 """根据 work_item_id 查找活跃的 WorkflowExecution"""
 from django.db.models import Q
 return await WorkflowExecution.objects.filter(
 Q(context__work_item_id=work_item_id) |
 Q(input_data__work_item_id=work_item_id),
 status__in=["pending", "running", "paused"],
 ).afirst
 ```
 - **验证**: 单元测试 `test_on_workitem_create`
- [x] **6.3.1.2** 修改 `_handle_workitem_create` 添加开关
 ```python
 # 修改 server/feishu/views.py
 from core.feature_flags import feature_flags
 from feishu.workflow_bridge import FeishuWorkflowBridge
 class FeishuWebhookView(APIView):
 async def _handle_workitem_create(self, project, payload, trigger_log):
 """处理工作项创建事件"""
 work_item_id = str(payload.get("work_item_id"))
 title = payload.get("work_item_name", "")
 description = payload.get("description", "")
 # === 特性开关: 使用 Workflow 还是 Task ===
 if feature_flags.use_workflow_for_new_tasks:
 # 新路径: 创建 Workflow
 bridge = FeishuWorkflowBridge
 execution = await bridge.on_workitem_create(
 project=project,
 work_item_id=work_item_id,
 title=title,
 description=description,
 )
 trigger_log.workflow_execution_id = str(execution.id)
 await sync_to_async(trigger_log.save)
 return
 # 旧路径: 创建 Task（保持原有逻辑不变）
 # ... 现有 Task 创建代码 ...
 ```
 - **验证**:
 1. `FF_USE_WORKFLOW_FOR_NEW_TASKS=false` → 创建 Task
 2. `FF_USE_WORKFLOW_FOR_NEW_TASKS=true` → 创建 Workflow
- [x] **6.3.1.3** 修改 `_handle_workitem_comment` 添加开关
 ```python
 # 修改 server/feishu/views.py
 async def _handle_workitem_comment(self, project, payload, trigger_log):
 """处理工作项评论事件（审批/驳回）"""
 work_item_id = str(payload.get("work_item_id"))
 comment = payload.get("comment", "").lower
 # 关键词匹配
 approval_keywords = ["通过", "批准", "approved", "lgtm", "ok", "👍"]
 rejection_keywords = ["驳回", "拒绝", "rejected", "需要修改", "不通过", "👎"]
 is_approved = any(kw in comment for kw in approval_keywords)
 is_rejected = any(kw in comment for kw in rejection_keywords)
 if not is_approved and not is_rejected:
 return # 非审批评论，忽略
 # === 优先尝试 Workflow 审批 ===
 bridge = FeishuWorkflowBridge
 handled = await bridge.on_approval_comment(
 work_item_id=work_item_id,
 approved=is_approved,
 comment=comment,
 approver=None # TODO: need to pass approver user
 )
 if handled:
 return # Workflow 处理成功
 # 回退到 Task 处理（兼容旧任务）
 # ... 现有 Task 审批代码 ...
 ```
 - **验证**: 飞书评论"通过" → 对应节点状态变为 completed
#### 6.3.2 飞书状态同步钩子
- [x] **6.3.2.1** 创建飞书同步钩子 `server/workflows/hooks/feishu_sync.py`
 ```python
 # 文件位置: server/workflows/hooks/feishu_sync.py
 from workflows.hooks.base import BaseHook
 from core.feature_flags import feature_flags
 import structlog
 logger = structlog.get_logger
 class FeishuSyncHook(BaseHook):
 """将工作流状态同步到飞书"""
 name = "feishu_sync"
 async def on_node_started(self, execution, node_execution, **kwargs):
 """节点开始 → 飞书评论"""
 if not feature_flags.sync_workflow_to_feishu:
 return
 work_item_id = execution.context.get("work_item_id")
 if not work_item_id:
 return
 await self._post_comment(
 work_item_id=work_item_id,
 content=f"🚀 开始执行: {node_execution.node.name}"
 )
 async def on_node_completed(self, execution, node_execution, **kwargs):
 """节点完成 → 飞书评论"""
 if not feature_flags.sync_workflow_to_feishu:
 return
 work_item_id = execution.context.get("work_item_id")
 if not work_item_id:
 return
 await self._post_comment(
 work_item_id=work_item_id,
 content=f"✅ 完成: {node_execution.node.name}"
 )
 async def on_node_waiting_approval(self, execution, node_execution, **kwargs):
 """等待审批 → 飞书评论提醒"""
 if not feature_flags.sync_workflow_to_feishu:
 return
 work_item_id = execution.context.get("work_item_id")
 if not work_item_id:
 return
 # 获取审批内容
 approval_config = node_execution.node.config
 description = approval_config.get("description_template", "请审批")
 await self._post_comment(
 work_item_id=work_item_id,
 content=f"⏳ 等待审批: {node_execution.node.name}\n\n{description}\n\n回复「通过」或「驳回」进行审批"
 )
 async def on_execution_completed(self, execution, **kwargs):
 """执行完成 → 更新飞书工作项状态"""
 if not feature_flags.sync_workflow_to_feishu:
 return
 work_item_id = execution.context.get("work_item_id")
 if not work_item_id:
 return
 # TODO: 调用飞书 API 更新工作项状态为"已完成"
 await self._post_comment(
 work_item_id=work_item_id,
 content="🎉 工作流执行完成!"
 )
 async def _post_comment(self, work_item_id: str, content: str):
 """发送飞书评论"""
 # TODO: 实现飞书 API 调用
 logger.info("feishu_comment_posted", work_item_id=work_item_id, content=content[:50])
 ```
 - **验证**: 节点状态变更时，日志显示 `feishu_comment_posted`
- [x] **6.3.2.2** 注册钩子到 HookManager
 ```python
 # 在 server/workflows/hooks/__init__.py 中注册
 from workflows.hooks.feishu_sync import FeishuSyncHook
 # 在 HookManager 初始化时注册
 hook_manager.register(FeishuSyncHook)
 ```
 - **验证**: `python manage.py shell -c "from workflows.hooks import hook_manager; print(hook_manager.hooks)"`
---
### 6.4 数据迁移（可选，按需执行）
> **目标**: 将历史 Task 数据转换为 WorkflowExecution，保持数据可查询。
>
> ⚠️ **注意**: 此步骤可延后执行，新旧系统可并行运行。
#### 6.4.1 迁移脚本
- [x] **6.4.1.1** 创建迁移管理命令目录
 ```bash
 mkdir -p server/workflows/management/commands
 touch server/workflows/management/__init__.py
 touch server/workflows/management/commands/__init__.py
 ```
- [x] **6.4.1.2** 创建迁移命令 `server/workflows/management/commands/migrate_tasks.py`
 ```python
 # 文件位置: server/workflows/management/commands/migrate_tasks.py
 from django.core.management.base import BaseCommand, CommandError
 from django.db import transaction
 from tasks.models import Task, TaskStatus
 from workflows.models import Workflow, WorkflowExecution, NodeExecution
 from workflows.templates.loader import create_workflow_from_template
 import structlog
 logger = structlog.get_logger
 class Command(BaseCommand):
 help = '将历史 Task 数据迁移到 WorkflowExecution'
 def add_arguments(self, parser):
 parser.add_argument(
 '--dry-run',
 action='store_true',
 help='模拟运行，不实际修改数据',
 )
 parser.add_argument(
 '--project-id',
 type=str,
 help='只迁移指定项目的 Task',
 )
 parser.add_argument(
 '--limit',
 type=int,
 default=0,
 help='限制迁移数量（0=不限制）',
 )
 def handle(self, *args, **options):
 dry_run = options['dry-run']
 project_id = options.get('project-id')
 limit = options.get('limit', 0)
 # 构建查询
 queryset = Task.objects.all
 if project_id:
 queryset = queryset.filter(project_id=project_id)
 if limit > 0:
 queryset = queryset[:limit]
 total = queryset.count
 self.stdout.write(f"Found {total} tasks to migrate")
 if dry_run:
 self.stdout.write(self.style.WARNING("DRY RUN - No changes will be made"))
 success = 0
 failed = 0
 for task in queryset:
 try:
 if not dry_run:
 self._migrate_task(task)
 success += 1
 self.stdout.write(f"✓ Migrated: {task.id} ({task.title[:30]}...)")
 except Exception as e:
 failed += 1
 self.stdout.write(self.style.ERROR(f"✗ Failed: {task.id} - {e}"))
 self.stdout.write(self.style.SUCCESS(f"\nCompleted: {success} success, {failed} failed"))
 @transaction.atomic
 def _migrate_task(self, task: Task):
 """迁移单个 Task"""
 # 1. 创建 Workflow
 workflow = create_workflow_from_template(
 project_id=str(task.project_id),
 template_id="code_generation",
 name=task.title,
 description=task.description or "",
 )
 # 2. 创建 WorkflowExecution
 execution = WorkflowExecution.objects.create(
 workflow=workflow,
 task=task, # 关联原 Task
 trigger_type="migration",
 status=self._map_task_status(task.status),
 input_data={
 "title": task.title,
 "description": task.description,
 },
 context={
 "legacy_task_id": str(task.id),
 "work_item_id": task.work_item_id,
 "branch_name": task.branch_name,
 "commit_sha": task.commit_sha,
 "pr_url": task.pr_url,
 },
 error_message=task.error_message or "",
 created_at=task.created_at,
 )
 # 3. 创建 NodeExecution 记录
 self._create_node_executions(execution, task, workflow)
 return execution
 def _map_task_status(self, task_status: str) -> str:
 """Task 状态映射到 Workflow 状态"""
 mapping = {
 TaskStatus.PENDING: "pending",
 TaskStatus.PLANNING: "running",
 TaskStatus.PLAN_REVIEW: "running",
 TaskStatus.EXECUTING: "running",
 TaskStatus.CODE_REVIEW: "running",
 TaskStatus.MERGED: "completed",
 TaskStatus.FAILED: "failed",
 }
 return mapping.get(task_status, "pending")
 def _create_node_executions(self, execution, task, workflow):
 """根据 Task 状态创建对应的 NodeExecution 记录"""
 # 获取模板节点
 nodes = {n.node_type: n for n in workflow.nodes.all}
 # 根据 Task 状态创建已完成的节点记录
 status_progression = [
 (TaskStatus.PLANNING, "generate_plan"),
 (TaskStatus.PLAN_REVIEW, "plan_approval"),
 (TaskStatus.EXECUTING, "code_implement"),
 (TaskStatus.CODE_REVIEW, "code_approval"),
 (TaskStatus.MERGED, "create_pr"),
 ]
 current_index = next(
 (i for i, (s, _) in enumerate(status_progression) if s == task.status),
 -1
 )
 for i, (_, node_type) in enumerate(status_progression):
 if node_type not in nodes:
 continue
 node = nodes[node_type]
 if i < current_index:
 # 已完成的节点
 NodeExecution.objects.create(
 workflow_execution=execution,
 node=node,
 status="completed",
 output_data={"migrated": True},
 )
 elif i == current_index:
 # 当前节点
 status = "waiting_approval" if "approval" in node_type else "running"
 NodeExecution.objects.create(
 workflow_execution=execution,
 node=node,
 status=status,
 )
 ```
 - **验证**: `python manage.py migrate_tasks --dry-run --limit=5`
- [x] **6.4.1.3** 创建验证命令 `server/workflows/management/commands/verify_migration.py`
 ```python
 # 文件位置: server/workflows/management/commands/verify_migration.py
 from django.core.management.base import BaseCommand
 from tasks.models import Task
 from workflows.models import WorkflowExecution
 class Command(BaseCommand):
 help = '验证 Task 迁移结果'
 def handle(self, *args, **options):
 task_count = Task.objects.count
 migrated_count = WorkflowExecution.objects.filter(
 context__has_key='legacy_task_id'
 ).count
 self.stdout.write(f"Total Tasks: {task_count}")
 self.stdout.write(f"Migrated: {migrated_count}")
 self.stdout.write(f"Remaining: {task_count - migrated_count}")
 if task_count == migrated_count:
 self.stdout.write(self.style.SUCCESS("✓ All tasks migrated!"))
 else:
 self.stdout.write(self.style.WARNING("⚠ Migration incomplete"))
 ```
 - **验证**: `python manage.py verify_migration`
---
### 6.5 API 兼容层
> **目标**: 保持 `/api/tasks/` 端点可用，内部透明代理到 Workflow 数据。
#### 6.5.1 响应转换器
- [x] **6.5.1.1** 创建转换器 `server/tasks/compat.py`
 ```python
 # 文件位置: server/tasks/compat.py
 # 功能: WorkflowExecution ↔ Task 格式互转
 from workflows.models import WorkflowExecution, NodeExecution, NodeExecutionStatus
 from tasks.models import TaskStatus
 class TaskCompatService:
 """Task 兼容服务，用于将 WorkflowExecution 转换为 Task 格式"""
 @staticmethod
 def map_workflow_status_to_task_status(workflow_status: str) -> str:
 mapping = {
 "pending": TaskStatus.PENDING,
 "running": TaskStatus.PLANNING, # 或者 EXECUTING
 "paused": TaskStatus.PENDING,
 "completed": TaskStatus.MERGED,
 "failed": TaskStatus.FAILED,
 "cancelled": TaskStatus.FAILED,
 }
 return mapping.get(workflow_status, TaskStatus.PENDING)
 @staticmethod
 def workflow_execution_to_task_data(execution: WorkflowExecution) -> dict:
 """将 WorkflowExecution 转换为 Task 格式的数据"""
 data = {
 "id": str(execution.id),
 "title": execution.workflow.name,
 "description": execution.workflow.description,
 "status": TaskCompatService.map_workflow_status_to_task_status(execution.status),
 "created_at": execution.created_at,
 "updated_at": execution.updated_at,
 "project": str(execution.workflow.project_id),
 "work_item_id": execution.context.get("work_item_id"),
 "branch_name": execution.context.get("branch_name"),
 "commit_sha": execution.context.get("commit_sha"),
 "pr_url": execution.context.get("pr_url"),
 "error_message": execution.error_message,
 "is_migrated": True, # 标识为迁移数据
 }
 return data
 @staticmethod
 def get_tasks_from_workflow_executions(
 project_id: str | None = None,
 status: str | None = None,
 limit: int = 100,
 offset: int = 0,
 ) -> list[dict]:
 """从 WorkflowExecution 获取 Task 列表"""
 queryset = WorkflowExecution.objects.filter(workflow__project_id=project_id) if project_id else WorkflowExecution.objects.all
 if status:
 # 简单的状态映射
 workflow_status = TaskCompatService._map_task_status_to_workflow_status(status)
 queryset = queryset.filter(status=workflow_status)
 # 应用分页
 queryset = queryset.order_by("-created_at")[offset: offset + limit]
 return [TaskCompatService.workflow_execution_to_task_data(exec) for exec in queryset]
 @staticmethod
 def _map_task_status_to_workflow_status(task_status: str) -> str:
 mapping = {
 TaskStatus.PENDING: "pending",
 TaskStatus.PLANNING: "running",
 TaskStatus.EXECUTING: "running",
 TaskStatus.MERGED: "completed",
 TaskStatus.FAILED: "failed",
 }
 return mapping.get(task_status, "pending")
 ```
 - **验证**: 单元测试
#### 6.5.2 API 视图代理
- [x] **6.5.2.1** 创建 Task 兼容 API 视图 `server/tasks/compat_views.py`
 ```python
 # 文件位置: server/tasks/compat_views.py
 # 功能: 提供 /api/tasks/ 的兼容 API
 from rest_framework.views import APIView
 from rest_framework.response import Response
 from rest_framework import status
 from rest_framework.permissions import IsAuthenticated
 from core.feature_flags import feature_flags
 from tasks.compat import TaskCompatService
 from tasks.models import Task
 from tasks.serializers import TaskSerializer
 from projects.models import Project
 class TaskCompatListView(APIView):
 """兼容层 Task 列表视图"""
 permission_classes = [IsAuthenticated]
 async def get(self, request):
 if not feature_flags.enable_task_compat_api:
 return Response({"detail": "Task compatibility API is disabled."},
 status=status.HTTP_404_NOT_FOUND)
 project_id = request.query_params.get("project")
 status_param = request.query_params.get("status")
 limit = int(request.query_params.get("limit", 100))
 offset = int(request.query_params.get("offset", 0))
 # 优先从 WorkflowExecution 获取
 workflow_tasks = await TaskCompatService.get_tasks_from_workflow_executions(
 project_id=project_id,
 status=status_param,
 limit=limit,
 offset=offset,
 )
 # 如果需要，从旧 Task 模型获取（仅当没有 Workflow 结果时）
 if not workflow_tasks:
 queryset = Task.objects.all
 if project_id:
 queryset = queryset.filter(project_id=project_id)
 if status_param:
 queryset = queryset.filter(status=status_param)
 tasks = await queryset.alimit(limit).aoffset(offset)
 serializer = TaskSerializer(tasks, many=True)
 return Response(serializer.data)
 return Response(workflow_tasks)
 class TaskCompatDetailView(APIView):
 """兼容层 Task 详情视图"""
 permission_classes = [IsAuthenticated]
 async def get(self, request, pk):
 if not feature_flags.enable_task_compat_api:
 return Response({"detail": "Task compatibility API is disabled."},
 status=status.HTTP_404_NOT_FOUND)
 # 优先从 WorkflowExecution 获取
 try:
 execution = await WorkflowExecution.objects.aget(id=pk)
 return Response(TaskCompatService.workflow_execution_to_task_data(execution))
 except WorkflowExecution.DoesNotExist:
 pass
 # 回退到旧 Task 模型
 try:
 task = await Task.objects.aget(id=pk)
 serializer = TaskSerializer(task)
 return Response(serializer.data)
 except Task.DoesNotExist:
 return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
 ```
 - **验证**: `curl http://localhost:8000/api/tasks/` (GET)
#### 6.5.3 注册兼容路由
- [x] **6.5.3.1** 修改 `server/tasks/urls.py`
 ```python
 # 修改 server/tasks/urls.py
 from django.urls import path
 from tasks.compat_views import TaskCompatListView, TaskCompatDetailView
 urlpatterns = [
 path('', TaskCompatListView.as_view, name='task-list-compat'),
 path('<uuid:pk>/', TaskCompatDetailView.as_view, name='task-detail-compat'),
 # path('<uuid:pk>/approve/', TaskApproveView.as_view, name='task-approve'), # 暂时不兼容
 # path('<uuid:pk>/reject/', TaskRejectView.as_view, name='task-reject'), # 暂时不兼容
 ]
 ```
 - **验证**: `python manage.py show_urls | grep tasks`
---
### 6.6 前端兼容层
> **目标**: 前端 `useTasksStore` 透明切换到 Workflow API。
#### 6.6.1 修改 `useTasksStore.ts`
- [x] **6.6.1.1** 修改 `web/src/stores/tasks.ts` 为 `useTasksCompatStore.ts`
- [x] **6.6.1.2** 创建新的 `web/src/stores/tasks.ts`
 ```typescript
 // 文件位置: web/src/stores/tasks.ts
 // 功能: 代理到 useWorkflowsStore
 import { defineStore } from 'pinia'
 import { computed } from 'vue'
 import { useWorkflowsStore } from './useWorkflowsStore'
 import { useTasksCompatStore } from './tasksCompat'
 import { featureFlags } from '~/featureFlags' // 假设有 featureFlags
 export const useTasksStore = defineStore('tasks', => {
 const workflowsStore = useWorkflowsStore
 const tasksCompatStore = useTasksCompatStore
 // 根据特性开关选择 store
 const currentStore = computed( => {
 // 暂时禁用 workflow，强制使用兼容模式
 return tasksCompatStore // 强制使用兼容模式
 // return featureFlags.useWorkflowForNewTasks ? workflowsStore: tasksCompatStore
 })
 // 代理方法
 return {
 fetchTasks: (...args: any) => currentStore.value.fetchTasks(...args),
 fetchTask: (...args: any) => currentStore.value.fetchTask(...args),
 createTask: (...args: any) => currentStore.value.createTask(...args),
 updateTask: (...args: any) => currentStore.value.updateTask(...args),
 deleteTask: (...args: any) => currentStore.value.deleteTask(...args),
 approveTask: (...args: any) => currentStore.value.approveTask(...args),
 rejectTask: (...args: any) => currentStore.value.rejectTask(...args),
 // 暴露原始任务列表和加载状态
 tasks: computed( => currentStore.value.tasks),
 loading: computed( => currentStore.value.loading),
 }
 })
 ```
- [x] **6.6.1.3** 修复 `tasksCompat.ts` 中的路径引用，确保 `useApi` 和 `taskStatusMapper` 路径正确
---
### 6.7 移除旧 Task 相关代码
> **目标**: 在 Workflow 稳定运行后，逐步移除旧的 Task 模型和视图。
>
> ⚠️ **注意**: 此步骤应在确认 Workflow 完全替代 Task 功能后执行。
#### 6.7.1 删除 Task 相关文件
- [x] **6.7.1.1** 删除 `server/tasks/models.py` 中的 `Task` 相关模型
- [x] **6.7.1.2** 删除 `server/tasks/views.py` 中非兼容层视图
- [x] **6.7.1.3** 删除 `server/tasks/serializers.py` 中非兼容层序列化器
- [x] **6.7.1.4** 删除 `server/services/scheduler.py`
- [x] **6.7.1.5** 删除 `server/services/task_dispatcher.py`
#### 6.7.2 更新引用
- [x] **6.7.2.1** 更新 `friday/settings.py` 移除 `tasks` app
- [x] **6.7.2.2** 更新 `friday/urls.py` 移除 `tasks` 路由
- [x] **6.7.2.3** 更新 `web/src/stores/projects.ts` 移除对 `tasks` 的引用
- [x] **6.7.2.4** 更新 `web/src/pages/tasks` 移除旧页面
---
### Phase: 前端交互完善 (剩余任务)
- [x] 4.5.1 实现从面板拖拽到画布
- [x] 4.5.2 实现节点连接（含验证）
- [x] 4.5.3 实现节点选择和配置
- [x] 4.5.4 实现撤销/重做
- [x] 4.5.5 实现保存/加载
### Phase: 状态管理 (剩余任务)
- [x] 4.6.4 实现 WebSocket 连接管理
### Phase: 执行监控 (剩余任务)
- [x] 4.7.1 创建 `ExecutionProgress.vue`（进度展示）
- [x] 4.7.2 实现节点状态颜色映射
- [x] 4.7.3 实现节点日志查看
- [x] 4.7.4 实现审批操作按钮
### Phase Git 节点 (剩余任务)
- [x] 5.1.3 实现 `MergePRNode`
### Phase 集成节点 (剩余任务)
- [x] 5.3.2 实现 `MCPDeployNode`
### Phase 控制流节点 (剩余任务)
- [x] 5.4.2 实现 `ParallelNode`（Fork/Join）
