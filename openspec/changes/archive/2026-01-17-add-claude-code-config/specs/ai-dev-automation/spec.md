## ADDED Requirements
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
## MODIFIED Requirements
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
