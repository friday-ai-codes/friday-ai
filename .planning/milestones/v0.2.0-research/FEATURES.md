# Feature Research

**Domain:** 个人访问令牌（PAT）+ 令牌即身份 + 会话用户隔离 + Agent/MCP 工具令牌打通（自托管研发自动化平台）
**Researched:** 2026-06-09
**Confidence:** HIGH（GitHub / GitLab 官方文档核对）

> 本里程碑（v0.2.0）为 brownfield。下文每个功能均对照 **Friday 现状基线** 标注，并打 `table stakes / differentiator / anti-feature`、复杂度、与既有能力的依赖。

---

## 0. 对照标杆：GitHub / GitLab PAT 真实行为（核对结论）

| 维度 | GitHub | GitLab | Friday 现状 | 差距 |
|------|--------|--------|-------------|------|
| **列表字段** | `token_name`、`token_expired`、`token_expires_at`、`token_last_used_at`、`created_at`（fine-grained REST 列表返回）；classic 有 `Note` 字段 | `name` + **`description`（17.7 引入）**、`expires_at`、`last_used_at`、`created_at`、scopes | name / token_prefix / created_at / expires_at / last_used_at / 状态 | 缺 **description/备注** |
| **创建流程** | 设名称 → 选 scope/过期 → 明文仅显示一次（`ghp_` / `github_pat_` 前缀），离开页面不可再看 | 设名称 → 可选 description → 选过期（**不能选"永不过期"**）→ 明文仅显示一次 | 设名称 → 过期策略（90天默认/永不/自定义）→ 明文仅一次（已实现） | 默认值方向相反（见下） |
| **过期默认** | 推动设置过期；fine-grained 默认 30 天，可选 custom | **16.0 起移除"永不过期"**；不填则默认 = 最大允许寿命（默认 365 天，flag 可到 400） | 表单默认 **90 天**；支持 null=永久 | 里程碑要改成 **默认永久** ←→ 标杆在往"强制过期"走 |
| **能否延期** | 不能延期；只能 **regenerate**（生成新明文） | 不能延期；提供 **rotate**（API 生成新串并吊销旧串），到期发提醒邮件 | 仅吊销，无延期/轮换 | "不可延期" **与标杆一致**；缺 rotate（本期不做） |
| **令牌=身份** | 携带 PAT = 以令牌所有者身份调用；fine-grained 叠加 scope | 官方明确：**"By default, they inherit permissions from the user who created them"** | 现状"有效即全权限"（不区分所有者权限） | 里程碑核心：改为继承所有者权限 |
| **指纹标识** | 列表显示有意义前缀（`ghp_xxxx`，前缀后字符各不相同） | 类似 | `token_prefix` = 明文前 12 字符，而 `friday_pat_` 前缀本身就 11 字符 → **几乎所有 token 显示同一串，无法区分** | 需补"后几位"才能识别（里程碑已意识到） |

**关键洞察（来自核对）：**
1. **"不可延期"是行业共识**：GitHub/GitLab 都不允许延长已有令牌寿命——到期即换新串（regenerate / rotate）。理由：长寿命密钥一旦泄露窗口无限放大；时间盒（time-box）+ 轮换才是安全模型。Friday "不可延期" 决策 **正确且与标杆一致**。
2. **"默认永久"与标杆方向相反**：GitLab 已在 16.0 **彻底移除永不过期令牌**，GitHub 默认强制短过期。Friday 选"默认永久"是面向自托管单租户研发自动化（长跑工作流不想频繁换证）的 **刻意权衡**，可接受，但应在 UI 给出安全提示，并把"轮换"留作后续。
3. **Friday `token_prefix` 当前形同虚设**：`PAT_PREFIX="friday_pat_"`（11 字符），而 `token_prefix` 取明文前 12 字符 → 实际只多 1 个区分字符，列表里所有令牌"指纹"几乎一样。里程碑"展示前后几位"正是修这个识别性缺陷。

---

## Feature Landscape

### Table Stakes（用户预期，缺了就"不完整"）

| Feature | Why Expected | Complexity | 依赖既有 / Notes |
|---------|--------------|------------|------------------|
| **令牌名称 + 备注（description）** | GitHub(Note)/GitLab(description) 都有；用户靠它区分"哪个令牌给了谁/干啥" | LOW | 既有 `name` 已有；**新增 `description` 字段**（model + serializer + 表单 + 列表列） |
| **明文仅展示一次 + 一键复制** | 所有 PAT 产品的硬约束；明文不落盘 | LOW | **已实现**（RevealDialog + 内存 ref，DB 只存 hash） |
| **可选过期时间（默认永久、不可延期）** | 用户预期能设过期；"不可延期"与 GitHub/GitLab 一致 | LOW | 既有 `expires_at`(null=永久) 已有；**改表单默认 90天→永久**；去掉任何"延期"入口 |
| **指纹：展示前 + 后几位** | 列表必须能区分多个令牌（当前前缀几乎不可区分） | LOW | **新增 `token_suffix`（明文后 4 位）**；前缀逻辑需取静态前缀之后的字符；类似密码尾号提示 |
| **列表展示创建时间 / 最后使用 / 过期 / 状态** | 用户判断"还在用吗、何时失效" | LOW | **已实现**（`created_at`/`last_used_at`/`expires_at`/状态徽标） |
| **用户自助新增 / 删除（吊销）** | 个人凭证必须自助管理，不走管理员 | LOW | **已实现**（create + revoke 软吊销 + 二次确认） |
| **令牌即所有者身份 + 继承其权限** | GitLab 官方默认语义；携带 token = 以该用户身份 + 其 RBAC 访问 | MEDIUM | 既有 `created_by` 已有；**改鉴权后端**：从"有效即全权限"→ 以 owner 身份注入 request.user 并施加其 permissions |
| **会话只看自己的（按用户过滤）** | 多用户系统隐私底线；用户不预期看到他人对话 | MEDIUM | 既有 chat 无隔离；**list/detail/create/delete/stream 全路径按 `created_by` 过滤**；需对话归属字段（可能要迁移） |

### Differentiators（差异化价值，非必须但加分）

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **令牌在 Friday 内绑定给 skill/mcp（服务端注入）** | 标杆做法是用户手动把 `Authorization: Bearer <token>` 抄进客户端 config；Friday 让用户在平台内生成并"绑定到工具"，运行时由服务端注入容器 → 免手抄、可集中吊销 | MEDIUM-HIGH | 依赖 PAT(#1) + 令牌即身份(#2)；令牌须 Fernet 加密存储（复用既有凭证加密路径） |
| **RemoteTool 链路接通：容器内 agent 以用户令牌真跑 skill/mcp** | 端到端打通"需求→agent→调用用户授权的工具"，是平台对裸 MCP 客户端的核心增量 | HIGH | 依赖 #4；跨进程 server↔runner↔task；`remote_tools` 契约需三端同步（Go runner + Python task） |
| **永久令牌 + 长跑工作流友好** | 自托管研发自动化的长期凭证不想频繁换 → 比 GitLab"强制 365 天"更贴合本场景 | LOW | 是权衡而非纯优点：**必须配安全提示**；后续补 rotate 才完整 |

### Anti-Features（本期明确不做 / 看似该有实则添乱）

| Feature | Why Requested | Why Problematic（本期） | Alternative |
|---------|---------------|------------------------|-------------|
| **细粒度 scope（读/写、按项目/资源分权）** | 最小权限原则 | 需要完整权限模型 + UI + 校验；里程碑已显式排除；GitLab 默认本就"继承用户全部权限" | **本期：令牌继承所有者 RBAC 全权限**（与 GitLab 默认一致），scope 留作未来里程碑 |
| **强制过期 / 到期前邮件提醒 / 自动轮换** | 安全合规（对齐 GitHub/GitLab 现行方向） | 与本期"默认永久"决策冲突；轮换链路是独立工作量 | 本期仅"可选过期 + 安全提示"；rotate/提醒列入 backlog |
| **令牌延期（extend expiry）** | 用户图省事不想换证 | 行业共识反对（延长泄露窗口）；GitHub/GitLab 均不提供 | 不做；到期→新建（未来 rotate） |
| **共享会话空间 / 团队工作区 / 会话转交** | 协作需求 | 与"只看自己"隔离正交且更复杂；先把隔离做对 | 本期只做 **个人会话私有**；共享空间留未来 |
| **per-token 用量分析 / 审计大盘** | 可观测 | 超出本期；`last_used_at` 已足够基本判活 | 仅保留 `last_used_at`；审计大盘 backlog |
| **MCP OAuth 2.1 / 设备授权流** | "更正规"的鉴权 | 自托管内网场景静态 Bearer 已足够（官方亦认可内部工具用 Bearer）；OAuth 链路重 | **静态 Bearer = 用户令牌**，与 Friday"令牌即身份"天然契合 |

---

## Feature Dependencies

```
PAT 增强 (#1: name+desc / 默认永久 / 一次明文 / 前后几位 / 自助增删)
    └──requires──> 既有 AccessToken model（created_by/expires_at/hash/prefix 已有）

令牌即身份+权限 (#2)
    └──requires──> #1（令牌须有明确 owner = created_by，已具备）
    └──replaces──> 现状"有效即全权限"鉴权

会话用户隔离 (#3)
    └──requires──> request.user 可靠（cookie-JWT 已有；token 路径需 #2）
    └──may-require──> 对话归属字段/迁移

MCP 用户令牌执行 (#4)
    └──requires──> #1（令牌存在）+ #2（身份语义）

RemoteTool 链路接通 (#5)
    └──requires──> #4（令牌注入）
    └──cross-process──> server / runner(Go) / task(Python) 契约同步
```

### Dependency Notes

- **#2 依赖 #1：** 令牌必须携带可信 owner 才能"以其身份"鉴权——`created_by` 已存在，故 #1→#2 主要是鉴权后端改造而非建模。
- **#3 与 #2 部分解耦：** Web（cookie-JWT）路径本就有 `request.user`，隔离可独立做；但**令牌调用**路径要正确隔离，必须先有 #2 让 token 解析出用户。
- **#5 依赖 #4：** 容器内 agent 调 skill/mcp 时需要把用户令牌注入到工具调用上下文，这一步是 #4 的产物；#5 是把它真正接到 task 容器消费 `remote_tools`。
- **跨进程契约（#5）：** `remote_tools` 结构需在 `server/runners/`、`runner/internal/ws/`、`task/` 三处一致（ARCHITECTURE 已列为约束）。

---

## MVP Definition

### Launch With（本里程碑 v0.2.0 必交）

- [ ] **#1 PAT 增强** — 缺备注/可识别指纹/正确默认值，令牌管理体验不完整（多为既有能力的小幅增量）
- [ ] **#2 令牌即身份 + 继承权限** — 里程碑核心语义；替换不安全的"有效即全权限"
- [ ] **#3 会话用户隔离** — 多用户隐私底线，缺了即数据泄露级缺陷
- [ ] **#4 MCP 用户令牌执行** — 让"令牌"真正有用武之地（绑定到工具）
- [ ] **#5 RemoteTool 链路接通** — 端到端价值闭环：agent 真的能以用户身份跑 skill/mcp

> 本里程碑 5 项 active 需求全部属于 MVP；它们构成一条依赖链（#1→#2→#4→#5，#3 并行），缺任一环价值闭环断裂。

### Add After Validation（v0.2.x，本期不做）

- [ ] **令牌轮换（rotate）+ 到期提醒** — 当"默认永久"被运维质疑安全性时引入（对齐 GitLab rotate）
- [ ] **令牌使用审计 / IP 来源** — 当出现"谁用了哪个令牌"排查需求时

### Future Consideration（未来里程碑）

- [ ] **细粒度 scope（读写/项目/资源分权）** — 本期已显式排除；待权限需求明确后做
- [ ] **共享会话空间 / 团队工作区** — 个人隔离稳定后再考虑协作
- [ ] **MCP OAuth 2.1** — 仅当面向不可信第三方暴露 MCP 时才需要

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| #1 PAT 增强（备注/默认永久/前后几位/自助增删） | MEDIUM | LOW | P1 |
| #2 令牌即身份 + 继承权限 | HIGH | MEDIUM | P1 |
| #3 会话用户隔离 | HIGH | MEDIUM | P1 |
| #4 MCP 用户令牌执行 | HIGH | MEDIUM-HIGH | P1 |
| #5 RemoteTool 链路接通 | HIGH | HIGH | P1 |
| 令牌指纹"后几位"修复（属 #1） | MEDIUM | LOW | P1 |
| 永久令牌安全提示文案 | LOW | LOW | P2 |
| 令牌 rotate / 到期提醒 | MEDIUM | MEDIUM | P3 |
| 细粒度 scope | MEDIUM | HIGH | P3（明确 anti-feature） |

---

## Competitor Feature Analysis

| Feature | GitHub | GitLab | Friday 本期方案 |
|---------|--------|--------|------------------|
| 名称 + 备注 | Note（classic） | name + description（17.7） | name + **新增 description** |
| 过期默认 | 强制/短期（fine-grained 默认 30天） | **不可永久**，默认 = 最大寿命(365天) | **默认永久（刻意权衡）** + 安全提示 |
| 延期 | 无（regenerate） | 无（rotate） | 无（与标杆一致） |
| 明文展示 | 仅一次 | 仅一次 | 仅一次（已实现） |
| 指纹识别 | 有意义前缀 | 有意义前缀 | **补"前缀+后4位"** 修可区分性 |
| 令牌=身份 | 是（+scope） | **是（默认继承用户全部权限）** | **是（继承 owner RBAC，不做 scope）** |
| 绑定给客户端 | 手抄 `Authorization: Bearer` 进 config | 同 | **平台内绑定 skill/mcp + 服务端注入容器**（差异化） |
| 会话隔离 | n/a | n/a | 个人会话私有（按 `created_by` 全路径过滤） |

---

## Sources

- GitHub Docs — REST API endpoints for personal access tokens（字段 `token_name/token_expired/token_expires_at/token_last_used_at/created_at`），<https://docs.github.com/en/enterprise-cloud@latest/rest/orgs/personal-access-tokens> — HIGH
- GitLab Docs — Personal access tokens（description 17.7 引入；**永不过期令牌 16.0 移除**；不填默认=最大寿命；"inherit permissions from the user who created them"），<https://docs.gitlab.com/18.8/user/profile/personal_access_tokens/> — HIGH
- GitLab Docs — Account and limit settings（"Require expiration dates" 默认开启；最大寿命 365/400 天），<https://docs.gitlab.com/17.11/administration/settings/account_and_limit_settings/> — HIGH
- GitLab Docs — Token overview（描述字段用途、到期邮件提醒），<https://docs.gitlab.com/security/tokens/> — HIGH
- github/github-mcp-server README + Claude Code MCP Docs（`Authorization: Bearer <PAT>` header；`${input:...}` / env 注入；内部工具静态 Bearer 即可），<https://code.claude.com/docs/en/mcp> — HIGH
- Agent Patterns Catalog / LangGraph 多租户隔离（每次读写按 user_id 过滤、DB 层兜底、个人 vs 共享空间），<https://www.agentpatternscatalog.org/patterns/session-isolation/> — MEDIUM
- Friday 代码基线：`server/access_tokens/models.py`、`web/src/components/accessTokens/*`、`web/src/api/accessTokens.ts`、`.planning/PROJECT.md` — HIGH（直接读取）

---
*Feature research for: 个人访问令牌 / 令牌即身份 / 会话隔离 / Agent 工具打通*
*Researched: 2026-06-09*
