---
quick_id: 260610-shc
slug: site-host-oidc
date: 2026-06-10
status: planned
---

# Quick Task 260610-shc: OIDC 回调 URL 消费「站点 Host」(site_host) 系统设置

## 背景

用户 docker compose 部署后配置飞书 OIDC 登录，授权完成被重定向到
`http://localhost:10241/api/oidc/callback/`。根因：

1. `identity/services.py build_callback_url` 只读 `settings.FRIDAY_BASE_URL`（env，默认
   `http://localhost:10241`）；`identity/views.py` 前端跳转只读 `FRIDAY_FRONTEND_URL`。
2. `docker-compose.yaml` 未透传这两个 env 到 server 容器，env 路径在 compose 部署下不可用。
3. 设置页已有「站点 Host」（`site_host` SystemSetting）且文案承诺"用于生成回调 URL"，
   但后端没有任何代码读取它（`rg site_host server/` 零命中）——空头支票。

用户裁决：统一用「站点 Host」设置，不走 env / compose 修补路线。

## 任务

### Task 1: 后端消费 site_host

- `server/system/models.py`：`SettingKeys` 增加 `SITE_HOST = "site_host"`。
- `server/identity/services.py`：
  - 新增 `aresolve_site_base_url(fallback)`：优先读 `site_host`（trim + 去尾斜杠 +
    无 scheme 自动补 `http://`），空则回退 `fallback`。
  - `build_callback_url` 改 async，base 取 `aresolve_site_base_url(FRIDAY_BASE_URL)`。
- `server/identity/views.py`：
  - 两处 `build_callback_url(request)` 改 `await`。
  - 回调成功跳转与 `_redirect_to_login` 的 `frontend_base` 改为
    `aresolve_site_base_url(FRIDAY_FRONTEND_URL)`；`_redirect_to_login` 改 async。

不动的消费点（有明确架构决策的内部链路，site_host 是外部访问地址，不混用）：
- `workflows/nodes/ai/coding.py` tools endpoint（RTOOL-03 决策：强制 FRIDAY_BASE_URL）
- `repositories/summary_service.py` env_FRIDAY_CALLBACK_URL（容器内部回调）

### Task 2: 测试

- `server/tests/test_oidc.py` 新增 `TestSiteHostResolution`：
  - site_host 设置存在 → callback URL 用 site_host
  - 未设置 → 回退 FRIDAY_BASE_URL
  - 尾斜杠剥离、无 scheme 补 http://
- 运行 OIDC 相关测试回归。

### Task 3: 前端 + 文档

- `web/src/api/settings.ts`：`SettingKey` 枚举补 `SITE_HOST = 'site_host'`；
  `GeneralSettings.vue` 去掉 `as any`，修正「留空则使用请求中的 Host 头」误导文案。
- `docs/guide/admin.md`：回调路径 `/api/identity/oidc/callback/` 改为正确的
  `/api/oidc/callback/`，并补充「站点 Host」配置说明。

## 验证

- `uv run pytest tests/test_oidc.py tests/test_auth_e2e.py -q` 全绿
- `rg site_host server/` 命中 SettingKeys 与 identity 服务层
