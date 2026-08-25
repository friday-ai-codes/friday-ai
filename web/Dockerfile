FROM node:24-slim AS builder

ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
# Enable corepack
RUN corepack enable

WORKDIR /app

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./

RUN pnpm install --frozen-lockfile

COPY . .

# 发版时由 CI 传入 git tag（如 v0.2.1），覆盖 package.json 中的版本号
ARG APP_VERSION
ENV APP_VERSION=$APP_VERSION
# vue-tsc 在 8GB 级 Docker VM 上默认 ~2GB heap 会 OOM
ENV NODE_OPTIONS=--max-old-space-size=4096

RUN pnpm build

FROM nginx:alpine AS production

# 非 root 用户运行 nginx
RUN chown -R nginx:nginx /var/cache/nginx /var/log/nginx /etc/nginx/conf.d && \
    chmod -R 755 /var/cache/nginx && \
    touch /tmp/nginx.pid && chown nginx:nginx /tmp/nginx.pid

COPY --from=builder /app/dist /usr/share/nginx/html

COPY nginx.conf /etc/nginx/conf.d/default.conf

# 修改 nginx 主配置使用 /tmp/nginx.pid（非 root 兼容，兼容不同版本的 pid 路径）
RUN sed -i -e 's|/var/run/nginx.pid|/tmp/nginx.pid|g' -e 's|/run/nginx.pid|/tmp/nginx.pid|g' /etc/nginx/nginx.conf

USER nginx

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]