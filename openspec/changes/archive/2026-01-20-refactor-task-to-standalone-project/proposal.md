# Change: 将 Task 模块迁移为独立项目
## Why
当前 Task 模块（`server/task/`）虽然物理上位于 server 目录下，但其功能是完全独立的 Docker 容器任务执行器。需要将其迁移到项目根目录作为独立子项目，以便：
1. **支持命令行直接调用**：可以独立运行，传入参数如 `baseurl`、`key`、`mode`（plan/exec）、Git 地址、需求描述等，直接被 Claude Code 使用
2. **独立构建和测试**：不依赖 server 模块，有自己完整的构建系统和测试套件
3. **更清晰的项目边界**：明确 server（API 服务）和 task（任务执行器）的职责分离
4. **简化 CI/CD**：可以独立发布和部署
## What Changes
### 目录结构变更
- **MOVE** `server/task/` → 根目录 `task/`
- **UPDATE** `task/pyproject.toml` - 创建独立的 Python 项目配置
- **UPDATE** `task/Dockerfile` - 调整构建上下文路径
### 功能增强
1. **命令行接口**：
 - 支持 `python -m friday_task --mode plan/exec --baseurl xxx --key xxx ...`
 - 支持环境变量和命令行参数两种配置方式
 - Git 仓库 URL、需求描述、新分支名称等参数支持直接传入
2. **会话管理增强**：
 - 支持 `--resume` 参数恢复之前的会话
 - session 映射信息可配置存储路径
3. **回调机制调整**：
 - 回调 URL 作为可选参数
 - 支持无回调的独立运行模式
### 测试迁移
- **MOVE** `server/tests/test_claude_sdk_integration.py` → `task/tests/`
- **REMOVE** server 中专属于 task 模块的测试
- **ADD** task 模块的单元测试和集成测试
### Docker Compose 更新
- **UPDATE** `docker-compose.yml` - 调整 task 镜像构建路径
## Impact
- Affected specs: `ai-dev-automation`
- Affected code:
 - `server/task/` → `task/`（完整迁移）
 - `server/src/friday/services/scheduler.py`（镜像路径引用注释）
 - `docker-compose.yml`（构建路径）
- Breaking changes:
 - **BREAKING** Docker 镜像构建路径变更，需要重新构建
 - 内部 API 不变，对 server 透明
