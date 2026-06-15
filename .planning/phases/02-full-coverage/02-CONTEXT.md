# Phase 2 Context: 全量敏感操作 emit 覆盖

## 设计决策

### Emit 入口

- 使用 Phase 1 创建的 `emit_audit_event()` / `aemit_audit_event()` from `audit.emitter`
- 同步视图用 `emit_audit_event()`，异步视图用 `aemit_audit_event()`

### Action 命名规范

- 格式：`{resource}.{operation}`
- 统一 snake_case
- 示例：`user.created`, `provider_credential.deleted`, `exclusion_rule.accepted`

| 资源 | 操作 | Action |
|------|------|--------|
| user | created | `user.created` |
| user | updated | `user.updated` |
| user | password_changed | `user.password_changed` |
| user | login | `user.login` |
| access_token | created | `access_token.created` |
| access_token | revoked | `access_token.revoked` |
| system_setting | created | `system_setting.created` |
| system_setting | updated | `system_setting.updated` |
| system_setting | deleted | `system_setting.deleted` |
| provider_credential | created | `provider_credential.created` |
| provider_credential | updated | `provider_credential.updated` |
| provider_credential | deleted | `provider_credential.deleted` |
| git_credential | created | `git_credential.created` |
| git_credential | updated | `git_credential.updated` |
| git_credential | deleted | `git_credential.deleted` |
| repository | created | `repository.created` |
| repository | deleted | `repository.deleted` |
| exclusion_rule | created | `exclusion_rule.created` |
| exclusion_rule | accepted | `exclusion_rule.accepted` |
| cleanup | started | `cleanup.started` |
| feishu_sync | completed | `feishu_sync.completed` |

### Target Type

- 使用 Django model name（如 `User`, `ProviderCredential`, `GitInstanceCredential`）

### Before/After 快照

- before: `model_to_dict()` 或 `serializer.data`（变更前状态）
- after: 新值字典（变更后状态）
- 敏感字段（password, api_key, encrypted_token 等）不入快照

### Emit 时机

- 在 DB 操作成功 **之后** emit
- best-effort：emit 失败不阻塞主操作（`audit.emitter` 已内建 try/except）

### 测试策略

- 每个 emit 点写一个专门测试
- 测试执行真实操作，然后 assert AuditEvent 存在
- 验证 action / target_type / target_id 正确
