---
quick_id: 260722-npg
status: complete
completed: 2026-07-22
---

# Summary: GitLab 仓库一键自动配置 push webhook

## 交付

**后端**

- `services/git_platform/models.py`：新增 `WebhookSetupResult` dataclass。
- `services/git_platform/gitlab_client.py`：
  - `GitLabClient.ensure_push_webhook(url, secret, branch_filter)`：幂等（按 URL 匹配已有
    project hook，命中更新、未中创建），`push_events_branch_filter` 原生按分支过滤。
  - `translate_gitlab_hook_error`：401/403/404/422 → 用户可读中文提示（token/响应体绝不回显）。
- `repositories/views.py`：`POST /api/repositories/{id}/setup-webhook/`：
  - 仅 GitLab；无 secret 先生成（已有不覆盖）；`aresolve_git_token` 解析凭证；
  - 回调 URL 用既有「站点 Host」链路（`aresolve_site_base_url`：site_host 设置 → 请求 Host → FRIDAY_BASE_URL）；
  - branch_filter 缺省 = default_branch，可 body 覆盖（空串 = 全部分支）；
  - 成功后启用 `auto_index_enabled`（接收端 fail-closed 依赖）；
  - structlog `repository_webhook_setup_started/completed/failed`（caller / repositories / duration_ms）。

**前端**

- `api/repositories.ts`：`setupWebhook(id, {branch_filter?})` + `SetupWebhookResponse`。
- `WebhookConfigPanel.vue`：GitLab 仓库显示「一键配置」按钮；手动指引保留兜底。
- `CreateRepositoryModal.vue`：GitLab + 测连成功后显示「自动配置 Webhook」勾选（默认勾选），
  建仓成功后 best-effort 调 setup，失败仅 toast 不阻塞。
- `EditRepositoryModal.vue`：同款勾选（默认不勾选），保存后触发。

## 验证

- `tests/repositories/test_setup_webhook.py`：11 passed（平台/凭证守卫、成功路径含 secret
  生成与 auto_index 启用、branch_filter 覆盖、secret 不重生成、失败翻译、错误码翻译参数化）。
- ruff check/format 通过；eslint + vue-tsc 通过。

## 备注

- GitHub/Gitea 未做出站自动配置（接口按平台守卫返回 400 并提示手动配置），后续可扩展。
- GitLab 拒绝内网回调 URL 时提示启用 "Allow requests to the local network from webhooks"。
