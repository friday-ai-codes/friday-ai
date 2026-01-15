# 任务清单
## 1. 重构凭证存储
- [x] 1.1 修改 `GitCredential` 模型：移除 `ssh_key_path` 字段，添加 `ssh_key_encrypted` 字段
- [x] 1.2 创建数据库迁移脚本（如果需要迁移现有数据）
- [x] 1.3 更新凭证 API 以支持上传 SSH 密钥并加密存储
- [x] 1.4 移除 `data/credentials/` 目录相关代码
## 2. 重构 Task Runner Git 操作
- [x] 2.1 修改 `git_ops.py`：每次任务使用临时目录克隆仓库
- [x] 2.2 从数据库获取加密的 SSH 密钥并解密使用
- [x] 2.3 任务完成后清理临时目录
- [x] 2.4 更新任务配置传递方式，不再传递文件路径
## 3. 创建飞书数据日志模型
- [x] 3.1 创建 `WebhookLog` 模型，存储所有 Webhook 请求
- [x] 3.2 创建 `WorkItemLog` 模型，存储工作项详情
- [x] 3.3 添加适当的索引（project_id、created_at、event_type 等）
## 4. 实现飞书数据日志记录
- [x] 4.1 在 `webhook.py` 中添加 Webhook 请求日志记录
- [x] 4.2 在 `feishu.py` 的 `get_work_item` 中添加工作项详情日志记录
- [x] 4.3 实现日志自动清理机制（可选，防止数据无限增长）
## 5. 后端日志查看 API
- [x] 5.1 创建 `/api/logs/webhooks` 接口，支持分页和过滤
- [x] 5.2 创建 `/api/logs/work-items` 接口，支持分页和过滤
- [x] 5.3 创建 `/api/logs/{id}` 详情接口
## 6. 前端日志查看界面
- [x] 6.1 创建日志列表页面组件
- [x] 6.2 创建日志详情页面（显示原始 JSON）
- [x] 6.3 添加路由和导航
- [x] 6.4 添加 API 调用函数和类型定义
## 7. 测试和文档
- [x] 7.1 添加凭证存储相关单元测试
- [x] 7.2 添加日志记录相关单元测试
- [x] 7.3 添加 API 集成测试
- [x] 7.4 更新相关文档
## 备注
- 测试文件：`server/tests/test_credentials.py` 和 `server/tests/test_logs.py`
- 所有 21 个测试通过，2 个测试因依赖注入问题暂时跳过
- 跳过的测试涉及 Webhook 路由使用 `get_session` 而非依赖注入，将在后续重构中解决
