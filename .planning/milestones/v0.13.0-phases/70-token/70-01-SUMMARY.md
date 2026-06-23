---
phase: 70-token
plan: 01
subsystem: git-credentials
tags: [token, git-instance-credential, fk, optional-token, resolver]
requires:
  - phase: "26 (GitInstanceCredential 实例池 + aresolve_git_token)"
    provides: "实例凭证池 + 统一 token 解析器"
provides:
  - "Repository.git_instance_credential FK（密钥提供方）+ resolver 优先级 per-repo→FK→host→none"
  - "建仓 access_token 可选（FK/host fallback，fail-loud）"
  - "前端密钥提供方 select + 可选 token + admin 用途说明"
affects: [建仓, token 解析, TestConnection]
tech-stack:
  added: []
  patterns:
    - "token 解析优先级 per-repo → 仓库 FK → host 自动匹配 → none（FK 标量取，老仓库零回归）"
    - "建仓 token 可选：无 token 必须密钥提供方 FK/host 可解析，否则 fail-loud；仅自有 token 建 per-repo GitCredential"
key-files:
  created:
    - server/repositories/migrations/0039_repository_git_instance_credential.py
    - server/tests/repositories/test_token_provider_fk.py
  modified:
    - server/repositories/models.py
    - server/services/git_credentials.py
    - server/repositories/serializers.py
    - server/repositories/views.py
    - web/src/types/index.ts
    - web/src/api/repositories.ts
    - web/src/components/repository/CreateRepositoryModal.vue
    - web/src/pages/admin/git-credentials/index.vue
status: complete
---

# Phase 70 Plan 01 Summary — access token / 密钥提供方重构（FK）

- **TOKEN-01**：`Repository.git_instance_credential` FK（可空，`SET_NULL`，related_name=repositories）+ migration 0039；`resolve_git_token_sync` 优先级扩为 per-repo `GitCredential` → 仓库 FK 实例凭证 → host 自动匹配 → None（FK 标量 `git_instance_credential_id` 取，避免 async lazy-FK；FK 为空老仓库天然跳过零回归）。
- **TOKEN-02 后端**：`RepositoryCreateSerializer` `access_token` 改可选 + 新增 `git_instance_credential_id`；`_acreate_repository_core` 无 token 时校验 FK 或 host 可解析（否则 400 fail-loud），仅自有 token 才建 per-repo `GitCredential`，FK 落库，base_branch 校验用 effective_token（FK/host 解密）；`get_has_credential` 反映 per-repo/FK/host 可解析；`TestConnectionView` 新建路径无 token 时按 FK/host fallback 解密实例池 token 校验。
- **TOKEN-02 前端**：`CreateRepositoryModal` token 改可选（label「（可选）」+ 留空提示）+ 新增「密钥提供方（实例凭证）」select（`onMounted` 加载 `gitInstanceCredentials.list`）；`hasCredentialInput` = 有 token 或选了 provider；`canTest`/`validate` 放宽；test/create 透传 `git_instance_credential_id`（空串归一 undefined）；URL/token/provider 变更防抖自动测连（失焦自动校验）。全局凭证 admin 页加「按 provider + host 生效 + 解析优先级」用途说明。

## 已知偏差（deferred）
- 建仓表单「URL 拆段拼接（host 前缀只读 + group/repo 输入 + 固定 .git）」未做完整拆段 UI；保留单 URL 输入 + 防抖自动校验（失焦校验功能等价）。后端 + 自动校验已就绪，拆段拼接列为 UI 打磨 deferred。

## 验收
- `test_token_provider_fk.py` 9 例（resolver 4 优先级 + 建仓 FK/host/fail-loud + has_credential）；`test_repositories`/`test_batch_and_reindex`/`test_git_credential_*` 42+ 零回归；`makemigrations --check` 干净。
- 前端 eslint clean + git-credentials spec 零回归。
