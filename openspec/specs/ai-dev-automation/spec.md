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
