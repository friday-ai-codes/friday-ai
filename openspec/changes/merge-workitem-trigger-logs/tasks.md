# Implementation Tasks
## 1. 后端模型与 API
- [x] 1.1 创建 `TriggerLog` 模型，包含 webhook 请求和工作项详情字段
- [x] 1.2 添加数据库迁移
- [x] 1.3 修改 `_handle_workitem_status` 等方法，统一记录到 TriggerLog
- [x] 1.4 创建 TriggerLog 序列化器，支持原始数据懒加载
- [x] 1.5 创建 API 端点 `GET /api/logs/triggers` 和 `GET /api/logs/triggers/{id}`
- [x] 1.6 添加 `GET /api/logs/triggers/{id}/raw` 端点，用于获取原始 JSON 数据
## 2. 前端类型定义
- [x] 2.1 定义 `TriggerLog` 类型（列表展示用）
- [x] 2.2 定义 `TriggerLogDetail` 类型（详情展示用）
- [x] 2.3 定义 `WorkItemField` 通用类型
- [x] 2.4 定义关键字段常量（field_bcff9b、description、field_3f6667）
## 3. 前端组件
- [x] 3.1 安装并配置 shiki 库
- [x] 3.2 创建 `JsonHighlighter` 组件，使用 shiki 高亮 JSON
- [x] 3.3 创建 `TriggerLogList` 组件，展示日志列表
- [x] 3.4 创建 `TriggerLogDetail` 组件，展示关键字段和可折叠原始数据
- [x] 3.5 创建 `KeyFieldsCard` 组件，突出展示三个关键字段
## 4. 前端页面
- [x] 4.1 创建触发日志列表页面 `/logs/triggers`
- [x] 4.2 创建触发日志详情页面 `/logs/triggers/:id`
- [x] 4.3 添加路由配置
- [x] 4.4 更新导航菜单
## 5. 测试与文档
- [x] 5.1 编写后端单元测试
- [x] 5.2 编写前端组件测试
- [x] 5.3 更新 API 文档
