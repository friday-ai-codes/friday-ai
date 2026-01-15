## MODIFIED Requirements
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
