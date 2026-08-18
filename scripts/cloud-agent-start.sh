#!/usr/bin/env bash
# Friday AI - Cloud Agent 每次开机的服务拉起脚本（供 .cursor/environment.json 的 start 阶段调用）
#
# 只做「进程级」的事：把 Postgres / Redis / Qdrant / Docker daemon 拉起来并等到可用。
# 依赖安装、编译、迁移一律不在这里做——那些属于 install，放到每次开机会拖慢启动
# 并把本该在安装期暴露的失败推迟到运行期。
#
# 这台 VM 的 PID 1 是 tini，没有 systemd，所以全部用 pg_ctlcluster / 裸进程 +
# nohup 的方式管理，并逐个做就绪探测。脚本可重复执行：已在跑的服务直接跳过。
set -uo pipefail

STATE_DIR="$HOME/.friday-env"
LOG_DIR="$STATE_DIR/logs"
mkdir -p "$LOG_DIR"

QDRANT_HOME="$HOME/.local/share/friday-qdrant"
PG_MAJOR="${FRIDAY_PG_MAJOR:-}"
# 允许把 Docker 从「尽力而为」提升为硬要求（嵌套 daemon 偶发起不来时便于定位）
REQUIRE_DOCKER="${FRIDAY_REQUIRE_DOCKER:-0}"

FAILED=()

log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok() { printf '\033[0;32m  ✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m  ! %s\033[0m\n' "$*"; }

# 等待条件成立，最多 $1 秒
wait_for() {
  local timeout="$1"; shift
  local deadline=$((SECONDS + timeout))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if "$@" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  return 1
}

# ---------------------------------------------------------------------------
# Postgres
# ---------------------------------------------------------------------------
start_postgres() {
  log "PostgreSQL"
  if [ -z "$PG_MAJOR" ]; then
    PG_MAJOR="$(ls /usr/lib/postgresql 2>/dev/null | sort -rn | head -1)"
  fi
  if [ -z "$PG_MAJOR" ]; then
    warn "未安装 PostgreSQL，跳过（先跑 scripts/cloud-agent-install.sh）"
    FAILED+=(postgres)
    return
  fi

  local bindir="/usr/lib/postgresql/$PG_MAJOR/bin"
  export PATH="$bindir:$PATH"

  if pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
    ok "已在运行 (major=$PG_MAJOR)"
  else
    # Debian 包安装时会建好 main 集簇；缺失时（例如镜像里被裁掉）现场初始化。
    if ! [ -d "/etc/postgresql/$PG_MAJOR/main" ]; then
      sudo pg_createcluster "$PG_MAJOR" main >/dev/null 2>&1 || warn "pg_createcluster 失败"
    fi
    sudo pg_ctlcluster "$PG_MAJOR" main start 2>&1 | tail -3 || true
    if ! wait_for 30 pg_isready -h 127.0.0.1 -p 5432; then
      warn "启动超时，日志见 /var/log/postgresql/"
      FAILED+=(postgres)
      return
    fi
    ok "已启动 (major=$PG_MAJOR)"
  fi

  # 角色与库：与 CI（friday/friday）和 compose 默认值保持一致，
  # 让 -m postgres_queue 那套测试无需改任何连接串就能跑。
  sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='friday'" 2>/dev/null | grep -q 1 \
    || sudo -u postgres psql -c "CREATE ROLE friday LOGIN SUPERUSER PASSWORD 'friday'" >/dev/null 2>&1
  for db in friday friday_test; do
    sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$db'" 2>/dev/null | grep -q 1 \
      || sudo -u postgres createdb -O friday "$db" >/dev/null 2>&1
  done
  ok "角色 friday / 库 friday, friday_test 就绪"
}

# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------
start_redis() {
  log "Redis"
  if redis-cli ping 2>/dev/null | grep -q PONG; then
    ok "已在运行"
    return
  fi
  if ! command -v redis-server >/dev/null 2>&1; then
    warn "未安装 redis-server，跳过"
    FAILED+=(redis)
    return
  fi
  # 不读 /etc/redis/redis.conf：它是 redis:redis 0640，ubuntu 读不了。
  # 直接用命令行参数起一个绑本机的实例，appendonly 与 compose 里的配置对齐。
  redis-server \
    --daemonize yes \
    --bind 127.0.0.1 \
    --port 6379 \
    --appendonly yes \
    --dir "$STATE_DIR" \
    --logfile "$LOG_DIR/redis.log" \
    --pidfile "$STATE_DIR/redis.pid"
  if wait_for 20 bash -c 'redis-cli ping | grep -q PONG'; then
    ok "已启动 (127.0.0.1:6379)"
  else
    warn "启动超时，日志见 $LOG_DIR/redis.log"
    FAILED+=(redis)
  fi
}

# ---------------------------------------------------------------------------
# Qdrant
# ---------------------------------------------------------------------------
start_qdrant() {
  log "Qdrant"
  if curl -fsS http://127.0.0.1:6333/healthz >/dev/null 2>&1; then
    ok "已在运行"
    return
  fi
  if ! command -v qdrant >/dev/null 2>&1; then
    warn "未安装 qdrant，跳过"
    FAILED+=(qdrant)
    return
  fi
  # Qdrant 用 mmap 存向量，一仓一 collection 时会撞内核默认的 vm.max_map_count
  # (65530) 而 abort；这里尽力抬高（非命名空间参数，容器里可能被拒，不阻塞启动）。
  sudo sysctl -w vm.max_map_count=1048576 >/dev/null 2>&1 || warn "vm.max_map_count 未能调整"
  mkdir -p "$QDRANT_HOME/storage" "$QDRANT_HOME/snapshots"
  # `exec setsid --fork` 而不是 `( setsid ... & )`：后者那层括号子 shell 会留下来
  # 等 qdrant（守护进程永不结束），并继续攥着本脚本的 stdout。管道写端不关 →
  # 上层 tee 收不到 EOF → 环境启动被判定为「一直没跑完」（start-user.status 不写出），
  # 尽管服务其实全都起好了。--fork 让 setsid 立刻退出，exec 顺带消掉子 shell 自身。
  ( cd "$QDRANT_HOME" && exec setsid --fork qdrant >"$LOG_DIR/qdrant.log" 2>&1 </dev/null )
  if wait_for 45 curl -fsS http://127.0.0.1:6333/healthz; then
    ok "已启动 (127.0.0.1:6333 / gRPC 6334，无鉴权)"
  else
    warn "启动超时，日志见 $LOG_DIR/qdrant.log"
    FAILED+=(qdrant)
  fi
}

# ---------------------------------------------------------------------------
# Docker daemon
# ---------------------------------------------------------------------------
start_docker() {
  log "Docker daemon"
  if docker info >/dev/null 2>&1; then
    ok "已在运行"
    return
  fi
  if ! command -v dockerd >/dev/null 2>&1; then
    warn "未安装 dockerd，跳过（runner/task 的容器链路不可用）"
    [ "$REQUIRE_DOCKER" = "1" ] && FAILED+=(docker)
    return
  fi
  # 这台 VM 的根文件系统本身是 overlayfs，overlay2 无法在其上再叠一层，
  # 必须显式用 fuse-overlayfs（/dev/fuse 可用）；实测 bridge 网络与 iptables
  # 正常，因此不动网络配置——任务容器需要出网拉仓库和调模型。
  local driver=fuse-overlayfs
  command -v fuse-overlayfs >/dev/null 2>&1 || driver=vfs
  sudo mkdir -p /etc/docker
  printf '{\n  "storage-driver": "%s"\n}\n' "$driver" | sudo tee /etc/docker/daemon.json >/dev/null
  sudo sh -c "exec setsid --fork dockerd >'$LOG_DIR/dockerd.log' 2>&1 </dev/null"
  # 探测用 sudo：install 阶段把 ubuntu 加进了 docker 组，但组成员身份要新登录会话
  # 才生效，本进程里 `docker info` 仍会 permission denied。socket 起来后直接放开权限，
  # 让后续所有 shell（含 terminals）都能免 sudo 用 docker。
  if wait_for 60 sudo docker info; then
    sudo chmod 666 /var/run/docker.sock 2>/dev/null || true
    ok "已启动 (storage-driver=$driver，bridge 网络可用)"
  else
    warn "启动失败，日志见 $LOG_DIR/dockerd.log；容器链路不可用，其余服务不受影响"
    [ "$REQUIRE_DOCKER" = "1" ] && FAILED+=(docker)
  fi
}

start_postgres
start_redis
start_qdrant
start_docker

log "服务状态"
printf '  %-10s %s\n' \
  postgres "$(pg_isready -h 127.0.0.1 -p 5432 2>/dev/null || echo '不可用')" \
  redis    "$(redis-cli ping 2>/dev/null || echo '不可用')" \
  qdrant   "$(curl -fsS http://127.0.0.1:6333/healthz 2>/dev/null || echo '不可用')" \
  docker   "$(docker info --format '{{.ServerVersion}} ({{.Driver}})' 2>/dev/null || echo '不可用')"

if [ ${#FAILED[@]} -gt 0 ]; then
  printf '\n\033[0;31m启动失败: %s\033[0m\n' "${FAILED[*]}"
  exit 1
fi
printf '\n\033[0;32m全部就绪\033[0m\n'
