# Phase 3 — Research

**Focus:** 落实「最大化复用既有 `ProviderConfigService`/`ProviderCredential`/Fernet/健康校验/Claude Code 绑定」的实现路径，确认无需重写既有系统。

## 关键发现（已读源码确认）

1. **权限天然满足**：Phase 2 后向导用户是已认证 superuser（`SetupInitView` 下发 cookie-JWT）。既有 `/api/providers/*` 全部 `IsSuperUser`/`IsAuthenticated` 端点可直接调用。

2. **凭证加密路径**：`system/serializers.py::ProviderCredentialCreateSerializer.create` 与本阶段编排端点共用
   `common.encryption.encrypt_value(json.dumps(config))` 写入 `ProviderCredential.encrypted_config`。`decrypt_value` 在 `get_decrypted_config()` 读回。**唯一加密入口，必须复用**。

3. **健康校验**：`services/provider_health.py`
   - `health_check(credential, override_model=...)` 对**已存库**凭证探活并 `aupdate` 三字段。
   - `_PING_DISPATCH[ProviderType.ANTHROPIC] = _ping_anthropic` → POST `/v1/messages/count_tokens`（兼容网关支持度最佳）。
   - 错误经 `_safe_error`→`redact_secrets_in_text` 脱敏。
   - **缺口**：无「落库前、无 DB 副作用」的无状态健康校验入口。→ 新增 `health_check_config(provider_type, cfg, model)`：构造未保存 `ProviderCredential` stub，复用 `_PING_DISPATCH` 探活，不调用 `aupdate`。

4. **Claude Code 绑定**：`services/provider_config.py::aset_claude_code_config(credential_id, model_mapping)`
   - 校验 credential 存在/active、provider_type==anthropic、三档 model ∈ `available_models`，写 `SystemSetting[CLAUDE_CODE_CONFIG]`（JSON）。
   - 向导把 opus/sonnet/haiku 三档统一映射到所选 model；available_models 含该 model → 校验通过。

5. **默认凭证**：`ProviderCredentialViewSet.set_default` 的原子语义（清零同维度其他 `is_default` 再置位）+ DB `uniq_default_provider_per_scope_type` 约束兜底。编排端点内联同一事务。

6. **能力归一化**：`system/serializers.py::_normalize_available_models` + `services/model_modalities.infer_model_modalities`（anthropic claude-* 推断 vision；deepseek 前缀 text-only；显式 `supports_vision` 优先）。预设可显式带 `supports_vision`/`context_length`。

7. **唯一约束**：`uniq_system_provider_credential (provider_type, name) where scope=system`。→ 编排端点用 `update_or_create((scope=system, provider_type=anthropic, name), defaults=...)` 保证重试幂等。

8. **前端复用**：`api/providerCredentials.ts`、`types/providerCredential.ts`（`AvailableModel`/`ClaudeCodeModelMapping`）。新增仅：`api/setup.ts::setupProvider`、`lib/providerPresets.ts`、`components/setup/SetupProviderStep.vue`、`setup.vue` 两步化、i18n。

## 测试范式
- 后端：`tests/test_provider_health.py` 用 `respx.mock` mock httpx；`_make_credential` helper；`@pytest.mark.django_db(transaction=True)` + `@pytest.mark.asyncio` 或 DRF `APIClient.force_authenticate`。
- 前端：`vi.mock('~/api/client')`；组件测试用 `@vue/test-utils` + happy-dom。

## 风险
- 预设 base_url/model 取值为各供应商 Anthropic 兼容端点的公开约定，可能随时间变化 → 字段**可编辑**纠错；健康校验失败给可操作提示。
- 落库前健康校验需真实外呼 → 测试用 respx mock；运行时 5s timeout（沿用 `HEALTH_CHECK_TIMEOUT_SECONDS`）。
