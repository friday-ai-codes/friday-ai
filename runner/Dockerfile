# Friday AI Runner - Go 多阶段构建
# Stage 1: 编译 Go 静态二进制
FROM golang:1.25-alpine AS builder
WORKDIR /src
# 先复制依赖文件以利用 Docker 层缓存
COPY go.mod go.sum ./
RUN go mod download
# 复制源码并编译
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build \
 -ldflags="-s -w" \
 -o /friday-runner \
 ./cmd/friday-runner
# Stage 2: alpine 运行时镜像（需要 shell 执行 entrypoint.sh）
FROM alpine:3.21
# Runner 二进制
COPY --from=builder /friday-runner /friday-runner
# Entrypoint 脚本
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
# 创建数据目录（用于持久化注册信息和密钥）
RUN mkdir -p /data && chown 65534:65534 /data
# 非 root 用户 nobody:nobody (65534:65534)
USER 65534:65534
ENTRYPOINT ["/entrypoint.sh"]
