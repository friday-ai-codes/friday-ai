# Project Research Summary

**Project:** Friday AI — v0.2.0「用户身份令牌与 Agent 工具打通」
**Domain:** Brownfield 增量 — 个人访问令牌（PAT-as-identity）+ 会话用户隔离 + MCP/RemoteTool 用户令牌注入 claude-agent-sdk 容器（Django 5.1 / Python 3.14 异步栈）
**Researched:** 2026-06-09
**Confidence:** HIGH（结论几乎全部基于现有代码实读 + claude-agent-sdk MCP API 经 Context7 官方文档核对）

## Executive Summary

本里程碑是一条**几乎零新增依赖**的 brownfield 改造：把 Friday 现有的 `AccessToken`（个人访问令牌）从"有效即全权限"升级为 GitHub/GitLab 风格的"令牌即身份"，并以此为地基打通会话隔离与 Agent 工具链。四份调研一致指向同一结论——**所有能力都能在现有栈内实现**：后端 0 个新 PyPI 包，task 容器 0 个新包（`claude-agent-sdk==0.1.58` 已自带 `mcp_servers` + `@tool` + `create_sdk_mcp_server`），runner 0 个新 Go 依赖。唯一的"看似新增"是两个 Django schema 迁移（`AccessToken` 加 `description`/后缀字段、`Conversation` 加 `created_by` FK）。功能侧对照 GitHub/GitLab 核对后确认 Friday 的两项关键决策方向正确：「不可延期」与行业共识一致；「默认永久」与标杆方向相反（GitLab 16.0 已彻底移除永不过期），属自托管长跑场景的刻意权衡，须配安全提示。

推荐路径是一条清晰的依赖链：**认证地基（令牌即 owner 身份）→ 对话隔离 → 工具反向执行端点 + 令牌注入 → task 容器接通**。核心改动其实只有一处——把 `AccessTokenAuthentication.authenticate()` 的返回从 `(None, token)` 改为 `(token.created_by, token)`（配 `select_related` 预取），此后 DRF 既有的 `IsAuthenticated` + `PermissionService` 权限链全部自动接管，不引入任何新授权库。工具链路则用进程内 SDK MCP proxy：容器只持短时令牌、经 `/api/tools/execute/` 回调 server，真实执行与第三方凭证解析始终留在 server 侧，容器攻击面最小。

最高优先的风险有三类，且都集中在"语义突变"而非"新功能"：**令牌泄漏**（用户 PAT 经 env 明文注入容器 → `docker inspect`/`/proc`/日志全暴露，叠加"默认永久"使爆炸半径极大）、**认证语义突变**（改返回 user 会让 `AllowAny`/匿名入口静默翻转，且 PAT 与 SimpleJWT 共用 Bearer 头会互相吃请求）、**历史会话迁移**（存量 `Conversation` 无 `created_by`，回填策略错误会造成越权聚合或全员会话失联）。三者都必须在引入对应能力的**同一阶段**连同防护一起交付，不能留作后续。

## Key Findings

### Recommended Stack

详见 [STACK.md](./STACK.md)。结论是"复用既有栈、几乎零新增依赖"——三项新能力全部落在 DRF `BaseAuthentication`、stdlib `secrets`/`hashlib`、`asgiref.sync_to_async`、已装的 `claude-agent-sdk` 与 `httpx` 之内。明确**不要新增**：`PyJWT`/任何 JWT 库、`djangorestframework-api-key`、`django-guardian`、容器内重装 `mcp`/`anthropic`，也**不要**把 claude-agent-sdk 升到 0.2.x（本里程碑用到的 MCP/工具 API 在 0.1.58 已具备，且 server pyproject 显式钉 `<0.2`）。

**Core technologies（全为"复用既有"）:**
- **DRF `BaseAuthentication`（返回 owner）**：令牌即身份的唯一核心机制 — 改返回 `(user, auth)` 后既有权限链自动生效，无需新机制
- **`secrets` + `hashlib`(sha256)**：PAT 生成/校验 — 已在用；令牌元数据增强纯属模型字段，零新依赖（且高熵随机令牌**维持无盐 sha256**，勿误改 Argon2/加盐）
- **`asgiref.sync_to_async` + `select_related`**：同步认证类 ↔ adrf 异步 view 的桥接 — 现有约束，认证里预取 `created_by` 防 async `SynchronousOnlyOperation`
- **`claude-agent-sdk==0.1.58`（保持不变）**：容器内进程内 SDK MCP server 把 `remote_tools` 暴露给 agent — 自带 `mcp_servers`/`@tool`/`create_sdk_mcp_server`
- **`httpx`（task 已装）**：容器内工具 handler 回调 server execute 端点，注入 `Authorization: Bearer <用户PAT>`
- **`cryptography` Fernet（已装）**：**仅**第三方/外部 MCP secret 落库时加密；Friday 自签 PAT 不落明文，大多场景用不到

### Expected Features

详见 [FEATURES.md](./FEATURES.md)。对照 GitHub/GitLab 核对后，本里程碑 5 项 active 需求**全部属于 MVP**，构成一条依赖链（#1→#2→#4→#5，#3 并行），缺任一环价值闭环断裂。

**Must have（table stakes）:**
- **令牌名称 + 备注（description）** — GitHub(Note)/GitLab(description) 都有，用户靠它区分令牌用途（需新增 `description` 字段）
- **明文仅展示一次 + 一键复制** — 已实现
- **可选过期（默认永久、不可延期）** — 改表单默认 90天→永久，去掉任何延期入口
- **指纹：展示前缀 + 后 4 位** — 当前 `token_prefix` 取明文前 12 字符 ≈ 只比固定前缀多 1 字符，列表里几乎无法区分（需新增 `token_suffix`）
- **令牌即所有者身份 + 继承其 RBAC 权限** — 里程碑核心语义，替换"有效即全权限"
- **会话只看自己的（按 `created_by` 全路径过滤）** — 多用户隐私底线，缺了即数据泄露级缺陷

**Should have（competitive / 差异化）:**
- **令牌在平台内绑定 skill/mcp + 服务端注入容器** — 标杆要用户手抄 `Authorization: Bearer` 进客户端 config，Friday 让用户平台内绑定、运行时服务端注入，免手抄、可集中吊销
- **RemoteTool 链路接通：容器内 agent 以用户令牌真跑 skill/mcp** — 对裸 MCP 客户端的核心增量，端到端"需求→agent→调用用户授权工具"闭环

**Defer（v2+，本期明确不做 / anti-feature）:**
- **细粒度 scope（读写/项目/资源分权）** — 本期显式排除；继承 owner 全部 RBAC（与 GitLab 默认一致），scope 留作未来里程碑
- **令牌 rotate / 到期提醒 / 自动轮换** — 与"默认永久"冲突，独立工作量，列 backlog
- **令牌延期（extend expiry）** — 行业共识反对（延长泄露窗口），GitHub/GitLab 均不提供
- **共享会话空间 / 团队工作区 / 会话转交** — 与"只看自己"正交且更复杂，先把隔离做对
- **per-token 用量分析 / 审计大盘** — `last_used_at` 已够基本判活
- **MCP OAuth 2.1 / 设备授权流** — 自托管内网静态 Bearer 已足够，OAuth 链路过重

### Architecture Approach

详见 [ARCHITECTURE.md](./ARCHITECTURE.md)。所有改动接入既有惯例、不发明新模式，落到具体文件/类/函数并标注 NEW/MOD，跨进程（server/runner/task）契约同步点逐一列明。核心是把单点认证改造扩散到既有权限链与既有 `env_` 前缀注入通道，task 侧用进程内 MCP proxy 让执行始终回到 server。

**Major components:**
1. **认证层 `AccessTokenAuthentication`（MOD）** — `(None, token)`→`(token.created_by, token)` + `select_related`；`interactions.entry` re-export 使一处改动全局生效；`request.auth` 保持为 token 实例不动（审计血脉）
2. **API 视图层（MOD + NEW）** — `mcp_tools` `AllowAny`→`IsAuthenticated`（fail-closed）；chat 各入口加 ownership 校验复用 `PermissionService.has_project_access`；NEW `tools/views.ExecuteRemoteToolView`（PAT 认证的 RemoteTool 执行端点，`tools/` 当前无对外 HTTP 入口）
3. **持久层（MOD）** — `Conversation` 增 `created_by` FK（`null=True` + 索引 + data migration 回填）；`AccessToken` 增 `description`/后缀元数据字段
4. **跨进程注入链（MOD 小 + NEW）** — server 在 dispatch 时 mint 短时令牌 → 复用 runner `buildContainerEnv` 的 `env_` 前缀通道注入（runner 近零改动，仅对齐 `FRIDAY_TASK_REMOTE_TOOLS` env 名）→ task 读取并装配 `create_sdk_mcp_server` proxy

**Build order（A→B→C→D→E，关键路径 A1→(A2/B0/C1)→D→E）:**
- **Phase A 认证地基**：A1 改 `authenticate` 返回 user + `select_related`（单点地基，无依赖）；A2 `mcp_tools` 收紧 `IsAuthenticated`
- **Phase B 对话隔离**（依赖 A 的可靠身份，B1 迁移可与 A 并行）：B0 chat 视图挂 `AccessTokenAuthentication`；B1 加 `created_by` + schema/data 迁移；B2 `ConversationService` 收敛过滤；B3 各入口 ownership 校验（含 detail/delete/stream/WS）
- **Phase C 工具反向端点**（依赖 A1）：NEW `ExecuteRemoteToolView` + urls 注册
- **Phase D 令牌注入**（依赖 C）：D1 短时 token mint+revoke；D2 dispatch 注入 `env_FRIDAY_TASK_USER_TOKEN`/`API_URL`；D3 runner remote_tools env 改名对齐
- **Phase E task 接通**（依赖 C 端点 + D 令牌）：E1 `config.py` 读 remote_tools/user_token/api_url；E2 `executor.py` 装配 `mcp_servers` proxy

### Critical Pitfalls

详见 [PITFALLS.md](./PITFALLS.md)（10 个坑均落到具体代码路径）。最高优先的三类风险：

1. **令牌泄漏 + 永久令牌放大爆炸半径**（Pitfall 7，P-注入）— 用户 PAT 走 `env_` 明文注入会被 `docker inspect`/`/proc`/`ps`/runner zerolog 看到（Go 侧无 Python 字段名脱敏），叠加"默认永久"使一次泄漏=全权限永不过期的钥匙。**避免：** 不直接注入长期 PAT，改 dispatch 时 mint 短 TTL 派生令牌、任务结束即 revoke；优先 tmpfs 密钥文件而非 env；Go 侧打印前按 key 名/值模式脱敏；task 侧禁止把令牌写进 session/usage/prompt 落盘文件。
2. **认证语义突变：`AllowAny`/匿名入口静默翻转**（Pitfall 1，P-身份+P-MCP）— 改返回 user 后，按"匿名也放行"写的入口语义翻转；`mcp_tools` 仍 `AllowAny` 则匿名洞依旧。**避免：** 改认证返回值与逐入口 audit 绑成同一阶段交付，禁止只改认证不改权限；建挂 `AccessTokenAuthentication` 的入口清单逐项标注；MCP 端点 **fail-closed**（要求有效 PAT）。
3. **PAT 与 SimpleJWT 共用 Bearer 头互相吃请求**（Pitfall 2，P-身份）— 二者都用 `Authorization: Bearer`，当前 PAT 认证对任意 Bearer 不校验前缀就查库、查不到即抛 401，会吃掉 JWT 的 `eyJ...` 请求（本仓 chat 已踩过同型坑）。**避免：** PAT 认证开头加 `if not plaintext.startswith(PAT_PREFIX): return None` 闸门，仅前缀匹配但查库失败才抛 `AuthenticationFailed`；明确认证类顺序；加四类 Bearer（cookie-JWT/PAT/过期JWT/乱Bearer）契约测试。
4. **历史会话 backfill 归属错误**（Pitfall 4，P-隔离首个 plan）— 存量 `Conversation` 无 `created_by`，归给首个 superuser=越权聚合全员历史；留 null + 过滤写错=全员失联或隔离失效。**避免：** 迁移分两步（加 null 列 + 索引 → data migration 按可推断归属源回填），无主会话显式标记策略写进 Key Decisions，回填完成前不收紧 `null=False`。
5. **会话隔离漏过滤 IDOR**（Pitfall 5，P-隔离）— 只在 list 加过滤、detail/stream/delete/fork/WS 按 id 直取忘了对象级校验。**避免：** 收口 `get_owned_conversation_or_404(user, id)`，所有按 id 取会话入口必经它；SSE 与 WebSocket 列入同阶段验收；加跨用户直取 id 全路径 403/404 测试。

## Implications for Roadmap

研究强烈建议沿依赖链分 5 个能力切片（与 ARCHITECTURE 的 Phase A–E 对齐）。每个切片都把对应的防护/验收**内置**，而非留作后续。

### Phase 1: PAT 模型增强 + 一次性明文（P-PAT）
**Rationale:** 纯模型/序列化/前端增量，无认证语义风险，可独立先行；为后续"令牌即身份"提供可信 owner 与可识别指纹。
**Delivers:** `AccessToken` 加 `description` + `token_suffix`（后 ≤4 位）；表单默认改"永久" + 安全提示；自助增删（已实现，补识别字段）。
**Addresses:** FEATURES table stakes #1（名称+备注/默认永久/前后几位/自助增删）。
**Avoids:** Pitfall 9（明文一次性被前后端持久化）、Pitfall 10（后缀位数过多 + 误把高熵令牌当口令加盐）。

### Phase 2: 令牌即用户身份（P-身份，认证地基）
**Rationale:** 单点地基，全链路前置；ARCHITECTURE 关键路径起点 A1。
**Delivers:** `authenticate` 返回 `(token.created_by, token)` + `select_related`；`mcp_tools` `AllowAny`→`IsAuthenticated`；保持 `request.auth` 为 token 实例。
**Uses:** DRF `BaseAuthentication` + 既有 `PermissionService`（零新授权库）。
**Implements:** 认证层 + API 视图层收紧。
**Avoids:** Pitfall 1（语义突变 fail-closed）、Pitfall 2（PAT/JWT Bearer 前缀闸门）、Pitfall 3（InteractionRun 审计 fingerprint 不被改坏）、Pitfall 6（同步认证里勿碰 async ORM）。

### Phase 3: 对话/会话用户隔离（P-隔离）
**Rationale:** 多用户隐私底线；依赖 Phase 2 的可靠身份，但 schema 迁移可与 Phase 2 并行起步。
**Delivers:** `Conversation.created_by` FK + schema/data 迁移；`ConversationService` 收敛过滤 + `get_owned_conversation_or_404` 收口；list/detail/create/delete/stream/WS 全路径校验。
**Addresses:** FEATURES table stakes #3（会话只看自己的）。
**Avoids:** Pitfall 4（backfill 归属——本阶段第一个 plan）、Pitfall 5（漏过滤 IDOR，含 WS/SSE）、Pitfall 6（视图侧惰性 `request.user`）。

### Phase 4: RemoteTool 执行端点 + 用户令牌注入（P-MCP + P-注入 server/runner 侧）
**Rationale:** 依赖 Phase 2 的 PAT 认证；先有可调用端点与安全注入通道，task 侧接通才有意义。
**Delivers:** NEW `tools/views.ExecuteRemoteToolView`（PAT 认证）+ urls 注册；短时令牌 mint+revoke；dispatch 注入 `env_FRIDAY_TASK_USER_TOKEN`/`API_URL`；runner remote_tools env 改名对齐 + Go 侧日志脱敏。
**Addresses:** FEATURES 差异化 #4（平台内绑定 + 服务端注入）。
**Avoids:** Pitfall 7（令牌泄漏——脱敏与短 TTL 派生凭证必须同阶段做）、Pitfall 1/3（执行端点也是认证入口）。

### Phase 5: task 容器接通（P-注入 task 侧）
**Rationale:** 价值闭环终点；依赖 Phase 4 端点 + 令牌。
**Delivers:** `task/core/config.py` 读 remote_tools/user_token/api_url；`task/core/executor.py` 装配 `create_sdk_mcp_server` + `@tool` proxy 挂 `ClaudeAgentOptions(mcp_servers=...)`；鉴权失效（401/403/revoked）定义为不可重试终止态、回传结构化错误。
**Addresses:** FEATURES 差异化 #5（agent 以用户身份真跑 skill/mcp）。
**Avoids:** Pitfall 7（落盘文件勿写令牌）、Pitfall 8（令牌中途失效无恢复——不可重试 + 明确错误回传）。

### Phase Ordering Rationale
- **依赖链决定顺序**：#1→#2→#4→#5 是硬依赖（令牌须先有 owner 才能"即身份"，须先有身份才能注入容器执行）；#3（隔离）在 #2 后可与 #4/#5 并行。
- **架构分组**：Phase A–E 的关键路径 A1→(A2/B0/C1)→D→E 已由 ARCHITECTURE 验证；A1 单点地基放最前，B 可并行，C+D+E 是工具打通主链。
- **避坑分组**：每个"语义突变/泄漏"风险都与引入它的能力同阶段交付防护——认证收紧与改返回值绑死（Pitfall 1/2/3）、backfill 与隔离绑死（Pitfall 4/5）、脱敏与令牌注入绑死（Pitfall 7/8），杜绝"先接通后补安全"的技术债。

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 5（task 接通）：** claude-agent-sdk 0.1.58 的 `create_sdk_mcp_server`/`@tool`/`mcp_servers` 具体签名在 ARCHITECTURE 中标为 MEDIUM（依据 SDK 训练知识 + milestone 上下文），STACK 已用 Context7 官方文档核对为 HIGH——计划时建议用 `/gsd-plan-phase --research-phase` 实测 `allowed_tools` 的 `mcp__friday__<tool>` 前缀规则与进程内 server 装配。
- **Phase 4（令牌注入安全）：** 短 TTL 派生凭证的具体形态（mint 短时 AccessToken vs tmpfs 文件 vs broker）与 Go 侧脱敏正则需要落实方案，属安全敏感、值得专研。

Phases with standard patterns（skip research-phase）:
- **Phase 1（PAT 增强）：** 纯模型/序列化/前端增量，既有 `AccessToken` + RevealDialog 已有范式。
- **Phase 2（令牌即身份）：** DRF `BaseAuthentication` 契约 + 既有 `PermissionService` 范式，改动单点且文档充分。
- **Phase 3（会话隔离）：** chat 既有端点已大量使用 `PermissionService.has_project_access` + `sync_to_async`/`select_related`，照搬即可。

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | 核心结论"复用既有栈、几乎零新增依赖"基于仓库代码实读；claude-agent-sdk MCP API 经 Context7 官方文档（597 snippets）+ PyPI 核对 |
| Features | HIGH | GitHub/GitLab 官方文档逐字段核对（description 17.7、永不过期 16.0 移除、继承用户权限语义）；Friday 现状基线直接读代码 |
| Architecture | HIGH | 集成点全部具体到现有文件/行号（authentication.py/views.py/executor.go/config.py）；唯 claude-agent-sdk `mcp_servers` 具体签名为 MEDIUM |
| Pitfalls | HIGH | 10 个坑均落到本仓具体代码路径 + CONCERNS.md 既有审计；判据方向（高熵令牌 vs 口令哈希、DRF 认证链语义、IDOR）为 MEDIUM 但与官方一致 |

**Overall confidence:** HIGH

### Gaps to Address（须在需求阶段决策的 Open Questions）

以下问题四份调研均标记为"需 roadmap/需求阶段拍板"，逐一汇总供决策：

- **会话归属回填策略**：存量 `Conversation` 无 `created_by`，回填归谁？候选：(a) 归最早的 superuser（确定性强但会让该 superuser 越权聚合全员历史）；(b) 全留 `null` 视为"legacy/仅 superuser 可见"（升级零风险但普通用户看不到历史会话）；(c) 按可推断归属源（project 成员/最早 message 发起者/OrchestrationRun user）回填，无法推断者显式标"无主"。`projects/models.py` 已确认**无 owner 字段**，无法按项目所有者回填。需写进 Key Decisions。
- **superuser 是否可见全部会话**：隔离语义下 superuser 是否短路放行看所有人会话（与 `PermissionService` superuser 短路一致），还是 superuser 也只看自己的？影响过滤实现与"无主会话谁可见"。
- **令牌绑定 MCP 的形态**：用户"把令牌绑定给 skill/mcp"如何建模？候选：(a) 最简——dispatch 时按 owner 即时 mint 短时 token，**无需新表**；(b) 持久绑定——NEW 表（user↔token↔tool 作用域）。决定是否需要新 schema。
- **容器内令牌形态：短 TTL 派生凭证 vs 直传长期 PAT**：MVP 是否必须直传 PAT？推荐短 TTL 派生 + tmpfs 文件而非 env 明文。若 MVP 必须传 PAT，须明确降级方案（tmpfs + payload 剥离 token 字段 + Go 脱敏）。直接关系 Pitfall 7 的爆炸半径。
- **吊销是否中断在途任务**：用户吊销/令牌过期时，正在跑的 task 容器如何处理？候选：(a) 中断——runner 走已有 `KillContainer`/`cancel` 路径；(b) 不中断——则在途任务必须用短 TTL 派生凭证（与上一条耦合），并在 UI 说明吊销语义。同时定义"令牌失效"为不可重试终止态、回传结构化错误（Pitfall 8）。
- **chat 端点对 Anonymous 的处理**：`ChatAuthPermission` 开关关闭时全放行；隔离需要真实用户，是把对话端点改 `IsAuthenticated` 还是对 Anonymous 显式降级？
- **令牌"前后几位"展示位数**：后缀严格 ≤4 位（叠加固定前缀避免熵损失），需求阶段确认展示规格（Pitfall 10）。

## Sources

### Primary (HIGH confidence)
- `/anthropics/claude-agent-sdk-python`（Context7，597 snippets）— `ClaudeAgentOptions.mcp_servers`（stdio/sse/http/sdk 四类型）、`@tool` 签名、`create_sdk_mcp_server`、`mcp__server__tool` 规则
- GitHub Docs — REST API personal access tokens（字段 `token_name/token_expired/token_expires_at/token_last_used_at`）
- GitLab Docs — Personal access tokens（description 17.7、永不过期 16.0 移除、"inherit permissions from the user who created them"）+ Account/limit settings（强制过期、最大寿命 365/400 天）
- Claude Code MCP Docs / github-mcp-server README — `Authorization: Bearer <PAT>` header、内部工具静态 Bearer 即可
- Friday 仓库代码实读 — `server/access_tokens/{authentication,models}.py`、`server/interactions/entry.py`、`server/mcp_tools/views.py`、`server/chat/{models,views,permissions,authentication,conversation_service}.py`、`server/permissions/{models,services}.py`、`server/tools/{executor,registry,models,sources/*}.py`、`server/runners/dispatcher.py`、`server/workflows/nodes/ai/coding.py`、`runner/internal/docker/executor.go`、`runner/internal/ws/client.go`、`task/core/{config,executor,runner}.py`、`task/integrations/callback.py`
- Friday 既有审计 — `.planning/codebase/CONCERNS.md`（密钥明文 env 注入、compat AllowAny 默认开放、容器无网络隔离）、`.planning/codebase/ARCHITECTURE.md`、`.planning/PROJECT.md`

### Secondary (MEDIUM confidence)
- PyPI `claude-agent-sdk`（最新 0.2.94 / 项目钉 0.1.58）
- Augment Code 指南（`claude-code-sdk`→`claude-agent-sdk` 重命名、Python 版本支持）— 二手但与官方一致
- Agent Patterns Catalog / LangGraph 多租户隔离（按 user_id 过滤、DB 层兜底、个人 vs 共享空间）
- claude-agent-sdk 0.1.58 `mcp_servers` 具体签名（milestone 上下文 + SDK 知识，待 Phase 5 实测确认）

### Tertiary (LOW confidence)
- 通用安全原则（高熵随机令牌 vs 低熵口令哈希策略、DRF 认证链"首个非 None/抛异常胜出"语义、OWASP IDOR/对象级授权）— 用于判据方向，需在测试中验证

---
*Research completed: 2026-06-09*
*Ready for roadmap: yes*
