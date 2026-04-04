---
title: 快速开始
---
# Friday AI 快速开始指南
Friday 是一个 AI 驱动的敏捷开发自动化系统，能够将飞书项目管理中的需求自动转化为代码合并请求（MR/PR）。
## 核心价值
- **全自动化链路**：从飞书需求创建到代码 MR，无需人工干预
- **AI 技术方案**：自动分析需求，生成结构化的技术实现方案
- **智能任务分派**：根据技术方案自动创建编码任务并分配到对应仓库
- **人机协作**：支持在关键节点（如方案审核）暂停等待人工确认
## 前置要求
### 必需环境
| 组件 | 版本要求 | 说明 |
|------|---------|------|
| Python | 3.14+ | 后端运行环境 |
| Node.js | 20+ | 前端构建环境 |
| pnpm | 8+ | 前端包管理器 |
| uv | 最新版 | Python 包管理器 |
| Git | 2.x | 版本控制 |
### 外部服务（可选）
| 服务 | 用途 | 必需性 |
|------|------|--------|
| 飞书项目空间 | 需求管理和 Webhook 触发 | 完整集成需要 |
| GitLab/GitHub | 代码仓库托管 | 创建 MR 需要 |
| Anthropic API | AI 技术方案生成 | AI 功能需要 |
## 快速安装
### 1. 克隆仓库
```bash
git clone https://github.com/your-org/friday-ai.git
cd friday-ai
```
### 2. 后端安装
```bash
cd server
# 安装依赖
uv sync
# 初始化数据库
uv run python manage.py migrate
# 创建管理员账户
uv run python manage.py createsuperuser
```
### 3. 前端安装
```bash
cd web
# 安装依赖
pnpm install
```
### 4. 环境配置
复制示例配置文件：
```bash
cp .env.example .env
```
编辑 `.env` 文件，配置以下必需项：
```bash
# Django 密钥（必需）
# 生成方式: python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key)"
SECRET_KEY=your-secret-key-here
# 数据加密密钥（必需）
# 生成方式: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key.decode)"
FRIDAY_ENCRYPTION_KEY=your-encryption-key-here
```
## 配置说明
### 环境变量
| 变量名 | 必需 | 默认值 | 说明 |
|--------|------|--------|------|
| `SECRET_KEY` | 是 | - | Django 密钥 |
| `FRIDAY_ENCRYPTION_KEY` | 是 | - | 敏感数据加密密钥 |
| `DATABASE_URL` | 否 | sqlite:///./data/friday.db | 数据库连接 |
| `DEBUG` | 否 | false | 调试模式 |
| `FRIDAY_WEB_PORT` | 否 | 10240 | 前端端口 |
| `FRIDAY_PORT` | 否 | 10241 | 后端 API 端口 |
### Anthropic API 配置
AI 功能需要配置 Anthropic API Key，支持两种方式：
1. **环境变量**：设置 `ANTHROPIC_API_KEY`
2. **项目级配置**：在 Web UI 的项目设置中配置（优先级更高）
### 飞书集成配置
1. 在飞书开放平台创建应用
2. 获取 App ID 和 App Secret
3. 配置 Webhook 回调地址：`https://your-domain/api/feishu/webhook/`
4. 在 Friday 系统设置中填入飞书应用凭据
### Git 仓库凭据
1. 进入 Friday Web UI
2. 创建项目并关联 GitLab/GitHub 仓库
3. 配置仓库访问令牌（Personal Access Token）
## 创建自动化工作流
### 步骤概览
1. **创建项目**：在 Friday 中创建项目，关联飞书项目空间
2. **添加仓库**：将代码仓库关联到项目
3. **创建工作流**：配置自动化工作流节点
### 工作流节点说明
Friday 提供以下核心节点类型：
#### 触发器节点
| 节点类型 | 说明 |
|---------|------|
| 飞书事件触发 | 监听飞书工作项创建、状态变更等事件 |
| 手动触发 | 通过 API 或 UI 手动启动工作流 |
| Webhook 触发 | 接收外部 HTTP 请求触发 |
#### AI 节点
| 节点类型 | 说明 |
|---------|------|
| AI 技术方案 | 基于需求自动生成结构化技术方案 |
| AI 编码指派器 | 根据技术方案创建编码任务 |
#### 控制节点
| 节点类型 | 说明 |
|---------|------|
| 等待飞书字段 | 暂停工作流，等待飞书字段变更后继续 |
| 条件分支 | 根据条件选择不同执行路径 |
### 推荐工作流配置
典型的需求到代码自动化工作流：
```
飞书事件触发 → AI 技术方案 → 等待飞书字段 → AI 编码指派器
```
**节点配置说明：**
1. **飞书事件触发**
 - 事件类型：工作项状态变更
 - 状态过滤：进入「开发中」状态时触发
2. **AI 技术方案**
 - 模型：claude-3-5-sonnet-20241022（推荐）
 - 飞书字段 Key：技术方案回填的目标字段
 - 自动流转状态：开启，目标状态「待审核」
3. **等待飞书字段**
 - 等待条件：审核状态字段变为「通过」
 - 超时时间：7 天（默认）
4. **AI 编码指派器**
 - 合并同分支任务：开启（推荐）
## 运行和测试
### 启动后端服务
```bash
cd server
uv run python manage.py runserver
```
后端服务运行在 `http://localhost:8000`
### 启动前端服务
```bash
cd web
pnpm dev
```
前端服务运行在 `http://localhost:5173`
### 访问服务
- **应用入口**：http://localhost:5173
- **API 文档**：http://localhost:8000/api/docs（Swagger UI）
- **API Schema**：http://localhost:8000/api/schema
### 测试工作流
**方式一：手动触发**
1. 进入工作流详情页
2. 点击「手动运行」按钮
3. 填入测试数据后执行
**方式二：飞书事件触发**
1. 确保飞书 Webhook 已正确配置
2. 在飞书中创建或更新工作项
3. 查看 Friday 工作流执行记录
## 常见问题和错误处理
### LLM API 错误
**错误信息**：`LLM API 错误: 401` 或 `未配置 Anthropic API Key`
**解决方案**：
1. 检查环境变量 `ANTHROPIC_API_KEY` 是否正确设置
2. 或在项目设置中配置 API Key
3. 确认 API Key 有效且有足够额度
### Schema 验证失败
**错误信息**：`技术方案验证失败: ...`
**解决方案**：
1. 检查需求描述是否足够清晰
2. 确保需求中包含具体的功能要求
3. 尝试调整 AI 模型或详细程度设置
### 飞书回填失败
**错误信息**：`飞书回填失败: ...` 或 `FeishuAPIError`
**解决方案**：
1. 检查飞书应用凭据是否正确
2. 确认飞书字段 Key 存在且有写入权限
3. 检查飞书应用是否有项目空间的访问权限
### 仓库未找到
**错误信息**：`仓库不存在: ...`
**解决方案**：
1. 确保仓库已关联到项目
2. 检查技术方案中的 repository_id 是否正确
3. 验证仓库访问令牌有效
### 工作流卡住
**错误信息**：工作流状态长时间为「运行中」或「等待事件」
**解决方案**：
1. 查看工作流执行详情页面的节点状态
2. 检查各节点的错误信息
3. 如果是「等待飞书字段」节点，确认条件是否已满足
4. 检查后端日志获取更多信息
### 编码任务创建失败
**错误信息**：`所有任务创建失败` 或 `缺少 workflow_execution 上下文`
**解决方案**：
1. 检查技术方案的 execution_plan 是否包含有效任务
2. 确认每个任务都指定了有效的 repository_id
3. 验证仓库已正确配置且可访问
## 下一步
### 深入了解
- **API 文档**：访问 `/api/docs` 查看完整 API 接口
- **API Schema**：访问 `/api/redoc` 获取 ReDoc 格式文档
### 进阶配置
- **自定义节点**：扩展 `workflows/nodes/` 目录创建自定义节点
- **多仓库支持**：一个项目可关联多个代码仓库
- **工作流模板**：保存常用工作流配置为模板
### 生产部署
使用 Docker Compose 进行生产环境部署：
```bash
# 配置环境变量
cp .env.example .env
# 编辑 .env 填入生产配置
# 启动服务
docker compose up -d
# 访问应用
# http://localhost:10240
```
## 获取帮助
- 查看项目 README 获取更多信息
- 提交 Issue 报告问题或建议
- 查看 `docs/` 目录下的其他文档
