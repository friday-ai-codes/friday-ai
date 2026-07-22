---
quick_id: 260722-npg
slug: gitlab-push-webhook-main
description: GitLab 仓库一键自动配置 push webhook（main 分支变更通知）
created: 2026-07-22
status: complete
---

# Quick Task 260722-npg: GitLab 仓库一键自动配置 push webhook

## 背景

接收端已就绪：`POST /api/repositories/{id}/webhooks/push/`（`RepositoryWebhookView`）验
`X-Gitlab-Token`（per-repo `Repository.webhook_secret`），default_branch push 触发自动索引。
缺"出站"一步：用 service account（`GitInstanceCredential` / `GitCredential` 解析出的 token）
调 GitLab API 把 project hook 自动创建出来。

外网地址复用既有「站点 Host」设置：`identity.services.aresolve_site_base_url`
（site_host → 请求 Host → FRIDAY_BASE_URL）。

## 任务

### T1 后端：GitLabClient.ensure_push_webhook + setup-webhook API

- `server/services/git_platform/models.py`：新增 `WebhookSetupResult` dataclass。
- `server/services/git_platform/gitlab_client.py`：新增 `ensure_push_webhook(url, secret, branch_filter)`
  - 幂等：按 url 匹配已有 hook，命中则更新（token / push_events / branch filter），否则创建。
  - GitLab 错误按 response_code 翻译成中文提示（401 token 无效 / 403 权限不足需 Maintainer+api scope /
    404 项目不可见 / 422 URL 被拒绝需管理端允许本地网络）。
- `server/repositories/views.py`：`RepositoryViewSet` 新增 action `setup_webhook`
  （`POST /api/repositories/{id}/setup-webhook/`）：
  - 仅 GitLab 平台；无 secret 先生成；`aresolve_git_token` 解析 token（无则 400）；
  - `aresolve_site_base_url` 拼回调 URL；默认 branch_filter = `default_branch`；
  - 成功时顺手启用 `auto_index_enabled`（接收端 fail-closed 依赖它）；
  - structlog：`repository_webhook_setup_started/completed/failed`，category=caller，
    component=repositories，带 duration_ms；错误文本过 `redact_secrets_in_text`。

### T2 前端：一键配置入口

- `web/src/api/repositories.ts`：`setupWebhook(id)`。
- `WebhookConfigPanel.vue`：GitLab 仓库显示「一键配置 Webhook」按钮；非 GitLab 保留手动指引。
- `CreateRepositoryModal.vue`：GitLab + 测连成功后显示勾选项「自动配置 Webhook（默认分支变更时自动通知）」，
  建仓成功后 best-effort 调 setup（失败仅告警 toast，不阻塞建仓）。
- `EditRepositoryModal.vue`：同款勾选项，保存后触发。

### T3 测试

- `server/tests/repositories/test_setup_webhook.py`：
  平台不支持 400 / 无凭证 400 / 成功创建（mock GitLabClient）/ 幂等更新 / GitLab 403 错误翻译。

## 验证

- `uv run pytest tests/repositories/test_setup_webhook.py`
- `pnpm vue-tsc`（或 eslint）前端类型检查
