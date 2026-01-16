# Change: 添加结构化日志配置
## Why
Server 服务在生产环境中请求 API 时没有日志输出。只有 Uvicorn 和 Alembic 的启动日志可见，应用程序自身的业务日志（如 Webhook 处理、数据库操作等）完全丢失。
**根本原因**：
1. 项目使用了 `structlog` 但未调用 `structlog.configure` 进行配置
2. 部分模块（如 `webhook.py`）使用标准 `logging`，其默认级别是 `WARNING`
3. 日志库混用导致配置不一致
## What Changes
- **添加**: 创建 `server/src/friday/logging.py` 模块，配置 structlog 并与标准 logging 集成
- **修改**: `server/src/friday/main.py` 在应用启动时初始化日志配置
- **修改**: `server/src/friday/routes/webhook.py` 将标准 logging 改为 structlog
- **修改**: `openspec/project.md` 添加日志规范说明
## Impact
- **Affected specs**: 无（这是基础设施修复，不涉及业务功能变更）
- **Affected code**:
 - `server/src/friday/logging.py` (新增)
 - `server/src/friday/main.py`
 - `server/src/friday/routes/webhook.py`
 - `openspec/project.md`
- **兼容性**: 完全向后兼容，仅影响日志输出格式
