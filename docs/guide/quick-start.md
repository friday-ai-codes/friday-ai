---
title: 快速开始
---
# Friday AI 快速开始指南
Friday AI 是一个 AI 驱动的敏捷开发自动化系统，能够将飞书项目管理中的需求**自动转化为代码合并请求（MR/PR）**。从需求创建到代码提交，全链路无需人工干预。
本指南将帮助你在 **15 分钟内**完成从零部署到运行第一个自动化工作流的完整体验。
## 前置要求
| 组件 | 说明 |
|------|------|
| Docker + Docker Compose | 必需，用于一键部署所有服务 |
| Git | 必需，克隆仓库 |
| 飞书开放平台账号 | 可选，完整集成飞书项目管理需要 |
| Anthropic API Key | AI 功能（技术方案生成、编码指派）需要 |
| GitLab/GitHub Token | 代码仓库集成（创建 MR/PR）需要 |
## 一键部署（Docker Compose）
### 步骤 1: 克隆仓库
```bash
git clone https://github.com/your-org/friday-ai.git
cd friday-ai
```
### 步骤 2: 配置环境变量
```bash
cp .env.example .env
```
### 步骤 3: 生成必填密钥
运行以下命令分别生成三个必填密钥：
```bash
# 生成 SECRET_KEY（Django 密钥）
openssl rand -base64 32
# 生成 FRIDAY_ENCRYPTION_KEY（数据加密密钥）
openssl rand -base64 32
# 生成 RUNNER_REGISTRATION_TOKEN（Runner 注册令牌）
openssl rand -base64 32
```
编辑 `.env` 文件，将生成的三个值分别填入对应的配置项：
```bash
SECRET_KEY=<粘贴第一个生成值>
FRIDAY_ENCRYPTION_KEY=<粘贴第二个生成值>
RUNNER_REGISTRATION_TOKEN=<粘贴第三个生成值>
```
### 步骤 4: 启动服务
```bash
docker compose --profile postgres up -d
```:: tip 推荐配置
`--profile postgres` 会启动内置的 PostgreSQL 数据库，适合快速体验和中小规模部署。如果你已有外部 PostgreSQL，可以在 `.env` 中修改 `DATABASE_URL` 后去掉 `--profile postgres`。::
### 步骤 5: 访问验证
服务启动后，访问以下地址确认部署成功：
- **Web 界面**: [http://localhost:10240](http://localhost:10240)
- **API 接口**: [http://localhost:10241/api/](http://localhost:10241/api/)
### 服务架构
Docker Compose 部署包含以下服务：
| 服务 | 容器名 | 端口 | 说明 |
|------|--------|------|------|
| web | friday-web | 10240 | 前端 Web 界面（Nginx 代理） |
| server | friday-server | 10241 | 后端 API 服务（Django + Gunicorn） |
| redis | friday-redis | 6379 | 消息队列和缓存 |
| runner | friday-runner | - | 工作流任务执行器 |
| postgres | friday-postgres | 5432 | 内置 PostgreSQL 数据库 |
| qdrant | friday-qdrant | 6333/6334 | 向量数据库（代码语义检索） |
## 环境配置详解
### 必填环境变量
| 变量名 | 生成方式 | 说明 |
|--------|---------|------|
| <span v-pre>`SECRET_KEY`</span> | <span v-pre>`openssl rand -base64 32`</span> | Django 密钥，用于加密签名 |
| <span v-pre>`FRIDAY_ENCRYPTION_KEY`</span> | <span v-pre>`openssl rand -base64 32`</span> | 敏感数据加密密钥（API Key、Token 等） |
| <span v-pre>`RUNNER_REGISTRATION_TOKEN`</span> | <span v-pre>`openssl rand -base64 32`</span> | Runner 注册令牌，server 和 runner 共享 |
| <span v-pre>`DATABASE_URL`</span> | 见下方说明 | 数据库连接字符串 |
使用内置 PostgreSQL 时，`DATABASE_URL` 默认值为 <span v-pre>`postgres://friday:${POSTGRES_PASSWORD:-friday}@postgres:5432/friday`</span>，无需修改。:: warning 生产环境安全
生产环境部署时，务必为每个密钥生成独立的随机值。不要使用示例中的占位值，不要在多个环境间复用密钥。建议将 `.env` 文件权限设置为 `600`。::
### 飞书集成配置
在飞书开放平台（[open.feishu.cn](https://open.feishu.cn)）创建企业自建应用后，获取以下凭据并填入 `.env`：
| 变量名 | 获取方式 |
|--------|---------|
| <span v-pre>`LARK_APP_ID`</span> | 飞书开放平台 → 应用详情 → 凭证与基础信息 |
| <span v-pre>`LARK_APP_SECRET`</span> | 同上 |
| <span v-pre>`LARK_ENCRYPT_KEY`</span> | 飞书开放平台 → 事件订阅 → Encrypt Key |
| <span v-pre>`LARK_VERIFICATION_TOKEN`</span> | 飞书开放平台 → 事件订阅 → Verification Token |
配置飞书应用的事件回调地址为：<span v-pre>`https://your-domain/api/feishu/webhook/`</span>
### AI 配置
AI 功能需要 Anthropic API Key，支持两种配置方式：
1. **环境变量**（全局）：在 `.env` 中设置 `ANTHROPIC_API_KEY`
2. **项目级配置**（推荐）：在 Web UI 的项目设置中单独配置，优先级更高，适合多项目使用不同 Key
### Git 仓库凭据
Git 仓库的访问凭据通过 Web UI 配置，不在环境变量中设置：
1. 在 GitLab/GitHub 中生成 Personal Access Token（需要 `api` 和 `write_repository` 权限）
2. 在 Friday Web UI 的项目设置中填入仓库 URL 和 Token
## 创建第一个项目
### 1. 登录 Web UI
打开 [http://localhost:10240](http://localhost:10240)，使用管理员账户登录。:: tip 管理员账户
如果在 `.env` 中配置了 `FRIDAY_ADMIN_USERNAME` 和 `FRIDAY_ADMIN_PASSWORD`，系统会在首次启动时自动创建管理员账户。否则需要通过命令行创建：`docker exec friday-server python manage.py createsuperuser`::
### 2. 创建项目
进入「项目管理」页面，点击「创建项目」：
- **项目名称**：填写你的项目名（如 "我的第一个项目"）
- **飞书项目空间 ID**：关联飞书项目空间，用于自动同步需求:: tip 获取飞书项目空间 ID
在飞书项目中打开目标空间，URL 中的数字即为空间 ID。例如 URL 为 `https://project.feishu.cn/xxx/story/12345`，其中 `xxx` 就是空间标识。::
### 3. 添加代码仓库
在项目设置中关联代码仓库：
- **仓库 URL**：填写 GitLab/GitHub 仓库的 HTTPS 或 SSH 地址
- **Access Token**：填写具有代码推送权限的 Personal Access Token
## 运行第一个工作流
### 1. 创建工作流
进入项目详情 → 「工作流」标签页 → 点击「创建工作流」。
### 2. 配置推荐工作流
典型的需求到代码自动化工作流包含四个节点：
```
飞书事件触发 → AI 技术方案 → 等待飞书字段 → AI 编码指派器
```
**各节点配置：**
1. **飞书事件触发** — 事件类型选择「工作项状态变更」，状态过滤设为进入「开发中」时触发
2. **AI 技术方案** — 模型推荐 `claude-3-5-sonnet-20241022`，配置技术方案回填的飞书字段 Key
3. **等待飞书字段** — 等待条件设为审核状态字段变为「通过」，超时时间默认 7 天
4. **AI 编码指派器** — 建议开启「合并同分支任务」
### 3. 手动测试
点击工作流页面的「手动运行」按钮，填入测试数据后执行，验证工作流配置是否正确。
## 查看执行结果
### 执行详情
在工作流的「执行记录」页面，点击具体的执行记录查看详情：
- **DAG 视图**：以有向无环图展示各节点的执行状态和依赖关系
- **节点详情**：点击节点查看输入输出数据、执行日志和耗时
### 成功标志
一次完整的自动化工作流成功执行后，你会看到：
- 飞书工作项的技术方案字段被自动填充
- 飞书卡片状态更新（如从「开发中」流转到「待审核」）
- Git 仓库中出现自动创建的 MR/PR
## 本地开发环境
如果你需要进行二次开发或贡献代码，可以使用本地开发环境替代 Docker 部署。
### 后端安装
```bash
cd server
# 安装依赖
uv sync
# 初始化数据库
uv run python manage.py migrate
# 创建管理员账户
uv run python manage.py createsuperuser
```
### 前端安装
```bash
cd web
# 安装依赖
pnpm install
```
### 启动开发服务
```bash
# 启动后端（终端 1）
cd server && uv run python manage.py runserver
# 启动前端（终端 2）
cd web && pnpm dev
```
访问地址：
- 前端开发服务: [http://localhost:5173](http://localhost:5173)
- 后端 API: [http://localhost:8000](http://localhost:8000)
## 常见问题
### LLM API 错误
<div v-pre>
**错误信息**：`LLM API 错误: 401` 或 `未配置 Anthropic API Key`
</div>
**原因**：未配置或配置了无效的 Anthropic API Key。
**解决方案**：
1. 检查环境变量 `ANTHROPIC_API_KEY` 是否正确设置
2. 或在 Web UI 的项目设置中配置 API Key（优先级更高）
3. 确认 API Key 有效且账户有足够余额
### Schema 验证失败
<div v-pre>
**错误信息**：`技术方案验证失败: ...`
</div>
**原因**：AI 生成的技术方案不符合预期的 JSON Schema 结构。
**解决方案**：
1. 检查需求描述是否足够清晰、包含具体的功能要求
2. 尝试调整 AI 模型或提示词配置
3. 查看执行日志中的完整错误信息定位具体字段问题
### 飞书回填失败
<div v-pre>
**错误信息**：`飞书回填失败: ...` 或 `FeishuAPIError`
</div>
**原因**：飞书应用权限不足或字段配置错误。
**解决方案**：
1. 检查飞书应用凭据（App ID、App Secret）是否正确
2. 确认飞书字段 Key 存在且应用有写入权限
3. 检查飞书应用是否已被授权访问目标项目空间
### 仓库未找到
<div v-pre>
**错误信息**：`仓库不存在: ...`
</div>
**原因**：技术方案引用了未关联到项目的仓库。
**解决方案**：
1. 确保目标仓库已在项目设置中关联
2. 检查技术方案中的 `repository_id` 是否与已关联仓库匹配
3. 验证仓库访问令牌仍然有效
### 工作流卡住
**错误信息**：工作流状态长时间显示「运行中」或「等待事件」。
**原因**：某个节点执行失败或等待条件未满足。
**解决方案**：
1. 在工作流执行详情页面检查各节点状态，定位卡住的节点
2. 如果是「等待飞书字段」节点，确认飞书中对应字段的条件是否已满足
3. 检查后端日志获取更详细的错误信息：`docker logs friday-server --tail 100`
### 编码任务创建失败
<div v-pre>
**错误信息**：`所有任务创建失败` 或 `缺少 workflow_execution 上下文`
</div>
**原因**：技术方案的执行计划中任务配置不完整。
**解决方案**：
1. 检查技术方案的 `execution_plan` 是否包含有效的任务列表
2. 确认每个任务都指定了有效的 `repository_id`
3. 验证对应仓库已正确配置且访问令牌有效
## 下一步
- [工作流指南](/guide/workflows) -- 详细了解节点配置、触发器设置和工作流调试
- [管理指南](/guide/admin) -- 用户权限管理、OIDC 单点登录、Runner 管理
- [API 参考](/api/) -- 完整的 REST API 接口文档
