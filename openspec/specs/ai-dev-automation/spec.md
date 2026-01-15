# AI Development Automation Specification
## Purpose
本规范定义了 Friday AI 敏捷开发自动化系统的核心能力和行为要求。系统通过与飞书项目管理平台集成，自动化处理从需求分析到代码实现的开发流程，利用 Claude AI 进行代码分析、方案规划和代码生成。
## Requirements
### Requirement: Project Management
The system SHALL provide project configuration management, including Git repository URL, platform type (GitHub/GitLab/Gitea/Bitbucket), default branch, and developer-notes.md path.
#### Scenario: Create project with Git configuration
- **WHEN** user creates a new project with name, repo_url, and git_platform
- **THEN** the system creates a project record with unique ID
- **AND** the project is available for task assignment
#### Scenario: Update project configuration
- **WHEN** user updates project settings (default_branch, claude_md_path)
- **THEN** the system persists the changes
- **AND** future tasks use the updated configuration
### Requirement: Git Credential Management
系统 SHALL 支持将 Git 凭证加密存储到数据库中，包括 SSH 私钥和访问令牌，实现项目级别的隔离。
#### Scenario: 添加 SSH 密钥凭证
- **WHEN** 用户为项目添加 SSH 私钥
- **THEN** 系统使用 Fernet 对称加密对私钥进行加密
- **AND** 将加密后的值存储到数据库的 `ssh_key_encrypted` 字段
- **AND** 凭证与项目关联
#### Scenario: 添加访问令牌凭证
- **WHEN** 用户为项目添加访问令牌
- **THEN** 系统加密令牌
- **AND** 存储用于 HTTPS Git 认证
#### Scenario: 任务执行时解密凭证
- **WHEN** 任务容器需要 Git 认证
- **THEN** 系统从数据库读取加密的凭证
- **AND** 解密凭证内容
- **AND** 将解密后的凭证注入容器环境
### Requirement: Task State Machine
The system SHALL implement a task state machine with the following states: PENDING, PLANNING, PLAN_REVIEW, EXECUTING, CODE_REVIEW, MERGED, FAILED.
#### Scenario: Task creation
- **WHEN** a new task is created with work_item_id, feature_id, and title
- **THEN** the task starts in PENDING state
- **AND** is associated with a project
#### Scenario: Valid state transition
- **WHEN** a task transitions from PENDING to PLANNING
- **THEN** the system updates the status
- **AND** records the plan_started_at timestamp
#### Scenario: Invalid state transition
- **WHEN** a task attempts an invalid transition (e.g., PENDING → EXECUTING)
- **THEN** the system rejects the transition
- **AND** returns an error with allowed transitions
#### Scenario: Task failure handling
- **WHEN** a task transitions to FAILED state
- **THEN** the system increments retry_count
- **AND** allows reset to PENDING for retry
### Requirement: Task Execution Container
系统 SHALL 在隔离的 Docker 容器中执行每个任务，使用临时目录进行仓库操作，支持 Plan 和 Execute 模式。
#### Scenario: 启动 Plan 模式任务
- **WHEN** 触发 mode="plan" 的任务执行
- **THEN** 系统启动带有任务配置的容器
- **AND** 将仓库克隆到临时目录
- **AND** Claude Code 分析代码库
- **AND** 生成实现方案
- **AND** 完成后任务状态转换为 PLAN_REVIEW
- **AND** 清理临时目录
#### Scenario: 启动 Execute 模式任务
- **WHEN** 方案审批后触发 mode="execute" 的任务执行
- **THEN** 系统启动带有会话恢复的容器
- **AND** 将仓库克隆到临时目录
- **AND** Claude Code 实现审批通过的方案
- **AND** 提交并推送变更到功能分支
- **AND** 完成后任务状态转换为 CODE_REVIEW
- **AND** 清理临时目录
#### Scenario: 容器资源隔离
- **WHEN** 任务容器启动时
- **THEN** 容器具有内存限制 (2GB)
- **AND** CPU 限制 (1 核)
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
The system SHALL invoke Claude Code CLI in headless mode with session persistence.
#### Scenario: Plan mode execution
- **WHEN** Claude Code runs in plan mode
- **THEN** the system restricts tools to read-only (Read, Glob, Grep, LS)
- **AND** generates an implementation plan without modifying code
- **AND** saves the session for later resumption
#### Scenario: Execute mode with session resume
- **WHEN** Claude Code runs in execute mode with a session ID
- **THEN** the system loads the previous session context
- **AND** Claude continues with the approved plan
- **AND** uses Edit tools to modify code
#### Scenario: Execution timeout handling
- **WHEN** Claude Code execution exceeds the configured timeout
- **THEN** the system terminates the process
- **AND** reports a timeout error to the callback endpoint
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
