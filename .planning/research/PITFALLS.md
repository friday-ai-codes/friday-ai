# Pitfalls Research

**Domain:** 在既有 Friday MCP / skills / 项目记忆 / 交付知识 RAG 上叠加 IDE 问答 Capture、价值评估与可召回精华（v0.25.0）
**Researched:** 2026-08-28
**Confidence:** HIGH（陷阱均对照本仓现行实现与锁定决策；Cursor `beforeSubmitPrompt` 能力以本仓 `ide_hook_assets.py` 注释为准）

> 相位代号仅用于 roadmap 编排，按依赖建议为：**P1 MCP 契约与仓库挂钩**（MCP-01/02）→ **P2 Skills/hooks 采集**（SKILL-01）→ **P3 Capture 账本**（STORE-01）→ **P4 价值评估与 RAG 入图**（EVAL-01）→ **P5 召回、回放与观测收口**。下文「Phase to address」对应该序，不预占具体相位号。

本文只谈**往现有系统上加这些能力时**会踩的坑，不复述通用 Web/LLM 常识。

## Critical Pitfalls

### Pitfall 1: 把 `branch_unresolved` fail-soft 当成「成功跳过」并沿用到 Capture

**What goes wrong:**
`report_project_knowledge` 在 `_resolve_report_project_id` 拿不到唯一项目时返回 HTTP 200、`accepted=false`、`reason=branch_unresolved`，**不写库、不报错、不阻断编码**。Stop hook 再包一层 `fail_soft()`（任何异常 `exit 0`）。新 Capture 若仍走这条链，零散问答在未绑项目的 `main` / 多命中分支上会**静默丢数据**，仪表盘看起来「工具调通了」。

**Why it happens:**
v0.15/v0.16 的纪律是「hook 绝不阻断编码」。测试 `test_report_project_knowledge.py` 还**正向断言**未绑分支 → `branch_unresolved` 且不入库。实现者会复制 `_resolve_report_project_id` + 200 skip，误以为 MCP-02「解析失败不得静默丢弃」已被覆盖。

**How to avoid:**
新工具把「挂钩」与「项目」拆开：仓库（`repository_id` / remote URL / 仓名）足够则**必须落 Capture**；项目是可选增强。`branch_unresolved` 只能表示「未挂项目」，不得表示「未收」。无仓无项目时返回显式原因码（如 `unanchored`）并仍落匿名/用户级队列，或 fail-loud 给 skill 重试——禁止 200 + 空写入冒充成功。旧 `report_project_knowledge` 行为可保留给 MEMORY 路径，Capture **不要**复用同一 skip 语义。

**Warning signs:**
- 新视图仍 `if resolved_pid is None: return 200 accepted=false`。
- 测试把「无 `project_id`」当成拒收而不是入库。
- hook 日志只有 `exit 0`，DB 无 Capture 行。

**Phase to address:**
P1 MCP 契约（MCP-01/02）。P2 不得先接线旧 skip。

---

### Pitfall 2: Stop hook 只报 `git diff --stat`，把「无改动」当成「无知识」

**What goes wrong:**
现行 `skills/hooks/stop`：无分支/`HEAD` 跳过；`diff --stat` 为空则跳过（注释写明只读会话会刷「最近提交」噪音）；再加 300s 间隔与内容指纹。里程碑目标是**无 git 改动的纯问答也回写**。沿用 stop + diff 门，Capture 永远收不到 Q&A。

**Why it happens:**
防噪音是真实踩过的坑（hook 注释）。实现者会「只放宽质量门槛」却不改触发条件。

**How to avoid:**
采集触发与「是否有工作区 diff」解耦。Stop 仍可附带 diff 摘要作**可选上下文**；问答正文来自会话抽取（skill / 工具参数），无 diff 也提交。本地去重键改为 `(session_id, question_hash, answer_hash)`，不要用 diff 指纹挡住对话。300s 节流只用于「同一 diff 摘要」，不要套到每条 Q&A。

**Warning signs:**
- 新 hook 仍 `if not changes: fail_soft()`。
- payload 只有「本次会话改动摘要」没有 `question`/`answer`。
- 验收用例全是「改了代码再停」。

**Phase to address:**
P2 Skills/hooks（SKILL-01）。P1 契约必须先有 Q&A 字段，否则 hook 只能塞进 `content` 自由文本。

---

### Pitfall 3: 假设 Cursor 能在 `beforeSubmitPrompt` 注入上下文或对称采集

**What goes wrong:**
本仓已写死：Cursor `beforeSubmitPrompt` **只能放行/拦截，不能注入上下文**（`ide_hook_assets.py`）。读路径 Cursor 只靠 always-on 规则 + MCP。写路径若照抄 Claude Code `UserPromptSubmit`/`Stop` 注册到 Cursor，采集器根本跑不起来或只能拦截提交。

**Why it happens:**
三家 IDE 被当成同一 hook 模型；skills 安装器会把 Claude 专属 hook 拷进 Cursor 目录。

**How to avoid:**
采集主链必须是 **MCP 工具由 agent/skill 显式调用**（会话结束或 skill 步骤），hooks 只作 Claude Code 增强。Cursor：规则 + skill 强制调新 Capture 工具；不要做注入 hook。Codex 同样「仅 MCP + rules」。资产 `notes` 继续声明限制；加守卫测试：Cursor 资产树**零** `UserPromptSubmit` / `beforeSubmitPrompt` 注入脚本。

**Warning signs:**
- Cursor 产物出现 `hooks.json` 的 `UserPromptSubmit`。
- 设计文档写「三家 hook 对称」。
- 验收只在 Claude Code 插件形态演示。

**Phase to address:**
P2 Skills/hooks。与 P1 工具面并行设计，避免 hook-only 方案。

---

### Pitfall 4: `lookup_project_by_branch` 在通用 `main` 上假命中，污染读写两侧

**What goes wrong:**
lookup 第三源：分支两源皆空且传了 `repository_id` 时，用 `RepoAssociation`（confirmed/verifying/verified）反查项目；**唯一命中即 `matched=true` 并注入 context**。开发者日常在仓默认分支 `main`/`master`/`develop` 提问时，会把**该仓关联的任意一个项目**当成「当前项目」。debug 会话已记录：`Friday branch lookup matched an unrelated project solely through generic main`。`_resolve_report_project_id` **没有**第三源，只走 work_item 解析 + `ProjectBranch`——读注入了项目 A，写回却 `branch_unresolved`。或反过来：有人给 `main` 做了 `ProjectBranch` 绑定，写回进错误项目记忆。

**Why it happens:**
quick-260723 用仓库兜底覆盖人工命名 feat 分支，未把默认分支排除。`parse_work_item_id_from_branch("main")` 为 `None`，于是直接掉进 RepoAssociation。

**How to avoid:**
默认分支名（仓 `default_branch` 或闭集 `main`/`master`/`develop`/`trunk`）**禁止**作为唯一项目信号。lookup：默认分支上第三源不注入 context（`matched=false`，可回候选）；仅 `ProjectBranch` 显式绑定或 feat/`-m{id}-` 形态才 `matched=true`。Capture 挂钩以仓库为准，**不要**为了「有项目」去调用 lookup 的第三源。读写解析函数必须同源或明确分表，禁止「读有第三源、写没有」。

**Warning signs:**
- 在 `main` 上 `matched=true` 且 `binding_source=repo_association`。
- Capture 或 MEMORY 出现与当前问答无关的项目记忆。
- 同一 `branch_name` lookup 命中、report skip。

**Phase to address:**
P1 解析策略（与 MCP-02 同批）。P5 回归：`main` + 唯一 RepoAssociation 不得注入、不得当项目主键写 Capture。

---

### Pitfall 5: 把 Interaction Ledger（或 MCP `run` 记录）当 RAG 正文

**What goes wrong:**
MCP 工具已 `begin_interaction_run` + `arecord_event` / `arecord_retrieval_trace`。实现者会觉得「问答已经在 Ledger 里了」，对 `InteractionEvent` payload 做 embedding，或让 `DeliveryKnowledgeSearchService` 扫 ledger 表。v0.17 已锁定 **Ledger 反哺检索为 Out of Scope**；v0.25 决策：Capture / 提炼知识 / Ledger **三层分离**。Ledger 含工具 I/O、可能含未脱敏片段与用量字段，入向量会把审计垃圾和密钥形态带进召回。

**Why it happens:**
「少一张表」；`redact_for_ledger` 被误读成「已可检索」。

**How to avoid:**
Ledger 只服务审计/用量/回放索引（可存 `capture_id` 外键）。RAG 只吃 **P4 提炼后的精华**（中高价值），经 `aschedule_ingestion` + `delivery_knowledge`。原始问答只在 Capture 账本。加 AST/grep 守卫：`DeliveryKnowledgeSearchService` / normalizer / `ingest_events` 不得 import `interactions.models` 当语料。评测回放读 Capture，不读 Ledger 全文。

**Warning signs:**
- normalizer `source_kind` 叫 `interaction_run` / `mcp_tool_call`。
- 检索测试 fixture 从 `InteractionEvent` 取 text。
- 需求写成「复用 Ledger 免建表」。

**Phase to address:**
P3 Capture 账本立表时焊死。P4 入图白名单不含 Ledger。

---

### Pitfall 6: 扩大 `writeback_mode=active`，用项目记忆冒充会话知识（MEM-04 / INV-6）

**What goes wrong:**
`MemoryService` INV-6：LLM 只 `create_draft`，人工 `confirm_draft` 才 active（MEM-04）。例外是 2026-06-26 **用户授权、范围极窄**的 `record_hook_writeback`（stop hook + 质量门槛 + 脱敏 + 非成员静默跳过）。把 IDE Q&A 再打进 `writeback_mode=active` → `ProjectMemory`，等于把 MEM-04 例外变成默认通道：共享项目记忆被会话噪音淹没，且与「Memory 只承载可召回精华」决策冲突。旁路 `ProjectMemory.objects.create` 还会红掉 `test_memory_inv6_guard`。

**Why it happens:**
现成 MCP 工具、现成 hook、现成质量门槛，看起来「加字段就能交差」。

**How to avoid:**
Capture **新写模型 + 新 Service 单一入口**（INV-6）。默认不要写 `ProjectMemory`。若中高价值要进「项目可召回」，走知识摄取（`source_kind` 新行 + 既有 kind），或经 `create_draft` 等人审——**禁止**把 Capture 评估器接到 `record_hook_writeback`。active 例外白名单保持「仅 git diff 摘要类 stop hook」，测试锁定：新 Q&A 工具即使 `writeback_mode=active` 也不得增加 `ProjectMemory` 行。

**Warning signs:**
- 新 serializer 复用 `ReportProjectKnowledgeRequestSerializer`。
- Capture 完成回调调用 `MemoryService.append`。
- 方案写「沿用 HOOK-02 accepted deviation」。

**Phase to address:**
P3 账本 + Memory 边界。P4 入项目 RAG 另开摄取，不经 MEMORY active。

---

### Pitfall 7: 新增 `EntityKind` 或改 kind 字面值，造成 uuid5 实体身份漂移

**What goes wrong:**
`generate_entity_id(kind, source_kind, source_id)` 拼接 `f"{kind}:{source_kind}:{source_id}"`。kind 进 uuid5：**先**按 `document` 入图、**再**改成新 kind，会生成另一 PK，旧点不 tombstone → 双实体。改已有 kind 字面值 = 全量迁移。`kentity_kind_valid` CheckConstraint + 枚举锁定。历史惯例（Phase 100/116）：MCP plan/蓝图 **复用** `tech_plan`/`document`/`code_change`，用 `source_kind` 分子类，**不**为每个产品概念加 EntityKind。

**Why it happens:**
「会话知识」看起来像新类型；过滤想 `entity_kinds=["ide_capture"]`。

**How to avoid:**
默认：操作态 Capture 表 + 入图用既有 kind（优先 `document` 或 `learning_case`）+ **新 `source_kind`**（如 `ide_session_capture`）写进 `generate_entity_id` docstring 规则表。确需新 kind 时：一次性 migration 改约束、**禁止**对已入图行改 kind、检索 filter 用 `source_kind` 而非发明平行 collection。禁止在 normalizer/测试里手写 `uuid5(KNOWLEDGE_NAMESPACE, ...)`。

**Warning signs:**
- PR 改 `EntityKind` 却无「零存量行」证明。
- 同 `source_id` 出现两个 `KnowledgeEntity`。
- 前端/MCP 复制 uuid5 公式。

**Phase to address:**
P4 入图设计（EVAL-01）。P3 不要提前把 Capture UUID 当成 knowledge PK。

---

### Pitfall 8: Capture 入 RAG 走 `aschedule_ingestion` → `background_runner`，重启丢向量

**What goes wrong:**
`aschedule_ingestion`：`transaction.on_commit` + `run_in_background(ingest)`。`background_runner` 自 v0.12 **定位为进程内、重启即丢**；生产长任务应走 durable。HTTP 200「已接受 Capture」后 worker 未跑完就重启 → PG 有 Capture、Qdrant 无点，召回空。现有 learning_case 已有此窗口；高频 IDE 回写会放大。

**Why it happens:**
「与 Phase 13 完全一致」被当成生产语义；测试里 runner 立即执行，绿不到丢任务。

**How to avoid:**
Capture 行是真相，状态机至少 `captured → grading → ingest_pending → ingested|ingest_failed`（低价值停在 captured，不向量化）。入图投递：**durable 队列**（与 index/graph 同底座）或可重试 outbox；禁止把「唯一投递」交给 `run_in_background`。启动/rescue 扫描 `ingest_pending`。`aschedule_ingestion` 可保留给低频产物，但 IDE 路径要可观察积压（LOGGING-SPEC `task_backlog`）。

**Warning signs:**
- 新 ingest 只 `run_in_background`，无 durable job id。
- 无 `ingest_pending` 对账命令。
- 单测 mock 掉 ingest 且无失败重放测。

**Phase to address:**
P4 入图投递。P3 状态字段先留好，避免 P4 再迁一次。

---

### Pitfall 9: 价值评估 LLM 未赋 `call_source`，或与 `llm_grader` 检索分级混用

**What goes wrong:**
`knowledge/llm_grader.py` 的 `grade_search_results` 做检索 **duplicate/related/unrelated**，`ainvoke` **没有** `use_call_source`；枚举里已有 `aux_knowledge_grader` 却未接线；失败日志 `error=str(exc)` 未走 `redact_secrets_in_text`。新「高/中/低价值」若复用该模块或同样裸 `ainvoke`：用量进 `unknown`、与检索分级词表冲突、路由 `confidence` 被误当成知识价值（PROJECT 已否决）。

**Why it happens:**
「已经有 grader」；复制 `llm_grader` 最快。

**How to avoid:**
新评估器独立模块 + 新 `CallSource`（先改 `call_source.py` 与 LOGGING-SPEC §4.1 再写业务）。`use_call_source` 包住整次 LLM。词表锁定 `high|medium|low`，禁止 `related/duplicate`。失败 fail-soft：Capture 仍保存，grade=`unevaluated`，不丢原文。不要用 `evaluate_writeback_quality`（过短/Jaccard）代替价值等级——那是防噪音，不是评测。补修既有 `llm_grader` 的 `call_source`/脱敏可作为同相位卫生项，但不要把它改成价值评估。

**Warning signs:**
- 评估 prompt 输出 `related`。
- `ModelUsageRecord` 无新 call_source。
- 用 RepoRouter confidence 过滤是否入 RAG。

**Phase to address:**
P4 评估。观测清单与 EVAL-01 同门禁。

---

### Pitfall 10: MCP 服务端新了工具，npm `mcp` 包 / skills 快照 / 容器白名单未齐

**What goes wrong:**
v0.20/v0.22 反复出现：Django MCP 已有工具，`mcp` npm 客户端缺工具 → `test_mcp_package_alignment` 红或生产 IDE 调不到。skills 快照守卫曾只检查反引号工具名子集，不检查协议语义（debug：缺 `approve_`/`request_` 前缀仍绿）。容器知识 MCP 是白名单子集。只改 `views.py` 时 Cursor 用户永远调不到新 Capture 工具。

**Why it happens:**
三仓/三发布面（server / mcp submodule / skills）节奏不同；安装器缓存旧 skill。

**How to avoid:**
同一里程碑把 **serializer + url + TOOL_SCHEMA_SNAPSHOT + npm tools.ts + skills SKILL.md + 容器 `KNOWLEDGE_TOOL_SCHEMAS`（若容器也要写）** 列为同一验收。对齐测试必须含新工具名。skills 守卫覆盖协议字段（`question`/`answer`/`repository`），不能只做 token 子集。文档写明：未发 npm 则 IDE 不可达。

**Warning signs:**
- 仅 server 测试绿。
- skill 仍教 `report_project_knowledge` 作为问答回写。
- 容器 agent 无新工具但产品宣称「编码容器也能沉淀会话」。

**Phase to address:**
P1 工具面（server+npm）。P2 skill 文案。容器写入若做，放 P2 末或明确 Out of Scope。

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| 复用 `report_project_knowledge` 塞 Q&A 进 `content` | 零新端点 | 无结构、无法评测回放、继续 `branch_unresolved` 丢数 | never（与 MCP-01 冲突） |
| Capture 行直接 `objects.create` | 少一个 Service | INV-6 失守、无脱敏/审计/成员口径 | never |
| 入图继续只走 `background_runner` | 少接 durable | 重启丢向量、无法积压告警 | 仅本地 SQLite/pytest；生产 never |
| 中高价值自动 `record_hook_writeback` | 项目工作台立刻能看见 | 永久破坏 MEM-04；记忆变会话垃圾桶 | never |
| 新 EntityKind `ide_qa` | 检索 filter 好看 | uuid5 空间膨胀、约束迁移、与 Phase 100 惯例分裂 | 仅当 `source_kind` 过滤被证明不够，且无存量点 |
| Claude Code hook 先做、Cursor 后补 | 演示快 | Cursor 是主用户；hook 方案不可移植 | MVP 可先 CC 增强，但 **MCP 主链必须同时支持 Cursor** |
| 低价值不落库 | 省存储 | 无评测样本，EVAL 闭环断裂 | never（STORE/EVAL：低价值留样本、不向量化） |
| 客户端猜模型名/token | 报表好看 | 假数据进评测 | never；缺省 `unknown` |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| `report_project_knowledge` | Capture 复用 `_resolve_report_project_id` skip | 新工具；无项目仍收；旧工具保持 MEMORY 语义以免回归 |
| `lookup_project_by_branch` | 用其 `project_id` 当 Capture 主键 | 仓为主；lookup 仅可选 enrich；默认分支假命中丢弃 |
| `MemoryService` / MEM-04 | Q&A active 直写记忆 | Capture Service；精华入 `delivery_knowledge` |
| `aschedule_ingestion` | 当 exactly-once | Capture 先提交；durable/outbox；对账 `ingest_pending` |
| `generate_entity_id` | 新 kind 或手写 uuid5 | 新 `source_kind` + docstring 表；唯一入口 |
| `llm_grader.py` | 当价值评估或继续无 call_source | 独立评估器 + 新 CallSource；卫生项再补 grader |
| Interaction Ledger | payload 进 Qdrant | 只链 `capture_id`；检索禁读 ledger |
| skills Stop hook | 无 diff 不报 | Q&A 与 diff 解耦；fail-soft 不得吞「未发送」 |
| Cursor hooks | 注册注入型 hook | 规则 + MCP；声明 `beforeSubmitPrompt` 不能注入 |
| npm `@friday-ai-codes/mcp` | 只改 Django | 同步 tools、snapshot、发版说明 |
| 容器 MCP 白名单 | 默认「全工具」 | 写路径显式加白或本里程碑不做容器写 |
| `evaluate_writeback_quality` | 当 high/medium/low | 仅防空/短/重复；价值另 LLM |
| Provider / `initiated_by_user_id` | 后台评估记 `system` | PAT 用户透传；`bind_task_context` |
| 排除文件 / 脱敏 | 把 `.env` 内容当答案 | `redact_secrets_in_text` 入库前；排除路径不进 Capture 附件 |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| 每条 Stop/每条消息全量 embed | 索引延迟、embedding 配额 | 仅中高价值向量化；低价值不进 Qdrant | 团队日均数百次 IDE 回写 |
| 同步 LLM 评估挡 MCP 响应 | IDE 超时、hook 10s 不够 | Capture 先 202/200 落库；评估异步 | 评估 > 数秒即拖垮 hook |
| lookup 在 `main` 打包整个项目 context | 上下文爆炸、错误项目 | 默认分支不注入；Capture 不依赖 lookup 正文 | 大项目 packer 已很重 |
| 原始问答全文进 delivery_knowledge | 召回被闲聊占据 | 只索引提炼精华；原文仅 Capture | 数周后检索质量塌 |
| 无幂等键（session+turn） | 重复点、重复记忆 | `(user, session_id, turn_id)` 或内容 hash upsert | hook 重试 / agent 连点 |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| hook/skill 上报完整隐藏思维链或工具原始 I/O | 密钥、内部 URL、PAT 进 Capture/RAG | 客户端只抽精华；服务端再 `redact_secrets_in_text`；禁止 CoT 字段 |
| 日志打印 question/answer 全文 | 凭证进系统日志 | kv 只记长度/hash；正文不进 INFO |
| `error=str(exc)` 评估失败 | 上游响应泄漏（`llm_grader` 已有此形态） | `redact_secrets_in_text` |
| 无成员校验的项目 RAG 命中 | 非成员召回他项目会话 | 入图带 `project_id`/`repository_id`；检索沿用 fail-closed access_scope |
| 未认证 hook 打到「匿名 Capture」 | 投毒知识库 | PAT/JWT 必填；无凭证 fail-soft **且不写** |
| 把 Ledger 当语料 | 审计库扩大攻击面 | 物理隔离；检索禁 import |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| 工具 200 + `accepted=false` | 用户以为已沉淀 | Capture：明确 `stored=true/false`；skip 与 stored 分字段 |
| 只在 Claude Code 自动、Cursor 全靠自觉 | Cursor 用户零回写 | skill 强制步骤 + 规则；不依赖注入 hook |
| 默认分支注入错误项目上下文 | 编码按错需求 | 默认分支不 `matched` 注入 |
| 低价值「消失」 | 无法做评测、无法申诉 | 工作台可筛选 grade；低价值只是不进 RAG |
| 自动写进项目记忆时间线 | 成员被 diff 摘要刷屏 | 记忆保持人审；会话知识走知识库/Capture UI |

## "Looks Done But Isn't" Checklist

- [ ] **MCP-02：** 无 `project_id` 仍有 Capture 行 — 用未绑 `main` 打工具，断言 DB insert 而非 `branch_unresolved`
- [ ] **SKILL-01：** 无 git diff 的问答 — 干净工作树停会话，仍有 Q&A payload
- [ ] **Cursor：** 无注入 hook，有 skill/规则调新工具 — 资产测试禁止 CC 专属 hook 出现在 Cursor 树
- [ ] **默认分支：** `lookup` 在唯一 RepoAssociation + `main` 上 `matched=false`（无显式 `ProjectBranch`）
- [ ] **STORE-01：** Capture 表 ≠ Ledger ≠ `ProjectMemory` — grep 入图路径无 `interactions.models` 语料
- [ ] **MEM-04：** 新 Q&A 路径零新增 active `ProjectMemory`（除非单独人审草稿）
- [ ] **INV-6：** Capture 仅经 `*Service`；有 grep 守卫
- [ ] **uuid5：** 无新 kind 或有迁移+docstring 规则表；无散落 `uuid5(`
- [ ] **ingest：** 重启后 `ingest_pending` 能续；不只 `background_runner`
- [ ] **EVAL-01：** 低价值有行、无向量点；中高有点且 `source_kind` 可滤
- [ ] **call_source：** 评估 LLM 在枚举内且 `use_call_source`；`llm_grader` 勿冒充价值分
- [ ] **三面对齐：** Django snapshot + npm 工具列表 + skills 文案含同一工具名
- [ ] **脱敏：** 含假 token 的答案入库后为红acted
- [ ] **RetrievalTrace：** 召回 Capture 精华时 MCP/Chat 两链有 trace
- [ ] **initiated_by_user_id：** durable 评估/ingest worker 非默默 `system`（有 PAT 时）

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| 静默 `branch_unresolved` 丢数 | HIGH（客户端未留） | 无法找回；修契约后只能从 IDE 重跑。预防优先 |
| diff 门挡掉纯对话 | MEDIUM | 放宽 hook；历史已丢。新会话生效 |
| `main` 假命中写入错项目 | MEDIUM | 按时间+分支筛 Capture/记忆，迁仓或 supersede；lookup 加默认分支黑名单 |
| Ledger 已入 Qdrant | HIGH | 按 `source_kind` tombstone 点；停 normalizer；对账 13-04 类 reconcile |
| 误扩 active 记忆 | MEDIUM | `supersede` 批量；审计 `ACTION_PROJECT_MEMORY_CREATED` 回放 |
| kind 字面值漂移双实体 | HIGH | 冻结写入；写迁移合并/作废旧 id；全量 revector |
| ingest 重启丢失 | LOW–MEDIUM | 扫描未 ingest Capture 重投 durable；补状态机 |
| 无 call_source 评估 | LOW | 补枚举与 contextvar；历史用量无法重标 |
| npm/skill 未齐 | LOW | 发 mcp/skills 版本；安装器重装；对齐测试锁门 |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| `branch_unresolved` 丢 Capture | P1 MCP 契约 | 无项目+有仓 → 201/200 `stored=true`；测试禁止 skip 当成功 |
| Stop 仅 diff | P2 hooks/skills | 无改动 fixture 仍 POST Q&A |
| Cursor 不能注入 | P2 | Cursor 资产无注入 hook；文档 notes |
| `main` 假命中 | P1 解析 + P5 回归 | lookup `main`+唯一 association → 不注入 |
| Ledger→RAG | P3/P4 | import 守卫 + 检索测不用 ledger |
| MEM-04 / active 记忆 | P3 | Q&A 不增 `ProjectMemory` |
| uuid5 kind 漂移 | P4 | 复用 kind+新 source_kind；约束测试 |
| background_runner 丢 ingest | P4 | durable/outbox + 重启续跑测 |
| 评估无 call_source / 混 grader | P4 | CallSource 测试 + 词表闭集 |
| 三面契约漂移 | P1+P2 | snapshot + npm alignment + skill 语义守卫 |

## Sources

- `server/mcp_tools/views.py`：`_resolve_report_project_id`、`lookup_project_by_branch` 第三源、`ReportProjectKnowledgeView` skip/`active` 分流
- `skills/hooks/stop`、`skills/hooks/hooks.json`、`skills/hooks/user-prompt-submit`
- `server/initiatives/services/ide_hook_assets.py`：Cursor `beforeSubmitPrompt` 不能注入
- `server/initiatives/services/memory_service.py`：MEM-04 vs `record_hook_writeback`
- `server/knowledge/ingestion.py` + `server/services/background_runner.py`：进程内 ingest、重启即丢
- `server/knowledge/models.py`：`generate_entity_id` / `EntityKind` 锁定
- `server/knowledge/llm_grader.py`：无 `use_call_source`；词表 related/duplicate
- `server/agents/call_source.py`：`aux_knowledge_grader` / `ide_hook_distill` 已存在
- `.planning/PROJECT.md` v0.25.0 决策：仓为主挂钩、三层分离、禁止 Ledger 反哺、价值≠路由 confidence
- `.planning/debug/multica-friday-agent-e2e.md`：`main` 假命中无关项目
- v0.17 Out of Scope：Ledger 反哺检索；INV-6 `aschedule_ingestion` 单一摄取入口

---
*Pitfalls research for: Friday AI v0.25.0 IDE 会话知识回写（Capture + 评估 + RAG）*
*Researched: 2026-08-28*
