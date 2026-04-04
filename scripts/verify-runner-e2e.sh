#!/usr/bin/env bash
# Runner 基础设施 E2E 验证脚本
# 用法: ./scripts/verify-runner-e2e.sh
#
# 前置条件:
# - Docker Engine 已安装并运行
# - Go 1.25+ 已安装
# - 当前目录为项目根目录
#
# 验证范围:
#: Runner 注册 + 心跳保持
#: Docker 容器隔离执行 + 结果回报
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"
# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'
PASS=0
FAIL=0
STEP=0
log_step {
 STEP=$((STEP + 1))
 echo -e "\n${BLUE}=== 步骤 $STEP: $1 ===${NC}"
}
log_pass {
 PASS=$((PASS + 1))
 echo -e "${GREEN}[PASS] $1${NC}"
}
log_fail {
 FAIL=$((FAIL + 1))
 echo -e "${RED}[FAIL] $1${NC}"
}
log_info {
 echo -e "${YELLOW}[INFO] $1${NC}"
}
cleanup {
 log_step "清理环境"
 # 停止 Runner（如果在运行）
 if [ -n "${RUNNER_PID:-}" ] && kill -0 "$RUNNER_PID" 2>/dev/null; then
 kill "$RUNNER_PID" 2>/dev/null || true
 wait "$RUNNER_PID" 2>/dev/null || true
 log_info "Runner 进程已停止"
 fi
 # 停止 Docker Compose
 docker compose down --remove-orphans 2>/dev/null || true
 log_info "Docker Compose 已停止"
}
trap cleanup EXIT
# ============================================================================
# 阶段 1: 环境准备
# ============================================================================
log_step "检查前置依赖"
command -v docker >/dev/null 2>&1 && log_pass "Docker 已安装: $(docker --version)" || { log_fail "Docker 未安装"; exit 1; }
command -v go >/dev/null 2>&1 && log_pass "Go 已安装: $(go version)" || { log_fail "Go 未安装"; exit 1; }
docker info >/dev/null 2>&1 && log_pass "Docker daemon 运行中" || { log_fail "Docker daemon 未运行"; exit 1; }
log_step "构建 friday-task 镜像"
docker build -t friday-task:latest ./task/ && log_pass "friday-task:latest 镜像构建成功" || { log_fail "friday-task 镜像构建失败"; exit 1; }
log_step "启动 Server + Web + Redis (Docker Compose)"
# per: Docker Compose 本地全栈启动
SECRET_KEY=test-secret-for-e2e \
DEBUG=true \
FRIDAY_ADMIN_USERNAME=admin \
FRIDAY_ADMIN_PASSWORD=admin123 \
GUNICORN_WORKERS=1 \
 docker compose -f docker-compose.yaml -f docker-compose.build.yaml up --build -d server web redis
log_info "等待 Server 健康检查通过..."
timeout 120 bash -c 'until docker inspect --format="{{.State.Health.Status}}" friday-server 2>/dev/null | grep -q healthy; do sleep 2; done' \
 && log_pass "Server 健康检查通过" || { log_fail "Server 启动超时"; docker compose logs server; exit 1; }
# ============================================================================
# 阶段 2: -- Runner 注册与心跳 (per,, )
# ============================================================================
log_step "创建 Registration Token"
REG_TOKEN=$(docker exec friday-server python manage.py shell -c "
from runners.models import RegistrationToken, generate_token, hash_token
from django.utils import timezone
from datetime import timedelta
from accounts.models import User
user = User.objects.first
token = generate_token
RegistrationToken.objects.create(
 token_hash=hash_token(token),
 expires_at=timezone.now + timedelta(hours=24),
 created_by=user,
)
print(token)
" 2>/dev/null)
if [ -n "$REG_TOKEN" ]; then
 log_pass "Registration Token 创建成功: ${REG_TOKEN:0:8}..."
else
 log_fail "Registration Token 创建失败"
 exit 1
fi
log_step "编译 Go Runner"
cd "$PROJECT_ROOT/runner"
go build -o friday-runner ./cmd/friday-runner/ && log_pass "Runner 编译成功" || { log_fail "Runner 编译失败"; exit 1; }
cd "$PROJECT_ROOT"
log_step "注册 Runner (per )"
# per: 手动流程验证 -- friday-runner register
./runner/friday-runner register \
 --url http://localhost:10241 \
 --token "$REG_TOKEN" \
 --name test-e2e-runner \
 && log_pass "Runner 注册成功" || { log_fail "Runner 注册失败"; exit 1; }
log_step "启动 Runner 并验证心跳 (per )"
./runner/friday-runner run &
RUNNER_PID=$!
log_info "Runner PID: $RUNNER_PID"
# 等待 Runner 连接和首次心跳（30 秒间隔）
sleep 10
# 检查 Runner 在线状态
RUNNER_STATUS=$(docker exec friday-server python manage.py shell -c "
from runners.models import Runner
r = Runner.objects.filter(name='test-e2e-runner').first
print(r.status if r else 'NOT_FOUND')
" 2>/dev/null)
if [ "$RUNNER_STATUS" = "online" ]; then
 log_pass "Runner 状态: online"
else
 log_fail "Runner 状态异常: $RUNNER_STATUS"
fi
# per: 等待 3+ 个心跳周期（90 秒）
log_info "等待 3 个心跳周期 (90 秒)..."
sleep 90
HEARTBEAT_STATUS=$(docker exec friday-server python manage.py shell -c "
from runners.models import Runner
r = Runner.objects.filter(name='test-e2e-runner').first
print(r.status if r else 'NOT_FOUND')
" 2>/dev/null)
if [ "$HEARTBEAT_STATUS" = "online" ]; then
 log_pass "3 个心跳后 Runner 仍在线 ( 心跳验证通过)"
else
 log_fail "心跳后 Runner 状态异常: $HEARTBEAT_STATUS"
fi
# per: 验证断连恢复
log_step "验证断连恢复 (per )"
kill "$RUNNER_PID" 2>/dev/null || true
wait "$RUNNER_PID" 2>/dev/null || true
log_info "Runner 已停止，等待 Server 检测离线..."
sleep 15
OFFLINE_STATUS=$(docker exec friday-server python manage.py shell -c "
from runners.models import Runner
r = Runner.objects.filter(name='test-e2e-runner').first
print(r.status if r else 'NOT_FOUND')
" 2>/dev/null)
if [ "$OFFLINE_STATUS" = "offline" ]; then
 log_pass "Runner 断连后状态: offline"
else
 log_fail "断连后状态异常: $OFFLINE_STATUS (预期 offline)"
fi
log_info "重新启动 Runner..."
./runner/friday-runner run &
RUNNER_PID=$!
sleep 15
RECOVER_STATUS=$(docker exec friday-server python manage.py shell -c "
from runners.models import Runner
r = Runner.objects.filter(name='test-e2e-runner').first
print(r.status if r else 'NOT_FOUND')
" 2>/dev/null)
if [ "$RECOVER_STATUS" = "online" ]; then
 log_pass "断连恢复: Runner 重新上线 ( 断连恢复验证通过)"
else
 log_fail "断连恢复失败: $RECOVER_STATUS (预期 online)"
fi
# ============================================================================
# 阶段 3: -- 容器隔离执行 (per,, )
# ============================================================================
log_step "创建真实任务并分发到 Runner (per )"
log_info "通过 Django shell 创建 SubAgentSession + 调用 TaskDispatcher 分发真实任务"
# 获取 Runner ID
RUNNER_ID=$(docker exec friday-server python manage.py shell -c "
from runners.models import Runner
r = Runner.objects.filter(name='test-e2e-runner', status='online').first
print(r.id if r else 'NOT_FOUND')
" 2>/dev/null)
if [ "$RUNNER_ID" = "NOT_FOUND" ] || [ -z "$RUNNER_ID" ]; then
 log_fail "Runner 不在线，无法分发任务"
else
 log_pass "Runner 在线 (ID: ${RUNNER_ID:0:8}...)"
fi
# 创建测试任务（SubAgentSession）并通过 Dispatcher 分发
DISPATCH_RESULT=$(docker exec friday-server python manage.py shell -c "
import asyncio
from accounts.models import User
from agents.models import AgentSession
from subagent.models import SubAgentSession
from runners.dispatcher import DispatchTask, get_dispatcher
user = User.objects.first
# 创建 AgentSession 作为 main_session
main_session, _ = AgentSession.objects.get_or_create(
 session_id='e2e-main-session-001',
 defaults={'status': 'running', 'created_by': user, 'workflow_id': ''},
)
# 创建 SubAgentSession 作为任务载体
sub_session, _ = SubAgentSession.objects.get_or_create(
 session_id='e2e-test-task-001',
 defaults={
 'main_session': main_session,
 'repo_url': 'https://github.com/test/e2e-repo.git',
 'task_type': 'coding',
 'status': 'pending',
 },
)
# 构造 DispatchTask
task = DispatchTask(
 task_id='e2e-test-task-001',
 task_type='coding',
 tags=, # global scope runner 不限标签
 image='friday-task:latest',
 repo_url='https://github.com/test/e2e-repo.git',
 branch='main',
 target_branch='main',
 prompt='echo hello-from-e2e-test',
 timeout=120,
 node_execution_id='e2e-node-001',
 session_id='e2e-test-task-001',
 metadata={'e2e': True},
)
# 通过 TaskDispatcher 分发到 Runner
async def dispatch_real_task:
 dispatcher = get_dispatcher
 await dispatcher.dispatch(task)
 return 'dispatched'
result = asyncio.run(dispatch_real_task)
print(result)
" 2>/dev/null)
if echo "$DISPATCH_RESULT" | grep -q "dispatched"; then
 log_pass "任务已通过 TaskDispatcher 分发到 Runner (per )"
else
 log_fail "任务分发失败: $DISPATCH_RESULT"
fi
log_step "验证容器隔离执行 (per )"
log_info "等待 Runner 接收任务并创建 Docker 容器 (最多 60 秒)..."
CONTAINER_FOUND=false
for i in $(seq 1 12); do
 sleep 5
 # 检查是否有 friday-task 容器被创建
 TASK_CONTAINER=$(docker ps -a --filter "ancestor=friday-task:latest" --format "{{.ID}} {{.Status}}" 2>/dev/null | head -1)
 if [ -n "$TASK_CONTAINER" ]; then
 CONTAINER_FOUND=true
 CONTAINER_ID=$(echo "$TASK_CONTAINER" | awk '{print $1}')
 log_pass "Docker 容器已创建: $TASK_CONTAINER"
 break
 fi
done
if [ "$CONTAINER_FOUND" = true ]; then
 # 检查容器日志是否可见 (per: 执行日志可在 Server 端查看)
 log_info "获取容器执行日志..."
 CONTAINER_LOGS=$(docker logs "$CONTAINER_ID" 2>&1 | head -20)
 if [ -n "$CONTAINER_LOGS" ]; then
 log_pass "容器日志可获取 (per 容器隔离验证通过)"
 echo "$CONTAINER_LOGS" | head -5
 else
 log_info "容器日志为空（容器可能还在执行中或已完成）"
 fi
else
 log_fail "60 秒内未检测到 friday-task 容器启动 (per )"
fi
log_step "验证结果回报 (per )"
log_info "等待任务完成并检查 Server 端状态 (最多 120 秒)..."
RESULT_REPORTED=false
for i in $(seq 1 24); do
 sleep 5
 ASSIGNMENT_STATUS=$(docker exec friday-server python manage.py shell -c "
from runners.models import RunnerTaskAssignment
a = RunnerTaskAssignment.objects.filter(session__session_id='e2e-test-task-001').first
if a:
 print(f'{a.status}')
else:
 print('NOT_FOUND')
" 2>/dev/null)
 if [ "$ASSIGNMENT_STATUS" = "completed" ]; then
 RESULT_REPORTED=true
 log_pass "任务结果回报成功: status=completed (per 结果回报验证通过)"
 break
 elif [ "$ASSIGNMENT_STATUS" = "failed" ]; then
 RESULT_REPORTED=true
 log_info "任务执行失败但结果已回报: status=failed (结果回报机制正常)"
 # E2E 测试中使用假 repo，失败是预期的；关键是结果能回报
 log_pass "任务结果回报机制正常: status=failed (per 结果回报验证通过)"
 break
 elif [ "$ASSIGNMENT_STATUS" = "running" ]; then
 log_info "任务执行中... ($((i * 5))秒)"
 fi
done
if [ "$RESULT_REPORTED" = false ]; then
 log_fail "120 秒内未收到任务结果回报 (per )"
 # 输出 Runner 日志帮助调试
 log_info "Runner 最近日志:"
 docker exec friday-server python manage.py shell -c "
from runners.models import RunnerEvent
events = RunnerEvent.objects.order_by('-created_at')[:5]
for e in events:
 print(f'{e.event_type}: {e.data}')
" 2>/dev/null || true
fi
# 额外检查: SubAgentSession 状态是否同步更新
SESSION_STATUS=$(docker exec friday-server python manage.py shell -c "
from subagent.models import SubAgentSession
s = SubAgentSession.objects.filter(session_id='e2e-test-task-001').first
print(s.status if s else 'NOT_FOUND')
" 2>/dev/null)
log_info "SubAgentSession 最终状态: $SESSION_STATUS"
# ============================================================================
# 验证报告
# ============================================================================
echo -e "\n${BLUE}============================================${NC}"
echo -e "${BLUE} Runner E2E 验证报告${NC}"
echo -e "${BLUE}============================================${NC}"
echo -e "通过: ${GREEN}$PASS${NC}"
echo -e "失败: ${RED}$FAIL${NC}"
echo ""
if [ "$FAIL" -eq 0 ]; then
 echo -e "${GREEN}所有自动化验证通过!${NC}"
 exit 0
else
 echo -e "${RED}有 $FAIL 项验证失败，请检查输出日志${NC}"
 exit 1
fi
