# Requirements: Friday AI — v0.10.0 操作审计治理

**Defined:** 2026-06-15
**Core Value:** 让团队"开箱即用、安全地"把需求自动变成代码

## v0.10 Requirements

本里程碑提交范围。每条映射到 roadmap 某个 phase。

### 基础：AuditEvent 模型 + emit 机制（AUDIT）

- [ ] **AUDIT-01**: 系统以统一 `AuditEvent` 模型记录审计事件，包含 actor（操作者）、action（操作类型）、target（目标对象类型+ID）、before（变更前快照）、after（变更后快照）、timestamp（事件时间）、source（来源：api/system/scheduler）
- [ ] **AUDIT-02**: 系统自动从请求上下文提取 actor 信息——JWT 用户（request.user）、PAT 所有者（AccessToken.owner）、系统/定时任务操作（system actor）
- [ ] **AUDIT-03**: 提供 `emit_audit_event()` 工具函数，各模块以统一方式写入审计事件（同步 + 异步双入口）
- [ ] **AUDIT-04**: AuditEvent 记录只追加（append-only），不提供 DELETE/PATCH API，确保审计日志不可篡改

### 覆盖面：全量敏感操作 emit 点（COV）

- [ ] **COV-01**: 用户管理操作产生审计记录（创建/更新/删除/启用/禁用用户，含 is_superuser 变更）
- [ ] **COV-02**: 供应商凭证操作产生审计记录（ProviderCredential 创建/更新/删除）
- [ ] **COV-03**: Git 实例凭证操作产生审计记录（GitInstanceCredential 创建/更新/删除）
- [ ] **COV-04**: 仓库配置变更产生审计记录（Repository 创建/删除/关键字段变更）
- [ ] **COV-05**: 排除规则变更产生审计记录（RepoExclusionRule 创建/更新/删除，含 AI 建议 accept/dismiss）
- [ ] **COV-06**: 清理任务产生审计记录（purge_file / run_cleanup / sensitive_purge，含 mode 和 match_count）
- [ ] **COV-07**: 访问令牌操作产生审计记录（AccessToken 创建/吊销）
- [ ] **COV-08**: 系统设置变更产生审计记录（SystemSetting 创建/更新，含 SettingKeys 敏感键）
- [ ] **COV-09**: 飞书同步操作产生审计记录（工作项同步/文档同步事件）

### 查询与导出：审计 UI（UI）

- [ ] **UI-01**: 管理员可通过审计 UI 按 actor（操作者）、action（操作类型）、target（目标）、时间范围过滤审计事件
- [ ] **UI-02**: 审计事件列表以分页表格展示，每行显示操作者、操作类型、目标、时间、变更摘要
- [ ] **UI-03**: 点击审计事件可查看详情，包含完整的 before-after 变更对比（JSON diff 高亮）
- [ ] **UI-04**: 审计事件支持 CSV 和 JSON 格式导出（尊重当前过滤条件）

## Out of Scope

明确排除，附理由，避免反复回炉。

| Feature | Reason |
|---------|--------|
| 审计日志自动过期/归档 | 后续里程碑按需引入，v0.10 只做全量记录 |
| 审计日志的访问权限细分 | v0.10 仅限 is_superuser 访问（沿用现有管理员角色模型） |
| 实时审计事件推送（WebSocket） | 非核心需求，后续按需引入 |
| 审计事件的 webhook 回调 | 属于 v0.11 开放协作范畴 |
| 新建管理员角色/权限层级 | 已确认沿用 is_superuser，不新建角色 |

## Traceability

哪个 phase 覆盖哪些需求。roadmap 创建时填充。

| Requirement | Phase | Status |
|-------------|-------|--------|
| AUDIT-01 | — | Pending |
| AUDIT-02 | — | Pending |
| AUDIT-03 | — | Pending |
| AUDIT-04 | — | Pending |
| COV-01 | — | Pending |
| COV-02 | — | Pending |
| COV-03 | — | Pending |
| COV-04 | — | Pending |
| COV-05 | — | Pending |
| COV-06 | — | Pending |
| COV-07 | — | Pending |
| COV-08 | — | Pending |
| COV-09 | — | Pending |
| UI-01 | — | Pending |
| UI-02 | — | Pending |
| UI-03 | — | Pending |
| UI-04 | — | Pending |

**Coverage:**
- v0.10 requirements: 17 total
- Mapped to phases: 0
- Unmapped: 17 ⚠️

---
*Requirements defined: 2026-06-15*
*Last updated: 2026-06-15 after initial definition*
