# Tasks: Task 模块独立化实施清单
## 1. 项目结构迁移
- 1.1 创建根目录 `task/` 目录结构
- 1.2 移动 `server/task/src/friday_task/` 到 `task/src/friday_task/`
- 1.3 移动 `server/task/Dockerfile` 到 `task/Dockerfile`
- 1.4 移动 `server/task/requirements.txt` 到 `task/requirements.txt`（作为参考，后续使用 pyproject.toml）
- 1.5 移动 `server/task/scripts/` 到 `task/scripts/`
## 2. 独立项目配置
- 2.1 创建 `task/pyproject.toml` - 包含项目元数据、依赖和构建配置
- 2.2 创建 `task/README.md` - 项目说明和使用文档
- 2.3 创建 `task/.gitignore` - Python 项目忽略规则
- 2.4 更新 `task/Dockerfile` - 调整构建上下文和入口点
## 3. 命令行接口实现
- 3.1 创建 `task/src/friday_task/cli.py` - 使用 click 实现命令行入口
- 3.2 实现 `plan` 子命令 - 执行计划模式（不创建新分支）
- 3.3 实现 `exec` 子命令 - 执行实现模式（创建新分支）
- 3.4 实现 `resume` 子命令 - 恢复会话
- 3.5 更新 `task/src/friday_task/config.py` - 移除 title 参数，description 作为必填
- 3.6 更新 `task/src/friday_task/config.py` - 添加 new_branch 参数
## 4. 权限模式和回调机制
- 4.1 更新 `task/src/friday_task/claude_runner.py` - Execute 模式使用 bypassPermissions
- 4.2 更新 `task/src/friday_task/callback.py` - 使回调 URL 可选
- 4.3 添加独立运行模式支持 - 无回调时仅记录日志
- 4.4 更新 `task/src/friday_task/runner.py` - Plan 模式不创建分支，适配可选回调
## 5. Session 管理增强
- 5.1 创建 session mapping 功能 - 支持 session_id 到 task_id 的映射
- 5.2 更新 `task/src/friday_task/claude_runner.py` - 支持通过 session_id 恢复
- 5.3 实现 session 查询和列表功能
## 6. 测试迁移
- 6.1 创建 `task/tests/` 目录结构
- 6.2 创建 `task/tests/conftest.py` - 测试配置和 fixtures
- 6.3 迁移 `server/tests/test_claude_sdk_integration.py` 到 `task/tests/`
- 6.4 创建 `task/tests/test_cli.py` - CLI 单元测试
- 6.5 创建 `task/tests/test_config.py` - 配置解析测试
- 6.6 创建 `task/tests/test_callback.py` - 回调客户端测试
## 7. Server 清理和更新
- 7.1 更新 `server/src/friday/services/scheduler.py` - 更新镜像构建路径注释
- 7.2 删除 `server/task/` 目录
- 7.3 删除 `server/tests/test_claude_sdk_integration.py`
## 8. Docker 构建更新
- 8.1 更新 `docker-compose.yml` - 修改 task 镜像构建路径
- 8.2 更新构建脚本（如有）
- 8.3 测试 Docker 镜像构建
## 9. 文档更新
- 9.1 更新根目录 `README.md` - 添加 task 子项目说明
- 9.2 创建 `task/README.md` - 详细使用说明
- 9.3 更新 `server/README.md` - 移除 task 相关内容
## 10. 验证
- 10.1 验证 task 独立构建：`cd task && uv sync && uv run pytest`
- 10.2 验证 CLI 功能：`uv run friday-task --help`
- 10.3 验证 Docker 构建：`docker build -t friday-task:latest ./task`
- 10.4 验证 server 集成：启动完整系统测试任务执行
- 10.5 验证 session 恢复功能
