# Feature Research

**Domain:** AI 编码代理平台的统一知识库 / agent memory / 完工沉淀闭环 / 容器代理工具配给（v0.17.0 KNOW·LOOP·AGENT·UNIFY）
**Researched:** 2026-07-15
**Confidence:** MEDIUM-HIGH（agent memory 生态与 claude-agent-sdk 集成为 HIGH——官方文档与多源一致；Devin/Cursor 内部机制为 MEDIUM——依据官方文档与工程访谈；本项目落地建议基于 MILESTONE-CONTEXT.md 的代码坐标为 HIGH）

> 范围限定：只调研 v0.17.0 四类新能力（KNOW/LOOP/AGENT/UNIFY）对应的业界做法。既有能力（RAG/codegraph、delivery_knowledge 图谱、process_runtime 编排、wave 编码、飞书链路、MCP 约 30 工具）不重复调研，只作为依赖坐标引用。

## 业界格局速览（结论先行）

1. **Agent memory 已收敛出标准分型**：working（上下文内）/ episodic（事件，"上次做了什么"）/ semantic（事实结论）/ procedural（做法规则）。生产系统主流是分层架构：小而热的常驻上下文 + 向量库支撑的检索层 + 显式的整合（consolidation）与遗忘（decay）策略。主流框架 Mem0（混合向量-图）、Zep/Graphiti（**bi-temporal 时间知识图谱**）、Letta/MemGPT（agent 自管理分页）、LangMem（LangGraph 原生）。**Friday 的 `KnowledgeEntity` + bi-temporal 边 + Qdrant 混合检索在架构上就是 Zep/Graphiti 同型**——本里程碑不需要新架构，需要的是把 learning case / MCP 产物这些"漏网数据源"接进既有架构，这正是 KNOW 的定位。
2. **编码 agent 完工自动沉淀的业界共识是"自动提炼 + 建议先行"**：Devin 自动从会话反馈生成 Knowledge 建议（人工审核后入库，带 Trigger Description 控制召回时机，可 pin 到 repo/org 作用域）；Cursor Memories 用 sidecar 小模型旁路观察对话提取记忆（关键工程教训：**必须激进过滤掉 90%+ 任务特定内容，只留可泛化知识**——主模型直接 tool-call 写记忆会偏向产出"任务日志"）；Qodo/PR-Agent 把"被采纳的 review 建议"沉淀为 auto best practices 文档并在后续 review 中标注引用。
3. **完工业务回写是 table stakes**：Copilot coding agent 全程锚定 PR——开 draft PR、任务清单打勾、commit message 链接 session log、完工更新 PR 描述并 tag 审核人。"跑完了但业务方（issue/工作项）看不到结果"在业界属于产品缺陷。Friday 三链路（工作流/Chat/MCP）回写不一致正是这个缺陷。
4. **容器内代理配 MCP 工具的标准做法**：claude-agent-sdk 进程内 SDK MCP server（`create_sdk_mcp_server`）+ `allowed_tools` 白名单（`mcp__<server>__<tool>` 全名）+ **代理凭证代持模式**（工具把请求转发到安全边界外的服务、由服务注入凭证，agent 永远拿不到密钥）——Friday 的"HTTP 调服务端工具面 + PAT 鉴权"方案与官方推荐的 proxy 模式完全一致。skills 走 `setting_sources=["project"]` + `Skill` 工具（task 容器已用此机制加载仓库自带 skills，v0.9.0 验证过）。
5. **知识库 MCP 工具面的典型形态**是小而稳的核心四件套（store / recall·search / inspect / forget）+ 作用域过滤 + 混合检索，工具数量克制（Loci 6 个、AutoMem 6 个），并附"先召回再干活、完工后存储、失败静默降级"的使用协议（rule/skill 文档）——Friday 已有 `search_*`/`create_learning_case`/`report_project_knowledge`，缺的是 schema snapshot 补全与使用协议（skills 文档）对齐，不是缺工具。

## Feature Landscape

### Table Stakes（用户/业界默认预期，缺了就是断裂）

| Feature | Why Expected | Complexity | Notes（本项目落点） |
|---------|--------------|------------|-------|
| **经验/记忆统一进单一检索面（向量检索）** | 所有主流 memory 框架（Mem0/Zep/Letta）第一原则：一个检索入口覆盖全部记忆类型，episodic 条目带 timestamp + scope + metadata 走语义检索 | MEDIUM | `McpLearningCase` 补 `knowledge/sources/learning_case.py` normalizer 入图；`search_learning_cases` 底层切 `DeliveryKnowledgeSearchService`（kind 过滤），API 契约不变。token 打分是业界已淘汰的"naive 关键词检索"形态 |
| **产物不分入口一律入库** | 同一种产物（方案/分析/执行 trace）走不同入口结果不同，属于数据管道 bug 而非产品选择；Zep/Mem0 都强调 ingestion 是统一入口 | MEDIUM | `McpCodingPlan`/`McpRepositoryAnalysis`/`McpCodingExecutionTrace` 各补 normalizer；与 chat `coding_plan`/`task_result` 用既有 natural key 去重关联 |
| **完工自动回写业务方（issue/工作项/PR）** | Copilot coding agent 的基线行为：完工更新 PR 描述 + tag 人；Devin 完工在 issue/PR 留痕。业务方在自己的系统里看到结果是底线 | MEDIUM | 从 `work_item_execution_service` 抽公共 write-back service，工作流 `ai_coding` 完成 / Chat 建 PR 后 / MCP 执行三处统一调用；开关默认开、fail-soft |
| **回写/沉淀 best-effort 不反噬主流程** | AutoMem 等 memory 集成的通用协议明文写死："store 失败照常完成任务，memory 是增强不是必需" | LOW | 项目已有 fail-soft 惯例（审计/回写均如此），沿用即可 |
| **容器内代理能主动查知识（读工具白名单）** | Devin/Copilot 的执行环境都能查组织知识；claude-agent-sdk 官方推荐 proxy 模式给沙箱代理配受控工具。"编码代理是知识贫民区"在业界是明确反模式 | HIGH | task 侧 `build_knowledge_mcp_server`（进程内 SDK MCP server，HTTP 调 `/api/mcp/tools/*` 白名单子集，PAT 鉴权），复用 `extra_mcp_servers`/`allowed_tools` 机制；注意 `allowed_tools` 须写 `mcp__<server>__<tool>` 全名（官方文档强调的常见踩坑点） |
| **skills 随代理环境自动可见** | Devin 自动发现 `.agents/skills/`/`.claude/skills/` 等多路径 SKILL.md 并在会话开始即列出 name+description；claude-agent-sdk 需 `setting_sources` 显式启用 + `Skill` 工具在 allowed_tools | MEDIUM | 派发准备 workspace 时注入 friday-code/friday-memory 精简版到 `.claude/skills/`（与仓库自带共存不覆盖）；v0.9.0 已打通 `setting_sources=["project"]` 通道，本次只是多放物料 |
| **三链路上下文注入对齐** | 同一平台不同入口给代理的上下文不一致 = 行为不可预期；Copilot 无论从 issue/panel/chat 发起都注入同样的 repo instructions | LOW | 工作流 `ai_coding` 节点派发前 prepend `pack_project_context`（对齐 Chat 的 `_resolve_project_context_for_dispatch`），纯复用 |
| **对外工具 schema 完整可发现** | MCP 生态基线：工具面即产品契约，注册了的工具必须进 schema/文档，否则客户端不可发现 | LOW | `report_project_state`/`reverse_lookup_requirements` 补进 `TOOL_SCHEMA_SNAPSHOT` + 快照测试 |
| **权限/排除/脱敏在新通道天然继承** | claude-agent-sdk 安全部署指南核心原则：凭证与权限校验留在安全边界外的服务端，agent 经 proxy 调用 | LOW | 容器 MCP 走服务端 HTTP 工具面（不直连 Qdrant/DB），排除文件 fail-closed、PAT 按所有者 RBAC 天然生效——这是选 proxy 方案的最大红利 |

### Differentiators（竞争优势，本里程碑值得投入的差异化）

| Feature | Value Proposition | Complexity | Notes（本项目落点） |
|---------|-------------------|------------|-------|
| **编码完成自动提炼 learning case（全自动入库）** | Devin/Cursor 都停在"建议 + 人工确认"；Qodo auto best practices 是商用独占功能。Friday 做到"任一编码路径完工 → 自动产可检索经验"即超出多数产品的默认形态 | HIGH | 挂 `subagent/api/callbacks.py` 完工回调，LLM 从 TaskResult/diff/plan 提炼，赋新 `call_source`，best-effort。质量门槛见下文专节——这是成败关键，业界教训集中在这里 |
| **bi-temporal 知识图谱做经验底座** | Zep 把 bi-temporal 作为对 Mem0/Letta 的核心差异化卖点（矛盾事实不删除而是失效 + 时点查询）；Friday 已有这套（v0.3.0/v0.6.0），learning case 入图即免费获得时效失效、supersedes 版本链、图边关联（case→plan→PR→work_item 可追溯） | LOW（复用） | 入图时把 learning case 与 work_item/repository/tech_plan 建边，检索时图扩散召回——纯复用既有 `GraphStore` 能力，业界要单独买 Zep 才有 |
| **平台级多步 Skill（pre_coding_research / post_coding_capture）** | 业界的"先召回再编码、完工后沉淀"只是 rule 文档里的君子约定（AutoMem 的 automem.mdc、Devin 的 Knowledge 使用习惯）；做成服务端可执行的多步 RemoteTool Skill，Cursor 与容器代理同一份，是把约定变成产品能力 | MEDIUM | 复用 `server/tools/sources/skill.py` 多步 steps + `/api/tools/execute/`；`pre_coding_research`: route→rag→delivery_knowledge→learning_cases 聚合；`post_coding_capture`: summarize_branch→create_learning_case→report_project_knowledge |
| **编排召回吃到全部沉淀（document/learning_case 扩容）** | 方案生成时召回历史经验/项目记忆 = ExpeL 的"insight 注入 inference"模式产品化；多数编码平台的方案生成不带组织记忆 | LOW | `recall_adapter` kinds 扩 `document` + `learning_case`，可配置开关默认开 |
| **PR 后轻量 review 沉淀** | Qodo 的差异化能力（商用独占）：review 结论回流成组织经验，形成"review→经验→下次更好"飞轮 | MEDIUM | 范围克制：PR 创建后可选触发 review，结论沉淀为 learning case；不做 review 产品化（UI/规则引擎显式 out of scope） |
| **skills 单一事实源（容器 == npm 包同源）** | Devin 用"indexed + 磁盘扫描覆盖"保证 skills 不漂移；多数自建平台的容器物料与对外包各维护一份、必然漂移 | LOW | 容器物料由根 `skills/` 包生成/直引，加一致性测试（hash 对比）防 CI 漂移 |
| **三链路检索同一条经验（统一排序验收）** | "在 Chat / 工作流 / MCP / 编排四处检索能召回同一条 learning case"是统一知识库的可验证承诺，业界没有对等物（各产品都是单入口） | —（验收面） | 这是里程碑验收标准 1，不是独立功能；靠 KNOW 各项共同达成 |

### Anti-Features（业界踩过的坑，明确不做/不这样做）

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **主模型直接 tool-call 写记忆（无过滤全自动）** | 实现最简单，"agent 自己决定记什么" | Cursor 实测：强模型有产出"任务日志"的强烈偏好，与"可泛化知识"目标相反；错误记忆会让模型"double down"（坚信记忆正确而拒绝纠正） | 沉淀走独立的提炼调用（旁路 LLM，专用 prompt 强调泛化性），不让编码主 agent 顺手写库；提炼失败静默丢弃 |
| **"记住一切"（每次完工无门槛入库）** | 数据越多越好的直觉 | Reflexion/ExpeL 系统性结论：无策展的记忆库积累噪声，"lesson rot"（过时经验误导后续）比没有记忆更糟；Mem0 明确把 consolidation 列为必须步骤 | 入库前质量门槛（见下节）+ 复用 bi-temporal 失效机制让过时 case 可被 supersede；重复 case 走实体 natural key 去重 |
| **给容器代理开放全部 30 个 MCP 工具** | 反正鉴权了，全开省事 | claude-agent-sdk 安全指南：无人值守运行必须窄白名单 + fail-closed；写类工具（create_merge_request 等）在容器内被 prompt injection 滥用的爆炸半径大；每工具都增加时延与 token 负担 | 只开读类知识工具白名单（search_rag_chunks/grep_repository/get_repository_file/search_delivery_knowledge/search_learning_cases/search_project_context/lookup_project_by_branch）+ 每任务调用配额/超时 |
| **容器直连 Qdrant/DB 查知识** | 绕过 HTTP 一跳，性能好 | 凭证进容器（违反 PAT-02 精神）、排除文件/权限过滤要在容器侧重新实现一遍、脱敏旁路 | 服务端 HTTP 工具面 proxy 模式（官方推荐），权限/排除/脱敏零成本继承 |
| **learning case 检索造第二套排序** | McpLearningCase 已有 token 打分，加权融合"兼顾两边" | 两套排序 = 统一知识库目标失败的根因（当前痛点就是平行两套"历史经验"无法统一排序） | 底层整体切 `DeliveryKnowledgeSearchService`，token 打分退役；保留 API 契约 + 对照测试守住召回质量（风险 1 的既定缓解） |
| **本里程碑合并 chat.CodingPlan 与 McpCodingPlan 两张表** | "同名不同物"看着难受，合表最彻底 | 改动面横跨 chat/MCP/执行 bridge，与知识收敛目标正交；MILESTONE-CONTEXT 已显式 out of scope | 两侧 plan 都稳定入统一知识库、可互相检索到（最小趋同）；合表单独立项 |
| **完整 review 产品化（评审 UI/规则引擎）** | review 沉淀听着像要做全套 | 范围爆炸；Qodo 整个产品线做这一件事 | "PR 后可选 review + 结论沉淀为 learning case"最小环 |
| **记忆自动注入每次对话开头（无召回条件）** | AutoMem 式"conversation start 自动 recall"看似省心 | 无关记忆污染上下文（context pollution 是 2026 memory 综述列的头号未解问题）；Devin 特意用 Trigger Description 控制"相关才召回" | 走检索式按需召回（既有 RAG 惯例）；Chat 工具面补读工具让 agent 主动查，而非无脑注入 |

## 自动提炼 learning case：触发时机 / 结构化字段 / 质量门槛（专节）

这是 LOOP 的技术核心，业界经验最集中的地方，单独展开供 requirements 直接消费。

**典型触发时机**（业界实践并集，按本项目适配排序）：

1. **编码任务终态回调**（成功与失败都触发——Reflexion/ExpeL 均强调失败经验价值更高，failure pattern 是最有用的 insight 类型）→ 本项目挂 `subagent/api/callbacks.py`。
2. **PR 创建/合并后**（Copilot/Qodo 的锚点；合并 = 人类隐式验收，质量信号最强）→ 本项目在 write-back service 后串接。
3. **review 结论产出后**（Qodo：被采纳的建议才入库——"人类采纳"是天然质量门槛）→ 本项目 PR 后轻量 review 的沉淀点。
4. **用户在会话中给出纠正性反馈时**（Devin Knowledge suggestion / Cursor sidecar 的主触发）→ 本项目已有 Cursor 侧 `create_learning_case` 手动通道 + friday-memory skill 引导，本里程碑不新增会话监听（避免 sidecar 模型这一整套新基建）。

**结构化字段**（Mem0 schema + Devin Knowledge + 既有 McpLearningCase 交集，推荐 schema）：

- `outcome`（success/failure/partial）——ExpeL 的成败配对是提炼输入的基础
- `root_cause` / `solution`（失败向）或 `approach` / `key_decision`（成功向）——Reflexion 的"可执行改进方向"
- `trigger_context`（什么场景该召回这条——Devin Trigger Description 的等价物；向量化后这就是检索锚点）
- `scope`（repository / work_item / 全局——Devin pin 语义；本项目用图边关联 repository/work_item/tech_plan 实现，比字段更强）
- `source_pointers`（task_result id / PR URL / plan_version——审计与可信度回溯；Mem0 的 source-message pointers）
- 时间戳 + `initiated_by_user_id`（无则 system）——观测规范既有要求

**质量门槛**（业界教训的并集，按拦截顺序）：

1. **泛化性过滤**：提炼 prompt 显式要求"可复用教训"而非"本次任务日志"（Cursor 的核心教训，90%+ 内容应被丢弃）；产出为空/低置信度直接不入库。
2. **去重门**：与既有 case 语义相似度过高（业界参考值 cosine > 0.92，Loci 的 dedup gate）则合并/跳过——本项目可复用实体 natural key + 向量相似检查。
3. **脱敏不可绕过**：提炼输入（TaskResult/diff）与产出都过 `redact_secrets_in_text`——既有强制规范。
4. **长度/结构校验**：必填字段齐全才入库（Devin：Knowledge 必须有 trigger）。
5. **可退场**：入库的 case 保留 supersede/失效通道（bi-temporal 天然支持），对抗 lesson rot；不做静默删除（Reflexion 模式明确：显式 retire 而非 overwrite）。
6. **全程 fail-soft + 观测**：提炼 LLM 调用赋新 `call_source`、失败吞掉、写入走 ingestion 唯一入口（INV-6）。

## Feature Dependencies

```
[KNOW-1 learning case 入图 normalizer]
    └──requires──> 既有 knowledge/sources/ 注册表 + aschedule_ingestion（v0.3.0）
[KNOW-2 search_learning_cases 切向量检索]
    └──requires──> KNOW-1（不入图无从检索）
[KNOW-3 MCP 产物入图（plan/analysis/trace）]
    └──requires──> 既有 sources 模式；与 chat coding_plan natural key 去重约定
[KNOW-4 编排召回扩容 document/learning_case]
    └──requires──> KNOW-1（learning_case kind 存在）；既有 recall_adapter
[KNOW-5 Chat 工具面补读工具]
    └──requires──> KNOW-2（否则 Chat 查到的还是 token 打分结果）

[LOOP-1 公共飞书回写 service]
    └──requires──> 既有 work_item_execution_service（抽取源）；三处调用点各自既有链路
[LOOP-2 完工自动提炼 learning case]
    └──requires──> KNOW-1（入库通道）+ 既有 callbacks.py + 脱敏/观测设施
[LOOP-3 平台 Skill 两枚]
    └──requires──> KNOW-2（pre_coding_research 引用向量版检索）+ 既有 RemoteTool SKILL 多步机制
[LOOP-4 PR 后轻量 review 沉淀]
    └──requires──> LOOP-2（沉淀通道同源）+ LOOP-1（挂接点在回写链路附近）

[AGENT-1 容器知识 MCP]
    └──requires──> 既有 extra_mcp_servers/allowed_tools 机制（task/core/executor.py）+ PAT 直传链路（v0.2.0）
    └──enhanced by──> KNOW-2（容器查到的 learning case 是向量版）
[AGENT-2 容器 skills 注入]
    └──requires──> 既有 setting_sources=["project"] 通道（v0.9.0）+ 根 skills/ 包（同源）
    └──enhanced by──> LOOP-3（skills 文档引导调用平台 Skill）
[AGENT-3 工作流上下文对齐 pack_project_context]
    └──requires──> 既有 project_context_packer（v0.15.0）——纯复用

[UNIFY-1 improve/analyze 收敛 delegate_process_runtime] ──independent──
[UNIFY-2 schema snapshot 补全] ──independent（但 AGENT-1 白名单工具的 schema 必须先稳定）──
```

### Dependency Notes

- **KNOW-1 是全里程碑的枢纽**：LOOP-2 的入库通道、KNOW-2 的检索底层、KNOW-4 的召回扩容、AGENT-1 容器查经验的数据源全部依赖它先落地。Phase 排序上应最先。
- **LOOP-1 与 KNOW 无依赖**，可并行推进（回写用的是既有飞书能力，不经知识库）。
- **AGENT-1 依赖 UNIFY-2 的顺序敏感点**：容器白名单里的工具 schema 若在同里程碑变动，会造成容器侧与 snapshot 漂移；建议 UNIFY-2 在 AGENT-1 验收前完成。
- **LOOP-4 是增值项**：依赖最深（LOOP-1 + LOOP-2 都要先在），范围最该守住"能跑通 + 沉淀"。

## MVP Definition

### Launch With (v1 — 本里程碑必达)

- [ ] KNOW-1/2 learning case 入图 + 向量检索切换 — 统一知识库的定义性交付，验收标准 1 的前提
- [ ] KNOW-3 MCP 产物入图 — 消除"同一产物走 MCP 就成盲区"的数据管道断裂
- [ ] LOOP-1 公共回写 service 三链路接入 — table stakes，业务侧可见性底线
- [ ] LOOP-2 完工自动提炼（含质量门槛全套） — 里程碑的差异化核心
- [ ] AGENT-1 容器知识 MCP（读白名单） — "知识贫民区"的直接解药
- [ ] AGENT-3 工作流 pack_project_context 对齐 — 复杂度最低、断裂感消除最直接
- [ ] UNIFY-2 schema snapshot 补全 — 低成本、契约完整性

### Add After Validation (v1.x — 里程碑内后置或视进度)

- [ ] KNOW-4 编排召回扩容 — KNOW-1 落地后加 kinds 即可，注意召回质量观测先行
- [ ] KNOW-5 Chat 工具面补读工具 — 薄封装，随 KNOW-2 顺手
- [ ] LOOP-3 平台 Skill 两枚 — 机制已有，物料工作为主
- [ ] AGENT-2 容器 skills 注入 + 同源校验 — 通道已有（v0.9.0），物料 + 一致性测试
- [ ] LOOP-4 PR 后轻量 review 沉淀 — 依赖最深的增值项，进度紧则最先降级
- [ ] UNIFY-1 improve/analyze 收敛 — 内部重构，用户不可见，可排后

### Future Consideration (v2+ — 显式不做)

- [ ] chat.CodingPlan 与 McpCodingPlan 合表 — 单独立项（已 out of scope）
- [ ] review 产品化（UI/规则引擎） — Qodo 整条产品线的体量
- [ ] 会话内 sidecar 记忆提取（Cursor Memories 同型） — 需要旁路小模型基建 + 激进过滤 prompt 调优，投入产出比不如完工触发
- [ ] 记忆 consolidation/decay 自动策展 — 业界前沿（Mem0 刚产品化），先靠 bi-temporal 失效 + 人工 supersede 过渡
- [ ] 对外知识开放平台（配额/租户/计费） — 已 out of scope

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| learning case 入图 + 向量检索（KNOW-1/2） | HIGH | MEDIUM | P1 |
| MCP 产物入图（KNOW-3） | HIGH | MEDIUM | P1 |
| 公共回写 service 三链路（LOOP-1） | HIGH | MEDIUM | P1 |
| 完工自动提炼 learning case（LOOP-2） | HIGH | HIGH | P1 |
| 容器知识 MCP（AGENT-1） | HIGH | HIGH | P1 |
| 工作流上下文对齐（AGENT-3） | MEDIUM | LOW | P1 |
| schema snapshot 补全（UNIFY-2） | MEDIUM | LOW | P1 |
| 编排召回扩容（KNOW-4） | MEDIUM | LOW | P2 |
| Chat 工具面补读工具（KNOW-5） | MEDIUM | LOW | P2 |
| 平台 Skill 两枚（LOOP-3） | MEDIUM | MEDIUM | P2 |
| 容器 skills 注入 + 同源校验（AGENT-2） | MEDIUM | MEDIUM | P2 |
| PR 后轻量 review 沉淀（LOOP-4） | MEDIUM | MEDIUM | P3 |
| improve/analyze 收敛（UNIFY-1） | LOW（内部质量） | MEDIUM | P3 |

**Priority key:**
- P1: 本里程碑必达（验收面 1–5、7、9 的支撑）
- P2: 应做，机制已有、物料/薄封装为主（验收面 6、10）
- P3: 增值/内部收口，进度紧可降级

## Competitor Feature Analysis

| Feature | Devin (Cognition) | Cursor | Copilot coding agent | Qodo/PR-Agent | Our Approach |
|---------|-------------------|--------|----------------------|---------------|--------------|
| 经验自动沉淀 | 会话反馈→Knowledge 建议→人工审核入库；Trigger Description 控召回 | sidecar 小模型旁路提取→用户审批；激进过滤任务日志 | 无（session log 可查但不提炼） | 采纳的 review 建议→定期提炼 auto best practices（商用） | 完工回调触发 LLM 提炼→质量门槛（泛化过滤/去重/脱敏/字段校验）→自动入库 + bi-temporal 可失效；比 Devin/Cursor 更自动，靠门槛而非人工审核守质量 |
| 沉淀数据结构 | 自由文本 + trigger + pin 作用域（repo/org）+ 文件夹 | 短 rule 式条目，项目作用域 | — | markdown 最佳实践文档 | 结构化字段（outcome/root_cause/solution/trigger_context）+ 图边关联（case↔repo↔work_item↔plan↔PR）+ 向量检索——结构化程度业界最高档 |
| 完工业务回写 | issue/PR 留痕 + session 可追问 | 本地工具，无业务回写 | draft PR 全程锚定：清单打勾、commit 链 session log、完工更新描述 tag 人 | review 评论回写 PR | 公共 write-back service：飞书工作项评论 + 可选文档，三链路（工作流/Chat/MCP）统一格式 |
| 容器代理知识工具 | 会话内建知识检索（Accessed Knowledge 可见）+ Devin MCP server 对外 | MCP 生态由用户自配 | repo instructions + 自定义 MCP（firewall 内） | — | 进程内 SDK MCP server 经服务端 HTTP proxy（官方推荐模式），PAT 鉴权，读白名单 7 工具，排除/权限/脱敏零成本继承 |
| skills 分发 | 多路径 SKILL.md 自动发现 + indexed/disk 双源防漂移 + 会话中自动建议新 skill | .cursor/skills + 插件市场 | .github/skills | — | 派发时注入容器 `.claude/skills/`，与 npm 包同源 + hash 一致性测试（对齐 Devin 的防漂移思路） |
| 知识 MCP 工具面 | Devin MCP：knowledge CRUD + 建议管理 | — | — | — | 既有约 30 工具补 snapshot 完整性 + 平台级多步 Skill（pre/post coding）——多步服务端 Skill 是业界少有形态 |

## Sources

- Devin Docs — Knowledge / Knowledge Onboarding / Skills / Advanced Capabilities（docs.devin.ai，HIGH：官方文档）
- Cursor Memories 工程访谈（leverage.to Yash Gaitonde 访谈；DataCamp Cursor 课程；MEDIUM：非官方但多源一致——sidecar vs tool-call、任务日志偏好、人工审批）
- GitHub Copilot coding agent（docs.github.com + GitHub Blog，HIGH：官方——draft PR 锚定、session log、完工回写模式）
- claude-agent-sdk 安全部署与 MCP/Skills 集成（code.claude.com 官方文档 + 多篇 2026 实践指南，HIGH：`create_sdk_mcp_server`、`allowed_tools` 全名前缀、proxy 凭证模式、`setting_sources` + `Skill` 工具、fail-closed 无人值守）
- Agent memory 框架综述（Zep arXiv 2501.13956、Mem0 episodic memory blog、Zylos 2026-04 综述、多篇 2026 对比文，HIGH/MEDIUM：四分型、分层架构、bi-temporal、consolidation/decay、context pollution 未解问题）
- Reflexion（NeurIPS 2023）/ ExpeL（AAAI 2024）（HIGH：学术源——失败经验提炼、ADD/UPVOTE/DOWNVOTE/EDIT insight 策展、lesson rot 与显式 retire）
- Qodo/PR-Agent auto best practices（docs.qodo.ai + GitHub，HIGH：官方——采纳建议追踪→定期提炼→标注引用闭环，商用独占）
- Memory MCP server 生态（Loci、AutoMem、mcp-memory、awesome-mcp-servers，MEDIUM：工具面形态——store/recall/forget 核心组、去重门 cosine>0.92 参考值、fail-soft 使用协议）
- 本项目 `.planning/MILESTONE-CONTEXT.md` / `.planning/PROJECT.md`（HIGH：代码坐标与既有资产）

---
*Feature research for: Friday AI v0.17.0 统一知识库与全链路联动*
*Researched: 2026-07-15*
