# Change: 添加系统级 Claude Code 配置 & 迁移到 Python SDK
## Why
目前 Claude Code 的实现存在以下问题：
1. **API 配置硬编码**：API Key、Base URL 通过环境变量硬编码，无法动态配置
2. **不支持代理**：国内用户无法配置 Anthropic API 代理地址
3. **无项目级隔离**：所有项目必须使用相同的 API 配置
4. **前端无法管理**：管理员无法通过 Web UI 管理配置
5. **CLI 依赖复杂**：当前使用 Claude Code CLI，需要安装 Node.js 或 bash 脚本
## What Changes
### 1. 迁移到 claude-agent-sdk（Python SDK）
- 使用 `claude-agent-sdk` Python 包替代 Claude Code CLI
- 直接在 Python 中调用，无需 CLI 和 Node.js
- 支持更丰富的功能：会话管理、钩子、自定义工具等
- 简化 Docker 镜像构建
### 2. 系统级配置（System Settings）
- 新增 `SystemSettings` 模型存储全局配置
- 支持配置 `anthropic_api_key` 和 `anthropic_base_url`
- API Key 加密存储
- 前端提供系统设置页面
### 3. 项目级配置覆盖
- Project 模型新增 `claude_api_key_encrypted` 和 `claude_base_url` 字段
- 项目配置优先于系统配置
- 前端项目编辑页增加 Claude 配置选项
### 4. Task 容器配置传递
- TaskScheduler 从数据库读取配置而非环境变量
- 按优先级获取配置：项目配置 > 系统配置 > 环境变量
### 5. Task 镜像简化
- 移除 Claude Code CLI 安装
- 仅需 `pip install claude-agent-sdk`
- 镜像更小、构建更快
## Impact
- **Affected specs**:
 - `ai-dev-automation` - 新增系统配置管理，迁移到 SDK
 - `frontend-architecture` - 新增系统设置页面
- **Affected code**:
 - `server/src/friday/models/` - 新增 SystemSettings 模型，修改 Project 模型
 - `server/src/friday/routes/` - 新增 settings 路由
 - `server/src/friday/services/scheduler.py` - 修改配置读取逻辑
 - `server/task/Dockerfile` - 移除 CLI 安装，使用 pip 安装 SDK
 - `server/task/src/claude_runner.py` - 使用 claude-agent-sdk 重写
 - `server/task/requirements.txt` - 添加 claude-agent-sdk 依赖
 - `web/src/` - 新增系统设置页面
## Non-Goals
- 不包含用户认证/授权系统（系统设置对所有用户可见）
- 不包含多租户支持
- 不包含自定义 MCP 工具（后续可扩展）
