# Roadmap: Friday AI

## Milestones

- 🟡 **v0.17.0 统一知识库与全链路联动（知识收敛 + 完工沉淀闭环 + 容器内置 MCP/Skills）** — Phases 100–104 (planning) — 把多套"知识/经验/沉淀"收敛成统一知识库（单一摄取 + 单一检索），补齐完工沉淀闭环（三链路一致），给编码容器内置 Friday MCP 与 skills — [requirements](./REQUIREMENTS.md) · [research](./research/SUMMARY.md) · [proposal](./knowledge-loop/MILESTONE-PROPOSAL.md)
- ✅ **v0.16.3 外部依赖接入知识体系（可检索 + 知识树 + 关联图谱）** — Phases 96–99 (shipped 2026-07-01) — 把项目外部依赖（`Artifact`：PRD/埋点评审/UI 文档等）接入知识总览/搜索/知识树，并与关键词/业务能力/仓库建关联 — 里程碑审计 tech_debt（12/12 需求满足 / integration_ok；遗留真机/浏览器视觉验收 + 既有范围外测试漂移）见 [audit](./milestones/v0.16.3-MILESTONE-AUDIT.md) — [archive](./milestones/v0.16.3-ROADMAP.md)
- ✅ **v0.16.1 统一 AI 技术方案生成（图编排归一 + 插槽式澄清拼接 + 能力完善）** — Phases 90–95 (shipped 2026-06-28) — 里程碑审计 tech_debt（18/18 需求满足 / integration_ok / 0 gaps / 0 BLOCKER；遗留真机·真实 provider·画布视觉端到端验收 + INFO 欠债）见 [audit](./milestones/v0.16.1-MILESTONE-AUDIT.md) — [archive](./milestones/v0.16.1-ROADMAP.md)
- ✅ **v0.16.0 项目工作区（飞书文档双向同步 + IDE 上下文闭环 + feature list 交付流水线）** — Phases 82–89 (shipped 2026-06-26) — 里程碑审计 tech_debt（37/37 需求满足 / integration_ok；遗留真机/live-platform 验收 + 既有并发测试欠债）见 [audit](./milestones/v0.16.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.16.0-ROADMAP.md)
- ✅ **v0.15.0 项目（交付上下文聚合根）** — Phases 76–81 (shipped 2026-06-26) — 里程碑审计 passed（38/38 需求满足 / integration_ok）见 [audit](./milestones/v0.15.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.15.0-ROADMAP.md)
- ✅ **v0.14.0 可观测性与日志治理** — Phases 71–75 (shipped 2026-06-24) — 里程碑审计 passed（34/34 需求满足 / integration_ok）见 [audit](./milestones/v0.14.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.14.0-ROADMAP.md)
- ✅ **v0.13.0 并发治理与索引体验** — Phases 65–70 (shipped 2026-06-23) — 里程碑审计 tech_debt（11/11 需求满足、integration_ok；遗留既有前端测试失败 + URL 拆段拼接 UI + 真机人工验收）见 [audit](./milestones/v0.13.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.13.0-ROADMAP.md)
- ✅ **v0.12.0 弹性任务底座（durable 任务队列与多副本就绪）** — Phases 60–64 (shipped 2026-06-20) — 里程碑审计 tech_debt（16/16 需求满足、integration_ok；遗留真机/真实平台运行期人工验收）见 [audit](./milestones/v0.12.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.12.0-ROADMAP.md)
- ✅ **v0.11.0 开放与协作** — Phases 56–59 (shipped 2026-06-17) — 里程碑审计 PASS（6/6 需求、INV-5/INV-6 成立）见 [audit](./milestones/v0.11.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.11.0-ROADMAP.md)
- ✅ **v0.10.0 操作审计治理** — Phases 53–55 (shipped 2026-06-17) — [archive](./milestones/v0.10.0-ROADMAP.md)
- ✅ **v0.9.0 SDD / OpenSpec 支持（重型）** — Phases 48–52 (shipped 2026-06-17) — [archive](./milestones/v0.9.0-ROADMAP.md)
- ✅ **v0.8.0 多仓串行编码 → 融合 PR** — Phases 43–47 (shipped 2026-06-17) — [archive](./milestones/v0.8.0-ROADMAP.md)
- ✅ **v0.7.0 方案编排（需求 → 主方案）** — Phases 36–42 (shipped 2026-06-16) — [archive](./milestones/v0.7.0-ROADMAP.md)
- ✅ **v0.6.0 领域脊柱 + 知识图谱补全** — Phases 27–35 (shipped 2026-06-15) — [archive](./milestones/v0.6.0-ROADMAP.md)
- ✅ **v0.5.0 索引检索地基与排除文件** — Phases 22–26 (shipped 2026-06-15) — [archive](./milestones/v0.5.0-ROADMAP.md)
- ✅ **v0.4.0 工作流系统契约重构** — Phases 17–21 (shipped 2026-06-13) — [archive](./milestones/v0.4.0-ROADMAP.md)
- ✅ **v0.3.0 交付知识图谱** — Phases 12–16 (shipped 2026-06-12) — [archive](./milestones/v0.3.0-ROADMAP.md)
- ✅ **v0.2.0 用户身份令牌与 Agent 工具打通** — Phases 6–11 (shipped 2026-06-10) — [archive](./milestones/v0.2.0-ROADMAP.md)
- ✅ **v0.1.0 首启初始化向导** — Phases 1–5 (shipped 2026-06-09) — [archive](./milestones/v0.1.0-ROADMAP.md)

> 历史里程碑详情归档在 `.planning/milestones/`，要点见 `MILESTONES.md`。

## Phases

### 🟡 v0.17.0 统一知识库与全链路联动 (Phases 100–104) — PLANNING

- [x] **Phase 100: 知识收敛基座** - learning case 入图 + 存量回填 + `search_learning_cases` 切向量检索（契约不变）+ MCP 三类产物入图（KNOW-01/02/03）— completed 2026-07-15（4/4 plans，verification passed 5/5）
- [x] **Phase 101: 完工沉淀闭环** - 公共飞书回写 service 三链路接入 + 编码完成自动提炼 learning case + 两个平台 Skill 种子 + PR 后可选 review 沉淀（LOOP-01~05）— completed 2026-07-22（4/4 plans，verification 5/5，review BLOCKER+5 已修复）
- [x] **Phase 102: 知识消费面与对外契约** - 编排召回扩 kinds + Chat 知识读工具 + ProjectStateApi 可检索 + snapshot/skills 文档对齐（KNOW-04/05/06, UNIFY-04）— completed 2026-07-22（3/3 plans，verification 4/4，review HIGH+6 修复中）
- [x] **Phase 103: 编码容器集成** - 任务级短 TTL token + 容器知识 MCP + skills 同源注入 + 工作流派发对齐 pack_project_context（AGENT-01~04）— completed 2026-07-22（4/4 plans）
- [ ] **Phase 104: 工具面收口** - improve/analyze 收敛 delegate_process_runtime + 退役 planning_service 确定性缝 + 清理 plan_orchestration 空壳（UNIFY-01/02/03）

**执行顺序（依赖链）:** 100 → 101 → 102 → 103 → 104。100 是全里程碑枢纽（natural key 规则表决策先于一切入图工作）；101 的回写抽取（LOOP-01/02）可与 100 并行、沉淀（LOOP-03）依赖 100 入图通路；102 依赖 100（learning_case kind 存在、检索已切向量版）；103 放 KNOW 定版后（容器白名单调的正是定版后的检索工具，AGENT-01 短 TTL token 是 AGENT-02 前置）；104 收口放最后（improve/analyze 收敛依赖 102 编排召回扩容先就位，退役工作最后做减 rebase 面）。观测埋点不设独立 phase，按 PITFALLS P8 分配内嵌各 phase 验收标准。

#### Phase Details (v0.17.0)

### Phase 100: 知识收敛基座（learning case 入图 + 检索切换 + MCP 产物入图）

**Goal**: 统一知识库成立——用户与自动链路产出的 learning case、MCP 链路产物（coding plan / 仓库分析 / 执行 trace）全部进入既有 `KnowledgeEntity` + Qdrant `delivery_knowledge`，经 `DeliveryKnowledgeSearchService` 单一检索面可召回，`search_learning_cases` 底层从 token 打分切换为向量检索且对外契约不变。
**Depends on**: Nothing（本里程碑首个 phase；复用 v0.3.0 摄取管线 + v0.16.x 已交付知识体系）
**Requirements**: KNOW-01, KNOW-02, KNOW-03
**Success Criteria** (what must be TRUE):

  1. 用户创建 learning case 后（含存量历史 case 经 backfill 回填），能在 `search_delivery_knowledge` 与 `search_learning_cases` 两处召回同一条 case（统一向量排序，`EntityKind.LEARNING_CASE` 过滤），work_item / tech_plan 关联边可见。
  2. `search_learning_cases` 对外契约不变（`TOOL_SCHEMA_SNAPSHOT` 键集不动、payload 外形一致、hint 参数走 metadata 过滤/rerank 不做摆设、score 语义显式定版），golden set 对照测试（含路径/symbol 类查询）作为验收门通过，token 打分退役。
  3. 用户走 MCP 建的 coding plan / 仓库分析 / 执行 trace 可被 `search_delivery_knowledge` 召回，且从 plan 实体沿边可达 execution 与 work_item（plan→execution→PR 端到端自动化断言）；与 chat `coding_plan` 实体经 natural key 规则表显式关联不重复入图。
  4. 重复摄取同一对象幂等（实体数不变、版本翻转正确）；Qdrant 不可用时检索 fail-soft 返回空结果不 500。
  5. 新召回路径写 `RetrievalTrace` 并上报召回条数/耗时/score（MCP 链 + Chat 链两条都覆盖）。

**Pitfalls**: P1 检索切换回归/契约漂移（normalizer/backfill/读切换同 phase 闭环 + golden set 验收门）；P7 实体去重/关联错误（natural key 规则表扩表为前置 task、锚照抄 `mcp_plan.py`）；P8 观测欠债（RetrievalTrace 断言内嵌验收）。
**Plans**: 4 plans

Plans:

- [ ] 100-01-PLAN.md — 地基：natural key 规则表扩表 + EntityKind.LEARNING_CASE migration + vector_recall kind 过滤吞参修复（Wave 1）
- [ ] 100-02-PLAN.md — KNOW-01：learning_case normalizer + create 投递钩子 + 幂等重摄测试（Wave 2）
- [ ] 100-03-PLAN.md — KNOW-03：MCP 三 normalizer + 5 写入点投递 + plan→execution→work_item 边 E2E（Wave 2）
- [ ] 100-04-PLAN.md — KNOW-02：search_learning_cases 向量切换（契约不变/token 退役/fail-soft）+ backfill 命令 + golden set 验收门 + RetrievalTrace（Wave 3）

### Phase 101: 完工沉淀闭环（公共回写 + 自动提炼 + Skill 种子）

**Goal**: 任一链路（工作流 / Chat / MCP）编码完成后业务侧一致可见、经验自动沉淀——飞书回写抽为公共 service 三链路统一接入，编码成功完成自动提炼 learning case 入统一知识库，平台内置编码前调研与完工沉淀两个多步 Skill，PR 后可选轻量 review 沉淀。
**Depends on**: Phase 100（LOOP-03 沉淀产物需经 100 的入图通路可检索；LOOP-01/02 回写抽取本身无依赖，可与 100 并行推进）
**Requirements**: LOOP-01, LOOP-02, LOOP-03, LOOP-04, LOOP-05
**Success Criteria** (what must be TRUE):

  1. 工作流跑完 `ai_coding`（MR 已知锚点）后，飞书工作项自动出现结果评论（与 MCP `write_back` 同格式）；Chat 编码建 PR 后若能反查到工作项三元组同样回写；MCP 链路改薄包装后行为零回归（含 `write_back` 开关与 retry_state 语义）。
  2. 存量工作流（节点 config 无新键 / 未绑定 work_item）升级后行为零变化（fallback 守门用例 + 升级说明）；回写失败记 `writeback_skipped`/`writeback_failed` 结构化事件跳过，不重试轰炸飞书 API。
  3. 任一链路编码成功完成后自动产生至多一条 learning case 且可被统一检索到；同一 TaskResult 回调重入只产一条（幂等键）；失败/取消任务不产正向 case，质量门槛不足的提炼产物走显式 REJECT 路径并计数；系统级开关可秒关。
  4. `pre_coding_research` / `post_coding_capture` 两个平台 Skill（RemoteTool `Source.SKILL` 种子）在 `/api/tools/execute/` 可调、步级 trace 完整；PR 创建后可选触发轻量 review 并沉淀结论为 learning case（可配置默认关）。
  5. 新增 LLM 调用点的 `call_source`（提炼、review 各一）先登记 LOGGING-SPEC §4.1，`ModelUsageRecord` 可按 source 聚合；回写/沉淀事件带 `initiated_by_user_id`（无则 `system`）。

**Pitfalls**: P2 自动沉淀噪音/成本失控（幂等键 + 准入门槛 + call_source 登记与功能同 phase，绝不"先跑通后补"）；P3 回写默认值改变存量行为（"模板默认开"与"存量 fallback"区分为设计输入）；P8 观测欠债。
**Plans**: 4 plans

Plans:

- [x] 101-01-PLAN.md — LOOP-01：CompletionWritebackService 公共回写抽取 + MCP 薄包装零回归（Wave 1）
- [x] 101-02-PLAN.md — LOOP-03 核心：call_source 登记先行 + McpLearningCase migration + 提炼管线（质量门/REJECT/幂等/开关）（Wave 1）
- [x] 101-03-PLAN.md — LOOP-02/03 锚点：三元组反查器 + workflow write_back 配置与存量 fallback 守门 + chat/MCP 接线 + 前端同步（Wave 2）✅ 2026-07-22
- [x] 101-04-PLAN.md — LOOP-04/05：平台 Skill 种子 + 步级 trace + PR 后可选 review 沉淀（Wave 3）

### Phase 102: 知识消费面与对外契约（编排召回扩容 + Chat 工具 + snapshot/skills 对齐）

**Goal**: 统一知识库的消费面补齐——方案编排召回覆盖项目沉淀与历史经验，Chat 对话能主动读知识，IDE 上报的 API 清单可语义检索，对外工具契约（schema snapshot + `@friday-ai-codes/skills` 文档）与新行为完整对齐。
**Depends on**: Phase 100（`learning_case` kind 已存在、检索已切向量版才有扩容与文档对齐的意义）
**Requirements**: KNOW-04, KNOW-05, KNOW-06, UNIFY-04
**Success Criteria** (what must be TRUE):

  1. 方案编排 recalling 阶段能召回 `document` 与 `learning_case` 两类沉淀（`RECALL_ENTITY_KINDS` 可配置默认开、每 kind 限额守 token 预算），召回埋点（RetrievalTrace + 条数/耗时/score）可见。
  2. Chat 对话可经白名单新增的 `search_learning_cases` / `read_project_doc` / `search_project_context` 三个工具主动读知识（复用既有 service 薄封装，权限 fail-closed）。
  3. IDE 上报 `ProjectStateApi` 后，`search_project_context` 能命中该 API 清单（经 STATE 文档物化路径入向量库）。
  4. `TOOL_SCHEMA_SNAPSHOT` 覆盖全部注册工具（补 `report_project_state`），快照测试全绿且含"注册工具 == snapshot 键集合"防漏断言；`@friday-ai-codes/skills` 文档与新行为对齐（learning case 向量检索语义、`reverse_lookup_requirements` 收录进 friday-code 技能路由）。

**Pitfalls**: P5 skills 双源漂移之文档面（skill 引用工具名 ∈ snapshot 的 grep 测试）；P8 观测欠债（召回埋点内嵌验收）；Performance Trap 编排召回 token 预算膨胀（每 kind 限额）。
**Plans**: 3 plans

Plans:

- [ ] 102-01-PLAN.md — KNOW-04：编排召回扩 5 kinds（settings 可配置 + 每 kind 限额 + RetrievalTrace 埋点 + 测试更新）（Wave 1）
- [ ] 102-02-PLAN.md — KNOW-05/06：Chat 三个知识读工具（薄封装 + 白名单 + chat 链 trace）+ ProjectStateApi 物化断链修复（upsert 钩子 + STATE normalizer live 内容 + 验收链测试）（Wave 1）
- [ ] 102-03-PLAN.md — UNIFY-04：snapshot 补 report_project_state + 注册==snapshot 守卫 + skills 工具名 ⊆ snapshot grep 守卫 + friday-memory/friday-code 文档对齐（Wave 1）

### Phase 103: 编码容器集成（短 TTL token + 容器知识 MCP + skills 注入 + 上下文对齐）

**Goal**: 编码容器不再是"知识贫民区"——三条派发链路统一铸造任务级短 TTL token，容器内代理经进程内 SDK MCP server 主动查 Friday 知识（服务端 HTTP 工具面复用、权限/排除/脱敏天然继承），friday-code/friday-memory skills 同源注入容器，工作流派发对齐 `pack_project_context`。
**Depends on**: Phase 100（容器白名单调用的检索工具行为需先定版，避免对着会变的契约集成两次）；AGENT-01 短 TTL token 是 AGENT-02 容器 MCP 的前置
**Requirements**: AGENT-01, AGENT-02, AGENT-03, AGENT-04
**Success Criteria** (what must be TRUE):

  1. 三条派发链路（workflow / chat / MCP）派发编码任务时为发起用户铸造任务级短 TTL token：明文仅在 dispatch 内存生成后直进容器 env、DB 只存 sha256、`expires_at`=任务 timeout+余量、任务终态回调吊销（PAT-02 不违反；显式推翻 PATX-04 搁置已记 Key Decisions）。
  2. 容器内编码代理能主动调用白名单只读知识工具（`search_rag_chunks` / `search_delivery_knowledge` / `search_learning_cases` 等 7 个），日志可见工具调用 + RetrievalTrace 经 run/task 关联键可查；被排除文件容器视角不可见（v0.5 六面加第七面回归测试）。
  3. env 三要素任一为空时整体降级不挂（存量任务零回归）；挂载后 Bash/Edit/Write 等内建编码工具仍可用（`allowed_tools` 合并收口单一构造函数 + 专项测试）；per-task 配额/超时生效且配额用尽返回 agent 可理解文案；容器产物（diff/PR/日志）无 `friday_pat_` 前缀泄漏。
  4. 容器内代理可见并遵循 friday-code / friday-memory skills（镜像构建期从 `skills/skills/` 同源 COPY + 运行时注入 `.claude/skills/` 同名不覆盖），hash 一致性测试通过防双源漂移。
  5. 工作流路径派发的编码容器 prompt 含 `pack_project_context` 输出（与 Chat 路径一致，`_dispatch_wave` 层按 (project, branch) 解析一次逐仓复用）；容器 MCP 转调入口纳入 QPS/错误率/时长观测。

**Pitfalls**: P4 容器 MCP 四险（白名单/配额/PAT 内存化/allowed_tools 合并测试/观测埋点全套同 phase）；P5 skills 双源漂移（hash 一致性 CI 测试）；P8 观测欠债（QPS 独立统计与功能同 phase 上线）。
**Plans**: 4 plans

Plans:

- [x] 103-01-PLAN.md — AGENT-01 任务级短 TTL token：kind/session_id 迁移 + mint/revoke service + 三链接线（替换 user_pat_plaintext 死通道）+ 终态吊销 + 泄漏防线（Wave 1）
- [x] 103-02-PLAN.md — AGENT-02 容器知识 MCP：knowledge_tools.py 7 工具白名单 + 配额 + allowed_tools 收口 + X-Friday-Session-Id 关联 + 第七面排除回归（Wave 1）
- [x] 103-03-PLAN.md — AGENT-03 skills 同源注入：sync 脚本 + assets 入库 + Dockerfile COPY + 运行时同名不覆盖注入 + hash 一致性测试（Wave 1）
- [x] 103-04-PLAN.md — AGENT-04 工作流上下文对齐：helper 上提 packer + _dispatch_wave 按 project 解析一次逐仓复用 + prompt/env 注入（Wave 2，依赖 103-01）✅ 2026-07-22

### Phase 104: 工具面收口（improve/analyze 收敛 + 确定性缝退役 + 端到端验收）

**Goal**: MCP 工具面收口到统一编排——`improve_coding_plan` / `analyze_repository` 收敛到 `delegate_process_runtime`，`planning_service.py` 确定性缝退役、`plan_orchestration/` 空壳删除、全仓残留引用清零，并完成"四处检索同一 learning case"的里程碑端到端验收。
**Depends on**: Phase 102（编排召回扩容先就位，收敛后 improve/analyze 的工具质量才不降级）；退役工作放最后减少与 KNOW/LOOP 改动面的 rebase 冲突
**Requirements**: UNIFY-01, UNIFY-02, UNIFY-03
**Success Criteria** (what must be TRUE):

  1. 用户经 `improve_coding_plan` 改版方案时走统一编排（携带 feedback 的编排重跑产新 version），trace 中可见编排 session；对外契约（同步 vs 会话式）作为本 phase 首个 task 定版并写进 schema 描述，Cursor 侧调用不超时/不挂起。
  2. `analyze_repository` 收敛且分析产物作为编排输入证据实际被消费（不留无人消费的空转工具）；`mcp_tools/planning_service.py` 删除，仍被引用的 helper（如 `map_canonical_to_coding_plan`）随迁，相关测试迁移不失覆盖。
  3. `rg planning_service` 全仓零残留引用；`services/plan_orchestration/` 空壳目录删除 + 文档/注释残留引用清理；被 patch 的 mock target 全部可 import（无 stale target 假通过）。
  4. 里程碑端到端验收成立：同一条 learning case 在 Chat 工具 / 编排召回 / MCP `search_learning_cases` / 容器知识 MCP 四处均可检索到（统一排序）。

**Pitfalls**: P6 收口断裂（契约先定、`rg planning_service` 引用清单为第一个 task、patch target 可 import 断言）。
**Plans**: 3 plans

Plans:

- [x] 104-01-PLAN.md — UNIFY-01 improve 收敛 delegate：引用清单 + 契约定版进 schema 描述 + map_canonical 随迁 + snapshot 双修（improve/create session_id/status）+ 测试迁 fake delegate（Wave 1）✅ 2026-07-22
- [ ] 104-02-PLAN.md — UNIFY-02/03 analyze 随迁 repository_analysis_service + extra_evidence 编排消费接线 + planning_service.py 删除 + plan_orchestration 空壳/docs 清零 + stale patch target 守卫（Wave 2，依赖 104-01）
- [ ] 104-03-PLAN.md — 里程碑端到端验收：同一 learning case 四面检索（Chat 工具/编排召回/MCP view/容器链同 URL 契约）+ MCP 与 Chat top-1 统一排序断言（Wave 3，依赖 104-02）

<details>
<summary>✅ v0.16.3 外部依赖接入知识体系（可检索 + 知识树 + 关联图谱）(Phases 96–99) — SHIPPED 2026-07-01 — 审计 tech_debt</summary>

- [x] Phase 96: 外部依赖进检索与总览 (5/5 plans) — 全类型工件登记可发现 + 搜索命中标类型可跳查看 + 知识总览加「交付文档」区块（KDEP-01/02/03）— completed 2026-07-01
- [x] Phase 97: 交付文档知识树视图 (3/3 plans) — `/knowledge` 树页并行「交付文档」树（项目→类型→工件）+ 树内搜索/查看 + 后端树数据 API（KDEP-04/05/06）— completed 2026-07-01
- [x] Phase 98: 工件↔仓库/能力/关键词关联 (3/3 plans) — RepoRouterV2 路由工件正文落 RELATES_TO 边 + 同步 verified RepoAssociation + 关联可查询（KDEP-07/08/09）— completed 2026-07-01
- [x] Phase 99: 关联可视化与交叉入口 (4/4 plans) — 星图纳入 artifact 节点/边 + 知识实体图/详情展示关联 + 作战室↔知识闭环（KDEP-10/11/12）— completed 2026-07-01

完整阶段详情见 [milestones/v0.16.3-ROADMAP.md](./milestones/v0.16.3-ROADMAP.md)；里程碑审计 tech_debt（12/12 需求满足 / integration_ok / 0 gaps / 0 BLOCKER；遗留真机·真实 provider·浏览器视觉端到端验收 + 既有范围外测试漂移）见 [milestones/v0.16.3-MILESTONE-AUDIT.md](./milestones/v0.16.3-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.16.1 统一 AI 技术方案生成（图编排归一 + 插槽式澄清拼接 + 能力完善）(Phases 90–95) — SHIPPED 2026-06-28 — 审计 tech_debt</summary>

- [x] Phase 90: 澄清能力层 (4/4 plans) — CLARIFY-01/02/03 — completed 2026-06-27
- [x] Phase 91: 澄清出口面 + 回流 resume (5/5 plans) — CLARIFY-04/05/06/07 — completed 2026-06-27
- [x] Phase 92: 插槽系统（后端） (3/3 plans) — SLOT-01/02 — completed 2026-06-27
- [x] Phase 93: 插槽编辑器（前端） (7/7 plans) — SLOT-03/04 — completed 2026-06-27
- [x] Phase 94: 入口统一 (5/5 plans) — UNIFY-01~06 — completed 2026-06-27
- [x] Phase 95: 拆分完善 (3/3 plans) — DECOMP-01 — completed 2026-06-27

完整阶段详情见 [milestones/v0.16.1-ROADMAP.md](./milestones/v0.16.1-ROADMAP.md)；里程碑审计 tech_debt（18/18 需求满足 / integration_ok / 0 gaps / 0 BLOCKER；遗留真机·真实 provider·画布视觉端到端验收 + INFO 欠债）见 [milestones/v0.16.1-MILESTONE-AUDIT.md](./milestones/v0.16.1-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.16.0 项目工作区（飞书文档双向同步 + IDE 上下文闭环 + feature list 交付流水线）(Phases 82–89) — SHIPPED 2026-06-26 — 审计 tech_debt</summary>

- [x] Phase 82: 项目工作区实体 + 权限翻转 + 飞书文件夹 + 5 文件 (5/5 plans) — WS-01~04, DOC-01~06 — completed 2026-06-26
- [x] Phase 83: 飞书文档双向同步引擎 (6/6 plans) — SYNC-01~06 — completed 2026-06-26
- [x] Phase 84: 项目工作台前端 2.0 (5/5 plans) — WB-01~05 — completed 2026-06-26
- [x] Phase 85: 项目上下文可读 + 分支绑定 (4/4 plans) — CTX-01/02, BIND-01/02 — completed 2026-06-27
- [x] Phase 86: IDE 上下文闭环（hooks） (5/5 plans) — HOOK-01~04 — completed 2026-06-27
- [x] Phase 87: 看板拆分节点 + 群 + 流式卡片 (4/4 plans) — BOARD-01/02 — completed 2026-06-27
- [x] Phase 88: 智能业务关联仓库 (5/5 plans) — REPO-01/02 — completed 2026-06-27
- [x] Phase 89: 技术方案深化 + 建分支绑项目 (4/4 plans) — PLAN-01~04 — completed 2026-06-27

完整阶段详情见 [milestones/v0.16.0-ROADMAP.md](./milestones/v0.16.0-ROADMAP.md)；里程碑审计 tech_debt（37/37 需求、integration_ok；遗留真机/live-platform 验收 + 既有并发测试欠债）见 [milestones/v0.16.0-MILESTONE-AUDIT.md](./milestones/v0.16.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.15.0 项目（交付上下文聚合根）(Phases 76–81) — SHIPPED 2026-06-26 — 审计 passed</summary>

- [x] Phase 76: 命名腾挪（Project→Space 重构前置） (1/1 plans) — RENAME-01/02 — completed 2026-06-25
- [x] Phase 77: 项目聚合根 + 身份映射 + 成员协作 (1/1 plans) — PROJ-01~05, IDENT-01, MEMBER-01~03 — completed 2026-06-25
- [x] Phase 78: 飞书触发建项目 + 看板枚举 + 工作项组合 (1/1 plans) — FSPROJ-01~03, COMPOSE-01/02 — completed 2026-06-25
- [x] Phase 79: 工件/依赖项（可配置类型 + 实例 + RAG）+ 知识关联 (1/1 plans) — ARTIFACT-01~05, KLINK-01/02 — completed 2026-06-26
- [x] Phase 80: 项目记忆 + MR 实体 + 上下文召回接入 Web 会话 (1/1 plans) — MEM-01~04, RECALL-01~03, MR-01/02 — completed 2026-06-26
- [x] Phase 81: Cursor 回流 + 前端项目工作台 (1/1 plans) — CURSOR-01~03, UI-01~03 — completed 2026-06-26

完整阶段详情见 [milestones/v0.15.0-ROADMAP.md](./milestones/v0.15.0-ROADMAP.md)；里程碑审计 passed（38/38 需求、integration_ok）见 [milestones/v0.15.0-MILESTONE-AUDIT.md](./milestones/v0.15.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.14.0 可观测性与日志治理 (Phases 71–75) — SHIPPED 2026-06-24 — 审计 passed</summary>

- [x] Phase 71: 可观测性地基（用户上下文贯穿 + 系统日志治理） (5/5 plans) — CTX-01/02, LOG-01~08 — completed 2026-06-24
- [x] Phase 72: 调用数据采集（AI/LLM + 召回 + 请求入口） (4/4 plans) — RATE-01/02, RAG-01/02, SLA-02/03/04 — completed 2026-06-24
- [x] Phase 73: 快照·趋势·查询 API (3/3 plans) — SNAP-01~05, RATE-03, SLA-01, QUERY-01/02 — completed 2026-06-24
- [x] Phase 74: 告警引擎与通知（阈值 + 告警事件 + 邮件） (3/3 plans) — ALERT-01/02/03 — completed 2026-06-24
- [x] Phase 75: 运维大盘前端 + 规范固化 (5/5 plans) — UI-01~04, SPEC-01 — completed 2026-06-24

完整阶段详情见 [milestones/v0.14.0-ROADMAP.md](./milestones/v0.14.0-ROADMAP.md)；里程碑审计 passed（34/34 需求、integration_ok）见 [milestones/v0.14.0-MILESTONE-AUDIT.md](./milestones/v0.14.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.13.0 并发治理与索引体验 (Phases 65–70) — SHIPPED 2026-06-23 — 审计 tech_debt</summary>

- [x] Phase 65: AI 对话串流隔离修复 (1/1 plans) — STREAM-01 — completed 2026-06-23
- [x] Phase 66: 默认禁用 LSP（仅 tree-sitter） (1/1 plans) — LSP-01 — completed 2026-06-23
- [x] Phase 67: 并发治理（槽位锁池 / provider 限流 / 容器上限） (3/3 plans) — CONC-01/02/03 — completed 2026-06-23
- [x] Phase 68: 实时进度统一 + 进度条修复 (1/1 plans) — PROG-01/02 — completed 2026-06-23
- [x] Phase 69: 批量加仓 + 全部更新索引（超管） (1/1 plans) — BATCH-01/02 — completed 2026-06-23
- [x] Phase 70: access token / 密钥提供方重构（FK） (1/1 plans) — TOKEN-01/02 — completed 2026-06-23

完整阶段详情见 [milestones/v0.13.0-ROADMAP.md](./milestones/v0.13.0-ROADMAP.md)；里程碑审计 tech_debt（11/11 需求、integration_ok）见 [milestones/v0.13.0-MILESTONE-AUDIT.md](./milestones/v0.13.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.12.0 弹性任务底座（durable 任务队列与多副本就绪）(Phases 60–64) — SHIPPED 2026-06-20</summary>

- [x] Phase 60: durable 底座地基 (4/4 plans) — DURABLE-01~04 — completed 2026-06-19
- [x] Phase 61: 迁移 index/graph + 收口 ResumableTask (4/4 plans) — MIGRATE-01/02, IDEMP-01 — completed 2026-06-19
- [x] Phase 62: 爬取+入库 durable 队列 + PageIndex 接入 (3/3 plans) — CRAWL-01/02, PAGEIDX-01 — completed 2026-06-20
- [x] Phase 63: 部署硬化 + 外部副作用 fencing (3/3 plans) — DEPLOY-01~03, IDEMP-02 — completed 2026-06-20
- [x] Phase 64: runner k8s Job executor (2/2 plans) — RUNNER-01/02 — completed 2026-06-20

完整阶段详情见 [milestones/v0.12.0-ROADMAP.md](./milestones/v0.12.0-ROADMAP.md)；里程碑审计 tech_debt（16/16 需求、integration_ok）见 [milestones/v0.12.0-MILESTONE-AUDIT.md](./milestones/v0.12.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.11.0 开放与协作 (Phases 56–59) — SHIPPED 2026-06-17 — 审计 PASS</summary>

- [x] Phase 56: compat 内部工具调用 → progress/trace 事件透出 (2/2 plans) — TRACE-01, TRACE-02 — completed 2026-06-17
- [x] Phase 57: Anthropic 兼容端点 `/v1/messages` (2/2 plans) — ANTHROPIC-01, ANTHROPIC-02 — completed 2026-06-17
- [x] Phase 58: 飞书原生流式卡片（CardKit）(2/2 plans) — CARD-01 — completed 2026-06-17
- [x] Phase 59: 工作流自动建群节点 (2/2 plans) — GROUP-01 — completed 2026-06-17

里程碑审计 PASS（6/6 需求、INV-5/INV-6 成立）见 [milestones/v0.11.0-MILESTONE-AUDIT.md](./milestones/v0.11.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.10.0 操作审计治理 (Phases 53–55) — SHIPPED 2026-06-17</summary>

完整阶段详情见 [milestones/v0.10.0-ROADMAP.md](./milestones/v0.10.0-ROADMAP.md)。

</details>

<details>
<summary>✅ v0.9.0 SDD / OpenSpec 支持（重型）(Phases 48–52) — SHIPPED 2026-06-17</summary>

完整阶段详情见 [milestones/v0.9.0-ROADMAP.md](./milestones/v0.9.0-ROADMAP.md)。

</details>

<details>
<summary>✅ v0.8.0 多仓串行编码 → 融合 PR (Phases 43–47) — SHIPPED 2026-06-17</summary>

完整阶段详情见 [milestones/v0.8.0-ROADMAP.md](./milestones/v0.8.0-ROADMAP.md)。

</details>

<details>
<summary>✅ v0.7.0 方案编排（需求 → 主方案）(Phases 36–42) — SHIPPED 2026-06-16</summary>

完整阶段详情见 [milestones/v0.7.0-ROADMAP.md](./milestones/v0.7.0-ROADMAP.md)。

</details>

<details>
<summary>✅ v0.6.0 领域脊柱 + 知识图谱补全 (Phases 27–35) — SHIPPED 2026-06-15</summary>

完整阶段详情见 [milestones/v0.6.0-ROADMAP.md](./milestones/v0.6.0-ROADMAP.md)。

</details>

## Progress

里程碑 v0.1.0–v0.16.3（Phases 1–99）均已交付。**🟡 当前立项：v0.17.0 统一知识库与全链路联动（Phases 100–104，5 阶段 / 19 需求 KNOW·LOOP·AGENT·UNIFY）** —— 把多套"知识/经验/沉淀"收敛成统一知识库（单一摄取 `knowledge/sources/` + 单一检索 `DeliveryKnowledgeSearchService`），补齐完工沉淀闭环（编码完成 → 经验入库 + 飞书回写，三链路一致），给编码容器内置 Friday 知识 MCP 与 skills。规划/调研已就绪（REQUIREMENTS + research 五件套 + knowledge-loop/MILESTONE-PROPOSAL），**待 `$gsd-plan-phase 100`（或 `$gsd-autonomous` 跑整个里程碑）**。

| Phase | Requirements | Plans Complete | Status | Completed |
|-------|--------------|----------------|--------|-----------|
| 100. 知识收敛基座 | KNOW-01/02/03 | 4/4 | ✅ Complete | 2026-07-15 |
| 101. 完工沉淀闭环 | LOOP-01~05 | 4/4 | Complete   | 2026-07-22 |
| 102. 知识消费面与对外契约 | KNOW-04/05/06, UNIFY-04 | 0/TBD | Not started | - |
| 103. 编码容器集成 | AGENT-01~04 | 3/4 | In Progress|  |
| 104. 工具面收口 | UNIFY-01/02/03 | 1/3 | In progress | 104-01 ✅（UNIFY-01 improve 收敛 delegate + 契约定版 + snapshot 双修） |

**Coverage:** 19/19 需求全部映射，无孤儿、无重复。

> 说明：沿用「续号 Phase」惯例（上一里程碑 v0.16.3 收官 Phase 99 → 本里程碑 100–104）。Phase 103 的短 TTL token 决策（显式推翻 PATX-04 搁置）已在立项时定版并记入 PROJECT.md Key Decisions。

v0.16.3 遗留的真机·真实 provider·浏览器视觉端到端人工验收见 [audit](./milestones/v0.16.3-MILESTONE-AUDIT.md)；v0.16.1 遗留人工验收（10 项）见 [audit](./milestones/v0.16.1-MILESTONE-AUDIT.md) §4。

各历史里程碑详情归档在 `.planning/milestones/`，要点见 `MILESTONES.md`。

---
*Previous milestones archived in .planning/milestones/*
