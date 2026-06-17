# Phase 54: 敏感操作全量覆盖 emit — Research

**Researched:** 2026-06-17
**Phase goal:** 把 Phase 53 立起的 `AuditService.emit/aemit` 单一写入入口接线到既有各敏感/管理操作，产出全量审计记录；把 v0.5 既有分散 `purge` 埋点收口到统一 `AuditEvent`。
**Requirements:** AUDITCOV-01, AUDITCOV-02
**Question answered:** "What do I need to know to PLAN this phase well?"

---

## TL;DR — Plan-shaping conclusions

1. **几乎全部接线点是 adrf async view（`request.user` 现成）→ 用 `aemit`**。后端写操作绝大多数在 view 层（`acreate` / `perform_a*` / `@action` / async `post/patch/delete`），ORM 走 `await *.objects.acreate` 或 `sync_to_async(serializer.save)`，多为 **autocommit**（无显式 `transaction.atomic`）。少数显式 atomic 块（`accounts/views.py:_atomic_create_superuser`、`system/views.py:_set_default_atomic`）需 `on_commit`。
2. **actor 传递：在 view 层 service/ORM 成功后就地 `await AuditService.aemit(actor=request.user, ...)`** —— 不必新增 service 参数。理由见 §3：这些敏感操作本就在 view 内完成（薄 service 或无 service），与 INV-6 领域 service（`WorkItemService` 等）不同，view 即操作真正落库处。`ProviderCredentialViewSet` 已有 `perform_acreate/aupdate/adestroy` 钩子，是天然 emit 落点。
3. **taxonomy 词表已全覆盖** SC-1/SC-2 —— 15 个 `ACTION_*` + `RESERVED_ACTIONS`（purge）。**唯一需新增常量**：仓库与空间的关联/解绑（`SpaceViewSet.link/unlink_repository`）若纳入「仓库权限变更」，复用既有 `ACTION_REPOSITORY_PERMISSION_CHANGED` 即可，**无需新常量**。本研究未发现任何 SC 覆盖点缺常量。
4. **purge 收口最干净的落点 = `services/purge_reconcile.py:349 log_purge_event`**：在该函数体内（保留既有 `logger.info`）追加 `AuditService.emit(action=ACTION_PURGE_*, ...)`，三处调用点（:239/:253/:304）零改动自动收口。
5. **`emit` 的 fail-soft + savepoint 兜底已在入口内**（Phase 53），接线侧**不需**再裹 try/except；只需保证「主操作成功后才 emit」+ autocommit 直接 `aemit` / atomic 块用 `on_commit`。
6. **凭证字段绝不进 before/after 明文**：接线侧只传非敏感标识（`provider_type`/`scope`/`host`/`name`/`has_token` 布尔 / `token_prefix`），入口 `_redact_audit_payload` 是纵深防御兜底，不是放任传明文。
7. **建议拆 2 个 PLAN**（§7）：54-01 身份/权限类（accounts + projects/members + 空间配置 + 仓库权限），54-02 凭证/数据治理类（provider/git/feishu 凭证 + PAT + 飞书同步 + 排除规则 + purge 收口）。

---

## 1. EMIT WIRING MAP（核心交付）

> 约定：**source** 取值沿用 Phase 53 字段语义 —— `api`（Web/REST 带 actor）、`feishu_webhook`（飞书回调无 actor）、`scheduler`（apscheduler 后台）。所有路径均为 **DB-mutating** → 主操作成功后 emit；autocommit 路径直接 `await aemit(...)`，显式 `transaction.atomic` 块内用 `transaction.on_commit(lambda: AuditService.emit(...))`。

### SC-1 — 身份与权限类

| # | 操作 | 文件:行（成功落库点） | sync/async | action 常量 | target_type / target_id / target_repr | before / after | tx |
|---|------|----------------------|------------|-------------|----------------------------------------|----------------|----|
| 1 | 邀请注册建用户 | `accounts/views.py:290` `InvitationAcceptView.post`（`User.objects.create_user`）| async（autocommit）| `ACTION_MEMBER_CREATED` | `user` / `user.id` / `username` | after `{username, source, email}` | 直接 aemit |
| 2 | 首启建 superuser | `accounts/views.py:487` `_atomic_create_superuser`（`create_superuser`，包在 `transaction.atomic()`）| sync（在 `sync_to_async` 块内，view `accounts/views.py:520` 调用）| `ACTION_MEMBER_CREATED` | `user` / `user.id` / `username` | after `{username, source:"system", is_superuser:true}` | **on_commit**（atomic 块内）|
| 3 | 用户启停 | `accounts/views.py:329-331` `UserDetailView.patch`（`is_active` → `asave`）| async（autocommit）| `is_active` 真→`ACTION_USER_ACTIVATED` / 假→`ACTION_USER_DEACTIVATED` | `user` / `user_id` / `target_user.username` | before `{is_active:旧}` / after `{is_active:新}` | 直接 aemit（仅当值真正变更时 emit，避免噪音）|
| 4 | 管理员改用户名/资料 | `accounts/views.py:405` `AdminProfileView.put`（`user.asave()`）| async | `ACTION_MEMBER_UPDATED` | `user` / `user.id` / `username` | diff `{username/display_name 前后}` | 直接 aemit |
| 5 | 添加空间成员 | `projects/members_views.py:82` `SpaceMemberListView.post`（`ProjectMembership.objects.create`）| async | `ACTION_MEMBER_CREATED` | `member`（或 `project_membership`）/ `membership.id` / `f"{user} @ {project}"` | after `{user_id, project_id, role}` | 直接 aemit（`sync_to_async(create)` 后）|
| 6 | 变更成员角色 | `projects/members_views.py:131` `SpaceMemberDetailView.patch`（`membership.save(update_fields=["role"])`）| async | `ACTION_ROLE_CHANGED` | `member` / `membership.id` / `f"{user} @ {project}"` | before `{role:旧}` / after `{role:新}`（须在 save 前读旧 role）| 直接 aemit |
| 7 | 移除空间成员 | `projects/members_views.py:151` `SpaceMemberDetailView.delete`（`membership.delete()`）| async | `ACTION_MEMBER_DELETED` | `member` / `membership.id` / `f"{user} @ {project}"` | before `{user_id, project_id, role}`（删前快照）| 直接 aemit（delete 后）|
| 8 | 空间配置变更（飞书插件/IM/Doc/webhook token）| `projects/views.py:170/178`（feishu_config PUT/DELETE）、`:338/345`（feishu_im PUT/DELETE）、`:436`（feishu_doc PUT）、`:268`（refresh_webhook_token）、`:301`（update_webhook_token）| async | `ACTION_PROJECT_CONFIG_CHANGED`（凭证型也可视作 `ACTION_CREDENTIAL_*`，见 §2 决策点）| `project` / `project.id` / `project.name` | 变更字段名集合（如 `{changed:["feishu_plugin_id"], has_secret:true}`）；**绝不**记 `feishu_plugin_secret_encrypted` / `feishu_app_secret_encrypted` / webhook token 明文 | 直接 aemit |
| 9 | 仓库权限级别变更 | `projects/views.py:675` `SpaceRepositoryDetailView.patch`（`link.asave(update_fields=["permission_level"])`）| async | `ACTION_REPOSITORY_PERMISSION_CHANGED` | `repository` 或 `project_repository` / `link.id` / `f"{repo} @ {project}"` | before `{permission_level:旧}` / after `{permission_level:新}` | 直接 aemit |
| 10 | 仓库关联/解绑空间（**决策点**）| `projects/views.py:120` link / `:138` unlink / `:618` 批量 link / `:688` `SpaceRepositoryDetailView.delete` | async | `ACTION_REPOSITORY_PERMISSION_CHANGED`（复用）| `project_repository` / link.id / repr | after/before `{repo_id, project_id}` | 直接 aemit |

### SC-2 — 凭证与数据治理类

| # | 操作 | 文件:行 | sync/async | action 常量 | target / before-after / 脱敏要点 | tx |
|---|------|---------|------------|-------------|----------------------------------|----|
| 11 | Provider 凭证创建 | `system/views.py:346` `ProviderCredentialViewSet.perform_acreate`（`sync_to_async(serializer.save)` 后，已有 `provider_credential_created` 日志）| async | `ACTION_CREDENTIAL_CREATED` | `provider_credential` / `serializer.instance.id` / `f"{provider_type}:{name}"`；after 只记 `{provider_type, scope, scope_id, name}`，**绝不**记 `encrypted_config`/`api_key` | 直接 aemit |
| 12 | Provider 凭证更新 | `system/views.py:427` `perform_aupdate` | async | `ACTION_CREDENTIAL_UPDATED` | `provider_credential` / `instance.id` / repr；记变更字段名集合（不含密文）| 直接 aemit |
| 13 | Provider 凭证删除（硬删）| `system/views.py:437` `perform_adestroy` | async | `ACTION_CREDENTIAL_DELETED` | `provider_credential` / `credential_id` / repr；before 删前非敏感快照 | 直接 aemit（delete 后）|
| 14 | Provider 凭证软禁用 toggle | `system/views.py:460` `toggle_active` | async | `ACTION_CREDENTIAL_UPDATED` | before/after `{is_active}` | 直接 aemit |
| 15 | Provider 设默认 | `system/views.py:487` `_set_default_atomic`（`transaction.atomic()` 块）| sync（`sync_to_async`）| `ACTION_CREDENTIAL_UPDATED` | after `{is_default:true, scope, provider_type}` | **on_commit** |
| 16 | Git 实例凭证创建 | `repositories/views.py:1175` `GitInstanceCredentialsView.post`（`GitInstanceCredential.objects.acreate`，已有 `git_instance_credential_created` 日志）| async | `ACTION_CREDENTIAL_CREATED` | `git_instance_credential` / `credential.id` / `host`；after `{host, provider, has_token:true}`，**绝不**记 `encrypted_token` | 直接 aemit |
| 17 | Git 实例凭证更新 | `repositories/views.py:1254` `GitInstanceCredentialDetailView._update`（`credential.asave()`）| async | `ACTION_CREDENTIAL_UPDATED` | after `{host, provider, token_changed:bool}` | 直接 aemit |
| 18 | Git 实例凭证删除 | `repositories/views.py:1275` `...DetailView.delete`（`credential.adelete()`）| async | `ACTION_CREDENTIAL_DELETED` | before `{host, provider}` | 直接 aemit |
| 19 | per-repo Git 凭证设置/更新 | `projects/views.py:478`（建仓时建凭证）、`:539/:543` `SetAccessTokenView.post`（create/update）、`projects/views.py:505` `RepositoryViewSet.credential` DELETE | async | `ACTION_CREDENTIAL_*` | `git_credential` / repo.id / repo repr；after `{has_token:true, git_user_name}`，**绝不**记 `encrypted_token` | 直接 aemit |
| 20 | Agent API key（PAT）创建 | `access_tokens/views.py:60` `AccessTokenViewSet.acreate`（`AccessToken.objects.acreate`）| async | `ACTION_PAT_CREATED` | `pat` / `token.id` / `token.name`；after `{name, token_prefix, token_suffix, expires_at}`，**绝不**记明文 / `token_hash` | 直接 aemit |
| 21 | Agent API key（PAT）吊销 | `access_tokens/views.py:84` `revoke`（仅首次 `revoked_at` 写入时）| async | `ACTION_PAT_REVOKED` | `pat` / `token.id` / `token.name`；after `{revoked_at}`（幂等：仅 `token.revoked_at is None` 分支 emit，避免重复 revoke 噪音）| 直接 aemit |
| 22 | 飞书同步触发（手动重试）| `feishu/views.py:1422` `TriggerLogRetryView.post`（重新派发 webhook）| async（有 `request.user`）| `ACTION_FEISHU_SYNC_TRIGGERED` | `trigger_log` / `original_log_id` / event_type；metadata `{event_type, source:"api"}` | 直接 aemit |
| 23 | 飞书同步触发（webhook 自动，**决策点**）| `feishu/views.py:540` `FeishuWebhookView.post` 派发成功点（`_dispatch_to_workflows` `feishu/views.py:691`）| async（**无 human actor**，`AllowAny`）| `ACTION_FEISHU_SYNC_TRIGGERED` | `trigger_log` / log.id / event_type；actor=None，source=`feishu_webhook` | 直接 aemit（见 §2 决策：建议纳入但 actor=None）|
| 24 | 排除规则新增 | `repositories/views.py:1082` `RepositoryExclusionRulesView.post`（`RepoExclusionRule.objects.acreate`）| async | `ACTION_EXCLUSION_RULE_CHANGED` | `repo_exclusion_rule` / `rule.id` / `f"{repo}:{pattern}"`；after `{pattern, rule_type, enabled, source}` | 直接 aemit |
| 25 | 排除规则删除 | `repositories/views.py:1118` `RepositoryExclusionRuleDetailView.delete`（`rule.adelete()`）| async | `ACTION_EXCLUSION_RULE_CHANGED` | `repo_exclusion_rule` / rule_id / repr；before `{pattern, rule_type}` | 直接 aemit |

### SC-3 — v0.5 既有 purge 埋点收口

| # | 操作 | 文件:行 | sync/async | action 常量 | 收口方式 |
|---|------|---------|------------|-------------|----------|
| 26 | purge 收口（单点）| `services/purge_reconcile.py:349` `log_purge_event`（被 `:239`/`:253`/`:304` 调用）| **sync 函数**（从 async `run_cleanup` 调用）| `RESERVED_ACTIONS` → `"purge.started"` / `"purge.completed"`（建议在 taxonomy 提升为 `ACTION_PURGE_STARTED`/`ACTION_PURGE_COMPLETED` 常量并纳入 `ALL_ACTIONS`，见 §2）| 在 `log_purge_event` 体内**保留** `logger.info(event,...)`，**追加** `AuditService.emit(action=..., target_type="repository", target_id=repository_id, metadata={mode, match_count, failures}, source="scheduler")`。三处调用点零改动。actor 通常为 None（清理多由调度/对账触发；若有 API 触发面可后续下传 actor）。fail-soft 已在入口，不破坏既有清理流程。|

> **收口注意**：`log_purge_event` 是 sync 函数，且从 async `run_cleanup`（已在 `sync_to_async` ORM 语境外）调用。直接调 `AuditService.emit`（sync）即可——它内部 `transaction.atomic()` 自建 savepoint/独立事务，fail-soft。**不要**在此用 `aemit`（会引入不必要 event-loop 依赖）。

---

## 2. action 常量缺口分析 + 决策点

- **无缺口**：SC-1..SC-3 的 25 个覆盖点全部命中 `taxonomy.py:45-61` 既有常量，purge 命中 `RESERVED_ACTIONS`。
- **建议（非阻断）**：把 `RESERVED_ACTIONS` 的 `"purge.started"`/`"purge.completed"` 提升为 `Final[str]` 具名常量 `ACTION_PURGE_STARTED`/`ACTION_PURGE_COMPLETED`，从 `RESERVED_ACTIONS` 移入 `ALL_ACTIONS`（Phase 54 是其接线 phase，taxonomy docstring 已预告「Phase 54 接线」）。这样消除字符串字面量，与 INV-2 命名守护一致。
- **决策点 A（飞书 webhook 自动同步，#23）**：`FeishuWebhookView` 无 human actor（`AllowAny`）。建议**纳入**（飞书同步是 SC-2 明列覆盖点），emit 时 `actor=None` + `source="feishu_webhook"`，仅在 `_dispatch_to_workflows` 成功（真正触发了工作流同步）处 emit 一次，避免对每个忽略/重复/校验事件 emit 造成噪音（SC-4）。若 planner 认为 webhook 量大有性能顾虑，可只保留手动 `TriggerLogRetryView`（#22）作为 SC-2「飞书同步操作」最小覆盖。
- **决策点 B（空间配置 vs 凭证，#8）**：飞书 plugin/IM secret 既是「空间配置变更」也是「凭证变更」。建议：飞书凭证型字段（plugin_secret/app_secret）用 `ACTION_CREDENTIAL_*`，纯配置字段（webhook token / doc folder）用 `ACTION_PROJECT_CONFIG_CHANGED`。或统一 `ACTION_PROJECT_CONFIG_CHANGED` + metadata 标注子类型 —— 由 planner 定，词表都已存在。

---

## 3. actor 传递架构建议（reuse INV-6 范式）

观察既有 INV-6 service（`WorkItemService`/`TechnicalPlanService`/`DocumentService`）：它们是**领域写收口 service**，view 调它们完成业务写。但 **Phase 54 的敏感操作几乎都在 view 层直接完成写**（薄 service 或纯 ORM）：
- `ProviderCredentialViewSet` 有 `perform_acreate/aupdate/adestroy` 钩子 → 天然 emit 落点，`self.request.user` 现成。
- members/exclusion/git-instance/PAT/feishu 等都是 async view 内 `await *.objects.a*` 或 `sync_to_async(serializer.save)`，`request.user` 现成。
- `provider_config.py` / `git_credentials.py` / `exclusion.py` 是**解析/读取** service，不是写收口；**写**发生在 view。`purge_reconcile.py` 是唯一「service 内完成写」的场景，其 emit 收口在 `log_purge_event`（无 actor，调度触发）。

**推荐：在 view 层 service/ORM 成功后就地 `await AuditService.aemit(actor=request.user, ...)`（CONTEXT「view 层无 service 的简单 CRUD 可在 view 内 service 调用成功后 emit」）。** 不新增 service 参数下传 actor —— 这些路径没有需要改签名的领域 service，view 即操作真正落库处。`actor.id`/`actor.username` 的访问由 `aemit`→`sync_to_async(emit)` 内部完成（Phase 53 已保证 async 安全），传 `User` 实例即可。

**helper 取舍（CONTEXT 倾向直接调用）**：直接调 `AuditService.emit/aemit` + 各自 `on_commit`/autocommit 判断，**不抽 helper**。理由：(1) before/after 字段每点不同，helper 难以通用且会掩盖「传了哪些字段」的评审可见性；(2) Phase 53 入口已收口脱敏/fail-soft/savepoint，样板已极薄（一次 `await aemit(...)`）；(3) INV-6 grep 守护要求 emit 显式经 `AuditService`，薄 helper 反而多一层间接。CONTEXT specifics 已明确「lean toward direct calls + on_commit」。

---

## 4. 事务边界（on_commit vs 直接 emit）

- **autocommit 路径（绝大多数 async view）**：`await *.objects.acreate(...)` / `await instance.asave()` 每语句即提交，无外层 atomic。主操作 `await` 完成即已提交 → 直接 `await AuditService.aemit(...)`。**无需 on_commit**（autocommit 下 `transaction.on_commit` 回调会立即同步执行，反而在 async 上下文需 `sync_to_async` 包裹，徒增复杂度）。CONTEXT：「autocommit 路径直接 emit」。
- **显式 `transaction.atomic` 块**：仅 2 处 —— `accounts/views.py:487 _atomic_create_superuser`、`system/views.py:491 _set_default_atomic`（均在 `sync_to_async` 同步块内）。这两处在 atomic 块内用 `transaction.on_commit(lambda: AuditService.emit(...))`（sync `emit`），确保只记真正提交的事实。
- **硬性评审项（Phase 53 docstring + CONTEXT specifics）**：任何 DB-mutating 路径若处于 `transaction.atomic` 内，必须 `on_commit`；接线评审把此列为 checklist。
- **purge（#26）**：`log_purge_event` 调用时 `run_cleanup` 的各步 ORM 已 `await` 完成（autocommit），直接 sync `emit` 即可。

---

## 5. Validation Architecture（pytest，落 `server/tests/audit/`）

全部后端 pytest，无需真实容器/外部系统。复用既有 `server/tests/audit/` 目录（已有 `test_audit_service.py` 等 7 个）。新增按区域分文件，如 `test_emit_identity.py` / `test_emit_credentials.py` / `test_emit_purge_consolidation.py`。

### SC-1 可验证性
- **行落库断言**：调用对应 async view（用 `adrf`/DRF async test client 或直接 await view method + mock request.user），断言 `AuditEvent.objects.filter(action=ACTION_*, actor_id=user.id, target_type=..., target_id=...).aexists()`；断言 `before`/`after` 字段内容正确（角色变更断言 `before["role"]!=after["role"]`）。
- **actor 正确性**：断言 `actor_id == request.user.id`、`actor_repr` 含 username。
- **启停分支**：`is_active` true→断言 `user.activated`，false→`user.deactivated`；值未变更时断言**无** AuditEvent（避免噪音）。
- **delete 前快照**：成员/凭证删除后断言 `before` 含删前关键字段（删后对象已不存在仍可追溯）。

### SC-2 可验证性
- **凭证脱敏 DB 断言**（核心）：创建 Provider/Git/feishu/PAT 凭证后 `AuditEvent.objects.aget(...)`，断言 `json.dumps(event.before)+json.dumps(event.after)` 中**不含**明文 `api_key`/`access_token`/`app_secret`/PAT 明文 / `encrypted_config` 密文；断言只含 `provider_type`/`host`/`name`/`has_token` 等非敏感标识。这同时验证「接线侧只传非敏感字段」+「入口脱敏兜底」两道防线。
- **PAT 幂等**：重复 `revoke` 同一 token，断言只产生 1 条 `pat.revoked`（仅首次 `revoked_at is None` 分支 emit）。
- **飞书同步**：调 `TriggerLogRetryView` 断言产 `feishu_sync.triggered`（actor=request.user, source="api"）；若纳入 webhook（#23），构造 webhook payload 断言 emit 时 `actor_id is None`、`source=="feishu_webhook"`。

### SC-3（purge 收口）可验证性
- **收口断言**：调 `services.purge_reconcile.run_cleanup(repo_id)`（mock `purge_file`），断言 `log_purge_event` 既保留 `logger.info`（structlog capture / caplog 断言 `purge.started`/`purge.completed` 事件仍发出），又产生 2 条 `AuditEvent`（started + completed），`target_type="repository"`、`metadata` 含 `mode`/`match_count`。
- **不破坏既有日志**：断言既有 `test_purge_reconcile.py` 仍全绿（收口是「补 emit」非重写）。

### SC-4（无噪音边界）可验证性
- **读操作无审计**：调 list/detail/get（`ProviderCredentialViewSet.list`、`SpaceMemberListView.get`、`RepositoryExclusionRulesView.get`、`AccessTokenViewSet.list`、检索/对话/索引接口样例）后断言 `AuditEvent.objects.count() == 0`。
- **普通业务无审计**：调一个非敏感写（如 profile `display_name` 自助更新 `ProfileUpdateView` —— 属个人资料非管理操作，**刻意不 emit**）断言无审计行。明确「刻意跳过」清单：登录/登出/刷新 token、自助改密、`Me`/dashboard/health 读、检索/RAG/对话/索引、workflow 普通节点执行、repo 状态轮询。
- **INV-6 守护沿用**：`test_audit_inv6_guard.py` 已存在且自动覆盖新接线（新代码仍只经 `AuditService`，旁路写表立即 fail）。新接线**不得**新增旁路 `AuditEvent.objects.create`。

---

## 6. 风险清单（接线必查）

1. **double-emit**：`ProviderCredentialViewSet` 的 `perform_a*` 与可能的 `@action`（toggle/set_default/refresh-models）若都 emit 同一逻辑变更，会重复记录。对策：每个语义动作只在一处 emit；`refresh-models`（拉模型列表）属普通运维**不 emit**（非凭证内容变更，SC-4 噪音）。
2. **emit before commit**：在 `_atomic_create_superuser`/`_set_default_atomic` 的 atomic 块内若直接 emit 而非 on_commit，事务回滚仍留审计行（记了未发生的事实）。对策：atomic 块内一律 `on_commit`。
3. **async actor lazy-FK**：传 `request.user` 给 `aemit` 安全（字段访问在 `sync_to_async(emit)` 内）；但**禁止**在 async view 里先 `request.user.username`（若 user 是 lazy）再拼 repr 传入 —— 交给入口取。`accounts`/`projects` 的 `request.user` 已是物化 User（认证中间件解析），低风险，仍以传实例为准。
4. **on_commit 性能**：autocommit 路径直接 emit，不堆 on_commit 钩子；atomic 仅 2 处，钩子量极小，无性能顾虑。
5. **不破坏既有 purge 结构化日志**：`log_purge_event` 收口必须**保留** `logger.info(event,...)`（下游可能依赖 structlog 事件名 `purge.started`/`purge.completed`）。emit 是**追加**，且 fail-soft 不阻断清理。
6. **before/after 读取时机**：update/role-change/permission-change 必须在 `save` **前**读旧值（如 `members_views.py:130` 改 role 前先存 `old_role`），否则 before==after。
7. **webhook 量级噪音（决策 A）**：若纳入 webhook 自动同步 emit，务必只在「真正派发工作流成功」点 emit 一次，不对 url_verification/duplicate/ignored 事件 emit。
8. **feishu 凭证字段名脱敏覆盖**：`feishu_plugin_secret_encrypted`/`feishu_app_secret_encrypted` 含 `secret` 段，入口 key-name 命中会脱敏；但接线侧仍**只传字段名集合 + has_secret 布尔**，不传字段值（双重保险）。

---

## 7. 建议 Plan 拆分（按区域，各自可评审）

**54-01 — 身份/权限 emit（SC-1）**
- accounts：建用户（#1/#2）、启停（#3）、管理员改资料（#4）
- projects/members：成员增删改 + 角色变更（#5/#6/#7）
- projects：空间配置变更（#8）、仓库权限/关联（#9/#10）
- 测试：`test_emit_identity.py`（含 SC-4 读无审计的身份侧样例）
- 改动面：`accounts/views.py`、`projects/members_views.py`、`projects/views.py`

**54-02 — 凭证/数据治理 emit + purge 收口（SC-2/SC-3）**
- provider 凭证 CRUD + toggle/set_default（#11–#15）
- git 实例凭证 + per-repo git 凭证（#16–#19）
- PAT 创建/吊销（#20/#21）
- 飞书同步（#22，+ 决策后可选 #23）
- 排除规则增删（#24/#25）
- purge 收口（#26，taxonomy 常量提升 + `log_purge_event` 追加 emit）
- 测试：`test_emit_credentials.py`、`test_emit_purge_consolidation.py`、`test_emit_no_noise.py`（SC-4 凭证侧读无审计 + 脱敏 DB 断言）
- 改动面：`system/views.py`、`repositories/views.py`、`access_tokens/views.py`、`feishu/views.py`、`projects/views.py`（git 凭证）、`services/purge_reconcile.py`、`audit/services/taxonomy.py`

> 两 plan 都不动 `audit/services/*`（除 54-02 在 taxonomy 提升 purge 常量）；emit 入口、脱敏、append-only、INV-6 守护均为 Phase 53 既成地基，Phase 54 纯接线。

---

## Key files referenced（ground truth）

| 区域 | 文件:行 |
|------|---------|
| emit/aemit 入口（actor 取标量、savepoint、fail-soft）| `server/audit/services/audit_service.py:61,113` |
| taxonomy 常量（15 + RESERVED purge）| `server/audit/services/taxonomy.py:45-90` |
| 入口脱敏（key-name + 高熵兜底）| `server/audit/services/redaction.py:121` |
| AuditEvent 字段/索引/append-only | `server/audit/models/audit_event.py:36-94` |
| INV-6 grep 守护（自动覆盖新接线）| `server/tests/audit/test_audit_inv6_guard.py` |
| accounts 身份操作 | `server/accounts/views.py:290,329,405,487,520` |
| 成员/角色 | `server/projects/members_views.py:82,131,151` |
| 空间配置/仓库权限 | `server/projects/views.py:170,268,338,436,478,539,675,688` |
| Provider 凭证 CRUD | `server/system/views.py:346,427,437,460,491` |
| git 实例凭证 | `server/repositories/views.py:1175,1254,1275` |
| 排除规则 | `server/repositories/views.py:1082,1118` |
| PAT | `server/access_tokens/views.py:60,84` |
| 飞书同步（手动重试/webhook）| `server/feishu/views.py:540,691,1422` |
| purge 收口单点 | `server/services/purge_reconcile.py:349`（调用 :239,:253,:304）|

## RESEARCH COMPLETE
