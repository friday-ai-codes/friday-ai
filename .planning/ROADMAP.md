# Roadmap: Friday AI — v0.1.0 首启初始化向导

## Overview

本里程碑用「首次访问引导用户自设账号」替代启动期自动建管理员，并在向导内一次配好必备能力。旅程从「全新部署被门禁正确导向向导」开始（SETUP），经「用户自设管理员并自动登录进入系统」（ADMIN）打通"能进去"闭环，再经「配好 Anthropic 兼容供应商并绑定 Claude Code」（PROV）打通"能跑 AI"闭环，随后补上「安全密钥校验 + 可选飞书/RAG 步骤」（SEC/FEISHU/RAG），最后以「入口迁移与向后兼容」（COMPAT）收尾，确保老部署升级不回退。所有阶段复用既有 `ProviderConfigService` / `ProviderCredential` / `SystemSetting` 与 Fernet 加密路径，不重写既有系统。

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: 向导门禁与初始化状态检测** - 全新部署被导向向导外壳，已初始化实例被 fail-closed 拒之门外 (completed 2026-06-08)
- [ ] **Phase 2: 管理员账号创建与自动登录** - 用户自设管理员账号，提交后即时创建并自动登录进入首页
- [ ] **Phase 3: LLM 供应商配置与 Claude Code 绑定** - 一键预设配好 Anthropic 兼容供应商，加密落库 + 健康校验 + 绑定 Claude Code
- [ ] **Phase 4: 安全校验与可选集成步骤** - 密钥安全风险提示 + 可跳过的飞书/向量检索配置步骤
- [ ] **Phase 5: 入口迁移与向后兼容** - entrypoint 不再自动建号，运维命令保留，老部署升级不回退

## Phase Details

### Phase 1: 向导门禁与初始化状态检测

**Goal**: 全新部署（无超级管理员）首次访问被自动导向首启向导外壳，已初始化实例则被拒之门外，初始化门禁 fail-closed 且防重入。
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: SETUP-01, SETUP-02, SETUP-03, SETUP-04
**Success Criteria** (what must be TRUE):

  1. 在无任何 superuser 的全新部署中，访问任意页面被自动重定向进入首启初始化向导
  2. 后端 `is_initialized` 只读接口可被前端无认证调用，前端路由守卫据此放行/拦截
  3. 系统一旦存在 superuser，初始化接口返回 403/重定向、向导界面不再出现
  4. 并发或重复请求初始化接口时，存在 superuser 即一律被拒绝，无法用于重置或接管已有实例

**Plans**: 2 plans
Plans:
**Wave 1**

- [x] 01-01-PLAN.md — 后端门禁层（SetupStatusView + SetupInitView + SetupNotInitialized + 后端测试）

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 01-02-PLAN.md — 前端路由守卫（api/setup.ts + auth store + i18n + router.beforeEach + setup.vue + 前端测试）

**UI hint**: yes

### Phase 2: 管理员账号创建与自动登录

**Goal**: 用户在向导中自定义管理员用户名与密码，提交后即时创建 superuser 并自动建立会话，直接进入系统首页。
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: ADMIN-01, ADMIN-02, ADMIN-03
**Success Criteria** (what must be TRUE):

  1. 用户在向导填写用户名 + 密码，含密码强度校验与二次确认后可提交
  2. 提交成功后系统创建 superuser 并即时生效，且不触发 must_change_password 强制改密
  3. 创建成功后自动建立登录会话，用户无需再次登录直接进入系统首页
  4. 该账号随后可正常用于登录，向导按 Phase 1 门禁逻辑对所有访问者关闭

**Plans**: 2 plans
Plans:
**Wave 1**

- [x] 02-01-PLAN.md — 后端增强（密码强度校验 + 创建后下发 cookie-JWT 会话 + 不强制改密 + 后端测试）

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 02-02-PLAN.md — 前端增强（auth store 会话 action + i18n + setup.vue 强度指示/校验/自动登录直达首页 + 前端测试）

**UI hint**: yes

### Phase 3: LLM 供应商配置与 Claude Code 绑定

**Goal**: 用户通过一键模型预设配好至少一个 Anthropic 兼容供应商，凭证经 Fernet 加密落库、健康校验通过，并设为系统默认且绑定 Claude Code 运行配置。
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: PROV-01, PROV-02, PROV-03, PROV-04, PROV-05, SEC-02
**Success Criteria** (what must be TRUE):

  1. 用户从预设（DeepSeek V4 Pro / MiMo V2.5 Pro / Kimi 2.6 / Anthropic 官方 / 自定义兼容端点）中选择，`base_url` 与默认 `model` 自动填充，仅需填 API Key
  2. 每个预设展示模型能力（上下文长度、是否多模态/图像）辅助用户选择
  3. 保存供应商凭证时执行连通/鉴权健康检查，失败给出明确可操作的提示
  4. 凭证经现有 Fernet 加密路径以密文存入系统级 `ProviderCredential`
  5. 所配 Anthropic 凭证被设为系统默认（`is_default`）并绑定 Claude Code 模型映射（`claude_code_config`）

**Plans**: TBD
**UI hint**: yes

### Phase 4: 安全校验与可选集成步骤

**Goal**: 向导对加密/安全密钥做健康校验与风险提示（不阻塞），并提供可一键跳过的飞书集成与向量检索配置步骤，写入与既有路径一致。
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: SEC-01, FEISHU-01, FEISHU-02, RAG-01, RAG-02
**Success Criteria** (what must be TRUE):

  1. 向导检测 `SECRET_KEY` / `FRIDAY_ENCRYPTION_KEY` 是否安全（非默认、相互独立），给出风险提示但不阻塞向导完成
  2. 用户可在向导中配置飞书集成（App ID / App Secret 等）或一键跳过，配置写入与既有 `SystemSetting` / `bootstrap_system_settings` 路径一致
  3. 用户可在向导中配置向量检索（Qdrant URL/Key、Embedding）或一键跳过，配置项与既有 `SettingKeys`（QDRANT_URL/EMBEDDING_*）对齐
  4. 跳过的可选步骤可稍后在既有设置页补充，不影响向导完成

**Plans**: TBD
**UI hint**: yes

### Phase 5: 入口迁移与向后兼容

**Goal**: entrypoint 默认不再自动建管理员（改由向导承担），保留运维兜底命令，已有部署升级后行为不回退、不出现向导。
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: COMPAT-01, COMPAT-02, COMPAT-03
**Success Criteria** (what must be TRUE):

  1. `server/entrypoint.sh` 默认不再调用 `init_superuser` 自动建管理员
  2. `init_superuser` 与 `reset_superuser_password` 命令保留，命令行仍可手动建/重置管理员
  3. 已存在 superuser 的部署升级后不出现向导、行为不回退
  4. 仅全新部署（无 superuser）升级后才进入首启向导

**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. 向导门禁与初始化状态检测 | 2/2 | Complete   | 2026-06-08 |
| 2. 管理员账号创建与自动登录 | 2/2 | Complete | 2026-06-08 |
| 3. LLM 供应商配置与 Claude Code 绑定 | 0/TBD | Not started | - |
| 4. 安全校验与可选集成步骤 | 0/TBD | Not started | - |
| 5. 入口迁移与向后兼容 | 0/TBD | Not started | - |
