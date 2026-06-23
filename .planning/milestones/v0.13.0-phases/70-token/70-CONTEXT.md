# Phase 70: access token / 密钥提供方重构（FK） - Context

**Gathered:** 2026-06-23
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous)

<domain>
## Phase Boundary

把仓库 access token 重构为可选——仓库可显式选「密钥提供方」（`GitInstanceCredential` FK）或填自有 token；建仓表单按 provider 拼接 URL 并失焦校验。复用既有 `GitInstanceCredential` 实例池 + `aresolve_git_token`。
</domain>

<decisions>
## Implementation Decisions

### TOKEN-01 解析优先级 + FK
- `Repository.git_instance_credential` FK（可空，`SET_NULL`，related_name=repositories）+ migration 0039。
- `resolve_git_token_sync` 优先级：per-repo `GitCredential` → 仓库 FK `git_instance_credential` → host 自动匹配 → None。老仓库（无 FK）零回归（FK 为空天然跳过）。
- FK 取标量 `git_instance_credential_id` 避免 async lazy-FK 访问。

### TOKEN-02 建仓 token 可选 + has_credential + TestConnection
- `RepositoryCreateSerializer.access_token` 改可选（`required=False, allow_blank=True`）+ 新增 `git_instance_credential_id`（可空 UUID）。
- `_acreate_repository_core`：无 token 时必须 FK 或 host 可解析（否则 fail-loud 400）；仅在填了自有 token 时建 per-repo `GitCredential`；FK 落库；base_branch 校验用 effective_token（FK/host 解密）。
- `has_credential` 反映 per-repo OR FK OR host 实例池可解析。
- `TestConnectionView`（新建路径）无 token 时按 FK/host fallback 解密实例池 token 校验。

### TOKEN-02 前端
- `CreateRepositoryModal`：token 改可选 + 新增「密钥提供方」select（加载 `gitInstanceCredentials.list`）；token 或 provider 任一即可；test/create 透传 `git_instance_credential_id`；URL/token/provider 变更防抖自动测连（失焦自动校验）。
- 全局凭证 admin 页加「按 provider + host 生效 + 解析优先级」用途说明。

### Claude's Discretion / 已知偏差
- 建仓表单「URL 拆段拼接（host 前缀只读 + group/repo 输入 + 固定 .git）」未做完整拆段 UI——保留单 URL 输入 + 防抖自动校验（失焦校验功能等价）；拆段拼接列为 UI 打磨 deferred（后端全支持）。
</decisions>

<code_context>
## Existing Code Insights
- `services/git_credentials.py` `resolve_git_token_sync`/`aresolve_git_token`/`_extract_git_host`（解析器单一入口）。
- `repositories/models.py` `Repository`/`GitInstanceCredential`/`GitCredential`。
- `repositories/views.py` `_acreate_repository_core`（Phase 69 抽取）/`TestConnectionView`；`repositories/serializers.py` `RepositoryCreateSerializer`/`RepositorySerializer.get_has_credential`。
- 前端 `CreateRepositoryModal.vue`、`api/gitInstanceCredentials.ts`、`pages/admin/git-credentials`。
</code_context>

<specifics>
## Specific Ideas
- 同 host 多仓库复用一份凭证（实例池），建仓免重复粘 token。
</specifics>

<deferred>
## Deferred Ideas
- 建仓表单 provider URL 拆段拼接 UI（host 前缀只读 + group/repo split input + .git 后缀）——UI 打磨，后端 + 自动校验已就绪。
</deferred>
