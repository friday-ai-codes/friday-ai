# Task 容器测试指南
本目录包含用于测试 Task 容器的脚本和工具。
## 快速开始
### 1. 验证容器能否构建
```bash
# 进入 task 目录并构建镜像
cd server/task
docker build -t friday-ai-task:test .
```
### 2. 快速测试（Dry Run 模式）
仅查看将要执行的命令，不实际运行容器：
```bash
./scripts/test_task_container.sh --dry-run
```
### 3. 基本功能测试
使用测试 Git 仓库运行 plan 模式：
```bash
./scripts/test_task_container.sh \
 --mode plan \
 --title "添加用户认证功能" \
 --description "实现基于 JWT 的用户认证，包括登录、注册和密码重置功能" \
 --api-key "$ANTHROPIC_API_KEY"
```
### 4. 真实仓库测试
使用真实的 Git 仓库测试：
```bash
./scripts/test_task_container.sh \
 --mode plan \
 --repo-url "git@github.com:your-org/your-repo.git" \
 --title "重构数据库层" \
 --description "将数据库操作迁移到 Repository 模式" \
 --api-key "$ANTHROPIC_API_KEY"
```
### 5. 执行模式测试
在 plan 模式成功后，测试 execute 模式：
```bash
./scripts/test_task_container.sh \
 --mode execute \
 --title "添加单元测试" \
 --description "为核心模块添加单元测试" \
 --api-key "$ANTHROPIC_API_KEY" \
 --build
```
## 测试选项说明
| 选项 | 说明 | 默认值 |
|------|------|--------|
| `-m, --mode` | 任务模式: `plan` 或 `execute` | `plan` |
| `-t, --task-id` | 任务 ID | 自动生成 |
| `-p, --project-id` | 项目 ID | `test-project-001` |
| `--title` | 任务标题 | "测试任务" |
| `--description` | 任务描述 | 示例描述 |
| `--repo-url` | Git 仓库 URL | 创建本地测试仓库 |
| `--api-key` | Anthropic API Key | 环境变量 `$ANTHROPIC_API_KEY` |
| `--base-url` | Anthropic Base URL | 环境变量 `$ANTHROPIC_BASE_URL` |
| `--server-url` | Friday Server 回调地址 | `http://host.docker.internal:8000` |
| `--build` | 测试前重新构建镜像 | 否 |
| `--dry-run` | 只显示命令，不执行 | 否 |
## 环境变量
可以通过环境变量预先配置：
```bash
export ANTHROPIC_API_KEY="sk-ant-xxx"
export ANTHROPIC_BASE_URL="https://api.anthropic.com" # 或你的代理地址
```
## 常见问题
### 1. 容器无法访问宿主机的 Friday Server
确保使用正确的回调地址：
- macOS/Windows: 使用 `http://host.docker.internal:8000`
- Linux: 使用 `http://172.17.0.1:8000` 或添加 `--network host`
### 2. SSH 密钥问题
如果使用私有仓库，确保：
1. SSH 密钥存在于 `~/.ssh/id_rsa`
2. 密钥已添加到 Git 服务（GitHub/GitLab 等）
### 3. 查看容器日志
```bash
# 实时查看日志
docker logs -f friday-task-test-<PID>
# 或在容器内调试
docker run -it --entrypoint /bin/bash friday-ai-task:test
```
## 完整测试流程示例
```bash
# 1. 设置环境变量
export ANTHROPIC_API_KEY="your-api-key"
# 2. 构建并测试 plan 模式
./scripts/test_task_container.sh \
 --mode plan \
 --build \
 --title "实现 API 限流" \
 --description "添加基于令牌桶算法的 API 限流功能，每个用户每分钟最多 100 次请求"
# 3. 如果 plan 成功，测试 execute 模式
./scripts/test_task_container.sh \
 --mode execute \
 --title "实现 API 限流" \
 --description "添加基于令牌桶算法的 API 限流功能，每个用户每分钟最多 100 次请求"
# 4. 检查生成的代码
ls -la /tmp/tmp.*/workspace/
```
