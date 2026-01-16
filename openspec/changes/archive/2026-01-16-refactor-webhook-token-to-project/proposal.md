# Change: 将 Webhook Token 从插件凭证分离为项目级配置
## Why
当前 Webhook Token 与飞书插件凭证（Plugin ID、Plugin Secret）绑定在一起，需要在配置飞书插件时一起设置。但实际上 Webhook Token 的用途与插件凭证完全不同：
- **飞书插件凭证**：用于调用飞书项目 API（获取工作项详情、更新状态等）
- **Webhook Token**：用于验证飞书项目发送过来的 Webhook 请求的真实性
将两者分离可以：
1. 降低配置复杂度，Webhook Token 在创建项目时自动生成
2. 提高安全性，Token 有明确的用途说明，用户知道不能泄露
3. 简化用户操作流程，无需手动去飞书配置界面生成和复制 Token
## What Changes
### 后端变更
1. **数据模型调整**
 - `Project` 模型保留 `feishu_webhook_token` 字段（已存在）
 - 项目创建时自动生成 32 字符的随机 Token
 - 新增 `ProjectBase` 中的 `webhook_token` 字段（只读，不在 FeishuConfigCreate 中）
2. **API 变更**
 - `POST /api/projects` - 创建项目时自动生成 webhook_token
 - `POST /api/projects/{id}/refresh-webhook-token` - **新增** 刷新 Token 接口
 - `PUT /api/projects/{id}/webhook-token` - **新增** 自定义 Token 接口（最大 32 字符）
 - 移除 `FeishuConfigCreate` 中的 `webhook_token` 字段
3. **响应调整**
 - `ProjectRead` 需返回 `webhook_token`（用于显示给用户复制）
 - `FeishuConfigRead` 移除 `has_webhook_token` 字段
### 前端变更
1. **项目详情页调整**
 - 显示 Webhook Token（带复制按钮）
 - 显示「刷新」按钮，点击后生成新 Token
 - 支持自定义输入 Token（最大 32 字符）
 - 显示安全警告：「请勿泄露此 Token，它用于验证 Webhook 请求的来源」
2. **飞书配置表单调整**
 - 移除 Webhook Token 输入框
 - 更新使用说明
## Impact
- 受影响的 specs: `feishu-integration`
- 受影响的代码:
 - `server/src/friday/models/project.py`
 - `server/src/friday/routes/projects.py`
 - `web/src/components/feishu/FeishuConfigForm.vue`
 - `web/src/pages/projects/[id]/feishu.vue` 或项目详情页
 - `web/src/types/index.ts`
 - `web/src/api/projects.ts`
