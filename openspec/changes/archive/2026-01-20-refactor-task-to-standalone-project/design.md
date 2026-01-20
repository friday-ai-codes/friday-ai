# Design: Task 模块独立化技术方案
## Context
当前 `server/task/` 模块作为 Friday AI 系统的任务执行器，运行在独立的 Docker 容器中。它使用 `claude-agent-sdk` 执行 AI 代码生成任务，并通过 HTTP 回调向 server 报告状态。
### 现有依赖关系
```
server/
├── pyproject.toml # 包含 task/src/friday_task 作为打包目标
├── src/friday/
│ └── services/
│ └── scheduler.py # 调用 Docker API 启动 task 容器
└── task/
 ├── Dockerfile # 任务容器镜像定义
 ├── requirements.txt # 运行时依赖
 └── src/friday_task/ # 任务执行器核心代码
```
### 约束条件
1. task 容器需要作为 Docker 容器独立运行
2. 需要支持 Claude Code 直接调用（命令行模式）
3. 保持与 server 的回调兼容性
4. session 管理需要跨容器持久化
## Goals / Non-Goals
### Goals
1. 将 task 迁移为独立的 Python 项目，有完整的 `pyproject.toml`
2. 支持两种运行模式：
 - 容器模式：被 server scheduler 启动
 - 命令行模式：直接被 Claude Code 或用户调用
3. 提供丰富的命令行参数支持
4. 独立的测试套件
### Non-Goals
1. 不改变 claude-agent-sdk 的使用方式
2. 不修改 server 的 API 接口
3. 不支持非 Docker 的分布式执行
## Decisions
### Decision 1: 项目结构
选择将 task 移动到根目录作为独立子项目：
```
friday-ai/
├── task/ # 独立的 task 项目
│ ├── pyproject.toml # 独立的项目配置
│ ├── Dockerfile
│ ├── README.md
│ ├── src/friday_task/
│ │ ├── __init__.py
│ │ ├── cli.py # 新增：命令行入口
│ │ ├── config.py # 增强：支持 CLI 参数
│ │ ├── runner.py
│ │ ├── claude_runner.py
│ │ ├── git_ops.py
│ │ └── callback.py # 增强：回调可选
│ └── tests/ # 独立的测试目录
│ ├── __init__.py
│ ├── test_cli.py
│ ├── test_config.py
│ └── test_claude_sdk_integration.py
├── server/
└── frontend/
```
**理由**：
- 清晰的项目边界
- 独立的依赖管理
- 可以单独构建和发布
### Decision 2: 命令行接口设计
使用 `click` 提供命令行支持：
```bash
# Plan 模式 - 直接在 branch 上分析，不创建新分支
python -m friday_task plan \
 --git-url git@github.com:org/repo.git \
 --branch main \
 --description "添加用户登录和认证功能..." \
 --api-key $ANTHROPIC_API_KEY
# Execute 模式 - 创建新分支并执行
python -m friday_task exec \
 --git-url git@github.com:org/repo.git \
 --branch main \
 --new-branch friday/feature-login \
 --description "添加用户登录和认证功能..." \
 --resume session-id-xxx
# 恢复已有会话
python -m friday_task resume \
 --session-id xxx \
 --mode exec
```
**参数设计**：
| 参数 | 环境变量 | 必需 | 说明 |
|------|----------|------|------|
| `--git-url` | FRIDAY_TASK_GIT_REPO_URL | 是 | Git 仓库地址 |
| `--branch` | FRIDAY_TASK_GIT_BRANCH | 否 | 基础分支，默认 main |
| `--new-branch` | FRIDAY_TASK_GIT_NEW_BRANCH | 否 | 功能分支名称（仅 exec 模式），默认自动生成 |
| `--description` | FRIDAY_TASK_TASK_DESCRIPTION | 是 | 需求描述（用于 Claude prompt 和 commit 消息） |
| `--api-key` | ANTHROPIC_API_KEY | 是* | Claude API Key |
| `--base-url` | ANTHROPIC_BASE_URL | 否 | Claude API Base URL |
| `--callback-url` | FRIDAY_TASK_CALLBACK_URL | 否 | 状态回调 URL |
| `--session-dir` | FRIDAY_TASK_SESSION_DIR | 否 | 会话存储目录 |
| `--resume` | - | 否 | 恢复的会话 ID |
| `--ssh-key` | FRIDAY_TASK_GIT_SSH_KEY | 否* | SSH 私钥内容 |
| `--access-token` | FRIDAY_TASK_GIT_ACCESS_TOKEN | 否* | Git 访问令牌 |
*注：ssh-key 或 access-token 至少需要一个用于 Git 认证
**模式差异**：
| 行为 | Plan 模式 | Execute 模式 |
|------|-----------|--------------|
| 创建新分支 | ❌ 不创建 | ✅ 创建 `--new-branch` |
| 修改代码 | ❌ 只读 | ✅ 可写 |
| 提交/推送 | ❌ 不提交 | ✅ 提交并推送 |
**关于 `--title` 参数**：
移除 `--title` 参数，原因：
- 原用于 commit 消息和 prompt，但可以从 `--description` 提取或让 Claude 生成
- 减少必填参数，简化命令行调用
- Commit 消息将使用 `--description` 的前50字符作为标题
**理由**：
- 支持环境变量和命令行参数双重配置
- 命令行参数优先于环境变量
- 与现有容器环境变量兼容
### Decision 3: 回调机制增强
修改 `CallbackClient` 使回调成为可选：
```python
class CallbackClient:
 def __init__(self, config: TaskConfig):
 self.enabled = bool(config.callback_url)
 if not self.enabled:
 logger.info("Callback disabled, running in standalone mode")
 async def report_status(self, status: str, ...) -> bool:
 if not self.enabled:
 logger.info("Status update (no callback)", status=status)
 return True
 # ... 原有逻辑
```
**理由**：
- 支持独立运行模式
- 保持与现有 server 集成的兼容性
- 便于本地测试和调试
### Decision 4: Session 管理
增强 session 管理支持跨调用恢复：
```python
# 会话存储结构
sessions/
├── {task_id}.json # 任务级会话
└── mapping.json # session_id -> task_id 映射
# mapping.json 格式
{
 "session-abc123": {
 "task_id": "task-001",
 "created_at": "2026-01-17T12:00:00Z",
 "last_output_preview": "..."
 }
}
```
**理由**：
- 支持 `--resume` 参数恢复任意会话
- 便于调试和重试
- 兼容现有的 session 持久化逻辑
### Decision 5: pyproject.toml 配置
```toml
[project]
name = "friday-task"
version = "0.1.0"
description = "AI-powered task executor for Friday development automation"
requires-python = ">=3.11"
dependencies = [
 "httpx>=0.27.0",
 "pydantic>=2.6.0",
 "pydantic-settings>=2.2.0",
 "gitpython>=3.1.42",
 "structlog>=24.1.0",
 "claude-agent-sdk>=0.1.0",
 "click>=8.0.0", # CLI 框架
]
[project.scripts]
friday-task = "friday_task.cli:main"
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
[tool.hatch.build.targets.wheel]
packages = ["src/friday_task"]
[dependency-groups]
dev = [
 "pytest>=9.0.2",
 "pytest-asyncio>=1.3.0",
 "ruff>=0.14.11",
]
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```
**理由**：
- 使用 `click` 作为 CLI 框架，比 argparse 更友好
- 提供 `friday-task` 命令行入口
- 独立的开发依赖
### Decision 6: Claude Agent SDK 权限模式
**关键问题**：claude-agent-sdk 在执行 Bash 命令时可能会询问用户确认，这会导致无人值守执行时中断。
**权限模式说明**：
| 模式 | 文件编辑 | Bash 命令 | 适用场景 |
|------|----------|-----------|----------|
| `default` | 需确认 | 需确认 | ❌ 会中断 |
| `plan` | 禁止 | 禁止 | ✅ Plan 模式 |
| `acceptEdits` | 自动接受 | 需确认 | ⚠️ 可能中断 |
| `bypassPermissions` | 自动接受 | 自动接受 | ✅ Execute 模式 |
**决策**：
- **Plan 模式**：使用 `permission_mode="plan"`（只读，不会触发任何确认）
- **Execute 模式**：使用 `permission_mode="bypassPermissions"`（跳过所有确认，包括 Bash 命令）
**当前代码问题**：
Execute 模式目前使用 `acceptEdits`，这会导致 Bash 命令（如 `wc`、`npm`、`pytest` 等）触发用户确认。需要改为 `bypassPermissions` 以支持无人值守执行。
```python
# 修改前
permission_mode="acceptEdits" # 文件编辑自动接受，但 Bash 需确认
# 修改后
permission_mode="bypassPermissions" # 完全跳过所有权限检查
```
**安全考虑**：
由于任务在隔离的 Docker 容器中执行，`bypassPermissions` 的风险可控。
## Risks / Trade-offs
### Risk 1: Docker 镜像构建路径变更
**风险**：现有的 CI/CD 和本地构建脚本需要更新
**缓解**：
- 更新 docker-compose.yml
- 更新相关文档
- 提供迁移指南
### Risk 2: 测试覆盖率
**风险**：测试迁移可能遗漏某些场景
**缓解**：
- 完整迁移现有测试
- 增加新的 CLI 测试
- CI 中独立运行 task 测试
## Migration Plan. **创建新目录结构**：在根目录创建 `task/` 目录
2. **迁移代码**：移动源代码和 Dockerfile
3. **创建 pyproject.toml**：配置独立项目
4. **实现 CLI**：添加命令行入口
5. **更新回调机制**：使回调可选
6. **迁移测试**：移动并更新测试代码
7. **更新构建配置**：docker-compose.yml、server/pyproject.toml
8. **删除旧目录**：清理 server/task/
9. **更新文档**：README、使用说明
## Open Questions
1. **是否需要发布到 PyPI？** - 初期可以仅作为本地项目使用，后续可考虑发布
2. **CLI 是否支持交互式输入？** - 初期仅支持参数传入，后续可增加交互式
