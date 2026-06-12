#!/usr/bin/env bash
# Friday AI - 本地完整体部署配置脚本
# 用法: scripts/setup.sh [--non-interactive] [--force] [--data-dir PATH]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

NON_INTERACTIVE=false
FORCE=false

FRIDAY_DATA_DIR="${HOME}/.friday-ai"
WEB_PORT="10240"
API_PORT="10241"
REDIS_PORT="6379"
QDRANT_HTTP_PORT="6333"
QDRANT_GRPC_PORT="6334"
POSTGRES_USER="friday"
POSTGRES_PASSWORD="friday"
POSTGRES_DB="friday"
FRIDAY_IMAGE_PREFIX="ghcr.io/friday-ai-codes/friday-ai"
FRIDAY_IMAGE_TAG="latest"
DATABASE_URL="postgres://friday:${POSTGRES_PASSWORD:-friday}@postgres:5432/friday"
SECRET_KEY_VALUE=""
ENCRYPTION_KEY_VALUE=""
RUNNER_TOKEN_VALUE=""
QDRANT_API_KEY_VALUE=""
ADMIN_USERNAME="admin"
ADMIN_PASSWORD=""
DOCKER_GID_VALUE="999"

print_header() {
    echo -e "${BLUE}=== $1 ===${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${YELLOW}  $1${NC}"
}

usage() {
    cat <<'EOF'
Friday AI 本地完整体部署配置

用法:
  scripts/setup.sh [--non-interactive] [--force] [--data-dir PATH]

选项:
  --non-interactive    使用默认值生成 .env
  --force              覆盖已存在的 .env
  --data-dir PATH      指定持久化数据目录，默认 ~/.friday-ai
  -h, --help           显示帮助
EOF
}

parse_args() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --non-interactive)
                NON_INTERACTIVE=true
                shift
                ;;
            --force)
                FORCE=true
                shift
                ;;
            --data-dir)
                if [ -z "${2:-}" ]; then
                    print_error "--data-dir 需要路径参数"
                    exit 1
                fi
                FRIDAY_DATA_DIR="$2"
                shift 2
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                print_error "未知参数: $1"
                usage
                exit 1
                ;;
        esac
    done
}

expand_path() {
    local input="$1"
    case "$input" in
        "~")
            printf '%s\n' "$HOME"
            ;;
        "~/"*)
            printf '%s/%s\n' "$HOME" "${input#~/}"
            ;;
        /*)
            printf '%s\n' "$input"
            ;;
        *)
            printf '%s/%s\n' "$ROOT_DIR" "$input"
            ;;
    esac
}

generate_secret() {
    local length="${1:-32}"
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -base64 "$length"
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c "import secrets; print(secrets.token_urlsafe($length))"
    else
        print_error "无法生成密钥: 需要 openssl 或 python3"
        exit 1
    fi
}

write_env() {
    printf '%s="%s"\n' "$1" "$2" >> "$ENV_FILE"
}

detect_docker_gid() {
    local gid=""
    if [ "$(uname -s 2>/dev/null)" = "Darwin" ]; then
        echo "0"
        return
    fi
    if [ -S /var/run/docker.sock ]; then
        gid=$(stat -c '%g' /var/run/docker.sock 2>/dev/null) || true
        if [ -z "$gid" ]; then
            gid=$(stat -f '%g' /var/run/docker.sock 2>/dev/null) || true
        fi
    fi
    echo "${gid:-999}"
}

check_prerequisites() {
    print_header "前置检查"
    local has_error=false

    if ! command -v docker >/dev/null 2>&1; then
        print_error "未找到 docker 命令"
        print_info "安装: https://docs.docker.com/get-docker/"
        has_error=true
    else
        print_success "Docker 已安装"
    fi

    if command -v docker >/dev/null 2>&1; then
        local compose_version
        compose_version=$(docker compose version --short 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || echo "0.0.0")
        local compose_major
        compose_major=$(echo "$compose_version" | cut -d. -f1)
        if [ -z "$compose_major" ] || [ "$compose_major" -lt 2 ]; then
            print_error "需要 Docker Compose V2+（当前: ${compose_version}）"
            has_error=true
        else
            print_success "Docker Compose v${compose_version}"
        fi
    fi

    if command -v docker >/dev/null 2>&1; then
        if ! docker info >/dev/null 2>&1; then
            print_info "Docker daemon 当前不可用；生成 .env 不受影响，启动前请先启动 Docker"
        else
            print_success "Docker daemon 可用"
        fi
    fi

    if ! command -v openssl >/dev/null 2>&1 && ! command -v python3 >/dev/null 2>&1; then
        print_error "需要 openssl 或 python3 来生成密钥"
        has_error=true
    else
        print_success "密钥生成工具可用"
    fi

    echo ""
    if [ "$has_error" = true ]; then
        print_error "前置检查未通过，请先修复上述问题"
        exit 1
    fi
}

configure_interactive() {
    if [ "$NON_INTERACTIVE" = true ]; then
        print_info "非交互模式: 使用默认端口、默认数据目录和内置 PostgreSQL"
        DOCKER_GID_VALUE=$(detect_docker_gid)
        return
    fi

    print_header "部署配置"
    print_info "默认会启动 PostgreSQL、Redis、Qdrant、Server、Web、Runner 完整体实例"
    echo ""

    read -rp "  数据目录 [${FRIDAY_DATA_DIR}]: " data_dir_input
    FRIDAY_DATA_DIR="${data_dir_input:-$FRIDAY_DATA_DIR}"

    read -rp "  Web 端口 [${WEB_PORT}]: " web_port_input
    WEB_PORT="${web_port_input:-$WEB_PORT}"

    read -rp "  API 端口 [${API_PORT}]: " api_port_input
    API_PORT="${api_port_input:-$API_PORT}"

    read -rp "  Redis 端口 [${REDIS_PORT}]: " redis_port_input
    REDIS_PORT="${redis_port_input:-$REDIS_PORT}"

    read -rp "  Qdrant HTTP 端口 [${QDRANT_HTTP_PORT}]: " qdrant_http_input
    QDRANT_HTTP_PORT="${qdrant_http_input:-$QDRANT_HTTP_PORT}"

    read -rp "  Qdrant gRPC 端口 [${QDRANT_GRPC_PORT}]: " qdrant_grpc_input
    QDRANT_GRPC_PORT="${qdrant_grpc_input:-$QDRANT_GRPC_PORT}"

    read -rp "  管理员用户名 [${ADMIN_USERNAME}]: " admin_user_input
    ADMIN_USERNAME="${admin_user_input:-$ADMIN_USERNAME}"

    # 首启默认走 Web 向导自行设置管理员；此处填写的用户名/密码仅供命令行兜底（init_superuser）使用。
    read -rp "  管理员密码（留空即可，首启走 Web 向导设置；或后续用 init_superuser 命令兜底）: " admin_pass_input
    ADMIN_PASSWORD="${admin_pass_input:-}"

    DOCKER_GID_VALUE=$(detect_docker_gid)
    echo ""
}

prepare_data_dirs() {
    print_header "创建持久化目录"
    FRIDAY_DATA_DIR="$(expand_path "$FRIDAY_DATA_DIR")"

    mkdir -p \
        "$FRIDAY_DATA_DIR/postgres" \
        "$FRIDAY_DATA_DIR/redis" \
        "$FRIDAY_DATA_DIR/qdrant" \
        "$FRIDAY_DATA_DIR/server" \
        "$FRIDAY_DATA_DIR/runner"

    chmod 755 "$FRIDAY_DATA_DIR"
    chmod 700 "$FRIDAY_DATA_DIR/postgres"
    chmod 777 \
        "$FRIDAY_DATA_DIR/redis" \
        "$FRIDAY_DATA_DIR/qdrant" \
        "$FRIDAY_DATA_DIR/server" \
        "$FRIDAY_DATA_DIR/runner"

    print_success "数据目录已准备: ${FRIDAY_DATA_DIR}"
    echo ""
}

generate_secrets() {
    print_header "生成安全密钥"
    SECRET_KEY_VALUE=$(generate_secret 32)
    ENCRYPTION_KEY_VALUE=$(generate_secret 32)
    RUNNER_TOKEN_VALUE=$(generate_secret 32)
    # Qdrant 必须生成非空 API Key：留空会让 qdrant 开启"空 key 鉴权"，
    # 而 server 客户端遇到空 key 不发认证头，导致健康检查 401。
    QDRANT_API_KEY_VALUE=$(generate_secret 32)
    print_success "SECRET_KEY 已生成"
    print_success "FRIDAY_ENCRYPTION_KEY 已生成"
    print_success "RUNNER_REGISTRATION_TOKEN 已生成"
    print_success "QDRANT_API_KEY 已生成"
    echo ""
}

confirm_overwrite() {
    if [ ! -f "$ENV_FILE" ]; then
        return
    fi

    if [ "$FORCE" = true ] || [ "$NON_INTERACTIVE" = true ]; then
        print_info "将覆盖现有 .env: ${ENV_FILE}"
        return
    fi

    print_info "检测到已存在的 .env 文件: ${ENV_FILE}"
    read -rp "  是否覆盖？(y/N): " overwrite
    if [[ ! "$overwrite" =~ ^[yY]$ ]]; then
        print_info "保留现有 .env 文件，退出。"
        exit 0
    fi
}

write_env_file() {
    print_header "写入 .env"
    : > "$ENV_FILE"

    cat >> "$ENV_FILE" <<EOF
# Friday AI 环境配置 - 由 scripts/setup.sh 自动生成
# 生成时间: $(date '+%Y-%m-%d %H:%M:%S')
# 数据目录: ${FRIDAY_DATA_DIR}

EOF

    echo "# 本地持久化目录" >> "$ENV_FILE"
    write_env "FRIDAY_DATA_DIR" "$FRIDAY_DATA_DIR"
    echo "" >> "$ENV_FILE"

    echo "# Docker Compose 端口配置" >> "$ENV_FILE"
    write_env "FRIDAY_WEB_PORT" "$WEB_PORT"
    write_env "FRIDAY_PORT" "$API_PORT"
    write_env "REDIS_PORT" "$REDIS_PORT"
    write_env "QDRANT_HTTP_PORT" "$QDRANT_HTTP_PORT"
    write_env "QDRANT_GRPC_PORT" "$QDRANT_GRPC_PORT"
    echo "" >> "$ENV_FILE"

    echo "# Docker 镜像配置" >> "$ENV_FILE"
    write_env "FRIDAY_IMAGE_PREFIX" "$FRIDAY_IMAGE_PREFIX"
    write_env "FRIDAY_IMAGE_TAG" "$FRIDAY_IMAGE_TAG"
    echo "" >> "$ENV_FILE"

    echo "# Django 核心配置" >> "$ENV_FILE"
    write_env "SECRET_KEY" "$SECRET_KEY_VALUE"
    write_env "DEBUG" "False"
    write_env "ALLOWED_HOSTS" "*"
    echo "" >> "$ENV_FILE"

    echo "# 数据库配置（Compose 内置 PostgreSQL）" >> "$ENV_FILE"
    write_env "DATABASE_URL" "$DATABASE_URL"
    write_env "POSTGRES_USER" "$POSTGRES_USER"
    write_env "POSTGRES_PASSWORD" "$POSTGRES_PASSWORD"
    write_env "POSTGRES_DB" "$POSTGRES_DB"
    echo "" >> "$ENV_FILE"

    echo "# Redis / Qdrant 配置（Compose 内置 Redis，channel layer 默认启用）" >> "$ENV_FILE"
    write_env "USE_REDIS_CHANNEL_LAYER" "true"
    write_env "QDRANT_URL" "http://qdrant:6333"
    write_env "QDRANT_API_KEY" "$QDRANT_API_KEY_VALUE"
    echo "" >> "$ENV_FILE"

    echo "# 安全与 Runner" >> "$ENV_FILE"
    write_env "FRIDAY_ENCRYPTION_KEY" "$ENCRYPTION_KEY_VALUE"
    write_env "RUNNER_REGISTRATION_TOKEN" "$RUNNER_TOKEN_VALUE"
    write_env "FRIDAY_RUNNER_NAME" "compose-runner"
    write_env "DOCKER_GID" "$DOCKER_GID_VALUE"
    echo "" >> "$ENV_FILE"

    echo "# 管理员配置（首启默认走 Web 向导建号；以下变量仅供 init_superuser 命令兜底读取）" >> "$ENV_FILE"
    write_env "FRIDAY_ADMIN_USERNAME" "$ADMIN_USERNAME"
    if [ -n "$ADMIN_PASSWORD" ]; then
        write_env "FRIDAY_ADMIN_PASSWORD" "$ADMIN_PASSWORD"
    fi
    echo "" >> "$ENV_FILE"

    chmod 600 "$ENV_FILE"
    print_success ".env 文件已生成: ${ENV_FILE}"
    echo ""
}

print_summary() {
    print_header "下一步"
    print_info "启动完整体实例:"
    echo "    docker compose up -d"
    echo ""
    print_info "访问 Friday AI:"
    echo "    http://localhost:${WEB_PORT}"
    echo ""
    print_info "查看日志:"
    echo "    docker compose logs -f"
    echo ""
    print_info "持久化数据目录:"
    echo "    ${FRIDAY_DATA_DIR}"
    echo ""
}

main() {
    parse_args "$@"

    echo ""
    print_header "Friday AI 本地完整体部署配置"
    print_info "本脚本会生成 .env，并准备 ~/.friday-ai 风格的本地持久化目录"
    echo ""

    check_prerequisites
    confirm_overwrite
    configure_interactive
    prepare_data_dirs
    generate_secrets
    write_env_file
    print_summary
}

main "$@"
