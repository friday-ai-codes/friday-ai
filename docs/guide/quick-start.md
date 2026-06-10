---
title: 快速开始
---

# 快速开始

Friday AI 是一个 AI 驱动的敏捷开发自动化系统，能够将飞书项目管理中的需求**自动转化为代码合并请求（MR / PR）**。本指南帮助你在 **15 分钟内**完成从零部署到运行第一个自动化工作流的完整体验。

<FlowPipeline :steps="['部署启动', '初始化向导', '配置 AI Provider', '索引仓库', '运行工作流', '查看 PR / MR']" />

## 前置要求

| 组件 | 说明 |
| --- | --- |
| Docker + Docker Compose v2 | 必需，用于一键部署所有服务 |
| Git | 必需，克隆仓库 |
| AI Provider Key | AI 功能（技术方案生成、编码指派）需要，支持 Anthropic / OpenAI / Gemini / Ollama |
| GitLab / GitHub Token | 代码仓库集成（创建 MR / PR）需要 |
| 飞书开放平台账号 | 可选，完整集成飞书项目管理需要 |

## 一键部署（Docker Compose）

<Steps>

1. 克隆仓库

   ```bash
   git clone https://github.com/friday-ai-codes/friday-ai.git
   cd friday-ai
   ```

2. 初始化配置

   ```bash
   scripts/setup.sh
   ```

   脚本会自动生成必填密钥，写入 `.env`，并默认在 `~/.friday-ai` 下创建 `postgres`、`redis`、`qdrant`、`server`、`runner` 五个独立持久化目录。

3. 启动服务

   ```bash
   docker compose up -d
   ```

   Compose 会启动 Web、Server、Runner、PostgreSQL、Redis 和 Qdrant 完整栈，无需自己 build 镜像。

4. 访问验证

   | 入口 | 地址 |
   | --- | --- |
   | Web 界面 | <http://localhost:10240> |
   | API 接口 | <http://localhost:10241/api/> |

</Steps>

### 服务架构

| 服务 | 容器名 | 端口 | 说明 |
| --- | --- | --- | --- |
| web | friday-web | 10240 | 前端 Web 界面（Nginx 代理） |
| server | friday-server | 10241 | 后端 API 服务（Django + Gunicorn） |
| redis | friday-redis | 6379 | 消息队列和缓存 |
| runner | friday-runner | — | 工作流任务执行器 |
| postgres | friday-postgres | — | 内置 PostgreSQL 数据库 |
| qdrant | friday-qdrant | 6333/6334 | 向量数据库（代码语义检索） |

更多编排细节（Docker socket、回调端口、备份升级）见 [Docker Compose 部署](/deploy/docker-compose)。

## 环境配置详解

### 必填环境变量

| 变量名 | 生成方式 | 说明 |
| --- | --- | --- |
| `SECRET_KEY` | `openssl rand -base64 32` | Django 密钥，用于加密签名 |
| `FRIDAY_ENCRYPTION_KEY` | `openssl rand -base64 32` | 敏感数据加密密钥（API Key、Token 等） |
| `RUNNER_REGISTRATION_TOKEN` | `openssl rand -base64 32` | Runner 注册令牌，server 和 runner 共享 |
| `DATABASE_URL` | 见下方说明 | 数据库连接字符串 |
| `FRIDAY_DATA_DIR` | `scripts/setup.sh` 自动写入 | Docker 持久化数据宿主机目录 |
| `FRIDAY_IMAGE_PREFIX` | `scripts/setup.sh` 自动写入 | 预构建容器镜像命名空间 |
| `FRIDAY_IMAGE_TAG` | `scripts/setup.sh` 自动写入 | 预构建容器镜像标签 |

使用内置 PostgreSQL 时，`DATABASE_URL` 默认值为 `postgres://friday:${POSTGRES_PASSWORD:-friday}@postgres:5432/friday`，无需修改。完整变量列表见[环境变量参考](/deploy/configuration)。

::: warning 生产环境安全
生产环境部署时，务必为每个密钥生成独立的随机值。不要使用示例中的占位值，不要在多个环境间复用密钥。建议将 `.env` 文件权限设置为 `600`。
:::

### 飞书集成配置

在飞书开放平台（[open.feishu.cn](https://open.feishu.cn)）创建企业自建应用后，获取以下凭据并填入 `.env`：

| 变量名 | 获取方式 |
| --- | --- |
| `LARK_APP_ID` | 飞书开放平台 → 应用详情 → 凭证与基础信息 |
| `LARK_APP_SECRET` | 同上 |
| `LARK_ENCRYPT_KEY` | 飞书开放平台 → 事件订阅 → Encrypt Key |
| `LARK_VERIFICATION_TOKEN` | 飞书开放平台 → 事件订阅 → Verification Token |

配置飞书应用的事件回调地址为：`https://your-domain/api/feishu/webhook/`。详细步骤见[飞书集成](/integrations/feishu)。

### AI 配置

AI 功能需要配置 Provider 凭据，支持两种方式：

1. **环境变量**（全局）：在 `.env` 中设置 `ANTHROPIC_API_KEY`
2. **项目级配置**（推荐）：在 Web UI 的项目设置中单独配置，优先级更高，适合多项目使用不同 Key

### Git 仓库凭据

Git 仓库的访问凭据通过 Web UI 配置，不在环境变量中设置：

1. 在 GitLab / GitHub 中生成 Personal Access Token（需要 `api` 和 `write_repository` 权限）
2. 在 Friday Web UI 的项目设置中填入仓库 URL 和 Token

## 创建第一个项目

<Steps>

1. 登录 Web UI

   打开 <http://localhost:10240>。全新部署首次访问会自动进入「首启初始化向导」，按提示设置管理员用户名与密码即可（提交后自动登录进入系统）。

2. 创建项目

   进入「项目管理」页面，点击「创建项目」：

   - **项目名称**：填写你的项目名（如「我的第一个项目」）
   - **飞书项目空间 ID**：关联飞书项目空间，用于自动同步需求

3. 添加代码仓库

   在项目设置中关联代码仓库：

   - **仓库 URL**：填写 GitLab / GitHub 仓库的 HTTPS 或 SSH 地址
   - **Access Token**：填写具有代码推送权限的 Personal Access Token

</Steps>

::: tip 命令行兜底创建管理员
无界面环境可执行 `docker exec friday-server python manage.py init_superuser`（可配 `.env` 中的 `FRIDAY_ADMIN_USERNAME` / `FRIDAY_ADMIN_PASSWORD`），重置密码用 `docker exec friday-server python manage.py reset_superuser_password`。已存在管理员的实例不会出现向导。
:::

::: tip 获取飞书项目空间 ID
在飞书项目中打开目标空间，URL 中的标识即为空间 ID。例如 URL 为 `https://project.feishu.cn/xxx/story/12345`，其中 `xxx` 就是空间标识。
:::

## 运行第一个工作流

典型的需求到代码自动化工作流包含四个节点：

<FlowPipeline :steps="['飞书事件触发', 'AI 技术方案', '等待飞书字段', 'AI 编码指派器']" />

<Steps>

1. 创建工作流

   进入项目详情 → 「工作流」标签页 → 点击「创建工作流」。

2. 配置节点

   - **飞书事件触发** —— 事件类型选择「工作项状态变更」，状态过滤设为进入「开发中」时触发
   - **AI 技术方案** —— 选择已配置的模型，配置技术方案回填的飞书字段 Key
   - **等待飞书字段** —— 等待条件设为审核状态字段变为「通过」，超时时间默认 7 天
   - **AI 编码指派器** —— 建议开启「合并同分支任务」

3. 手动测试

   点击工作流页面的「手动运行」按钮，填入测试数据后执行，验证工作流配置是否正确。

</Steps>

## 查看执行结果

### 执行详情

在工作流的「执行记录」页面，点击具体的执行记录查看详情：

- **DAG 视图**：以有向无环图展示各节点的执行状态和依赖关系
- **节点详情**：点击节点查看输入输出数据、执行日志和耗时

### 成功标志

一次完整的自动化工作流成功执行后，你会看到：

- 飞书工作项的技术方案字段被自动填充
- 飞书卡片状态更新（如从「开发中」流转到「待审核」）
- Git 仓库中出现自动创建的 MR / PR

## 本地开发环境

如果你需要进行二次开发或贡献代码，参见[源码与本地开发](/deploy/source)。

## 常见问题

### LLM API 错误

**错误信息**：`LLM API 错误: 401` 或 `未配置 Anthropic API Key`

**原因**：未配置或配置了无效的 AI Provider Key。

**解决方案**：

1. 检查环境变量 `ANTHROPIC_API_KEY` 是否正确设置
2. 或在 Web UI 的项目设置中配置 API Key（优先级更高）
3. 确认 API Key 有效且账户有足够余额

### Schema 验证失败

**错误信息**：`技术方案验证失败: ...`

**原因**：AI 生成的技术方案不符合预期的 JSON Schema 结构。

**解决方案**：

1. 检查需求描述是否足够清晰、包含具体的功能要求
2. 尝试调整 AI 模型或提示词配置
3. 查看执行日志中的完整错误信息定位具体字段问题

### 飞书回填失败

**错误信息**：`飞书回填失败: ...` 或 `FeishuAPIError`

**原因**：飞书应用权限不足或字段配置错误。

**解决方案**：

1. 检查飞书应用凭据（App ID、App Secret）是否正确
2. 确认飞书字段 Key 存在且应用有写入权限
3. 检查飞书应用是否已被授权访问目标项目空间

### 仓库未找到

**错误信息**：`仓库不存在: ...`

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

**错误信息**：`所有任务创建失败` 或 `缺少 workflow_execution 上下文`

**原因**：技术方案的执行计划中任务配置不完整。

**解决方案**：

1. 检查技术方案的 `execution_plan` 是否包含有效的任务列表
2. 确认每个任务都指定了有效的 `repository_id`
3. 验证对应仓库已正确配置且访问令牌有效

## 下一步

<LinkCards>
  <LinkCard icon="🧩" title="工作流指南" desc="节点配置、触发器设置和工作流调试" link="/guide/workflows" />
  <LinkCard icon="🛡️" title="管理指南" desc="用户权限管理、OIDC 单点登录、Runner 管理" link="/guide/admin" />
  <LinkCard icon="🚀" title="部署总览" desc="Docker Compose、Helm / K8s、源码部署选型" link="/deploy/" />
  <LinkCard icon="📖" title="API 参考" desc="完整的 REST API 接口文档" link="/api/" />
</LinkCards>
