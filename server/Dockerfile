# Friday AI Dev Agent - Django API Service
# Stage 1: Build dependencies
FROM python:3.14-slim AS builder
# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
 gcc \
 libc-dev \
 libffi-dev \
 libpq-dev \
 default-libmysqlclient-dev \
 pkg-config \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# 先复制依赖声明以利用 Docker 层缓存
COPY pyproject.toml uv.lock ./
# 从 uv.lock 导出依赖列表并安装（源码变动不会触发重新安装）
RUN pip install uv \
 && uv export --frozen --no-hashes -o requirements.txt \
 && uv pip install --system -r requirements.txt
# 再复制全部源码并安装项目本身（不重装依赖）
COPY . .
RUN uv pip install --system --no-deps .
# Stage 2: Runtime image
FROM python:3.14-slim
# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
 curl \
 libpq5 \
 default-mysql-client \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# 创建非 root 用户
RUN groupadd -r friday && useradd -r -g friday -d /app -s /sbin/nologin friday
# Copy app from builder
COPY --from=builder /app /app
# Copy installed packages from builder's system Python
COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
# Entrypoint 脚本
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
# Create data directory
RUN mkdir -p /app/data
# 设置目录权限并切换到非 root 用户
RUN chown -R friday:friday /app
USER friday
# Expose port
EXPOSE 8000
# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
 CMD curl -f http://localhost:8000/health || exit 1
ENTRYPOINT ["/app/entrypoint.sh"]
