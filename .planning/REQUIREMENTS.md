# Requirements: Friday AI — v0.2.0 用户身份令牌与 Agent 工具打通

**Defined:** 2026-06-09
**Core Value:** 让每个用户用 GitHub/GitLab 风格的个人访问令牌，以"用户身份 + 用户权限"安全调用 Friday，并让 skill/mcp 工具以用户身份在容器内真正执行。

## v1 Requirements

本里程碑（v0.2.0）的全部需求。每条映射到一个 roadmap 阶段。

### 个人访问令牌 (PAT)

- [x] **PAT-01**: 用户可创建访问令牌，必填名称、可选备注，可选有效期（不填即永久）
- [x] **PAT-02**: 创建令牌时明文仅在创建响应中一次性展示且可复制，此后不可再获取（DB 仅存 sha256 hash，明文绝不落盘）
- [x] **PAT-03**: 令牌列表展示名称、备注、创建时间、最后使用时间、过期时间，并展示明文的前几位与后几位（前缀 + 后缀）以便区分不同令牌
- [x] **PAT-04**: 用户可删除（吊销）自己的令牌；系统不提供延期/续期（到期后只能新建）
- [x] **PAT-05**: 创建"永不过期"令牌时给出安全风险提示（非阻塞）
- [x] **PAT-06**: 用户只能查看/创建/删除属于自己的令牌，不能管理他人令牌

### 令牌即用户身份 (IDENT)

- [x] **IDENT-01**: 携带有效令牌的请求以令牌所有者身份被认证（`request.user` = owner），并施加该用户的 RBAC 权限（暂不做读写 scope 细分）
- [x] **IDENT-02**: 令牌认证按 `friday_pat_` 前缀闸门识别，PAT 与 JWT（同用 Bearer）互不吞掉，认证类顺序明确
- [x] **IDENT-03**: MCP/工具入口从 `AllowAny` 收紧为要求认证（fail-closed），匿名请求不可调用
- [x] **IDENT-04**: 令牌鉴权后审计链路保持不断（`request.auth` 仍为令牌实例，InteractionRun fingerprint 正常记录）
- [x] **IDENT-05**: 已吊销/已过期令牌一律被拒，不能用于任何用户身份调用

### 对话/会话用户隔离 (ISO)

- [x] **ISO-01**: 每个会话记录创建者（`Conversation.created_by`）；迁移时历史无主会话归属给最早的 superuser
- [ ] **ISO-02**: 普通用户在 AI 对话中只能查看/操作属于自己的会话（list / detail / runtime / stream / patch / delete / fork 等全路径按 owner 过滤）
- [ ] **ISO-03**: 管理员在 AI 对话界面默认也只看自己的会话（与普通用户行为一致）
- [ ] **ISO-04**: 越权访问他人会话（含 SSE/WebSocket 流式入口与对象级操作）返回 403/404，不泄漏会话存在性

### 管理员会话管理后台 (ADMVW)

- [ ] **ADMVW-01**: 管理员有一个专门的「会话管理」后台视图，可浏览所有用户的会话（区别于普通 AI 对话界面）
- [ ] **ADMVW-02**: 该后台视图为只读，管理员不能直接在他人会话上续聊/交互
- [ ] **ADMVW-03**: 管理员如需基于他人会话交互，可 fork 一份归属到自己名下后再进行

### MCP/skill 绑定用户令牌 (MCPB)

- [ ] **MCPB-01**: 用户可在 Friday 中把自己的某个访问令牌持久绑定给 skill/mcp 使用（绑定关系入库）
- [ ] **MCPB-02**: 被绑定的 skill/mcp 调用以该令牌所有者的身份与权限执行
- [ ] **MCPB-03**: 用户可查看并解除自己的绑定

### RemoteTool 链路接通 (RTOOL)

- [ ] **RTOOL-01**: 提供一个经令牌认证的 RemoteTool 执行端点（按工具 name 执行），供容器内 agent 回调调用
- [ ] **RTOOL-02**: task 容器消费 `remote_tools`，claude-agent-sdk 通过 SDK MCP server 真正加载并调用这些工具（含 builtin/mcp/skill）
- [ ] **RTOOL-03**: 用户令牌以直传 PAT 形态经 server→runner→task 注入容器，供 agent 以用户身份回调执行；日志/审计对令牌脱敏
- [ ] **RTOOL-04**: 任务运行中令牌被吊销时，在途任务继续跑完，仅阻断后续新调用（graceful）

## v2 Requirements

后续里程碑跟踪，不在当前 roadmap。

### 令牌增强 (PATX)

- **PATX-01**: 细粒度读写 scope / per-tool 权限
- **PATX-02**: 令牌 rotate / 续期（regenerate 新明文）
- **PATX-03**: IP allowlist / 使用次数与频率限额
- **PATX-04**: 注入容器改为短 TTL 派生凭证（broker token）+ tmpfs，替代直传 PAT

## Out of Scope

明确排除，防止范围蔓延。

| Feature | Reason |
|---------|--------|
| 令牌读写/资源 scope 细分 | 本期明确不做，令牌继承所有者全部 RBAC（与 GitLab 默认一致） |
| 令牌延期/续期 | 与 GitHub/GitLab 一致：到期只能新建，不延长既有令牌寿命 |
| 短 TTL 派生凭证注入容器 | 本期选直传 PAT + 脱敏；派生凭证留 v2（PATX-04） |
| 吊销中断在途任务 | 选 graceful：在途跑完仅阻断新调用，避免中断回滚复杂度 |
| OIDC/SSO token exchange | 已有独立 OIDC 设置；令牌体系聚焦 PAT |

## Traceability

阶段对需求的覆盖。roadmap 创建时填充。

| Requirement | Phase | Status |
|-------------|-------|--------|
| PAT-01 | Phase 6 | Complete |
| PAT-02 | Phase 6 | Complete |
| PAT-03 | Phase 6 | Complete |
| PAT-04 | Phase 6 | Complete |
| PAT-05 | Phase 6 | Complete |
| PAT-06 | Phase 6 | Complete |
| IDENT-01 | Phase 7 | Complete |
| IDENT-02 | Phase 7 | Complete |
| IDENT-03 | Phase 7 | Complete |
| IDENT-04 | Phase 7 | Complete |
| IDENT-05 | Phase 7 | Complete |
| ISO-01 | Phase 8 | Complete |
| ISO-02 | Phase 8 | Pending |
| ISO-03 | Phase 8 | Pending |
| ISO-04 | Phase 8 | Pending |
| ADMVW-01 | Phase 9 | Pending |
| ADMVW-02 | Phase 9 | Pending |
| ADMVW-03 | Phase 9 | Pending |
| MCPB-01 | Phase 10 | Pending |
| MCPB-02 | Phase 10 | Pending |
| MCPB-03 | Phase 10 | Pending |
| RTOOL-01 | Phase 10 | Pending |
| RTOOL-02 | Phase 11 | Pending |
| RTOOL-03 | Phase 11 | Pending |
| RTOOL-04 | Phase 11 | Pending |

**Coverage:**

- v1 requirements: 25 total
- Mapped to phases: 25 (Phase 6-11)
- Unmapped: 0 ✓

---
*Requirements defined: 2026-06-09*
