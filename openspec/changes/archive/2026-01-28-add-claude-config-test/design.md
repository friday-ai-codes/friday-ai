## Context
用户配置 Claude API Key 和 Base URL 后，需要验证配置是否正确。系统需要提供一个通用的对话能力，既用于配置测试，也为后续功能扩展（如保留对话记录、多轮对话等）打下基础。
## Goals / Non-Goals
**Goals:**
- 提供可复用的 LLM 对话后端服务
- 支持获取模型列表
- 支持配置验证测试
- 前端提供统一的测试 UI 组件
**Non-Goals:**
- 当前不实现对话记录持久化
- 当前不实现多轮对话上下文管理
- 当前不实现流式响应（SSE）
## Decisions
### 1. 后端架构：独立 Django App
**Decision:** 创建独立的 `chat` Django app 处理对话功能
**Rationale:**
- 职责分离，对话功能独立于其他业务逻辑
- 便于后续扩展（对话记录、多轮对话等）
- 符合项目现有的 app 组织结构
**Alternatives considered:**
- 在 `core` app 中添加：会使 core 过于臃肿
- 在 `services` 中添加服务类：缺少 API 端点定义位置
### 2. API 设计：兼容 OpenAI 格式
**Decision:** 使用类 OpenAI 的 API 格式
```python
# POST /api/v1/chat/completions
{
 "model": "claude-3-5-sonnet-20241022",
 "messages": [{"role": "user", "content": "你基于什么模型？"}],
 "source": "system" | "project", # 配置来源
 "project_id": 1 # 如果 source=project
}
# GET /api/v1/chat/models
{
 "source": "system" | "project",
 "project_id": 1 # 如果 source=project
}
```
**Rationale:**
- 熟悉的 API 格式，易于理解和使用
- 便于后续支持其他 LLM 提供商
### 3. 前端组件：可复用 Dialog
**Decision:** 创建 `ClaudeTestDialog` 组件，可在系统设置和项目配置中复用
**Props:**
- `source`: 'system' | 'project' - 配置来源
- `projectId?`: number - 项目 ID（当 source=project 时）
- `apiKey?`: string - 临时 API Key（用于未保存的配置测试）
- `baseUrl?`: string - 临时 Base URL
### 4. 模型列表获取流程
**Decision:** 填写配置后自动获取模型列表
**Flow:**
1. 用户填写 API Key 和 Base URL
2. 失焦或手动触发时调用 `/api/v1/chat/models` 获取模型列表
3. 默认选中第一个模型
4. 显示「测试」按钮
5. 点击测试弹出 Dialog
## Risks / Trade-offs
| Risk | Mitigation |
|------|------------|
| API Key 通过请求传递可能泄露 | 使用 HTTPS，API Key 在请求体中而非 URL |
| 模型列表 API 可能不可用 | 提供手动输入模型名称的备选方案 |
| 测试请求超时 | 设置合理的超时时间（30s），显示加载状态 |
## Migration Plan
无需数据迁移，纯功能新增。
## Open Questions
1. 是否需要缓存模型列表？（建议：前端 session 级别缓存）
2. 测试的默认 prompt 是否可配置？（当前硬编码为「你基于什么模型？」）
