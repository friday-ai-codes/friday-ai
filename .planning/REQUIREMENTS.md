# Requirements: Friday AI v0.17.0 统一知识库与全链路联动

**Defined:** 2026-07-15
**Core Value:** 让"产出→入图→召回→更好的产出"的知识飞轮真正转起来：任一链路的产物都可被任一链路检索到，任一链路编码完成都自动沉淀经验并回写业务侧，编码容器天然带着 Friday 的知识工具与 skills 干活。
**调研基线:** `.planning/knowledge-loop/MILESTONE-PROPOSAL.md`（断点调研）+ `.planning/research/`（STACK/FEATURES/ARCHITECTURE/PITFALLS/SUMMARY）

## v0.17.0 Requirements

### KNOW 统一知识库（收敛 + 消费面）

- [ ] **KNOW-01**: 用户创建的 learning case 自动进入统一知识库——新增 `EntityKind.LEARNING_CASE` 字面值（+CHECK 约束 migration）与 `knowledge/sources/learning_case.py` normalizer（work_item 锚双事件 + RELATES_TO/REFERENCES 边，锚缺料降级单事件），`create_learning_case` 写库后经 `aschedule_ingestion` 投递（INV-6 唯一通路）
- [ ] **KNOW-02**: 用户经 `search_learning_cases` 检索经验时走统一向量检索——底层切换为 `DeliveryKnowledgeSearchService.search_similar(entity_kinds=["learning_case"])` 并按 source_id 回捞行渲染既有 payload 外形，对外契约（`TOOL_SCHEMA_SNAPSHOT` 键）不变，token 打分退役；附对照测试（既有用例召回集合非空 + 存量 case 回填入图）
- [ ] **KNOW-03**: MCP 链路产物（`McpCodingPlan` / `McpRepositoryAnalysis` / `McpCodingExecutionTrace`）可被 `search_delivery_knowledge` 召回——三个 normalizer + 各写入点投递，与 chat `coding_plan` / `task_result` 实体经 natural key 去重关联（不重复入图）
- [ ] **KNOW-04**: 方案编排 recalling 阶段能召回项目沉淀与历史经验——`recall_adapter` 的 `RECALL_ENTITY_KINDS` 扩 `document` 与 `learning_case`（可配置，默认开），召回埋点（RetrievalTrace + 条数/耗时/score）先行
- [ ] **KNOW-05**: Chat 对话能主动读知识——白名单新增 `search_learning_cases` / `read_project_doc` / `search_project_context` 三个薄封装工具（复用既有 service，权限 fail-closed）
- [ ] **KNOW-06**: `ProjectStateApi`（IDE 上报的 API 清单）可被语义检索——经 STATE 文档物化路径确认入向量库并可召回（验收：上报后 `search_project_context` 能命中）

### LOOP 完工沉淀闭环（三链路一致）

- [ ] **LOOP-01**: 飞书回写能力抽为公共服务——`delivery/services/coding_completion.py` `CompletionWritebackService`（工作项评论 + 可选文档 append，入参中性化），MCP `_write_results_back` 改薄包装（含 `write_back` 开关与 retry_state 语义零回归）
- [ ] **LOOP-02**: 工作流与 Chat 编码完成后业务侧可见——workflow `AICodingNode._finalize_and_notify`（MR 后锚点）与 chat `coding_graph.create_pr_or_skip_node` 接入公共回写（节点/会话开关，模板默认开；取不到工作项三元组 no-op fail-soft；三元组经 `pr_cross_reference` 追溯链反查）
- [ ] **LOOP-03**: 任一链路编码完成自动沉淀经验——LLM 从 TaskResult/diff/plan 提炼 outcome/root_cause/solution 落 `McpLearningCase`（FK 放松允许无 technical_plan）并入图；新 `call_source=learning_case_extraction` 登记 LOGGING-SPEC §4.1；质量门槛（最小信息量校验 + 失败/取消任务不沉淀 + 每任务至多一条）；best-effort 绝不阻断主流程；带 `initiated_by_user_id`（无则 system）
- [ ] **LOOP-04**: 平台内置两个多步 Skill（RemoteTool `Source.SKILL` 种子）——`pre_coding_research`（route_repositories→search_rag_chunks→search_delivery_knowledge→search_learning_cases）与 `post_coding_capture`（summarize_branch→create_learning_case→report_project_knowledge），在 `/api/tools/execute/` 可调、步级 trace 完整
- [ ] **LOOP-05**: PR 创建后可选触发轻量 review 并沉淀结论为 learning case（可配置默认关；范围=能跑通+沉淀，不做评审 UI/规则引擎）

### AGENT 编码容器内置 MCP/Skills + 上下文对齐

- [ ] **AGENT-01**: 派发编码任务时为发起用户铸造任务级短 TTL token——明文仅在 dispatch 内存生成后直进容器 env，DB 只存 sha256，`expires_at`=任务 timeout+余量，任务终态回调吊销；三条派发链路（workflow/chat/MCP）统一覆盖（显式推翻 PATX-04 搁置，PAT-02 不违反：明文不落盘、不从 DB 反取）
- [ ] **AGENT-02**: 容器内编码代理可主动查 Friday 知识——`task/core/knowledge_tools.py` 进程内 SDK MCP server（HTTP POST `/api/mcp/tools/<name>/` + Bearer PAT），白名单读工具（search_rag_chunks/grep_repository/get_repository_file/search_delivery_knowledge/search_learning_cases/search_project_context/lookup_project_by_branch）；env 三要素任一为空整体降级不挂（零回归）；handler return-not-raise + 60s 超时 + 脱敏；服务端排除文件 fail-closed 天然继承；新请求入口纳入 QPS/错误率观测
- [ ] **AGENT-03**: 容器内代理可见 Friday skills——task 镜像构建期从 `skills/skills/{friday-code,friday-memory}` 同源 COPY，运行时注入 `<workspace>/.claude/skills/`（同名不覆盖仓库自带）；hash 一致性测试防双源漂移
- [ ] **AGENT-04**: 工作流派发的编码容器带项目上下文——`AICodingNode` dispatch 前 prepend `pack_project_context`（项目定位：ProjectBranch 反查 + work_item 关联 fallback；`_dispatch_wave` 层按 (project,branch) 解析一次逐仓复用；共享 `_prepend_project_context` helper 上提避免 workflow import chat）

### UNIFY 工具面收口

- [ ] **UNIFY-01**: `improve_coding_plan` 走统一编排——View 改 `delegate_process_runtime`（改版语义=携带 feedback 的编排重跑产新 version），trace 中可见编排 session
- [ ] **UNIFY-02**: `analyze_repository` 收敛且确定性缝退役——分析产物作为编排输入证据挂接；`mcp_tools/planning_service.py` 删除（`map_canonical_to_coding_plan` 等仍被引用的 helper 随迁），相关测试迁移不失覆盖
- [ ] **UNIFY-03**: `services/plan_orchestration/` 空壳目录删除 + 全仓文档/注释残留引用清理
- [ ] **UNIFY-04**: 对外工具契约完整——`TOOL_SCHEMA_SNAPSHOT` 补 `report_project_state`，快照测试全绿；`@friday-ai-codes/skills` 文档对齐新行为（learning case 向量检索、`reverse_lookup_requirements` 收录进 friday-code 技能路由）

## Future Requirements（明确后置）

- `chat.CodingPlan` 与 `McpCodingPlan` 合并 canonical `ArtifactVersion` — 单独立项（改动面大）
- review 产品化（评审 UI / 规则引擎 / 门禁） — Qodo 级体量
- 会话内 sidecar 记忆提取（Cursor Memories 同型） — 需旁路小模型基建
- 记忆 consolidation / decay 自动策展 — 先靠 bi-temporal 失效 + 人工 supersede 过渡
- 对外知识开放平台（配额/租户/计费）

## Out of Scope

| 项 | 理由 |
|----|------|
| 为 learning case 新建 Qdrant collection / 平行检索服务 | 与统一排序目标冲突；锁定"不新建存储" |
| Interaction Ledger 反哺检索 | 规范明确指标/留痕/日志分离，保持纯审计 |
| 图片/UI 稿多模态召回 | 既有 v2 backlog（PROJX-01） |
| 原生定时触发恢复 | 与本里程碑无关，外部 cron→webhook 可用 |
| 回写/沉淀挂容器回调 `_handle_completed` | 回调时刻无 MR 结果 + 5xx 重试风暴风险；锚点必须在"MR 已知"之后 |

## Traceability

<!-- Filled by roadmapper (2026-07-15): 19/19 需求映射到 Phases 100–104，无孤儿、无重复 -->

| REQ-ID | Phase | Status |
|--------|-------|--------|
| KNOW-01 | Phase 100 | Pending |
| KNOW-02 | Phase 100 | Pending |
| KNOW-03 | Phase 100 | Pending |
| KNOW-04 | Phase 102 | Pending |
| KNOW-05 | Phase 102 | Pending |
| KNOW-06 | Phase 102 | Pending |
| LOOP-01 | Phase 101 | Pending |
| LOOP-02 | Phase 101 | Pending |
| LOOP-03 | Phase 101 | Pending |
| LOOP-04 | Phase 101 | Pending |
| LOOP-05 | Phase 101 | Pending |
| AGENT-01 | Phase 103 | Pending |
| AGENT-02 | Phase 103 | Pending |
| AGENT-03 | Phase 103 | Pending |
| AGENT-04 | Phase 103 | Pending |
| UNIFY-01 | Phase 104 | Pending |
| UNIFY-02 | Phase 104 | Pending |
| UNIFY-03 | Phase 104 | Pending |
| UNIFY-04 | Phase 102 | Pending |

---
*Requirements defined: 2026-07-15*
*Last updated: 2026-07-15*
