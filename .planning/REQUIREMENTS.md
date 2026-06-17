# Requirements: Friday AI

**Defined:** 2026-06-17
**Core Value:** 让团队"开箱即用、安全地"把需求自动变成代码。
**Milestone:** v0.10.0 — 操作审计治理

> 横切治理能力——立起统一 `AuditEvent` 审计模型，对成员/凭证/飞书同步/仓库权限/排除规则/清理任务/API key 等敏感操作做不可篡改留痕，并提供查询/导出，使敏感操作可查、可追溯、可审计。系统管理员 = 现有 `is_superuser`（不新建角色）；审计为横切能力，各功能产生敏感操作时 emit，本里程碑统一收口 + 补齐覆盖 + UI；v0.5 既有分散埋点（`purge.started/completed` 结构化日志、`TriggerLog`/`ActionLog`）收口到统一表。设计底座：`ROADMAP-vNext.md §v0.10`、`DOMAIN-MODEL.md §11`（`AuditEvent` 横切治理）。PREFLIGHT 无映射 v0.10 的 blocking/should-fix 项。

## v1 Requirements

### 审计模型与 emit 地基（AUDIT）

- [x] **AUDIT-01**: 统一 `AuditEvent` 模型（actor / action / target_type / target_id / target_repr / before / after / source / occurred_at / metadata），落库经单一写入入口（service 收口，INV-6 精神），append-only 不可篡改——无 update/delete 业务路径，模型层守护
- [x] **AUDIT-02**: 统一 emit 机制（service helper / Django signal）以稳定 action taxonomy 记录审计事件，emit 失败 best-effort 不阻断主操作（fail-soft），凭证/密钥/明文 token 字段在审计记录中脱敏不落明文

### 敏感操作全量覆盖（AUDITCOV）

- [x] **AUDITCOV-01**: 身份与权限类操作 emit 审计——成员/用户增删改、用户启停、角色/权限变更、空间（Project）配置变更、仓库权限变更，记录 actor + 目标 + 前后值
- [x] **AUDITCOV-02**: 凭证与数据治理类操作 emit 审计——Provider 凭证 / Git 实例凭证 / 飞书凭证增删改、Agent API key / PAT 创建吊销、飞书同步、排除规则变更、清理任务（v0.5 既有排除/清理埋点收口到统一 `AuditEvent` 表）

### 审计查询与导出（AUDITUI）

- [x] **AUDITUI-01**: 审计查询 REST API——按 actor / action / target / 时间范围过滤 + 分页，superuser fail-closed 访问控制，记录对外只读（无创建/编辑/删除入口）
- [x] **AUDITUI-02**: 审计前端视图——列表 / 过滤 / 详情（before-after 对比）+ 导出（CSV/JSON）

## v2 Requirements

### 审计进阶（AUDITX）

- **AUDITX-01**: 审计日志密码学级防篡改（hash chain / WORM 存储），抵御 DB 直接篡改
- **AUDITX-02**: 实时告警 / SIEM 集成 / webhook 外发（敏感操作触发主动告警）
- **AUDITX-03**: 审计日志保留策略 / 归档 / 自动清理（按时间或容量）

## Out of Scope

| Feature | Reason |
|---------|--------|
| 新建独立审计角色 / 权限层（非 superuser 的审计查看角色） | 复用既有 `is_superuser`，不新建角色（与既有里程碑「系统管理员=superuser」决策一致） |
| 密码学级防篡改（hash chain / WORM） | 应用层 append-only（无 update/delete 业务路径）即满足「不可篡改」治理诉求；密码学防篡改成本高，留 v2（AUDITX-01） |
| 实时告警 / SIEM / 外部 webhook 外发 | 本里程碑聚焦「留痕 + 查询 + 导出」，主动告警是独立能力，留 v2（AUDITX-02） |
| 审计日志保留 / 归档 / 自动清理策略 | 先做全量留痕与查询，保留治理留 v2（AUDITX-03） |
| 读操作 / 普通业务操作的全量审计 | 审计聚焦敏感/管理操作；全量操作日志会产生噪音且与现有 `ActionLog`/structlog 重叠 |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| AUDIT-01 | Phase 53 | Complete |
| AUDIT-02 | Phase 53 | Complete |
| AUDITCOV-01 | Phase 54 | Complete |
| AUDITCOV-02 | Phase 54 | Complete |
| AUDITUI-01 | Phase 55 | Complete |
| AUDITUI-02 | Phase 55 | Complete |

**Coverage:**

- v1 requirements: 6 total
- Mapped to phases: 6
- Unmapped: 0 ✓

---
*Requirements defined: 2026-06-17 for milestone v0.10.0*
