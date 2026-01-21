## ADDED Requirements
### Requirement: 触发工作项日志
系统 SHALL 将 Webhook 请求日志和工作项详情日志合并为统一的「触发工作项日志」（TriggerLog），记录完整的事件处理链路。
#### Scenario: 记录触发日志
- **WHEN** 系统收到 WorkitemStatusEvent 等触发事件
- **AND** 成功获取工作项详情
- **THEN** 系统创建 TriggerLog 记录
- **AND** 保存 Webhook 原始请求 JSON
- **AND** 保存工作项详情 API 响应 JSON
- **AND** 提取并保存关键字段（需求文档链接、需求描述、技术方案文档链接）
#### Scenario: 查询触发日志列表
- **WHEN** 用户调用 GET /api/logs/triggers 接口
- **THEN** 系统返回分页的触发日志列表
- **AND** 每条记录包含摘要信息（时间、项目、事件类型、工作项名称、状态）
- **AND** 包含提取的关键字段值
- **AND** 不返回原始 JSON 数据（减少传输量）
#### Scenario: 查看触发日志详情
- **WHEN** 用户调用 GET /api/logs/triggers/{id} 接口
- **THEN** 系统返回日志详情
- **AND** 包含 event_uuid、work_item_type 等完整信息
- **AND** 不返回原始 JSON 数据
#### Scenario: 获取原始数据
- **WHEN** 用户调用 GET /api/logs/triggers/{id}/raw 接口
- **THEN** 系统返回完整的原始 JSON 数据
- **AND** 包含 webhook_request 和 work_item_response 两部分
### Requirement: 前端触发日志展示
系统 SHALL 提供前端界面用于查看触发工作项日志，支持关键字段突出展示和原始数据 JSON 高亮。
#### Scenario: 访问触发日志列表
- **WHEN** 用户访问 /logs/triggers 页面
- **THEN** 页面显示按时间倒序排列的日志列表
- **AND** 每行显示时间、项目、事件类型、工作项名称、状态
- **AND** 支持按项目、事件类型、时间范围过滤
#### Scenario: 查看日志详情
- **WHEN** 用户点击日志列表中的某条记录
- **THEN** 导航到 /logs/triggers/:id 详情页
- **AND** 显示基本信息卡片
- **AND** 突出显示关键字段卡片（需求文档链接、需求描述、技术方案文档链接）
- **AND** 提供复制链接按钮
#### Scenario: 展开原始数据
- **WHEN** 用户点击「展开原始数据」按钮
- **THEN** 前端调用 GET /api/logs/triggers/{id}/raw 获取原始数据
- **AND** 使用 shiki 库对 JSON 进行语法高亮
- **AND** 以可折叠面板形式展示 Webhook 请求和工作项详情
#### Scenario: 折叠原始数据
- **WHEN** 原始数据已展开
- **AND** 用户点击「折叠」按钮
- **THEN** 隐藏原始数据区域
- **AND** 保留已加载的数据（避免重复请求）
### Requirement: 前端触发日志类型定义
前端项目 SHALL 定义触发日志相关的 TypeScript 类型，支持工作项 fields 数组的类型安全访问。
新增类型：
- `TriggerLog` - 触发日志列表项
- `TriggerLogDetail` - 触发日志详情
- `TriggerLogRaw` - 原始数据响应
- `WorkItemField` - 工作项字段通用类型
- `WorkItemData` - 工作项数据类型
- `KEY_FIELDS` - 关键字段常量（field_bcff9b、description、field_3f6667）
#### Scenario: 类型安全的字段访问
- **WHEN** 前端需要访问工作项的特定字段
- **THEN** 使用 KEY_FIELDS 常量获取字段 key
- **AND** TypeScript 编译器能检查类型错误
- **AND** 提供字段值的类型推断
## MODIFIED Requirements
### Requirement: Webhook 事件处理
系统 SHALL 支持处理飞书项目自动化规则触发的 Webhook 事件。
支持的事件类型（基于飞书项目文档）：
| event_type | 触发场景 |
|------------|---------|
| WorkitemCreateEvent | 创建工作项 |
| WorkitemUpdateEvent | 字段值修改 |
| WorkitemStatusEvent | 工作项状态修改 |
| WorkFlowNodeStatusEvent | 工作项节点流转 |
| WorkitemFinishEvent | 完成工作项 |
| WorkitemDeleteEvent | 删除工作项 |
| WorkitemCommentEvent | 评论操作 |
#### Scenario: 处理工作项创建事件
- **WHEN** 系统收到 event_type 为 WorkitemCreateEvent 的请求
- **THEN** 系统解析 payload 中的工作项信息
- **AND** 包括 id、name、project_key、work_item_type_key、fields 等
- **AND** 创建对应的 Task 记录
- **AND** 创建 TriggerLog 记录
#### Scenario: 处理工作项状态变更事件
- **WHEN** 系统收到 event_type 为 WorkitemStatusEvent 的请求
- **THEN** 系统解析 pre_work_item_status 和 cur_work_item_status
- **AND** 根据状态变化触发相应的自动化流程
- **AND** 创建 TriggerLog 记录（包含 Webhook 请求和工作项详情）
#### Scenario: 处理节点流转事件
- **WHEN** 系统收到 event_type 为 WorkFlowNodeStatusEvent 的请求
- **THEN** 系统解析 nodes 列表中的节点状态变化
- **AND** status_change_type 可能为 Rollback/Reached/Checked
- **AND** 根据节点状态触发相应流程
#### Scenario: 处理评论事件
- **WHEN** 系统收到 event_type 为 WorkitemCommentEvent 的请求
- **THEN** 系统解析 payload.comment 内容
- **AND** 检查评论中的审批关键词
- **AND** 触发相应的审批流程
#### Scenario: 幂等处理
- **WHEN** 系统收到 Webhook 请求
- **THEN** 系统使用 header.uuid 作为幂等标识
- **AND** 避免重复处理同一事件
