# Phase 3: LLM 供应商配置与 Claude Code 绑定 - Context

**Gathered:** 2026-06-08
**Status:** Ready for planning
**Mode:** autonomous smart-discuss（无人值守，所有灰区直接采纳推荐答案，未调用 AskUserQuestion）

<domain>
## Phase Boundary

本阶段在 Phase 1（门禁 + 向导外壳）与 Phase 2（管理员创建 + 自动登录会话）之上，在首启向导中**新增「供应商配置」步骤**，打通"能跑 AI"闭环：用户通过一键模型预设配好至少一个 Anthropic 兼容供应商，凭证经既有 Fernet 加密路径密文落库、健康校验通过、设为系统默认并绑定 Claude Code 运行配置。

**关键前提（复用而非重建）：** Phase 2 创建 superuser 后已下发 cookie-JWT 会话，向导用户在 Phase 3 即为**已认证的 superuser**。因此既有 `/api/providers/*` 全套能力（`ProviderCredentialCreateSerializer` Fernet 加密、`provider_health.health_check`、`set-default`、`aset_claude_code_config`）的 `IsSuperUser`/`IsAuthenticated` 权限天然满足，可直接复用，**不新建凭证存储、不绕过加密与权限**。

**In scope（Phase 3 拥有）：**
- 后端：新增**一个薄编排端点** `POST /api/providers/setup-wizard/`（`IsSuperUser`），对既有 service 层做幂等编排：Pydantic 校验 → 健康校验（连通/鉴权）→ Fernet 加密 upsert 系统级 anthropic `ProviderCredential` → 设为 `is_default` → 绑定 `claude_code_config`（opus/sonnet/haiku 三档映射）。失败给出可操作中文提示。
- 后端：`provider_health.py` 新增**无状态健康校验** helper `health_check_config(provider_type, cfg, model)`，复用既有 `_PING_DISPATCH`，不产生 DB 副作用（用于落库前的连通/鉴权门）。
- 前端：将 `setup.vue` 升级为**两步向导**（步骤 1=管理员，步骤 2=供应商），新增供应商配置步骤组件 + 5 个一键预设（DeepSeek V4 Pro / MiMo V2.5 Pro / Kimi 2.6 / Anthropic 官方 / 自定义兼容端点），预设自动填充 `base_url` + 默认 `model`、展示模型能力（上下文长度、是否多模态/图像），用户仅需填 API Key。
- 前端：复用既有 `providerCredentials` 类型；新增 `api/setup.ts::setupProvider()` 调用编排端点；i18n（`setup.steps.*` / `setup.provider.*`，默认中文）。
- 前后端测试覆盖 PROV-01..05、SEC-02。

**Out of scope（不在本阶段）：**
- 不重写既有四层 Provider 解析（`ProviderConfigService`）、不改既有 `/api/providers/credentials/` CRUD、`test-connection`、`refresh-models`、`claude-code-config` 端点语义。
- 不回退 Phase 1 fail-closed 门禁 / 原子防重入 / `SetupNotInitialized`，不回退 Phase 2 管理员创建 + 自动登录。
- 安全密钥（SECRET_KEY/FRIDAY_ENCRYPTION_KEY）健康校验提示、可选飞书/RAG 步骤 → Phase 4；entrypoint 迁移 → Phase 5。
- 多供应商批量配置、项目级凭证、模型逐一手选（向导只配「一个系统默认 anthropic 兼容供应商」最小闭环）。

**判定标准：** 用户在向导步骤 2 选预设 → base_url/model 自动填充并展示能力 → 仅填 API Key → 提交触发连通/鉴权健康校验（失败给可操作中文提示）→ 成功则密文落库（Fernet）+ 设系统默认 + 绑定 Claude Code → 进入系统首页 `/`。
</domain>

<decisions>
## Implementation Decisions

### A. 编排放在后端薄端点（而非前端多次串调）
- 新增 `POST /api/providers/setup-wizard/`（`permission_classes=[IsSuperUser]`），单次原子编排「校验→健康校验→Fernet upsert→设默认→绑 Claude Code」，给前端**单一清晰的 PROV-04 错误路径**，避免前端 4 次串调（create→test→set-default→claude-code-config）的部分失败/清理复杂度。
- 该端点**不自建存储、不绕过加密**：写库仍走 `encrypt_value(json.dumps(...))`（与 `ProviderCredentialCreateSerializer.create` 同一 Fernet 路径），Claude Code 绑定仍走既有 `aset_claude_code_config`，健康校验仍走既有 `provider_health` 的 `_PING_DISPATCH`。
- **幂等**：按 `(scope="system", provider_type="anthropic", name)` 做 `update_or_create`，用户改 key 重试不会撞 `uniq_system_provider_credential` 唯一约束。

### B. 健康校验时机与实现（PROV-04 + SEC-02）
- **落库前**先做无状态健康校验（连通/鉴权），失败则**不落任何凭证**、返回 400 + 可操作中文提示（如「连接/鉴权失败：<脱敏错误>。请检查 API Key 是否正确、Base URL 是否为该供应商的 Anthropic 兼容端点」），用户修正 key 后可直接重试。
- 新增 `health_check_config(provider_type, cfg, model)`：构造**未保存**的 `ProviderCredential` stub + 复用 `_PING_DISPATCH[anthropic]=_ping_anthropic`（POST `/v1/messages/count_tokens`，最稳健的 anthropic 兼容探活端点），不触发 `health_check` 内的 `aupdate` DB 副作用。
- 错误一律经既有 `redact_secrets_in_text`/`_safe_error` 脱敏后返回（沿用 provider_health 安全契约），绝不回显 api_key 明文。

### C. 凭证落库与默认/Claude Code 绑定（PROV-01/04/05、SEC-02）
- `encrypted_config = encrypt_value(json.dumps({"api_key":..., "base_url":...}))`；`default_model = 预设/自定义 model`；`available_models = _normalize_available_models([{id: model, context_length?, supports_vision?}], provider_type="anthropic")`（复用既有归一化 + 能力推断）。
- 设默认：与既有 ViewSet `set_default` 同一原子语义（同 `(scope, scope_id, provider_type)` 维度先清零其他 `is_default` 再置位），DB `uniq_default_provider_per_scope_type` 约束兜底。
- 绑定 Claude Code：`await aset_claude_code_config(str(cred.id), {"opus":model,"sonnet":model,"haiku":model})`；该函数会校验三档 model ∈ `available_models`，因 available_models 含该 model 故通过。
- SEC-02 测试：断言 DB `encrypted_config` 不含明文 api_key、且 `decrypt_value(encrypted_config)` 还原原值。

### D. 前端两步向导结构（PROV-02/03 + UI）
- `setup.vue` 增加内部 `step` 状态（`'admin' | 'provider'`）：管理员表单提交成功（Phase 2 已自动登录）后**原地切到供应商步骤**（不做路由跳转，避免触发/改动 Phase 1 路由守卫——守卫不回退），供应商步骤完成后再 `router.push('/')`。
- 顶部加轻量步骤指示（1/2）。供应商步骤抽为组件 `components/setup/SetupProviderStep.vue`（更易测）。
- 5 个预设（前端常量 `lib/providerPresets.ts`）：每项含 `id/label/baseUrl/model/contextLength/supportsVision/description`；选中后自动填充 base_url + model（仍可编辑以纠错），custom 预设需用户自填 base_url + model；能力以 badge 展示（上下文长度、文本/图像）。
- 提交调用 `setupProvider()`；失败展示后端可操作中文提示并允许重试；提供**克制的**「稍后在设置中配置」次级动作（与刷新即回首页的行为一致；记为 Claude 自主裁量，平衡「必配」意图与 UX 逃生）。

### E. 路由守卫不回退（安全）
- 不修改 `main.ts` 路由守卫的 fail-closed 语义；向导步骤切换走组件内部状态，不产生 `/setup` 导航，守卫不触发。Phase 1 的 init 端点仍后端 403 兜底（已初始化拒绝），匿名访客仍被导向 `/login`。

### Claude's Discretion
- 预设的具体 base_url/model 取值（按各供应商 Anthropic 兼容端点的公开约定填写，且字段可编辑以纠错）、步骤指示与能力 badge 的视觉实现、`setup-wizard` 响应体字段命名、测试文件拆分与命名、「稍后配置」次级动作的呈现，均由规划/执行阶段按既有约定自主决定。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets（直接复用，勿重建）
- **凭证模型与加密**：`system.models.ProviderCredential`（`encrypted_config`/`is_default`/`available_models`/`default_model`/`last_health_check_*`，唯一约束 `uniq_system_provider_credential`、`uniq_default_provider_per_scope_type`）；`common.encryption.encrypt_value/decrypt_value`（Fernet）。
- **创建/校验序列化器**：`system.serializers.ProviderCredentialCreateSerializer`（Pydantic `AnthropicCredentialSchema` 校验 + `encrypt_value` 落库）、`_normalize_available_models`（能力推断 + 去重）、`_validate_bound_models`。
- **健康校验**：`services.provider_health.health_check` / `_PING_DISPATCH` / `_ping_anthropic`（POST `/v1/messages/count_tokens`）/ `_safe_error`+`redact_secrets_in_text`（脱敏契约）。
- **Provider 注册表**：`services.provider_config.PROVIDER_REGISTRY[ProviderType.ANTHROPIC]`（`AnthropicCredentialSchema`，`base_url` 默认 `https://api.anthropic.com`，`supports_vision=True`）。
- **Claude Code 绑定**：`services.provider_config.aset_claude_code_config(credential_id, model_mapping)` + `CLAUDE_CODE_MODEL_TIERS=(opus,sonnet,haiku)` + `SettingKeys.CLAUDE_CODE_CONFIG`。
- **既有 Provider API**：`/api/providers/credentials/`(CRUD)、`/test-connection/`、`/set-default/`、`/refresh-models/`、`/claude-code-config/`、`/fetch-models/`、`/types/`（挂载 `system/urls_providers.py`）。
- **权限**：`permissions.api_permissions.IsSuperUser`。
- **前端**：`api/providerCredentials.ts` + `types/providerCredential.ts`（`AvailableModel`/`ProviderCredentialCreatePayload`/`ClaudeCodeConfigPayload`）；既有 provider 组件 `components/providers/*`（参考样式，非直接复用）。
- **向导外壳**：`pages/setup.vue`（glass 卡片 + vee-validate/zod + `~/components/ui/{form,input,button}`）；`stores/auth.ts::applySetupSession`；`api/setup.ts`。
- **测试基线**：`tests/test_provider_health.py`（respx mock httpx 范式）、`tests/test_setup_gate.py`（api_client/admin_user fixture）、`api/__tests__/setup.spec.ts`（vi.mock client）。

### Established Patterns
- 后端 async-first：adrf APIView async；ORM/同步 serializer 走 `await sync_to_async(...)`；异步 ORM `aupdate_or_create`/`aget`。
- 凭证一律密文落库（Fernet），错误一律脱敏；`logger` 不传 api_key/明文 config。
- 注释/文案中文（zh-CN）；Python `ruff format`（行宽 100，py314）。
- 前端文件路由 + `<route> meta.layout:false`；用户可见文案经 `t('setup.*')`；vee-validate + zod。

### Integration Points
- 后端：`system/views.py`（新增 `ProviderSetupWizardView`）+ `system/serializers.py`（新增 `ProviderSetupWizardSerializer`）+ `system/urls_providers.py`（新增 `setup-wizard/` path，置于 router.urls 前）+ `services/provider_health.py`（新增 `health_check_config`）。
- 前端：`pages/setup.vue`（两步）+ `components/setup/SetupProviderStep.vue`（新增）+ `lib/providerPresets.ts`（新增）+ `api/setup.ts`（新增 `setupProvider`）+ `locales/zh-CN.json`（新增文案）。
- 测试：`tests/test_provider_setup_wizard.py`（新增，PROV-01/04/05+SEC-02）+ 前端 `api/__tests__/setup.spec.ts` 扩展 + `lib/__tests__/providerPresets.spec.ts` + `components/setup` 组件测试。
</code_context>

<specifics>
## Specific Ideas

- DeepSeek/MiMo/Kimi 以 anthropic 兼容端点接入是既定决策：provider_type 恒为 `anthropic`，靠 `base_url` 覆盖 + 指定 model 区分（`AnthropicCredentialSchema` 支持 base_url 覆盖）。
- `_ping_anthropic` 走 `/v1/messages/count_tokens` 是兼容网关支持度最好的探活端点（优于 `/v1/models`，部分网关不暴露 models）。落库前健康校验用它。
- Claude Code 三档（opus/sonnet/haiku）在向导阶段统一映射到所选预设的同一 model（向导只配一个供应商；后续可在设置页细分）。
</specifics>

<deferred>
## Deferred Ideas

- 安全密钥（SECRET_KEY/FRIDAY_ENCRYPTION_KEY）健康校验与风险提示 → Phase 4（SEC-01）。
- 可选飞书集成步骤、可选向量检索（Qdrant/Embedding）步骤 → Phase 4。
- entrypoint 默认不再自动建号、保留运维命令、老部署不回退 → Phase 5（COMPAT-*）。
- 向导内多供应商/项目级凭证/逐模型手选、Claude Code 三档分别映射不同模型 → 后续设置页既有能力承载。
</deferred>
