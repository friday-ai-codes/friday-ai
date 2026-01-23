## MODIFIED Requirements
### Requirement: Git Operations
系统 SHALL 执行 Git 操作，包括克隆、分支创建、提交和推送，使用动态认证、临时工作目录和可选的代理配置。
#### Scenario: 使用 SSH 密钥克隆仓库
- **WHEN** 使用 SSH 认证开始 Git 操作
- **THEN** 系统从数据库读取加密的 SSH 密钥
- **AND** 解密后写入临时文件
- **AND** 配置 SSH_COMMAND 使用该私钥
- **AND** 将仓库克隆到临时工作目录
- **AND** 操作完成后删除临时密钥文件
#### Scenario: 使用 HTTP 代理克隆仓库
- **WHEN** 需要执行 Git 操作
- **THEN** 优先检查 Repository 级别的代理配置
- **AND** 若未配置，则检查系统级 `git_http_proxy` 配置
- **AND** 若存在有效配置，Git 操作（clone, push, pull）使用该代理
- **AND** 确保代理配置仅在任务执行期间生效，不污染全局环境
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
### Requirement: Repository Management
系统 SHALL 提供独立的 Git 仓库管理能力，支持创建、更新、查询和删除仓库配置。
#### Scenario: Create repository
- **WHEN** 用户调用创建仓库 API
- **AND** 提供 name, git_url, git_platform, default_branch
- **THEN** 系统创建新的 Repository 记录
#### Scenario: Update repository
- **WHEN** 用户调用更新仓库 API
- **THEN** 系统更新仓库配置信息
#### Scenario: Configure repository proxy
- **WHEN** 用户设置仓库的 proxy_url
- **THEN** 系统保存该仓库专用的代理配置
- **AND** 该配置在任务执行时优先级高于系统级全局代理
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
#### Scenario: 配置全局 Git 代理
- **WHEN** 设置 `git_http_proxy` 配置项
- **THEN** 该代理作为所有仓库的默认 Git 代理
- **AND** 仅在仓库未单独配置代理时生效
### Requirement: Task Execution Container
系统 SHALL 在隔离的 Docker 容器中执行每个任务，使用 claude-agent-sdk Python 包进行 AI 代码生成，从数据库获取 Claude 配置，并支持网络代理配置。
#### Scenario: 容器资源隔离
- **WHEN** 任务容器启动时
- **THEN** 容器具有内存限制（2GB）
- **AND** CPU 限制（1 核）
- **AND** 隔离的网络环境
#### Scenario: 传递代理配置
- **WHEN** 系统检测到配置了 Git 代理（仓库级或系统级）
- **THEN** 启动容器时注入代理相关的环境变量（如 `HTTP_PROXY`）
- **AND** 容器内的 Git 操作自动使用该代理
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
