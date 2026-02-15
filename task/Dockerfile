# Stage 0: Node.js tools
FROM node:22.12.0-alpine AS node-tools
# Node is pre-installed, we just need this layer
# Stage 1: Build dependencies
FROM python:3.14-alpine AS builder
RUN apk add --no-cache \
 gcc \
 musl-dev \
 libffi-dev
WORKDIR /app
COPY pyproject.toml ./
COPY cli/ ./cli/
COPY core/ ./core/
COPY git_ops/ ./git_ops/
COPY integrations/ ./integrations/
RUN pip install --no-cache-dir -e . \
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
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
 ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
# 从 builder 复制已安装的 Python 包
COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app
RUN git config --global --add safe.directory "*"
RUN mkdir -p /app/workspace /app/sessions
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
