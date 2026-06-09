# Milestones

## v0.1.0 首启初始化向导 (Shipped: 2026-06-09)

**Phases completed:** 5 phases, 9 plans

**Delivered:** 用「首次访问引导用户自设账号」替代启动期自动建管理员，并在向导内一次配好管理员、LLM 供应商、安全校验与可选的飞书/RAG 集成。

**Key accomplishments:**

- 首启门禁：无任何 superuser 时首次访问自动进入向导，已初始化实例 fail-closed 拒绝（防重入/防接管）
- 管理员自设：向导内自定义用户名+密码（强度校验），提交即建 superuser 并自动登录直达首页
- 供应商一键预设：DeepSeek V4 Pro / MiMo V2.5 Pro / Kimi 2.6 / Anthropic 官方 / 自定义端点，Fernet 加密落库 + 健康校验 + 绑定 Claude Code 模型映射
- 安全与可选集成：SECRET_KEY/FRIDAY_ENCRYPTION_KEY 风险校验（非阻塞）+ 可一键跳过的飞书、向量检索（Qdrant/Embedding）配置步骤
- 向后兼容：`entrypoint.sh` 默认不再自动建号，`init_superuser`/`reset_superuser_password` 保留为运维兜底，老部署升级不回退

**Known deferred items at close:** 2 — Phase 01 / 02 人工验收（UAT）签字未完成（功能已实现，详见 STATE.md Deferred Items）

---

## v0.2.0 用户身份令牌与 Agent 工具打通 (Shipped: 2026-06-10)

**Phases completed:** 6 phases (6-11), 21 plans

**Delivered:** 给每个用户一套 GitHub/GitLab 风格的个人访问令牌（PAT），以「用户身份 + 用户权限」贯通认证、会话隔离、管理员只读后台与 agent 工具链路，使 skill/mcp 能以用户令牌在容器内执行。

**Key accomplishments:**

- PAT 模型增强：令牌加名称/备注/可选有效期（默认永久、不可延期）+ 前缀…后缀指纹，明文仅展示一次（仅存 sha256），用户自助创建/吊销
- 令牌即用户身份（认证地基）：PAT 认证返回 owner 并施加其 RBAC（替代「有效即全权限」），friday_pat_ 前缀闸门让 PAT/JWT 互不干扰，MCP/工具入口收紧为 fail-closed
- 对话/会话用户隔离：Conversation 加 created_by + 历史回填最早 superuser，全 25 路径按 owner 过滤（含 SSE/WebSocket），越权 404 不泄漏存在性
- 管理员只读会话后台：物理隔离的 /api/admin/conversations/（IsSuperUser）浏览所有会话，只读防误操作，交互需 fork 到自己名下
- MCP 绑定 + RemoteTool 执行端点：ToolTokenBinding 持久绑定令牌给 skill/mcp，新增经 PAT 认证 fail-closed 的按工具 name 执行端点供容器回调
- task 容器接通（链路机制闭环）：容器消费 remote_tools 经 SDK MCP server 加载工具，PAT 经 server→runner→task 直传注入并全程脱敏，令牌吊销 graceful（在途跑完仅阻断新调用）

**Stats:** ~6,200 行净增（60 文件，server/web/runner/task），150 commits，2026-06-09 → 2026-06-10。

**Known deferred items at close:** 6 — Phase 6-11 人工验收（UAT）顺延（自动化全绿，浏览器/容器级 E2E 待人工确认，详见 STATE.md Deferred Items）。

**Known follow-ups (tech debt, by-design):**

- Phase 11 实时明文 PAT 通道（contextvar）未接入：_resolve_user_pat 恒返回 ''，RemoteTool 链路端到端休眠、ToolTokenBinding 暂未被执行路径消费（受 PAT-02 明文不落盘约束的有意推迟，Open-Q1 Option C）
- MCPB-02 集成 PARTIAL：执行端点已按 PAT 认证为 owner，但 execute_tool 未接收 user 上下文
- Nyquist 卫生：各阶段 *-VALIDATION.md frontmatter nyquist_compliant 仍为 false（仅标志位未回填）

---
