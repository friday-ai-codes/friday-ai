# Requirements: Friday AI — v0.1.0 首启初始化向导

**Defined:** 2026-06-07
**Core Value:** 让团队开箱即用、安全地完成首次登录与必备配置，从而把飞书需求自动跑成 PR。

## v1 Requirements

本里程碑（v0.1.0）的全部需求。每条映射到一个 roadmap 阶段。

### Setup 向导框架与门禁 (SETUP)

- [x] **SETUP-01**: 系统检测到不存在任何超级管理员时，用户首次访问 Web 自动进入首启初始化向导
- [x] **SETUP-02**: 后端提供只读「初始化状态」接口（如 `is_initialized`），前端路由守卫据此放行：未初始化时绕过登录进入向导，已初始化时禁止进入向导
- [x] **SETUP-03**: 向导完成（已创建管理员）后，初始化接口与界面对所有访问者关闭（403 或重定向到登录），不再出现
- [x] **SETUP-04**: 初始化接口 fail-closed 且具备防重入/并发保护——存在 superuser 时一律拒绝，无法用于重置或接管已有实例

### 管理员账号 (ADMIN)

- [ ] **ADMIN-01**: 用户在向导中自定义管理员用户名与密码，含密码强度校验与二次确认
- [ ] **ADMIN-02**: 提交后创建 superuser 并即时生效，用户可立即用该账号登录（不触发 must_change_password 强制改密）
- [ ] **ADMIN-03**: 创建管理员成功后自动建立登录会话，用户直接进入系统首页，无需再次登录

### LLM 供应商与模型预设 (PROV)

- [x] **PROV-01**: 用户在向导中配置至少一个 Anthropic 兼容 LLM 供应商凭证（Claude Code 必备），保存为系统级 `ProviderCredential`（Fernet 加密）
- [x] **PROV-02**: 向导提供一键模型预设：DeepSeek V4 Pro、MiMo V2.5 Pro、Kimi 2.6、Anthropic 官方、自定义兼容端点；预设自动填充 `base_url` 与默认 `model`，用户仅需填 API Key
- [x] **PROV-03**: 每个预设标注模型能力（上下文长度、是否多模态/图像），辅助用户选择
- [x] **PROV-04**: 保存供应商凭证时执行健康检查（连通/鉴权），失败给出明确可操作的提示
- [x] **PROV-05**: 向导自动将所配 Anthropic 凭证设为系统默认（`is_default`）并绑定 Claude Code 运行配置（`claude_code_config` 模型映射）

### 安全密钥校验 (SEC)

- [ ] **SEC-01**: 向导检测 `SECRET_KEY` / `FRIDAY_ENCRYPTION_KEY` 是否为安全值（非默认、相互独立），给出风险提示但不阻塞完成
- [x] **SEC-02**: 向导写入的所有凭证/密钥经现有 Fernet 加密路径落库，确保为密文存储

### 飞书集成（可选步骤）(FEISHU)

- [ ] **FEISHU-01**: 向导提供可选的飞书集成配置步骤（App ID / App Secret 等），用户可一键跳过
- [ ] **FEISHU-02**: 飞书配置写入与既有 `SystemSetting` / `bootstrap_system_settings` 路径一致，跳过后可在设置页补充

### 向量检索（可选步骤）(RAG)

- [ ] **RAG-01**: 向导提供可选的向量检索配置步骤（Qdrant URL/API Key、Embedding 配置），用户可一键跳过
- [ ] **RAG-02**: RAG 配置项与既有 `SettingKeys`（QDRANT_URL/EMBEDDING_* 等）对齐，跳过后可在设置页补充

### 向后兼容与迁移 (COMPAT)

- [ ] **COMPAT-01**: `server/entrypoint.sh` 默认不再调用 `init_superuser` 自动建管理员（改由向导承担）
- [ ] **COMPAT-02**: 保留 `init_superuser` 与 `reset_superuser_password` 管理命令作为运维兜底，命令行仍可手动建/重置管理员
- [ ] **COMPAT-03**: 已有部署（已存在 superuser）升级后不出现向导、行为不回退；全新部署才进入向导

## v2 Requirements

后续里程碑跟踪，不在当前 roadmap。

### 向导增强 (SETUPX)

- **SETUPX-01**: 向导内一键生成/校验基础设施密钥脚本联动（与 `scripts/setup.sh` 打通）
- **SETUPX-02**: 向导内 Git 平台默认凭证配置步骤
- **SETUPX-03**: 部署健康总览（runner 在线、DB/Redis/Qdrant 连通）作为向导收尾页

## Out of Scope

明确排除，防止范围蔓延。

| Feature | Reason |
|---------|--------|
| 多管理员 / 团队批量初始化 | 首启只建一个 superuser；成员管理走既有 `/admin/users` |
| 向导内配置 OIDC/SSO | 已有独立 OIDC 设置页；首启聚焦能进去 + 能跑 AI |
| 重写四层 Provider 解析逻辑 | 向导复用 `ProviderConfigService` / `ProviderCredential`，不改既有解析 |
| 把 SECRET_KEY 等基础设施密钥改为运行时 Web 设置 | 启动期 env 生命周期，向导仅做校验提示，不接管 |
| 向导主题/品牌化深度定制 | 复用既有设计系统与 i18n，不做可配置主题 |
| `FRIDAY_ADMIN_*` 环境变量自动建号并跳过向导 | 已选择保留命令作运维兜底；不引入会绕过向导的隐式 env 路径 |

## Traceability

阶段对需求的覆盖。roadmap 创建时填充。

| Requirement | Phase | Status |
|-------------|-------|--------|
| SETUP-01 | Phase 1 | Complete |
| SETUP-02 | Phase 1 | Complete (Plan 01-01) |
| SETUP-03 | Phase 1 | Complete (Plan 01-01) |
| SETUP-04 | Phase 1 | Complete (Plan 01-01) |
| ADMIN-01 | Phase 2 | Pending |
| ADMIN-02 | Phase 2 | Pending |
| ADMIN-03 | Phase 2 | Pending |
| PROV-01 | Phase 3 | Complete |
| PROV-02 | Phase 3 | Complete |
| PROV-03 | Phase 3 | Complete |
| PROV-04 | Phase 3 | Complete |
| PROV-05 | Phase 3 | Complete |
| SEC-01 | Phase 4 | Pending |
| SEC-02 | Phase 3 | Complete |
| FEISHU-01 | Phase 4 | Pending |
| FEISHU-02 | Phase 4 | Pending |
| RAG-01 | Phase 4 | Pending |
| RAG-02 | Phase 4 | Pending |
| COMPAT-01 | Phase 5 | Pending |
| COMPAT-02 | Phase 5 | Pending |
| COMPAT-03 | Phase 5 | Pending |

**Coverage:**

- v1 requirements: 21 total
- Mapped to phases: 21 ✓
- Unmapped: 0

---
*Requirements defined: 2026-06-07*
*Last updated: 2026-06-07 after initialization*
