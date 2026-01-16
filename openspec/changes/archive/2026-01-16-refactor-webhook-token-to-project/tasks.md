## 1. 后端实现
- [x] 1.1 更新 Project 模型，添加自动生成 webhook_token 的逻辑
- [x] 1.2 更新 ProjectRead schema，返回 webhook_token 字段
- [x] 1.3 更新 FeishuConfigCreate schema，移除 webhook_token 字段
- [x] 1.4 更新 FeishuConfigRead schema，移除 has_webhook_token 字段
- [x] 1.5 修改 create_project API，创建项目时自动生成 Token
- [x] 1.6 新增 POST /api/projects/{id}/refresh-webhook-token 接口
- [x] 1.7 新增 PUT /api/projects/{id}/webhook-token 接口（自定义 Token，最大 32 字符）
- [x] 1.8 更新 set_feishu_config API，移除 webhook_token 处理逻辑
## 2. 前端类型定义
- [x] 2.1 更新 Project 类型，添加 webhook_token 字段
- [x] 2.2 更新 FeishuConfig 类型，移除 has_webhook_token
- [x] 2.3 更新 FeishuConfigCreate 类型，移除 webhook_token
- [x] 2.4 新增 WebhookTokenUpdate 类型
## 3. 前端 API 层
- [x] 3.1 新增 refreshWebhookToken API
- [x] 3.2 新增 updateWebhookToken API
## 4. 前端 UI 调整
- [x] 4.1 更新飞书配置页面/项目详情页，添加 Webhook Token 显示区域
- [x] 4.2 实现 Token 复制功能
- [x] 4.3 实现刷新 Token 按钮和确认对话框
- [x] 4.4 实现自定义 Token 输入（最大 32 字符验证）
- [x] 4.5 添加安全警告提示
- [x] 4.6 更新飞书配置表单，移除 Webhook Token 输入框
- [x] 4.7 更新使用说明
## 5. 测试
- [x] 5.1 更新后端测试用例
- [x] 5.2 验证 Webhook Token 自动生成
- [x] 5.3 验证刷新和自定义 Token 功能
