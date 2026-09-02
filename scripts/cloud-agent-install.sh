#!/usr/bin/env bash
# Friday AI - Cloud Agent 环境安装脚本（幂等，供 .cursor/environment.json 的 install 阶段调用）
#
# 职责边界：只做「可重建的持久化准备」——系统包、工具链、项目依赖、submodule、
# 迁移后的 SQLite 库。常驻服务（Postgres / Redis / Qdrant / Docker daemon）一律
# 交给 scripts/cloud-agent-start.sh，因为进程活不过快照。
#
# 版本一律从仓库自身的声明里读，不在本脚本里写死，避免与仓库 pin 漂移：
#   Python → server/.python-version   Node → web/.nvmrc
#   pnpm   → web/package.json         Go   → runner/go.mod
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# 工具链软链目录。必须排在 PATH 的 /exec-daemon 之前才能盖住基础镜像自带的旧版本
# node，所以在 ~/.bashrc 里前插（见 ensure_path_block）。
TOOLCHAIN_BIN="$HOME/.local/friday-toolchain/bin"

PY_VERSION="$(tr -d '[:space:]' < server/.python-version)"
NODE_VERSION="$(tr -d '[:space:]' < web/.nvmrc)"
PNPM_VERSION="$(sed -n 's/.*"packageManager"[[:space:]]*:[[:space:]]*"pnpm@\([^"]*\)".*/\1/p' web/package.json)"
GO_VERSION="$(awk '/^go[[:space:]]+[0-9]/{print $2; exit}' runner/go.mod)"
# Qdrant 不在仓库里 pin（compose 用 :latest），这里固定一个版本保证可重复构建。
QDRANT_VERSION="${FRIDAY_QDRANT_VERSION:-1.19.0}"
# Ubuntu 24.04 自带 postgresql-16，而 CI / compose 都用 17，走 PGDG 对齐大版本。
PG_MAJOR="${FRIDAY_PG_MAJOR:-17}"

log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[warn] %s\033[0m\n' "$*"; }

log "Friday AI Cloud Agent 环境安装"
echo "python=$PY_VERSION node=$NODE_VERSION pnpm=$PNPM_VERSION go=$GO_VERSION qdrant=$QDRANT_VERSION postgres=$PG_MAJOR"

mkdir -p "$TOOLCHAIN_BIN"
export PATH="$TOOLCHAIN_BIN:$HOME/.local/bin:/usr/local/go/bin:$PATH"

# ---------------------------------------------------------------------------
# 1. 系统包
# ---------------------------------------------------------------------------
apt_install_missing() {
  local missing=()
  for pkg in "$@"; do
    dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed" || missing+=("$pkg")
  done
  if [ ${#missing[@]} -eq 0 ]; then
    echo "已安装，跳过: $*"
    return 0
  fi
  echo "安装: ${missing[*]}"
  # --force-confold 必带：基础镜像已改过 /etc/fuse.conf 之类的配置文件，
  # 缺了它 dpkg 会在 conffile 冲突处等交互输入，install 阶段直接卡死/失败。
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    -o Dpkg::Options::=--force-confdef \
    -o Dpkg::Options::=--force-confold \
    "${missing[@]}"
}

log "系统包"
sudo apt-get update -qq

# mysqlclient 需要 default-libmysqlclient-dev + pkg-config 才能编译；
# fuse-overlayfs / iptables / uidmap 是 VM 内嵌套 Docker daemon 的前置。
apt_install_missing \
  build-essential pkg-config curl ca-certificates git jq unzip tmux ripgrep \
  default-libmysqlclient-dev libpq-dev \
  redis-server \
  docker.io docker-compose-v2 fuse-overlayfs iptables uidmap

# PostgreSQL：优先 PGDG 的 $PG_MAJOR，仓库不可用时退回发行版自带版本。
if ! ls "/usr/lib/postgresql/$PG_MAJOR/bin/postgres" >/dev/null 2>&1; then
  log "PostgreSQL $PG_MAJOR (PGDG)"
  if [ ! -f /etc/apt/sources.list.d/pgdg.list ]; then
    sudo install -d -m 0755 /usr/share/postgresql-common/pgdg
    sudo curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
      https://www.postgresql.org/media/keys/ACCC4CF8.asc
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo "$VERSION_CODENAME")-pgdg main" \
      | sudo tee /etc/apt/sources.list.d/pgdg.list >/dev/null
    sudo apt-get update -qq
  fi
  if ! apt_install_missing "postgresql-$PG_MAJOR" "postgresql-client-$PG_MAJOR"; then
    warn "PGDG postgresql-$PG_MAJOR 安装失败，退回发行版自带 PostgreSQL"
    apt_install_missing postgresql postgresql-client
  fi
fi

# 装完立刻停掉 apt 拉起的服务：常驻进程属于 start 阶段，装进快照的只应是数据目录。
sudo systemctl disable --now redis-server postgresql docker containerd 2>/dev/null || true
sudo pkill -x redis-server 2>/dev/null || true

# 让 ubuntu 用户免 sudo 用 docker.sock（docker 组由 docker.io 包创建）
sudo usermod -aG docker "$USER" 2>/dev/null || true

# ---------------------------------------------------------------------------
# 2. PATH 前插块
# ---------------------------------------------------------------------------
ensure_path_block() {
  local marker="# >>> friday-ai cloud agent toolchain >>>"
  local rc="$HOME/.bashrc"
  touch "$rc"
  if grep -qF "$marker" "$rc"; then
    return 0
  fi
  log "写入 PATH 前插块到 ~/.bashrc"
  cat >> "$rc" <<'EOF'

# >>> friday-ai cloud agent toolchain >>>
# 必须前插：基础镜像的 /exec-daemon 在 PATH 最前面且自带一个旧版 node，
# 追加到尾部会被它盖住，仓库声明的 node/pnpm 版本就形同虚设。
export PATH="$HOME/.local/friday-toolchain/bin:$HOME/.local/bin:/usr/local/go/bin:$PATH"
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
# <<< friday-ai cloud agent toolchain <<<
EOF
}
ensure_path_block

link_tool() {
  local target="$1" name="$2"
  [ -x "$target" ] || { warn "缺少 $target，跳过软链 $name"; return 0; }
  ln -sfn "$target" "$TOOLCHAIN_BIN/$name"
}

# ---------------------------------------------------------------------------
# 3. uv + Python
# ---------------------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  log "安装 uv"
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$HOME/.local/bin" sh
fi
link_tool "$HOME/.local/bin/uv" uv
link_tool "$HOME/.local/bin/uvx" uvx
export PATH="$HOME/.local/bin:$PATH"

log "Python $PY_VERSION (uv 托管)"
uv python install "$PY_VERSION"

# ---------------------------------------------------------------------------
# 4. Go
# ---------------------------------------------------------------------------
if [ "$(/usr/local/go/bin/go version 2>/dev/null | awk '{print $3}')" != "go$GO_VERSION" ]; then
  log "Go $GO_VERSION"
  tmp="$(mktemp -d)"
  curl -fsSL -o "$tmp/go.tgz" "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz"
  sudo rm -rf /usr/local/go
  sudo tar -C /usr/local -xzf "$tmp/go.tgz"
  rm -rf "$tmp"
else
  echo "Go go$GO_VERSION 已就位"
fi
link_tool /usr/local/go/bin/go go
link_tool /usr/local/go/bin/gofmt gofmt

# ---------------------------------------------------------------------------
# 5. Node + pnpm
# ---------------------------------------------------------------------------
export NVM_DIR="$HOME/.nvm"
if [ ! -s "$NVM_DIR/nvm.sh" ]; then
  log "安装 nvm"
  curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
fi
# shellcheck disable=SC1091
. "$NVM_DIR/nvm.sh"

if [ ! -d "$NVM_DIR/versions/node/v$NODE_VERSION" ]; then
  log "Node $NODE_VERSION"
  nvm install "$NODE_VERSION"
fi
nvm alias default "$NODE_VERSION" >/dev/null
nvm use "$NODE_VERSION" >/dev/null

NODE_BIN="$NVM_DIR/versions/node/v$NODE_VERSION/bin"
log "pnpm $PNPM_VERSION (corepack)"
"$NODE_BIN/corepack" enable --install-directory "$NODE_BIN" >/dev/null 2>&1 || "$NODE_BIN/corepack" enable
"$NODE_BIN/corepack" prepare "pnpm@$PNPM_VERSION" --activate

for t in node npm npx corepack pnpm pnpx; do
  link_tool "$NODE_BIN/$t" "$t"
done
export PATH="$TOOLCHAIN_BIN:$PATH"
hash -r 2>/dev/null || true

# ---------------------------------------------------------------------------
# 6. Qdrant（原生二进制，不依赖 Docker daemon）
# ---------------------------------------------------------------------------
if [ "$(qdrant --version 2>/dev/null | awk '{print $2}')" != "$QDRANT_VERSION" ]; then
  log "Qdrant $QDRANT_VERSION"
  tmp="$(mktemp -d)"
  curl -fsSL -o "$tmp/qdrant.tgz" \
    "https://github.com/qdrant/qdrant/releases/download/v${QDRANT_VERSION}/qdrant-x86_64-unknown-linux-gnu.tar.gz"
  tar -C "$tmp" -xzf "$tmp/qdrant.tgz"
  sudo install -m 755 "$tmp/qdrant" /usr/local/bin/qdrant
  rm -rf "$tmp"
else
  echo "Qdrant $QDRANT_VERSION 已就位"
fi
# 二进制启动时会读 ./config/config.yaml；start 脚本在固定工作目录里放一份最小配置。
QDRANT_HOME="$HOME/.local/share/friday-qdrant"
mkdir -p "$QDRANT_HOME/config" "$QDRANT_HOME/storage" "$QDRANT_HOME/snapshots"
cat > "$QDRANT_HOME/config/config.yaml" <<EOF
storage:
  storage_path: $QDRANT_HOME/storage
  snapshots_path: $QDRANT_HOME/snapshots
service:
  host: 127.0.0.1
  http_port: 6333
  grpc_port: 6334
telemetry_disabled: true
EOF

# ---------------------------------------------------------------------------
# 7. Submodule（mcp / skills）
# ---------------------------------------------------------------------------
# skills / mcp 是独立仓库，server 与 task 的 skills 一致性守卫测试要读它们。
# main 上 skills 的 pin 指向一个上游已被 force-push 覆盖的 commit，`submodule
# update` 会硬失败；这里退化为「至少把默认分支检出到位」，让守卫有文件可扫，
# 而不是让整个环境装不上。
log "Submodule"
# 逐个子模块处理，不用全局 --remote 兜底：那会把本来 pin 正常的子模块也顶到默认分支
# HEAD，反而弄坏 test_mcp_package_alignment 之类「按 pin 比对」的守卫。
git submodule init >/dev/null
while read -r _ sm_path; do
  [ -n "$sm_path" ] || continue
  if git submodule update --init --recursive -- "$sm_path" >/dev/null 2>&1; then
    echo "  ✓ $sm_path 已对齐 pin"
    continue
  fi
  # 走到这里通常是 pin 指向的 commit 在上游被 force-push 覆盖了（main 上 skills
  # 当前就是这种状态，GitHub Actions 也因此在 checkout 阶段直接失败）。环境不该被
  # 这个上游状态卡死，退化为「检出默认分支」，让依赖这些文件的用例至少有东西可读。
  warn "$sm_path 的 pin 无法检出，退回默认分支"
  git -C "$sm_path" fetch --quiet origin 2>/dev/null || true
  git -C "$sm_path" remote set-head origin --auto >/dev/null 2>&1 || true
  default_ref="$(git -C "$sm_path" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || echo origin/main)"
  git -C "$sm_path" reset --hard "$default_ref" >/dev/null 2>&1 \
    && echo "  ! $sm_path 已检出 $default_ref（与 .gitmodules 的 pin 不一致）" \
    || warn "$sm_path 仍未就绪"
done < <(git config --file .gitmodules --get-regexp '^submodule\..*\.path$')

# ---------------------------------------------------------------------------
# 8. 项目依赖
# ---------------------------------------------------------------------------
log "server 依赖 (uv sync --locked --dev)"
(cd server && uv sync --locked --dev)

log "task 依赖 (uv sync --locked --dev)"
(cd task && uv sync --locked --dev)

log "web 依赖 (pnpm install --frozen-lockfile)"
(cd web && pnpm install --frozen-lockfile)

log "Playwright chromium"
(cd web && pnpm exec playwright install --with-deps chromium)

log "runner Go 模块与构建缓存"
(cd runner && go mod download && go build ./...)

# ---------------------------------------------------------------------------
# 9. Django 迁移（默认 SQLite 路径）
# ---------------------------------------------------------------------------
# 刻意不生成 .env：settings 的默认值就是 SQLite + 内存 channel layer，
# 而 pytest 带 --disable-socket，一旦 .env 把 DATABASE_URL 指到 Postgres，
# 默认测试套件会因为禁用 socket 而整体失败。Postgres/Redis/Qdrant 由 start
# 阶段拉起，需要时用环境变量显式切过去（见 AGENTS.md）。
log "Django check + migrate (SQLite)"
(cd server && uv run python manage.py check && uv run python manage.py migrate --noinput)

log "安装完成"
printf '%s\n' \
  "node   $(node --version 2>/dev/null)" \
  "pnpm   $(pnpm --version 2>/dev/null)" \
  "python $(cd server && uv run python --version 2>/dev/null)" \
  "go     $(go version 2>/dev/null)" \
  "qdrant $(qdrant --version 2>/dev/null)"
