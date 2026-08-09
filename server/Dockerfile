# Friday AI Dev Agent - Django API Service
# Stage 1: Build dependencies
FROM python:3.14-slim AS builder

# Install build dependencies
# gcc + g++：numpy 2.x 用 meson 构建，需同时具备 C 与 C++ 编译器。
# libopenblas-dev：仅 x86_64 从源码重编 numpy 时链接它，避免退回慢速 fallback。
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
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
# RuntimeError。注意 numpy 2.x 的 baseline=min 在 x86-64 上恰好等于 X86_V2，
# 必须用 none 才能兼容老 VM（官方文档明确建议）——baseline 设为 none 后仅保留
# 运行时按 CPU 分派的优化路径。链接系统 OpenBLAS 保证矩阵运算性能不退化。
# arm64 无此问题，继续用官方预编译 wheel（更快）。numpy 版本需与 uv.lock 一致。
RUN if [ "$(uname -m)" = "x86_64" ]; then \
        uv pip install --system \
            --reinstall-package numpy \
            --no-binary numpy \
            -C setup-args=-Dcpu-baseline=none \
            "numpy==2.4.3"; \
    fi

# 再复制全部源码并安装项目本身（不重装依赖）
COPY . .
RUN uv pip install --system --no-deps .

# Stage 2: Runtime image
FROM python:3.14-slim

# Install runtime dependencies only
# ripgrep：grep_repository MCP 工具的首选检索引擎（缺失时自动回退 git grep）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    openssh-client \
    ripgrep \
    libpq5 \
    postgresql-client \
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

# 预置 fastembed BM25 稀疏编码模型（assets/ 内仅 ~84KB 停用词表 + config，无权重文件，
# 已按 huggingface_hub 缓存目录结构存放，构建与运行均无需访问 HuggingFace）。
# 若缺失：运行时首次检索会卡在模型下载直到网关超时（502/504），随后 sparse encoder
# 熔断，route_repositories / RAG 检索全部静默返回空结果。
ENV FASTEMBED_CACHE_PATH=/opt/fastembed_cache
COPY --chown=friday:friday assets/fastembed_cache /opt/fastembed_cache

# Copy installed packages from builder's system Python
COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Entrypoint 脚本
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Create data directory
RUN mkdir -p /app/data

# =============================================================================
# Phase 127 / D-01 / D-11：Semgrep CLI（独立 /opt/semgrep）+ Node 22 + volar/tsdk
# + Go/gopls —— 必须在切换非 root 用户之前安装，ENV PATH 全局可见。
# ⛔ 禁止把 semgrep 写进 pyproject.toml / uv.lock。
# 镜像体积预估 +400–550MB（真实 docker images 待 CI 测）。
# =============================================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

# 1) Semgrep CE ≥1.172.0 — 独立 tool dir，不进 server venv
RUN pip install --no-cache-dir uv \
    && uv tool install --default-index https://pypi.org/simple semgrep==1.172.0 \
        --install-dir /opt/semgrep

ENV SEMGREP_BIN=/opt/semgrep/bin/semgrep
ENV PATH="/opt/semgrep/bin:${PATH}"

# 2) Node 22 LTS + @vue/language-server + typescript（discover_tsdk 经 npm root -g）
ARG NODE_VERSION=22.17.0
RUN ARCH="$(dpkg --print-architecture)" \
    && case "$ARCH" in \
         amd64) NODE_ARCH=x64 ;; \
         arm64) NODE_ARCH=arm64 ;; \
         *) echo "unsupported arch: $ARCH" >&2; exit 1 ;; \
       esac \
    && curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" \
        | tar -xJ -C /usr/local --strip-components=1 \
    && npm install -g "@vue/language-server@3.3.9" "typescript@7.0.2"

# 3) Go toolchain + gopls v0.23.x → /usr/local
ARG GO_VERSION=1.24.5
RUN ARCH="$(dpkg --print-architecture)" \
    && case "$ARCH" in \
         amd64) GO_ARCH=amd64 ;; \
         arm64) GO_ARCH=arm64 ;; \
         *) echo "unsupported arch: $ARCH" >&2; exit 1 ;; \
       esac \
    && curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-${GO_ARCH}.tar.gz" \
        | tar -C /usr/local -xz \
    && GOBIN=/usr/local/bin /usr/local/go/bin/go install golang.org/x/tools/gopls@v0.23.0

ENV PATH="/usr/local/go/bin:/opt/semgrep/bin:${PATH}"
ENV GOTOOLCHAIN=local

# 构建探针：缺失则 build fail（root；二进制对 friday PATH 可达）
RUN semgrep --version \
    && node -v \
    && command -v vue-language-server \
    && go version \
    && gopls version

# 设置目录权限并切换到非 root 用户
RUN chown -R friday:friday /app
USER friday

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
