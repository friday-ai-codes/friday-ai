## 1. 后端：创建 Chat App
- [x] 1.1 创建 `server/chat/` Django app 基础结构
- [x] 1.2 创建 `ChatService` 服务类，封装 LLM 调用逻辑
- [x] 1.3 实现 `GET /api/v1/chat/models` 获取模型列表接口
- [x] 1.4 实现 `POST /api/v1/chat/completions` 对话接口
- [x] 1.5 集成 Claude 配置服务，支持系统级和项目级配置
- [x] 1.6 添加 URL 路由配置
- [x] 1.7 编写单元测试
## 2. 前端：Chat API 客户端
- [x] 2.1 创建 `web/src/api/chat.ts` API 客户端
- [x] 2.2 定义 TypeScript 类型（ChatMessage, ChatCompletionRequest, Model 等）
## 3. 前端：测试 Dialog 组件
- [x] 3.1 创建 `ClaudeTestDialog.vue` 组件
- [x] 3.2 实现测试输入框（默认值：「你基于什么模型？」）
- [x] 3.3 实现测试按钮和加载状态
- [x] 3.4 实现结果展示区域（Markdown 渲染）
- [x] 3.5 实现错误处理和提示
## 4. 前端：系统设置页面集成
- [x] 4.1 添加模型选择下拉框
- [x] 4.2 实现配置变更后自动获取模型列表
- [x] 4.3 添加「测试」按钮
- [x] 4.4 集成 ClaudeTestDialog 组件
## 5. 前端：项目 Claude 配置集成
- [x] 5.1 添加模型选择下拉框
- [x] 5.2 实现配置变更后自动获取模型列表
- [x] 5.3 添加「测试」按钮
- [x] 5.4 集成 ClaudeTestDialog 组件
## 6. 测试与验证
- [x] 6.1 后端接口测试
- [x] 6.2 前端组件测试
- [x] 6.3 端到端功能验证
