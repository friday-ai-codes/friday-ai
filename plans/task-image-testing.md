# Task 镜像测试命令集
本文档提供测试 Friday Task 容器镜像的命令集，用于验证镜像是否能正确拉取工作项、生成 plan 和执行代码生成。
> **注意**：本文档已更新为使用 `claude-agent-sdk` Python SDK，不再依赖 Claude Code CLI。
## 前置条件
1. 已构建 task 镜像：`docker build -t friday-task:latest ./server/task`
2. 已启动 friday-server 服务
3. 已配置 `ANTHROPIC_API_KEY` 环境变量
4. 已有测试用的 Git 仓库和 SSH 密钥
## 1. 镜像构建测试
```bash
# 构建 task 镜像
cd server/task
docker build -t friday-task:latest .
# 验证镜像
docker images friday-task:latest
# 验证 Python SDK 安装
docker run --rm friday-task:latest python -c "from claude_agent_sdk import query, ClaudeSDKClient; print('SDK OK')"
# 验证所有依赖
docker run --rm friday-task:latest python -c "
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
from claude_agent_sdk import AssistantMessage, TextBlock, ResultMessage
print('All imports OK')
"
```
## 2. 环境变量准备
```bash
# 设置测试环境变量
export FRIDAY_TASK_TASK_ID="test-$(date +%s)"
export FRIDAY_TASK_PROJECT_ID="test-project"
export FRIDAY_TASK_TASK_TITLE="测试任务：添加健康检查端点"
export FRIDAY_TASK_TASK_DESCRIPTION="为 API 服务添加 /health 健康检查端点，返回服务状态"
export FRIDAY_TASK_TASK_MODE="plan" # 或 "execute"
# Git 配置
export FRIDAY_TASK_GIT_REPO_URL="git@github.com:your-org/your-repo.git"
export FRIDAY_TASK_GIT_BRANCH="main"
export FRIDAY_TASK_GIT_AUTH_TYPE="ssh"
export FRIDAY_TASK_GIT_SSH_KEY="$(cat ~/.ssh/id_rsa)" # 或使用测试密钥
# Claude 配置（SDK 直接读取这些环境变量）
export ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY"
export ANTHROPIC_BASE_URL="https://api.anthropic.com" # 或自定义代理
# Callback 配置（本地测试可使用 mock）
export FRIDAY_TASK_CALLBACK_URL="http://host.docker.internal:8000/api/v1"
export FRIDAY_TASK_CALLBACK_TOKEN=""
```
## 3. Plan 模式测试
```bash
# 运行 plan 模式
docker run --rm \
 --name friday-task-test \
 --network host \
 -e FRIDAY_TASK_TASK_ID \
 -e FRIDAY_TASK_PROJECT_ID \
 -e FRIDAY_TASK_TASK_TITLE \
 -e FRIDAY_TASK_TASK_DESCRIPTION \
 -e FRIDAY_TASK_TASK_MODE=plan \
 -e FRIDAY_TASK_GIT_REPO_URL \
 -e FRIDAY_TASK_GIT_BRANCH \
 -e FRIDAY_TASK_GIT_AUTH_TYPE \
 -e FRIDAY_TASK_GIT_SSH_KEY \
 -e ANTHROPIC_API_KEY \
 -e ANTHROPIC_BASE_URL \
 -e FRIDAY_TASK_CALLBACK_URL \
 -e FRIDAY_TASK_CALLBACK_TOKEN \
 friday-task:latest
```
## 4. Execute 模式测试
```bash
# 运行 execute 模式（需要先完成 plan 并保存 session）
docker run --rm \
 --name friday-task-test \
 --network host \
 -v friday-sessions-test:/app/sessions \
 -e FRIDAY_TASK_TASK_ID \
 -e FRIDAY_TASK_PROJECT_ID \
 -e FRIDAY_TASK_TASK_TITLE \
 -e FRIDAY_TASK_TASK_DESCRIPTION \
 -e FRIDAY_TASK_TASK_MODE=execute \
 -e FRIDAY_TASK_GIT_REPO_URL \
 -e FRIDAY_TASK_GIT_BRANCH \
 -e FRIDAY_TASK_GIT_AUTH_TYPE \
 -e FRIDAY_TASK_GIT_SSH_KEY \
 -e ANTHROPIC_API_KEY \
 -e ANTHROPIC_BASE_URL \
 -e FRIDAY_TASK_CALLBACK_URL \
 -e FRIDAY_TASK_CALLBACK_TOKEN \
 friday-task:latest
```
## 5. 交互式调试
```bash
# 进入容器进行交互式调试
docker run -it --rm \
 --entrypoint /bin/bash \
 --network host \
 -e FRIDAY_TASK_TASK_ID \
 -e FRIDAY_TASK_PROJECT_ID \
 -e FRIDAY_TASK_TASK_TITLE \
 -e FRIDAY_TASK_TASK_DESCRIPTION \
 -e FRIDAY_TASK_TASK_MODE=plan \
 -e FRIDAY_TASK_GIT_REPO_URL \
 -e FRIDAY_TASK_GIT_BRANCH \
 -e FRIDAY_TASK_GIT_AUTH_TYPE \
 -e FRIDAY_TASK_GIT_SSH_KEY \
 -e ANTHROPIC_API_KEY \
 -e ANTHROPIC_BASE_URL \
 -e FRIDAY_TASK_CALLBACK_URL \
 -e FRIDAY_TASK_CALLBACK_TOKEN \
 friday-task:latest
# 在容器内执行
python -c "from claude_agent_sdk import query; print('SDK OK')" # 验证 SDK
python -m src.runner # 手动运行 runner
```
## 6. SDK 功能单独测试
```bash
# 测试 SDK 基本功能（需要有效的 API Key）
docker run --rm \
 -e ANTHROPIC_API_KEY \
 friday-task:latest \
 python -c "
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions
async def test:
 options = ClaudeAgentOptions(
 allowed_tools=, # 不使用工具
 max_turns=1
 )
 async for msg in query(prompt='Say hello in one word', options=options):
 print(msg)
asyncio.run(test)
"
# 测试 ClaudeSDKClient 会话功能
docker run --rm \
 -e ANTHROPIC_API_KEY \
 friday-task:latest \
 python -c "
import asyncio
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, AssistantMessage, TextBlock
async def test:
 options = ClaudeAgentOptions(max_turns=1)
 async with ClaudeSDKClient(options=options) as client:
 await client.query('What is 2+2?')
 async for msg in client.receive_response:
 if isinstance(msg, AssistantMessage):
 for block in msg.content:
 if isinstance(block, TextBlock):
 print(f'Answer: {block.text}')
asyncio.run(test)
"
```
## 7. 集成测试脚本
```bash
#!/bin/bash
# test-task-image.sh - 完整的 Task 镜像测试脚本
set -e
echo "=== Friday Task Image Test (SDK Version) ==="
# 1. 构建镜像
echo "[1/5] Building task image..."
docker build -t friday-task:latest ./server/task
# 2. 验证 Python 环境
echo "[2/5] Verifying Python environment..."
docker run --rm friday-task:latest python --version
# 3. 验证 SDK 安装
echo "[3/5] Verifying claude-agent-sdk..."
docker run --rm friday-task:latest python -c "
from claude_agent_sdk import query, ClaudeSDKClient, ClaudeAgentOptions
from claude_agent_sdk import AssistantMessage, TextBlock, ResultMessage
print('SDK imports OK')
"
# 4. 验证 Git 操作
echo "[4/5] Verifying Git operations..."
docker run --rm friday-task:latest git --version
# 5. 验证配置模块
echo "[5/5] Testing config module..."
docker run --rm \
 -e FRIDAY_TASK_TASK_ID=test-dry-run \
 -e FRIDAY_TASK_PROJECT_ID=test \
 -e FRIDAY_TASK_TASK_TITLE="Dry Run Test" \
 -e FRIDAY_TASK_TASK_DESCRIPTION="Test description" \
 -e FRIDAY_TASK_TASK_MODE=plan \
 -e FRIDAY_TASK_GIT_REPO_URL="https://github.com/test/test.git" \
 -e FRIDAY_TASK_GIT_BRANCH=main \
 -e FRIDAY_TASK_CALLBACK_URL="http://localhost:8000/api/v1" \
 friday-task:latest \
 python -c "
from src.config import TaskConfig
c = TaskConfig
print(f'Task: {c.task_id}, Mode: {c.task_mode}')
print('Config OK')
"
echo "=== All tests passed ==="
```
## 8. 使用 docker-compose 进行完整测试
```bash
# 启动完整环境
docker-compose up -d
# 等待服务就绪
sleep 10
# 通过 API 创建任务并执行
curl -X POST http://localhost:10241/api/v1/tasks \
 -H "Content-Type: application/json" \
 -d '{
 "project_id": "your-project-id",
 "title": "测试任务",
 "description": "添加健康检查端点"
 }'
# 执行任务（替换 task-id）
curl -X POST http://localhost:10241/api/v1/tasks/{task-id}/execute \
 -H "Content-Type: application/json" \
 -d '{"mode": "plan"}'
# 查看任务日志
curl http://localhost:10241/api/v1/tasks/{task-id}/logs
# 查看容器状态
docker ps -a | grep friday-task
```
## 常见问题排查
### SDK 导入失败
```bash
# 检查 SDK 是否安装
docker run --rm friday-task:latest pip list | grep claude-agent-sdk
# 重新安装
docker run --rm friday-task:latest pip install claude-agent-sdk
```
### API Key 无效
```bash
# 验证 API Key 格式
echo $ANTHROPIC_API_KEY | head -c 10
# 测试 API 连接
docker run --rm \
 -e ANTHROPIC_API_KEY \
 friday-task:latest \
 python -c "
import asyncio
from claude_agent_sdk import query
async def test:
 try:
 async for msg in query(prompt='hi', options=None):
 print('API connection OK')
 break
 except Exception as e:
 print(f'API error: {e}')
asyncio.run(test)
"
```
### Git 克隆失败
```bash
# 检查 SSH 密钥
docker run --rm \
 -e FRIDAY_TASK_GIT_SSH_KEY="$(cat ~/.ssh/id_rsa)" \
 friday-task:latest \
 bash -c 'echo "$FRIDAY_TASK_GIT_SSH_KEY" > /tmp/key && chmod 600 /tmp/key && ssh -i /tmp/key -T git@github.com'
```
### Callback 连接失败
```bash
# 使用 host network 模式
docker run --rm --network host friday-task:latest curl http://localhost:8000/health
# 或使用 Docker 网络名
docker run --rm --network friday-ai_friday-network friday-task:latest curl http://friday-server:8000/health
```
## SDK vs CLI 对比
| 功能 | CLI 方式 | SDK 方式 |
|------|----------|----------|
| 安装 | Node.js + CLI | pip install |
| 镜像大小 | 较大 | 较小 |
| 会话管理 | 文件 + resume 参数 | ClaudeSDKClient |
| 错误处理 | 解析 JSON 输出 | Python 异常 |
| 自定义工具 | 不支持 | 支持 MCP |
| 钩子 | 不支持 | 支持 Hooks |
