## ADDED Requirements
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
## MODIFIED Requirements
### Requirement: Git Credential Management
Git 凭证 SHALL 关联到 Repository 而非 Project。
#### Scenario: Add SSH key to repository
- **WHEN** 用户为仓库添加 SSH 私钥
- **THEN** 系统将凭证与 Repository 关联
- **AND** 存储加密的私钥
### Requirement: Project Management
Project 配置 SHALL 移除 Git 相关字段（repo_url, git_platform, default_branch, claude_md_path），仅保留项目基本信息和飞书配置。
#### Scenario: Create project (Simplified)
- **WHEN** user creates a new project
- **THEN** only name and description are required
- **AND** Git configuration is handled via Repository association
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