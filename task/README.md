# Friday Task
AI 驱动的开发任务执行器，使用 Claude Agent SDK 自动化代码生成和修改。
## 功能特性
- **Plan 模式**: 分析代码库并生成详细的实施计划（只读，不修改代码）
- **Execute 模式**: 根据计划或描述自动实现代码变更（创建分支，提交推送）
- **Session 管理**: 支持会话恢复，可以从中断处继续执行
- **独立运行**: 支持命令行直接调用，无需 server 支持
- **容器模式**: 作为 Docker 容器被 Friday Server 调度执行
## 快速开始
### 安装
```bash
# 使用 uv（推荐）
cd task
uv sync
# 或使用 pip
pip install -e .
```
### 命令行使用
```bash
# 查看帮助
friday-task --help
# Plan 模式 - 分析并生成计划
friday-task plan \
 --git-url git@github.com:org/repo.git \
 --branch main \
 --description "添加用户登录功能，包括 JWT 认证和密码加密" \
 --api-key $ANTHROPIC_API_KEY
# Execute 模式 - 执行变更
friday-task exec \
 --git-url git@github.com:org/repo.git \
 --branch main \
 --new-branch friday/feature-login \
 --description "添加用户登录功能，包括 JWT 认证和密码加密" \
 --api-key $ANTHROPIC_API_KEY
# 恢复会话
friday-task resume --session-id <session-id> --mode exec
```
### Docker 使用
```bash
# 构建镜像
docker build -t friday-task:latest .
# CLI 模式
docker run friday-task:latest plan --help
docker run -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY friday-task:latest plan \
 --git-url git@github.com:org/repo.git \
 --description "添加用户登录功能"
# 容器模式（环境变量配置）
docker run \
 -e FRIDAY_TASK_TASK_ID=task-001 \
 -e FRIDAY_TASK_GIT_REPO_URL=git@github.com:org/repo.git \
 -e FRIDAY_TASK_TASK_DESCRIPTION="添加用户登录功能" \
 -e FRIDAY_TASK_TASK_MODE=plan \
 -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
 friday-task:latest
```
## 命令参数
### 通用参数
| 参数 | 环境变量 | 必需 | 说明 |
|------|----------|------|------|
| `--git-url` | FRIDAY_TASK_GIT_REPO_URL | ✅ | Git 仓库 URL |
| `--branch` | FRIDAY_TASK_GIT_BRANCH | ❌ | 基础分支（默认 main）|
| `--description` | FRIDAY_TASK_TASK_DESCRIPTION | ✅ | 任务描述 |
| `--api-key` | ANTHROPIC_API_KEY | ✅ | Claude API Key |
| `--base-url` | ANTHROPIC_BASE_URL | ❌ | API Base URL（代理）|
| `--ssh-key` | FRIDAY_TASK_GIT_SSH_KEY | ❌* | SSH 私钥内容 |
| `--access-token` | FRIDAY_TASK_GIT_ACCESS_TOKEN | ❌* | Git 访问令牌 |
| `--callback-url` | FRIDAY_TASK_CALLBACK_URL | ❌ | 状态回调 URL |
| `--session-dir` | FRIDAY_TASK_SESSION_DIR | ❌ | 会话目录（默认 ./sessions）|
*注：`--ssh-key` 或 `--access-token` 至少需要一个用于 Git 认证
### Exec 模式特有参数
| 参数 | 环境变量 | 必需 | 说明 |
|------|----------|------|------|
| `--new-branch` | FRIDAY_TASK_GIT_NEW_BRANCH | ❌ | 功能分支名称（默认自动生成）|
| `--resume` | - | ❌ | 恢复的会话 ID |
## 模式说明
### Plan 模式
- 使用 `permission_mode="plan"`（只读）
- 不创建新分支，在目标分支上分析
- 不修改任何文件
- 输出详细的实施计划
### Execute 模式
- 使用 `permission_mode="bypassPermissions"`（完全访问）
- 创建新的功能分支
- 自动实现代码变更
- 提交并推送到远程
- 支持无人值守执行
## 开发
### 运行测试
```bash
cd task
uv sync --dev
uv run pytest
```
### 代码检查
```bash
uv run ruff check src/
uv run ruff format src/
```
## 架构
```
task/
├── src/friday_task/
│ ├── __init__.py # 包初始化
│ ├── __main__.py # 模块入口
│ ├── cli.py # 命令行接口
│ ├── config.py # 配置管理
│ ├── runner.py # 容器模式入口
│ ├── claude_runner.py # Claude Agent SDK 封装
│ ├── git_ops.py # Git 操作
│ └── callback.py # 状态回调
└── tests/ # 测试目录
```
## 许可证
MIT License
