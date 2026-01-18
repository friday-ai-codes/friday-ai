#!/bin/bash
# Task 容器测试脚本
#
# 此脚本用于测试 Task 容器镜像是否能正确执行任务，包括：
# - 拉取工作项描述
# - 生成实施计划 (plan 模式)
# - 根据计划生成代码 (execute 模式)
#
# 使用方法:
# ./test_task_container.sh [选项]
#
# 选项:
# -m, --mode MODE 任务模式: plan 或 execute (默认: plan)
# -t, --task-id ID 任务 ID (默认: test-task-001)
# -p, --project-id ID 项目 ID (默认: test-project-001)
# --description DESC 任务描述
# --repo-url URL Git 仓库 URL (可选，用于真实测试)
# --api-key KEY Anthropic API Key
# --base-url URL Anthropic Base URL (可选)
# --access-token TOKEN Git access token (用于私有仓库认证)
# --server-url URL Friday Server 回调地址 (默认: http://host.docker.internal:8000)
# --build 构建镜像后再测试
# --dry-run 只显示将要执行的命令，不实际执行
# -h, --help 显示帮助信息
#
# 示例:
# # 快速测试 (仅验证容器启动)
# ./test_task_container.sh --dry-run
#
# # 使用自定义任务运行 plan 模式
# ./test_task_container.sh -m plan --description "添加用户认证"
#
# # 使用真实仓库测试
# ./test_task_container.sh -m plan --repo-url "git@github.com:user/repo.git" --api-key "sk-xxx"
set -e
# 默认值
MODE="plan"
TASK_ID="f3848c6d-f1ee-4046-b241-0f4b8dd2c9e9"
PROJECT_ID="1ebef9c9-9b36-47cf-9c94-cf1d8f9acce1"
TASK_DESCRIPTION="这是一个用于测试容器的示例任务描述"
REPO_URL=""
API_KEY="${ANTHROPIC_API_KEY:-}"
BASE_URL="${ANTHROPIC_BASE_URL:-}"
ACCESS_TOKEN=""
SERVER_URL="http://host.docker.internal:8000"
BUILD=false
DRY_RUN=false
IMAGE_NAME="friday-task:test"
# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color
# 日志函数
log_info {
 echo -e "${BLUE}[INFO]${NC} $1"
}
log_success {
 echo -e "${GREEN}[SUCCESS]${NC} $1"
}
log_warn {
 echo -e "${YELLOW}[WARN]${NC} $1"
}
log_error {
 echo -e "${RED}[ERROR]${NC} $1"
}
# 帮助信息
show_help {
 head -40 "$0" | tail -35 | sed 's/^#//' | sed 's/^!//'
 exit 0
}
# 解析参数
while [[ $# -gt 0 ]]; do
 case $1 in
 -m|--mode)
 MODE="$2"
 shift 2;;
 -t|--task-id)
 TASK_ID="$2"
 shift 2;;
 -p|--project-id)
 PROJECT_ID="$2"
 shift 2;;
 --description)
 TASK_DESCRIPTION="$2"
 shift 2;;
 --repo-url)
 REPO_URL="$2"
 shift 2;;
 --api-key)
 API_KEY="$2"
 shift 2;;
 --base-url)
 BASE_URL="$2"
 shift 2;;
 --access-token)
 ACCESS_TOKEN="$2"
 shift 2;;
 --server-url)
 SERVER_URL="$2"
 shift 2;;
 --build)
 BUILD=true
 shift;;
 --dry-run)
 DRY_RUN=true
 shift;;
 -h|--help)
 show_help;;
 *)
 log_error "未知选项: $1"
 echo "使用 -h 查看帮助信息"
 exit 1;;
 esac
done
# 验证模式
if [[ "$MODE" != "plan" && "$MODE" != "execute" ]]; then
 log_error "无效的模式: $MODE (必须是 plan 或 execute)"
 exit 1
fi
# 切换到 task 目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TASK_DIR="$(dirname "$SCRIPT_DIR")"
cd "$TASK_DIR"
log_info "工作目录: $TASK_DIR"
# 构建镜像
if [[ "$BUILD" == true ]]; then
 log_info "构建 Task 容器镜像..."
 docker build -t "$IMAGE_NAME" .
 log_success "镜像构建完成: $IMAGE_NAME"
fi
# 检查镜像是否存在
if ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
 log_warn "镜像 $IMAGE_NAME 不存在，正在构建..."
 docker build -t "$IMAGE_NAME" .
 log_success "镜像构建完成"
fi
# 创建临时目录用于挂载
TMP_DIR=$(mktemp -d)
WORKSPACE_DIR="$TMP_DIR/workspace"
SESSION_DIR="$TMP_DIR/sessions"
SSH_DIR="$TMP_DIR/ssh"
mkdir -p "$WORKSPACE_DIR" "$SESSION_DIR" "$SSH_DIR"
# 如果没有提供仓库，创建测试用的 Git 仓库
if [[ -z "$REPO_URL" ]]; then
 log_info "创建测试 Git 仓库..."
 cd "$WORKSPACE_DIR"
 git init
 echo "# Test Project" > README.md
 echo 'print("Hello, World!")' > main.py
 git add .
 git commit -m "Initial commit"
 cd "$TASK_DIR"
 REPO_URL="file://$WORKSPACE_DIR"
 log_success "测试仓库创建完成: $WORKSPACE_DIR"
fi
# 从 description 提取标题
TASK_TITLE="${TASK_DESCRIPTION:0:50}"
# 构建 Docker 运行命令
DOCKER_CMD="docker run --rm"
DOCKER_CMD+=" --name friday-task-test-$$"
# 环境变量
DOCKER_CMD+=" -e FRIDAY_TASK_TASK_ID=$TASK_ID"
DOCKER_CMD+=" -e FRIDAY_TASK_PROJECT_ID=$PROJECT_ID"
DOCKER_CMD+=" -e FRIDAY_TASK_TASK_MODE=$MODE"
DOCKER_CMD+=" -e FRIDAY_TASK_TASK_TITLE=$TASK_TITLE"
DOCKER_CMD+=" -e FRIDAY_TASK_TASK_DESCRIPTION=$TASK_DESCRIPTION"
DOCKER_CMD+=" -e FRIDAY_TASK_GIT_REPO_URL=$REPO_URL"
DOCKER_CMD+=" -e FRIDAY_TASK_CALLBACK_URL=$SERVER_URL/api"
DOCKER_CMD+=" -e FRIDAY_TASK_SESSION_DIR=/app/sessions"
DOCKER_CMD+=" -e GIT_AUTHOR_NAME=Friday-AI-Agent"
DOCKER_CMD+=" -e GIT_AUTHOR_EMAIL=friday@example.com"
# Claude 配置
if [[ -n "$API_KEY" ]]; then
 DOCKER_CMD+=" -e FRIDAY_TASK_CLAUDE_API_KEY=$API_KEY"
fi
if [[ -n "$BASE_URL" ]]; then
 DOCKER_CMD+=" -e FRIDAY_TASK_CLAUDE_BASE_URL=$BASE_URL"
fi
# Git access token 配置
if [[ -n "$ACCESS_TOKEN" ]]; then
 DOCKER_CMD+=" -e FRIDAY_TASK_GIT_AUTH_TYPE=token"
 DOCKER_CMD+=" -e FRIDAY_TASK_GIT_ACCESS_TOKEN=$ACCESS_TOKEN"
fi
# 卷挂载
DOCKER_CMD+=" -v $SESSION_DIR:/app/sessions"
# 如果有 SSH 密钥，挂载它
if [[ -f "$HOME/.ssh/id_rsa" ]]; then
 cp "$HOME/.ssh/id_rsa" "$SSH_DIR/id_rsa"
 chmod 600 "$SSH_DIR/id_rsa"
 DOCKER_CMD+=" -v $SSH_DIR:/root/.ssh:ro"
fi
# macOS 网络支持
if [[ "$(uname)" == "Darwin" ]]; then
 DOCKER_CMD+=" --add-host=host.docker.internal:host-gateway"
fi
# 镜像名称
DOCKER_CMD+=" $IMAGE_NAME"
# 显示测试配置
echo ""
log_info "============================================="
log_info " Task 容器测试配置"
log_info "============================================="
echo ""
echo " 任务 ID: $TASK_ID"
echo " 项目 ID: $PROJECT_ID"
echo " 模式: $MODE"
echo " 任务描述: ${TASK_DESCRIPTION:0:50}..."
echo " 仓库 URL: $REPO_URL"
echo " 回调地址: $SERVER_URL/api"
echo " API Key: ${API_KEY:+[已设置]} ${API_KEY:-[未设置]}"
echo " Base URL: ${BASE_URL:-[未设置]}"
echo " Access Token: ${ACCESS_TOKEN:+[已设置]} ${ACCESS_TOKEN:-[未设置]}"
echo "${ACCESS_TOKEN}"
echo ""
log_info "============================================="
echo ""
# 执行或显示命令
if [[ "$DRY_RUN" == true ]]; then
 log_warn "[DRY RUN] 将要执行的命令:"
 echo ""
 echo "$DOCKER_CMD" | tr ' ' '\n' | sed 's/^/ /'
 echo ""
 log_info "临时目录: $TMP_DIR"
 log_warn "Dry run 模式不会清理临时目录"
else
 log_info "启动 Task 容器..."
 echo ""
 # 捕获退出信号以清理
 cleanup {
 log_info "清理临时文件..."
 rm -rf "$TMP_DIR"
 }
 trap cleanup EXIT
 # 执行容器
 set +e
 eval "$DOCKER_CMD"
 EXIT_CODE=$?
 set -e
 echo ""
 if [[ $EXIT_CODE -eq 0 ]]; then
 log_success "Task 容器执行成功"
 else
 log_error "Task 容器执行失败 (退出码: $EXIT_CODE)"
 fi
 # 显示会话文件
 if [[ -f "$SESSION_DIR/$TASK_ID.json" ]]; then
 log_info "会话文件内容:"
 cat "$SESSION_DIR/$TASK_ID.json" | python3 -m json.tool 2>/dev/null || cat "$SESSION_DIR/$TASK_ID.json"
 fi
 exit $EXIT_CODE
fi
