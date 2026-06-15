---
phase: 02-full-coverage
plan: 01
subsystem: accounts, access_tokens, system
tags: [audit, emit, coverage]
requires: [AUDIT-01, AUDIT-02, AUDIT-03]
provides: [COV-01, COV-07, COV-08]
key_files:
  created:
    - server/tests/audit/test_coverage_accounts.py
  modified:
    - server/accounts/views.py
    - server/access_tokens/views.py
    - server/system/views.py
    - server/system/setup_views.py
  not_modified:
    - server/audit/emitter.py
    - server/audit/models.py
decisions:
  - "Best-effort emit: all audit calls wrapped in try/except, never block the operation"
  - "Async views use aemit_audit_event(), sync views use emit_audit_event()"
  - "No sensitive data (passwords, api_keys) in before/after snapshots"
metrics:
  duration: "18min"
  completed: "2026-06-15"
  tasks: 2
  files: 5
  tests: 10
---

# Phase 2 Plan 01: accounts + access_tokens + system 审计覆盖 Summary

## One-liner
All user management, access token, system setting, and provider credential mutations emit audit events via best-effort calls.

## Coverage Delivered

### COV-01: 用户管理
| Action | View | Emit Point |
|--------|------|------------|
| `user.login` | LoginView.post | After successful token generation |
| `user.created` | SetupInitView.post | After superuser creation (actor_type=system) |
| `user.created` | InvitationAcceptView.post | After user creation from invitation |
| `user.invitation_created` | InvitationView.post | After invitation object creation |
| `user.updated` | UserDetailView.patch | After is_active change |
| `user.updated` | ProfileUpdateView.patch | After display_name update |
| `user.updated` | AdminProfileView.put | After admin profile update |
| `user.password_changed` | ChangePasswordView.post | After password save |
| `user.password_changed` | ForceChangePasswordView.post | After forced password save |
| `user.password_changed` | AdminChangePasswordView.post | After admin password change |

### COV-07: 访问令牌
| Action | View | Emit Point |
|--------|------|------------|
| `access_token.created` | AccessTokenViewSet.acreate | After token creation |
| `access_token.revoked` | AccessTokenViewSet.revoke | After first revocation (idempotent) |

### COV-08: 系统设置 + 供应商凭证
| Action | View | Emit Point |
|--------|------|------------|
| `system_setting.created` | SettingsListCreateView.post | After setting creation |
| `system_setting.updated` | SettingsDetailView.put | After setting update |
| `system_setting.deleted` | SettingsDetailView.delete | After setting deletion |
| `system_setting.updated` | SetupFeishuWizardView.post | After feishu config write |
| `system_setting.updated` | SetupRagWizardView.post | After RAG config write |
| `provider_credential.created` | ProviderCredentialViewSet.perform_acreate | After credential save |
| `provider_credential.updated` | ProviderCredentialViewSet.perform_aupdate | After credential update |
| `provider_credential.deleted` | ProviderCredentialViewSet.perform_adestroy | After credential delete |
| `provider_credential.toggled` | ProviderCredentialViewSet.toggle_active | After is_active toggle |
| `provider_credential.created` | ProviderSetupWizardView.post | After wizard credential creation |

## Tests
10 integration tests covering all mutation points. All pass.

## Deviations from Plan
None.
