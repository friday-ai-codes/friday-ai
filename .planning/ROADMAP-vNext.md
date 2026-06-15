# Friday AI · 前瞻路线图（v0.5 → v0.11）

> **这份文档的作用**：跨里程碑的持久决策主文档（source of truth）。记录 7 个规划里程碑的目标、特性映射、代码现状坐标、关键设计决策、跨里程碑依赖与推荐默认。
>
> **它不归 GSD 自动管理**，因此不会与 `.planning/ROADMAP.md`（当前激活里程碑的 phase 路线）冲突。
>
> **配套文档**：
> - `.planning/DOMAIN-MODEL.md` — 领域数据模型（脊柱/状态机/产物/purge/事件 taxonomy），各里程碑的数据底座。
> - `.planning/PREFLIGHT.md` — 前置修复/风险清单（与功能需求分轨）。
>
> **使用方式（每个里程碑轮到时）**：
> 1. 从本文档抽出对应里程碑章节（+ DOMAIN-MODEL 相关模型）→ 写成 `.planning/MILESTONE-CONTEXT.md`
> 2. 先扫 `PREFLIGHT.md` 中该里程碑的 blocking / should-fix-before 项
> 3. 运行 `/gsd-new-milestone`（消费 CONTEXT，生成该里程碑的 `REQUIREMENTS.md` + `ROADMAP.md`，带 REQ-ID 与 phases）
> 4. 运行 `/gsd-plan-phase N`（逐 phase 即时生成 `PLAN.md`，贴合当时代码）
>
> *最后更新：2026-06-14 · 基线：v0.4.0 已交付*

---

## 里程碑总览

| 里程碑 | 主题 | 依赖 |
|--------|------|------|
| **v0.5** | 索引/检索地基 + 排除文件（含两种 purge 模式） | — |
| **v0.6** | 领域脊柱 + 知识图谱补全（WorkItem 脊柱 / 评论事件流 / document / Release 账本 / 历史 diff / 截图 / 工作项关系 / 片段→需求反查） | v0.5 |
| **v0.7** | 方案编排（需求 → 多 agent 调研 → 架构师融合主方案；canonical TechnicalPlan + 状态机 + 事件 taxonomy） | v0.5、v0.6 |
| **v0.8** | 多仓串行编码 → 融合 PR（DAG 分层 + wave + 产物传递） | v0.7 |
| **v0.9** | SDD / OpenSpec 支持（重型：打标 → 产 spec → 状态机/gate/评审 → spec↔需求/PR 关联 → 编码遵循） | v0.7、v0.8 |
| **v0.10** | 操作审计治理（横切：成员/凭证/飞书同步/仓库权限/排除规则/清理任务/API key） | v0.5 后任意（基础表宜早埋点） |
| **v0.11** | 开放与协作（Agent API trace 透出 + Anthropic、流式卡片、自动建群） | 相对独立（v0.5 后可灵活插入） |

> **变化说明**：相较初版——①审计从 v0.5 拆出为独立里程碑（治理是横切能力，非索引附属）；②v0.6 升格为"领域脊柱 + 知识补全"（新增 `delivery` 操作态主模型，见 DOMAIN-MODEL）；③SDD 走重型（影响 v0.7/v0.8 留扩展点）；④开放协作顺延为 v0.11。

### 跨里程碑依赖图

```text
v0.5 索引地基 ──> v0.6 领域脊柱+知识 ──> v0.7 方案编排 ──> v0.8 多仓编码 ──> v0.9 SDD
                                          (v0.7 同时依赖 v0.5 路由/索引 与 v0.6 脊柱/历史召回)

v0.10 审计治理：v0.5 后任意位置（审计基础表 + 埋点宜作横切尽早引入）
v0.11 开放协作：仅依赖 v0.5，可任意穿插（但 Agent API 复用 v0.7 起的事件 taxonomy）
```

### 原始 12 项规划 → 里程碑映射

| 原始项 | 去向 |
|--------|------|
| #1 管理员权限（空间/系统管理员、审计日志） | 空间 admin 已有；系统管理员=现有 superuser（不新建角色）；审计日志 → v0.10 |
| #2 看板/缺陷 + 飞书关联 + 上线文档 | v0.6（WorkItem 脊柱 + Document + Release 账本） |
| #3 排除文件机制（P0） | v0.5 |
| #4 文件全文/关联 MCP、行→片段、片段→需求反查 | v0.5（行号回填）+ v0.6（片段→需求反查） |
| #5 Commit 历史索引 | v0.5 |
| #6 开放（飞书机器人/流式卡片、提问澄清、Agent API） | v0.11 |
| #7 工作流自动建群 | v0.11 |
| #8 父子看板/所属看板 → 工作项关系 | v0.6（`WorkItemRelation`，待飞书 payload 样例确认语义） |
| #9 技术方案自动生成 + 评论读取 | v0.6（评论事件流）+ v0.7（生成收敛 + canonical Plan） |
| #10 方案 session/复用/多仓连接隔离 | v0.7 + v0.8（顶两个里程碑） |
| #11 图片/截图识别需求 | v0.6（多模态 LLM 路线） |
| #12 批量多仓检索 + gitlab token 统一 | v0.5 |

---

## v0.5 · 索引/检索地基 + 排除文件

**Goal:** 把代码索引/检索的地基补齐——敏感文件全链路 fail-closed 不可见（两种 purge 模式）、commit 历史可检索、行级反查可用、多仓凭证统一。

> 审计已拆出为独立里程碑 v0.10（横切治理）。但**审计基础表 + 排除/清理操作的埋点宜在本里程碑作为横切先引入**，全量覆盖在 v0.10。

### Target features
- **排除文件机制（P0）**：AI 识别敏感文件（密钥/env/敏感信息）→ 建议名单 → 用户确认/手动增删；被排除文件在 RAG / MCP / grep / agent / 编码容器**任何地方不可见（fail-closed，INV-4）**；支持目录 / 通配 / 正则。
- **两种 purge 模式**（见 DOMAIN-MODEL §9）：**普通排除**（清派生索引 + 未来访问）/ **敏感清理**（额外覆盖 message parts / trace / TaskResult / CodeChangeArchive / prompt snapshot / 错误日志可控范围）。**不混一个按钮**。
- **Commit 历史索引**：commit message / author / 变更 的可检索 RAG（区别于现有仅 SHA 锚点）。
- **行级反查打底**：回填 `ChunkRegistry.line_start/line_end`，提供 `file:line → chunk_id` 能力（为 v0.6 片段→需求反查铺路）。
- **多仓凭证统一**：GitLab access token 从 per-repo OneToOne 升级为可共享/集中管理；MCP RAG 工具暴露多仓参数。

### 代码现状坐标
- **排除文件 = 部分有**：`scan_directory` 仅硬编码目录名 + 扩展名白名单，**无 .gitignore / 无可配置**（`server/services/code_parser.py`）；注释谎称"已应用 .gitignore"（`indexer.py` ~833 需修正）。
- **clone/落盘 7 处**：① 索引临时 clone ② 图谱重建 clone ③ MCP 常驻 **bare 镜像**（`repo_mirror.py`）④ rg worktree ⑤ task 容器独立 clone（`task/git_ops/operations.py`）⑥ Docker bare 缓存卷 ⑦ 工作流建分支。
- **需治理的数据面 9 处**：Qdrant 主库 + overlay、`ChunkRegistry`、codegraph、bare 镜像/worktree、`CodeChangeArchive`、知识库 diff、`repo_summaries`、`repo_index_nodes`。
- **可复用清理能力**：`QdrantService.delete_by_file_path`（主库）、`GraphWriter.adelete_for_files`（图谱）、`cleanup_index`（整仓）。缺口：overlay、ChunkRegistry 单文件、镜像、Docker 卷、CodeChangeArchive、摘要重建。
- **commit RAG = 完全没有**（仅 `last_indexed_commit_sha`、CO_CHANGED 边、diff 归档）。
- **行号回填 = 部分有**：Qdrant payload 有行号；`ChunkRegistry.line_start/end` 字段存在但**索引时未回填**（`symbol_lookup.py` 走 Qdrant scroll 兜底）。
- **多仓凭证 = per-repo**：`GitCredential` OneToOne 绑 `Repository`，无统一池；跨仓 RAG/grep 部分有，MCP `search_rag_chunks` 仅单仓。
- **审计 = 部分有**：分散的 TriggerLog/ActionLog/structlog 安全事件，**无统一 Admin Audit 表**。

### 关键设计决策
- **安全边界（产品化措辞，见 DOMAIN-MODEL §9.1）**：承诺"从 Friday 索引/检索/MCP/grep/agent/容器不可见"，**不承诺**"从本地 git object 物理消失"（不做 filter-repo）。bare 镜像对象可能残留，靠工具层 denylist 兜底。
- 排除做**三层**：① 物理层（每个 clone 落点 clone 后过滤/删文件，含 task 容器）② 工具层 path denylist fail-closed（挡 bare 镜像 `git show` 漏读）③ 配置单一源（`Repository` 字段 per-repo glob+正则，全局默认 `SystemSetting`）。
- **存量清理 = 对账任务 × 两模式**："当前 exclude 列表 vs 已索引内容" diff → 按普通/敏感模式删命中项 → 重建摘要。UI：对比列表→有变更→提示并允许点击清理。
- 顺手修 PREFLIGHT 中 PF-03/04/05（incremental 删除一致性、scan_directory 注释、overlay per-file 删）。

### 推荐默认（可推翻）
- 敏感文件自动识别走 **"建议 + 红色提醒 + 用户确认"**，而非静默删除（避免 LLM 误判踢出正常文件；真密钥高优先级告警）。

### 候选 phases（new-milestone 时细化）
1. 排除文件配置源 + scan/diff/MCP/容器统一过滤 + 工具层 fail-closed denylist
2. 存量清理对账任务（普通/敏感两模式）+ UI
3. 敏感文件 AI 识别 → 建议名单
4. Commit 历史 RAG 索引
5. ChunkRegistry 行号回填 + `file:line→chunk` API
6. 多仓凭证统一 + MCP 多仓参数
（审计基础表 + 排除/清理埋点作为横切，模型见 DOMAIN-MODEL，全量覆盖在 v0.10）

---

## v0.6 · 领域脊柱 + 知识图谱补全

**Goal:** 立起 `delivery` 操作态脊柱（以飞书 work item 为中心），并把知识图谱补全到"可沉淀历史、可反查、可吃多源输入"。**详细数据模型见 `DOMAIN-MODEL.md`。**

> 本里程碑是整个后续的**数据底座**——v0.7/v0.8/v0.9 的方案/编码/SDD 都挂在这里立的脊柱上。若评估偏大可拆为 v0.6（脊柱 + work item/评论/document）与 v0.6.x（Release 账本 + 历史 diff + 截图）。

### Target features
- **`WorkItem` 脊柱 + 单一 upsert 入口**（DOMAIN-MODEL §1）：飞书三元组身份；webhook/手动/Bitable/MR反查全走 `WorkItemService.upsert`；source-of-truth 三分类（镜像/增强/写回）+ `WorkItemSyncState` 来源完整度。
- **`WorkItemCommentEvent` 评论事件流**（§2）：append-only 事件 + 投影当前评论树（为灰区讨论/方案再生成提供事件边界），非快照。
- **`Document`（区分外部飞书/内部生成）**（§3）：`document_type/source_kind/external_ref/content_storage/...`；`REFERENCES` 边。
- **Release 账本宽容模型**（§4）：`ReleaseBatch/Record/Artifact`，adapter 后填，不被 Bitable 列名绑死。
- **飞书 Bitable 适配器**：扒"上线历史"多维表格入库（先骨架，数据后填）。
- **(看板URL + MR URL) → 一键摄取**：拉看板 → 需求/技术方案文档 RAG → MR diff RAG。
- **历史 diff 时效处理**：冻结历史快照 + bi-temporal 失效（commit 锚定，不追 master；PF-08）。
- **`WorkItemRelation`（父子/需求-缺陷/业务线-模块）**：⚠ 措辞从"看板层级"修正为工作项关系，**待飞书 payload 样例确认语义**。
- **评论入图 + 片段→需求反查**：评论摄取进知识投影；从 code chunk/模块反查需求/文档（依赖 v0.5 行号回填）。
- **截图识别需求**：多模态 LLM 路线（vision → 文本 → RAG），**非图片向量库**。

### 代码现状坐标
- **Bitable = 完全没有**：现有飞书客户端只有 docx + 项目 API，无 `bitable/app_table_record` 封装。
- **MR diff RAG = 已有**：`CodeChangeArchive` + diff 向量化(`chunk_kind=diff`) + `MODIFIES_CHUNK` 对齐（`knowledge/diff_archive.py`）；diff 走 MR/PR API 拉取。
- **历史 diff 时效 = 缺口**：`CodeChangeArchive` 无 `invalid_at`；master 演进后旧 `MODIFIES_CHUNK` 边不自动失效（实体/边版本链 bi-temporal 已有，但未用于 diff 对齐失效）。
- **飞书 docx = 部分有**：`get_document_content` 可读；PRD/技术方案**嵌进 work_item content**；`EntityKind.DOCUMENT` 枚举有但**无 normalizer 落地**。
- **截图 = 部分有**：chat 已有图片多模态(vision)；"截图→匹配需求"是新功能。
- **看板层级 = 完全没有**：`KnowledgeEntity` 无 board/parent 字段；工作项关联只写进 content 文本，未入 `RELATES_TO` 边。
- **评论 = 部分有**：`get_comments` API 有、MCP 上下文可选含评论；**不入知识图谱**；飞书文档评论完全没有。
- **ingestion 适配器模式 = 成熟**：`knowledge/sources/` 注册表 + `normalize()` 契约（`coding_plan/mcp_technical_plan/workflow_plan/task_result/feishu_work_item`）。新增来源只需注册 + 实现 `normalize()`。

### 关键设计决策
- 历史 diff **冻结快照、不追 master**：`commit_sha` 锚定不可变历史，`valid_at`=合并时间；master 演进后旧 `MODIFIES_CHUNK` 边置 `invalid_at`（"当年成立"），查询区分历史(as_of)/当前。
- **diff 不需对 diff 本身跑 tree-sitter**：靠 hunk 行范围 与已索引 chunk/Symbol 行区间**重叠对齐**；历史 chunk 变了则退化文件级；diff 文本本身已向量化。
- 截图 **先多模态 LLM，不建图片向量库**：vision LLM 读截图 → 提取文字/UI/业务语义 → 文本 query → 现有 work_item/知识库 RAG。图片向量库（视觉相似/标注重）列 backlog。
- Bitable 走现有 ingestion 适配器：新 `feishu_bitable` source_kind + natural key `{app_token}:{table_id}:{record_id}`。

### 推荐默认（可推翻）
- 需求/技术方案文档落**独立 DOCUMENT 实体**（已定，区分外部/内部，见 DOMAIN-MODEL §3）。
- 脊柱用 **canonical WorkItem 操作态 + 知识图谱投影引用**（已定，见 DOMAIN-MODEL §0/§8）。

### 候选 phases
1. **`WorkItem` 脊柱**：模型 + `WorkItemService.upsert`（单一入口）+ source-of-truth 三分类 + `WorkItemSyncState`
2. `WorkItemCommentEvent` 评论事件流 + 当前树投影
3. `Document`（外部/内部）+ `feishu_document` normalizer + `REFERENCES` 边
4. Release 账本宽容模型 + 飞书 Bitable client/adapter（骨架先行）
5. (看板URL+MR URL) → 一键摄取编排
6. 历史 diff 冻结 + bi-temporal 失效对账（PF-08）
7. `WorkItemRelation` 建模 + 关联入图（待飞书 payload 样例）
8. 评论入图 + 片段→需求反查 API/MCP（依赖 v0.5 行号回填）
9. 截图识别需求（多模态 LLM）

> ⚠ **待你提供**：飞书 work item payload/字段样例（定 `WorkItemRelation` 与业务线/模块字段归属）；上线多维表格链接（定 Release 粒度与 adapter 映射）。

---

## v0.7 · 方案编排（需求 → 主方案）

**Goal:** 把"需求 → 一份高质量多仓主技术方案"做成可复用的 map-reduce 多 agent 编排：拆分 → 路由 → 召回 → 澄清 → 并行调研 → 架构师融合。

### 流水线（6 段）
```text
需求
 → ① 拆分(server orchestrator)：前后端/业务线/模块
 → ② 路由(RepoRouterV2 知识树)：涉及哪些仓库
 → ③ 召回(历史需求/缺陷/复盘/相似需求 RAG)
 → ④ 澄清(HITL，不清晰问用户)
 → ⑤ 筛选 → 只对"需深入"的仓起 claude code 容器并行调研(上下文隔离)
 → ⑥ 架构师子 agent：收齐 partial → 融合主方案 + 跨仓依赖梳理
```

### 概念定义
- **隔离** = ⑤ 每仓独立子 agent 容器（独立上下文/记忆，防串味 + 防超长上下文）。
- **连接** = ⑥ 多仓 partial 融合成主方案 + 跨仓依赖显式建模。

### 代码现状坐标
- **`ai_plan_generation` = 单 orchestrator 工具循环**（`server/workflows/nodes/ai/plan_generation.py`），**非并行子 agent**；多仓靠 `include_repos` 文本注入；方案一次性生成（非分仓融合）。
- **并行子 agent 调研 = Chat 路径已有**：`deep_analysis` 每仓 `SubAgentSession(explore)` 容器 + `BarrierManager` 聚合（`agents/tools/chat_tools.py`）；**工作流方案节点未接**；`SubAgentSession.PLAN` 枚举有但**无派发代码**。
- **融合 = 仅 chat 文本拼接**（`_execute_with_results`），无结构化 multi-partial → 单一 `TechnicalPlan`。
- **仓库路由 = 已有**：`RepoRouterV2`（能力树 + LLM）+ `analyze_repository_relevance`；方案节点未接入。
- **召回 = 已有**：`DeliveryKnowledgeSearchService` + `auto_inject_similar_history`（缺陷/复盘需 v0.6 入图）。
- **澄清 = 已有**：`ask_user_question`(workflow) / `clarification`(chat)。
- **并行容器派发 = 已有**：`AICodingNode` `asyncio.gather` + `waiting_event`；Runner `concurrent`。
- **现存 bug（开工必修，见 PREFLIGHT PF-01/PF-02）**：工具名 `search_code` 漂移、`verify_plan` schema 漂移。

> **数据模型见 DOMAIN-MODEL §5（canonical `TechnicalPlan` + `TechnicalPlanService` + 迁移规则）、§6（编排状态机）、§7（结构化产物 + PlanValidator）、§10（事件 taxonomy）。**

### 关键设计决策（已与用户确认）
- 子 agent 运行：**先 server 端 RAG/路由快筛，只对"需深入"仓起 claude code 容器**（filter_then_container），省资源。
- 融合：**起一个"架构师"子 agent** + **结构化 `MergedPlan` + `PlanValidator`**（否则只是"更贵的总结器"）。
- canonical 方案：新编排经 `TechnicalPlanService` 写 canonical `TechnicalPlan`；旧 3 路径 eager 投影挂软链（迁移规则见 DOMAIN-MODEL §5，**不全量双写**）。
- 主入口：**工作流 + Chat 都要，但底层抽成可复用 orchestration engine**；工作流先行，Chat 薄封装后置——**不要两入口并行造**。
- 事件 taxonomy **本里程碑即落**（`work_item.syncing`/`repo.research.*`/`plan.merge.*`…），v0.11 对外只是 adapter。
- **SDD 扩展点预留**：`PlanSession` 对 SDD 仓库产 `spec draft`（v0.9 做全）。

### 候选 phases
1. 修 PF-01/PF-02 + `ai_plan_research` engine 骨架 + `PlanSession` 状态机
2. canonical `TechnicalPlan` + `TechnicalPlanService` + 旧路径软链/迁移
3. 路由 + 召回接入（RepoRouterV2 + 历史召回）
4. 并行调研子 agent（`RepoResearchTask`/`PartialPlan` + 结构化 partial 契约 + 上下文隔离 + 过期 invalidation）
5. 架构师融合 + `MergedPlan` + `PlanValidator` + 跨仓依赖建模
6. HITL 澄清（`Clarification` + 重跑规则）+ 事件 taxonomy 产出 + 工作流入口
7. Chat 入口薄封装

---

## v0.8 · 多仓串行编码 → 融合 PR

**Goal:** 把主方案落成多仓代码：按跨仓依赖分层 wave 执行、上游产物注入下游、冲突检查、关联多仓 PR。

### Target features
- **execution_plan DAG 拓扑分层**（按 `dependencies`）。
- **wave 式执行**：wave1(后端)完成 → 提取产物(API 契约/OpenAPI/diff) → 注入 wave2(前端) `global_context` → dispatch。
- **多仓融合 PR** + 跨仓 PR 关联。

### 代码现状坐标
- **跨仓/跨任务上下文传递 = 完全没有**：`execution_plan[].dependencies` 仅 schema 声明 + prompt 提示；`AICodingNode` 只按 `repository_id` 全并行(`asyncio.gather`)，不读 dependencies、不传产物（`server/workflows/nodes/ai/coding.py`）。
- **动态重规划 = 编码层几乎没有**：callback 注释写死"Server 端不再重试"；plan 阶段才有 verify+revise。
- **可复用**：`DispatchTask` 协议、RemoteTool MCP、callback 驱动 workflow resume、`execution_plan` schema、`waiting_event`。
- **缺口**：workflow 编码路径 env 不一致（branch strategy / git token 在 chat 路径有、workflow 路径缺）。

### 关键设计决策
- 范围：scope=**plan_to_pr**，本里程碑聚焦"主方案 → 多仓 wave 编码 → 融合 PR"。数据模型见 DOMAIN-MODEL §6（`RepoCodingTask`：wave/`depends_on` DAG/`produced_artifacts`）。
- **显式非目标**：**不做编码中全自动回溯重规划**。编码遇阻**走已有 question 协议抛给用户/orchestrator**（协议在、task 侧未发），全自动 replan 留后续增量——避免范围爆炸。
- 复用 `waiting_event` + callback resume 扩成多 wave。修 PF-06（workflow 编码路径 env 不一致）、消化 PF-07（dependencies 不读）。
- **SDD 扩展点预留**：`RepoCodingTask.follow_openspec` 标记 → 编码容器注入 openspec 指引（v0.9 做全）。

### 候选 phases
1. `execution_plan` DAG 拓扑分层 + wave 调度（`RepoCodingTask`）
2. 上游产物提取 + 注入下游 prompt/global_context
3. workflow 编码路径 env 对齐（PF-06：branch/git token）
4. 多仓融合 PR + 跨仓 PR 关联
5. 编码遇阻 → question 抛人（HITL 回路，非全自动 replan）

---

## v0.9 · SDD / OpenSpec 支持（重型）

**Goal:** 让 spec-driven development 成为可治理的过程资产（领导看重）：仓库打标、方案产 spec、spec 状态机 + 编码前置 gate + 评审状态、spec↔需求/PR 关联、交付验收。

> **重型**：不只是"识别目录 + 注入 prompt"。v0.7/v0.8 已预留扩展点（`PlanSession` 产 spec draft、`RepoCodingTask.follow_openspec`），本里程碑做完整生命周期与治理。

### Target features
- **SDD 仓库自动打标**：索引后检测 `openspec/` 目录 → `facets["methodology"]="SDD"` + 前端标签。
- **产出 SDD spec**：SDD 仓库产技术方案同时产 openspec spec（change proposal / spec delta），落 `Document(document_type=sdd_spec)`。
- **spec 状态机 + 变更记录 + 评审状态**：draft → in_review → approved → implemented → archived；评审记录。
- **编码前置 gate**：SDD 仓库编码前校验 spec 已 approved（gate）。
- **spec ↔ 需求/PR 关联**：spec 挂 `WorkItem`，关联实现 PR/MR；交付验收视图。
- **编码遵循 OpenSpec skill**（仓库内 `.claude/skills` + system prompt 指引）。

### 代码现状坐标
- **Repository 打标 = 部分有**：通用 `facets` JSON + `is_monorepo` 已有，**无** SDD 专用字段，**无** openspec 检测钩子（`server/repositories/models.py` / `facet_service.py`）。
- **编码 skill = 好消息**：task 容器已 `setting_sources=["project"]`，**自动加载克隆仓库内 `.claude/`、`.claude/skills/`、CLAUDE.md**（`task/core/executor.py`）。SDD 仓库自带 openspec skill 即可被 claude code 原生使用，Friday 侧改动极小。
- **缺口**：task `system_prompt` 写死，需加"按仓库类型注入 SDD 指引"的注入点；SPEC 状态机/展示从零。

### 关键设计决策
- 打标走 `facets["methodology"]="SDD"`（低改动），索引完成钩子检测 `openspec/`。
- 编码优先利用**仓库内 .claude/skills + setting_sources=project** 原生能力 + system prompt SDD 指引注入。
- 重型范围由用户确认（编码前置 gate + 评审 + spec↔需求/PR 关联 + 交付验收资产）。

### 候选 phases
1. SDD 仓库检测 + facets 打标 + 前端标签
2. 方案产 openspec spec（接 v0.7 扩展点）+ `Document(sdd_spec)`
3. spec 状态机 + 变更记录 + 评审状态 + 展示
4. 编码前置 gate + openspec skill 编码策略（接 v0.8 扩展点）
5. spec ↔ 需求/PR 关联 + 交付验收视图

---

## v0.10 · 操作审计治理

**Goal:** 横切治理能力——统一审计模型覆盖管理员/敏感操作，可查可追溯。

> 从 v0.5 拆出独立。审计基础表 + 排除/清理埋点宜在 v0.5 作横切先引入，本里程碑做**全量覆盖 + 查询 UI + 回填补齐**。

### Target features
- **统一 `AuditEvent` 模型**（DOMAIN-MODEL §11）：actor / action / target / before-after / 时间 / 来源。
- **覆盖面**：成员增删改、凭证操作、飞书同步、仓库权限、排除规则变更、清理任务、Agent API key、空间配置、用户启停。
- **查询/审计 UI** + 导出。

### 代码现状坐标
- **无统一审计表**：分散 `TriggerLog`/`ActionLog`/structlog 安全事件（前述调研）。
- 可复用 structlog 命名规范作采集参考。

### 关键设计决策
- 审计为**横切**：各功能产生敏感操作时 emit；本里程碑统一收口 + 补齐历史覆盖 + UI。
- 系统管理员 = 现有 `is_superuser`（不新建角色，已与用户确认）。

### 候选 phases
1. `AuditEvent` 模型 + emit 中间件/信号
2. 全量覆盖各敏感操作 emit 点
3. 查询/审计 UI + 导出

---

## v0.11 · 开放与协作

**Goal:** 对外开放与协作层：Agent API 透出 trace/progress 事件、Anthropic 兼容端点、飞书原生流式卡片、工作流自动建群。

### Target features
- **Agent API trace 透出**：把内部工具调用（RAG/Grep 等）作为 **progress/trace 事件**透出给 OpenAI/Anthropic 兼容调用方（复用 v0.7 起的事件 taxonomy，DOMAIN-MODEL §10）。
- **Anthropic 兼容端点**（`/v1/messages`）。
- **飞书原生流式卡片**（CardKit）。
- **工作流自动建群**。

### 代码现状坐标
- **OpenAI compat = 已有**（`/v1/chat/completions` 流式 + `reasoning_content`），**`tool_calls` 完全没有**（`adapter.py` 明确 `continue` 跳过），**无 Anthropic 端点**。
- **机器人对话 = 已有**（双向、群聊需 @）；**流式卡片 = 部分有**（PATCH 全量替换，非原生 CardKit）。
- **自动建群 = 完全没有**（只能 `add_bot_to_chat` 加入已有群）。

### 关键设计决策（已与用户确认）
- **内部工具调用透出为 progress/trace 事件，不用标准 tool_calls，也不叫"思考过程"**（INV-5）：内部工具是服务端闭环执行，外部客户端不该回传；标准 `tool_calls` 会让规范客户端误以为挂起等回传 → 卡死。映射为 `reasoning_summary` / progress event（用户看到"正在检索 RAG / grep / 分析仓库"），**非模型私有 CoT**。
- 复用 v0.7 起产出的事件 taxonomy，对外只是不同 adapter。标准双向 tool_calls 仅在未来支持"客户端自带工具"时才做。

### 候选 phases
1. compat `TOOL_USE_*` → progress/trace 事件透出（adapter over 事件 taxonomy）
2. Anthropic 兼容端点 `/v1/messages`
3. 飞书原生流式卡片（CardKit）
4. 工作流自动建群节点

---

## Deferred / Backlog（明确后置，不入上述里程碑）

- **编码中全自动 replan/回溯**（前端卡住自动唤起后端重调研改方案）：最高阶，v0.8 用"抛 question 给人"过渡，全自动留后续。
- **图片向量库**（视觉相似/淘宝识图式 + 业务标注）：太重且场景不匹配，等真有"视觉精确定位"诉求再评估。
- **系统运维角色分层**（非 superuser 的中间角色）：当前 superuser 够用，不做。
- **标准双向 tool_calls 协议**（客户端自带工具）：等有此诉求再做。
- v0.2/v0.3 历史 follow-up（实时明文 PAT 通道、timeline provenance、graph 边类型统一等）见 `MILESTONES.md` / `PROJECT.md`。

---

## 决策日志（本轮 AskQuestion 确认）

| 议题 | 用户选择 |
|------|---------|
| 系统管理员含义 | = 现有 superuser，不新建角色（审计日志单独做） |
| #10 连接 vs 隔离 | 两者都要（连接=多仓融合+跨仓依赖；隔离=子 agent 上下文隔离） |
| #6.3 工具调用透出 | 内部工具调用 → 封装成 reasoning 思考过程透出（非标准 tool_calls） |
| 下一里程碑优先级 | 索引 / 知识 / 开放 / 治理 全选 |
| 调研子 agent 运行 | filter_then_container（先快筛，只对需深入仓起容器） |
| 融合 reduce | architect_subagent（专门架构师子 agent 融合） |
| 编排主入口 | 工作流 + Chat 都要（底层 engine 复用，工作流先行） |
| v0.8 范围 | plan_to_pr（需求→方案→多仓编码→融合 PR 整条） |
| 排除文件安全边界 | tools_refuse：工作树干净 + Friday API/工具/容器 fail-closed denylist；不抹 git object |
| SDD/OpenSpec 力度 | 重型：打标 + 产 spec + 状态机/gate/评审 + spec↔需求/PR 关联 + 交付验收 |
| 操作审计位置 | 独立里程碑 v0.10（全覆盖；基础表+埋点 v0.5 横切先行） |
| 领域脊柱方式 | canonical WorkItem 操作态主模型 + 知识图谱投影引用；3 条 plan 路径渐进适配不爆改 |

---

## 待用户提供的输入（阻塞部分 v0.6 定稿）

- ✅ **飞书 work item** → 已用真实 plugin 凭证**实地拉取确认**：身份/类型/字段结构/关系（在字段里）/状态/PRD 字段全部坐实（DOMAIN-MODEL §1.5）；并发现 PF-09/10/11/12 四个现存接口缺陷。
- ✅ **GitLab MR** → 实地拉取确认：`target_branch=<release-branch>`(非 master)、有 merge_commit_sha、changes diff；坐实 diff base 锚定策略。
- ⚠ **上线多维表格(Bitable)** → 仍未读到：Bitable 在 `<tenant>.feishu.cn`（飞书**开放平台**，需 `app_id/app_secret` 的 tenant_access_token），用户给的是 Meego **项目 plugin** 凭证，体系不同。**仍需开放平台 app 凭证**，或贴列头/样例行。
- ⚠ **容器型("project")真实 type_key** → URL 段 `project` 非 API type；`所属项目` 字段反推或查"工作项类型"接口可得，待补。

---

# 各里程碑细化：交付物 / 成功标准 / 风险

> 每个里程碑的可验收交付物、成功标准（observable）、关联的 PREFLIGHT 与 DOMAIN 模型、主要风险。`/gsd-new-milestone` 时据此生成 REQ-ID 与 phase 成功标准。

## v0.5 · 索引地基 + 排除文件

**交付物**：
- `Repository` 排除配置字段（glob + 正则）+ 全局默认 `SystemSetting`。
- 统一过滤函数，挂载于 scan / git_diff 文件列表 / MCP grep+read / task 容器 clone 后。
- 工具层 fail-closed denylist（RAG/MCP/grep 拒读命中路径）。
- 存量清理对账任务（普通/敏感两模式）+ 前端"对比→清理"UI。
- 敏感文件 AI 识别 → 建议名单（建议+确认，不静默删）。
- Commit 历史 RAG 索引；`ChunkRegistry.line_start/end` 回填 + `file:line→chunk` API。
- 多仓 GitLab 凭证统一池 + MCP RAG 多仓参数。

**成功标准**：
1. 排除某文件后，RAG 检索 / MCP get_file / grep / 新编码容器**均拿不到**该文件内容（fail-closed）。
2. 已索引文件被加入排除并执行"清理"后，Qdrant(主+overlay)/ChunkRegistry/codegraph/摘要**无残留**。
3. 普通排除与敏感清理是**两个独立动作**，覆盖范围不同（敏感额外清 trace/TaskResult/CodeChangeArchive 等）。
4. commit message 可被语义检索召回。
5. 同一 GitLab 实例的多个仓库可复用同一凭证。

**关联**：修 PF-03/04/05；DOMAIN §9（purge 矩阵/两模式/边界）、§17-C。
**风险**：bare 镜像 git object 不抹除——denylist 必须无遗漏路径，否则泄漏；敏感清理覆盖面广，需明确边界避免误删历史。

## v0.6 · 领域脊柱 + 知识补全

**交付物**：
- `delivery` app：`WorkItem` + `WorkItemService.upsert`（唯一入口）+ `WorkItemSyncState` + `WorkItemRelation`（字段派生）+ `WorkItemCommentEvent` + `WorkItemStatusEvent`。
- `Document`/`DocumentVersion`（外部/内部）+ `feishu_document` normalizer + `REFERENCES` 边。
- `ReleaseBatch/Record/Artifact` 宽容模型 + 飞书 Bitable client/adapter（开放平台凭证）。
- (看板URL+MR URL)→一键摄取编排；历史 diff 冻结 + bi-temporal 失效。
- 评论入图 + 片段→需求反查 API/MCP；截图识别需求（多模态 LLM）。

**成功标准**：
1. 同一飞书工作项无论从 webhook/手动/Bitable/MR反查进入，都收敛到**唯一** `WorkItem`（INV-1）。
2. `WorkItem` 正确区分 mirror/enhanced/writeback，sync 不覆盖 enhanced。
3. 从 story 的 `所属项目` 字段正确派生父子关系（不依赖失效的 relation 端点）。
4. 给定 (看板URL, MR URL) 能拉看板 + PRD/技术方案文档 + MR diff 并入库可检索。
5. 历史 MR diff 冻结为 commit 锚定快照，master 演进后旧关联标 invalid。
6. 截图 → vision LLM → 召回对应需求（无图片向量库）。

**关联**：修 PF-09/10/11/12（飞书接口）；DOMAIN §1/§2/§3/§4/§12/§16；待开放平台凭证（Bitable）。
**风险**：飞书接口缺陷较多（PF-09~12）须先修；Bitable 跨租户凭证未到位；容器型 type_key 未知。本里程碑偏大，必要时拆 v0.6 / v0.6.x。

## v0.7 · 方案编排（需求→主方案）

**交付物**：
- `ai_plan_research` 编排 engine + `PlanSession` 状态机；canonical `TechnicalPlan` + `TechnicalPlanService` + 旧路径软链/迁移。
- 路由(RepoRouterV2)+召回接入；并行调研子 agent（`RepoResearchTask`/`PartialPlan`，容器隔离，过期 invalidation）。
- 架构师融合 + `MergedPlan` + `PlanValidator`；`Clarification` 澄清回路；事件 taxonomy 产出；工作流入口（Chat 薄封装）。

**成功标准**：
1. 一个需求经"拆分→路由→召回→澄清→并行调研→融合"产出一份带跨仓依赖的 `MergedPlan`。
2. 子 agent 上下文隔离；单仓失败可重试，不重跑整 session。
3. 澄清回答后仅相关 partial 重跑；仓库重索引使过期 partial 标 stale 并重跑。
4. `PlanValidator` 能拦截契约不一致/依赖成环/缺回滚的方案。
5. 全程产出 §15 trace 事件。

**关联**：必修 PF-01/02；DOMAIN §5/§6/§7/§14/§15；预留 SDD 扩展点。
**风险**：多 agent 编排复杂度高；架构师融合质量依赖 validator；engine 抽象不当会拖累 v0.8。

## v0.8 · 多仓串行编码→融合 PR

**交付物**：`RepoCodingTask`（DAG 拓扑分层 + wave 调度）；上游产物提取注入下游；workflow 编码 env 对齐（PF-06）；多仓融合 PR + 跨仓 PR 关联；编码遇阻→question 抛人。

**成功标准**：
1. 按 `dependencies` 分 wave，后端 wave 完成产物注入前端 wave 上下文。
2. 多仓产出关联的 PR/MR，diff base 用各仓正确 target_branch（非假设 master）。
3. 编码遇阻走 question 抛给用户/orchestrator（**不做全自动回溯重规划**）。

**关联**：消化 PF-06/07；DOMAIN §6（RepoCodingTask）；显式非目标=全自动 replan。
**风险**：跨仓产物契约传递的正确性；容器并发与凭证；wave 失败的部分回滚语义。

## v0.9 · SDD / OpenSpec（重型）

**交付物**：SDD 仓库检测+facets 打标+前端标签；方案产 openspec spec（接 v0.7 扩展点）；spec 状态机+变更记录+评审状态；编码前置 gate + openspec skill 编码策略（接 v0.8 扩展点）；spec↔需求/PR 关联 + 交付验收视图。

**成功标准**：
1. 索引后 SDD 仓库自动打标，前端可见。
2. SDD 仓库方案产出 openspec 格式 spec draft 并落 `Document(sdd_spec)`。
3. spec 有完整状态机（draft→in_review→approved→implemented→archived）+ 评审记录。
4. SDD 仓库编码前校验 spec 已 approved（gate 拦截未批）。
5. spec 关联到对应 `WorkItem` 与实现 PR，验收视图可追溯。

**关联**：DOMAIN §6 SDD 扩展点；依赖 v0.7/v0.8 已留 hook。
**风险**：openspec 约定与现有 claude-code skill 加载方式的契合；过程资产范围大，易膨胀。

## v0.10 · 操作审计治理

**交付物**：统一 `AuditEvent` 模型 + emit 中间件/信号；全量覆盖（成员/凭证/飞书同步/仓库权限/排除规则/清理/API key/空间配置/用户启停）；查询/审计 UI + 导出。

**成功标准**：
1. 上述敏感操作均产生不可篡改审计记录（actor/action/target/前后值/时间/来源）。
2. 排除规则变更与清理任务（v0.5 埋点）在审计中可查。
3. 审计 UI 支持按 actor/action/target/时间过滤 + 导出。

**关联**：v0.5 已埋审计基础表 + 排除/清理点；系统管理员=superuser（不新建角色）。
**风险**：横切埋点易遗漏；审计本身的访问控制（谁能看审计）。

## v0.11 · 开放与协作

**交付物**：compat `TOOL_USE_*`→progress/trace 事件透出（adapter over §15 taxonomy）；Anthropic 兼容端点 `/v1/messages`；飞书原生流式卡片（CardKit）；工作流自动建群节点。

**成功标准**：
1. 外部 OpenAI/Anthropic 兼容调用方能看到"正在检索 RAG/grep/分析仓库"的 progress（reasoning_summary/thinking），**不暴露原始 CoT、不误用 tool_calls**。
2. Anthropic `/v1/messages` 流式可用。
3. 飞书卡片走原生流式，体验顺滑。
4. 工作流可自动创建群并拉人。

**关联**：复用 v0.7 起的事件 taxonomy（§15）；DOMAIN INV-5。
**风险**：飞书 CardKit 接入工作量；事件 taxonomy 若 v0.7 未沉淀稳定，这里会返工——故 taxonomy 必须 v0.7 落。
