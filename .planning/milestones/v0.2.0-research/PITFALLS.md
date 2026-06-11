# Pitfalls Research

**Domain:** 自托管 AI 自动化平台 — 个人访问令牌（PAT）/ 令牌即身份 / 会话隔离 / 跨进程令牌注入（brownfield Friday AI v0.2.0）
**Researched:** 2026-06-09
**Confidence:** HIGH（结论基于本仓代码实读：`server/access_tokens/`、`server/chat/`、`server/mcp_tools/views.py`、`server/runners/dispatcher.py`、`runner/internal/docker/executor.go`、`task/core/executor.py`、`.planning/codebase/CONCERNS.md`）

> 本文档的坑均落到**本系统的具体代码路径**，不是泛安全清单。每个坑给：失败模式 → 根因 → 预防（可执行）→ 警示信号 → 应处理阶段。阶段名引用本里程碑的能力切片（roadmap 尚未生成，故按能力命名）：
> - **P-PAT**：PAT 模型增强 + 自助创建/吊销 + 明文仅展示一次
> - **P-身份**：`authenticate` 从 `(None, token)` 改为 `(user, token)`（令牌即身份）
> - **P-隔离**：Conversation 加 `created_by` + 历史 backfill + 全路径过滤
> - **P-MCP**：MCP/skill 绑定用户令牌执行
> - **P-注入**：RemoteTool 链路接通 + 用户 PAT 经 server→runner→task 注入容器

---

## Critical Pitfalls

### Pitfall 1: `authenticate` 改返回 `user` 让所有 AllowAny/匿名入口语义突变

**What goes wrong:**
`AccessTokenAuthentication.authenticate` 当前返回 `(None, token)`（见 `server/access_tokens/authentication.py:74`），`request.user` 是 `AnonymousUser`。改成「令牌即身份」后返回 `(token.created_by, token)`，`request.user` 变成真实用户。问题在于**下游入口的放行逻辑是按"匿名也放行"写的**，语义会静默翻转：

- `server/mcp_tools/views.py:144-145` 的 `McpToolView`：`authentication_classes=[AccessTokenAuthentication]` + `permission_classes=[AllowAny]`。当前**无 Bearer 头时 `authenticate` 返回 `None` → 匿名 → AllowAny 放行**，即所有 MCP 工具接口对任何能访问到端口的人开放。改身份语义但仍保留 `AllowAny`，匿名洞**依旧存在**；而一旦后续把 `AllowAny` 换 `IsAuthenticated`，所有"无令牌"的内部调用方会突然 401。
- `server/chat/permissions.py` 的 `ChatAuthPermission`：开关关闭时 `return True`（全放行）。它通过 `request.user.is_authenticated` 判定 JWT 通过。如果 access-token 也挂到 chat 视图，`request.user` 突然变成 token 所有者 → 鉴权开关「打开」时行为从"必须 JWT"变成"PAT 也算登录用户"，可能放大权限面。

**Why it happens:**
`(None, token)` 是当前 contract（authentication.py 文档明确写"有效即放行，不做 scope 校验"）。很多入口默认"未认证=匿名=按 AllowAny 处理"，没人预期 `request.user` 会从 PAT 路径被填上。

**How to avoid:**
- 把"改 authenticate 返回值"和"逐个 audit 入口"绑成同一阶段交付，禁止只改认证类不改权限类。
- 给所有挂 `AccessTokenAuthentication` 的视图建一张**入口清单**（grep `AccessTokenAuthentication` 与 `AllowAny`），逐个标注：改身份后应保持开放 / 应改 `IsAuthenticated` / 应加对象级过滤。
- MCP 端点应**fail-closed**：要求有效 PAT 才放行（参考 CONCERNS.md 对 compat 端点"AllowAny 默认开放"的同类批评），不要继续 `AllowAny`。

**Warning signs:**
- 测试里出现"无 token 也能调 MCP 工具"仍通过；`request.user` 在原本匿名的处理分支里突然为真实用户。
- 改完认证后，`/api/mcp/tools/*` 的匿名请求行为没变（说明 AllowAny 没收紧）。

**Phase to address:** P-身份（必须与 P-MCP 的端点收紧同阶段交付）

---

### Pitfall 2: PAT 与 SimpleJWT 双认证类共存——Bearer 头被 PAT 先吃掉，JWT 永远轮不到

**What goes wrong:**
SimpleJWT 与 `AccessTokenAuthentication` **都用 `Authorization: Bearer ...`**。而当前 `AccessTokenAuthentication.authenticate` 对任意 Bearer 值**不校验 `friday_pat_` 前缀就直接 `hash_token` 查库**，查不到即 `raise AuthenticationFailed`（authentication.py:57-63）。后果：

- 若认证类顺序是 `[AccessTokenAuthentication, JWTAuthentication]`，前端用 JWT 的 `eyJ...` Bearer 调接口 → 被 PAT 哈希查库 → DoesNotExist → **直接抛 401**，JWT 类根本没机会执行。
- DRF 的认证链是"第一个返回非 None 或抛异常者胜出"，所以**顺序 + 是否抛异常**双重决定成败。

**Why it happens:**
PAT 设计时是"work-item 外部单一入口"，没考虑和 cookie-JWT（`common.authentication.CookieJWTAuthentication`，全局默认见 `settings.py:265`）在同一视图共存。`authenticate` 对非 PAT 的 Bearer 抛异常而非返回 `None`，违反"不是我的就让给下一个"的 DRF 惯例。

**How to avoid:**
- `AccessTokenAuthentication` 开头加前缀闸门：`if not plaintext.startswith(PAT_PREFIX): return None`（让非 PAT Bearer 落到 JWT），仅当前缀匹配但查库失败才抛 `AuthenticationFailed`。`PAT_PREFIX = "friday_pat_"` 已在 `models.py:21` 定义，直接复用。
- 明确认证类顺序：cookie-JWT/Optional JWT 在前、PAT 在后（或前缀闸门保证互斥）。注意 `chat/authentication.py` 已有同类历史坑记录（继承错基类导致 cookie 路径被丢、前端永远 401）——这是本仓**已经踩过一次的同型坑**。
- 加契约测试：同一视图分别用 cookie-JWT、`friday_pat_*`、过期 JWT、乱 Bearer 四种请求，断言各自走对分支。

**Warning signs:**
- 加了 PAT 认证后，前端正常登录态接口偶发"无效的 Friday Access Token"或 401。
- `access_token_denied reason=not_found` 日志里出现明显是 JWT 的 fingerprint（高频、来自浏览器）。

**Phase to address:** P-身份

---

### Pitfall 3: InteractionRun 审计依赖 `request.auth=token`——身份切换时被顺手改坏

**What goes wrong:**
denial 审计（`_record_denial`）与下游 MCP 审计都以 **`token_fingerprint`（= `token_hash`，绝不含明文）** 为锚点，且依赖 `request.auth` 仍是 `AccessToken` 实例。"令牌即身份"重构时若把返回值改成 `(user, None)`、或把 `request.auth` 改写成 user/字符串，会让：
- MCP 工具里所有 `create_interaction_run(token_fingerprint=request.auth.token_hash, ...)` 取不到 fingerprint（`request.auth` 不再是 token）→ 审计断链或抛 `AttributeError`。
- 误把明文 token 写进 `raw_request`（当前刻意只存 `reason/path`，并由 ledger 内部 `redact_for_ledger` 兜底）。

**Why it happens:**
重构焦点在"填 user"，容易忘记 `request.auth` 这条审计血脉；DRF 里 `request.auth` 和 `request.user` 是两个独立返回位，新人常以为只有一个。

**How to avoid:**
- 重构后**保持 `request.auth` 仍是 `AccessToken` 实例**：返回 `(token.created_by, token)`，user 和 auth 各司其职。
- 给审计写入点加测试：DENIED run 的 `token_fingerprint` 等于 `hash_token(明文)`、`raw_request` 不含明文、`record_event` 不抛。
- 复用既有 `redact_for_ledger` / structlog `redact_credentials`，新增字段名（如 `pat`, `access_token`）也纳入脱敏名单。

**Warning signs:**
- MCP 调用后 `InteractionRun.token_fingerprint` 为空/为 user id。
- 审计表里出现 `friday_pat_...` 明文样式的值（严重）。

**Phase to address:** P-身份（审计回归）+ P-MCP（工具侧 fingerprint 复核）

---

### Pitfall 4: 历史会话无 `created_by`——backfill 归属错误造成越权或全员失联

**What goes wrong:**
`Conversation` 当前**只有 `project` FK，没有 `user`/`created_by`**（`server/chat/models.py:21-84`），`ConversationService.list_conversations()` 也**无任何用户过滤**（`views.py:335`）。加 `created_by` 做隔离时，存量会话没有归属：
- 若 backfill 默认归给某个 superuser/首个用户 → 该用户能看到所有人历史会话（**越权聚合**）；其他用户看不到自己过去发起的会话（**数据"丢失"投诉**）。
- 若留 `null` 又把过滤写成 `filter(created_by=request.user)` → 所有历史会话对**所有人不可见**；写成 `filter(Q(created_by=user) | Q(created_by__isnull=True))` → 历史会话对**所有人可见**（隔离失效）。两个极端都错。

**Why it happens:**
brownfield 既有数据没有"作者"维度；隔离需求是事后追加，迁移策略（归谁、null 怎么办）没人在模型层定义。

**How to avoid:**
- 迁移分两步：①加 `created_by`（`null=True`）字段 + 索引；②数据迁移用**可推断的归属源**回填——优先从会话关联线索推断（如该 project 的成员、最早 message 的发起者、OrchestrationRun/通知 user 等），无法推断的显式标记为"系统/无主"而非随意塞给某人。
- 明确产品决策并写进 Key Decisions：无主历史会话是"仅 superuser 可见"还是"归 project owner"——**不要让默认 ORM 行为替你做这个决定**。
- 字段最终是否 `null=False` + 默认值，要在回填完成后再收紧，避免新建会话漏填 `created_by`。

**Warning signs:**
- 上线后用户报"我的历史对话不见了"或"看到别人对话"。
- `Conversation.objects.filter(created_by__isnull=True).count()` 长期不为 0（回填没覆盖全）。

**Phase to address:** P-隔离（数据迁移必须是该阶段第一个 plan）

---

### Pitfall 5: 会话隔离漏过滤——list 改了，detail/stream/delete/fork/WS 没改（IDOR）

**What goes wrong:**
隔离最常见的实现错误是**只在列表加过滤，按 id 直查的路径忘了对象级校验**。本仓有多条按 `conversation_id` 直取的入口：
- `ConversationDetailView.get`（views.py:393，直接 `get_conversation_with_messages(id)`，**无 owner 校验**）
- `ConversationMessagesDeleteView` / `ConversationMessageForkView` —— 现有校验是**项目级**（`PermissionService` MEMBER+/viewer，superuser 豁免，见 views.py:828-895/978-990），**不是 per-user owner**；隔离语义要的是"自己的会话"，项目级权限会让同项目他人仍可访问。
- `ChatStreamView`（SSE，views.py:1116）、`ChatInterruptView`、以及 **WebSocket 消费者** `server/workflows/consumers.py` / `chat` 流式入口——这些非 REST 路径极易漏过滤。

任何一条漏掉 = 越权读取/删除/接管他人会话（IDOR）。

**Why it happens:**
过滤逻辑分散在 N 个视图 + 流式入口 + WS，缺少统一的"按当前用户取会话"收口；现有项目级权限给人"已经鉴权了"的错觉。

**How to avoid:**
- 收口一个 `get_owned_conversation_or_404(user, conversation_id)`（async 安全），**所有**按 id 取会话的入口必须经它，禁止直接 `Conversation.objects.aget(id=...)`。
- 明确隔离判据 = `created_by == request.user`（或 + 项目权限叠加），与既有项目级权限的关系写清楚，别让两套语义打架。
- 把 SSE 与 WebSocket 列入同一阶段的验收清单（这是最易漏的两类）。
- 加越权测试：用户 B 用自己令牌访问用户 A 的 `conversation_id`，对 detail/stream/delete/fork/WS 全部断言 403/404。

**Warning signs:**
- 隔离 PR 的 diff 只动了 `ConversationListView`。
- 测试只覆盖 list，没有"跨用户直取 id"用例。

**Phase to address:** P-隔离

---

### Pitfall 6: 同步认证类里碰 async ORM / 异步视图里碰惰性 `request.user`

**What goes wrong:**
两个方向的 `sync_to_async` 坑：
1. `AccessTokenAuthentication.authenticate` 是**同步**方法（与 `RunnerTokenAuthentication`、`ChatKeyAuthentication` 一致），内部必须用**同步 ORM**。"令牌即身份"若在这里顺手 `await` / 调异步 ledger / 触发跨表惰性查询，会抛 `SynchronousOnlyOperation` 或事件循环错乱。`token.created_by` 的 FK 访问在同步上下文是安全的，但**别在同步认证里做 async 操作**。
2. 异步视图里按 `request.user` 过滤会话时，`request.user` 可能是惰性对象；在 `async for`/`afilter` 上下文直接解引用其 FK 或 `.is_authenticated` 可能触发同步 ORM。本仓已有正确范式（DetailView 用 `select_related().aget()` 预取，见 views.py:414）。

**Why it happens:**
adrf 异步栈 + 同步认证类混用是本项目核心约束（CLAUDE.md 明确"async ORM 走 sync_to_async"），认证/权限是同步而视图是异步的边界最易踩。

**How to avoid:**
- 认证类内保持纯同步 ORM；user 解析就用 `token.created_by`（同步 FK），不在此处写审计以外的异步逻辑。
- 视图侧过滤：先在异步上下文取到 `user_id = str(request.user.id)`（必要时 `sync_to_async`），再用 `Conversation.objects.filter(created_by_id=user_id)` 的 async 迭代，**不要**在查询里惰性穿透 user 的关联。
- 复用既有 `sync_to_async`/`aget`/`select_related` 范式，别新造桥接。

**Warning signs:**
- 日志出现 `SynchronousOnlyOperation` 或 `You cannot call this from an async context`。
- 认证在高并发下偶发卡顿（同步阻塞混入事件循环）。

**Phase to address:** P-身份（认证侧）、P-隔离（视图侧）

---

### Pitfall 7: 用户 PAT 经 server→runner→task 注入容器——多面泄漏 + 永久令牌放大爆炸半径

**What goes wrong:**
要让 MCP/skill 在容器内以用户身份执行，用户 PAT 必须传进 task 容器。现有链路把敏感值这样传：coding 节点构造 `metadata["env_FRIDAY_TASK_CLAUDE_API_KEY"]`（`coding.py:847`）→ `TaskDispatcher` 把整个 `metadata` 放进 TASK_ASSIGN payload（`dispatcher.py:76`）→ runner `buildContainerEnv` 把 `env_` 前缀 TrimPrefix 后**注入容器环境变量**（`executor.go:122-131`），并且把 `remote_tools` 整段 JSON 塞进 `FRIDAY_REMOTE_TOOLS` env（`executor.go:104`）。把用户 PAT 走同一条路，泄漏面包括：
- **`docker inspect` / `/proc/<pid>/environ` / `ps -e`**：env 对容器内任意进程（含 LLM 生成并执行的代码！）与宿主可见。CONCERNS.md 已将"密钥以明文 env 注入容器"列为现存安全问题。
- **日志**：structlog 的 `redact_credentials` 是**按字段名**脱敏（coding.py:365 只记 `has_api_key` boolean）；但 PAT 若藏在 `remote_tools` JSON / `FRIDAY_REMOTE_TOOLS` env / runner 的 zerolog 里，字段名脱敏**抓不到**。runner（Go）侧无 Python 脱敏处理器。
- **镜像层 / 会话文件**：`task/core/executor.py` 把 session 落盘（`_save_session` 写 JSON 到 `session_dir`）；若把 PAT 写进 prompt/session/usage 文件，会随卷或调试产物长存。
- **永久令牌**：本里程碑 PAT **默认永久、不可延期**（`expires_at=None`）。一旦从某次任务泄漏，攻击者拿到的是**以该用户全权限、永不过期**的钥匙——爆炸半径极大。

**Why it happens:**
现成链路就是"env 明文 + metadata 透传"，复用最省事；脱敏是字段名维度的，覆盖不到透传 JSON 与 Go 侧日志；PAT 默认永久放大了任何泄漏的后果。

**How to avoid:**
- **不要直接注入长期用户 PAT**。优先**短期交换令牌（broker / 一次性 scoped token）**：容器拿到的是任务级、短 TTL、最小权限的派生凭证，任务结束即失效。CONCERNS.md 的推荐同此（"短期 broker token 替代长期 provider key"）。
- 若 MVP 阶段必须传 PAT：用**挂载 tmpfs 密钥文件**而非 env（避免 `docker inspect`/`/proc`/`ps`）；并把 `remote_tools` 里的 token 字段从 payload 剥离，改为容器启动后按需取。
- **Go 侧日志脱敏**：runner 打印 task payload / env 前必须按 key 名（`*TOKEN*`、`*API_KEY*`、`friday_pat_` 值模式）做正则脱敏；`FRIDAY_REMOTE_TOOLS` 不得整段打日志。
- **task 侧**：禁止把 PAT 写进 session/usage/prompt 落盘文件；prompt 注入前对 token 模式做兜底打码。
- PAT 默认永久虽是产品决策，但**注入容器的派生凭证不得永久**；并提供吊销即时生效路径。

**Warning signs:**
- `docker inspect <task容器>` 能看到 `friday_pat_...` 或用户 token。
- runner/任务日志、`FRIDAY_REMOTE_TOOLS` 打印里出现 `friday_pat_` 值。
- 容器内 `env | grep -i token` 出现长期用户令牌。

**Phase to address:** P-注入（必须在"接通链路"的同一阶段做脱敏与凭证降级，不能留作后续）

---

### Pitfall 8: 容器内回调/工具鉴权失败无恢复——任务跑一半令牌被吊销/过期即静默失败

**What goes wrong:**
容器内 agent 用注入的用户令牌回调 server 或调 MCP 工具时，令牌可能在任务执行期间**被用户吊销 / 过期 / 派生失效**。当前 task executor 的错误处理只对 Claude API 的瞬时错误重试（`_is_transient_claude_error`，executor.py:48-51），**认证类错误（401/403）不在重试白名单**，会被当作普通失败吞掉或耗光 turn 重试无意义请求。结果：任务静默失败、产物不完整、用户拿不到明确原因。

**Why it happens:**
重试逻辑是为 LLM 网关 5xx/断流设计的；鉴权失效是新引入的失败类别（之前容器只用 provider key，不用"会被用户随时吊销的"用户令牌），没有对应的失败语义与回传。

**How to avoid:**
- 把"令牌失效（401/403/token revoked）"定义为**不可重试的终止态**，立即结束并通过 callback 回传**明确的结构化错误**（区别于网络瞬时错误），让 server/前端能提示"令牌已失效，请重新生成/绑定"。
- 容器内对 MCP/回调的鉴权失败**不要无限重试**（会刷爆 `access_token_denied` 审计，参考 authentication.py 对"乱 token 灌爆审计表"的顾虑）。
- 设计令牌吊销与在途任务的关系：吊销是否中断在途任务？若是，runner 需有 kill 路径（已有 `KillContainer`/`cancel`）；若否，需说明在途任务用的是短 TTL 派生凭证（见 Pitfall 7）。

**Warning signs:**
- 任务在用户刚吊销令牌后"成功但产物为空"或超时，日志无明确鉴权失败原因。
- `InteractionRun` DENIED 在单个任务窗口内高频出现（容器在重试废令牌）。

**Phase to address:** P-注入 + P-MCP

---

### Pitfall 9: 明文"仅展示一次"在前后端被意外持久化/泄漏

**What goes wrong:**
PAT 明文只在创建响应里返回一次（`models.py` 文档与 `generate_pat()`，DB 只存 `token_hash` + `token_prefix`）。常见破坏：
- 后端把明文写进**日志 / DRF 序列化器的可读字段 / 审计 / 异常堆栈**（DEBUG 下尤其危险）。
- 前端把明文塞进 **Pinia/localStorage/URL query/路由 state**，或在创建后用它发请求时落进网络日志、Sentry。
- "复制成功"toast 之外，组件卸载时明文仍驻留响应缓存（如 TanStack Query 缓存了创建响应）。

**Why it happens:**
"一次性"是约定，不是机制；只要任一层把响应体当普通数据处理就会留痕。

**How to avoid:**
- 后端：创建响应的明文字段**仅在该次响应**出现，序列化器 list/detail **永不**含明文；明文绝不进 logger（structlog 脱敏 + 不传入）。
- 前端：明文只放组件局部 state，**禁止**进全局 store / 持久化 / URL；展示后即提示"关闭后不可再查看"。创建用的 query 结果用完即清（`removeQueries`），不长期缓存含明文的响应。
- 展示靠 `token_prefix`（前 12 位，`models.py:42` 已有）做识别，不回显明文。

**Warning signs:**
- 在浏览器 devtools Application 面板 / localStorage 里能找到 `friday_pat_`。
- 后端日志、Sentry、审计表出现完整明文。

**Phase to address:** P-PAT

---

### Pitfall 10: `token_prefix` 前 12 位暴露过多 + 无盐 sha256 的真实风险边界

**What goes wrong:**
两个常被误判的点：
- `token_prefix` 默认存**明文前 12 字符**（`models.py:42`）。明文形如 `friday_pat_<token_urlsafe(32)>`，前 11 字符是固定前缀 `friday_pat_`，第 12 位才是随机串首字符——**前 12 位几乎只暴露固定前缀 + 1 个随机字符**，识别度低且不泄密，看似安全。但若未来改前缀长度或缩短随机段，"前 N 位"可能逐渐逼近可枚举范围；展示"前后几位"时若**后缀取太多位**（如后 8 位），结合前缀会显著降低剩余熵。
- 有人会担心"sha256 无盐不安全"，要求加盐/加 HMAC，**方向其实搞反了**：本系统 token 是 `secrets.token_urlsafe(32)` ≈ 256bit 高熵随机串，无盐 sha256 对它**足够**（彩虹表/字典攻击对 256bit 随机不成立，无盐反而支持 O(1) 唯一索引精确匹配）。真正该担心的是**比较方式**与**前后缀暴露位数**，不是加盐。

**Why it happens:**
把"低熵口令存储（需加盐慢哈希）"的直觉套到"高熵随机令牌"上；同时低估了"展示前后几位"叠加固定前缀后的熵损失。

**How to avoid:**
- 维持无盐 sha256 + 唯一索引（`hash_token`，contract 锁定，`models.py:18` 注释明确禁止重写），**不要**改 Argon2/加盐——那是给用户密码的，不是给高熵令牌的。
- 展示"前后几位"时严格限位：后缀**最多 4 位**，且文档说明前缀是固定串（识别价值来自随机段而非前缀）。
- 查库匹配走唯一索引精确等值即可；若未来做"按前缀模糊列出"功能，注意别把它变成枚举面。timing 方面：对 256bit 随机令牌的 DB 等值查找，时序侧信道不构成实际可利用攻击（无法据此逼近 token），无需为查找额外做常量时间比较——但**任何明文与明文的字符串比较**（如 chat key 路径）仍必须用 `hmac.compare_digest`（本仓 `ChatKeyAuthentication`、compat 已正确这么做）。

**Warning signs:**
- 有 PR 要把 `hash_token` 改成加盐/Argon2（多半是误解）。
- 展示位数评审时后缀取了 6~8 位。

**Phase to address:** P-PAT

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| MCP 端点维持 `permission_classes=[AllowAny]`，只改认证不收紧 | 不动现有调用方，少改代码 | 匿名洞长期存在；与 CONCERNS.md 已记的 compat AllowAny 同型债 | **Never**（fail-closed 是本项目安全宪法） |
| 用户 PAT 直接以 env 明文注入容器（复用 `env_` 透传链路） | 链路现成、最快接通 RemoteTool | `docker inspect`/`/proc`/日志全暴露 + 永久令牌放大爆炸半径 | 仅 spike 验证；进生产前必须换 tmpfs/短 TTL 派生凭证 |
| 会话隔离用既有"项目级权限"近似代替"per-user owner" | 复用 `PermissionService`，不加字段 | 同项目他人仍可越权访问，隔离名存实亡 | 仅当产品确认"隔离=项目级"时；否则 never |
| 历史会话 backfill 一律归给首个 superuser | 迁移一行搞定 | superuser 越权聚合全员历史；他人会话失联 | **Never**（须按可推断归属或显式无主） |
| 认证类对非 PAT 的 Bearer 抛异常而非返回 None | 实现直白 | 与 JWT 共存时直接吃掉 JWT 请求 | Never（必须前缀闸门 + 返回 None） |
| Go runner 侧不做日志脱敏（沿用现状） | 不动 runner | 用户令牌/密钥随 zerolog 落盘，无 Python 脱敏覆盖 | Never（注入用户令牌后） |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| SimpleJWT + AccessToken 双认证类 | 都用 Bearer，PAT 无前缀闸门先吃掉 JWT | PAT 认证开头 `startswith(PAT_PREFIX)` 否则 return None；JWT 优先或前缀互斥 |
| adrf 异步视图 + 同步认证类 | 在同步 `authenticate` 里调 async/惰性跨表查询 | 同步 ORM only；user 取 `token.created_by`；视图侧先取 `user_id` 再 async 过滤 |
| InteractionRun ledger | 重构身份时改坏 `request.auth`，fingerprint 取不到 | 返回 `(user, token)`，保持 `request.auth` 为 AccessToken；fingerprint 永远是 hash |
| server→runner TASK_ASSIGN payload | 把用户 PAT 塞进 `metadata`/`remote_tools` 透传 | 剥离 token 出 payload；短 TTL 派生凭证 + tmpfs 文件 |
| runner→container env (`buildContainerEnv`) | `env_` 前缀透传任意敏感值，`docker inspect` 可见 | 敏感项走挂载文件；env 仅放非敏感；Go 侧打印前脱敏 |
| task claude-agent-sdk `mcp_servers` 配置 | 把用户令牌写进会落盘的 prompt/session/usage 文件 | 令牌只在内存/请求头；落盘前按 `friday_pat_` 模式打码 |
| WebSocket / SSE 流式入口 | 只给 REST 加隔离过滤，漏 WS/SSE | 流式入口纳入同一 `get_owned_conversation_or_404` 收口与验收清单 |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| `last_used_at` 每请求写库 | 高频 token 调用下写放大、行锁争用 | 已有 60s 节流（authentication.py:39/76），保持；别改成每次写 | 单 token 高 QPS（MCP 工具循环调用）时 |
| 乱 token / 失效 token 高频认证写审计 | `InteractionRun` DENIED 表暴涨 | 不存在 token 不建 run（已有，authentication.py:60-63）；容器侧失效令牌不重试（Pitfall 8） | 容器内令牌失效后无限重试 |
| 会话列表 N+1（隔离后加 owner/project 关联） | 列表接口随会话数变慢 | 过滤用 `created_by_id` 直接条件 + `select_related` 预取，不惰性穿透 | 单用户会话数上千时 |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| MCP/外部端点 AllowAny 默认开放 | 匿名读取代码/RAG/执行工具（CONCERNS.md 已记同型） | fail-closed：要求有效 PAT，移除 AllowAny |
| 用户 PAT 以明文 env 注入容器 | LLM 生成代码 + `docker inspect` 可读取并外泄 | tmpfs 密钥文件 + 短 TTL 派生凭证 + 网络egress 收敛 |
| PAT 默认永久 + 泄漏 | 全权限、永不过期的钥匙落入攻击者 | 注入容器的凭证必须短 TTL；提供即时吊销；考虑可选过期默认 |
| 明文落日志/落盘/落前端存储 | 一次性明文被持久化、可被翻出 | 明文只在创建响应；structlog + Go 双侧脱敏；前端不持久化 |
| 隔离只做列表、漏对象级校验 | IDOR 越权读取/删除/接管他人会话 | 统一 owner 校验收口，全路径（含 WS/SSE）覆盖 |
| 误把高熵令牌当口令加盐/慢哈希 | 浪费且破坏 O(1) 唯一索引匹配（方向错） | 维持无盐 sha256（contract 锁定）；该常量时间比较的是明文字符串比较场景 |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| 明文展示后无"不可再查看"提示 | 用户没保存就关闭，token 永久丢失只能重建 | 创建后强提示"仅此一次"，提供一键复制 + 确认已保存 |
| 令牌列表无 prefix/备注/最近使用 | 多 token 无法区分，不敢删 | 展示 `token_prefix` + 备注 + `last_used_at`，便于识别与吊销 |
| 吊销后无明确反馈在途任务影响 | 用户以为吊销立即生效，结果任务仍在跑 | UI 说明吊销语义（是否中断在途）；失效任务回传清晰错误（Pitfall 8） |
| 隔离上线后历史会话"消失" | 用户恐慌以为数据丢失 | 迁移前公告 + 无主会话有明确归属策略（Pitfall 4） |

## "Looks Done But Isn't" Checklist

- [ ] **令牌即身份:** 常漏 `request.auth` 仍为 token —— 验证 InteractionRun fingerprint 仍正确写入
- [ ] **PAT/JWT 共存:** 常漏前缀闸门 —— 验证 cookie-JWT 与 `friday_pat_*` 各走对分支、乱 Bearer 不吃掉 JWT
- [ ] **MCP 收紧:** 常漏 AllowAny 没换 —— 验证无 token 调 `/api/mcp/tools/*` 被拒（fail-closed）
- [ ] **会话隔离:** 常漏 detail/stream/delete/fork/WS —— 验证用户 B 直取用户 A 的 conversation_id 全部 403/404
- [ ] **历史 backfill:** 常漏无主会话 —— 验证 `created_by__isnull=True` 计数为 0 或有明确归属
- [ ] **容器令牌:** 常漏泄漏面 —— 验证 `docker inspect` + 任务/runner 日志无 `friday_pat_`
- [ ] **令牌失效恢复:** 常漏不可重试语义 —— 验证任务中途吊销令牌时回传明确鉴权错误而非静默失败
- [ ] **明文一次性:** 常漏前端持久化 —— 验证 localStorage/store/URL 无明文

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| AllowAny 匿名洞遗留上线 | MEDIUM | 紧急把 MCP 端点改 IsAuthenticated + 有效 PAT；审计期间匿名访问；通知调用方补令牌 |
| JWT 被 PAT 吃掉（前端集体 401） | LOW | 加前缀闸门 + 调整认证类顺序；热修发版；回归四类请求 |
| 历史会话归属错误（越权/失联） | HIGH | 回滚数据迁移；按可推断源重新回填；通知受影响用户；补越权审计 |
| 用户 PAT 已以 env 泄漏进容器/日志 | HIGH | 吊销受影响令牌（永久令牌尤甚）；改 tmpfs/短 TTL；清理日志/镜像层；轮换 |
| IDOR 越权被发现 | HIGH | 统一 owner 收口热修；审计访问日志评估泄漏范围；补全路径测试 |
| 明文落盘/落库 | MEDIUM | 清理痕迹；吊销暴露令牌；加脱敏；复核序列化器与日志 |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| 1 AllowAny/匿名入口语义突变 | P-身份 + P-MCP | 无 token 调 MCP 被拒；入口清单逐项标注落实 |
| 2 PAT/JWT Bearer 冲突 | P-身份 | 四类请求（cookie-JWT/PAT/过期JWT/乱Bearer）走对分支 |
| 3 InteractionRun 审计断链 | P-身份 + P-MCP | DENIED run fingerprint=hash、raw_request 无明文 |
| 4 历史会话 backfill 归属 | P-隔离（首个 plan） | `created_by__isnull` 计数=0 或显式无主策略 |
| 5 隔离漏过滤 IDOR | P-隔离 | 跨用户直取 id 全路径 403/404（含 WS/SSE） |
| 6 sync/async ORM 桥接 | P-身份 + P-隔离 | 无 SynchronousOnlyOperation；认证纯同步 ORM |
| 7 容器令牌泄漏 + 永久放大 | P-注入（同阶段做脱敏/降级） | `docker inspect`/日志无 PAT；容器凭证短 TTL |
| 8 令牌失效无恢复 | P-注入 + P-MCP | 中途吊销回传明确错误；DENIED 不刷屏 |
| 9 明文一次性被持久化 | P-PAT | 前端无持久化；后端日志/序列化器无明文 |
| 10 前后缀位数 + 哈希误解 | P-PAT | 维持无盐 sha256；后缀≤4 位；明文比较用 compare_digest |

## Sources

- 本仓代码（HIGH）：`server/access_tokens/authentication.py`、`server/access_tokens/models.py`、`server/runners/models.py:16-18`（`hash_token`）、`server/chat/models.py`、`server/chat/views.py`、`server/chat/permissions.py`、`server/chat/authentication.py`、`server/mcp_tools/views.py:141-145`、`server/runners/dispatcher.py`、`server/workflows/nodes/ai/coding.py`、`server/friday/settings.py:264-277`、`runner/internal/docker/executor.go`、`task/core/executor.py`
- 本仓既有审计（HIGH）：`.planning/codebase/CONCERNS.md`（容器无资源/网络隔离、密钥明文 env、compat AllowAny 默认开放、加密静默回退）
- 里程碑意图（HIGH）：`.planning/PROJECT.md`（v0.2.0 Active 需求与约束）
- 通用安全原则（MEDIUM，用于判据方向）：高熵随机令牌 vs 低熵口令的哈希策略差异；DRF 认证链"首个非 None/抛异常胜出"语义；OWASP IDOR/对象级授权

---
*Pitfalls research for: Friday AI v0.2.0 用户身份令牌与 Agent 工具打通*
*Researched: 2026-06-09*
