# Change: 多飞书项目集成支持
## Why
当前系统只支持单一的全局飞书配置，无法满足以下场景：
- 用户有多个飞书项目（如「学习工具与平台」和「智课」）
- 每个项目有独立的飞书项目插件，拥有不同的 Plugin ID 和 Secret
- 每个项目的 Webhook 配置携带不同的验证 Token（在 `header.token` 中）
- 需要根据项目动态选择正确的插件凭证来调用飞书项目 API
此外，现有代码实现存在以下问题：
1. **Webhook 验证方式错误**：当前使用 `X-Lark-Signature` 签名验证，这是飞书开放平台事件订阅的方式，不适用于飞书项目的自动化 Webhook。飞书项目 Webhook 使用 `header.token` 进行简单验证。
2. **API 调用路径错误**：当前 `get_work_item` 使用 GET 请求，但飞书项目文档明确使用 POST `/open_api/{project_key}/work_item/{type}/query`。
3. **响应解析错误**：工作项详情 API 返回 `data` 数组，当前代码未正确处理。
## What Changes
### 1. Project 模型扩展 **BREAKING**
- 添加飞书项目插件凭证字段到 Project 模型
 - `feishu_space_id`: 飞书项目空间 ID（别名，可选）
 - `feishu_plugin_id`: 飞书项目插件 ID
 - `feishu_plugin_secret_encrypted`: 飞书项目插件 Secret（加密存储）
 - `feishu_webhook_token_encrypted`: Webhook 验证 Token（加密存储）
### 2. Webhook 验证逻辑修改
- 适配飞书项目新版 Webhook 格式（header/payload 结构）
- 根据请求中 `payload.project_key` 查找对应的 Project
- 使用 `header.token` 与项目配置的 webhook_token 进行比较验证
- 移除不适用的 HMAC 签名验证逻辑
- 支持 URL 验证挑战（challenge）
### 3. Feishu Client 改造
- 添加 `create_feishu_client_for_project(project)` 工厂函数
- 修正 `get_work_item` 使用正确的 POST query API
- 正确解析工作项响应中的 fields 数组和 work_item_status
- 标记全局 `get_feishu_client` 为 deprecated（向后兼容）
### 4. 项目管理 API 扩展
- 添加飞书插件凭证配置接口（POST/GET/DELETE）
- 添加凭证有效性测试接口
- 凭证加密存储，敏感信息不返回给前端
### 5. 事件处理改造
- 适配飞书项目新版事件格式（WorkitemStatusEvent 等）
- 正确解析 pre_work_item_status/cur_work_item_status 状态变更
- 添加幂等处理（使用 header.uuid）
## Impact
- **Affected specs**: 新增 `feishu-integration` 规格
- **Affected backend code**:
 - [`server/src/friday/models/project.py`](server/src/friday/models/project.py) - 模型字段扩展
 - [`server/src/friday/services/feishu.py`](server/src/friday/services/feishu.py) - Client 改造、API 修正
 - [`server/src/friday/routes/webhook.py`](server/src/friday/routes/webhook.py) - 验证逻辑修改、事件处理适配
 - [`server/src/friday/routes/projects.py`](server/src/friday/routes/projects.py) - 新增配置接口
 - [`server/src/friday/config.py`](server/src/friday/config.py) - 全局配置标记为 deprecated
- **Affected frontend code**:
 - [`web/src/types/index.ts`](web/src/types/index.ts) - 添加 FeishuConfig 类型定义
 - [`web/src/api/projects.ts`](web/src/api/projects.ts) - 添加飞书配置 API 方法
 - `web/src/stores/projects.ts` - 添加飞书配置状态管理
 - `web/src/components/FeishuConfigForm.vue` - 新建配置表单组件
 - `web/src/components/FeishuConfigStatus.vue` - 新建配置状态组件
 - `web/src/pages/projects/[id]/feishu-config.vue` - 新建配置页面
## Migration
1. 现有项目数据需要手动配置飞书插件凭证
2. 全局环境变量 `FEISHU_APP_ID`、`FEISHU_APP_SECRET` 将被标记为 deprecated
3. 需要在每个 Project 中单独配置飞书插件凭证
4. 未配置 webhook_token 的项目将跳过 Token 验证（向后兼容）
## 关键发现（来自飞书文档分析）
### Webhook 格式
飞书项目自动化 Webhook 使用新版格式：
```json
{
 "header": {
 "operator": "操作者userkey",
 "event_type": "WorkitemStatusEvent",
 "token": "注册webhook时填入的token",
 "uuid": "幂等串"
 },
 "payload": {
 "id": 111,
 "project_key": "空间ID",
 "work_item_type_key": "story",
 ...
 }
}
```
### 获取工作项详情 API
- 请求：POST `/open_api/{project_key}/work_item/{work_item_type_key}/query`
- 请求体：`{"work_item_ids": [id1, id2, ...], "fields": [...]}`
- 响应：`{"err_code": 0, "data": [{...工作项详情...}]}`
### 验证方式
- 飞书项目 Webhook 使用简单 Token 验证（比较 header.token）
- 不是飞书开放平台的 HMAC 签名验证
