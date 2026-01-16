"""Friday 日志配置模块。
配置 structlog 和标准 logging 的集成，确保所有日志正确输出。
"""
import logging
import sys
import structlog
def configure_logging(debug: bool = False) -> None:
 """配置应用程序日志系统。
 Args:
 debug: 是否启用调试模式，调试模式使用更详细的彩色控制台输出格式
 """
 # 设置时间戳格式
 timestamper = structlog.processors.TimeStamper(fmt="iso")
 # 共享的 processors
 shared_processors: list[structlog.types.Processor] = [
 structlog.contextvars.merge_contextvars,
 structlog.stdlib.add_log_level,
 structlog.stdlib.add_logger_name,
 timestamper,
 structlog.stdlib.PositionalArgumentsFormatter,
 structlog.processors.StackInfoRenderer,
 structlog.processors.UnicodeDecoder,
 ]
 if debug:
 # 开发模式：使用彩色控制台输出
 renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer(colors=True)
 else:
 # 生产模式：使用 JSON 格式便于日志收集
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
 # 配置标准 logging 的 formatter
 formatter = structlog.stdlib.ProcessorFormatter(
 foreign_pre_chain=shared_processors,
 processors=[
 structlog.stdlib.ProcessorFormatter.remove_processors_meta,
 renderer,
 ],
 )
 handler = logging.StreamHandler(sys.stdout)
 handler.setFormatter(formatter)
 # 配置 root logger
 root_logger = logging.getLogger
 root_logger.handlers.clear
 root_logger.addHandler(handler)
 root_logger.setLevel(logging.DEBUG if debug else logging.INFO)
 # 设置第三方库的日志级别
 logging.getLogger("uvicorn").setLevel(logging.INFO)
 logging.getLogger("uvicorn.access").setLevel(logging.INFO)
 logging.getLogger("uvicorn.error").setLevel(logging.INFO)
 logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
 logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
 logging.getLogger("httpx").setLevel(logging.WARNING)
 logging.getLogger("httpcore").setLevel(logging.WARNING)
 logging.getLogger("alembic").setLevel(logging.INFO)
