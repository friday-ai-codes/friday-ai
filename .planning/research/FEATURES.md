# Feature Research

**Domain:** IDE 会话知识回写（Cursor / Claude Code → Friday Capture 账本 → 价值评估 → 仓库/项目 RAG）
**Researched:** 2026-08-28
**Confidence:** HIGH（Friday 既有 MCP/记忆/RAG 以源码为准）；MEDIUM（竞品与宿主 hooks 以官方文档 + 社区实现交叉验证）

## Feature Landscape

本里程碑要补的不是「再造一套记忆」，而是把现有闭环从 **「分支绑定项目 + git diff 才写回 + 长度/去重门槛」** 升级为 **「仓库为主挂钩、无项目也先收、零散问答也收、永不静默丢 Capture、价值分级后中高进 RAG」**。

产业上成熟产品都走同一条管线：**采集（hook/transcript）→ 抽精华（非全文、非 CoT）→ 持久化（账本 ≠ 向量）→ 重要性/去重 → 按 query 召回**。Mem0 官方模型是「发 messages，默认存提炼事实而非逐字 transcript」；Claude Code 官方 hooks 在 `Stop`/`SessionEnd` 提供 `transcript_path`，并警告 transcript 异步滞后、hook 有超时。Friday 现有 `skills/hooks/stop` 则在无 `git diff --stat` 时直接 `exit 0`，纯对话被系统性丢掉——这是 v0.25 相对 v0.16 stop hook 的核心缺口。

### Table Stakes（用户期望这些）

缺任一项，产品会感觉「回写没发生」或「知识进不去下次会话」。

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| MCP 结构化回写契约（问题 / 答案 / 回答模型 / 仓库 / 分支 / 会话） | 宿主只能提交结构化字段；缺字段记 `unknown`，不猜 | MEDIUM | 新建专用工具优于硬扩 `report_project_knowledge`（后者契约是自由文本 `content` + 项目定位）。须同步 `TOOL_SCHEMA_SNAPSHOT`、`mcp/src/tools.ts`、skills snapshot 守卫。依赖 PAT fail-closed（v0.2）。 |
| 仓库为主挂钩、项目可选；无 `project_id` 仍接受 Capture | 问答常挂仓、不一定挂 Friday 项目 | MEDIUM | 解析仓库：`repository_id` 优先，否则 git remote / 本机 cwd 映射既有 `Repository`。项目经 `lookup_project_by_branch` **增强**，失败不得挡写入。 |
| 禁止 `branch_unresolved` 静默丢数据 | 用户以为沉淀了，服务端 200 + `accepted=false` 等于丢 | LOW–MEDIUM | 今日 `ReportProjectKnowledgeView` 在 `_resolve_report_project_id` 失败时 200 跳过（`views.py`）。Capture 账本必须先落库；`accepted` 只表示「是否进记忆/RAG」，不是「是否收到」。 |
| 零散问答 / 无 git 改动也采集 | 用户在 IDE 里问架构/坑/约定，往往不改文件 | MEDIUM | 现 stop hook 注释写明「只有未提交工作区改动才上报」。须改采集触发：技能主动抽 Q&A + hook 在无 diff 时仍提交精华。 |
| Skills + Cursor / Claude Code hooks 抽精华并触发回写 | 不靠用户每次说「记下来」 | HIGH | Claude Code：`Stop` 已 `async: true`（`skills/hooks/hooks.json`）。Cursor 侧现多为 rule/技能编排，无与 Claude 对等的 transcript stdin。客户端只抽精华，禁止上报完整隐藏思维链。 |
| Capture 账本（原始结构化问答 + 元数据） | 评测回放、审计、永不丢 | MEDIUM | 新写模型（INV-6 单一 service）。**不是** `Interaction Ledger`，也不是 `ProjectMemory`。Ledger 继续记 MCP run/用量。 |
| 三层分离：Capture ≠ 提炼知识 ≠ Ledger | 统一知识库口径（v0.17）：Ledger 禁止反哺检索 | LOW（纪律）/ MEDIUM（建模） | 锁定决策已在 `PROJECT.md` Key Decisions。normalizer 只吃提炼后的中高价值正文。 |
| 价值评估 high / medium / low + 提炼 | 全量向量化会污染 `delivery_knowledge` | MEDIUM | **不是** `evaluate_writeback_quality`（过短 / 低信息量 / Jaccard 重复）。新 LLM 调用须赋 `call_source`，fail-soft 不得丢掉 Capture。路由 `confidence` 禁止当知识价值。 |
| 中高价值进仓库/项目 RAG；低价值留评测样本 | 下次编码能搜到决策与坑 | MEDIUM | 复用 `knowledge/sources/` 摄取 + `DeliveryKnowledgeSearchService`。建议新 `source_kind`（如 `session_capture`），**不要**假装成 `project_memory`（后者要求 active `ProjectMemory` + `repository_id=None`）。 |
| 按仓 / 按项目可检索；Capture 可回放 | 用户验收「问过的能搜到、原始问答能打开」 | MEDIUM | 读路径：MCP 检索工具扩 filter（`repository_id` / 可选 `project_id`）+ 控制台或 API 回放。写 `RetrievalTrace`。 |
| 认证、归因、脱敏 | 团队共享知识不可泄漏凭证 | LOW（复用） | `redact_secrets_in_text` 双保险；`initiated_by_user_id`；PAT=用户身份。 |
| Hook / 技能 fail-soft，不阻断编码 | 产业与现网纪律一致 | LOW | Claude Code Stop 可 block 会话结束；Friday 必须 exit 0 / 200。超时：采集异步，避免同步 LLM。 |

### Differentiators（竞争优势）

这些不是「有个 memory.json」就能交差；这是 Friday 相对 `@modelcontextprotocol/server-memory` / 本机 MEMORY.md 的差异。

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| 团队共享、自托管、权限 fail-closed | 记忆属于仓/项目成员，不是个人 JSON | MEDIUM | 仓库 ACL 现状偏「登录即可读仓」（已知欠债）；项目记忆仍须成员校验。无项目 Capture 的读权限应对齐仓库可见性，禁止比代码 RAG 更松。 |
| 挂仓库图谱 + 可选项目聚合根 | 同一条知识可被编码代理与「开发到哪一步了」共用 | MEDIUM | 有项目时 `REFERENCES` 到项目节点（镜像 `project_memory.py`）；无项目时 `repository_id` 必填进实体 payload。 |
| 价值分级进 RAG，低价值永不进向量但仍可评测 | 召回质量可控，同时满足「永不丢 Capture」 | MEDIUM | Mem0 用 importance（约 1–10）+ recency 融合检索；Friday 用离散三档更可测、更好做 golden set。 |
| 与既有 `friday-dev` 召回环路合流 | 开工 `lookup_project_by_branch` 能带上会话沉淀 | MEDIUM | 今日 context packer 吃项目记忆/工件；仓级 Capture 须进入 `search_rag_chunks` / `search_delivery_knowledge` / `search_project_context` 至少一条用户可走的面。 |
| 宿主最小化：IDE 抽 Q&A 精华，Friday 评估 | 不把 CoT/token 账本塞进知识库 | LOW–MEDIUM | 模型名拿不到记 `unknown`。与 Claude Code 官方「Stop 用 `last_assistant_message` 而非滞后 transcript」对齐。 |
| Capture 回放作评测集 | 可回归「哪些问答该进 RAG」 | MEDIUM | 低价值样本是资产不是垃圾。与 v0.19 golden set 纪律同类。 |
| 不依赖专用 IDE 插件 | 复用 MCP + skills（CURSOR 回流 v0.15 已否决专用插件） | — | 专用插件仍是 PROJX-04 backlog，本里程碑不做。 |

### Anti-Features（常被要求、往往有害）

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| 把 `report_project_knowledge` 当唯一写入口，继续 `branch_unresolved` 跳过 | 少一个 MCP 工具 | 语义是「项目记忆草稿/active」，无法表达无项目 Capture；跳过即丢数 | 新 Capture 工具（或显式 `accepted` vs `captured` 双字段）；旧工具行为保持向后兼容 |
| 无 git diff 就不回写 | 防噪音（现 hook 实测踩过「每轮写最近提交」） | 丢掉本里程碑目标里的零散问答 | 无 diff 时改抽 transcript/本轮 Q&A 精华；噪音用价值评估 + 指纹去重，不用「有没有 diff」当闸 |
| 全文会话 / 隐藏思维链入账本或 RAG | 「以后有完整上下文」 | 体积、隐私、脱敏失败面、RAG 被过程噪音淹没 | 只存问题、可见答案精华、模型名；CoT 禁止 |
| 把 Interaction Ledger 当 RAG 正文 | 已经有 run 记录 | v0.17 明确 Ledger 不反哺检索；形态是调用/用量不是知识 | Ledger 只关联 `request_id`/`run_id` |
| 用路由 `confidence` 或长度门槛当 high/medium/low | 省一次 LLM | `evaluate_writeback_quality` 只防 `too_short`/`low_information`/`duplicate`；路由分是选仓把握不是知识价值 | 独立价值评估器；长度门槛可作 **pre-filter**（过短仍落 Capture，标 low 或不评估） |
| 无差别把所有 Capture 向量化 | 实现简单 | 污染 `delivery_knowledge`，伤害编码/方案召回 | 仅 medium/high 摄取；low 留账本 |
| 把 Capture 写成 `ProjectMemory` 再等人工确认才「算收到」 | 对齐历史 MEM-04 | 无项目时没有 Memory 可挂；确认延迟 = 用户以为丢了；Phase 86 已用 active 直写打破「全部须确认」 | **账本无条件落**；RAG 是否 auto 见下方产品张力 |
| 会话开始把全部记忆 dump 进 prompt | 模仿 memory.json | 社区与 Mem0 均警告撑爆上下文、旧事实压过关键约束 | 按 query / 仓 / 项目 on-demand 检索（已有 `search_project_context`） |
| 本机 `@modelcontextprotocol/server-memory` 当 Friday 存储 | Cursor 教程多 | 个人文件、无权限、不进团队 RAG、重启路径易丢 | Friday 服务端账本 + Qdrant |
| Stop hook 内同步跑评估 LLM | 一次完成 | Claude Code hook 超时；官方建议异步；现 Stop 已 async | Hook 只 POST Capture；评估进 durable/后台任务 |
| 自动覆盖人工已确认的项目记忆 | 「最新会话为准」 | 蓝图/记忆「AI 不覆盖人工」；Phase 86 active 直写已是高风险特例 | Capture/RAG 与 `ProjectMemory` 解耦；可选「提议草稿」进记忆，不默默 supersede |
| 猜测回答模型、token、项目 | 报表好看 | 锁定：拿不到记 `unknown`；不编造 `project_id` | 字段显式 optional / unknown |
| Cursor 专用采集插件 | 更稳的 transcript | v0.15 明确留 v2；范围爆炸 | Skills + MCP；Cursor 用规则强制「有 Q&A 就调回写工具」 |

## Feature Dependencies

```
PAT 认证 MCP 入口 (v0.2)
    └──requires──> 新 Capture MCP 工具 (MCP-01)
                       └──requires──> Capture 账本 STORE-01
                       └──requires──> 仓库解析（Repository 实体 / remote 映射）
                       └──enhances──> lookup_project_by_branch（项目可选）

Skills / hooks 采集 (SKILL-01)
    └──requires──> MCP-01 契约
    └──conflicts──> 现 stop hook「无 git diff 则 skip」（必须改触发条件）
    └──enhances──> friday-dev 收工 report_project_knowledge（并行保留，不替代 Capture）

价值评估 EVAL-01
    └──requires──> STORE-01（先有 Capture 再评）
    └──requires──> ProviderConfig / call_source / MemoryDistiller 同类 LLM seam（可复用 distill，不可复用其「必须 project 成员 + 只产 draft」语义）
    └──conflicts──> 把 evaluate_writeback_quality 结果当作 high/medium/low

RAG 摄取（中高）
    └──requires──> EVAL-01 完成（或明确默认档）
    └──requires──> knowledge/sources 新 normalizer + 摄取管线
    └──requires──> DeliveryKnowledgeSearchService + 权限/exclusion fail-closed
    └──conflicts──> 仅投影进 project_memory（无项目 / 非 active 会被 skip）

召回与回放
    └──requires──> RAG 摄取（检索）+ Capture 账本（回放原文）
    └──enhances──> friday-dev / friday-memory / search_rag_chunks

Phase 86 report_project_knowledge active 直写
    └──conflicts──> 「所有 AI 产物必须 draft 确认才存在」
    └──enhances──> 仅当用户仍要「改动摘要进项目记忆」时保留；与 Capture 账本分流
```

### Dependency Notes

- **MCP-01 requires Capture 账本：** 工具成功语义必须是「已持久化」，不能再等于「已解析到唯一项目」。
- **SKILL-01 requires 改 stop 闸：** 不改 `if not changes: fail_soft()`，零散问答需求无法验收。
- **EVAL-01 requires 独立于质量门槛：** 门槛可拒绝「进 ProjectMemory」，但 v0.25 锁定永不丢 Capture；过短条目应入库并标 low。
- **RAG requires 新 source_kind：** `project_memory.normalize` 在非 active 或无记忆时返回空列表；仓级知识必须能带 `repository_id`。
- **lookup_project_by_branch 是增强不是前置：** 有项目则 context packer / 记忆 UI 更完整；无项目不得阻塞。
- **`MemoryDistiller`：** 可复用 LLM seam 与脱敏；不可复用 `distill_to_draft` 的「必须项目成员否则抛」作为 Capture 入口（无项目用户仍应能回写仓级知识，权限改对齐仓库）。
- **npm MCP 白名单：** 历史多次「服务端有、客户端无」。新工具必须同期改 `mcp/src/tools.ts`，否则 Cursor 调不到。

## 产品张力（MEM-04 vs 中高自动入 RAG）

历史 MEM-04：LLM 只产 **pending draft**，人工确认后才成 active `ProjectMemory`，且 **只有 active 才被 `project_memory` 摄取进 RAG**。

Phase 86 已出现 **accepted deviation**：stop hook `writeback_mode=active` 直写生效记忆（质量门槛 + 脱敏 + 成员静默跳过 + 审计可回滚）。这与 MEM-04 字面冲突，但是为了「编码不中断、沉淀真正发生」。

v0.25 建议把张力拆成两道闸，避免再混在一个开关里：

| 层 | 建议默认 | 理由 |
|----|----------|------|
| Capture 账本 | **无确认、永不丢** | 评测与审计；用户可见「已收到」 |
| 价值评估 / 提炼 | 自动（fail-soft，失败保留原文 Capture） | 客户端已抽过一版精华 |
| 中高 → RAG 向量 | **产品决策点（须立项拍板）** | 自动：闭环像 Phase 86，编码代理立刻可搜；草案确认：更接近 MEM-04，延迟与漏确认会导致「搜不到刚问过的」。推荐：**仓级 RAG 对 medium/high 自动摄取**（可 supersede/下线，审计可回滚），**写入 `ProjectMemory` 仍默认 draft**（不把会话 Capture 冒充项目长期记忆）。低价值永不向量化。 |
| 项目记忆 UI | 不自动 active | 避免会话噪音进入「团队长期记忆」编辑面 |

若选择「中高也须人审才进 RAG」，必须提供积压队列与超时策略，否则验收「可召回」会系统性失败（与 v0.19 澄清卡死同类）。

## MVP Definition

### Launch With（v0.25.0）

- [ ] **MCP-01/02** — 结构化 Capture 写入；无项目按仓收；解析失败仍落账本
- [ ] **SKILL-01** — Cursor 规则/技能 + Claude Code hooks：有/无 git 改动都抽 Q&A 精华并调用新工具
- [ ] **STORE-01** — Capture 账本 + 与 Ledger / ProjectMemory 分表
- [ ] **EVAL-01** — high/medium/low + 提炼；中高进仓（及可选项目）RAG；low 可回放
- [ ] 脱敏 / PAT / fail-soft / `call_source` / RetrievalTrace / schema snapshot 与 npm 工具对齐

### Add After Validation（v0.25.x）

- [ ] 控制台 Capture 回放与价值纠偏（人把 low↔medium）
- [ ] SessionStart 按仓注入「近期高价值摘要」预算（防 dump）
- [ ] 与 `report_project_knowledge` 去重：同一会话决策不双写 Memory + Capture RAG
- [ ] Cursor 侧更稳的 transcript 采集（仍非专用插件）

### Future Consideration（v2+）

- [ ] 专用 IDE 插件 / PROJX-04
- [ ] 结构化记忆矛盾消解、时效降权（PROJX-02）
- [ ] 记忆全自动进 `ProjectMemory` active 且无人审（PROJX-03）——与本里程碑「账本自动、项目记忆谨慎」相反，保持 backlog
- [ ] 多模态会话（截图问答）入 Capture

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Capture MCP + 永不因无项目丢数 | HIGH | MEDIUM | P1 |
| 无 git diff 的 Q&A 采集 | HIGH | MEDIUM | P1 |
| Capture 账本三层分离 | HIGH | MEDIUM | P1 |
| 价值分级 + 中高 RAG | HIGH | MEDIUM | P1 |
| Skills/hooks 双宿主 | HIGH | HIGH | P1 |
| 按仓/按项目检索 + 回放 | HIGH | MEDIUM | P1 |
| 项目记忆 draft 确认 UI | MEDIUM | LOW（已有） | P2（不阻塞仓级 RAG） |
| SessionStart 记忆注入 | MEDIUM | MEDIUM | P2 |
| 价值人工纠偏 | MEDIUM | MEDIUM | P2 |
| 专用插件 | LOW（本里程碑） | HIGH | P3 |
| 全文 transcript 入向量 | LOW / 负 | LOW | 不做 |

**Priority key:**
- P1: Must have for launch
- P2: Should have, add when possible
- P3: Nice to have, future consideration

## Competitor Feature Analysis

| Feature | Mem0 / 通用 Memory MCP | Claude Code 原生 memory + hooks | Friday 现状 | Our Approach (v0.25) |
|---------|------------------------|---------------------------------|-------------|----------------------|
| 跨会话持久化 | `add` 提炼事实 + 向量检索 | `~/.claude/projects/.../memory/` 文件；社区要 PostMemoryWrite 才好外同步 | 项目记忆 + stop hook 改动摘要 | 服务端 Capture + 仓/项目 RAG |
| 采集触发 | 应用显式 `add` | `Stop`/`SessionEnd` 读 transcript；超时需异步 | 有 diff 才 `report_project_knowledge` active | Hook + 技能；无 diff 也提交 Q&A |
| 无项目/个人范围 | `user_id`/`agent_id` 过滤 | 本机目录 | **必须**唯一项目否则 skip | 仓为主、项目可选 |
| 重要性 | LLM importance + recency 融合 | 无统一三档；靠模型自觉写 MEMORY.md | 长度/词数/Jaccard，非价值 | high/medium/low；仅中高向量化 |
| 原始记录 | 默认可关 infer 存原文 | transcript 文件在宿主侧 | Ledger 是用量不是问答正文 | Capture 账本可回放 |
| 团队权限 | 自建过滤 | 无 | 项目成员 + PAT | 仓可见性 + 可选项目成员 |
| 与编码 RAG 一体 | 通常独立 memory 库 | 独立 | `delivery_knowledge` 已统一检索面 | 新 `source_kind` 进同一 collection，kind 过滤 |

## 对既有 Friday 能力的依赖（落地清单）

| 能力 | 路径 | 本里程碑用法 |
|------|------|----------------|
| `report_project_knowledge` | `mcp_tools/views.py` | **保留**给「收工项目记忆」；不要让它承担无项目 Capture |
| `evaluate_writeback_quality` | `services/cursor_writeback.py` | 仅作噪音 pre-filter；**不是** EVAL-01 |
| `MemoryDistiller` | `initiatives/services/memory_distill.py` | 复用 LLM seam / 脱敏 / `ide_hook_distill`；评估提示词与「NONE→不写」语义要改成「始终留 Capture」 |
| `lookup_project_by_branch` | MCP | 可选填充 `project_id` |
| `ProjectMemory` + MEM-04 draft | `MemoryService` | 可选二次投影；默认不把 Capture 当 active 记忆 |
| `knowledge/sources/project_memory.py` | RAG | 参考 normalizer 范式；仓级知识另建 source |
| `DeliveryKnowledgeSearchService` | 统一检索 | 中高价值召回 |
| `skills/hooks/stop` + `friday-dev` | 客户端 | 改触发；技能教「零散问答也调 Capture 工具」 |
| `@friday-ai-codes/mcp` 工具表 | `mcp/src/tools.ts` | 新工具必须同期发布，防客户端不可达 |
| Durable 队列 (v0.12) | 评估/摄取 | 评估与向量化后台跑，hook 只负责 POST |
| 可观测 | LOGGING-SPEC | Capture started/completed/failed；评估 `call_source`；召回 `RetrievalTrace` |

## Sources

- Friday 源码（HIGH）：`server/mcp_tools/views.py`（`branch_unresolved` / draft vs active）、`server/services/cursor_writeback.py`、`server/initiatives/services/memory_distill.py`、`server/knowledge/sources/project_memory.py`、`skills/hooks/stop`、`skills/skills/friday-dev/SKILL.md`、`.planning/PROJECT.md` v0.25 Active 需求
- Mem0 官方 How it works（HIGH）：https://docs.mem0.ai/core-concepts/how-it-works — 提炼事实 vs transcript；检索须 scope filter
- Mem0 RAG vs Memory（MEDIUM）：importance × recency × similarity，禁止纯相似度当记忆
- Claude Code hooks 官方（HIGH）：https://code.claude.com/docs/en/hooks.md — `Stop`/`SessionEnd`、`transcript_path` 滞后、`last_assistant_message`、hook 可 block、建议异步
- 社区：Substrate / OpenViking Claude Code 插件（MEDIUM）— Stop 增量 checkpoint、fail-open exit 0、本地 spool
- Cursor Memory MCP 教程（LOW–MEDIUM）— 本机 JSON 图谱；Rules 做 recall-act-memorize；**不能**替代团队知识库
- 历史里程碑：v0.15 MEM-04/CURSOR-03、v0.16 Phase 86 active 直写 deviation、v0.17 Ledger ≠ RAG

---
*Feature research for: IDE session knowledge writeback (Friday v0.25.0)*
*Researched: 2026-08-28*
