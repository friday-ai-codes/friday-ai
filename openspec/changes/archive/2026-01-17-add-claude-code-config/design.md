# 技术设计：系统级 Claude Code 配置 & 迁移到 Python SDK
## Context
当前 Friday 系统的 Claude Code 实现存在以下限制：
- API Key 仅通过环境变量 `ANTHROPIC_API_KEY` 配置
- 无法配置 API 代理地址（对国内用户尤为重要）
- 所有项目共享同一配置，无法隔离
- 依赖 Claude Code CLI，需要安装 Node.js 或 bash 脚本
本次变更将：
1. 实现分层配置机制：**项目级配置 > 系统级配置 > 环境变量默认值**
2. 迁移到 `claude-agent-sdk` Python SDK，简化依赖和实现
## Goals / Non-Goals
**Goals:**
- 使用 `claude-agent-sdk` 替代 Claude Code CLI
- 支持通过 Web UI 配置系统级 Claude Code 设置
- 支持项目级覆盖系统配置
- API Key 加密存储
- 配置变更无需重启服务
- 简化 Docker 镜像（移除 Node.js 依赖）
**Non-Goals:**
- 用户认证/授权（当前系统无用户体系）
- 配置版本历史
- 配置审计日志
- 自定义 MCP 工具（后续可扩展）
## Decisions
### Decision 1: 使用 claude-agent-sdk 替代 CLI
**选择**: 使用 `claude-agent-sdk` Python 包
**安装**:
```bash
pip install claude-agent-sdk
```
**优势**:
- 纯 Python 实现，无需 Node.js
- 支持会话管理（ClaudeSDKClient）
- 支持钩子（hooks）拦截工具执行
- 支持自定义权限控制
- 更好的错误处理
- 镜像更小、构建更快
**claude_runner.py 重写示例**:
```python
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, AssistantMessage, TextBlock, ResultMessage
class ClaudeRunner:
 def __init__(self, config: TaskConfig, workspace: Path):
 self.config = config
 self.workspace = workspace
 async def run_plan_mode(self) -> dict:
 """使用 SDK 运行 plan 模式"""
 options = ClaudeAgentOptions(
 # 仅允许只读工具
 allowed_tools=["Read", "Glob", "Grep", "LS"],
 permission_mode="plan", # 规划模式，不执行
 cwd=str(self.workspace),
 system_prompt={
 "type": "preset",
 "preset": "claude_code",
 "append": self._build_plan_prompt
 },
 # 加载项目设置（developer-notes.md）
 setting_sources=["project"],
 )
 async with ClaudeSDKClient(options=options) as client:
 await client.query(self._build_task_prompt)
 output_parts =
 async for message in client.receive_response:
 if isinstance(message, AssistantMessage):
 for block in message.content:
 if isinstance(block, TextBlock):
 output_parts.append(block.text)
 elif isinstance(message, ResultMessage):
 return {
 "success": not message.is_error,
 "output": "\n".join(output_parts),
 "session_id": message.session_id,
 "cost": message.total_cost_usd,
 }
 return {"success": False, "error": "No result received"}
 async def run_execute_mode(self, plan: str | None = None) -> dict:
 """使用 SDK 运行 execute 模式"""
 options = ClaudeAgentOptions(
 # 允许所有编辑工具
 allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep", "LS"],
 permission_mode="acceptEdits", # 自动接受编辑
 cwd=str(self.workspace),
 system_prompt={
 "type": "preset",
 "preset": "claude_code",
 "append": self._build_execute_prompt(plan)
 },
 setting_sources=["project"],
 # 恢复会话（如果有）
 resume=self._get_session_id if self._has_session else None,
 )
 async with ClaudeSDKClient(options=options) as client:
 await client.query(self._build_task_prompt)
 output_parts =
 async for message in client.receive_response:
 if isinstance(message, AssistantMessage):
 for block in message.content:
 if isinstance(block, TextBlock):
 output_parts.append(block.text)
 elif isinstance(message, ResultMessage):
 self._save_session(message.session_id)
 return {
 "success": not message.is_error,
 "output": "\n".join(output_parts),
 "session_id": message.session_id,
 "cost": message.total_cost_usd,
 }
 return {"success": False, "error": "No result received"}
```
### Decision 2: 使用 key-value 模式存储系统配置
**选择**: 创建 `system_settings` 表，使用 key-value 模式存储
**原因**:
- 灵活扩展，未来可添加更多系统配置项
- 无需为每个配置项修改表结构
- 便于 API 设计
**表结构**:
```sql
CREATE TABLE system_settings (
 key VARCHAR PRIMARY KEY, -- 配置键，如 anthropic_api_key
 value TEXT, -- 配置值（敏感值加密存储）
 is_encrypted BOOLEAN DEFAULT FALSE,
 description TEXT,
 updated_at TIMESTAMP
);
```
### Decision 3: 项目级配置扩展 Project 模型
**选择**: 在 `projects` 表中添加 Claude 配置字段
**字段**:
```python
claude_api_key_encrypted: Optional[str] # 加密存储
claude_base_url: Optional[str] # API 代理地址
```
### Decision 4: 配置优先级获取逻辑
**选择**: 在 TaskScheduler 中实现配置合并逻辑
```python
async def get_claude_config(project_id: str, db: AsyncSession) -> dict:
 # 1. 尝试从项目获取
 project = await get_project(db, project_id)
 api_key = decrypt(project.claude_api_key_encrypted) if project.claude_api_key_encrypted else None
 base_url = project.claude_base_url
 # 2. 回退到系统配置
 if not api_key:
 api_key = await get_system_setting(db, "anthropic_api_key")
 if not base_url:
 base_url = await get_system_setting(db, "anthropic_base_url")
 # 3. 回退到环境变量
 if not api_key:
 api_key = os.environ.get("ANTHROPIC_API_KEY")
 if not base_url:
 base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
 return {"api_key": api_key, "base_url": base_url}
```
### Decision 5: Task 容器环境变量传递
**选择**: 添加 `ANTHROPIC_API_KEY` 和 `ANTHROPIC_BASE_URL` 环境变量到容器
**修改 `scheduler.py`**:
```python
env = {
 ...
 # Claude SDK 直接读取这些环境变量
 "ANTHROPIC_API_KEY": claude_config["api_key"],
 "ANTHROPIC_BASE_URL": claude_config["base_url"],
}
```
### Decision 6: 简化 Dockerfile
**修改 Dockerfile**:
```dockerfile
FROM python:3.14-slim
# 系统依赖
RUN apt-get update && apt-get install -y \
 git \
 openssh-client \
 curl \
 && rm -rf /var/lib/apt/lists/*
# 不再需要 Node.js 和 Claude CLI
# RUN curl -fsSL https://claude.ai/install.sh | bash
# Python 依赖
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
# requirements.txt 包含:
# claude-agent-sdk
# structlog
# httpx
# gitpython
COPY src/ ./src/
# Git 配置
RUN git config --global user.email "ai-agent@friday.dev" \
 && git config --global user.name "Friday AI Agent" \
 && git config --global --add safe.directory "*"
# SSH 配置
RUN mkdir -p /root/.ssh \
 && chmod 700 /root/.ssh \
 && echo "Host *\n\tStrictHostKeyChecking no\n\tUserKnownHostsFile=/dev/null" > /root/.ssh/config
RUN mkdir -p /app/workspace /app/sessions
ENTRYPOINT ["python", "-m", "src.runner"]
```
## API 设计
### 系统设置 API
```
GET /api/v1/settings # 获取所有系统设置
GET /api/v1/settings/{key} # 获取单个设置
PUT /api/v1/settings/{key} # 更新设置
DELETE /api/v1/settings/{key} # 删除设置
# 请求/响应示例
PUT /api/v1/settings/anthropic_api_key
{
 "value": "sk-ant-xxx",
 "is_encrypted": true
}
```
### 项目 Claude 配置 API
```
GET /api/v1/projects/{id}/claude-config # 获取项目 Claude 配置
PUT /api/v1/projects/{id}/claude-config # 更新项目 Claude 配置
# 请求示例
PUT /api/v1/projects/{id}/claude-config
{
 "api_key": "sk-ant-xxx", # 可选，覆盖系统配置
 "base_url": "https://proxy.example.com" # 可选
}
# 响应示例
{
 "has_api_key": true, # 不返回实际 key
 "base_url": "https://proxy.example.com",
 "source": "project" # project | system | environment
}
```
## 前端设计
### 系统设置页面
路由: `/settings`
布局:
```
+----------------------------------+
| 系统设置 |
+----------------------------------+
| Claude Code 配置 |
| ┌────────────────────────────┐ |
| │ API Key: [••••••••••] [👁] │ |
| │ Base URL: [https://...] │ |
| │ [保存] │ |
| └────────────────────────────┘ |
+----------------------------------+
```
### 项目编辑页新增 Tab
在项目详情页增加 "Claude 配置" Tab：
```
项目详情
[基本信息] [飞书配置] [Claude 配置] [关联仓库]
Claude 配置
┌────────────────────────────────────┐
│ ☐ 使用项目专属配置（覆盖系统配置） │
│ │
│ API Key: [••••••••••] │
│ Base URL: [https://...] │
│ │
│ 当前生效配置来源: 系统配置 │
└────────────────────────────────────┘
```
## SDK 功能扩展（未来）
`claude-agent-sdk` 支持以下高级功能，可在后续版本中利用：
1. **钩子（Hooks）**: 拦截工具执行，实现自定义权限控制
2. **自定义工具（MCP）**: 添加项目特定的工具
3. **会话持久化**: 跨多次执行保持对话上下文
4. **中断支持**: 支持中途停止任务执行
## 数据迁移
无需数据迁移，新增表和字段均为可选配置。
## Risks / Trade-offs
| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 配置加密密钥丢失 | 无法解密已存储的 API Key | 文档说明备份 FRIDAY_ENCRYPTION_KEY |
| 前端暴露配置接口 | 非授权访问可修改配置 | 当前系统无认证，标记为已知限制 |
| 配置变更影响运行中任务 | 任务执行中配置生效 | 容器启动时读取配置，运行中不受影响 |
| SDK 版本兼容性 | SDK 更新可能引入不兼容变更 | 锁定 SDK 版本，定期更新测试 |
## Open Questions
1. 是否需要支持多个 API Key 轮询？（当前 scope 外）
2. 是否需要配置测试功能验证 API Key 有效性？
3. 是否需要支持自定义 MCP 工具？（后续版本）
