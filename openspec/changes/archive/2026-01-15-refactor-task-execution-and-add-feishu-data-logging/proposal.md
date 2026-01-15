# Change: 重构任务执行流程并添加飞书数据日志
## Why
当前系统存在两个需要改进的问题：
1. **仓库缓存复杂度高**：当前 Task Runner 在 `data/repos/` 目录下缓存克隆的仓库，这增加了状态管理的复杂度，可能导致缓存过期、分支冲突等问题。同时，SSH 密钥存储在文件系统中（`data/credentials/`），增加了安全风险和运维复杂度。
2. **飞书数据不透明**：飞书 Webhook 请求和拉取的工作项详情没有持久化存储，无法追溯问题、调试或审计。运维人员和开发者无法查看原始数据。
## What Changes
### 1. 简化仓库管理和凭证存储
- **移除 repos 缓存**：每次任务执行都从头克隆仓库到临时目录，任务完成后清理
- **SSH 密钥数据库存储**：将 SSH 私钥加密存储到数据库，而非文件系统
- **移除凭证文件目录**：不再使用 `data/credentials/` 目录
### 2. 飞书数据持久化
- **Webhook 请求日志**：保存所有飞书 Webhook 请求的原始 JSON 到数据库
- **工作项详情日志**：保存每次拉取的工作项详情到数据库
- **前端数据查看器**：提供界面查看这些原始数据
## Impact
- 受影响规范：`ai-dev-automation`, `feishu-integration`
- 受影响代码：
 - `server/src/friday/models/credential.py` - 修改凭证模型
 - `server/task/src/git_ops.py` - 修改 Git 操作
 - `server/src/friday/routes/webhook.py` - 添加日志记录
 - `server/src/friday/services/feishu.py` - 添加日志记录
 - `server/src/friday/models/` - 新增日志模型
 - `server/src/friday/routes/` - 新增日志查看 API
 - `web/src/` - 新增日志查看页面
