## ADDED Requirements
### Requirement: Webhook 请求日志
系统 SHALL 记录所有飞书 Webhook 请求的原始数据到数据库，支持问题追溯和调试。
#### Scenario: 记录 Webhook 请求
- **WHEN** 系统收到飞书 Webhook 请求
- **THEN** 系统创建 WebhookLog 记录
- **AND** 保存完整的原始请求 JSON
- **AND** 记录 event_uuid、event_type、project_key
- **AND** 记录处理状态（accepted、ignored、error）
#### Scenario: 记录处理错误
- **WHEN** Webhook 处理过程中发生错误
- **THEN** 系统在 WebhookLog 中记录错误信息
- **AND** 设置状态为 error
#### Scenario: 查询 Webhook 日志列表
- **WHEN** 用户调用 GET /api/logs/webhooks 接口
- **THEN** 系统返回分页的 Webhook 日志列表
- **AND** 支持按 project_id、event_type、status、时间范围过滤
#### Scenario: 查看 Webhook 日志详情
- **WHEN** 用户调用 GET /api/logs/webhooks/{id} 接口
- **THEN** 系统返回完整的日志记录
- **AND** 包含解析后的原始 JSON 数据
### Requirement: 工作项详情日志
系统 SHALL 记录每次从飞书 API 获取的工作项详情到数据库，支持数据追溯。
#### Scenario: 记录工作项详情
- **WHEN** 系统调用 get_work_item 方法获取工作项详情
- **THEN** 系统创建 WorkItemLog 记录
- **AND** 保存完整的 API 响应 JSON
- **AND** 关联 project_id 和 task_id（如果有）
#### Scenario: 查询工作项日志列表
- **WHEN** 用户调用 GET /api/logs/work-items 接口
- **THEN** 系统返回分页的工作项日志列表
- **AND** 支持按 project_id、task_id、work_item_id、时间范围过滤
#### Scenario: 查看工作项日志详情
- **WHEN** 用户调用 GET /api/logs/work-items/{id} 接口
- **THEN** 系统返回完整的日志记录
- **AND** 包含解析后的原始 JSON 数据
### Requirement: 前端日志查看
系统 SHALL 提供前端界面用于查看飞书相关的日志数据。
#### Scenario: 访问日志列表页面
- **WHEN** 用户访问日志管理页面
- **THEN** 页面显示 Webhook 日志和工作项日志的切换选项
- **AND** 显示按时间倒序排列的日志列表
- **AND** 每条日志显示关键信息摘要
#### Scenario: 查看日志详情
- **WHEN** 用户点击日志列表中的某条记录
- **THEN** 页面显示日志详情
- **AND** 以格式化的 JSON 形式展示原始数据
- **AND** 支持复制原始 JSON
#### Scenario: 过滤日志
- **WHEN** 用户设置过滤条件
- **THEN** 页面显示符合条件的日志
- **AND** 支持按项目、事件类型、时间范围过滤
### Requirement: 日志数据管理
系统 SHALL 支持日志数据的自动清理，防止数据无限增长。
#### Scenario: 配置日志保留时间
- **WHEN** 管理员配置日志保留天数
- **THEN** 系统保存配置
- **AND** 在后续清理时使用此配置
#### Scenario: 自动清理过期日志
- **WHEN** 系统执行定期清理任务
- **THEN** 系统删除超过保留期限的日志记录
- **AND** 记录清理操作的统计信息
### Requirement: 前端日志类型定义
前端项目 SHALL 定义日志相关的 TypeScript 类型。
新增类型：
- `WebhookLog` - Webhook 日志记录
- `WebhookLogDetail` - 包含解析后 JSON 的详情
- `WorkItemLog` - 工作项日志记录
- `WorkItemLogDetail` - 包含解析后 JSON 的详情
- `LogListQuery` - 日志查询参数
- `LogListResponse` - 分页日志响应
#### Scenario: 类型安全的日志 API 调用
- **WHEN** 前端调用日志相关 API
- **THEN** 请求和响应均有正确的类型定义
- **AND** TypeScript 编译器能检查类型错误
