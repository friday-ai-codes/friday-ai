# Friday AI Dev Agent - Django API Service
# Stage 1: Build dependencies
FROM python:3.14-slim AS builder

# Install build dependencies
# libopenblas-dev：仅 x86_64 从源码重编 numpy 时链接它，避免退回慢速 fallback。
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc-dev \
    libffi-dev \
    libopenblas-dev \
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

# 仅在 x86_64 上从源码重编 numpy：官方预编译 wheel 默认带 x86-64-v2 基线指令，
# 在不支持 v2 指令集的虚拟机（如默认 qemu64/kvm64 的 KVM）上 import 时会直接
# RuntimeError。把 CPU baseline 降到最低（SSE3）以兼容这类机器，并链接系统
# OpenBLAS 保证矩阵运算性能不退化。arm64 无此问题，继续用官方预编译 wheel（更快）。
# 注意：numpy 版本需与 uv.lock 中保持一致。
RUN if [ "$(uname -m)" = "x86_64" ]; then \
        uv pip install --system \
            --reinstall-package numpy \
            --no-binary numpy \
            -C setup-args=-Dcpu-baseline=min \
            "numpy==2.4.3"; \
    fi

# 再复制全部源码并安装项目本身（不重装依赖）
COPY . .
RUN uv pip install --system --no-deps .

# Stage 2: Runtime image
FROM python:3.14-slim

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    openssh-client \
    libpq5 \
    default-mysql-client \
    && rm -rf /var/lib/apt/lists/*

# x86_64 镜像里的 numpy 链接了系统 OpenBLAS，需带上其运行库；
# arm64 用的是自带 BLAS 的预编译 wheel，无需安装。
RUN if [ "$(uname -m)" = "x86_64" ]; then \
        apt-get update && apt-get install -y --no-install-recommends libopenblas0-pthread \
        && rm -rf /var/lib/apt/lists/*; \
    fi

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
