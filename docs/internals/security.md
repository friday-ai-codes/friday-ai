---
title: 安全模型
---

# 安全模型

Friday 的定位是「安全地把需求自动变成代码」，安全设计贯穿凭据存储、初始化、执行隔离与审计四个层面。

## 凭据加密存储

所有运行时凭据（AI Provider Key、Git Token、飞书应用凭据、Qdrant API Key 等）**不走环境变量**，而是在 Web 界面配置后经 `cryptography` Fernet 对称加密存入数据库：

- 加密密钥为部署级的 `FRIDAY_ENCRYPTION_KEY`（32 字节，base64）；
- 统一通过 `ProviderCredential` / `SystemSetting`（`SettingKeys`）模型与对应 service 层读写，新增凭据类型必须复用这套通道，不绕过加密与权限；
- 个人访问令牌（PAT）只存哈希，明文仅在创建时显示一次（CI 中有 `test_no_plaintext_token_in_db` 守护测试）。

::: warning 密钥保管
`FRIDAY_ENCRYPTION_KEY` 丢失意味着数据库中所有加密凭据无法解密，备份时必须连同 `.env` 一起保存。
:::

## Fail-closed 初始化

首启初始化向导（设置管理员账号）是 fail-closed 设计：

- 仅当系统中**不存在任何 superuser** 时初始化接口可用；
- 一旦存在 superuser，接口直接拒绝 —— 防止被用于重置或接管已运行的实例；
- 命令行兜底（`init_superuser` / `reset_superuser_password`）保留，供无界面环境与运维恢复使用。

## 认证与权限

| 机制 | 实现 |
| --- | --- |
| Web 登录 | JWT（simplejwt + token blacklist），Cookie 携带，401 自动刷新重试 |
| 单点登录 | OIDC（Discovery 自动发现、用户映射），见[管理指南](/guide/admin#oidc-单点登录配置) |
| API / MCP 访问 | 个人访问令牌（PAT），`Authorization: Bearer` |
| Runner 注册 | 一次性注册令牌 `RUNNER_REGISTRATION_TOKEN`，注册后换长期凭据 |
| 角色权限 | 项目级角色与成员关系模型，越权操作返回显式 `PermissionDenied` |

生产硬化开关 `FRIDAY_ENV` / `FRIDAY_PRODUCTION`：强制 `DEBUG=False`、要求非默认 `SECRET_KEY` 与显式 `ALLOWED_HOSTS`，并自动启用 WebSocket TLS 要求。

## 执行隔离

AI 编码代理永远不在 server 进程里运行：

- Runner 把每个任务放进独立容器（Docker / k8s Job），代理只拿到该任务所需的仓库与一次性凭据；
- 任务容器与 server 之间只有受控的回调通道（进度、提问、结果），拿不到数据库与全局密钥；
- 执行真实写操作（推分支、建 MR）的 MCP / Skill workflow 内置「执行前必须人工确认」的硬性规则。

## 日志与泄漏防护

- 结构化日志（structlog）统一经 `common.logging.configure_structlog` 配置，内置凭据脱敏（CI 守护测试 `test_credential_leak_protection`）；
- CI 每次运行 gitleaks 扫描完整 Git 历史，防止密钥误提交；
- Task 镜像每次构建经 Trivy CVE 扫描（CRITICAL / HIGH 即失败）。

## 审计轨迹

每条 AI 链路都落在 Interaction Ledger 中：`InteractionRun`、`InteractionEvent`、`ToolCallRecord`、`RetrievalTrace`、模型用量、执行轨迹与 MR 结果记录。多步 Skill workflow 通过 `run_id` 聚合为同一条轨迹，团队可以追问每一步「为什么这么改、依据是什么」。

## 漏洞报告

请勿在公开 issue 中报告安全漏洞，流程见仓库 [SECURITY.md](https://github.com/friday-ai-codes/friday-ai/blob/main/SECURITY.md)。
