---
phase: 3
slug: llm-claude-code
status: complete
verified: 2026-06-08
gaps_found: 0
must_haves_met: 6
must_haves_total: 6
human_needed: 1
---

# Phase 3 — Verification (goal-backward)

**Goal:** 用户通过一键模型预设配好至少一个 Anthropic 兼容供应商，凭证经 Fernet 加密落库、
健康校验通过，并设为系统默认且绑定 Claude Code 运行配置。

**Status: COMPLETE** — 6/6 must-have 成功标准达成，0 gaps。

## Success Criteria

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | 从预设（DeepSeek V4 Pro / MiMo V2.5 Pro / Kimi 2.6 / Anthropic 官方 / 自定义）选择，base_url 与默认 model 自动填充，仅需填 API Key | ✅ MET | `lib/providerPresets.ts`（5 预设）+ `SetupProviderStep.vue` 选预设自动填充；测试 `providerPresets.spec.ts`、`SetupProviderStep.spec.ts`「selecting a preset auto-fills」 |
| 2 | 每个预设展示模型能力（上下文长度、是否多模态/图像） | ✅ MET | 预设含 `contextLength`/`supportsVision`；组件渲染能力 badge（上下文/图像/纯文本）；`SetupProviderStep.spec.ts`「renders the 5 model presets」 |
| 3 | 保存时执行连通/鉴权健康校验，失败给明确可操作提示 | ✅ MET | 后端落库前 `health_check_config` 探活；失败 400 + 「请检查 API Key…Base URL…」；测试 `test_health_fail_no_persist_actionable`、前端「shows backend actionable error」 |
| 4 | 凭证经现有 Fernet 加密路径以密文存入系统级 ProviderCredential | ✅ MET | `encrypt_value(json.dumps(cfg))` 落库；测试 `test_creates_encrypted_default_and_binds_claude_code` 断言密文 + `decrypt_value` 还原；SEC-02 |
| 5 | Anthropic 凭证被设为系统默认（is_default）并绑定 Claude Code（claude_code_config） | ✅ MET | 原子设 `is_default` + `aset_claude_code_config` 三档映射；测试断言 `is_default=True` + `CLAUDE_CODE_CONFIG` 写入 credential_id + opus/sonnet/haiku |
| SEC-02 | 写入凭证经 Fernet 密文存储 | ✅ MET | 同 #4；测试断言 encrypted_config 非明文 |

## Requirements coverage
- PROV-01 ✅（系统级 anthropic ProviderCredential，Fernet 加密）
- PROV-02 ✅（5 一键预设，自动填充 base_url + model）
- PROV-03 ✅（预设能力展示：上下文/多模态）
- PROV-04 ✅（健康校验 + 可操作中文提示，失败不落库）
- PROV-05 ✅（设系统默认 + 绑定 Claude Code）
- SEC-02 ✅（Fernet 密文）

## Reuse compliance（关键约束）
- ✅ 复用 `common.encryption.encrypt_value/decrypt_value`（Fernet 唯一入口）——未自建凭证存储。
- ✅ 复用 `services.provider_health` 健康校验（`_PING_DISPATCH`/`_ping_anthropic`/脱敏）。
- ✅ 复用 `services.provider_config.aset_claude_code_config` 绑定 Claude Code。
- ✅ 复用 `system.models.ProviderCredential` + `set_default` 原子语义 + DB 约束。
- ✅ 复用 `permissions.api_permissions.IsSuperUser`。
- ✅ 未回退 Phase 1 fail-closed 门禁 / Phase 2 管理员创建 + 自动登录（向导步骤走组件内部状态，不改路由守卫）。

## Tests
- Backend: `tests/test_provider_setup_wizard.py` → 7 passed；回归 `test_provider_health.py`+`test_setup_gate.py`+`test_provider_credential_api.py` → 47 passed。
- Frontend: `setup.spec.ts`(6) + `providerPresets.spec.ts`(5) + `SetupProviderStep.spec.ts`(5) → 16 passed。

## Human-needed (manual UAT — 1 项)
- **端到端浏览器真机流程 + 真实供应商 Key**：自动化测试以 respx/vi.mock 桩替代真实外呼。需人工在浏览器跑：全新部署 → 创建管理员（自动登录）→ 步骤 2 选预设 → 填真实 API Key → 健康校验通过 → 进入首页，并在设置页确认凭证密文落库 + is_default + Claude Code 绑定生效。（属 human_verify_mode=end-of-phase 既定人工项，非缺陷）

## Gaps
- 无。
