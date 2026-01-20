## MODIFIED Requirements
### Requirement: Task Execution Container
系统 SHALL 在隔离的 Docker 容器中执行每个任务，使用 claude-agent-sdk Python 包进行 AI 代码生成，从数据库获取 Claude 配置。Task 容器作为独立项目构建，支持命令行直接调用。
#### Scenario: 启动 Plan 模式任务
- **WHEN** 触发 mode="plan" 的任务执行
- **THEN** 系统从数据库获取 Claude 配置（项目级或系统级）
- **AND** 系统启动带有任务配置的容器
- **AND** 将仓库克隆到临时目录（不创建新分支）
- **AND** 使用 permission_mode="plan" 仅允许只读操作
- **AND** 使用 claude-agent-sdk 的 ClaudeSDKClient 分析代码库
- **AND** 生成实现方案
- **AND** 完成后任务状态转换为 PLAN_REVIEW
- **AND** 清理临时目录
#### Scenario: 启动 Execute 模式任务
- **WHEN** 方案审批后触发 mode="execute" 的任务执行
- **THEN** 系统从数据库获取 Claude 配置
- **AND** 系统启动带有会话恢复的容器
- **AND** 将仓库克隆到临时目录并创建功能分支
- **AND** 使用 permission_mode="bypassPermissions" 跳过所有确认
- **AND** 使用 claude-agent-sdk 实现审批通过的方案
- **AND** 提交并推送变更到功能分支
- **AND** 完成后任务状态转换为 CODE_REVIEW
- **AND** 清理临时目录
#### Scenario: 容器资源隔离
- **WHEN** 任务容器启动时
- **THEN** 容器具有内存限制（2GB）
- **AND** CPU 限制（1 核）
- **AND** 隔离的网络环境
#### Scenario: 命令行直接调用
- **WHEN** 用户或 Claude Code 直接调用 friday-task 命令
- **AND** 传入 plan/exec 子命令、--git-url、--description、--api-key 等参数
- **THEN** 系统直接执行任务而无需 server 调度
- **AND** 回调 URL 为可选参数
- **AND** 无回调时任务结果仅输出到 stdout
#### Scenario: 无人值守执行
- **WHEN** Execute 模式执行时
- **THEN** 使用 permission_mode="bypassPermissions" 跳过所有确认
- **AND** 包括 Bash 命令、文件编辑等操作均自动执行
- **AND** 不会因为权限确认而中断等待用户输入
#### Scenario: 会话恢复
- **WHEN** 使用 --resume 参数指定 session-id
- **THEN** 系统加载之前的会话上下文
- **AND** 继续执行或获取之前的执行结果
## ADDED Requirements
### Requirement: Task CLI Interface
Task 模块 SHALL 提供命令行接口，支持独立运行和参数传入。
#### Scenario: Plan 模式命令行调用
- **WHEN** 执行 `friday-task plan --git-url xxx --description xxx --api-key xxx`
- **THEN** 系统克隆仓库（不创建新分支）并分析代码
- **AND** 使用 claude-agent-sdk 生成实现方案
- **AND** 将方案输出到 stdout
- **AND** 保存 session 信息供后续恢复
#### Scenario: Execute 模式命令行调用
- **WHEN** 执行 `friday-task exec --git-url xxx --description xxx --api-key xxx`
- **THEN** 系统克隆仓库并创建功能分支
- **AND** 执行代码变更
- **AND** 使用 description 前50字符作为 commit 消息标题
- **AND** 提交并推送变更到功能分支
- **AND** 输出分支名和 commit SHA
#### Scenario: 自定义功能分支名称
- **WHEN** 使用 --new-branch 参数指定功能分支名称（仅 exec 模式）
- **THEN** 系统使用指定名称创建新分支
- **AND** 未指定时默认生成唯一名称
#### Scenario: 参数和环境变量配置
- **WHEN** 同一配置项同时存在命令行参数和环境变量
- **THEN** 命令行参数优先于环境变量
- **AND** 支持 FRIDAY_TASK_ 前缀的环境变量
- **AND** 支持 ANTHROPIC_API_KEY、ANTHROPIC_BASE_URL 环境变量
#### Scenario: SSH 密钥认证
- **WHEN** 使用 --ssh-key 参数或 FRIDAY_TASK_GIT_SSH_KEY 环境变量
- **THEN** 系统使用 SSH 密钥进行 Git 认证
- **AND** 密钥内容直接传入而非文件路径
#### Scenario: Access Token 认证
- **WHEN** 使用 --access-token 参数或 FRIDAY_TASK_GIT_ACCESS_TOKEN 环境变量
- **THEN** 系统使用访问令牌进行 Git 认证
- **AND** 自动将 SSH URL 转换为 HTTPS URL
### Requirement: Standalone Task Project
Task 模块 SHALL 作为独立的 Python 项目进行管理、构建和测试。
#### Scenario: 独立构建
- **WHEN** 在 task/ 目录执行 `uv sync && uv build`
- **THEN** 系统生成 friday-task 包
- **AND** 不依赖 server 模块代码
#### Scenario: 独立测试
- **WHEN** 在 task/ 目录执行 `uv run pytest`
- **THEN** 系统运行 task 模块的所有测试
- **AND** 包含 CLI 测试、配置测试、集成测试
#### Scenario: Docker 镜像构建
- **WHEN** 执行 `docker build -t friday-task:latest ./task`
- **THEN** 系统构建任务容器镜像
- **AND** 镜像包含 Node.js 和 Claude Code CLI
- **AND** 入口点为 friday-task 命令
### Requirement: Optional Callback Mechanism
Task 容器 SHALL 支持可选的状态回调机制，允许独立运行模式。
#### Scenario: 有回调 URL 时
- **WHEN** 配置了 callback_url 参数
- **THEN** 系统向回调 URL 报告任务状态
- **AND** 包含 started、git_ready、plan_ready、execution_complete、error 等状态
#### Scenario: 无回调 URL 时
- **WHEN** 未配置 callback_url 参数
- **THEN** 系统以独立模式运行
- **AND** 状态变更仅记录到日志
- **AND** 最终结果输出到 stdout
