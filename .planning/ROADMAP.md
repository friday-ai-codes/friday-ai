# Roadmap: Friday AI

## Milestones

- ✅ **v0.1.0 首启初始化向导** — Phases 1-5 (shipped 2026-06-09) — 详见 `milestones/v0.1.0-ROADMAP.md`
- 🚧 **v0.2.0 用户身份令牌与 Agent 工具打通** — Phases 6-11 (in progress)

## Phases

<details>
<summary>✅ v0.1.0 首启初始化向导 (Phases 1-5) — SHIPPED 2026-06-09</summary>

- [x] Phase 1: 向导门禁与初始化状态检测 (2/2 plans) — completed 2026-06-08
- [x] Phase 2: 管理员账号创建与自动登录 (2/2 plans) — completed 2026-06-08
- [x] Phase 3: LLM 供应商配置与 Claude Code 绑定 (2/2 plans) — completed 2026-06-08
- [x] Phase 4: 安全校验与可选集成步骤 (2/2 plans) — completed 2026-06-08
- [x] Phase 5: 入口迁移与向后兼容 (1/1 plan) — completed 2026-06-08

</details>

### 🚧 v0.2.0 用户身份令牌与 Agent 工具打通 (In Progress)

**Milestone Goal:** 让每个用户拥有 GitHub/GitLab 风格的个人访问令牌，以「用户身份 + 用户权限」调用 API；在此地基上实现会话用户隔离、管理员只读会话后台、MCP/skill 绑定用户令牌、RemoteTool 链路接通，使工具能以用户令牌在容器内真正执行。

**依赖链（务必按序）:** PAT 模型增强（独立）→ 令牌即用户身份（单点地基，全链路前置）→ 对话用户隔离（依赖身份）→ 管理员会话后台（依赖隔离）→ MCP 绑定 + RemoteTool 执行端点（依赖身份）→ task 容器接通（链式依赖最重，放最后）。

- [ ] **Phase 6: PAT 模型增强与一次性明文** - 令牌加名称/备注/可选有效期/前后缀指纹，明文仅展示一次，自助增删
- [ ] **Phase 7: 令牌即用户身份（认证地基）** - PAT 认证返回 owner + 施加其 RBAC，MCP 入口 fail-closed，PAT/JWT 前缀闸门
- [ ] **Phase 8: 对话/会话用户隔离** - Conversation 加 created_by + 历史回填，全路径按 owner 过滤，越权 403/404
- [x] **Phase 9: 管理员会话管理后台（只读）** - 独立只读后台浏览所有会话，交互需 fork 到自己名下 (completed 2026-06-09)
- [ ] **Phase 10: MCP 绑定用户令牌 + RemoteTool 执行端点** - 持久绑定令牌给 skill/mcp，以 owner 身份执行；新增认证执行端点
- [ ] **Phase 11: task 容器接通（RemoteTool 链路闭环）** - 容器消费 remote_tools + 直传 PAT 注入脱敏 + graceful 吊销

## Phase Details

### Phase 6: PAT 模型增强与一次性明文
**Goal**: 用户能创建带名称/备注/可选有效期的个人访问令牌，明文仅展示一次，列表可按前后缀区分并自助吊销
**Depends on**: Nothing（纯模型/序列化/前端增量，无认证语义风险，可独立先行）
**Requirements**: PAT-01, PAT-02, PAT-03, PAT-04, PAT-05, PAT-06
**Success Criteria** (what must be TRUE):
  1. 用户能创建令牌（必填名称、可选备注、可选有效期，不填即永久），创建响应一次性展示明文并可一键复制
  2. 创建「永不过期」令牌时看到非阻塞安全风险提示
  3. 令牌列表展示名称、备注、创建/最后使用/过期时间，并显示明文前缀 + 后 ≤4 位以区分不同令牌
  4. 用户能删除（吊销）自己的令牌，界面无任何延期/续期入口（到期只能新建）
  5. 用户只能查看/创建/删除属于自己的令牌；关闭后明文不可再获取，前后端均不持久化明文
**Constraints**: 维持无盐 sha256 + 唯一索引（contract 锁定，勿改 Argon2/加盐）；后缀严格 ≤4 位避免熵损失；明文绝不进 logger/序列化器 list/detail/前端 store/localStorage/URL
**Plans**: 3 plans
- [x] 06-01-PLAN.md — Wave 0 验证脚手架：后端 token_suffix/note/序列化器只读断言 + 前端指纹/never 警告/note payload spec（RED）
- [x] 06-02-PLAN.md — 后端增量：模型加 note + token_suffix 字段 + AddField 迁移 + 序列化器/acreate 透传（plaintext[-4:]）
- [x] 06-03-PLAN.md — 前端增量：DTO + 表单 note 输入/never 非阻塞警告 + 列表备注列/prefix…suffix 指纹
**UI hint**: yes

### Phase 7: 令牌即用户身份（认证地基）
**Goal**: 携带有效 PAT 的请求以令牌所有者身份 + 其 RBAC 权限被鉴权（替代「有效即全权限」），MCP 入口 fail-closed，PAT 与 JWT 互不干扰，审计链路不断
**Depends on**: Phase 6（需可信 owner 与可识别指纹）
**Requirements**: IDENT-01, IDENT-02, IDENT-03, IDENT-04, IDENT-05
**Success Criteria** (what must be TRUE):
  1. 携带有效 PAT 的请求 `request.user` = 令牌所有者，并施加该用户的 RBAC 权限（不再「有效即全权限」）
  2. 无令牌/匿名调用 MCP/工具入口一律被拒（原 `AllowAny` 收紧为要求认证，fail-closed）
  3. cookie-JWT 与 `friday_pat_` 前缀令牌（同用 Bearer）各走对认证分支，互不吞掉请求
  4. 已吊销/已过期令牌一律被拒，不能用于任何用户身份调用
  5. 令牌鉴权后审计仍正常：`request.auth` 为令牌实例，InteractionRun fingerprint 正确记录且不含明文
**Constraints**: 「改 authenticate 返回值」与「逐入口权限 audit」必须同阶段交付（Pitfall 1）；`authenticate` 开头加 `friday_pat_` 前缀闸门、非 PAT Bearer 返回 None（Pitfall 2）；认证类保持纯同步 ORM + `select_related("created_by")` 预取防 async `SynchronousOnlyOperation`（Pitfall 6）；保持 `request.auth` 为 AccessToken 实例（Pitfall 3）
**Plans**: 3 plans
- [x] 07-01-PLAN.md — Wave 0 验证脚手架（RED）：test_valid_token_passes owner 断言 + 新 test_pat_identity（前缀闸门/owner 身份/PAT·JWT 共存）+ MCP fail-closed authentication_failed
- [x] 07-02-PLAN.md — 认证地基：authentication.py 返回 (owner, token) + friday_pat_ 闸门 + authenticate_header（保 401）+ settings 认证类 PAT 优先
- [x] 07-03-PLAN.md — MCP 入口 fail-closed：McpToolView 基类收紧 IsAuthenticated + 显式 auth 类（17 子类全继承）

### Phase 8: 对话/会话用户隔离
**Goal**: 每个会话记录创建者，普通用户与管理员在 AI 对话中默认只能访问自己的会话，越权访问安全拒绝
**Depends on**: Phase 7（需可靠用户身份；schema 迁移可与 Phase 7 并行起步）
**Requirements**: ISO-01, ISO-02, ISO-03, ISO-04
**Success Criteria** (what must be TRUE):
  1. 新建会话记录创建者（`Conversation.created_by`）；升级迁移后历史无主会话归属给最早的 superuser，无遗留 `null`
  2. 普通用户在 list / detail / runtime / stream / patch / delete / fork 全路径只能查看/操作属于自己的会话
  3. 管理员在普通 AI 对话界面默认也只看自己的会话（与普通用户行为一致）
  4. 用户 B 直取用户 A 的会话 id（含 SSE/WebSocket 流式入口与对象级操作）返回 403/404，不泄漏会话存在性
**Constraints**: 历史 backfill 是本阶段第一个 plan（Pitfall 4），迁移分两步（加 `null=True` 列 + 索引 → data migration 回填给最早 superuser），回填完成前不收紧 `null=False`；收口 `get_owned_conversation_or_404`，所有按 id 取会话入口必经它，SSE/WebSocket 纳入同阶段验收（Pitfall 5）
**Plans**: 4 plans
- [x] 08-01-PLAN.md — Wave 0 RED 验证脚手架：test_conversation_isolation.py 覆盖全 25 路径 cross-user-denied(404) + 回填/admin-no-bypass/open-mode + conftest fixtures
- [x] 08-02-PLAN.md — 数据地基：Conversation.created_by FK + AddField(0018) + RunPython 回填(0019,可逆) + ConversationService owner-scoped 取数(aget_for_user/list/create/delete)
- [x] 08-03-PLAN.md — 直接会话端点 #1-12 owner gate（list/create/detail/delete/patch/preflight/runtime/messages/fork/stream/interrupt/export），SSE 流前 404
- [x] 08-04-PLAN.md — 关联模型端点 #13-25 owner gate（coding-session/plan + trace/clarification via .conversation），去 superuser bypass

### Phase 9: 管理员会话管理后台（只读）
**Goal**: 管理员有一个独立的只读会话管理后台浏览所有用户的会话，需交互时 fork 一份归到自己名下
**Depends on**: Phase 8（依赖隔离语义与 owner 维度）
**Requirements**: ADMVW-01, ADMVW-02, ADMVW-03
**Success Criteria** (what must be TRUE):
  1. 管理员能进入独立的「会话管理」后台，浏览所有用户的会话（区别于普通 AI 对话界面）
  2. 该后台为只读，管理员不能直接在他人会话上续聊/交互
  3. 管理员能把他人会话 fork 一份归属到自己名下后再进行交互
**Constraints**: 只读默认防误操作；fork 复用 Phase 8 既有 fork 路径并设 `created_by = 管理员`；后台入口与普通对话隔离过滤共存、互不打架
**Plans**: 3 plans
- [x] 09-01-PLAN.md — Wave 0 RED 验证脚手架：test_admin_conversations.py（admin 看全部/非 admin 403/匿名拒绝/只读 405/fork 归属）+ 前端 conversations.spec.ts + Phase 8 隔离回归保障
- [x] 09-02-PLAN.md — 后端：chat/admin_views.py + admin_urls.py 挂载 /api/admin/conversations/（IsSuperUser+默认认证，只读 GET+fork POST）+ ConversationService.admin_* + AdminConversationListSerializer
- [x] 09-03-PLAN.md — 前端：adminConversations.ts + ReadonlyConversationView.vue + admin/conversations.vue（DataTable+只读详情+fork→/chat?conversation=）+ AppSidebar 导航入口
**UI hint**: yes

### Phase 10: MCP 绑定用户令牌 + RemoteTool 执行端点
**Goal**: 用户能把自己的访问令牌持久绑定给 skill/mcp，被绑定的工具以令牌所有者身份与权限执行；提供经令牌认证、按工具 name 执行的 RemoteTool 端点供容器回调
**Depends on**: Phase 7（端点与绑定执行均靠 PAT 认证用户身份）
**Requirements**: MCPB-01, MCPB-02, MCPB-03, RTOOL-01
**Success Criteria** (what must be TRUE):
  1. 用户能在 Friday 中把自己的某个访问令牌持久绑定给 skill/mcp（绑定关系入库）
  2. 被绑定的 skill/mcp 调用以该令牌所有者的身份与权限执行
  3. 用户能查看并解除自己的绑定
  4. 存在一个经令牌认证、按工具 name 执行的 RemoteTool 端点（`auth=AccessToken` + `IsAuthenticated`），匿名/无效令牌被拒
**Constraints**: 持久绑定走 NEW 表（user↔token↔tool），绑定可见可管理；执行端点复用 `tools.executor.execute_tool` 三源派发（builtin/mcp/skill），执行与第三方凭证解析始终留在 server 侧；执行端点亦是认证入口，纳入 Pitfall 1/3 验收
**Plans**: 4 plans
- [x] 10-01-PLAN.md — Wave 0 RED 验证脚手架：conftest make_remote_tool/make_tool_binding + test_tool_bindings.py + test_remote_tool_execute.py + 前端 ToolBindingSettings.spec.ts
- [x] 10-02-PLAN.md — 数据地基：tools.ToolTokenBinding 模型（三 FK CASCADE + unique(user, remote_tool)）+ 0003 CreateModel 迁移
- [ ] 10-03-PLAN.md — 后端装配：serializers + 绑定 ViewSet(owner 隔离+upsert+归属校验) + bindable 端点 + RemoteToolExecuteView(PAT fail-closed+审计) + 挂载 /api/tools/
- [x] 10-04-PLAN.md — 前端：types/api/store(toolBindings) + ToolBindingSettings/Table/Dialog + profile.vue 绑定卡片（下拉仅列 valid 令牌，无明文）
**UI hint**: yes

### Phase 11: task 容器接通（RemoteTool 链路闭环）
**Goal**: task 容器消费 `remote_tools` 并经 SDK MCP server 真正加载调用工具，用户令牌以直传 PAT 安全注入（脱敏），令牌吊销时在途任务 graceful 跑完仅阻断新调用
**Depends on**: Phase 10（需可调用的执行端点 + 绑定令牌；链式依赖最重）
**Requirements**: RTOOL-02, RTOOL-03, RTOOL-04
**Success Criteria** (what must be TRUE):
  1. task 容器消费 `remote_tools`，agent 经 `create_sdk_mcp_server` proxy 真正加载并调用工具（含 builtin/mcp/skill）
  2. 用户令牌以直传 PAT 形态经 server→runner→task 注入容器，agent 以用户身份回调执行端点完成端到端「需求→agent→调用用户授权工具」闭环
  3. `docker inspect` 与 runner/task 日志中不出现明文令牌（注入与脱敏必须同阶段交付）
  4. 任务运行中令牌被吊销时在途任务继续跑完、仅阻断后续新调用（graceful），鉴权失效定义为不可重试终止态并回传结构化错误
**Constraints**: 复用 runner `env_` 前缀透传通道对齐 `FRIDAY_TASK_REMOTE_TOOLS`/`USER_TOKEN`/`API_URL`；Go 侧打印前按 key 名/`friday_pat_` 值模式脱敏，task 侧禁止把令牌写进 session/usage/prompt 落盘文件（Pitfall 7）；401/403/revoked 列为不可重试（Pitfall 8）；零新增依赖（claude-agent-sdk 0.1.58 自带 mcp_servers/@tool/create_sdk_mcp_server）
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 6 → 7 → 8 → 9 → 10 → 11

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. 向导门禁与初始化状态检测 | v0.1.0 | 2/2 | Complete | 2026-06-08 |
| 2. 管理员账号创建与自动登录 | v0.1.0 | 2/2 | Complete | 2026-06-08 |
| 3. LLM 供应商配置与 Claude Code 绑定 | v0.1.0 | 2/2 | Complete | 2026-06-08 |
| 4. 安全校验与可选集成步骤 | v0.1.0 | 2/2 | Complete | 2026-06-08 |
| 5. 入口迁移与向后兼容 | v0.1.0 | 1/1 | Complete | 2026-06-08 |
| 6. PAT 模型增强与一次性明文 | v0.2.0 | 2/3 | In progress | - |
| 7. 令牌即用户身份（认证地基） | v0.2.0 | 1/3 | In progress | - |
| 8. 对话/会话用户隔离 | v0.2.0 | 4/4 | Complete | 2026-06-09 |
| 9. 管理员会话管理后台（只读） | v0.2.0 | 3/3 | Complete   | 2026-06-09 |
| 10. MCP 绑定用户令牌 + RemoteTool 执行端点 | v0.2.0 | 3/4 | In Progress|  |
| 11. task 容器接通（RemoteTool 链路闭环） | v0.2.0 | 0/TBD | Not started | - |
