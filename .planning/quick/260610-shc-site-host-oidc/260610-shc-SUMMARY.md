---
quick_id: 260610-shc
slug: site-host-oidc
date: 2026-06-10
status: complete
provides:
  - "OIDC 回调 URL（redirect_uri）与登录前端跳转优先消费 SystemSetting site_host"
  - "SettingKeys.SITE_HOST 常量 + identity.services.aresolve_site_base_url 解析器"
  - "前端 SettingKey.SITE_HOST 枚举（去掉 as any）+ 站点 Host 文案修正"
  - "docs/guide/admin.md 回调路径修正（/api/oidc/callback/）+ 站点 Host 配置说明"
---

# Quick Task 260610-shc: OIDC 回调 URL 消费「站点 Host」(site_host) 系统设置 Summary

## 根因

docker compose 部署下飞书 OIDC 登录被重定向到 `http://localhost:10241/api/oidc/callback/`：
`build_callback_url` 只读 env `FRIDAY_BASE_URL`（compose 未透传，落默认 localhost），
而设置页「站点 Host」（`site_host`）虽然承诺"用于生成回调 URL"，后端却从未读取（dead setting）。

## What Was Built

### server

- `system/models.py`：`SettingKeys.SITE_HOST = "site_host"`（补注释说明用途与回退语义）。
- `identity/services.py`：
  - 新增 `aresolve_site_base_url(fallback)`：读 `site_host` → trim/去尾斜杠/无 scheme 补 `http://`，
    空则回退 fallback（兼容旧部署，env 行为不回退）。
  - `build_callback_url` 改 async，base 经 `aresolve_site_base_url(FRIDAY_BASE_URL)`。
- `identity/views.py`：两处 `await build_callback_url`；回调成功跳转与 `_redirect_to_login`
  （改 async）的 frontend base 经 `aresolve_site_base_url(FRIDAY_FRONTEND_URL)`。
- 刻意不动的消费点：`coding.py` tools endpoint（RTOOL-03 决策强制 FRIDAY_BASE_URL）、
  `summary_service.py` 容器回调（内部链路，与外部站点地址语义不同）。

### tests

- `tests/test_oidc.py` 新增 `TestSiteHostResolution`（7 用例）：site_host 命中/回退/
  尾斜杠/补 scheme/空值回退 + authorize 端点 redirect_uri E2E + 登录错误跳转 E2E。
- `uv run pytest tests/test_oidc.py tests/test_auth_e2e.py -q` → **56 passed, 1 xfailed**。

### web + docs

- `web/src/api/settings.ts`：`SettingKey.SITE_HOST`；`GeneralSettings.vue` 用枚举替换
  `'site_host' as any`，修正「留空则使用请求中的 Host 头」虚假文案（实际回退 env）。
- `docs/guide/admin.md`：回调路径 `/api/identity/oidc/callback/` → `/api/oidc/callback/`
  （修正与路由不符的文档错误），补充站点 Host 配置步骤。

## 用户操作指引

1. 设置 → 通用 → 站点 Host 填 `http://<机器IP或域名>:10240`（web/nginx 端口，`/api` 会代理到后端）。
2. 飞书开放平台重定向 URL 配 `http://<机器IP或域名>:10240/api/oidc/callback/`。
3. 重新走登录（旧 code 已一次性失效）。无需改 env / 重启容器，设置实时生效。

## Self-Check: PASSED

- 测试全绿、ESLint 通过、`rg site_host server/` 命中 SettingKeys + identity 服务层。
