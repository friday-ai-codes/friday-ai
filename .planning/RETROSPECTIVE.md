# Retrospective

## Milestone: v0.1.0 — 首启初始化向导

**Shipped:** 2026-06-09
**Phases:** 5 | **Plans:** 9

### What Was Built
用「首次访问引导用户自设账号」替代启动期自动建管理员：首启门禁（fail-closed 防重入）、管理员自设+自动登录、Anthropic 兼容供应商一键预设（Fernet 加密 + 健康校验 + 绑 Claude Code）、安全密钥校验、可选飞书/RAG 步骤、entrypoint 去自动建号且向后兼容。

### What Worked
- 严格复用既有 `ProviderConfigService` / `ProviderCredential` / `SystemSetting` / Fernet 加密路径，未重写既有系统，集成风险低。
- fail-closed 安全门禁（仅无 superuser 可用）从 Phase 1 就锁定为独立权限类，后续阶段直接复用。
- 一键模型预设以「anthropic 类型 + base_url 覆盖」统一接入第三方模型，前端常量化，扩展简单。

### What Was Inefficient
- Phase 01/02 的人工验收（UAT）签字未闭环，里程碑关闭时作为 deferred 项带走。
- SUMMARY.md 的 one-liner 格式与 SDK summary-extract 不匹配，归档成果摘要需手动补全。

### Patterns Established
- 敏感配置一律走加密落库（`is_encrypted=True` + `SettingKeys.*`），不走通用明文 PUT /settings/。
- 薄编排端点（IsSuperUser）承担「校验→加密→落库→绑定」的组合写操作。

### Key Lessons
- 向导类需求要尽早把「安全门禁 + 向后兼容」作为一等公民，避免收尾阶段返工。
- 人工验收门应在每个 Phase 完成时即时签字，避免堆积到里程碑关闭。

## Milestone: v0.8.0 — 多仓串行编码 → 融合 PR

**Shipped:** 2026-06-17
**Phases:** 5 (43–47) | **Plans:** 16 | **Tasks:** 38

### What Was Built
把 v0.7 产的 `MergedPlan.execution_plan` + 跨仓依赖 DAG 真正落成多仓代码：PF-06 workflow 编码 dispatch env 对齐 chat 基线（私有仓 clone + 正确目标分支）+ 入口无关 resume 续驱 helper（消化 v0.7 audit D-2）；`RepoCodingTask` 操作态模型 + `execution_plan[].dependencies` graphlib 拓扑分层成 wave + `aadvance_coding_waves` 推进（wave N done → N+1，失败隔离不死锁）+ `AICodingNode` 按 wave 分批 dispatch 经 callback 重入自驱；上游产物提取（OpenAPI/契约/diff）注入下游 wave；各仓 MR 锚定各仓 `default_branch` + 跨仓 PR cross-ref + 追溯 `TechnicalPlan`/`WorkItem`；编码遇阻 `ask_user` 抛 question 给人（容器心跳保活）+ resume 续跑，非全自动 replan。

### What Worked
- **「不造两套」贯穿全程**：续驱 helper（节点/工具/回调三处同源）、wave 推进、单一写入入口（INV-6）全部复用底座，跨阶段集成审计直接判 integration_ok。
- **复用既有 `waiting_event` + callback resume 扩成多 wave**，未另造调度器（`while True`→有界 `for`，无 sleep/timer/apscheduler），liveness 风险可控。
- **liveness 命门前置识别**：传递闭包阻断必在任何 early-return 前完成（T-44-DEADLOCK），从设计阶段就锁死避免死锁。
- **空依赖退化全并行的零回归命门**贯穿 wave 分层/调度/产物注入，保证存量单仓/同 default 多仓字节级等价。
- **mock IO 边界的单测/集成测试**充分覆盖拓扑分层、wave gating、失败隔离、幂等、产物传递、PR cross-ref、HITL 全链，本地无 runner/Docker 也能验收到 accepted level。

### What Was Inefficient
- **STATE.md 在收官前未及时回写**：Phase 47 实际已完成验证，但 STATE.md 仍停在「Phase 47 未开始 / 80%」，autonomous 收尾时需先辨明磁盘真实状态（roadmap.analyze 权威）才能继续。
- **REQUIREMENTS.md traceability 表滞后**：PF-06/WAVE-01/WAVE-02 已交付但表中仍标 Pending/未勾选，靠 3 源交叉（VERIFICATION + SUMMARY + traceability）才确认满足。
- **Phase 45 SUMMARY 缺 `requirements-completed` frontmatter 字段**，ARTIFACT-01/02 覆盖只能从 VERIFICATION 需求表确认。
- **Phase 26 遗留 `test_batch_pr.py` 5 例 stale patch target 失败**跨里程碑悬挂未清。

### Patterns Established
- **wave 分层用 task 级 DAG（`execution_plan[].dependencies`）+ 仓 wave 取 task 层级 max**，环检测复用 `plan_validator.validate_plan` 不重写。
- **wave 失败部分回滚语义**：done 出 MR、failed/blocked 如实标注 `upstream_failed`、不自动回滚（v0.8 非目标）。
- **per-repo MR `target_branch` fallback 链** `default_branch or base_branch or "main"`，保单仓/同 default 多仓零回归。
- **跨仓 PR cross-ref `successful_mrs ≥2` 守门 + 全程 fail-soft**（绝不上抛回灌 5xx），追溯链 `plan_version → TechnicalPlan → WorkItem` 逐跳 afirst 链断返空。
- **编码遇阻 HITL：容器 `ask_user` + 心跳保活 RUNNING + `answer.json` 共享卷回灌**，复用既有 question 协议，no-replan 守护测试坐实。

### Key Lessons
- **收官前先以 roadmap.analyze（磁盘权威）核对真实状态**，STATE.md / REQUIREMENTS.md 可能滞后；状态文件回写应作为 phase 收尾一等公民。
- **「不造两套」从设计阶段就锁死单源 helper / 单一写入入口**，是跨阶段集成零缝隙的根本原因，值得在后续里程碑继续坚持。
- **liveness / 死锁风险在并发 wave 调度里要前置到设计**（阻断顺序、early-return 时机），不能留到测试才发现。
- **真实 runner+Docker 容器 E2E 是结构性 deferred**（本地无法闭环），mock IO 边界覆盖应明确标注为 accepted verification level，避免反复回炉。

### Cost Observations
- Sessions: 跨多会话执行（v0.8.0 收官于 autonomous lifecycle 单会话）。
- Notable: phase 内多以 mock IO 边界测试收敛，单 plan 多在 5–25min 量级（见 STATE.md Performance Metrics）。

## Milestone: v0.16.3 — 外部依赖接入知识体系（可检索 + 知识树 + 关联图谱）

**Shipped:** 2026-07-01
**Phases:** 4（96–99） | **Plans:** 15 | **Requirements:** 12/12（KDEP-01~12）| **Audit:** tech_debt

### What Was Built
把项目外部依赖（`Artifact`）完整接入「知识」体系：全类型工件登记可发现（非 ragable 元数据-only 实体+边）+ 搜索标类型可跳查看 + 知识总览「交付文档」区块（P96）；`/knowledge` 并行「交付文档」树 + 树内搜索/查看 + 后端树 API（P97）；RepoRouterV2 路由工件正文落 `RELATES_TO` 边 + verified `RepoAssociation` 单向派生 + 双向关联查询（P98）；星图纳入 artifact/capability 节点边 + 实体详情双向关联展示 + 作战室↔知识闭环（P99）。

### What Worked
- **research 基线先行**：里程碑立项时已产出详尽的现状探查 + 架构决策锁定（复用 Artifact / delivery_knowledge / RepoRouterV2 / RepoAssociation / graph_store，不新建真相源），使 smart-discuss 几乎无灰区、plan/execute 直接落到复用点，返工极少。
- **严格复用 + 单一写入入口（INV-6）**：四阶段层层复用上游产物（P97 镜像 P96 的 access_scope/截断范式、P99 只读消费 P98 查询服务），跨阶段 integration_ok 一次通过。
- **全自动 discuss→plan→execute→verify→review→fix 流水线**：每阶段 review 都抓到真实"好用/优雅"缺陷（dep_type 预筛未生效、空态连坐隐藏、陈旧路由边累积、type_key 生显）并即时修复，质量门控发挥作用。

### What Was Inefficient
- **规划文档与工具链契约漂移**：里程碑 Phase 详情初始只放在 `milestones/v0.16.3-ROADMAP.md`，顶层 ROADMAP 缺 `### Phase N:` 明细块，导致 `roadmap.get-phase` 找不到阶段，须先回填明细块工具链才识别。教训：立项即在顶层 ROADMAP 内联当前里程碑 Phase 明细。
- **共享常量事后抽取**：徽标/载体图标常量在 P96/P97/P99 三处复制，到集成检查才抽 `artifactDisplay.ts`。教训：跨阶段复用的展示常量应在首个阶段就建共享模块。

### Patterns Established
- 非 ragable 工件「元数据-only 知识实体登记」（建 document 实体 + REFERENCES 边、零向量、幂等）——为无正文工件提供可发现性的通用范式。
- 关联边 metadata 承载关键词/能力（不建独立实体表）+ 唯一真相源单向派生 + 重摄取陈旧边收敛。

### Key Lessons
- LLM 非确定性路由必须配"陈旧边失效收敛"，否则关联随重摄取累积污染查询——已在 P98 补齐并加收敛测试。
- 自动化验证 human_needed（真机/浏览器）是结构性 deferred，代码层 must-haves + 自动化测试全绿即可 accept tech_debt 归档，勿反复回炉。

### Cost Observations
- Sessions: 单会话全自动执行（$gsd-autonomous），中途 2 次用户中断后 `继续` 无缝续跑（阶段产物已提交，幂等续接）。
- Notable: 每阶段 planner→executor→verifier→reviewer→fixer 子代理链隔离上下文，主编排上下文保持精简。

## Milestone: v0.19.0 — 技术方案可信度（编排不塌陷 + 路由可解释 + 编排产出直连执行流 + 过程可见）

**Completed:** 2026-08-02（未打 tag）
**Phases:** 5（105/106/107/109/110，原 108 移交 v0.20.0） | **Plans:** 39 | **Tasks:** 101 | **Requirements:** 17 满足 / 2 部分 / 0 未达（共 19）| **Audit:** tech_debt
**Timeline:** 2026-07-29 → 2026-08-02（5 天，303 commits，275 files，+66265/−1309）

### What Was Built
把「一次生产事故」变成一条可回归的工程链路：置信度由分数 margin 确定性推导、LLM 只降不升（P105）；三信号扩六信号的可拆解打分函数，消除大单体尺寸偏置、元数据真正入分、权重外置不发版可调（P106）；候选分「本项目 / 全局」两组呈现并带跨组标注与降级横幅，Stage 1 有界重试，澄清超时有真实续驱的出口（P107）；编排产出经幂等投影直连执行流，`create_coding_plan` 在 schema 层被砍掉创作半边（P109）；编排全过程经既有事件表 fan-out 上 SSE，阶段时间线与调研容器日志对用户可见（P110）。收尾补一次跨相位的 ROUTE 缺口闭环。

### What Worked
- **反向对照（改坏 → 跑测 → 还原 → 确认工作区干净）成了本里程碑最有价值的工具。** 审计与闭环期共跑 7 组，每一组都产出了报告里写不出来的结论：把 `derive_confidence` 短路为恒 low，degraded 套件 14 红**而 golden 门禁全绿**——这直接暴露了 ROUTE-08 的门禁对本里程碑立项时那个具体故障是盲的；摘掉候选面的挂载点 11 条全灭——这证明新用例守的确实是「用户能看到」。没有反向对照，这两条都只会是「测试通过」。
- **「不删 `create_coding_plan`，改在 schema 层收窄入参」这个取舍。** 实证它是 SPA 唯一的编码执行入口、MCP 执行链还依赖它做桥接，删除会断两条链；收窄入参则精准砍掉创作半边，且用键集合枚举式相等断言（`set(properties) == 白名单`）守住——换名重新加回也会红。
- **research 先行定版排序算法。** 融合方式（归一化线性加权和，否决 LTR）、多命中聚合（MaxP + pivoted 对数饱和，加性不乘性）、幂等策略（系统层保证，不指望 temperature=0）在动手前就有数值验算，Phase 106 的公式一次定版，`golden` 门禁全程未因公式改动翻车。

### What Was Inefficient
- **四条需求被建在一个已下线的组件里，整整五个相位无人发现。** `RoutingDecisionPanel` 自 2026-05-29（本里程碑立项**之前**）起零挂载点且有锁测试断言它不渲染。105-06 往里加分数分解、106-05 往里加信号中文标签、107-09 往里加分组与降级横幅——三个相位、三个不同的执行者，全部通过了 VERIFICATION 与 UI-REVIEW。唯一能发现它的那条人工项（浏览器视觉核对）恰恰是被延后的那条，而它本身又因面板下线而「无从执行」——一个闭合的盲区。**返工成本：一次跨 105/107/110 三相的缺口闭环 + 删 612 行组件与 39 条单测。**
- **「随下个相位补齐」的递延承诺落空。** 106 的 MN-05（权重设置组件 484 行零单测）与 MN-07（golden 数值来源标注）都写着「Phase 107 一并处理」，107 完成后两项原样未动。递延时写「归谁」比写「什么时候」更容易兑现——归属不明的递延等于挂账，应当一开始就显式挂账。
- **台账漂移到里程碑审计才被发现。** ROADMAP 进度表 109/110 两行在两相位 8/8、7/7 完成后仍写 `0/TBD | Not started`；REQUIREMENTS 的 Traceability 状态列口径三分（Pending / Complete / 未勾选）。106-VERIFICATION 早就指出过同类问题（W-2），修了 106 行没修其余。

### Patterns Established
- **UI 需求的取证从挂载宿主出发，不单测叶子组件。** `routingCandidateSurface.spec.ts` 一条都不 mount `RoutingCandidateList`，全部从 `ChatMessageBubble` 出发、走用户真实的两次点击（展开「分析过程」→ 展开「仓库分级路由」）才开始断言，点不开即失败。这是对「组件存在 + 结构断言通过 = 用户能看到」这个错误等式的直接反制。建议推广为全仓 UI 取证纪律。
- **「消费方在线、生产方离线」是一类需要专门检查的接缝。** 本里程碑出现了两个镜像实例：`RoutingDecisionPanel`（生产方在线、消费方缺席）与 `nr_snapshot`（消费方在线、生产方是一条从未在生产执行的手动命令）。两者的自动化测试都全绿，因为测试里两端都在。集成检查必须显式问「生产方在生产环境真的跑过吗」。
- **降级/错误这类事实由后端算好，前端绝不推断。** 前端按 `router_version` 或候选内容猜降级，会在 payload 形状变化时静默失真；缺键就补键（加性、无迁移）。

### Key Lessons
- **「测试全绿」与「用户拿到」之间隔着一层没人负责的接线**，而且这层接线的两种失效形态（渲染者无宿主 / 数据生产方没跑）都不会让任何一条自动化用例变红。里程碑审计的价值恰在于它是唯一从「用户能否做到」倒推的环节——本次它抓到的是一个跨越五个相位、早于立项就存在的结构性缺口。
- **回归门禁只能防住它被设计来防的那类退化。** golden set 的三条规则（Recall@5 / Top-1 / 误自动选中率）防排序退化很有效，但对「置信度整体塌陷」完全免疫——而后者正是本里程碑立项的那个故障。**门禁应当为已发生过的故障各补一条断言**，成本极低。
- **人工验收零执行会让「代码层成立」成为多数需求的天花板。** 27 项 UAT 全部 pending，四个目标分句里三句的端到端证据完全缺席，这是判 `tech_debt` 而非 `passed` 的直接原因。真实飞书 / 真实容器 / 浏览器这三类环境的缺席是结构性的，但**不应因此把「代码层成立」重新表述为「已交付」**。
- **归档时的诚实收口比数字好看重要。** 本次把 `gaps_found` 改判 `tech_debt` 是回源码独立复核后的结论（含一组变异验证），同时如实订正了两处计数错误（满足数 16→17、人工验收 26→27）、保留 `integration: seams_found`、把 ROUTE-03 与 RELY-02 明确留在 PARTIAL。**改状态必须附证据与理由，不能静默翻数字。**

### Cost Observations
- Sessions: 跨多会话执行（相位链 discuss→plan→execute→verify→review），收尾的缺口闭环与归档各为独立会话。
- Notable: 5 天 303 commits，密度高于既往里程碑；返工集中在收尾的 ROUTE 缺口闭环一处，而该处的成因（人工视觉验收被延后）不是执行效率问题而是验证策略问题。

## Milestone: v0.20.0 — 技术方案蓝图（六段结构化蓝图 + 确认门与分仓方案 + 划线澄清收敛 + 全入口收编）

**Shipped:** 2026-08-02
**Phases:** 6（111–116） | **Plans:** 34 | **Requirements:** 34/35（GATE-01 PARTIAL）| **Audit:** tech_debt
**Timeline:** 2026-07-29 → 2026-08-02（4 天，384 commits / 92 feat）；代码面 268 files（+86,544 / −576）

### What Was Built

把技术方案从「单轮 LLM 产的一份 JSON」升级为项目级结构化蓝图：`blueprint/v1` 六段 jsonschema 强制 + 11 态生命周期 + `RepoCharter` 章程 + golden set（P111）；`spec_gate` 歧义门 + 三分量可拆解的双面路由 + 逐仓容器 fitness 调研 + `repo_confirmation` 硬确认门（P112）；`RepoPlan` 分仓方案 + 会话级 Context Bus（两档等待恢复 + 互等环检测）+ 融合装配与跨仓 API 对账（P113）；AI 对抗审查七类规则有界打回 + 澄清回灌与批注重锚定 + 人工 block 编辑的双向覆盖保护（P114）；`BlueprintViewer` 十段渲染 + 飞书式划线批注层 + 引用二级预览 + 知识库 tab + 人审终审（P115）；四入口的蓝图可执行路径与 per-entry 开关 + MCP 异步澄清协议 + 飞书导出与不可关闭的「未经确认」标注 + 知识图谱物化反查（P116）。

### What Worked

- **「让缺陷在结构上不可能」优于「让缺陷被测试逮住」**，本里程碑反复用到并且都奏效：`render_blueprint_markdown` 把「未经确认」标注做成必填 keyword-only + 闭合白名单 + 零布尔开关（唯一可机器验的形式是 `inspect.signature` 断言）；`blueprint_answer_action` 把作答通道收敛成唯一实现让 MCP 与 REST 继承同一批闸；`_aassert_project_scope` / `_aassert_gate_scope` 用 import 复用而非复制第四份。
- **并行开发的边界纪律事前定版、逐 plan 核算**：冻结既有 `technical_plan` 六文件 + `repo_router_v2.py` + `ConvergenceSessionEvent` 既有契约，蓝图流水线全走 `blueprint_*` 新文件。结果是 6 个相位跑完与 v0.19.0 **零文件交集**，合并只剩 `.planning/` 三文件的机械冲突。
- **变异验证（实跑一次真实变异让用例转红再恢复）成为常规动作**，不是写完测试就算数。多处「静默假通过」正是靠它逮住的：`useBlueprintLive` 缺 `watch(isLive)` 导致章节进度冻结、`arestore_human_blocks` 的重装保护链、finding 闸的顺序、`assume_more` 不等于跳过澄清。
- **相位间用 SUMMARY 做契约交接**（「开工前必读 §N 的三条最容易踩」），下游 plan 的返工显著少于依赖 PLAN 文本的做法。

### What Was Inefficient

- **需求验证范围的夹缝没人负责**：CLAR-03「人类可直接编辑蓝图内容」后端在 114 全量交付、UI 归 115，而 115 的需求清单不含 CLAR-03 ⇒ 六份 VERIFICATION **结构性地看不见**它，直到里程碑审计才发现「后端齐备而产品面不可达」，还得额外做一个 closure。更糟的是 115 留了一条**主动阻止**该入口出现的源码守卫，其注释同时写着「顺延 116」与「不该有这个能力」两种立场且未经调和。⇒ 跨相位交付的需求必须有一个相位显式 own 它的**用户可达性**。
- **守卫在环境缺失时静默 skip，等于从未运行**：`test_mcp_package_alignment` 与 `test_skills_snapshot_guard` 在 `mcp/`、`skills/` 子模块未 checkout 时 `pytest.skip` ⇒ 整个里程碑从未实跑过。归档前初始化子模块才第一次跑起来，当场暴露「mcp npm 包缺四个本里程碑新增工具」这个真实缺口。⇒ 空跑掩盖的从来不止一条。
- **顺延项的措辞会过期**：「113 若需…否则留到 115 定夺」这类指向具体相位的顺延写法，在两个相位都完成且都没做之后就变成无主条目（FLOW-02 的替代建议结构化正是如此）。⇒ 顺延目标要么是明确的 plan，要么直接写成「里程碑收尾之后的独立工作项」。
- **工具链对非常规目录名沉默失效**：`112-1` / `113-2` 这两个纯数字 slug 让 `extractPhaseToken` 把 `112-1` 整体当作 phase token ⇒ `roadmap.analyze` 把两个相位报成 0 plans、`milestone complete` 的守卫误判为「未开工」并拒绝执行。归档因此改为手工按契约完成。⇒ 相位目录名的 slug 不要以数字开头。

### Patterns Established

- **状态机守卫收口进单一 service + CAS + 事务内单次查询**（`BlueprintLifecycleService`），把 confirm 的 TOCTOU 从设计上消除；任何「把终态会话拉回运行」的需求复用 `areopen_stage`，不各自 update session.status。
- **超界不等于失败**：AI 审查打回 ≤2 轮后转「待人审」并携未决清单，死锁的正向出口是 finding 处置端点（`resolve`/`dismiss`），⛔ 不用作答通道处置。
- **「best-effort」只覆盖观测、不覆盖业务**：读失败如实 503 + 中性 detail，⛔ 不把业务主体包进 `except` 返 200 空结构（否则「读失败」与「真的没数据」在 HTTP 层同形）。
- **无数据的统计返 `None` 不返 0**，并把「无数据 / 零值 / 有值」写成三条并列用例——这是逮住「口径写错导致指标恒零而测试全绿」的唯一手段。
- **相位内新增 stage 的 `stage_state` 只写自己那个键**，靠 engine 顶层浅合并落盘（写别人的桶会被整桶覆盖抹掉，症状是计数归零 → 无限打回循环）。

### Key Lessons

- **需求的验收单位是「用户能不能做到」，不是「后端有没有实现」。** CLAR-03 的整条链路（后端全绿 → 相位 verified → 需求打勾 → 审计打回）说明相位级 VERIFICATION 无法覆盖跨相位需求的可达性，需要在需求层面指定 owner。
- **顺延必须给出语义理由而不只是排期理由。** GATE-01 顺延同步点 2 的理由是「蓝图的 `DONE` 语义是等人审，翻默认 = 未经人审的蓝图直送编码代理」——这条写清楚之后，后续每个 plan 都能独立判断「现在能不能翻」，而不需要回头问人。
- **默认值是安全边界的一部分。** 四个 per-entry 开关默认 `technical_plan` 让三道 BROKEN 的入口接缝（G1/G3/G4）在生产上零影响，从而使「审计判 tech_debt 而非 gaps_found」这个判断成立。灰度顺序也要按此推演：真翻开关后**第一次澄清**就撞 G1/G4，早于「未经人审的蓝图进 ai_coding」显形。
- **双 worktree 并行开发是可行的，前提是边界纪律在立项时定版并逐 plan 核算**（`git diff <冻结面>` 为空作为门禁），而不是靠执行时的自觉。

### Cost Observations

- Sessions: 跨多会话执行，逐 plan discuss→plan→execute→verify→review→fix 子代理链；两次 provider 资源上限打断后由续跑执行者逐条复核补齐（116-07），未重做实现。
- Notable: 单 plan 多在 60–180min 量级（见 STATE.md Performance Metrics）；相位级 review 修复轮（114: 10 fixed / 115-UI: 13 fixed / 116: 9 fixed）稳定抓到真实缺陷，是质量门控中性价比最高的一环。

## Milestone: v0.22.0 — 代码智能图分析升级（对标 GitNexus）

**Completed:** 2026-08-11（未打 tag）
**Phases:** 7（121–127） | **Plans:** 44 | **Tasks:** 105 | **Requirements:** 26 满足 / 1 部分（IMPACT-03）/ 0 未达 | **Audit:** tech_debt
**Timeline:** 2026-08-09 → 2026-08-11（约 3 天）

### What Was Built

在现有 codegraph/RAG 底座上叠加内存图分析层：`(repository, branch)` 图缓存地基（P121）；impact/trace 深度分组与最短路、MCP/对话双面（P122）；detect_changes 水位锚定 diff（P123）并闭环进容器自查与 MR 影响面（P124）；Louvain 社区 + 指纹跳过 + 模块摘要三点注入（P125）；Endpoint→Process 执行流 + rename_preview + friday-impact/refactoring skills（P126）；Semgrep diff-aware advisory + LSP 基准且不盲翻默认（P127）。Phase 127 收口实修闭合空 SHA 入队 hollow，并清掉 code_graph 链路 83 项观测契约违规。

### What Worked

- **「让假绿在结构上不可能」再次奏效**：空 SHA 入队被 `enqueue_semgrep_scan_for_branches` 守卫堵住；MCP↔对话双面逐字节守护；弱证据封顶 MEDIUM 防止裸名边顶到 CRITICAL。
- **冻结面纪律守住**：`repo_router_v2.py` 与 `mcp/` 子模块指针全程不动；模块摘要只在 adapter/evidence 层注入。
- **对抗性审计透镜**：不采信自报，专找「单测绿但生产数据流断开」——抓住 IMPACT-03 数据依赖与 Semgrep hollow。
- **观测契约收口进 LOGGING-SPEC**：把原先只活在守卫测试里的命名规则写进规范 §5，后续自动生效。

### What Was Inefficient

- **合成测绿掩盖生产空数据**：IMPACT-03 四条分支全靠合成数据，DB CrossRepo=0 时用户永远看不到跨仓结果——需求勾 Complete 过早。
- **客户端白名单再次漂移**：服务端新增图工具，`mcp` npm 静态白名单未跟进（v0.20.0 同型复现）。
- **Nyquist VALIDATION 七相位均未 reconcile 到 `validated`**：文件在、状态停在 planned/complete/draft，覆盖债累积。
- **CLI 归档产出英文 one-liner 堆砌**：MILESTONES/STATE 需手工中文化，与仓库台账风格对齐成本固定。

### Patterns Established

- **图工具双面同源编排**：内核纯函数 + 包外 ORM 壳 + `run_*` 唯一编排 + MCP/agents 薄壳，失败语义与信封固定。
- **水位锚定 diff**：detect_changes base 钉 `last_indexed_commit_sha`，保证与 Symbol 行号同源。
- **fingerprint/Jaccard 跳过重生成**：社区成员未变 ⇒ LLM 调用数为 0（可验收）。
- **advisory + 诚实边界声明**：Semgrep CE 函数内 taint 边界写进 MR 文案，Pro 经 token opt-in。

### Key Lessons

- **空洞入队是比「功能未写」更危险的假绿**：空 SHA → 恒 unavailable → 单测 mock enqueue 不断言 SHA ⇒ 生产链路从未真正扫描。守卫必须钉在「能不能跑」的前置条件上。
- **Partial 要写进用户可见口径**：CrossRepo=0 时诚实空列表可以，但台账/文档不得写成「生产跨仓 impact 已可用」。
- **子模块白名单与服务端工具面是同一交付面**：skills 指引调用的工具若 npm 包不可发现，IDE 侧交付就是 hollow。

### Cost Observations

- Sessions: 多会话连续执行（121–127 波次并行度高，125 可与 122–124 并行）。
- Notable: Phase 127 收口多一轮实修（hollow 闭合 + 观测违规清理），验证从 gaps_found 回到 human_needed。

## Milestone: v0.23.0 — 仓库路由增强（分阶段决策漏斗）

**Completed:** 2026-08-14（未打 tag）
**Phases:** 5（128–132） | **Plans:** 16 | **Tasks:** ~30 | **Requirements:** 25/25 | **Audit:** tech_debt
**Timeline:** 2026-08-14 当日立项并收口

### What Was Built

把选仓从全库相似度升级为决策漏斗：专项画像 + 团队门禁（128）→ shortlist/历史先验/角色图（129）→ 放置单元 + 主路径接线（130）→ 五门 + 有界反思（131）→ 高三合成回归 + 契约包（132）。`RepoRouterV2` 降为 shortlist 内细排，未推倒。

### What Worked

- **线性漏斗 + 硬范围**：out_of_team / 空团队在结构上无法静默全库 primary；V2 调用一律 hard_scope。
- **合成宇宙回归**：Learning-tools fixture + D2 bar 让 INT-02 不依赖活 Space 也能绿。
- **决策锁前置（DECISIONS.md）**：D1–D5 减少 discuss 灰区，当日五相位可跑完。

### What Was Inefficient

- **Nyquist 再次未 reconcile**：五相位 VALIDATION 停在 draft（与 v0.22 同型债）。
- **CLI `milestone.complete` 英文 one-liner**：MILESTONES 条目需手工中文化。
- **live_space 默认 skip**：真 Space 抽验仍挂账。

### Patterns Established

- **漏斗阶段可单测纯函数**：profile / team_gate / shortlist / place_units / gates / reflection 先内核后 Adapter 接线。
- **D2 bar 作为客观验收函数**：hit@primary + out_of_team=0 可文档化、可自动化。

### Key Lessons

- **不推倒 V2、只收窄候选**比重写排序更稳：硬 scope 比调权重更能挡住漂仓。
- **合成 fixture 是活 Space 的必要替身**，但不能替代真 Space 抽验——记 tech_debt 而非 pretended passed。

### Cost Observations

- Sessions: 单日连续执行（128→132，`--no-transition` 收尾后独立 complete-milestone）。
- Notable: 约 94 files / +16k LOC（含 tests）；审计当日完成。

## Milestone: v0.25.0 — Cursor / Claude Code 会话知识回写

**Shipped:** 2026-08-31
**Phases:** 5 (141–145) | **Plans:** 25 | **Tasks:** 57

### What Was Built
IDE 会话知识回写全链路：独立 `SessionCapture` 账本 + INV-6 `CaptureService`；新 MCP `report_session_knowledge`（服务端/snapshot/npm 三面对齐）；durable eval（`session_capture_eval`）与 medium/high → `DOCUMENT`/`session_capture` 入图；按仓召回与 Capture 只读回放；Cursor/Claude Code hooks 配对可见问答（干净树仍回写、hooks.json v1 merge、fail-soft）。

### What Worked
- Capture 永不丢作为第一门禁：挂钩失败仍 `accepted=true`，评估/入图失败不删账本。
- 新工具而非扩 `report_project_knowledge`，Memory 门闩零回归可测。
- 双宿主按官方事件模型分别接线，避免 Claude Stop 脚本误拷到 Cursor。

### What Was Inefficient
- 收口时 historical `deferred-items.md` heading/table 形 CLI 无法 acknowledge，需手写 `status`/`resolved` 单元格才过 audit-open。
- skills 子模块 push 遇 HTTPS 凭据失败，改 SSH 后才同步 gitlink。

### Patterns Established
- 会话原始问答 ≠ 提炼知识 ≠ Interaction Ledger；评估专用 `call_source`。
- IDE 资产与实体 skills 事件模型对齐 + 父仓 gitlink 必须可达远端 tip ancestry。

### Key Lessons
- 里程碑关闭前先扫 `audit-open` 的 heading-shape deferred 项，避免最后一公里卡死。
- 可选真实 IDE smoke 可标 `deferred_advisory`，勿与 Nyquist 门禁混为一谈。

## Cross-Milestone Trends

| Milestone | Phases | Plans | Shipped |
|-----------|--------|-------|---------|
| v0.1.0 首启初始化向导 | 5 | 9 | 2026-06-09 |
| v0.8.0 多仓串行编码 → 融合 PR | 5 | 16 | 2026-06-17 |
| v0.16.3 外部依赖接入知识体系 | 4 | 15 | 2026-07-01 |
| v0.19.0 技术方案可信度 | 5 | 39 | 2026-08-02（未打 tag） |
| v0.20.0 技术方案蓝图 | 6 | 34 | 2026-08-02 |
| v0.21.0 蓝图过程可见与返工闭环 | 4 | — | 2026-08-05（未打 tag） |
| v0.22.0 代码智能图分析升级 | 7 | 44 | 2026-08-11（未打 tag） |
| v0.23.0 仓库路由增强（决策漏斗） | 5 | 16 | 2026-08-14（未打 tag） |

> v0.19.0 与 v0.20.0 是同期双 worktree 并行开发的两个里程碑（2026-07-29 → 2026-08-02），于 2026-08-02 合并（同步点 2）。v0.22.0 为单线高速交付（约 3 天 / 7 相位）。v0.23.0 为单日五相位漏斗交付。

**趋势观察（截至 v0.23.0）：**

- **单相位规模在涨。** v0.16.3 是 15 plans / 4 phases（≈3.8），v0.19.0 是 39 plans / 5 phases（≈7.8），翻了一倍；v0.20.0 是 34 plans / 6 phases（≈5.7），在并行约束下略有回落。收益是相位内依赖可控、wave 并行度高；代价是单相位的验证面变大，v0.19.0 的 107 一相就压了 5 条需求 9 个 plan，也正是缺口发生的那一相。
- **审计判定连续落在 `tech_debt`**：代码层需求全满足或近乎全满足，卡在「真实飞书 / 真实容器 / 真实 Qdrant / 浏览器视觉 / 真 Space」这几类本地无法闭环的人工验收上。累计已挂账多项，**至今无承接方**。这不再是单个里程碑的遗留，而是一个需要独立处置的结构性缺口——建议建立运维验收 backlog 与定期真机验收窗口。
- **「延后人工视觉验收」的代价在 v0.19.0 第一次具体化。** 此前它只是挂账数字；这次它直接导致四条需求被建在一个已下线的组件里、五个相位判绿、返工一次跨相位闭环。挂账不是零成本的。
- **双 worktree 并行开发首次验证可行。** 前提是边界纪律在立项时定版并逐 plan 核算（冻结面 `git diff` 为空作为门禁）：两个里程碑 11 个相位跑完**零源码文件交集**，合并冲突只剩 `.planning/` 台账与一个 migration 叶子分叉。
- **`tech_debt` 归档已成默认出口（含 v0.22.0 / v0.23.0）。** 代码层近乎全满足，卡在真实环境样本 / Nyquist reconcile——继续 accept 归档可以，但债务清单必须进 STATE Deferred，避免「过了审计就消失」。
- **「服务端在线、客户端白名单缺席」在 v0.22.0 第三次同型复现**（v0.19 `nr_snapshot` / v0.20 mcp 四工具 / v0.22 图工具集）——子模块发版应进里程碑 Definition of Done，或显式标为跨仓 out-of-scope 并挂账。
- **v0.23.0 证明「决策锁 + 合成回归 + 硬 scope」可当日收口五相位**；Nyquist draft 债仍未断。

**反复出现的形态（跨里程碑）：**

| 形态 | 首次登记 | v0.19.0 复现 | v0.20.0 复现 | v0.22.0 复现 | v0.23.0 复现 |
|------|----------|--------------|--------------|--------------|--------------|
| 状态文件（STATE / REQUIREMENTS traceability）滞后于磁盘真实状态 | v0.8.0 | ROADMAP 进度表滞后；Traceability 口径三分 | 归档前专门记账订正 | CLI 英文 one-liner 需手工中文化；IMPACT-03 Traceability 曾标 Complete | CLI 英文堆砌；progress 计数短暂漂移 |
| 真机 / 真实 provider / 浏览器视觉验收是结构性 deferred | v0.16.3 | 27 项 UAT pending | 无飞书凭证真实导出未跑 | 127 三项 human_needed（镜像体积 / LSP 真仓 / IMPACT-03 样本） | live_space skip + 真 Space 抽验 |
| 规划文档与工具链契约漂移 | v0.16.3 | 未复现 | `112-1`/`113-2` 目录名令归档工具失效 | CLI `milestone complete` 产出英文堆砌，与中文台账风格冲突 | 同左 |
| 「消费方在线、生产方离线」的接缝 | v0.19.0 | `RoutingDecisionPanel` / `nr_snapshot` | mcp npm 缺四个蓝图工具 | mcp npm 缺图工具集；CrossRepo 生产者因 LSP 关而离线 | 未新增同型；漏斗硬 scope 主动防漂 |
| 合成测 / mock 掩盖生产空洞 | v0.19.0（叶子组件单测当用户可见） | 首次具体化 | 守卫 skip 掩盖对齐缺口 | Semgrep 空 SHA 入队 hollow；跨仓四分支纯合成 | D2 bar 合成宇宙绿；真 Space 未跑 |
