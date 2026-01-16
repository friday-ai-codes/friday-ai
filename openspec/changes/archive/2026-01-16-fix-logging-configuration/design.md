## Context
项目在生产环境中请求 API 时没有日志输出。经调查发现：
1. 项目依赖了 `structlog`（见 [`pyproject.toml`](server/pyproject.toml:20)），部分模块使用了 `structlog.get_logger`
2. 但从未调用过 `structlog.configure` 进行配置
3. [`webhook.py`](server/src/friday/routes/webhook.py:24) 使用了标准 `logging` 模块，默认级别为 `WARNING`
4. 日志库混用且都未配置，导致 `logger.info` 等调用不输出任何内容
### 当前日志使用情况
| 模块 | 日志库 | 问题 |
|------|--------|------|
| [`database.py`](server/src/friday/database.py:28) | structlog | 未配置 |
| [`scheduler.py`](server/src/friday/services/scheduler.py:12) | structlog | 未配置 |
| [`webhook.py`](server/src/friday/routes/webhook.py:24) | logging | 默认级别 WARNING |
## Goals / Non-Goals
### Goals
- 配置 structlog 使所有日志正确输出到 stdout
- 集成标准 logging 模块，确保第三方库日志也能正确输出
- 统一项目内所有模块使用 structlog
- 支持开发模式（彩色控制台）和生产模式（JSON 格式）
### Non-Goals
- 不添加日志收集/聚合功能（如 ELK、Loki 等）
- 不添加日志文件轮转功能
- 不修改 Uvicorn 或其他第三方库的日志配置
## Decisions
### Decision 1: 使用 structlog 作为统一日志方案
**选择**: structlog + 标准 logging 集成
**原因**:
1. 项目已经在使用 structlog，保持一致性
2. structlog 支持结构化日志，便于后续日志分析
3. 可以与标准 logging 无缝集成
**替代方案**:
- 仅使用标准 logging: 简单但缺乏结构化日志支持
- 使用 loguru: 需要替换所有现有代码，变更范围大
### Decision 2: 生产环境使用 JSON 格式输出
**选择**: 生产模式输出 JSON，开发模式输出彩色控制台
**原因**:
1. JSON 格式便于日志收集工具解析（如 Docker logs、ELK）
2. 开发模式彩色输出提升可读性
### Decision 3: 在 main.py 入口处初始化日志
**选择**: 在 FastAPI 应用创建之前调用 `configure_logging`
**原因**:
1. 确保所有模块导入时日志已配置
2. 遵循"尽早配置日志"的最佳实践
## Implementation Details
### 日志配置模块结构
```python
# server/src/friday/logging.py
import logging
import sys
import structlog
def configure_logging(debug: bool = False) -> None:
 """配置应用程序日志系统。"""
 # 时间戳格式
 timestamper = structlog.processors.TimeStamper(fmt="iso")
 # 共享处理器
 shared_processors = [
 structlog.contextvars.merge_contextvars,
 structlog.stdlib.add_log_level,
 structlog.stdlib.add_logger_name,
 timestamper,
 structlog.stdlib.PositionalArgumentsFormatter,
 structlog.processors.StackInfoRenderer,
 structlog.processors.UnicodeDecoder,
 ]
 # 根据环境选择渲染器
 if debug:
 renderer = structlog.dev.ConsoleRenderer(colors=True)
 else:
 renderer = structlog.processors.JSONRenderer
 # 配置 structlog
 structlog.configure(
 processors=[
 *shared_processors,
 structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
 ],
 logger_factory=structlog.stdlib.LoggerFactory,
 wrapper_class=structlog.stdlib.BoundLogger,
 cache_logger_on_first_use=True,
 )
 # 配置标准 logging
 formatter = structlog.stdlib.ProcessorFormatter(
 foreign_pre_chain=shared_processors,
 processors=[
 structlog.stdlib.ProcessorFormatter.remove_processors_meta,
 renderer,
 ],
 )
 handler = logging.StreamHandler(sys.stdout)
 handler.setFormatter(formatter)
 root_logger = logging.getLogger
 root_logger.handlers.clear
 root_logger.addHandler(handler)
 root_logger.setLevel(logging.DEBUG if debug else logging.INFO)
 # 设置第三方库日志级别
 logging.getLogger("uvicorn").setLevel(logging.INFO)
 logging.getLogger("uvicorn.access").setLevel(logging.INFO)
 logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
 logging.getLogger("httpx").setLevel(logging.WARNING)
```
### 预期日志输出
**生产模式（JSON）**:
```json
{"event": "处理事件: WorkitemCreateEvent", "level": "info", "timestamp": "2026-01-16T10:00:00.000000Z", "logger": "friday.routes.webhook"}
```
**开发模式（控制台）**:
```
2026-01-16 18:00:00 [info ] 处理事件: WorkitemCreateEvent [friday.routes.webhook]
```
## Risks / Trade-offs
| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 日志格式变更可能影响现有日志监控 | 低 | JSON 是标准格式，兼容性好 |
| structlog 配置错误导致启动失败 | 中 | 添加启动验证日志 |
## Migration Plan. 创建 `logging.py` 模块
2. 修改 `main.py` 调用配置
3. 统一 `webhook.py` 使用 structlog
4. 本地测试验证
5. 部署到生产环境
**回滚**: 如出现问题，删除 `configure_logging` 调用即可恢复原状（虽然仍无日志）
## Open Questions
无
