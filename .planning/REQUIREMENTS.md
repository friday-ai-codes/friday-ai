# Requirements — v0.20.0 技术方案蓝图

**Milestone:** v0.20.0
**Defined:** 2026-07-29
**Source:** `.planning/technical-blueprint/DESIGN.md`（设计蓝图，13 节，§12 八项决策已定夺）+ 高三提分专项路由试验（RepoCharter 动机实证）
**并行开发:** 与 v0.19.0（`milestone/v0.19.0-plan-trust` worktree）双线并行，边界纪律见 DESIGN.md §13；DEPTH-01~05 自 v0.19.0 Phase 108 迁入本里程碑（映射：DEPTH-01→SCHEMA-04、DEPTH-02/03→SCHEMA-03、DEPTH-04→SCHEMA-06、DEPTH-05→FLOW-01）

> 需求以「用户能做到什么 / 用户不会遭遇什么」表述，不描述实现。实现取舍见 DESIGN.md。

---

## v0.20.0 Requirements

### SCHEMA — 蓝图产物结构

- [ ] **SCHEMA-01**：用户拿到的技术方案是结构化蓝图（blueprint/v1）：六段固定骨架（仓库关联 / 现状分析 / 实现概述 / API / 影响范围 / 交互流程）+ 需求规格 + 验收锚点；缺段或必填缺失无法通过校验入库（schema 强制而非提示词约定）
- [ ] **SCHEMA-02**：蓝图关键结论（选仓理由 / 现状 finding / 影响判断）均携带引用证据，指向知识实体 / 代码文件 / RAG chunk / 其他蓝图 / 仓库章程条目，可溯源可预览
- [ ] **SCHEMA-03**：实现概述逐项标注 change_type（新建 / 改动 / 删除 / 间接完善），并给出功能↔模块↔仓库映射与实现依赖波次（迁入 DEPTH-02/03）
- [ ] **SCHEMA-04**：交互流程段呈现完整业务编排叙事：在哪个页面、经哪个接口、传什么参数、拿到什么数据、数据流向哪里、有哪几条行为路径（迁入 DEPTH-01）
- [ ] **SCHEMA-05**：API 段包含接口描述 / 请求响应示例 / 数据来源说明（数据已有，或需哪个仓支持产出）
- [ ] **SCHEMA-06**：execution_plan 从蓝图确定性派生且与现行 schema 一致，编码分发链路零改动可消费；方案中不出现以周为单位的排期（迁入 DEPTH-04）
- [ ] **SCHEMA-07**：蓝图是项目级——一个项目一份活跃蓝图，多版本演进；版本间可做 block 级 diff

### LIFE — 生命周期

- [ ] **LIFE-01**：每份蓝图具备 11 态生命周期（调研中 / 产出中 / AI 审查中 / 需要澄清 / 待人类审查 / 已确认 / 实施中 / 实施完成 / 已归档 / 已失败 / 已废弃），状态转移有守卫且全程可追溯
- [ ] **LIFE-02**：存在未解决的阻塞澄清时蓝图不可确认；执行确认动作的成员自动进入方案评审人名单（可多人），署名留痕、通知定向
- [ ] **LIFE-03**：生成失败或中途放弃有显式终态，不再停留在进行中状态误导用户；失败可重试

### CHARTER — 仓库章程与双面路由

- [ ] **CHARTER-01**：每仓一份版本化章程（定位 / owned_domains 含 planned / 边界禁区 / 落点偏好 / 演进态），AI 起草、人工确认生效；人工确认内容不被 AI 覆盖，AI 只可提修订草案
- [ ] **CHARTER-02**：路由按 feature_point 意图分流加权——净新增重章程与历史落点、改造重能力树（章程作 sanity check：命中禁区或 maintenance_only 降权且保留须显式理由）；score breakdown 含 charter_match 分量且可解释
- [ ] **CHARTER-03**：确认门动作回灌章程学习闭环——确认/改判沉淀 owned_domains 草案、移除仓沉淀 boundaries 草案、rejected 路由候选可提示沉淀为禁区；一律 AI 草案 + 人工 confirm

### FLOW — 三大编排阶段

- [ ] **FLOW-01**：需求歧义超阈值时，系统先抛出带候选选项的澄清再进入调研（规格门），并对每个 feature_point 给出意图分类（greenfield / brownfield / fix）（迁入 DEPTH-05）
- [ ] **FLOW-02**：阶段 1 逐仓容器调研产出 fitness 判定（suitable / partial / unsuitable + 理由 + 替代建议）；不合适仓自动回主 agent 重路由（有界 ≤2 轮），过程对用户可见
- [ ] **FLOW-03**：阶段 1 出口是硬确认门——用户确认仓库集与职责后才进入方案拟定；可移除仓 / 手动加仓 / 改判 role / 修改职责，反馈驱动重调研直至确认；确认后锁定，后续变更必须重开确认门
- [ ] **FLOW-04**：仓库关联区分 direct（要编码改动）/ indirect（被依赖调研），各带结构化选仓理由与证据；indirect 默认轻量调研、可人工升级深调研
- [ ] **FLOW-05**：阶段 2 按锁定职责逐仓拟定分仓方案（RepoPlan），期间可多轮澄清、可发起单仓定向补调研
- [ ] **FLOW-06**：阶段 3 主 agent 融合装配六段蓝图并做跨仓 API 对账——消费的接口必须找到提供方或显式标注 needs_support，跨仓矛盾抛澄清而非静默拍板
- [x] **FLOW-07**：独立 AI 审查代理按七类规则（schema / goal-backward / 引用覆盖 / 角色一致性 / API 闭环 / 禁令 / 章程边界）产出分级 findings；BLOCKER 按归因有界打回（仓级回该仓、融合级回 merge，合计 ≤2 轮）后升人审
- [x] **FLOW-08**：蓝图必经人类终审（通过 / 驳回带划线评论）；驳回回产出中修订并计轮次

### CLAR — 划线澄清

- [x] **CLAR-01**：AI 可对蓝图任意位置发起飞书文档式划线提问（带候选选项），用户在查看器中看到划线高亮并可多轮回复；人也可对任意选区主动发起评论
- [x] **CLAR-02**：澄清答案回灌产生新版本，线程置 resolved 并物化进决策记录；版本变更后批注按 block 重锚定，失锚线程集中可见、不静默丢失
- [x] **CLAR-03**：人类可直接编辑蓝图内容（block 级），编辑生成新版本、归属可审计；人工编辑不被 AI 覆盖，冲突时 AI 必须开线程询问
- [x] **CLAR-04**：澄清无人应答保持显式 pending——可提醒、可随时作答恢复；不自动作答、不判失败、绝不无声卡死

### BUS — 共享上下文总线

- [ ] **BUS-01**：蓝图容器经任务 token 绑定「会话→项目」作用域（方案期无分支也能定位项目），可实时读写会话级上下文总线，写入即对并行容器可见
- [ ] **BUS-02**：容器可声明等待某条上下文：短等待保活轮询带超时降级，长等待携带 partial 产物退出、条目就绪后自动重派续作；互相等待环被检测并抛澄清
- [ ] **BUS-03**：会话结束后有沉淀价值的上下文条目可经 distill 管道进入项目记忆（人工 confirm）

### VIEW — 前端与知识库

- [x] **VIEW-01**：用户可打开结构化蓝图查看器：六段导航、结构化渲染（流程图 / 伪代码 / API 卡 / 影响矩阵）、状态徽标与阶段时间线（生成中实时进展）
- [x] **VIEW-02**：仓库关联可直接跳转仓库页；引用可在查看器上再弹一层预览（知识实体 / **代码位置：文件路径 + 行号区间 + 引用快照** / 其他蓝图 / 章程条目）
  - ⚠️ **Phase 115 范围说明（代码预览为降级形态）**：现有读面拿不到源码正文 —— `chunk_lookup._query_covering_chunks` 只 select `chunk_id/file_path/line_start/line_end/chunk_index`，`chunk_at_views` 返 `{path, line, chunks}` 不带正文；唯一带 `content` 的是 `POST /api/repositories/<id>/search/`（向量搜索，必须给 query、已重排过滤，无法按 path + 行号区间取）。因此 115 交付「路径 + 行号区间 + 引用快照」，**无源码正文亦无行高亮**；源码正文读面（及相应的行高亮）顺延 **Phase 116**，⛔ 115 不新增后端端点。
- [x] **VIEW-03**：知识库新增「技术方案」tab：列表、状态 / 项目 / 仓库筛选、搜索、深链直达查看器
- [x] **VIEW-04**（**PARTIAL @ Phase 115，剩余部分顺延 Phase 116**）：蓝图与项目自动关联（项目内生成即挂项目）；蓝图关联的知识 / 上下文 / 其他蓝图互相可查、可引用（互引成图谱边）
  - ✅ **Phase 115 交付**：项目自动关联 + 项目物料面板可见；**正向**可查 —— 本蓝图**引用了**哪些知识实体 / 仓库 / 其它蓝图，逐条可点可跳。
  - ⏭ **顺延 Phase 116（其 SC-4 知识图谱物化）**：**反向「被谁引用」**与互引成图谱边。原因：`server/knowledge/artifact_associations.py:75` 查的是 `initiatives.Artifact` 投影出的 `KnowledgeEntity`，而蓝图落在 `delivery.Artifact` ⇒ 拿蓝图 id 去调 `getRelated` / `getArtifactAssociations` **必然落空**；图谱边的物化本就归属 116，115 不提前补后端。
- [ ] **VIEW-05**：蓝图可导出飞书文档（含决策记录附录）；未确认版本在界面与导出物上均显式标注

### GATE — 入口与质量

- [ ] **GATE-01**：workflow / chat / MCP / feature list 全入口统一走蓝图编排；MCP 入口支持异步澄清协议（返回 pending、可作答、可续取结果），不再跳过澄清
- [ ] **GATE-02**：蓝图 golden set 与质量指标基线建立（引用覆盖率 / AI 打回率 / 人审修改量 / 澄清轮次 / 目标仓命中率，首条 golden case 为高三提分专项），质量退化可被回归检出

---

## Future Requirements（本里程碑不做）

- 蓝图 golden set 弱标签扩样（依赖采纳/修改行为日志积累）
- AI 审查与起草强制换模型的交叉审查实验（档位已可配，默认同档）
- 章程 charter_match 权重的自动调参 / 在线学习
- 段级细粒度编辑权限（初版全员可编辑 + 版本链审计）
- 母子蓝图的编排级拆分（schema 已支持蓝图互引，编排拆分另议）

## Out of Scope（显式排除及理由）

- **修改 `repo_router_v2.py`** — §13.2 边界纪律：章程/历史落点证据在 `blueprint_route` adapter 层融合，路由核心归 v0.19.0 独占
- **修改既有 `technical_plan` process 六文件**（decompose_segments / research_adapter / architect_merge_adapter / merged_plan / clarify_adapter / render）— 冻结只读，蓝图流水线全走 `blueprint_*` 新文件；旧 process 退役观察期后另行删除
- **TechPlanCard / RoutingDecisionPanel / 执行时间线组件改动** — 归 v0.19.0（Phase 109/110）；本里程碑仅在同步点 2 之后做触点接入（Phase 116）
- **`ConvergenceSessionEvent` 既有事件类型/字段变更** — 契约由 v0.19.0 定义，本里程碑只新增 `blueprint_*` 事件类型
- **Prompt Center 化蓝图提示词** — 沿用硬编码 Python 字符串惯例，搬迁另议

---

## Traceability

**Coverage: 35/35 — 每条需求恰好映射到一个相位，无孤儿、无重复。**

| Requirement | Phase | Status |
|-------------|-------|--------|
| SCHEMA-01 | Phase 111 蓝图底座 | Pending |
| SCHEMA-06 | Phase 111 蓝图底座 | Pending |
| SCHEMA-07 | Phase 111 蓝图底座 | Pending |
| LIFE-01 | Phase 111 蓝图底座 | Pending |
| LIFE-02 | Phase 111 蓝图底座 | Pending |
| LIFE-03 | Phase 111 蓝图底座 | Pending |
| CHARTER-01 | Phase 111 蓝图底座 | Pending |
| GATE-02 | Phase 111 蓝图底座 | Pending |
| FLOW-01 | Phase 112 规格门与双面路由调研 | Pending |
| FLOW-02 | Phase 112 规格门与双面路由调研 | Pending |
| FLOW-03 | Phase 112 规格门与双面路由调研 | Pending |
| FLOW-04 | Phase 112 规格门与双面路由调研 | Pending |
| CHARTER-02 | Phase 112 规格门与双面路由调研 | Pending |
| CHARTER-03 | Phase 112 规格门与双面路由调研 | Pending |
| FLOW-05 | Phase 113 分仓方案与融合 + Context Bus | Pending |
| FLOW-06 | Phase 113 分仓方案与融合 + Context Bus | Pending |
| SCHEMA-02 | Phase 113 分仓方案与融合 + Context Bus | Pending |
| SCHEMA-03 | Phase 113 分仓方案与融合 + Context Bus | Pending |
| SCHEMA-04 | Phase 113 分仓方案与融合 + Context Bus | Pending |
| SCHEMA-05 | Phase 113 分仓方案与融合 + Context Bus | Pending |
| BUS-01 | Phase 113 分仓方案与融合 + Context Bus | Pending |
| BUS-02 | Phase 113 分仓方案与融合 + Context Bus | Pending |
| BUS-03 | Phase 113 分仓方案与融合 + Context Bus | Pending |
| FLOW-07 | Phase 114 审查与澄清收敛 | Complete |
| CLAR-02 | Phase 114 审查与澄清收敛 | Complete |
| CLAR-03 | Phase 114 审查与澄清收敛 | Complete |
| CLAR-04 | Phase 114 审查与澄清收敛 | Complete |
| VIEW-01 | Phase 115 前端查看器与知识库 | Pending（后端供数面已就位 @ 115-01：`blueprint-document` / `blueprint-events`；查看器本体待 115-02+） |
| VIEW-02 | Phase 115 前端查看器与知识库 | Pending（代码预览为降级形态：路径 + 行号区间 + 引用快照；源码正文与行高亮顺延 116） |
| VIEW-03 | Phase 115 前端查看器与知识库 | Pending（后端供数面已就位 @ 115-01：`blueprint-list` 含筛选与五键分页；tab 本体待 115-06） |
| VIEW-04 | Phase 115 前端查看器与知识库（正向引用可查）+ Phase 116（反向「被谁引用」与图谱边） | PARTIAL |
| CLAR-01 | Phase 115 前端查看器与知识库 | Pending（后端供数面与写口已就位 @ 115-01：`blueprint-review-threads` GET 多轮 + POST 选区评论；批注层待 115-03/04） |
| FLOW-08 | Phase 115 前端查看器与知识库 | Complete |
| GATE-01 | Phase 116 入口收编与导出 | Pending |
| VIEW-05 | Phase 116 入口收编与导出 | Pending |

**按相位汇总：**

| Phase | Requirements | 数量 |
|-------|--------------|------|
| 111 蓝图底座 | SCHEMA-01/06/07, LIFE-01/02/03, CHARTER-01, GATE-02 | 8 |
| 112 规格门与双面路由调研 | FLOW-01/02/03/04, CHARTER-02/03 | 6 |
| 113 分仓方案与融合 + Context Bus | FLOW-05/06, SCHEMA-02/03/04/05, BUS-01/02/03 | 9 |
| 114 审查与澄清收敛 | FLOW-07, CLAR-02/03/04 | 4 |
| 115 前端查看器与知识库 | VIEW-01/02/03/04, CLAR-01, FLOW-08 | 6 |
| 116 入口收编与导出 | GATE-01, VIEW-05 | 2 |
| **合计** | | **35** |

**跨类别组合的理由（不按 SCHEMA/LIFE/CHARTER/FLOW/CLAR/BUS/VIEW/GATE 机械切分）：**

- **CHARTER-01 与底座同相位、CHARTER-02/03 与路由调研同相位**：章程模型/起草管道是数据底座（111），而双面路由与确认门回灌是消费闭环（112）——闭环依赖确认门存在，必须与阶段 1 编排同相位交付。
- **SCHEMA-02~05 与阶段 2/3 同相位**：六段内容与引用强制由分仓方案与融合真实产出，schema 字段在 111 已定义，但「产出达标」的承诺只能随流水线（113）验收。
- **CLAR-01 与 FLOW-08 在前端相位**：划线交互与人审终审的用户可见承诺依赖查看器（115），线程/回灌等后端机制在 114 先行。
- **GATE-02（golden set）放底座**：对齐 v0.19.0 Phase 105 方法论——质量标尺先建，后续每个相位的产出都有客观基线可回归。

---
---

# Requirements — v0.19.0 技术方案可信度

**Milestone:** v0.19.0
**Defined:** 2026-07-28
**Source:** 生产实例实证排查（friday.yc345.tv / 会话 `ccd817d9`）+ `.planning/research/ROUTING-RANKING.md`

> 需求以「用户能做到什么 / 用户不会遭遇什么」表述，不描述实现。实现取舍见 PROJECT.md Key context 与 research。

---

## v0.19.0 Requirements

### RELY — 链路可靠性

- [ ] **RELY-01**：用户拿到的技术方案一定来自完整编排链路；编排未完成时，系统不会用未经调研的草稿冒充正式方案（如仍提供草稿，必须显式标注「未经代码调研」）
- [ ] **RELY-02**：技术方案编排不会无人应答地永久停在澄清阶段——澄清必达用户、可作答，且超时/失败有明确出口
- [ ] **RELY-03**：路由降级时用户能看见「本次未经 LLM 推理，置信度仅供参考」，而不是拿到一份看不出问题的全 low 结果
- [ ] **RELY-04**：Stage 1 完全失联时，系统仍能给出可用的置信度分级并自动推进——置信度由分数 margin 确定性推导，LLM 判断降为输入而非决策者
- [ ] **RELY-05**：路由在上游 LLM 抖动或缓慢时仍可用——单次调用有重试与延迟上界，用户不会无限等待

### ROUTE — 路由质量

- [ ] **ROUTE-01**：路由结果分两组呈现——本项目关联仓一组、全局候选一组，各自排序，用户能一眼看出哪些是本平台内的
- [ ] **ROUTE-02**：跨组候选带明确标注「未关联当前平台，可能涉及跨组协作」，用户据此判断是否要拉其他团队
- [ ] **ROUTE-03**：大而全的单体仓库不再因命中节点多而被系统性高估——同等相关度下小而精的正确仓库能胜出
- [ ] **ROUTE-04**：业务域、团队归属、技术栈、关键程度等元数据参与排序打分，而不只是给 LLM 看
- [ ] **ROUTE-05**：仓库维护活跃度以连续量参与打分，而非只有「疑似废弃」一档生效
- [ ] **ROUTE-06**：运维可在不发版的前提下调整各信号权重
- [ ] **ROUTE-07**：每个候选的分数可展开到各信号的贡献值，用户与开发者都能看懂它为什么排这个位置
- [ ] **ROUTE-08**：路由质量有可回归的验收基线——golden set 覆盖真实用例，权重改动导致的退化能被自动检出
- [ ] **ROUTE-09**：同样的需求与同样的索引状态，重复路由得到同样的结果与排序

### DEPTH — 方案深度

- [ ] **DEPTH-01**：技术方案包含数据产出与流转方向、业务流程编排叙事（用户在哪个页面、经哪个接口、传什么参数、拿到什么数据、数据流向哪里、用户有哪几条行为路径）
- [ ] **DEPTH-02**：技术方案给出功能 ↔ 模块 ↔ 仓库的映射关系
- [ ] **DEPTH-03**：技术方案逐项标注新增还是改造，改造项须说明与既有功能如何配合、影响哪些已交付能力
- [ ] **DEPTH-04**：技术方案不再产出以周为单位的分阶段实施计划
- [ ] **DEPTH-05**：需求存在影响方案质量的不确定点时，系统主动抛出澄清并给出候选选项，而不是带着模糊假设直接出方案

### SPINE — 双脊柱合流

- [ ] **SPINE-01**：编排产出的技术方案可直接进入选目标仓 → 配置分支 → 确认编码流程，无需用户重新走一遍方案生成
- [ ] **SPINE-02**：系统不再存在「由对话模型徒手编写方案正文」的产出路径

### OBS — 过程可观测

- [ ] **OBS-01**：技术方案生成过程实时返回阶段进展与内容，用户能看到它正在做什么，而不是长时间静默后一次性吐出结果
- [ ] **OBS-02**：方案调研阶段的容器执行日志对用户可见（与深度分析一致的体验）
- [ ] **OBS-03**：前端展示方案生成的阶段时间线，失败停在哪一步一目了然

---

## Future Requirements（本里程碑不做）

- 把 161 个未被飞书对照表覆盖的仓库归入团队空间（需业务侧先补表）
- 客户端仓（ios / android / harmony，飞书表中 215 个）接入 Friday 索引
- 两套 CodingPlan（`chat.CodingPlan` / `mcp_tools.McpCodingPlan`）合表为 canonical
- 用 `WorkItem → PlanVersion → MR` 追溯链自动生成弱标签，把 golden set 从数十条推到 200+
- 路由权重的自动调参 / 在线学习（需先积累点击与采纳日志）

## Out of Scope（显式排除及理由）

- **仓库去重与 Space 归属治理** — 立项前已作为前置工作完成（261→259 仓、7 个团队空间、17 个幽灵点清除）
- **删除 `create_coding_plan`** — 实证它是 SPA 唯一的编码执行入口，MCP 执行链路亦依赖其桥接；本里程碑改为拆分创作/执行两半而非删除
- **把前后端从仓库名迁到彩色标签** — 生产环境已按前后端加好命名前缀；标签化属 UI 改造，与本里程碑的可信度目标无关
- **Prompt Center 化方案提示词** — 方案结构提示词硬编码在 `process_runtime/*.py`，本次直接改代码；是否搬进 Prompt Center 另议

---

## Traceability

<!-- 由 gsd-roadmapper 填充：REQ-ID → Phase。相位定义见 ROADMAP.md（Phases 105–110）。 -->

**Coverage: 24/24 — 每条需求恰好映射到一个相位，无孤儿、无重复。**

| Requirement | Phase | Status |
|-------------|-------|--------|
| RELY-04 | Phase 105 编排解锁与评估标尺 | Pending |
| ROUTE-07 | Phase 105 编排解锁与评估标尺 | Pending |
| ROUTE-08 | Phase 105 编排解锁与评估标尺 | Pending |
| ROUTE-09 | Phase 105 编排解锁与评估标尺 | Pending |
| ROUTE-03 | Phase 106 多信号打分函数重构 | Pending |
| ROUTE-04 | Phase 106 多信号打分函数重构 | Pending |
| ROUTE-05 | Phase 106 多信号打分函数重构 | Pending |
| ROUTE-06 | Phase 106 多信号打分函数重构 | Pending |
| ROUTE-01 | Phase 107 分层呈现与链路韧性 | Pending |
| ROUTE-02 | Phase 107 分层呈现与链路韧性 | Pending |
| RELY-02 | Phase 107 分层呈现与链路韧性 | Pending |
| RELY-03 | Phase 107 分层呈现与链路韧性 | Pending |
| RELY-05 | Phase 107 分层呈现与链路韧性 | Pending |
| DEPTH-01 | Phase 108 方案深度 | Pending |
| DEPTH-02 | Phase 108 方案深度 | Pending |
| DEPTH-03 | Phase 108 方案深度 | Pending |
| DEPTH-04 | Phase 108 方案深度 | Pending |
| DEPTH-05 | Phase 108 方案深度 | Pending |
| SPINE-01 | Phase 109 双脊柱合流 | Pending |
| SPINE-02 | Phase 109 双脊柱合流 | Pending |
| RELY-01 | Phase 109 双脊柱合流 | Pending |
| OBS-01 | Phase 110 过程可观测 | Pending |
| OBS-02 | Phase 110 过程可观测 | Pending |
| OBS-03 | Phase 110 过程可观测 | Pending |

**按相位汇总：**

| Phase | Requirements | 数量 |
|-------|--------------|------|
| 105 编排解锁与评估标尺 | RELY-04, ROUTE-07, ROUTE-08, ROUTE-09 | 4 |
| 106 多信号打分函数重构 | ROUTE-03, ROUTE-04, ROUTE-05, ROUTE-06 | 4 |
| 107 分层呈现与链路韧性 | ROUTE-01, ROUTE-02, RELY-02, RELY-03, RELY-05 | 5 |
| 108 方案深度 | DEPTH-01, DEPTH-02, DEPTH-03, DEPTH-04, DEPTH-05 | 5 |
| 109 双脊柱合流 | SPINE-01, SPINE-02, RELY-01 | 3 |
| 110 过程可观测 | OBS-01, OBS-02, OBS-03 | 3 |
| **合计** | | **24** |

**跨类别组合的理由（不按 RELY/ROUTE/DEPTH/SPINE/OBS 机械切分）：**

- **RELY-04 与 ROUTE-07/08/09 同相位**：四者共用同一套分数管线改造（去截断 → 分数分解落 trace → 稳定排序与快照回放 → 离线 harness），且 RELY-04 是解开编排死锁的最短路径、ROUTE-08 是后续所有排序改动的判定标尺，合成一个"解锁性"前置相位。
- **RELY-02/03/05 与 ROUTE-01/02 同相位**：都是"用户看到的东西不再骗人"——分组与跨组标注、降级可见、澄清必达、Stage 1 有界，共享同一批出口面与事件面改造。
- **RELY-01 与 SPINE-01/02 同相位**：RELY-01「方案一定来自完整编排链路」正是移除徒手创作路径（SPINE-02）后的对外表述，两者同一改动的两面，且都必须等 SPINE-01 的替代路径先成立。
