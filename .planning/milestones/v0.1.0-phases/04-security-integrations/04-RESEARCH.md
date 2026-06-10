---
phase: 4
slug: security-integrations
created: 2026-06-08
---

# Phase 4 — Research（既有写法核对）

研究目标（关键复用约束）：飞书/RAG 配置必须复用既有 `SystemSetting` / `SettingKeys` /
`bootstrap_system_settings` 路径与既有 Fernet 加密；安全校验只做"检测+提示"不阻塞。以下为代码核对结论。

## 1. 加密写设置的范式（bootstrap_system_settings）

`server/system/management/commands/bootstrap_system_settings.py` 是加密写 `SystemSetting` 的权威范式：

```python
from common.encryption import encrypt_value
from system.models import SettingKeys, SystemSetting

SystemSetting.objects.get_or_create(
    key=SettingKeys.QDRANT_URL,
    defaults={"value": qdrant_url, "is_encrypted": False, "description": "..."},
)
SystemSetting.objects.get_or_create(
    key=SettingKeys.QDRANT_API_KEY,
    defaults={"value": encrypt_value(qdrant_api_key), "is_encrypted": True, "description": "..."},
)
```

→ 结论：非敏感项明文 `is_encrypted=False`；敏感项 `encrypt_value(...)` + `is_encrypted=True`。
Phase 4 向导端点对 `QDRANT_API_KEY` / `EMBEDDING_API_KEY` / `FEISHU_APP_SECRET` 采用同一写法；用
`update_or_create`（向导可重试，需幂等覆盖）而非 `get_or_create`。

## 2. SettingKeys 常量（server/system/models.py:29-58）

已存在且必须复用（不得硬编码字符串键）：
- `QDRANT_URL="qdrant_url"`、`QDRANT_API_KEY="qdrant_api_key"`
- `EMBEDDING_API_URL="embedding_api_url"`、`EMBEDDING_API_KEY="embedding_api_key"`、
  `EMBEDDING_MODEL="embedding_model"`、`EMBEDDING_DIMENSION="embedding_dimension"`
- `FEISHU_APP_ID="feishu_app_id"`、`FEISHU_APP_SECRET="feishu_app_secret"`

## 3. 既有读路径已兼容 is_encrypted（关键：加密不会破坏读取）

- 飞书 App Secret 读取：`feishu/websocket_client.py:359-362`、`services/feishu_im.py:648-654`：
  `value = setting.value; if setting.is_encrypted: value = decrypt_value(value)` → 加密存储读路径透明兼容。
- Qdrant Key 读取：`services/qdrant_service.py:78-80`、`repositories/index_views.py:784-788`：
  `decrypt_value(api_key_setting.value)`（`decrypt_value` 对明文有 fallback，密文/明文都安全）。
- Embedding Key 读取：`repositories/index_views.py:832-836` 同样 `decrypt_value`。
- 已知小瑕疵（**非本期目标，不改**）：`system/views.py` 的 `FeishuIMTestView` 直接读 `setting.value`
  未判 `is_encrypted`；主消费路径（websocket_client / feishu_im）均正确处理，故对本期落库无功能影响。

→ 结论：加密 `FEISHU_APP_SECRET` 安全（主消费路径解密），且更符合"敏感项走 Fernet"约束。

## 4. 安全密钥判定依据（settings.py + encryption.py）

- `friday/settings.py:35` `INSECURE_SECRET_KEY = "django-insecure-change-me-in-production"`；
  `:40` 默认 `SECRET_KEY=INSECURE_SECRET_KEY`；`:70` 生产模式即对默认 SECRET_KEY fail-fast。
- `friday/settings.py:320` `FRIDAY_ENCRYPTION_KEY = os.environ.get("FRIDAY_ENCRYPTION_KEY", "")`（默认空）。
- `common/encryption.py:30` `secret = FRIDAY_ENCRYPTION_KEY or SECRET_KEY` → 加密密钥为空时回退派生自 SECRET_KEY。

→ 判定：
- `secret_key_secure` = `SECRET_KEY` 非空且 ≠ `INSECURE_SECRET_KEY`
- `encryption_key_set` = `FRIDAY_ENCRYPTION_KEY` 非空
- `keys_independent` = `FRIDAY_ENCRYPTION_KEY` 非空且 ≠ `SECRET_KEY`
- 端点只返回布尔 + 风险清单，**绝不**返回任何密钥明文。

## 5. 端点 / 视图 / 测试范式

- adrf 异步视图范式：`system/views.py:ProviderSetupWizardView`（`APIView` + `IsSuperUser` +
  `await sync_to_async(serializer.is_valid)(raise_exception=True)` + `@sync_to_async` 包 ORM 写）。
- URL 放置：`system/urls_system.py`（`/api/system/`，当前仅 `health/`，无 `<str:key>/` 通配冲突）。
- 后端测试范式：`tests/test_provider_setup_wizard.py`（DRF `APIClient` + `force_authenticate`，
  `@pytest.mark.django_db(transaction=True)`，断言密文落库 + `decrypt_value` 还原 + 权限 403/401）。
- 前端测试范式：`web/src/components/setup/__tests__/SetupProviderStep.spec.ts`、
  `web/src/api/__tests__/setup.spec.ts`（`vi.mock('~/api/...')` + `vi.mock('vue-i18n')` 返回 key + mount）。

## 6. 前端集成点

- `web/src/api/setup.ts`：新增 `getSecurityCheck` / `setupFeishu` / `setupRag`（走 `client.ts` 的 `get`/`post`，
  此时已自动登录为 superuser，cookie-JWT 生效）。
- `web/src/pages/setup.vue`：步骤机扩展 + 圆点指示；新增三组件 `SetupSecurityStep/SetupFeishuStep/SetupRagStep`。
- `web/src/locales/zh-CN.json`：`setup.*` 新增 `steps.security/feishu/rag` 与 `security/feishu/rag/finish` 子树。
