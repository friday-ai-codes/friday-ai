# Phase 2: 管理员账号创建与自动登录 - Context

**Gathered:** 2026-06-08
**Status:** Ready for planning
**Mode:** autonomous smart-discuss（无人值守，所有灰区直接采纳推荐答案）

<domain>
## Phase Boundary

本阶段在 Phase 1 已交付的「门禁 + 向导外壳 + 同一 setup 端点」之上，交付「管理员账号创建的完整 UX 与自动登录会话」，打通"用户能进去系统"的闭环。

**In scope（Phase 2 拥有）：**
- 后端 `SetupInitSerializer` 增强：用 Django `validate_password` 做密码强度校验（复用既有 `AUTH_PASSWORD_VALIDATORS`）。
- 后端 `SetupInitView` 创建 superuser 成功后**下发 JWT cookie 会话**（复用 `LoginView` 的 cookie-JWT 路径），响应体返回 `{access_token, user, must_change_password}`，使前端无需二次登录。
- 创建的 superuser **不触发** `must_change_password`（保持默认 False）。
- 前端 `setup.vue` 表单增强：密码强度校验/强度指示 + 二次确认；提交成功后写入 auth store 并直接跳转系统首页 `/`。
- i18n：密码强度/错误/自动登录相关中文文案。
- 前后端测试覆盖 ADMIN-01/02/03 四条成功标准。

**Out of scope（不在本阶段）：**
- 不重写或回退 Phase 1 的 fail-closed 门禁、原子防重入、`SetupNotInitialized` 权限、migration（仅在其上增强）。
- 不新增 setup 端点；仍用同一 `POST /api/auth/setup/`。
- LLM 供应商配置、Claude Code 绑定 → Phase 3。
- 安全密钥校验、飞书/RAG 可选步骤 → Phase 4；entrypoint 迁移 → Phase 5。

**判定标准：** 用户在向导填用户名 + 密码（强度校验 + 二次确认）→ 提交即时创建 superuser（不强制改密）→ 自动建立会话直达首页 `/` → 该账号可正常登录、向导对后续访问者按 Phase 1 门禁关闭。
</domain>

<decisions>
## Implementation Decisions

### A. 密码强度校验策略
- 后端为权威校验源：在 `SetupInitSerializer.validate_password` 中调用 `django.contrib.auth.password_validation.validate_password(value, user=User(username=...))`，复用 `settings.AUTH_PASSWORD_VALIDATORS`（UserAttributeSimilarity / MinimumLength / Common / Numeric）。
- 传入未保存的 `User(username=...)` 实例，使「密码与用户名过于相似」校验生效。
- 因 `LANGUAGE_CODE = "zh-hans"` 且 `USE_I18N = True`，Django 校验器错误消息天然为中文，直接透传。
- serializer 的 `password.min_length` 从 6 提升到 8，与 Django `MinimumLengthValidator` 默认（8）对齐；同步更新 Phase 1 中依赖 6 位弱口令的既有测试（如改用更强口令断言成功路径），不回退门禁/防重入测试语义。
- 前端 zod 提供即时反馈（min 8 + 非纯数字 refine + 两次一致），并渲染「弱/中/强」强度指示；前端仅作 UX 提示，最终以后端校验为准。
- 后端 400 字段错误（`{"password": [...]}` / `{"username": [...]}`）由前端回填到对应字段/错误条展示，文案直接用后端中文消息。

### B. 会话建立机制（自动登录）
- 复用 `LoginView` 的 cookie-JWT 路径：创建成功后 `await sync_to_async(RefreshToken.for_user)(user)`，设置自定义 `sub` claim，`response.set_cookie` 下发 `refresh_token` 与 `access_token` 两个 HttpOnly cookie（沿用 `settings.COOKIE_HTTPONLY/SAMESITE/SECURE` 与既有 max_age）。
- 响应体复用 `LoginResponseSerializer` 形态：`{access_token, user, must_change_password}`，状态码保持 201。
- `must_change_password` 恒为 `False`（`create_superuser` 默认 False，不显式置位，满足成功标准 2）。
- 不改变 Phase 1 的 fail-closed 门禁与 `_atomic_create_superuser` 防重入逻辑；会话下发只发生在创建成功（user 非 None）之后。

### C. 前端自动登录与跳转
- `setup.vue` 提交成功后改为直达首页：解析响应体的 `user`，写入 auth store（`user` / `isAuthenticated=true` / `mustChangePassword=false` / `needsSetup=false` / `setupStatusChecked=true` / `isInitialized=true`），随后 `router.push('/')`（替换 Phase 1 的跳转 `/login`）。
- 新增 auth store action（如 `applySetupSession(user)`）集中写入会话状态，避免在组件里散落赋值；成功后调用 `fetchMe()` 拉取空间成员/头像（失败静默，与 `login()` 一致）。
- 保持 POST 走原始 `fetch('/api/auth/setup/', { credentials: 'include' })`（不走 `api/client.ts` 的 `post()`，避免 403/401 触发全局 `auth:forbidden`/`auth:logout` 重定向——沿用 Phase 1 决策 D-D / 威胁 T-1-05），但解析新增的 `user` 字段。

### D. 端点形态与门禁复用
- 仍用同一 `POST /api/auth/setup/`，不新增端点、不改路由；门禁 `SetupNotInitialized` + 原子防重入（Phase 1）原样保留。
- 本阶段对 `SetupInitView`/`SetupInitSerializer` 仅做「增强」：强度校验 + 会话下发 + 返回 user，行为对已初始化实例仍 fail-closed 403。
- 创建成功后既有 Phase 1 门禁自动对后续访问者关闭（存在 superuser → 403 / 前端守卫重定向到 `/login`），无需新增关闭逻辑（满足成功标准 4）。

### E. i18n（文案）
- 在 `web/src/locales/zh-CN.json` 的 `setup.*` 命名空间新增：密码强度标签（弱/中/强）、强度提示、自动登录/进入首页相关提示，及若干前端即时校验错误文案（如「密码至少 8 位」「两次输入的密码不一致」「密码不能全为数字」）。
- 后端返回的校验错误消息（中文）直接展示，不在前端二次翻译。

### Claude's Discretion
- auth store 会话写入 action 的具体命名、强度指示的视觉实现（进度条/分段/颜色档位）、强度计算的具体算法、字段错误回填的具体交互、新增测试文件的拆分与命名，均由规划/执行阶段按既有约定自主决定。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- **cookie-JWT 会话范式**：`server/accounts/views.py::LoginView`（`RefreshToken.for_user` + `sub` claim + `set_cookie(refresh_token/access_token)`，`LoginResponseSerializer{access_token,user,must_change_password}`）——Phase 2 创建成功后直接复用该下发逻辑。
- **Phase 1 门禁与创建**：`SetupInitView`（`authentication_classes=[]` + `[AllowAny, SetupNotInitialized]`）、`_atomic_create_superuser`（`transaction.atomic` double-check + `IntegrityError` 兜底）、`SetupInitSerializer`（`validate_username` 查重）——在其上增强，不重写。
- **密码校验器**：`settings.AUTH_PASSWORD_VALIDATORS` 四项已配置；`ChangePasswordView`/`ForceChangePasswordView` 已演示 `must_change_password=False` 的清除模式。
- **前端表单范式**：`web/src/pages/setup.vue` 已用 vee-validate + zod + `~/components/ui/{form,input,button}`，含 username/password/confirmPassword 三字段与原始 fetch POST。
- **auth store**：`web/src/stores/auth.ts`（`login()` 写入 user/isAuthenticated/mustChangePassword + `fetchMe()`；`needsSetup`/`setupStatusChecked`/`isInitialized` 已存在）。
- **类型**：`web/src/types` 的 `User`、`LoginResponse` 形态可复用/对齐。
- **测试基线**：`server/tests/test_setup_gate.py`（8 用例，含 `api_client`/`admin_user` fixture）、`web/src/api/__tests__/setup.spec.ts`。

### Established Patterns
- 后端 async-first：ORM/JWT 同步 API 走 `await sync_to_async(...)`；serializer DB 校验在 `sync_to_async(serializer.is_valid)` 内执行。
- 注释/文案中文（zh-CN）；Python `ruff format`（行宽 100，py314）。
- 前端文件路由 + `<route> meta.layout:false`；用户可见文案经 `t('setup.*')`；POST 成功后写 auth store + 路由跳转。

### Integration Points
- 后端：`server/accounts/serializers.py`（`SetupInitSerializer` 增强）+ `server/accounts/views.py`（`SetupInitView.post` 下发会话、返回 user）；路由不变。
- 前端：`web/src/pages/setup.vue`（强度 UI + 提交成功改为直达首页）+ `web/src/stores/auth.ts`（新增会话写入 action）+ `web/src/locales/zh-CN.json`（新增文案）。
- 测试：扩展 `server/tests/test_setup_gate.py`（强度校验 / 会话 cookie / 不触发改密）+ 前端 `setup.vue`/store 测试。
</code_context>

<specifics>
## Specific Ideas

- Phase 1 决策 D-D 与威胁 T-1-05 明确要求 setup POST 保持原始 fetch（绕开 client.ts 全局 403/401 跳转），Phase 2 必须沿用此约束，仅扩展响应体解析。
- 成功标准 2「不触发 must_change_password」需有测试：创建后断言用户 `must_change_password is False`；成功标准 3「自动建立会话」需断言响应 set 了 `refresh_token`/`access_token` cookie；成功标准 4「随后可正常登录」可用创建的账号请求 `POST /api/auth/login/` 断言 200。
</specifics>

<deferred>
## Deferred Ideas

- LLM 供应商一键预设与 Claude Code 绑定 → Phase 3（PROV-*）。
- 安全密钥校验、可选飞书/RAG 步骤 → Phase 4。
- entrypoint 默认不再自动建号、保留运维命令、老部署不回退 → Phase 5（COMPAT-*）。
- 向导多步骤指示器/进度（管理员之后的步骤）→ 随 Phase 3/4 引入步骤时再设计。
</deferred>
