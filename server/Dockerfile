# Friday AI Dev Agent - Django API Service
FROM python:3.14-slim
# Install system dependencies
RUN apt-get update && apt-get install -y \
 curl \
 && rm -rf /var/lib/apt/lists/*
# Install uv
RUN pip install uv
# Set working directory
WORKDIR /app
# Copy project files
COPY pyproject.toml uv.lock ./
COPY manage.py ./
COPY friday/ ./friday/
COPY core/ ./core/
COPY projects/ ./projects/
COPY tasks/ ./tasks/
COPY webhooks/ ./webhooks/
COPY services/ ./services/
COPY utils/ ./utils/
# Install dependencies
RUN uv sync --frozen --no-dev
# Create data directory
RUN mkdir -p /app/data
# Expose port
EXPOSE 8000
# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
 CMD curl -f http://localhost:8000/health || exit 1
# Run the application with Gunicorn + Uvicorn workers
# 参考: https://docs.djangoproject.com/zh-hans/6.0/howto/deployment/asgi/uvicorn/
#
# 配置说明:
# - --workers: worker 进程数量，根据 CPU 核心数调整
# - --worker-class: 使用 uvicorn.workers.UvicornWorker 支持 ASGI
# - --bind: 绑定地址和端口
# - --access-logfile: 访问日志输出到 stdout
# - --error-logfile: 错误日志输出到 stderr
# - --capture-output: 捕获 stdout/stderr 到日志
# - --timeout: worker 超时时间（秒）
# - friday.asgi:application: Django ASGI 应用入口
#
# 启动前自动执行数据库迁移
CMD ["sh", "-c", "uv run python manage.py migrate --noinput && uv run gunicorn friday.asgi:application --workers 2 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --access-logfile - --error-logfile - --capture-output --timeout 120"]
