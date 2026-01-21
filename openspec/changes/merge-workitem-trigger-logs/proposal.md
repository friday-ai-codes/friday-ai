# Change: 合并工作项触发日志
## Why
当前系统在处理 `WorkitemStatusEvent` 等事件时，会分别记录两种日志：
1. **WebhookLog** - 记录飞书 Webhook 原始请求
2. **WorkItemLog** - 记录从飞书 API 获取的工作项详情
这两种日志在业务上紧密关联（收到 Webhook 后必然调用 API 获取详情），但在数据库和前端展示中是分离的，导致：
- 查看日志时需要在两个列表间切换
- 难以追溯完整的事件处理链路
- 前端需要展示两种不同格式的原始数据
## What Changes
- 创建统一的 `TriggerLog` 模型，合并 Webhook 请求和工作项详情
- 前端展示合并后的「触发工作项日志」列表
- 原始数据默认折叠，点击展开时使用 shiki 高亮显示 JSON
- 关键字段（需求文档链接、需求描述、技术方案文档链接）提取并突出展示
- 定义清晰的 TypeScript 类型，支持工作项 fields 数组的类型安全访问
## Impact
- Affected specs: `feishu-integration`
- Affected code:
 - `server/webhooks/models.py` - 新增/修改模型
 - `server/webhooks/views.py` - 修改日志记录逻辑
 - `server/webhooks/serializers.py` - 新增序列化器
 - `web/src/types/logs.ts` - 新增类型定义
 - `web/src/components/logs/` - 日志展示组件
 - `web/src/pages/logs/` - 日志页面
