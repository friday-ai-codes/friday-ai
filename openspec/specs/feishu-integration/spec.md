# feishu-integration Specification
## Purpose
TBD - created by archiving change add-multi-project-feishu-integration. Update Purpose after archive.
## Requirements
### Requirement: 项目级飞书凭证配置
Project 模型 SHALL 仅包含飞书集成配置，不再包含 Git 配置。Webhook Token 独立于插件凭证进行管理。
#### Scenario: 配置飞书插件凭证
- **WHEN** 用户调用设置飞书配置接口
- **THEN** 系统更新 Project 的飞书凭证字段（plugin_id、plugin_secret）
- **AND** 不影响 webhook_token 字段
- **AND** 不影响任何 Git 仓库配置
#### Scenario: 查看飞书配置状态
- **WHEN** 用户获取飞书配置
- **THEN** 系统返回 plugin_id、has_plugin_secret、is_configured
- **AND** 不返回 webhook_token 相关信息（由项目接口返回）
### Requirement: 动态 Webhook 验证
系统 SHALL 根据 Webhook 请求体中的 `project_key`（位于 payload 中）或 `header.token` 动态选择对应项目的 Webhook Token 进行签名验证。
根据飞书项目 Webhook 文档，所有事件的请求结构如下：
```json
{
 "header": {
 "operator": "", // 操作者的 userkey
 "event_type": "", // webhook 的 event_type
 "token": "", // 注册 webhook 填入的 token
 "uuid": "" // 幂等串
 },
 "payload": {
 "project_key": "", // 空间 ID
 ...
 }
}
```
#### Scenario: 验证成功
- **WHEN** 飞书项目发送 Webhook 请求到 /api/webhook/feishu
- **AND** 请求体中 payload.project_key 存在
- **AND** 系统能找到对应 feishu_project_key 的 Project 配置
- **AND** 使用该项目的 webhook_token 与 header.token 进行验证
- **THEN** 系统接受并处理该请求
#### Scenario: 项目未配置 Token 时跳过验证
- **WHEN** 飞书项目发送 Webhook 请求
- **AND** 对应的 Project 未配置 feishu_webhook_token
- **THEN** 系统跳过 Token 验证，仍然处理请求（向后兼容）
#### Scenario: 验证失败
- **WHEN** 飞书项目发送 Webhook 请求
- **AND** header.token 与项目配置的 webhook_token 不匹配
- **THEN** 系统返回 401 Unauthorized
#### Scenario: 找不到对应项目
- **WHEN** 飞书项目发送 Webhook 请求
- **AND** 系统找不到 project_key 对应的 Project
- **THEN** 系统返回 {"status": "ignored", "reason": "project not found"}
### Requirement: 动态飞书 API 客户端
系统 SHALL 根据项目配置的插件凭证动态创建飞书 API 客户端，而非使用全局单例。
#### Scenario: 根据项目创建客户端
- **WHEN** 系统需要为某个 Project 调用飞书 API
- **THEN** 系统从 Project 模型中获取 plugin_id 和解密后的 plugin_secret
- **AND** 创建独立的 FeishuClient 实例
#### Scenario: 项目未配置凭证时报错
- **WHEN** 系统需要调用飞书 API
- **AND** 对应的 Project 未配置 feishu_plugin_id 或 feishu_plugin_secret
- **THEN** 系统抛出 FeishuConfigurationError 异常
### Requirement: 获取工作项详情
系统 SHALL 支持调用飞书项目「获取工作项详情」API 获取工作项的完整信息。
API 接口规格（根据飞书文档）：
- 请求方式：POST
- 请求地址：/open_api/:project_key/work_item/:work_item_type_key/query
- 请求体：`{"work_item_ids": [id1, id2, ...], "fields": ["字段列表"]}`
#### Scenario: 获取单个工作项详情
- **WHEN** 系统调用 get_work_item 方法
- **AND** 传入 project_key、work_item_id 和 work_item_type
- **THEN** 系统调用 POST /open_api/{project_key}/work_item/{work_item_type}/query
- **AND** 请求体为 {"work_item_ids": [work_item_id]}
- **AND** 返回解析后的 WorkItemInfo 对象
#### Scenario: 批量获取工作项详情
- **WHEN** 系统调用 get_work_items 方法
- **AND** 传入 project_key、work_item_ids 列表（最多 50 个）和 work_item_type
- **THEN** 系统调用相同的 API 批量获取
- **AND** 返回 WorkItemInfo 列表
#### Scenario: 解析工作项字段
- **WHEN** 系统收到飞书 API 返回的工作项数据
- **THEN** 系统解析以下关键字段：
 - id: 工作项 ID
 - name: 工作项名称
 - work_item_type_key: 工作项类型
 - work_item_status: 状态信息（state_key, is_archived_state）
 - fields: 字段列表（包含 description、owner 等）
 - current_nodes: 当前节点列表（仅节点流）
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
### Requirement: 数据模型扩展
Project 模型 SHALL 移除 Git 相关字段，保留飞书配置字段。
#### Scenario: Project 模型结构
- **WHEN** 查看 Project 模型定义
- **THEN** 包含 feishu_project_key, feishu_plugin_id, feishu_plugin_secret_encrypted 等字段
- **AND** 不包含 repo_url, git_platform 等字段
### Requirement: 前端飞书配置管理
系统 SHALL 提供前端界面用于管理项目的飞书集成配置。Webhook Token 在项目级别管理，不在飞书配置表单中。
#### Scenario: 查看飞书配置状态
- **WHEN** 用户访问项目详情页
- **THEN** 页面显示飞书配置状态卡片
- **AND** 显示「已配置」或「未配置」状态
- **AND** 显示各字段配置状态指示器（不包含 Webhook Token）
#### Scenario: 配置飞书凭证
- **WHEN** 用户点击「配置飞书集成」按钮
- **AND** 填写 Plugin ID、Plugin Secret
- **AND** 点击提交
- **THEN** 前端调用 POST /api/projects/{id}/feishu-config
- **AND** 成功后显示成功提示
- **AND** 更新配置状态显示
#### Scenario: 测试飞书凭证
- **WHEN** 用户点击「测试凭证」按钮
- **THEN** 前端调用 POST /api/projects/{id}/feishu-config/test
- **AND** 显示测试结果（成功/失败）
- **AND** 显示详细消息
#### Scenario: 删除飞书配置
- **WHEN** 用户点击「删除配置」按钮
- **AND** 确认删除操作
- **THEN** 前端调用 DELETE /api/projects/{id}/feishu-config
- **AND** 成功后更新配置状态显示
- **AND** 不影响 Webhook Token
### Requirement: 前端类型定义
前端项目 SHALL 定义飞书配置相关的 TypeScript 类型。Webhook Token 类型独立于飞书配置类型。
新增类型：
- `FeishuConfig` - 配置状态响应（不含 webhook_token）
- `FeishuConfigCreate` - 配置创建请求（不含 webhook_token）
- `FeishuConfigTestResult` - 凭证测试结果
- `WebhookTokenUpdate` - Webhook Token 更新请求
#### Scenario: 类型安全的 API 调用
- **WHEN** 前端调用飞书配置 API
- **THEN** 请求和响应均有正确的类型定义
- **AND** TypeScript 编译器能检查类型错误
### Requirement: 前端路由扩展
前端项目 SHALL 添加飞书配置管理页面路由。
#### Scenario: 导航到飞书配置页
- **WHEN** 用户在项目详情页点击「飞书配置」链接
- **THEN** 导航到 /projects/:id/feishu-config 页面
- **AND** 显示飞书配置表单
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
### Requirement: 项目级 Webhook Token 自动生成
系统 SHALL 在创建项目时自动生成一个唯一的 Webhook Token，用于验证飞书项目发送的 Webhook 请求。
#### Scenario: 创建项目时自动生成 Token
- **WHEN** 用户创建新项目
- **THEN** 系统自动生成一个 16 字符的随机 Token（使用 `secrets.token_urlsafe`）
- **AND** 将 Token 保存到 Project 的 webhook_token 字段
- **AND** 在项目创建响应中返回此 Token
#### Scenario: 查看项目详情时显示 Token
- **WHEN** 用户查看项目详情
- **THEN** 系统返回项目的 webhook_token 字段
- **AND** 前端显示 Token 及复制按钮
### Requirement: Webhook Token 刷新功能
系统 SHALL 支持用户主动刷新项目的 Webhook Token，生成新的随机 Token。
#### Scenario: 刷新 Webhook Token
- **WHEN** 用户调用 POST /api/projects/{id}/refresh-webhook-token
- **THEN** 系统生成新的 16 字符随机 Token
- **AND** 更新 Project 的 webhook_token 字段
- **AND** 返回新的 Token
#### Scenario: 前端刷新确认
- **WHEN** 用户点击「刷新 Token」按钮
- **THEN** 系统显示确认对话框，提示刷新后需要更新飞书项目配置
- **AND** 用户确认后调用刷新接口
### Requirement: Webhook Token 自定义功能
系统 SHALL 支持用户自定义 Webhook Token，但限制最大长度为 32 个字符。
#### Scenario: 自定义 Webhook Token
- **WHEN** 用户调用 PUT /api/projects/{id}/webhook-token
- **AND** 请求体包含 token 字段（最大 32 字符）
- **THEN** 系统更新 Project 的 webhook_token 字段
- **AND** 返回更新后的 Token
#### Scenario: Token 长度验证
- **WHEN** 用户提交超过 32 字符的 Token
- **THEN** 系统返回 400 错误
- **AND** 提示 Token 长度不能超过 32 个字符
#### Scenario: 前端自定义 Token 输入
- **WHEN** 用户在输入框中输入自定义 Token
- **THEN** 前端验证长度不超过 32 个字符
- **AND** 用户点击保存后调用更新接口
### Requirement: Webhook Token 安全提示
系统 SHALL 在前端显示 Webhook Token 时提供安全警告，告知用户此 Token 的用途和安全注意事项。
#### Scenario: 显示安全警告
- **WHEN** 前端显示 Webhook Token
- **THEN** 在 Token 下方显示安全警告
- **AND** 警告内容包含：「此 Token 用于验证飞书项目 Webhook 请求的来源，请勿泄露给他人」
- **AND** 说明在飞书项目自动化规则中配置 Webhook 时需要填入此 Token
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
