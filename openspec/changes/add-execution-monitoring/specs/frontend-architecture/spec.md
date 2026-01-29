## ADDED Requirements
### Requirement: 执行监控页面
前端项目 SHALL 提供全局执行监控页面，用于查看所有工作流执行记录。
#### Scenario: 访问执行监控页面
- **WHEN** 用户访问 `/executions`
- **THEN** 显示执行监控页面
- **AND** 展示状态统计卡片（运行中、待审批、已完成、失败数量）
- **AND** 展示执行记录列表
#### Scenario: 执行列表筛选
- **WHEN** 用户选择筛选条件（项目、工作流、状态）
- **THEN** 列表应根据条件过滤显示
- **AND** 筛选状态应在 URL 中持久化
#### Scenario: 执行列表空状态
- **WHEN** 没有执行记录或筛选结果为空
- **THEN** 显示友好的空状态提示
- **AND** 提供创建工作流的引导链接
---
### Requirement: 执行详情页面
前端项目 SHALL 提供执行详情页面，用于查看单次执行的完整信息。
#### Scenario: 访问执行详情页
- **WHEN** 用户访问 `/executions/[id]`
- **THEN** 显示执行详情页面
- **AND** 展示执行状态、进度、耗时等基本信息
- **AND** 展示节点执行时间线
#### Scenario: 执行操作按钮
- **WHEN** 执行状态为 `running`
- **THEN** 显示「暂停」和「取消」按钮
- **WHEN** 执行状态为 `paused`
- **THEN** 显示「恢复」和「取消」按钮
#### Scenario: 节点执行详情
- **WHEN** 用户点击某个节点
- **THEN** 展开显示节点的输入、输出、日志信息
- **AND** 如果节点失败，显示错误信息和堆栈
---
### Requirement: 执行状态徽章组件
前端项目 SHALL 提供可复用的执行状态徽章组件。
#### Scenario: 状态显示
- **WHEN** 传入执行状态
- **THEN** 显示对应颜色和图标的徽章
- **AND** 状态映射如下：
 - `pending`: 灰色，时钟图标
 - `running`: 蓝色，加载动画图标
 - `paused`: 黄色，暂停图标
 - `completed`: 绿色，勾选图标
 - `failed`: 红色，叉号图标
 - `cancelled`: 灰色，方块图标
 - `waiting_approval`: 橙色，用户确认图标
#### Scenario: 运行中动画
- **WHEN** 状态为 `running`
- **THEN** 图标应显示旋转动画
---
### Requirement: 导航栏执行入口
前端项目 SHALL 在主导航栏提供执行监控入口，替代废弃的任务入口。
#### Scenario: 导航栏显示
- **WHEN** 用户查看主导航菜单
- **THEN** 显示「执行」导航链接（替代原「任务」）
- **AND** 使用 `lucide--play-circle` 图标
- **AND** 点击后跳转到 `/executions` 页面
#### Scenario: 导航激活状态
- **WHEN** 用户在 `/executions` 或 `/executions/[id]` 页面
- **THEN** 「执行」导航项应显示激活状态
---
### Requirement: Executions Store 增强
前端项目 SHALL 增强 Executions Store 以支持统计和自动刷新功能。
#### Scenario: 执行统计
- **WHEN** 调用 `executionsStore.stats`
- **THEN** 返回各状态的执行数量统计
- **AND** 包含 `total`, `running`, `pending`, `waitingApproval`, `completed`, `failed` 字段
#### Scenario: 自动刷新
- **WHEN** 调用 `executionsStore.startAutoRefresh(interval)`
- **THEN** 每隔指定间隔自动刷新执行列表
- **AND** 仅在有活跃执行时刷新
#### Scenario: 停止自动刷新
- **WHEN** 调用 `executionsStore.stopAutoRefresh`
- **THEN** 停止自动刷新定时器
---
## MODIFIED Requirements
### Requirement: 工作流管理页面
前端项目 SHALL 提供工作流管理页面，用于查看和管理所有工作流模板，并展示执行状态概览。
#### Scenario: 工作流列表页
- **WHEN** 用户访问 `/workflows`
- **THEN** 显示工作流卡片网格
- **AND** 每个卡片显示工作流名称、描述、触发类型
- **AND** 每个卡片显示最近执行状态徽章
- **AND** 每个卡片显示执行次数统计
#### Scenario: 工作流执行历史入口
- **WHEN** 用户查看工作流卡片
- **THEN** 卡片底部显示「查看执行历史」链接
- **AND** 点击后跳转到 `/executions?workflow_id=[id]`
#### Scenario: 创建工作流
- **WHEN** 用户点击「新建工作流」按钮
- **THEN** 弹出创建工作流对话框
- **AND** 创建成功后刷新列表
#### Scenario: 编辑工作流
- **WHEN** 用户点击工作流卡片
- **THEN** 跳转到工作流编辑器页面 `/workflows/[id]`
