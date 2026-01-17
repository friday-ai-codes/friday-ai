# 实施任务清单
## 1. 后端：系统设置模型和 API
- [x] 1.1 创建 `server/src/friday/models/settings.py` - SystemSettings 模型
- [x] 1.2 创建 `server/src/friday/routes/settings.py` - 系统设置 CRUD API
- [x] 1.3 在 `server/src/friday/main.py` 中注册 settings 路由
- [x] 1.4 生成 Alembic 迁移脚本 - 创建 system_settings 表
## 2. 后端：项目级 Claude 配置
- [x] 2.1 修改 `server/src/friday/models/project.py` - 添加 claude_api_key_encrypted 和 claude_base_url 字段
- [x] 2.2 创建 ProjectClaudeConfig Schema（Create/Read）
- [x] 2.3 在 `server/src/friday/routes/projects.py` 添加 Claude 配置 API 端点
- [x] 2.4 生成 Alembic 迁移脚本 - 添加项目 Claude 配置字段
## 3. 后端：配置获取服务
- [x] 3.1 创建 `server/src/friday/services/claude_config.py` - 配置获取服务
- [x] 3.2 实现配置优先级逻辑：项目级 > 系统级 > 环境变量
- [x] 3.3 修改 `server/src/friday/routes/tasks.py` - 使用新的配置获取服务
## 4. Task 容器迁移到 claude-agent-sdk
- [x] 4.1 修改 `server/task/requirements.txt` - 添加 claude-agent-sdk 依赖
- [x] 4.2 修改 `server/task/Dockerfile` - 添加 Node.js 和 Claude CLI 安装（SDK 依赖 CLI）
- [x] 4.3 重写 `server/task/src/claude_runner.py` - 使用 claude-agent-sdk
 - [x] 4.3.1 实现 `run_plan_mode` 使用 query
 - [x] 4.3.2 实现 `run_execute_mode` 使用 query
 - [x] 4.3.3 实现会话保存
 - [x] 4.3.4 处理 AssistantMessage、ResultMessage 等消息类型
- [x] 4.4 修改 `server/task/src/config.py` - 添加 claude_base_url 配置项
## 5. 前端：系统设置页面
- [x] 5.1 创建 `web/src/api/settings.ts` - 系统设置 API 客户端
- [x] 5.2 创建 `web/src/pages/settings/index.vue` - 系统设置页面
- [x] 5.3 在导航菜单中添加「设置」入口
## 6. 前端：项目 Claude 配置
- [x] 6.1 在 `web/src/api/settings.ts` 添加 Claude 配置 API 方法
- [x] 6.2 创建项目 Claude 配置页面 `web/src/pages/projects/[id]/claude.vue`
- [x] 6.3 在项目详情页添加 Claude 配置卡片
## 7. 测试脚本
- [x] 7.1 创建 `server/task/scripts/test_task_container.sh` - Task 容器测试脚本
- [x] 7.2 创建 `server/task/scripts/README.md` - 测试说明文档
## 8. 测试与文档
- [x] 8.1 后端单元测试 - 系统设置 CRUD
- [x] 8.2 后端单元测试 - 项目 Claude 配置
- [x] 8.3 后端单元测试 - 配置优先级获取逻辑
- [x] 8.4 集成测试 - claude-agent-sdk 运行（Plan 和 Execute 模式）
- [x] 8.5 更新 README.md - 说明 Claude Code 配置方式
- [x] 8.6 更新 .env.example - 添加 ANTHROPIC_BASE_URL 示例
