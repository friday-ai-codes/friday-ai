# 任务清单：多飞书项目集成支持
## 1. 后端 - 数据模型扩展
- [x] 1.1 在 Project 模型中添加飞书凭证字段
 - `feishu_plugin_id: Optional[str]` - 插件 ID
 - `feishu_plugin_secret_encrypted: Optional[str]` - 加密的插件 Secret
 - `feishu_webhook_token: Optional[str]` - Webhook Token（明文，用于简单比较验证）
- [x] 1.2 更新 ProjectCreate/ProjectUpdate schema 支持新字段
 - 添加 FeishuConfigCreate schema（plugin_id、plugin_secret、webhook_token）
 - 在保存时自动加密敏感字段
- [x] 1.3 更新 ProjectRead schema
 - 添加 `has_feishu_config: bool` 字段
 - 不返回加密的敏感字段
## 2. 后端 - 飞书凭证管理 API
- [x] 2.1 添加 `PUT /api/projects/{project_id}/feishu-config` 接口
 - 接收 plugin_id、plugin_secret、webhook_token
 - 使用 encrypt_value 加密敏感信息
 - 返回配置状态
- [x] 2.2 添加 `GET /api/projects/{project_id}/feishu-config` 接口
 - 返回配置状态（已配置/未配置）
 - 返回 plugin_id、has_webhook_token 布尔值
 - 不返回敏感信息明文
- [x] 2.3 添加 `DELETE /api/projects/{project_id}/feishu-config` 接口
 - 清除所有飞书凭证字段
- [x] 2.4 添加 `POST /api/projects/{project_id}/feishu-config/test` 接口
 - 使用配置的凭证尝试获取 plugin_access_token
 - 返回凭证是否有效的结果
## 3. 后端 - Feishu Client 改造
- [x] 3.1 添加 `create_feishu_client_for_project(project: Project)` 工厂函数
 - 从 Project 获取 plugin_id 和解密后的 plugin_secret
 - 创建独立的 FeishuClient 实例
 - 缺少配置时抛出 ValueError
- [x] 3.2 修正 `get_work_item` 方法使用正确的 API
 - 改用 POST `/open_api/{project_key}/work_item/{type}/query`
 - 请求头使用 `X-USER-KEY` 而非 `Authorization: Bearer`
 - 请求体为 `{"work_item_ids": [id]}`
 - 正确解析响应中的 data 数组
- [x] 3.3 添加 test_connection 方法测试连接有效性
- [x] 3.4 保留全局 `get_feishu_client` 作为向后兼容（标记为 deprecated）
## 4. 后端 - Webhook Handler 改造
- [x] 4.1 重构 `handle_feishu_webhook` 适配飞书项目 Webhook 格式
 - 解析 header 获取 event_type、token、uuid、operator
 - 解析 payload 获取 project_key 和事件数据
- [x] 4.2 实现基于 project_key 的项目查找
 - 根据 payload.project_key 查找对应的 Project
 - 找不到时返回 {"status": "ignored", "reason": "project not found"}
- [x] 4.3 实现 Token 验证（简单字符串比较）
 - 比较 header.token 与项目配置的 webhook_token
 - 项目未配置 token 时跳过验证（向后兼容）
 - 验证失败返回 401 Unauthorized
- [x] 4.4 使用项目配置的插件凭证创建 FeishuClient
 - 调用 create_feishu_client_for_project(project)
- [x] 4.5 添加事件类型路由
 - WorkitemCreateEvent -> 创建任务
 - WorkitemStatusEvent -> 状态变更处理
 - WorkFlowNodeStatusEvent -> 节点流状态处理
 - WorkitemCommentEvent -> 评论事件处理
 - WorkitemUpdateEvent -> 更新事件处理
## 5. 后端 - 幂等处理
- [x] 5.1 实现基于 header.uuid 的幂等处理
 - 使用内存 Set 存储已处理的 uuid
 - 重复请求直接返回成功
## 6. 后端 - 配置清理
- [x] 6.1 更新 config.py
 - 将全局飞书配置标记为可选/deprecated
 - 添加注释说明多项目配置方式
- [x] 6.2 更新 .env.example
 - 更新文档说明配置方式变更
 - 保留全局配置项但标记为 deprecated
## 7. 前端 - 类型定义扩展
- [x] 7.1 更新 `web/src/types/index.ts`
 - 添加 FeishuConfig 接口
 - 添加 FeishuConfigCreate 接口
 - 添加 FeishuConfigTestResult 接口
 - 更新 Project 接口添加 `has_feishu_config: boolean`
## 8. 前端 - API 服务层扩展
- [x] 8.1 在 `web/src/api/projects.ts` 添加飞书配置 API
 - `getFeishuConfig(projectId: string): Promise<FeishuConfig>`
 - `setFeishuConfig(projectId: string, data: FeishuConfigCreate): Promise<FeishuConfig>`
 - `deleteFeishuConfig(projectId: string): Promise<void>`
 - `testFeishuConfig(projectId: string): Promise<FeishuConfigTestResult>`
- [x] 8.2 更新 projects API 导出
 - 在 default 导出中添加新方法
- [x] 8.3 添加 PUT 方法到 API client
## 9. 前端 - Store 扩展
- [x] 9.1 在 `web/src/stores/projects.ts` 添加飞书配置管理方法
 - `currentFeishuConfig: FeishuConfig | null` 状态
 - `fetchFeishuConfig(projectId: string)` 方法
## 10. 前端 - UI 组件
- [x] 10.1 创建 `FeishuConfigForm.vue` 组件
 - 表单字段：插件 ID、插件 Secret、Webhook Token
 - 敏感字段使用 password 类型输入框
 - 保存、测试、删除操作按钮
 - 加载和错误状态处理
## 11. 前端 - 页面集成
- [x] 11.1 更新项目详情页 `/projects/:id`
 - 添加飞书配置卡片区域
 - 显示配置状态和链接
- [x] 11.2 创建飞书配置页 `/projects/:id/feishu`
 - 页面布局和导航
 - 集成 FeishuConfigForm 组件
 - 使用说明文档
## 12. 修正：使用飞书插件凭证
- [x] 12.1 确认飞书项目使用插件凭证（plugin_id/plugin_secret）而非应用凭证（app_id/app_secret）
- [x] 12.2 更新所有后端代码使用 plugin_id/plugin_secret
- [x] 12.3 更新所有前端代码使用 plugin_id/plugin_secret
- [x] 12.4 更新配置文件和环境变量名称
- [x] 12.5 运行测试验证所有变更
---
**状态**：✅ 已完成
**完成日期**：2026-01-15
