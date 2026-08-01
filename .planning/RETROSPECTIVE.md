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

## Cross-Milestone Trends

| Milestone | Phases | Plans | Shipped |
|-----------|--------|-------|---------|
| v0.1.0 首启初始化向导 | 5 | 9 | 2026-06-09 |
| v0.8.0 多仓串行编码 → 融合 PR | 5 | 16 | 2026-06-17 |
| v0.16.3 外部依赖接入知识体系 | 4 | 15 | 2026-07-01 |
| v0.20.0 技术方案蓝图 | 6 | 34 | 2026-08-02 |

**反复出现的形态（跨里程碑）：**

| 形态 | 首次登记 | v0.20.0 复现 |
|------|----------|--------------|
| 状态文件（STATE / REQUIREMENTS traceability）滞后于磁盘真实状态 | v0.8.0 | 归档前需专门做一轮记账订正（ROADMAP 六处 + 14 份 SUMMARY frontmatter） |
| 真机 / 真实 provider / 浏览器视觉验收是结构性 deferred | v0.16.3 | 无飞书凭证 ⇒ 一次真实导出验证未执行，版式退化风险未消解 |
| 规划文档与工具链契约漂移 | v0.16.3（顶层 ROADMAP 缺 `### Phase N:` 明细块） | 相位目录名 `112-1` / `113-2` 让 phase token 解析失效，归档工具拒绝执行 |
| 共享展示常量 / 单源 helper 事后抽取 | v0.16.3 | 反向验证成立：本里程碑把「单一实现」前置为纪律（作答通道 / 范围闸 / 渲染器 / 文件读取），未出现事后抽取 |
