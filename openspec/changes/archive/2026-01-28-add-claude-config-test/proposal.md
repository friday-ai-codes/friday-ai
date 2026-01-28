# Change: 添加 Claude 配置测试功能
## Why
用户在配置 Claude API Key 和 Base URL 后，无法验证配置是否正确，需要提供一个即时测试功能来验证配置的有效性。同时，需要支持获取可用模型列表并选择模型进行测试。
## What Changes
- **后端**：新增 `chat` Django app，提供通用的 LLM 对话能力
 - 提供 `/api/v1/chat/completions` 端点，转发请求到配置的 Claude API
 - 提供 `/api/v1/chat/models` 端点，获取可用模型列表
 - 使用系统配置或项目配置的 Claude API Key 和 Base URL
 - 当前不保留对话记录，但架构支持后续扩展
- **前端**：在所有 Claude 配置位置增加测试功能
 - 系统设置页面 (`/settings`) 增加模型选择和测试按钮
 - 项目 Claude 配置 Tab 增加模型选择和测试按钮
 - 填写 API Key 和 Base URL 后自动获取模型列表
 - 点击测试弹出 Dialog，显示测试输入框和结果
 - 测试结果支持 Markdown 渲染
## Impact
- Affected specs: `ai-dev-automation`, `frontend-architecture`
- Affected code:
 - 新增: `server/chat/` Django app
 - 修改: `web/src/pages/settings.vue` 系统设置页面
 - 修改: `web/src/pages/projects/[id].vue` 项目详情页 Claude 配置 Tab
 - 新增: `web/src/components/ClaudeTestDialog.vue` 测试对话框组件
 - 新增: `web/src/api/chat.ts` Chat API 客户端
