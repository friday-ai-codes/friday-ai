# Phase 4: 安全校验与可选集成步骤 - Context

**Gathered:** 2026-06-08
**Status:** Ready for planning

<domain>
## Phase Boundary

在 Phase 1/2/3 已交付的 `/setup` 多步向导外壳（glass 卡片 + `~/components/ui/*` + vee-validate/zod，
管理员账户 → AI 供应商）之上，**追加**三件事，全部为增量、绝不回退前序逻辑：

1. **安全密钥校验提示（SEC-01，非阻塞）**：向导检测后端 `SECRET_KEY` / `FRIDAY_ENCRYPTION_KEY`
   是否安全（非默认、相互独立），仅给风险提示，**永不阻塞**向导完成。
2. **可选飞书集成步骤（FEISHU-01/02）**：可一键跳过；填写 App ID / App Secret，写入与既有
   `SystemSetting` / `bootstrap_system_settings` 加密路径一致。
3. **可选向量检索步骤（RAG-01/02）**：可一键跳过；填写 Qdrant URL/Key、Embedding 配置，键名与既有
   `SettingKeys`（QDRANT_URL / QDRANT_API_KEY / EMBEDDING_*）对齐。

边界**之外**（沿用 REQUIREMENTS Out of Scope）：不把 `SECRET_KEY`/`FRIDAY_ENCRYPTION_KEY`
改成运行时可写设置（仅校验提示）；不重写四层 Provider 解析；不新建凭证/设置存储；不做主题化定制；
跳过的步骤稍后可在既有设置页（飞书 `FeishuIMConfigSection` / 向量检索 `VectorIndexSettings`）补充。

</domain>

<decisions>
## Implementation Decisions

### 安全密钥校验（SEC-01）
- 前端无法读 env，故新增**只读**后端端点 `GET /api/system/security-check/`（`IsSuperUser`），
  返回布尔判定 + 风险清单，**绝不回显密钥明文**。
- 判定逻辑（对齐 `friday/settings.py` 与 `common/encryption.py`）：
  - `secret_key_secure` = `SECRET_KEY` 非空且 ≠ `INSECURE_SECRET_KEY`（"django-insecure-change-me-in-production"）。
  - `encryption_key_set` = `FRIDAY_ENCRYPTION_KEY` 非空。
  - `keys_independent` = `FRIDAY_ENCRYPTION_KEY` 非空且 ≠ `SECRET_KEY`（为空时加密回退派生自 SECRET_KEY → 视为不独立）。
  - `secure` = 三者皆真。
- 风险项以 `{code, level:"warning", message}` 列表返回，前端按 warning 样式展示，**不阻塞**「继续」。
- 端点失败/异常时前端按"无法校验"中性提示处理，仍允许继续（fail-open 仅对提示，不影响安全落库）。

### 飞书集成（FEISHU-01/02）
- 新增编排端点 `POST /api/system/setup-feishu/`（`IsSuperUser`），薄封装写 `SystemSetting`：
  - `FEISHU_APP_ID` → 明文（`is_encrypted=False`，非敏感）。
  - `FEISHU_APP_SECRET` → `common.encryption.encrypt_value` 加密 + `is_encrypted=True`，
    与 `bootstrap_system_settings` 对 `QDRANT_API_KEY` 的加密写法一致；契合既有读路径
    （`feishu/websocket_client.py`、`services/feishu_im.py` 均 `if is_encrypted: decrypt_value(...)`）。
  - `update_or_create(key=...)` 幂等；用 `SettingKeys.FEISHU_APP_ID/FEISHU_APP_SECRET` 常量，不硬编码键名。
- 跳过 = 前端不调用该端点；向导照常完成。可稍后在 `admin` 设置页飞书区补充。

### 向量检索（RAG-01/02）
- 新增编排端点 `POST /api/system/setup-rag/`（`IsSuperUser`），按字段写 `SystemSetting`，键名严格对齐
  `SettingKeys`：`QDRANT_URL`、`QDRANT_API_KEY`、`EMBEDDING_API_URL`、`EMBEDDING_API_KEY`、
  `EMBEDDING_MODEL`、`EMBEDDING_DIMENSION`。
  - 敏感项（`QDRANT_API_KEY`、`EMBEDDING_API_KEY`）→ `encrypt_value` + `is_encrypted=True`
    （与 `bootstrap_system_settings` 一致；读路径 `qdrant_service.py`/`repositories/index_views.py` 用 `decrypt_value`，明文亦兼容）。
  - 非敏感项（URL / 模型 / 维度）→ 明文。
  - 仅写"已提供且非空"的字段；`update_or_create` 幂等。要求至少 `qdrant_url` 才视为有效配置。
- 跳过 = 前端不调用；可稍后在 `VectorIndexSettings` 补充。

### 向导步骤机（前端，增量）
- `setup.vue` 步骤机由 admin→provider 扩为：`admin → provider → security → feishu → rag → 进入首页`。
- 安全/飞书/RAG 三步均**新增**，provider 步骤的 `done`/`skip` 改为推进到 `security` 而非直接 `router.push('/')`。
- 三个新步骤抽为独立组件：`SetupSecurityStep.vue`（信息+继续）、`SetupFeishuStep.vue`（表单+跳过）、
  `SetupRagStep.vue`（表单+跳过，末步 done/skip → 进首页）。
- 步骤指示由两枚标签升级为 N 枚圆点 + `setup.steps.indicator`（"第 {current} / {total} 步"）文字，避免 5 标签拥挤。
- 不改 Phase 1 路由守卫、不改 Phase 2 自动登录、不改 Phase 3 供应商端点与组件契约。

### 端点放置与权限
- 三个新端点均挂 `/api/system/`（`system/urls_system.py`，当前仅 `health/`，无 `<str:key>/` 通配冲突），
  视图集中于新模块 `system/setup_views.py`，避免 `system/views.py` 继续膨胀。
- 权限统一 `permissions.api_permissions.IsSuperUser`（向导完成管理员创建并自动登录后调用方为 superuser）。
- adrf 异步视图；ORM 写走 `sync_to_async`（与 `ProviderSetupWizardView` 一致）。

### Claude's Discretion
- 风险项的 `code` 命名、i18n 文案细节、组件内部布局与圆点指示具体样式由实现自定，遵循既有设计系统。
- 是否对飞书/RAG 保存做可选连通校验：本期**不做**（成功标准只要求"可配置或跳过"，不要求健康校验），保持简单。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `common/encryption.py`：`encrypt_value` / `decrypt_value`（Fernet 唯一入口，明文 fallback）。
- `system/models.py`：`SystemSetting`（key 主键 + value + is_encrypted）、`SettingKeys`（QDRANT_*/EMBEDDING_*/FEISHU_*）。
- `system/management/commands/bootstrap_system_settings.py`：**加密写设置的范式**（`get_or_create` + `encrypt_value` + `is_encrypted=True`）。
- `permissions/api_permissions.py`：`IsSuperUser`。
- 读路径已支持 `is_encrypted` 分支：`feishu/websocket_client.py`、`services/feishu_im.py`（飞书），
  `services/qdrant_service.py`、`repositories/index_views.py`（Qdrant/Embedding，`decrypt_value` 明文兼容）。
- 前端：`web/src/api/setup.ts`（向导 API 封装）、`SetupProviderStep.vue`（步骤组件范式）、
  `lib/providerPresets.ts`、`web/src/locales/zh-CN.json` `setup.*` 命名空间、`~/components/ui/{form,input,button}`。
- 既有设置页参考：`web/src/pages/admin/components/FeishuIMConfigSection.vue` + `composables/useFeishuIMSettings.ts`、
  `web/src/components/settings/VectorIndexSettings.vue`（跳过后补填的归属页）。

### Established Patterns
- adrf `APIView` + `permission_classes=[IsSuperUser]` + `await sync_to_async(serializer.is_valid)(...)` + `sync_to_async` 包 ORM 写（见 `ProviderSetupWizardView`）。
- 后端测试：`tests/test_provider_setup_wizard.py` 用 DRF `APIClient` + `force_authenticate` 同步驱动 async 端点；断言密文落库 + `decrypt_value` 还原。
- 前端测试：`vi.mock('~/api/...')` + `@vue/test-utils` mount；`vi.mock('vue-i18n')` 返回 key。

### Integration Points
- URL：`system/urls_system.py`（`/api/system/`）追加三个 path。
- 前端：`setup.vue` 步骤机 + 三个新组件 + `api/setup.ts` 三个新函数 + `zh-CN.json` 新增文案。

</code_context>

<specifics>
## Specific Ideas

- 安全校验只读、非阻塞：端点只返回布尔 + 风险清单，绝不返回密钥明文；前端 warning 样式 + 始终可「继续」。
- 敏感项加密必须复用 `encrypt_value` + `is_encrypted=True`，与 `bootstrap_system_settings` 完全一致，使既有读路径透明兼容。
- 键名一律取 `SettingKeys.*` 常量，绝不在向导里硬编码字符串键。

</specifics>

<deferred>
## Deferred Ideas

- 飞书/RAG 保存后的连通健康校验（类似 Phase 3 的 provider health）——本期不做，留待后续增强（v2 SETUPX）。
- 向导收尾的部署健康总览（runner/DB/Redis/Qdrant 连通）——已在 REQUIREMENTS v2 SETUPX-03 跟踪，不在本期。

</deferred>
