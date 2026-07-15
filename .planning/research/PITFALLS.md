# Pitfalls Research

**Domain:** 既有 AI 交付自动化系统（Friday AI，brownfield）新增"统一知识库 + 完工沉淀闭环 + 容器内置 MCP/Skills + 工具面收口"
**Researched:** 2026-07-15
**Confidence:** HIGH（坑 1–8 均以仓库真实代码坐标 + 外部来源交叉验证；个别缓解手段为 MEDIUM，正文标注）

> 本文写给 roadmapper 与 plan-phase：每个坑聚焦"往既有系统加这些功能"的集成风险，不是泛泛 LLM 应用坑。Phase 指 v0.17.0 的四大块（KNOW / LOOP / AGENT / UNIFY），Phases 100+ 具体编号由 roadmap 落定后按块映射。

## Critical Pitfalls

### Pitfall 1: 检索底层切换（token→向量）的召回回归与 API 契约漂移

**What goes wrong:**
`search_learning_cases` 从 token 打分（`mcp_tools/learning_case_service.py` 的 `_TOKEN_RE` 命中计数 + repo/file/symbol hint 加权）切到 `DeliveryKnowledgeSearchService` 向量检索后，出现三类回归：
1. **精确标识符召回变差**——token 版对仓库名、文件路径、symbol 这类精确串命中是强项（hint 命中 +3.0 分），纯向量对 `server/mcp_tools/views.py` 这种路径类查询天然弱（外部验证：向量检索对 exact identifiers / rare terms 的召回缺口是行业共识坑）。
2. **API 契约静默漂移**——现契约里 `score` 是 token 命中计数（0–N 开区间、`round(score, 4)`），向量版是余弦相似度（约 0–1）；调用方（Cursor friday-memory skill、`create_feishu_technical_plan` 自动召回）若对 score 有阈值/排序假设会静默失真。`work_item_type` 过滤、`repo_hints`/`file_hints`/`symbol_hints` 参数语义也要在向量层重新实现，容易"参数还在、不再生效"。
3. **存量数据空窗**——存量 `McpLearningCase` 从未入过 `delivery_knowledge` 向量库；切换当天若无 backfill，向量检索对全部历史 case 返回空，看起来像"检索坏了"。
4. **基础设施依赖变化**——token 版纯 DB 查询，向量版依赖 Qdrant 在线；dev（SQLite、无 Qdrant）与 Qdrant 故障场景下行为从"能用"变"报错/空结果"。

**Why it happens:**
"底层换实现、契约不变"听起来是纯重构，但检索的"契约"不仅是 request/response schema，还包括**召回分布与 score 语义**——这部分没有类型系统保护，只有对照测试能看住。

**How to avoid:**
- **切换前先建 golden set**：从现有 token 版跑 30–100 条真实查询（含精确路径/symbol 查询、中文语义查询、hint 组合），记录"必须可召回集合"；切换后断言这些集合非空且目标 case 在 top-k 内（milestone 风险 1 已点名，落成 pytest 固定用例，不是一次性人工对比）。
- **hint 类参数走过滤/加权而非丢弃**：`repo_hints`/`file_hints` 映射为向量检索的 metadata 过滤或后置 rerank 加权；如向量层不支持，保留一条轻量 keyword 补召回路径（hybrid），不要让参数变摆设。
- **score 语义显式定版**：要么归一化到 0–1 并在工具 schema 描述里写清语义变化，要么在 payload 中新增 `score_kind` 字段；`TOOL_SCHEMA_SNAPSHOT` 与快照测试（`server/tests/mcp_tools/test_schema_snapshot.py`）同步更新。
- **backfill 与切换解耦为两步**：先写 normalizer + management command 把存量 case 全量入图（可观察摄取成功率），确认向量侧可召回后再切读路径；切换后保留 token 实现一个里程碑周期作为 fallback 开关（MEDIUM：是否留开关可在 plan-phase 权衡）。
- **Qdrant 不可用时 fail-soft**：向量检索异常降级为空结果 + 结构化 `xxx_failed` 事件，不抛 500（对齐"观测永不反噬业务"）。

**Warning signs:**
- 对照测试里"路径/symbol 类查询"召回集合明显缩水而"语义类查询"变好——典型 hybrid 缺口信号。
- 切换 PR 里没有出现 backfill command / 数据迁移，只有 service 层改动。
- `TOOL_SCHEMA_SNAPSHOT` diff 为空但返回 payload 字段语义实际变了。
- 上线后 `search_learning_cases` 空结果率突增（RetrievalTrace 条数指标可见）。

**Phase to address:**
KNOW 块的"learning case 入图 + 检索切换" phase：**normalizer + backfill 与读路径切换必须在同一 phase 内闭环**（否则中间态"写了新库、读还在旧库"或反之），golden set 对照测试作为该 phase 的验收门。

---

### Pitfall 2: 自动 LLM 沉淀的噪音污染与成本失控

**What goes wrong:**
编码完成回调自动触发 LLM 提炼 learning case 后，知识库被低质量 case 淹没：失败/中途取消的任务也产 case、同一任务重复产多条 case、case 内容复述 diff 而非提炼"root_cause/solution"、召回时垃圾 case 挤掉人工精品 case。外部佐证极强：mem0 社区审计 10,134 条自动沉淀记忆发现 **97.8% 是垃圾**，根因正是"提取后无准入门槛直进向量库 + 回调重入放大"。成本侧：每次编码完成一次 LLM 调用看似可控，但叠加"PR 后可选 review 沉淀"与重试后放大，且无 per-source 用量归因时发现不了。

**Why it happens:**
两个本仓库特有的放大器：
1. **callback 重入自驱**——v0.8 起 `subagent/api/callbacks.py` 的回调被刻意设计为"重入自驱推进 wave"（同一 TaskResult 的回调路径可能被走多次），沉淀钩子若挂在回调上而不做幂等，天然重复提炼。
2. **fail-soft 掩盖质量问题**——沉淀被正确地定为 best-effort 吞异常，但"吞异常"会连带吞掉"产出了但质量差"的信号，没有人看见它在变坏。

**How to avoid:**
- **幂等键前置**：以 `TaskResult`/session UUID 为确定性锚（对齐 natural key 规则表 `task_result` 行），提炼前先查"该 result 是否已产 case"，重入直接跳过——这是最便宜也最必须的一道闸。
- **准入门槛（admission gate），不是产了就入库**：最小规则集——任务 status 非 success 不提炼（或只提炼为 failure 教训并显式标注 outcome）；提炼产物缺 `root_cause` 或 `solution` 为空/过短则丢弃并计数；diff 为空或极小的任务不提炼。行业方向（A-MAC、Bedrock AgentCore consolidation）是"打分准入 + 异步整合"，本里程碑不必上打分模型，但**必须有显式 REJECT 路径**，不能只有 ADD。
- **成本归因先行**：新 `call_source`（如 `learning_case_distill`、`post_pr_review`）在第一行代码前登记 LOGGING-SPEC §4.1，`ModelUsageRecord` 自动可按 source 聚合；给该 source 配可观测阈值（日调用数/日 token）而非事后追查。
- **提炼失败/被拒也要有结构化事件**（`learning_case_distill_rejected`，category=sampling），让"质量门在挡什么"可见。
- **可关**：自动沉淀提供系统级开关（`SystemSetting`），污染发生时能立即止血而不用回滚代码。

**Warning signs:**
- learning case 日增量与编码任务完成数不是约 1:1（>1 说明重复提炼，明显 >1 说明回调重入没挡住）。
- `search_learning_cases` top-k 里自动 case 占比迅速接近 100%、且 `root_cause` 字段大面积雷同或空泛。
- `ModelUsageRecord` 里新 call_source 的 token 曲线随重试/失败率上升而非随任务量上升。

**Phase to address:**
LOOP 块"自动经验沉淀" phase：幂等键 + 准入规则 + call_source 登记与提炼逻辑**同 phase 落地**（不是"先跑通再补质量门"——污染入库后清理成本远高于预防，见 Recovery）。回写/沉淀开关的默认值决策也在此 phase 显式过一遍（联动 Pitfall 3）。

---

### Pitfall 3: 回写开关默认值改变存量部署行为

**What goes wrong:**
公共飞书回写 service 接入工作流 `ai_coding` 后，若"默认开"，存量部署升级当天，**所有已保存的工作流**跑完编码突然开始往飞书工作项写评论/文档——用户没改任何配置。轻则重复通知（既有 `notify_feishu_im` 下游节点 + 新回写 = 一件事两条消息），重则写错对象（工作流上下文里 work_item 绑定缺失/陈旧时评论挂错单）、或用无权限凭证反复失败刷 error 日志。反向坑同样存在：若"默认关"，验收面第 3 条（"工作流跑完自动出现结果评论"）对升级用户不成立，功能等于没上。

**Why it happens:**
brownfield 加开关的经典两难：新默认值只对"新建"安全，对"存量已保存配置"是静默行为变更。本仓库的既有先例是把配置放在节点 config 上（如 `CreateGroupChatNode` 的可选写回），而节点 config 是随工作流定义持久化的——**存量工作流定义里根本没有这个字段**，代码里的 fallback 默认值就是存量行为。

**How to avoid:**
- **区分"模板默认"与"存量 fallback"**：内置模板/新建节点默认开（对齐 milestone 预设），但节点 config 缺失该字段时的代码 fallback 明确定为——有绑定 work_item 才回写、无绑定静默跳过（fail-soft），并把该决策写进升级说明。这样存量工作流"绑定了 work_item 的"获得新能力，"没绑定的"零变化。
- **回写前守门**：work_item 存在性 + 凭证可用性校验，任一不满足记 `writeback_skipped` 事件后跳过，绝不重试轰炸飞书 API。
- **与既有通知去重界定**：回写（工作项评论，业务留痕）与 IM 推送（群卡片，即时通知）语义分开写清，避免用户看到"两条差不多的消息"后把整个功能关掉。
- **升级说明 + 审计留痕**：回写动作 emit 审计/结构化事件带 `initiated_by_user_id`（工作流触发者，无则 `system`），让"谁的工作流往哪个单写了什么"可回答。

**Warning signs:**
- 升级后飞书侧出现大量来源为 Friday 的评论且用户反馈"我没配过这个"。
- 日志里 `writeback_failed` 高频出现同一 work_item / 同一凭证错误（守门缺失信号）。
- 测试只覆盖"新建节点带 config"路径，没有"存量节点 config 无该键"的 fallback 用例。

**Phase to address:**
LOOP 块"公共回写 service" phase：fallback 语义、守门、与 `notify_feishu_im` 的关系界定都是该 phase 的设计输入，不是收尾补丁。roadmap 上该 phase 的成功标准应显式含"存量工作流（未绑定 work_item）行为零变化"。

---

### Pitfall 4: 容器内 MCP 的时延/负载/凭证泄漏/排除绕过

**What goes wrong:**
task 容器挂 Friday 知识 MCP（HTTP 转调 `/api/mcp/tools/*`，PAT 鉴权）后四类风险叠加：
1. **时延与负载**：agent 在编码 hot loop 里高频调检索（一次任务几十次 `search_rag_chunks`），每次都是跨网络 HTTP + 服务端向量检索，编码总时长显著拉长；多容器并发时服务端 QPS 突增（原 MCP 工具面只服务 Cursor 人类节奏，现在是 agent 机器节奏）。
2. **凭证泄漏面扩大**：PAT 是任务 user_token（PAT-02 约束：明文绝不落盘）。MCP server 配置若以文件形式写进 workspace（`.mcp.json` 风格），或 PAT 出现在 agent 可读的 env dump / 错误信息里，**agent 可能把它读进上下文进而写进 diff/PR/日志**——这是比传统日志泄漏更隐蔽的新通道。
3. **排除文件绕过**：服务端工具层排除 fail-closed 已有（v0.5），"天然继承"成立的前提是**只走白名单工具**；若白名单里混入能间接读任意内容的工具，或转调层拼错误信息时把上游响应体原样透出，排除与脱敏就被打洞。
4. **`allowed_tools` 排他白名单陷阱（本仓库特有，最容易翻车）**：`task/core/executor.py` 明确注释——`allowed_tools` 一旦非空即排他，挂新 MCP server 时若只列远程工具名，会**连带禁掉 Bash/Edit/Write 等编码内建工具，编码直接废掉**。ask_user 集成时已踩过一次（代码里 `_BUILTIN_CODING_TOOLS` 必须一并列入），新增 knowledge MCP 是第三个挂载方，三方 merge 逻辑一旦有一方漏列就全盘失效。

**Why it happens:**
容器内 agent 是全新的调用主体：既有工具面的权限/排除/脱敏假设"调用方是外部客户端"，而 agent 拿着 PAT 在服务器眼里与 Cursor 无异，但它的调用频率、错误处理方式（把响应塞进上下文）、和对 workspace 文件的读写能力都完全不同。

**How to avoid:**
- **白名单最小化 + 每任务配额/超时**（milestone 风险 2 已点名）：白名单锁定 7 个只读检索工具；task 侧转调层做 per-task 调用计数与单次超时，超限后工具返回明确"配额已用尽"提示（agent 可理解并停止重试），不无声失败。
- **PAT 只走内存**：MCP server 用进程内 SDK server（既有 `extra_mcp_servers` 机制）在 Python 侧持有 PAT 发 HTTP，**不生成任何含 PAT 的 workspace 文件**；转调层错误信息过 `redact_secrets_in_text` 再返回给 agent。复用 v0.2.0 既有 PAT 直传/脱敏链路，不新开传递通道。
- **`allowed_tools` merge 收口**：把"内建工具 + ask_user + repo_summary + knowledge MCP"的白名单合并逻辑收成单一构造函数 + 专项测试断言 Bash/Edit/Write 始终在列——这是一行注释救不了的坑，必须测试看住。
- **服务端把容器来源标记出来**：转调请求带 source 标识（如 header 或 PAT 绑定元数据），服务端指标按"容器 MCP"独立统计 QPS/错误率（新请求入口纳入观测是强制规范），才能在负载出问题时定位到是哪类调用方。
- **排除回归测试**：新增"容器视角"测试——用任务 PAT 调白名单每个工具查询已排除文件，断言不可见（复用 v0.5 六面 fail-closed 测试模式加第七面）。

**Warning signs:**
- 编码任务平均时长上升且 trace 里检索调用次数与耗时占比高（观测埋点先行才能看到，联动 Pitfall 8）。
- 服务端 `/api/mcp/tools/*` QPS 曲线在编码任务启动时出现尖峰。
- workspace 产物（diff/PR body/日志回传）中出现 `friday_pat_` 前缀串——立即视为事故。
- 挂载新 MCP 后 smoke 任务里 agent 报"Bash tool not allowed"——排他白名单翻车信号。

**Phase to address:**
AGENT 块"容器内置 MCP" phase：白名单/配额/PAT 内存化/allowed_tools 合并测试全部在此 phase；**观测埋点（QPS、per-task 调用数、RetrievalTrace）必须与功能同 phase 上线**，不能等 UNIFY 或收尾（没有埋点就无法判断风险 2 是否成真）。

---

### Pitfall 5: skills 双源漂移（容器内置 ≠ npm 包）

**What goes wrong:**
容器注入的 friday-code/friday-memory skills 与根 `skills/`（npm `@friday-ai-codes/skills`）各自演化：改了包没同步容器物料（或反之），两边 agent 拿到不同指引；更隐蔽的是**行为契约漂移**——KNOW 块改了 `search_learning_cases` 的检索行为/score 语义后，包内 friday-memory 的 SKILL.md 还在描述旧行为，Cursor 侧 agent 按过时文档调工具。CI 构建脚本若在生成"容器精简版"时做裁剪转换，转换逻辑本身成为第三个漂移源。

**Why it happens:**
"同源"在设计上一句话，在工程上是构建产物问题：容器物料在派发时写入 workspace，npm 包走独立发版节奏，仓库里没有任何机制强制两者一致——除非专门造一个。

**How to avoid:**
- **单一物理源**：容器物料直接从 `skills/skills/` 目录读取/打包（构建期拷贝也行，但拷贝必须由脚本完成、产物不进 git 手工维护区）。
- **一致性测试**（milestone 风险 4 已点名，落实为 CI 用例）：断言"容器注入物料的内容 hash == 包内对应文件 hash"（若有精简转换，则断言转换脚本输出与提交产物一致），漂移即红。
- **工具行为变更联动检查**：KNOW 块任何改动 `search_learning_cases`/新增知识工具的 PR，checklist 含"skills 文档是否需要同步"——可用简单 grep 测试（skill 文档中引用的工具名必须存在于 `TOOL_SCHEMA_SNAPSHOT`）半自动看住。

**Warning signs:**
- git log 里 `skills/skills/**` 与容器注入物料路径的提交不再成对出现。
- 容器内 agent 的工具调用参数与服务端 schema 不匹配的报错率上升（文档教的旧用法）。

**Phase to address:**
AGENT 块"容器内置 skills" phase 落一致性测试；KNOW 块"对外知识服务面"（skills 文档与新检索行为对齐）在检索切换 phase 的验收清单里带上。

---

### Pitfall 6: 退役"确定性缝"（planning_service）的测试与兼容断裂

**What goes wrong:**
`improve_coding_plan`/`analyze_repository` 从 `planning_service.py` 确定性实现收敛到 `delegate_process_runtime` 后：
1. **调用方契约断裂**——确定性版是同步、快速、输出形状稳定；编排版走 `process_runtime` session（异步状态机、可能要 poll/事件驱动、时延从秒级到分钟级）。外部调用方（Cursor 经 HTTP MCP、`@friday-ai-codes/skills` 文档描述的用法）若假设同步返回完整结果，切换后表现为"工具超时/挂起"。
2. **测试假死**——指向 `planning_service` 内部符号的既有测试在删除后大面积失败或（更糟）patch target 失效但测试静默通过。本仓库有前科：Phase 26 遗留 `test_batch_pr.py` 5 例 stale patch target 至今未修——**mock 路径退化是这个 codebase 已被证实的债务模式**。
3. **删空壳目录连带断 import**——`services/plan_orchestration/` 空壳清理时，若仍有文档/测试/迁移引用旧路径，删除即断。

**Why it happens:**
"收敛到统一编排"改变的不只是实现，而是**执行模型**（同步→会话式）；而退役旧代码时测试套件对 mock target 的引用不会被类型检查捕获。

**How to avoid:**
- **先定契约再动实现**：切换前明确 `improve_coding_plan` 对外语义——是保持同步语义（服务端内部等编排完成再返回，超时上限写进 schema 描述）还是改为返回 session id + 轮询。若改语义，`TOOL_SCHEMA_SNAPSHOT` 变更 + skills 文档同步（联动 Pitfall 5）+ 对外变更说明三件套一起走。
- **退役前先 grep 引用面**：`rg planning_service` 全仓（含 tests/docs/.planning 引用），列出清单逐一处置，作为该 phase 的第一个 task 而非最后。
- **mock target 专项清扫**：切换 PR 内跑全量后端测试且检查"被 patch 的路径仍真实存在"（可写一个轻量测试工具断言 patch target 可 import）；顺手把 Phase 26 那 5 例已知 stale 一并修掉或显式 skip 标注（MEDIUM：是否顺手修在 plan-phase 定）。
- **保留 analyze 产物的消费语义**："分析结果作为编排输入证据"要落到具体接线（analysis 进 recall/context），否则退役后 `analyze_repository` 变成产物无人消费的空转工具——工具面收口反而制造新孤岛。

**Warning signs:**
- 切换后 Cursor 侧 `improve_coding_plan` 调用超时率上升 / 用户反馈"工具卡住"。
- CI 全绿但 coverage 报告显示原 planning_service 测试文件覆盖归零（patch 假通过信号）。
- 删除 PR 的 diff 里没有 tests/ 目录改动——几乎必然有 stale 引用没清。

**Phase to address:**
UNIFY 块整体一个 phase，且**建议排在 KNOW/LOOP 之后**：process_runtime 承接 improve/analyze 前，编排召回扩容（KNOW）先就位，收敛后的工具质量才不降级。契约决策（同步 vs 会话式）是该 phase 的第一个决策点。

---

### Pitfall 7: 知识实体去重/关联错误（同一方案多来源重复入图）

**What goes wrong:**
本里程碑一次性新增 3+ 个 normalizer（learning_case、McpCodingPlan、McpRepositoryAnalysis、McpCodingExecutionTrace），而系统里"同一件事"天然多来源：Chat `create_coding_plan` 落 `chat.CodingPlan`（已入图，source_kind=`coding_plan`）、MCP 同名工具落 `McpCodingPlan`、执行时 bridge 还会**拷贝** plan 跨表（`mcp_tools/execution_service.py`）。若 McpCodingPlan normalizer 简单以自身 UUID 为 source_id 新建 TECH_PLAN 实体，同一份方案在图里出现两个节点：检索时同一方案占两个坑挤掉其他结果、图扩散沿错误节点走、"plan→execution→PR"关联边挂在其中一个节点上而检索命中另一个——验收面第 2 条（trace 带关联边）直接不成立。锚实体同样有此坑：work_item 锚必须复用 `feishu_work_item` 的三元组 natural key（`mcp_plan.py` 已示范），新 normalizer 若自造锚格式，边就挂到孤儿节点上。

**Why it happens:**
`generate_entity_id` 的 natural key 规则表（`knowledge/models.py` docstring）是 locked decision——**id 拼接格式一旦漂移需要全量数据迁移而非改函数**。多个 normalizer 并行开发时，每个作者局部看都"合理地"用了自己模型的 UUID，去重问题只在图整体视角才暴露。

**How to avoid:**
- **入图前先扩 natural key 规则表**：该 phase 的第一个产出是更新 `generate_entity_id` docstring 规则表——新增 source_kind 各自的 source_id 构成、以及"bridge 拷贝场景下 Chat plan 与 MCP plan 是同一实体还是关联实体"的显式决策。推荐：**不同表就是不同实体 + `supersedes`/`REFERENCES` 边显式关联**（合表已 Out of Scope，硬去重到同一 entity id 会踩 bridge 拷贝的时序坑），但检索层需按关联簇去重（同簇只出最优一条，MEDIUM：具体去重层次在 plan-phase 定）。
- **锚实体只用既有规则**：所有新 normalizer 的 work_item / repository 锚一律照抄 `mcp_plan.py` 的构造方式，code review checklist 明确"禁止自造锚 source_id 格式"。
- **幂等断言测试**：每个新 normalizer 带"重复摄取同一对象 → 实体数不变、版本翻转正确"的测试（既有摄取管线的 upsert 幂等锚正是 uuid5 稳定 PK，测试模式现成）。
- **图完整性抽查**：phase 验收含一条端到端断言——建 MCP plan → 执行 → PR 后，从 plan 实体沿边可达 execution 与 work_item（即验收面第 2 条落成自动化测试而非人工看）。

**Warning signs:**
- `search_delivery_knowledge` 返回结果里出现 title 几乎相同、source_kind 不同的成对条目。
- 图里出现零边的 TECH_PLAN/WORK_ITEM 节点数增长（锚拼错的直接产物）。
- normalizer PR 里 source_id 构造是 f-string 现拼而非引用规则表注释。

**Phase to address:**
KNOW 块"MCP 产物入图" phase：natural key 规则表扩表 + 关联决策是该 phase 的**前置设计 task**；learning_case normalizer（Pitfall 1 的 phase）也依赖同一决策，两者若拆 phase，规则表决策放在先执行的那个。

---

### Pitfall 8: 观测规范欠债（call_source / RetrievalTrace / 新入口漏埋）

**What goes wrong:**
本里程碑几乎每一块都触发强制观测规范的"新增"条款：新 LLM 调用点（learning case 提炼、可选 review）、新召回路径（learning case 向量检索、容器 MCP 七个检索工具、编排召回扩 document/learning_case）、新请求入口（容器 MCP 转调）。漏埋的后果不是"少个日志"：**风险 2（容器时延/负载）和风险 1（召回回归）的判定手段就是这些埋点**——漏埋等于蒙眼上线；且 `call_source` 枚举未登记 LOGGING-SPEC §4.1 会让 `ModelUsageRecord` 聚合出现"unknown 来源"黑洞，成本失控（Pitfall 2）不可归因。历史规律：横切规范在功能 phase 里最常被"先跑通、观测后补"，而后补的观测在 brownfield 里往往永远停在 backlog。

**Why it happens:**
观测是每个 phase 的"第 11 项任务"，单个 phase 里砍掉它对该 phase 验收无影响——影响的是下一个 phase 和线上排障，激励错位。

**How to avoid:**
- **把规范 checklist 摊到 phase 验收标准里**，而不是笼统一句"遵守观测规范"。具体分配：
  - KNOW 检索切换：`search_learning_cases` 新路径写 `RetrievalTrace`（MCP 链 + Chat 链两条都要，规范原文点名）+ 召回条数/耗时/score 上报；
  - LOOP 沉淀：新 `call_source`（提炼、review 各一）先登记 §4.1 再写调用代码；回写/沉淀事件带 `initiated_by_user_id`（回调触发的用工作流触发者，无则 `system`）+ `category`/`component`；
  - AGENT 容器 MCP：转调入口纳入 QPS/错误率/时长统计；容器侧检索经服务端自然产 RetrievalTrace，需验证 run/task 关联键贯穿（能从一次编码任务查到它的全部召回）；
  - 全部：高频检索循环用 `sampling` 分类，禁 INFO 刷屏。
- **验收面第 5 条已内嵌观测**（"日志可见工具调用 + RetrievalTrace"）——roadmapper 把同样写法复制到其余各条验收，让漏埋直接等于验收不过。
- **利用现成设施**：v0.14.0 平台设施（contextvars 用户上下文、RequestMetric、GaugeSample）已就位，新代码只需按约定接线，没有"先建基建"的借口。

**Warning signs:**
- phase PLAN 的 task 列表里没有独立的观测 task / 验收标准不含埋点断言。
- `ModelUsageRecord` 出现新的高量 unknown/复用旧 call_source 的记录。
- 上线容器 MCP 后想看"每任务检索次数"时发现查不出来——已经晚了。

**Phase to address:**
不设独立观测 phase（会变成永远排最后的 phase）；按上面分配**内嵌进各功能 phase 的验收标准**。roadmapper 在写各 phase success criteria 时逐条带上。

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| 检索切换不做 golden set，靠人工点几条查询验证 | 省 1–2 天 | 召回回归静默上线，用户以"知识库不好用"弃用整个飞轮 | Never（milestone 风险 1 已点名，对照测试是验收门） |
| 自动沉淀先"全量入库"，质量门后补 | 快速看到"闭环跑通" | 垃圾 case 入库后需人工清洗 + 向量下线，成本远超预防（mem0 案例 97.8% 垃圾率） | Never（至少幂等键 + status 门槛与功能同 PR） |
| 容器 skills 物料手工拷贝一份"先用着" | 当天可演示 | 双源漂移（Pitfall 5），后续每次改 skills 都要人肉记得同步 | 仅限本地 spike，合入主干前必须换成脚本 + 一致性测试 |
| 退役 planning_service 时只删代码不清 tests/docs 引用 | PR 小 | stale patch target 假通过（本仓库 Phase 26 前科），未来重构不敢动 | Never |
| 容器 MCP 先不做配额/超时，"观察一下再说" | 少写一层控制逻辑 | agent 重试风暴打满服务端时无刹车，只能全量下线功能 | 仅当同 phase 已有 QPS 告警阈值且有系统级开关可秒关 |
| 回写默认值不写升级说明，"反正 fail-soft 不会崩" | 省文档 | 存量用户被静默行为变更惊到，信任损失 > 崩溃 | Never（Compatibility 约束明文要求升级行为不回退） |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| claude-agent-sdk `allowed_tools` | 挂新 MCP server 时只列远程工具名 → 排他白名单禁掉 Bash/Edit，编码全废 | 收口单一白名单构造函数，永远合并 `_BUILTIN_CODING_TOOLS`；专项测试断言内建工具在列 |
| `/api/mcp/tools/*` 容器转调 | 把上游错误响应体原样返回给 agent（可能含敏感串），或 PAT 进 workspace 文件 | 错误过 `redact_secrets_in_text`；PAT 仅进程内存持有（复用 v0.2.0 直传链路），不落任何文件 |
| `subagent/api/callbacks.py` 沉淀钩子 | 直接在回调里触发提炼——回调重入自驱会重复提炼 | 以 TaskResult UUID 为幂等键，先查已产 case 再提炼 |
| `knowledge/sources/` 新 normalizer | 自造 source_id 格式 / 自拼 work_item 锚 | 先扩 `generate_entity_id` docstring 规则表，锚照抄 `mcp_plan.py` |
| 飞书工作项回写 | 无守门直接写评论；失败重试轰炸飞书 API | work_item 存在性 + 凭证校验，不满足记 `writeback_skipped` 跳过；不自动重试 |
| `TOOL_SCHEMA_SNAPSHOT` | 改了工具行为/score 语义但 schema 描述没动，快照测试绿着通过 | schema 描述随行为更新；补 `report_project_state`/`reverse_lookup_requirements` 时顺手核对全部 30 工具描述与现实一致 |
| `recall_adapter` 扩 kinds | 直接加 document/learning_case 无开关，编排召回 token 预算被撑爆 | kinds 可配置（默认开）+ 每 kind 限额，召回总量守 token 预算 |
| Qdrant | 向量检索路径无降级，Qdrant 故障时 learning case 检索 500 | fail-soft 空结果 + 结构化 failed 事件（token 版原本不依赖 Qdrant，这是新引入的故障面） |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| 容器 agent 高频调检索（机器节奏 vs 人类节奏） | 编码任务时长上升、服务端 MCP 入口 QPS 尖峰 | per-task 调用配额 + 单次超时 + 白名单最小化；QPS 独立统计告警 | 约 5–10 个并发编码容器同时活跃时（每容器几十次检索 × 向量查询） |
| 编排召回扩 kinds 后候选集膨胀 | 方案生成变慢、LLM 上下文超预算被截断 | 每 kind 限额 + 时间衰减排序保留既有行为；扩容前后对比方案生成耗时 | document 类实体量大的部署（v0.15/0.16 沉淀多的老用户） |
| 自动沉淀 LLM 调用随重试放大 | token 成本曲线与任务量脱钩 | 幂等键 + 失败不重试（best-effort 语义）+ 按 call_source 日限额告警 | 编码失败率高的时期（失败任务反复回调） |
| learning case backfill 一次性全量摄取 | 摄取队列积压堵住正常 ingestion | backfill 走低优先级批处理（复用 durable queue 多逻辑队列），分批 + 可断点续跑 | 存量 case 数百条以上的部署 |
| 向量检索替代 token 打分后每次查询都打 embedding | 单次检索延迟从 ~10ms（DB 查询）升到百 ms 级 | 查询 embedding 用既有 fastembed 本地路径；hint 过滤前置缩小候选集 | 对时延敏感的调用点（`create_feishu_technical_plan` 自动召回在交互路径上） |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| PAT 出现在容器 workspace 文件 / agent 可读 env dump | agent 把 PAT 读进上下文 → 写进 diff/PR/日志，凭证公开泄漏 | MCP server 进程内持有 PAT；不生成 `.mcp.json` 类文件；错误信息过脱敏；CI 加"产物中无 `friday_pat_` 前缀"扫描（MEDIUM：扫描点位 plan-phase 定） |
| 容器白名单混入非只读工具或未过排除的路径 | 排除文件经容器 agent 泄漏（绕过 v0.5 六面 fail-closed） | 白名单锁定只读检索子集；加"容器视角排除回归测试"（第七面） |
| LLM 提炼的 learning case 未脱敏入库 | TaskResult/diff 中的密钥、内网地址随 case 入向量库并可被全员检索 | 提炼输出入库前过 `redact_secrets_in_text`（对齐"入库留痕走脱敏"规范）；case 检索受既有权限过滤 |
| 回写内容把上游异常文本原样写进飞书评论 | 异常里的连接串/token 泄漏到飞书侧 | 回写正文只用结构化结果字段；异常路径只记内部日志（脱敏后） |
| 自动沉淀/回写不带 initiated_by_user_id | 审计无法回答"谁触发的"，违反强制规范 | 回调链路透传工作流/会话触发者；无触发用户标 `system` |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| 回写 + IM 通知双发同一结果 | 用户觉得吵，关掉其一时可能连功能一起关 | 语义分工写清（评论=业务留痕，卡片=即时通知），文案区分 |
| 自动 case 与人工 case 检索时不可区分 | 用户对召回结果信任下降（"这条是机器瞎写的吗"） | payload 带来源标记（auto/manual），排序时人工确认的 case 可加权 |
| `improve_coding_plan` 切编排后从秒级变分钟级且无进度反馈 | Cursor 用户以为工具挂了，反复重试 | 若改会话式，返回 session 引用 + skills 文档教轮询；若保同步，schema 描述写明预期时长 |
| 容器配额用尽后工具静默空结果 | agent 反复重试烧时间，任务变慢且难解释 | 配额用尽返回明确文案（"检索配额已用尽，请基于已有上下文继续"），agent 可理解并停手 |

## "Looks Done But Isn't" Checklist

- [ ] **检索切换**：向量路径通了，但常缺——存量 case backfill、hint 参数在新层的等价实现、score 语义定版、Qdrant 故障降级。验证：golden set 对照测试 + 断开 Qdrant 跑一次。
- [ ] **自动沉淀**：能产 case，但常缺——回调重入幂等、REJECT 路径、call_source 登记、脱敏入库。验证：同一 TaskResult 回调两次只产一条 case；失败任务不产正向 case。
- [ ] **公共回写**：三链路都调了 service，但常缺——存量工作流（config 无该键）的 fallback 用例、无绑定 work_item 时的跳过路径、升级说明。验证：老工作流定义 JSON 直接跑，行为与升级前一致。
- [ ] **容器 MCP**：工具能调通，但常缺——`allowed_tools` 合并测试（Bash/Edit 仍在）、per-task 配额、容器视角排除测试、QPS 独立统计。验证：smoke 编码任务能同时用 Bash 和检索工具；排除文件查不到。
- [ ] **skills 同源**：容器里能看到 skills，但常缺——hash 一致性 CI 测试、skills 文档与新检索行为对齐。验证：改一个包内 skill 文件不跑同步脚本，CI 应红。
- [ ] **工具面收口**：improve/analyze 走了 process_runtime，但常缺——stale mock target 清扫、`plan_orchestration/` 引用清理、analyze 产物的实际消费接线。验证：`rg planning_service` 零结果；coverage 无归零文件。
- [ ] **MCP 产物入图**：normalizer 写了，但常缺——natural key 规则表更新、重复摄取幂等测试、plan→execution→PR 边的端到端可达性断言。验证：图上从 plan 实体沿边走到 PR。
- [ ] **快照补全**：`report_project_state` 进了 snapshot，但常缺——快照测试断言"注册工具 == snapshot 键集合"（防未来再漏），而非只加两条。

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| 召回回归上线（P1） | MEDIUM | 若留了 token fallback 开关：切回旧路径 → 修 golden set 红项 → 再切。没留开关：热修 hybrid 补召回，同时补 backfill 缺口 |
| 知识库被垃圾 case 污染（P2） | HIGH | 关自动沉淀系统开关止血 → 按 call_source/时间窗筛出自动 case → 批量下线向量 + 实体失效（bi-temporal `invalid_at`，勿物理删）→ 补质量门后重开。污染越久清洗越贵，这是"预防远优于恢复"的头号项 |
| 回写惊扰存量用户（P3） | LOW | 系统级关回写 → 发升级说明与默认值修正 → 以"存量 fallback 关、新建默认开"重上 |
| PAT 泄漏进产物（P4） | HIGH | 立即吊销该 PAT（graceful 机制已有）→ 排查泄漏通道（workspace 文件/错误透传）→ 审计该 PAT 时间窗内调用记录 → 修通道后换新 token 重跑 |
| skills 漂移被发现（P5） | LOW | 跑同步脚本对齐 → 补一致性测试防复发 |
| 收口后契约断裂（P6） | MEDIUM | 若外部调用方超时：临时恢复确定性实现为 fallback 分支 → 定契约（同步/会话式）→ 按新契约重切并同步 skills 文档 |
| 实体重复入图（P7） | MEDIUM | 找出重复簇（同 title 异 source_kind）→ 补关联边或按规则表迁移 source_id（uuid5 漂移需数据迁移，勿直接改函数）→ 检索层加簇去重 |
| 观测漏埋（P8） | LOW–MEDIUM | 补埋点本身便宜；贵在漏埋期间的问题不可归因——尽早在 phase 验收中拦住 |

## Pitfall-to-Phase Mapping

> Phase 编号待 roadmap 落定，此处按 v0.17.0 四大块 + 建议顺序映射。

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| P1 检索切换回归/契约漂移 | KNOW·learning case 入图 + 检索切换（normalizer/backfill/读切换同 phase） | golden set 对照测试通过；`TOOL_SCHEMA_SNAPSHOT` diff 含 score 语义；断 Qdrant 不 500 |
| P7 实体去重/关联错误 | KNOW·MCP 产物入图（natural key 规则表扩表为前置 task，若与 P1 拆 phase 则规则表决策放先行者） | 重复摄取幂等测试；plan→execution→PR 边可达性端到端断言 |
| P2 沉淀噪音/成本 | LOOP·自动经验沉淀（幂等键 + 准入门 + call_source 与功能同 phase） | 回调重入只产一条 case；失败任务不产正向 case；ModelUsageRecord 可按新 call_source 聚合 |
| P3 回写默认值 | LOOP·公共回写 service（fallback 语义为设计输入） | 存量工作流定义（config 无新键）行为零变化用例；升级说明产出 |
| P4 容器 MCP 四险 | AGENT·容器内置 MCP（白名单/配额/PAT 内存化/allowed_tools 测试/观测埋点同 phase） | allowed_tools 合并测试；容器视角排除测试；MCP 入口 QPS 可查；产物无 PAT 前缀 |
| P5 skills 双源漂移 | AGENT·容器内置 skills（一致性测试）；KNOW·对外服务面（文档对齐） | hash 一致性 CI 红绿可证；skill 引用工具名 ∈ snapshot |
| P6 收口断裂 | UNIFY（建议排 KNOW/LOOP 之后；契约决策为首个 task） | `rg planning_service` 零引用；patch target 可 import 断言；Cursor 侧调用不超时 |
| P8 观测欠债 | 内嵌各功能 phase 验收（不设独立观测 phase） | 各 phase success criteria 含对应埋点断言（RetrievalTrace/call_source/QPS） |

**对 phase 排序的两点建议：**
1. **KNOW 的 natural key 规则表决策先于一切入图工作**（P1/P7 共享前置）；LOOP 的沉淀依赖 KNOW 的 learning case 入图路径（沉淀产物要能被统一检索到），故 KNOW 检索切换 → LOOP 沉淀存在软依赖。
2. **AGENT 容器 MCP 依赖 KNOW 的检索工具行为定版**（容器白名单调的就是这些工具），放 KNOW 之后可避免容器侧对着会变的契约集成两次；UNIFY 收口放最后。

## Sources

- 仓库代码实证（HIGH）：`server/mcp_tools/learning_case_service.py`（token 打分现实现与 score 语义）、`server/knowledge/models.py` `generate_entity_id` docstring（natural key locked 规则表与漂移警告）、`server/knowledge/sources/mcp_plan.py`（锚实体构造范式）、`task/core/executor.py`（`allowed_tools` 排他白名单注释与 ask_user 前科）、`server/tests/mcp_tools/test_schema_snapshot.py`（快照测试存在性）、`server/mcp_tools/work_item_execution_service.py`（write_back 现状）
- `.planning/MILESTONE-CONTEXT.md`（风险 1–4 原始识别、复用坐标表、Out of Scope 边界）；`.planning/PROJECT.md`（Phase 26 stale patch target 前科、v0.8 callback 重入自驱设计、PAT-02 约束、Compatibility 约束）
- `.cursor/rules/observability-logging.mdc` + LOGGING-SPEC 引用（call_source/RetrievalTrace/新入口强制条款）
- 检索切换回归防护（MEDIUM，多源一致）：llmbestpractices.com Embeddings Evaluation（golden set 100–500 查询 + recall@k/MRR CI 门）、backendbytes.com Production RAG Pipelines（golden set day one + hybrid 补精确标识符召回）、qaskills.sh RAG Regression Testing（冻结数据集 + 阈值门 + 版本化）
- 自动沉淀污染（HIGH，一手案例 + 论文）：mem0ai/mem0 issue #4573（10,134 条审计 97.8% 垃圾：反馈环放大、无准入门、需 REJECT 路径）、arXiv 2603.04549 A-MAC（五维准入打分：utility/confidence/novelty/recency/type prior）、arXiv 2604.07877 MemReader（被动提取无价值判断 → 低价值信息重复入库污染）、hidekazu-konishi.com Agent Memory Design Guide（异步提取 + 写门槛不在 hot loop）

---
*Pitfalls research for: Friday AI v0.17.0 统一知识库与全链路联动（brownfield 集成）*
*Researched: 2026-07-15*
