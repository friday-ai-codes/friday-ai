# Change: Add AI-Powered Development Automation System (Friday)
## Why
构建一个 AI 驱动的敏捷开发自动化系统，实现从飞书项目管理看板到代码落地的半自动化闭环。该系统将打通飞书 Project（Meego）→ Claude Code → Git 的工作流，显著提升开发效率。
核心痛点：
- 需求从看板到代码落地需要大量人工操作
- AI 代码生成缺乏与项目管理系统的集成
- 人工评审流程难以与 AI 执行无缝衔接
## What Changes
### 新增功能
- **项目管理模块**: 支持多项目配置，包括 Git 仓库 URL、平台类型、凭证管理
- **任务状态机**: 实现 PENDING → PLANNING → PLAN_REVIEW → EXECUTING → CODE_REVIEW → MERGED 的完整生命周期
- **飞书集成**: Webhook 接收、状态流转、评论反馈
- **任务容器化执行**: 每任务一容器，支持 Plan 和 Execute 两种模式
- **Git 操作封装**: 克隆、分支创建、提交、推送
- **Claude Code 集成**: 无头模式调用，会话持久化
### 技术栈
- **后端**: FastAPI + SQLModel + SQLite + aiosqlite
- **容器**: Docker + Docker Compose
- **AI**: Claude Code CLI
- **集成**: 飞书 Open API + GitHub/GitLab Webhook
## Impact
- **Affected specs**: 新增 `ai-dev-automation` 能力规范
- **Affected code**:
 - `src/friday/` - 主 API 服务
 - `task/` - 任务执行容器
 - `Dockerfile`, `docker-compose.yml` - 部署配置
- **Breaking changes**: 无（新项目）