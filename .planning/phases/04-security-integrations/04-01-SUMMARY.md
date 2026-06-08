---
phase: 4
plan: "04-01"
wave: 1
status: complete
completed: 2026-06-08
requirements: [SEC-01, FEISHU-01, FEISHU-02, RAG-01, RAG-02]
---

# Plan 04-01 Summary — 后端安全校验 + 飞书/RAG 配置编排端点

## 交付
- `server/system/setup_serializers.py`（新建）：`SetupFeishuSerializer`、`SetupRagSerializer`（请求体校验，敏感项 write_only）。
- `server/system/setup_views.py`（新建）：
  - `SetupSecurityCheckView`（GET `/api/system/security-check/`，只读、非阻塞、不回显密钥）。
  - `SetupFeishuWizardView`（POST `/api/system/setup-feishu/`）。
  - `SetupRagWizardView`（POST `/api/system/setup-rag/`）。
- `server/system/urls_system.py`（改）：注册三个 `/api/system/` 路由。
- `server/tests/test_setup_integrations.py`（新建）：14 测试。

## 复用与安全
- 加密一律 `common.encryption.encrypt_value`；键名一律 `SettingKeys.*`；写法与 `bootstrap_system_settings` 一致
  （非敏感明文 `is_encrypted=False`，敏感 Fernet 密文 `is_encrypted=True`）。
- `FEISHU_APP_SECRET` / `QDRANT_API_KEY` / `EMBEDDING_API_KEY` 密文落库；既有读路径按 `is_encrypted`/`decrypt_value` 兼容。
- 安全校验只读、非阻塞，响应仅含布尔 + 风险码，断言不含任何密钥明文。
- 权限 `IsSuperUser`；adrf async + `sync_to_async` ORM 写。

## 测试
- `tests/test_setup_integrations.py` → 14 passed。
- 回归 `test_provider_setup_wizard.py` + `test_security_baseline.py` + `test_bootstrap_system_settings.py` → 17 passed。
- `ruff format` / `ruff check` 干净。
