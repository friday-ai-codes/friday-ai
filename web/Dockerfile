# Build stage
FROM node:20-slim AS builder
# Enable pnpm
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
RUN corepack enable
WORKDIR /app
# Copy package files
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
# Install dependencies
RUN pnpm install --frozen-lockfile
# Copy source code
COPY . .
# Build
RUN pnpm build
# Production stage
FROM nginx:alpine AS production
# Copy built assets
COPY --from=builder /app/dist /usr/share/nginx/html
# Copy nginx config - 配置 API 反向代理和静态文件服务
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]