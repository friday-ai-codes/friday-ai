## 0. 后端增强
- 0.1 修改 `server/workflows/api/serializers.py`
 - 为 `WorkflowListSerializer` 添加 `last_execution` 字段
 - 复用 `WorkflowSerializer` 中的 `get_last_execution` 方法逻辑
## 1. 核心页面
- 1.1 创建 `web/src/pages/executions/index.vue` 全局执行监控页面
 - 状态统计卡片（运行中、待审批、已完成、失败）
 - 执行列表，支持筛选（项目、工作流、状态）
 - Glassmorphism 设计风格
- 1.2 创建 `web/src/pages/executions/[id].vue` 执行详情页
 - 迁移现有 `/workflows/executions/[id].vue` 逻辑
 - 节点执行时间线
 - 操作按钮（暂停/恢复/取消）
## 2. 通用组件
- 2.1 创建 `web/src/components/execution/ExecutionStatusBadge.vue`
 - 支持所有执行状态（pending, running, paused, completed, failed, cancelled, waiting_approval）
 - 运行中状态显示动画
- 2.2 创建 `web/src/components/execution/ExecutionCard.vue`
 - 复用的执行列表卡片组件
 - 显示工作流名称、状态、进度、触发类型、时间
## 3. 导航栏更新
- 3.1 修改 `web/src/layouts/default.vue`
 - 将 `{ to: '/tasks', label: '任务' }` 替换为 `{ to: '/executions', label: '执行', icon: 'lucide--play-circle' }`
## 4. Store 增强
- 4.1 增强 `web/src/stores/useExecutionsStore.ts`
 - 添加 `stats` computed 属性（统计各状态数量）
 - 添加 `startAutoRefresh(interval)` 方法（轮询活跃执行）
 - 添加 `stopAutoRefresh` 方法
## 5. 工作流卡片增强
- 5.1 修改 `web/src/pages/workflows/index.vue`
 - 工作流卡片显示最近执行状态
 - 显示执行次数统计
 - 添加"查看执行历史"链接
## 6. 验证
- 6.1 页面访问测试
 - 验证 `/executions` 页面正常加载
 - 验证 `/executions/[id]` 详情页正常加载
- 6.2 功能测试
 - 手动触发工作流，验证执行记录出现
 - 测试筛选功能
 - 测试暂停/恢复/取消操作
- 6.3 导航测试
 - 验证顶部导航"执行"链接正确
