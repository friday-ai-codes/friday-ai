# Phase 1: 向导门禁与初始化状态检测 - Context

**Gathered:** 2026-06-08
**Status:** Ready for planning
**Mode:** autonomous smart-discuss（无人值守，所有灰区直接采纳推荐答案）

<domain>
## Phase Boundary

本阶段交付「首启向导的门禁层与初始化状态检测」，不含具体向导步骤的业务逻辑：

**In scope（Phase 1 拥有）：**
- 后端只读「初始化状态」接口（`is_initialized` / `needs_setup`），无认证可调用
- 可复用的 fail-closed 门禁（存在 superuser 即拒绝）+ 并发/重入保护（原子事务 + 复核）
- 前端路由守卫：未初始化 → 导向向导；已初始化 → 拒绝进入向导
- 首启向导「外壳」路由（容器 + 占位），供 Phase 2~4 填充步骤

**Out of scope（移交后续阶段）：**
- 管理员账号创建表单/密码强度/二次确认/自动登录会话 → Phase 2
- LLM 供应商配置、Claude Code 绑定 → Phase 3
- 安全密钥校验、飞书/RAG 可选步骤 → Phase 4
- entrypoint 迁移与向后兼容 → Phase 5

**判定标准：** "存在任意 `is_superuser=True` 用户" 即视为「已初始化」（与 `init_superuser` 命令、PROJECT 约束一致）。
</domain>

<decisions>
## Implementation Decisions

### A. 初始化状态检测接口（is_initialized）
- 路径复用前端既有约定 `GET /api/auth/setup/status/`（`web/src/pages/setup.vue` 已写死调用此路径，复用可减少前端改动）。
- 响应体同时给出两个语义字段：`{ "needs_setup": <bool>, "is_initialized": <bool> }`，其中 `needs_setup = not is_initialized`，兼容现有前端读取 `needs_setup`。
- 权限 `AllowAny`，只读 `GET`，无需认证即可调用（满足成功标准 2）。
- 实现采用 adrf `APIView` 异步视图，DB 访问走 `await sync_to_async(User.objects.filter(is_superuser=True).exists)()`，与 `accounts/views.py`、`system/health_views.py` 既有异步写法一致。
- 挂载于 accounts app（`accounts/urls.py`，前缀 `/api/auth/`），与现有 `setup.vue` 调用路径对齐。
- 响应仅返回布尔状态，不泄露用户名/数量等敏感信息。

### B. 初始化门禁 fail-closed 与防重入
- 新增可复用 DRF 权限类（如 `accounts` 下 `SetupNotInitialized`）：存在 superuser 时返回 403、无 superuser 时放行；供本阶段 init POST 与 Phase 2 创建管理员 POST 共用，保证单一门禁来源。
- 防重入/并发：初始化写操作包裹在 `transaction.atomic()` 内，进入后 `select_for_update`（或在事务内再次 `User.objects.filter(is_superuser=True).exists()` 复核），已存在即拒绝；依赖数据库事务串行化，确保并发/重复请求只可能成功一次、其余被拒（满足成功标准 4）。SQLite 本地开发下 `select_for_update` 退化为 no-op，因此以"事务内复核 + 唯一性"双保险。
- Phase 1 即落地受门禁保护的 `POST /api/auth/setup/`：
  - 已初始化（存在 superuser）→ 一律 403（fail-closed），满足成功标准 3、4 且可端到端测试。
  - 未初始化 → 在原子事务内创建 superuser（复用 `User.objects.create_superuser`），作为最小可用实现；密码强度/二次确认/自动登录会话等 UX 增强留待 Phase 2，不在本阶段重复建设。
- 不引入会绕过向导的隐式 env 自动建号路径（遵循 REQUIREMENTS Out of Scope）。

### C. 前端路由守卫与初始化状态获取
- 在 `web/src/main.ts` 的 `router.beforeEach` 中加入「初始化状态」分支，置于现有 `authStore.initAuth()` 之前/旁路。
- 新增 `web/src/api/setup.ts`（`getSetupStatus()`）封装无认证 GET；初始化状态在应用启动期查询一次并缓存（可放入 auth store 或新建轻量 setup store，推荐复用 auth store 减少样板）。
- 守卫逻辑：
  - 未初始化（`needs_setup=true`）→ 除 `/setup` 外的任意路由重定向到 `/setup`。
  - 已初始化 → 访问 `/setup` 重定向到 `/login`（向导界面不再出现，满足成功标准 3）。
  - `/setup` 加入 `publicPages`（无需认证即可进入向导外壳）。
- 容错（fail-safe）：状态请求失败时按「已初始化」处理 —— 宁可不进向导，也不把已有生产实例误导向重置/接管（安全优先，呼应 PROJECT fail-closed 约束）。

### D. 向导外壳范围与视觉
- 复用既有 `/setup` 路由（`web/src/pages/setup.vue`）改造为「向导外壳」容器：标题/品牌 + 步骤框架占位，后续 Phase 在外壳内填充各步骤组件。
- 现有 `setup.vue` 的管理员表单在 Phase 1 继续可用（接到新门禁 POST 后端），保证本阶段交付即可端到端跑通首启；表单的强度校验/确认/自动登录等增强在 Phase 2 完善（避免留下不可用的空壳）。
- 视觉沿用现有 glass 卡片风格（`bg-card/70 backdrop-blur-xl`、`icon-[lucide--*]`、`~/components/ui/{button,form,input}`），不做主题化定制（遵循 Out of Scope）。

### E. i18n（向导文案）
- 向导外壳的用户可见文案通过 `vue-i18n` 落地，默认语言 `zh-CN`（遵循 PROJECT/Constraints 显式要求）。
- 现状：`vue-i18n` 已在 `main.ts` 注册但 `messages: {}` 为空、`web/src/locales/` 仅含 `.gitkeep`。本阶段为向导新建 `setup.*` 命名空间的 zh-CN 文案，并按既有 unplugin-vue-i18n 装载方式接入 `main.ts`。
- 技术细节（catalog 装载方式、是否启用 `@intlify/unplugin-vue-i18n` 的 yaml 自动加载）交由研究/规划阶段确认；若接入成本过高，退化为在 `main.ts` 内联 `messages.zh-CN` 对象亦可接受，但用户文案必须经 `t()`/`$t` 取用而非散落硬编码。

### Claude's Discretion
- 状态缓存落点（auth store vs 新建 setup store）、权限类与锁工具的具体文件命名、向导外壳的步骤指示器是否在 Phase 1 渲染、i18n catalog 的具体装载实现，均由规划/执行阶段按既有约定自主决定。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- **异步 DRF 视图范式**：`server/accounts/views.py`（`adrf.views.APIView` + `AllowAny` + `sync_to_async`），`server/system/health_views.py`（`AllowAny` 改 `IsAuthenticated` 的聚合只读接口范式）。
- **管理命令**：`server/accounts/management/commands/init_superuser.py`（`User.objects.filter(is_superuser=True).exists()` 判定 + `create_superuser`），`reset_superuser_password.py` 保留为运维兜底。
- **URL 装载**：`server/accounts/urls.py`（`/api/auth/*`）已在 `server/friday/urls.py` 中 include。
- **前端脚手架**：`web/src/pages/setup.vue` 已存在（调用 `/api/auth/setup/` 与 `/api/auth/setup/status/`，含 `<route> meta.layout:false`），`web/src/pages/login.vue` 为公开页范式（vee-validate + zod + `~/components/ui/form`）。
- **路由守卫**：`web/src/main.ts` `router.beforeEach` 已有 `publicPages` 白名单与 `initAuth` 流程。
- **Auth store**：`web/src/stores/auth.ts`（`isInitialized`、`initAuth`、`$reset`）。
- **API client**：`web/src/api/client.ts`（`get/post`）、`web/src/api/users.ts` 为封装范式。
- **事务/锁范式**：仓库内已用 `transaction.atomic` / `select_for_update`（如 `server/workflows/engine/scheduler.py`、`server/system/views.py`）。

### Established Patterns
- 后端 async-first：ORM 访问统一 `sync_to_async`；权限用 DRF `permission_classes` / `get_permissions()` 按 method 分派（见 `InvitationView`）。
- 注释/文案中文（zh-CN）；Python `ruff format`（行宽 100，目标 py314）。
- 前端文件路由（unplugin-vue-router），公开页用 `<route lang="yaml">meta.layout:false`；样式 Tailwind 4 + reka-ui 风格的 `~/components/ui/*`。
- 测试基线：后端 `server/tests/test_*.py`（含 `test_auth.py`、`test_accounts_smoke.py`），前端 `*.spec.ts`（如 `web/src/api/__tests__/`）。

### Integration Points
- 后端新增视图 → `server/accounts/views.py` + `server/accounts/urls.py`（已被 `friday/urls.py` include）。
- 前端守卫 → `web/src/main.ts`；新增 `web/src/api/setup.ts`（从 `web/src/api/index.ts` re-export）；状态缓存 → `web/src/stores/auth.ts`。
- 向导外壳 → `web/src/pages/setup.vue`（已存在，改造为外壳）。
- i18n → `web/src/main.ts` + `web/src/locales/`。
</code_context>

<specifics>
## Specific Ideas

- 前端 `setup.vue` 已经按 `GET /api/auth/setup/status/`（读取 `needs_setup`）与 `POST /api/auth/setup/`（创建管理员、期望后端下发 cookie）设计；后端据此对齐路径与字段，避免前端改造。
- 成功标准 4「并发/重复请求一律被拒绝」需有真实测试覆盖：后端用并发/重复 POST（已存在 superuser）断言全部 403；事务内复核保证不可重置/接管。
</specifics>

<deferred>
## Deferred Ideas

- 管理员创建的完整 UX（密码强度、二次确认、自动建立会话直达首页、不触发 must_change_password）→ Phase 2（ADMIN-01/02/03）。需与本阶段 init POST 协调：Phase 2 在同一门禁与端点上增强，不另起炉灶。
- LLM 供应商一键预设与 Claude Code 绑定 → Phase 3。
- 安全密钥校验、可选飞书/RAG 步骤 → Phase 4。
- `entrypoint.sh` 默认不再自动建号、保留运维命令、老部署不回退 → Phase 5（与本阶段门禁互补）。
</deferred>
