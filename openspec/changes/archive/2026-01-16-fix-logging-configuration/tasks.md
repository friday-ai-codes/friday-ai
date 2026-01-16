## 1. 实现日志配置模块
- [x] 1.1 创建 `server/src/friday/logging.py` 模块
 - 配置 structlog 处理器
 - 集成标准 logging 模块
 - 支持 DEBUG 模式（彩色控制台）和 生产模式（JSON）
- [x] 1.2 修改 `server/src/friday/main.py`
 - 导入并调用 `configure_logging` 函数
 - 在任何日志调用之前初始化配置
## 2. 统一日志使用
- [x] 2.1 修改 `server/src/friday/routes/webhook.py`
 - 将 `import logging` 改为 `import structlog`
 - 将 `logging.getLogger(__name__)` 改为 `structlog.get_logger(__name__)`
## 3. 文档更新
- [x] 3.1 更新 `openspec/project.md`
 - 添加日志使用规范说明
## 4. 验证
- [x] 4.1 本地测试日志输出
 - 启动服务，调用 API 接口
 - 确认控制台有日志输出
- [x] 4.2 Docker 环境验证
 - 重新构建 Docker 镜像
 - 部署并验证日志输出正常
