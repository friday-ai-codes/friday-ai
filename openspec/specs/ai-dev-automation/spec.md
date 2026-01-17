# AI Development Automation Specification
## Purpose
本规范定义了 Friday AI 敏捷开发自动化系统的核心能力和行为要求。系统通过与飞书项目管理平台集成，自动化处理从需求分析到代码实现的开发流程，利用 Claude AI 进行代码分析、方案规划和代码生成。
## Requirements
### Requirement: Project Management
Project 配置 SHALL 移除 Git 相关字段（repo_url, git_platform, default_branch, claude_md_path），仅保留项目基本信息和飞书配置。
#### Scenario: Create project (Simplified)
- **WHEN** user creates a new project
- **THEN** only name and description are required
- **AND** Git configuration is handled via Repository association
### Requirement: Git Credential Management
Git 凭证 SHALL 关联到 Repository 而非 Project。
#### Scenario: Add SSH key to repository
- **WHEN** 用户为仓库添加 SSH 私钥
- **THEN** 系统将凭证与 Repository 关联
- **AND** 存储加密的私钥
### Requirement: Task State Machine
Task SHALL 明确关联一个 Repository 用于代码执行。
#### Scenario: Task creation with repository
- **WHEN** 创建新任务
- **AND** Project 关联了唯一 Repository
- **THEN** 系统自动将任务关联到该 Repository
#### Scenario: Task execution with repository context
- **WHEN** 任务开始执行 (Planning/Executing)
- **THEN** 系统使用 task.repository_id 获取 Git 配置和凭证
- **AND** 在容器中克隆对应的仓库
### Requirement: Task Execution Container
系统 SHALL 在隔离的 Docker 容器中执行每个任务，使用 claude-agent-sdk Python 包进行 AI 代码生成，从数据库获取 Claude 配置。
#### Scenario: 启动 Plan 模式任务
- **WHEN** 触发 mode="plan" 的任务执行
- **THEN** 系统从数据库获取 Claude 配置（项目级或系统级）
- **AND** 系统启动带有任务配置的容器
- **AND** 将仓库克隆到临时目录
- **AND** 使用 claude-agent-sdk 的 ClaudeSDKClient 分析代码库
- **AND** 生成实现方案
- **AND** 完成后任务状态转换为 PLAN_REVIEW
- **AND** 清理临时目录
#### Scenario: 启动 Execute 模式任务
- **WHEN** 方案审批后触发 mode="execute" 的任务执行
- **THEN** 系统从数据库获取 Claude 配置
- **AND** 系统启动带有会话恢复的容器
- **AND** 将仓库克隆到临时目录
- **AND** 使用 claude-agent-sdk 实现审批通过的方案
- **AND** 提交并推送变更到功能分支
- **AND** 完成后任务状态转换为 CODE_REVIEW
- **AND** 清理临时目录
#### Scenario: 容器资源隔离
- **WHEN** 任务容器启动时
- **THEN** 容器具有内存限制（2GB）
- **AND** CPU 限制（1 核）
- **AND** 隔离的网络环境
### Requirement: Feishu Integration
The system SHALL integrate with Feishu Project (Meego) for webhook events and status updates.
#### Scenario: Webhook challenge verification
- **WHEN** Feishu sends a URL verification challenge
- **THEN** the system returns the challenge token
- **AND** confirms webhook registration
#### Scenario: Work item status change event
- **WHEN** Feishu sends a work_item_status_change event
- **THEN** the system parses the event payload
- **AND** triggers appropriate task actions based on the new status
#### Scenario: Comment feedback processing
- **WHEN** a comment is added to a Feishu work item
- **THEN** the system captures the feedback
- **AND** includes it in the task context for Claude
### Requirement: Git Operations
系统 SHALL 执行 Git 操作，包括克隆、分支创建、提交和推送，使用动态认证和临时工作目录。
#### Scenario: 使用 SSH 密钥克隆仓库
- **WHEN** 使用 SSH 认证开始 Git 操作
- **THEN** 系统从数据库读取加密的 SSH 密钥
- **AND** 解密后写入临时文件
- **AND** 配置 SSH_COMMAND 使用该私钥
- **AND** 将仓库克隆到临时工作目录
- **AND** 操作完成后删除临时密钥文件
#### Scenario: 创建功能分支
- **WHEN** 任务执行开始
- **THEN** 系统创建名为 `friday/task-{task_id}` 的分支
- **AND** 切换到新分支
#### Scenario: 提交并推送变更
- **WHEN** Claude Code 完成代码修改
- **THEN** 系统暂存所有变更
- **AND** 使用包含任务 ID 的描述性消息进行提交
- **AND** 推送到远程仓库
#### Scenario: 任务完成后清理
- **WHEN** 任务执行完成或失败
- **THEN** 系统删除临时工作目录
- **AND** 清理所有临时凭证文件
### Requirement: Claude Code Integration
系统 SHALL 使用 claude-agent-sdk Python 包进行 AI 代码生成，支持会话持久化和多种执行模式。
#### Scenario: Plan mode execution
- **WHEN** Claude Code runs in plan mode
- **THEN** 系统使用 ClaudeSDKClient 创建会话
- **AND** 设置 allowed_tools 为只读工具：Read, Glob, Grep, LS
- **AND** 生成实现方案但不修改代码
- **AND** 保存 session_id 用于后续恢复
#### Scenario: Execute mode with session resume
- **WHEN** Claude Code runs in execute mode with a session ID
- **THEN** 系统使用 resume 参数恢复之前的会话上下文
- **AND** Claude 继续执行审批通过的方案
- **AND** 使用 Write 和 Edit 工具修改代码
#### Scenario: Execution timeout handling
- **WHEN** Claude Code 执行超过配置的超时时间
- **THEN** 系统终止 SDK 客户端
- **AND** 报告超时错误到回调端点
### Requirement: API Callback Mechanism
The system SHALL provide callback endpoints for task containers to report status updates.
#### Scenario: Report plan completion
- **WHEN** plan generation completes successfully
- **THEN** the container calls POST /api/tasks/{id}/status with status="plan_ready"
- **AND** includes the generated plan in details
#### Scenario: Report execution completion
- **WHEN** code execution completes successfully
- **THEN** the container calls POST /api/tasks/{id}/status with status="execution_complete"
- **AND** includes branch_name, commit_sha, and diff_summary
#### Scenario: Report error
- **WHEN** task execution fails
- **THEN** the container calls POST /api/tasks/{id}/status with status="error"
- **AND** includes error message and phase information
### Requirement: Repository Management
系统 SHALL 提供独立的 Git 仓库管理能力，支持创建、更新、查询和删除仓库配置。
#### Scenario: Create repository
- **WHEN** 用户调用创建仓库 API
- **AND** 提供 name, git_url, git_platform, default_branch
- **THEN** 系统创建新的 Repository 记录
#### Scenario: Update repository
- **WHEN** 用户调用更新仓库 API
- **THEN** 系统更新仓库配置信息
### Requirement: Project-Repository Association
系统 SHALL 支持建立 Project（飞书项目）与 Repository（Git 仓库）的多对多关联。
#### Scenario: Link repository to project
- **WHEN** 用户调用关联 API
- **AND** 指定 project_id 和 repository_id
- **THEN** 系统创建关联记录
- **AND** 该仓库对该项目可见
#### Scenario: Unlink repository from project
- **WHEN** 用户调用解除关联 API
- **THEN** 系统删除关联记录
- **AND** 历史任务保留原有 repository_id 引用
### Requirement: Database Migration Management
系统 SHALL 使用 Alembic 管理数据库 Schema 迁移，支持自动迁移和版本回滚。
#### Scenario: 服务启动时自动迁移
- **WHEN** 后端服务启动
- **THEN** 系统检测数据库迁移状态
- **AND** 自动执行 `alembic upgrade head` 升级到最新版本
- **AND** 日志记录迁移执行结果
#### Scenario: 现有数据库首次引入迁移
- **WHEN** 检测到数据库存在但无 alembic_version 表
- **THEN** 系统自动执行 `alembic stamp head` 标记当前版本
- **AND** 后续迁移正常执行增量变更
#### Scenario: AI Agent 完成 Model 变更
- **WHEN** AI Agent 修改了 `server/src/friday/models/` 中的模型定义
- **THEN** Agent **必须** 执行 `uv run alembic revision --autogenerate -m "描述变更"`
- **AND** 检查生成的迁移脚本是否正确
- **AND** 确保迁移脚本包含在代码提交中
#### Scenario: Docker 容器部署
- **WHEN** 使用 Docker 部署新版本后端服务
- **THEN** 容器启动时自动执行数据库迁移
- **AND** 无需手动执行迁移命令
- **AND** 迁移失败时服务启动失败并记录错误
#### Scenario: 迁移回滚
- **WHEN** 需要回滚数据库变更
- **THEN** 执行 `uv run alembic downgrade -1` 回滚一个版本
- **AND** 系统恢复到上一个 Schema 版本
### Requirement: System Settings Management
系统 SHALL 提供系统级配置管理能力，支持通过 API 动态管理全局配置项。
#### Scenario: 获取所有系统设置
- **WHEN** 调用 `GET /api/v1/settings`
- **THEN** 返回所有系统配置项列表
- **AND** 敏感配置值不直接返回，仅返回是否已配置
#### Scenario: 更新系统设置
- **WHEN** 调用 `PUT /api/v1/settings/{key}` 并提供新值
- **THEN** 系统更新对应配置
- **AND** 如果配置项标记为加密，则加密存储
#### Scenario: 删除系统设置
- **WHEN** 调用 `DELETE /api/v1/settings/{key}`
- **THEN** 系统删除对应配置项
- **AND** 相关功能回退到环境变量默认值
---
### Requirement: Claude Code Configuration
系统 SHALL 支持分层的 Claude Code 配置，包括 API Key 和 Base URL，按优先级获取配置。
#### Scenario: 系统级 Claude 配置
- **WHEN** 管理员配置系统级 `anthropic_api_key` 和 `anthropic_base_url`
- **THEN** 所有未配置项目级覆盖的项目使用此配置
- **AND** API Key 加密存储
#### Scenario: 项目级 Claude 配置覆盖
- **WHEN** 项目配置了 `claude_api_key` 和 `claude_base_url`
- **THEN** 该项目的任务使用项目专属配置
- **AND** 优先于系统级配置
#### Scenario: 配置优先级获取
- **WHEN** 任务容器启动需要获取 Claude 配置
- **THEN** 按以下优先级获取配置：
 1. 项目级配置（如已配置）
 2. 系统级配置（如已配置）
 3. 环境变量（ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL）
#### Scenario: 容器环境变量传递
- **WHEN** TaskScheduler 启动任务容器
- **THEN** 将解析后的 Claude 配置通过环境变量传递给容器
- **AND** 包含 ANTHROPIC_API_KEY 和 ANTHROPIC_BASE_URL
---
### Requirement: Claude Agent SDK Integration
Task 容器 SHALL 使用 `claude-agent-sdk` Python 包替代 Claude Code CLI，直接在 Python 中调用 Claude Code 功能。
#### Scenario: SDK 依赖安装
- **WHEN** 构建 Task 容器镜像
- **THEN** 使用 `pip install claude-agent-sdk` 安装 SDK
- **AND** 不依赖 Node.js 或 Claude CLI
#### Scenario: Plan 模式执行
- **WHEN** 任务以 plan 模式运行
- **THEN** 使用 ClaudeSDKClient 创建会话
- **AND** 设置 `permission_mode="plan"` 禁止代码修改
- **AND** 仅允许只读工具：Read, Glob, Grep, LS
- **AND** 生成实现方案并返回
#### Scenario: Execute 模式执行
- **WHEN** 任务以 execute 模式运行
- **THEN** 使用 ClaudeSDKClient 创建会话
- **AND** 设置 `permission_mode="acceptEdits"` 自动接受编辑
- **AND** 允许所有编辑工具：Read, Write, Edit, Bash, Glob, Grep, LS
- **AND** 如有之前的 session_id，使用 `resume` 参数恢复会话
#### Scenario: 消息处理
- **WHEN** SDK 返回消息流
- **THEN** 处理 AssistantMessage 提取文本内容
- **AND** 处理 ResultMessage 获取执行结果和成本信息
- **AND** 保存 session_id 用于后续恢复
#### Scenario: 错误处理
- **WHEN** SDK 抛出 CLINotFoundError
- **THEN** 报告 Claude Code 未安装错误
- **WHEN** SDK 抛出 ProcessError
- **THEN** 报告进程执行错误和退出码
