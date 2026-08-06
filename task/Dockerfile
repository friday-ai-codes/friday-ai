# Stage 0: Node.js tools
FROM node:24-alpine AS node-tools
# Node is pre-installed, we just need this layer

# Stage 1: Build dependencies
FROM python:3.14-alpine AS builder

RUN apk add --no-cache \
    gcc \
    musl-dev \
    libffi-dev

WORKDIR /app

# 先复制依赖声明以利用 Docker 层缓存
COPY pyproject.toml uv.lock ./

# 依赖必须从 uv.lock 安装：直接 pip install . 会按上游声明的开区间重新解析，
# 曾因此把 mcp 装成与 claude-agent-sdk 不兼容的 2.x（见 pyproject.toml 的 mcp 上界注释）。
RUN pip install --no-cache-dir uv \
    && uv export --frozen --no-dev --no-hashes --no-emit-project -o requirements.txt \
    && uv pip install --system --no-cache -r requirements.txt

# 再复制全部源码并安装项目本身（不重装依赖）
COPY cli/ ./cli/
COPY core/ ./core/
COPY git_ops/ ./git_ops/
COPY integrations/ ./integrations/

RUN uv pip install --system --no-cache --no-deps . \
    && pip uninstall -y uv 2>/dev/null || true \
    && pip uninstall -y pip setuptools wheel 2>/dev/null || true

# Stage 2: Runtime image
FROM python:3.14-alpine

# 只安装运行时依赖
RUN apk add --no-cache \
    git \
    bash \
    ripgrep \
    jq \
    tree \
    curl \
    ca-certificates \
    libffi \
    libstdc++ \
    docker-cli

WORKDIR /app

# Copy Node.js from node-tools
COPY --from=node-tools /usr/local/bin/node /usr/local/bin/
COPY --from=node-tools /usr/local/lib/node_modules /usr/local/lib/node_modules
# Pin claude-code 版本 (2026-05-28)，定期升级时更新此版本号
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx && \
    npm install -g @anthropic-ai/claude-code@2.1.153

# 从 builder 复制已安装的 Python 包
COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app

# 清理 Python 编译缓存以减小镜像体积
# 注意: rm -rf /root/.cache/pip 是防御性操作——虽然 pip cache 主要在 builder stage，
# 但 COPY --from=builder 可能携带残留缓存文件，此步骤确保 runtime 镜像干净
RUN find /usr/local/lib/python3.14 -name "*.pyc" -delete && \
    find /usr/local/lib/python3.14 -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true && \
    rm -rf /root/.cache/pip

RUN adduser -D -u 1000 friday && \
    git config --global --add safe.directory "*" && \
    mkdir -p /app/workspace /app/sessions /home/friday/.claude && \
    chown -R friday:friday /app /home/friday

# Friday skills 同源链路（单一事实源是仓库根 skills/skills/）：
# skills/skills/ → (task/scripts/sync_skills.py) → assets/skills/
#   → (此处 COPY) → /opt/friday/skills/ → (runner.py 运行时注入) → {workspace}/.claude/skills/
COPY --chown=friday:friday assets/skills/ /opt/friday/skills/

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENV PYTHONUNBUFFERED=1

USER friday

ENTRYPOINT ["/app/entrypoint.sh"]
