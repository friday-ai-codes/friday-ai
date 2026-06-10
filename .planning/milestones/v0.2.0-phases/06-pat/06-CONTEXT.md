# Phase 6: PAT 模型增强与一次性明文 - Context

**Gathered:** 2026-06-09
**Status:** Ready for planning

<domain>
## Phase Boundary

在已有 `access_tokens` app（`AccessToken` 模型 + CookieJWT 管理 API + Vue 前端组件）基础上做增量增强，使其满足 PAT-01~PAT-06：

- 增加「备注」与「后缀指纹」两个维度，令牌列表可按前缀+后缀区分不同令牌。
- 创建「永不过期」令牌时给出非阻塞安全风险提示。
- 明文一次性展示（已具备）、按 owner 隔离（已具备）、软吊销（已具备）保持不变。

**不在本期**：令牌认证语义（Phase 7）、scope 细分、rotate/续期（v2）。本期纯模型/序列化/前端增量，不触碰认证链路。
</domain>

<decisions>
## Implementation Decisions

### 数据模型增强
- 新增 `note = models.CharField(max_length=500, blank=True, default="")` 可选备注字段。
- 新增 `token_suffix = models.CharField(max_length=8, default="")`，创建时存明文后 4 字符（与现有 `token_prefix` 对称）。
- 迁移只加列；历史 token 的 `token_suffix`/`note` 留空串（明文已丢无法回填），UI 对历史 token 仅展示 prefix。
- `AccessTokenSerializer` 新增 `note` + `token_suffix` 只读字段。

### 创建表单与安全提示
- 创建表单新增可选「备注」`Input`（≤500 字符）。
- 选择「永不过期」(never) 时，表单内 inline 非阻塞警告（icon + 黄色提示文案），不阻断提交。
- 备注本期仅创建时填写，不支持创建后编辑（不引入 PATCH）。
- 校验沿用 vee-validate + zod：name 必填 ≤200，note 可选 ≤500。

### 列表展示
- 列表新增「备注」列展示 note。
- 指纹展示格式 `friday_pat_xxx…abcd`（prefix + … + suffix）；无 suffix（历史 token）时仅展示 prefix。
- 时间列（创建/最后使用/过期）沿用现有展示，保持现状。
- 吊销交互保持现有确认弹窗 + revoke 流程。

### Claude's Discretion
- 警告文案具体措辞、备注列宽与截断、suffix 与 prefix 的具体 UI 排版，由实现时按既有组件风格决定。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- 后端：`server/access_tokens/models.py`（`AccessToken`、`generate_pat`、`PAT_PREFIX="friday_pat_"`、`token_prefix=plaintext[:12]`）、`serializers.py`（`AccessTokenSerializer` / `AccessTokenCreateSerializer`）、`views.py`（`AccessTokenViewSet`，`get_queryset` 强制 `created_by=request.user`，`acreate` 一次性返回明文，`revoke` action）。
- 哈希复用 `runners.models.hash_token`（sha256，contract 锁定）。
- 前端：`web/src/types/accessToken.ts`（DTO，过期三态语义）、`components/accessTokens/AccessTokenForm.vue`（vee-validate + zod，过期 Select 90d/never/custom）、`AccessTokenListTable.vue`、`AccessTokenRevealDialog.vue`、`AccessTokenSettings.vue`、`stores/accessTokens.ts`、`api/accessTokens.ts`。

### Established Patterns
- 后端 adrf 异步 ViewSet；序列化器只读字段严禁暴露 `token_hash`/明文。
- 前端表单仿 `ProviderCredentialForm` 的 FormField 结构；明文经 `AccessTokenRevealDialog` 瞬态展示。
- 过期三态：省略 expires_at→默认 90 天；显式 null→永不过期；ISO 字符串→自定义。

### Integration Points
- 新增 migration（`access_tokens/migrations/`）。
- DTO `AccessTokenDto` / `AccessTokenCreatePayload` 同步新增字段。
- 既有测试：`server/tests/test_access_tokens.py`、`test_no_plaintext_token_in_db.py`、前端 `__tests__/AccessTokenRevealDialog.spec.ts` 等需对应更新。
</code_context>

<specifics>
## Specific Ideas

- 指纹对齐 GitHub/GitLab PAT 习惯：前缀 `friday_pat_` 已具备，后缀补最后 4 位形成可区分指纹。
- 「永不过期」提示参照 GitHub 创建 classic PAT 时的非阻塞风险提示风格。
</specifics>

<deferred>
## Deferred Ideas

- 令牌 rotate / 续期、细粒度 scope、IP allowlist（v2：PATX-01~04）。
- 备注创建后编辑（PATCH）——本期不做。
</deferred>
