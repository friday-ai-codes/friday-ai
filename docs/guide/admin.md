---
title: 管理指南
---

# 管理指南

本指南面向系统管理员，涵盖用户管理、角色与权限配置、OIDC 单点登录、Runner 管理和高级部署等内容。

::: tip 前置阅读
请先完成[快速开始指南](/guide/quick-start)中的基础部署，再进行管理配置。
:::

## 用户管理

### 邀请用户

管理员可以通过 Web UI 邀请新用户加入项目：

1. 进入项目设置页面
2. 点击「成员管理」→「邀请成员」
3. 输入被邀请人的邮箱地址
4. 选择分配的角色（admin / member / viewer）
5. 发送邀请链接

::: tip
邀请链接发送后，被邀请人通过链接注册账号即可自动加入项目并获得对应角色。
:::

### 用户注册

- 收到邀请链接的用户点击链接进入注册页面
- 填写用户名、密码等基本信息完成注册
- 注册完成后自动关联到邀请的项目

### 分配与变更角色

管理员可以在项目成员列表中随时调整用户角色：

1. 进入项目设置 →「成员管理」
2. 找到目标用户，点击角色下拉框
3. 选择新角色并保存

## 角色与权限

Friday 采用 **Scoped RBAC**（基于项目的角色访问控制）模型。角色按项目分配，同一用户在不同项目中可以拥有不同角色。

### 角色定义

角色定义来源于 `ProjectRole`（`server/permissions/models.py`）：

| 角色 | 标识 | 说明 | 典型权限 |
| --- | --- | --- | --- |
| 管理员 | `admin` | 项目管理员 | 所有操作，包括成员管理、项目设置、工作流管理 |
| 成员 | `member` | 普通成员 | 创建/编辑工作流，查看执行记录，手动触发工作流 |
| 观察者 | `viewer` | 只读观察 | 查看项目、工作流和执行记录，不可修改 |

### 成员关系模型

`ProjectMembership` 模型关联用户（user）、项目（project）和角色（role），实现了灵活的项目级权限管理：

- 每个用户在每个项目中只能有一个角色（`unique_user_project` 约束）
- `invited_by` 字段记录邀请人，便于审计追踪
- `joined_at` 记录加入时间

::: warning 注意
每个项目至少需要保留一个 `admin` 角色用户。如果尝试移除最后一个管理员，操作将被拒绝。
:::

## OIDC 单点登录配置

Friday 支持 OIDC（OpenID Connect）单点登录，允许用户通过企业身份提供商（如 Azure AD、Okta、Keycloak 等）登录。

### 配置 Provider

通过管理后台或 API 创建 OIDC Provider 记录。配置字段如下（来源：`server/identity/models.py` — `OIDCProvider` 模型）：

| 字段 | 必填 | 说明 | 示例 |
| --- | --- | --- | --- |
| `name` | 是 | 提供商名称 | "企业 Azure AD" |
| `issuer_url` | 是 | Issuer URL | <span v-pre>`https://login.microsoftonline.com/{tenant}/v2.0`</span> |
| `client_id` | 是 | OAuth 应用 Client ID | 从 Provider 控制台获取 |
| `client_secret` | 是 | OAuth 应用 Client Secret（加密存储） | 从 Provider 控制台获取 |
| `authorization_endpoint` | 否 | 授权端点（可从 Discovery 自动获取） | |
| `token_endpoint` | 否 | Token 端点（可从 Discovery 自动获取） | |
| `userinfo_endpoint` | 否 | UserInfo 端点（可从 Discovery 自动获取） | |
| `scopes` | 否 | 请求范围，默认 `openid profile email` | `openid profile email` |
| `is_active` | 否 | 是否启用，默认 true | |

### Callback URL 配置

Friday 生成 OIDC 回调 URL 与登录跳转链接时，优先使用「系统设置 → 通用 → 站点 Host」配置的外部访问地址（如 `https://your-domain`）；未配置时自动使用当前请求的访问地址。如果部署在反向代理 / HTTPS 终止层之后，建议显式配置站点 Host，确保回调地址稳定一致。

然后在身份提供商控制台中，将以下 URL 配置为 Redirect URI / Callback URL：

```text
https://your-domain/api/oidc/callback/
```

### Discovery 自动发现

如果 Provider 支持 `.well-known/openid-configuration`（大多数主流提供商都支持），只需填写 `issuer_url`，Friday 会自动获取 `authorization_endpoint`、`token_endpoint` 和 `userinfo_endpoint`。

### 用户映射

OIDC 登录的用户会自动创建 `OIDCIdentity` 记录，关联到 Friday 用户账号：

- 首次 OIDC 登录时，系统根据 email 匹配已有用户或创建新用户
- `sub`（Subject）字段作为用户在该 Provider 中的唯一标识
- `raw_claims` 保存 Provider 返回的完整声明数据

::: warning 安全提示
`client_secret` 通过 `FRIDAY_ENCRYPTION_KEY` 环境变量加密后存储。请确保 `FRIDAY_ENCRYPTION_KEY` 已正确配置且妥善保管。
:::

## Runner 管理

### 架构概述

Runner 是 Friday 的执行代理，使用 Go 编写，通过 WebSocket 连接 Server。Runner 在 Docker 容器中隔离执行 AI 编码任务（`ai_coding`、`ai_code_review`），确保代码操作的安全性和独立性。内部实现见 [Runner 与 Task 执行器](/internals/runner)。

### 注册流程

Runner 注册基于一次性令牌机制（`RegistrationToken` 模型）：

<Steps>

1. 创建注册令牌

   管理员在 Web UI 或 API 中创建注册令牌：

   - 设置作用域（`scope`）：`global`（全局）或 `project`（项目级）
   - 设置预设标签（`tags`）：如 `["coding", "review"]`
   - 设置过期时间（`expires_at`）

2. 配置 Runner

   将令牌配置到 Runner 的 `RUNNER_REGISTRATION_TOKEN` 环境变量。

3. 启动注册

   Runner 启动时使用令牌向 Server 注册，成功后获得永久认证 token。

4. 令牌失效

   注册成功后，令牌自动标记为 `is_used=True`，不可重复使用。

</Steps>

::: danger 注意
注册令牌为一次性使用。如果令牌丢失或过期，需要重新生成。已使用的令牌无法再次使用。
:::

### 心跳监控

Runner 通过 WebSocket 连接定期发送心跳信号：

- `last_heartbeat` 字段记录最近一次心跳时间
- Server 端管理页面可查看所有 Runner 的在线状态（`online` / `offline`）
- 心跳超时表示 Runner 可能已离线，需排查网络或进程状态

### Runner 配置项

| 配置项 | 说明 | 默认值 |
| --- | --- | --- |
| `name` | Runner 名称 | — |
| `scope` | 作用域：global / project | `global` |
| `tags` | 能力标签 | `["coding"]` |
| `concurrent` | 并发任务数 | `1` |
| `run_untagged` | 是否运行未打标签的作业 | `true` |
| `is_protected` | 仅受保护分支 | `false` |
| `max_timeout` | 最大作业超时（秒），最小 600 | — |

### 故障排查

**Runner 无法注册：**

- 检查 `RUNNER_REGISTRATION_TOKEN` 是否与 Server 端创建的令牌匹配
- 检查令牌是否已过期（`expires_at`）或已被使用（`is_used`）
- 确认 Runner 与 Server 之间的网络连通性

**Runner 离线：**

- 检查 WebSocket 连接是否正常
- 确认 Docker socket 权限（Runner 需要访问 `/var/run/docker.sock`）
- 查看 Runner 进程日志排查错误

**任务执行失败：**

- 确认 Docker 服务正在运行
- 检查容器资源限制（CPU、内存）是否充足
- 查看任务执行日志获取详细错误信息

## 高级部署：Helm / K8s

需要在 Kubernetes 集群中进行生产级部署时，推荐使用 Helm Chart 安装。Chart 随每个版本发布到 GHCR（OCI 制品仓库），支持零配置安装（密钥自动随机生成并持久化）：

```bash
helm install friday oci://ghcr.io/friday-ai-codes/friday-ai/charts/friday \
  --namespace friday --create-namespace
```

完整的安装、升级、配置项与迁移说明见 [Helm / Kubernetes 部署](/deploy/helm)。

## 环境变量完整参考

完整的环境变量列表（端口、Django 核心、数据库、安全密钥、飞书、Redis、JWT、管理员等）统一维护在[环境变量参考](/deploy/configuration)。

## 下一步

<LinkCards>
  <LinkCard icon="⚡" title="快速开始指南" desc="基础部署入门" link="/guide/quick-start" />
  <LinkCard icon="🧩" title="工作流指南" desc="工作流配置操作" link="/guide/workflows" />
  <LinkCard icon="🔐" title="安全模型" desc="凭据加密、fail-closed 初始化、审计轨迹" link="/internals/security" />
</LinkCards>
