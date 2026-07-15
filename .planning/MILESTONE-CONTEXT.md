# MILESTONE-CONTEXT: v0.17.0 统一知识库与全链路联动（知识收敛 + 完工沉淀闭环 + 容器内置 MCP/Skills）

> 由深度调研会话产出（2026-07-15）：三路并行代码探查（MCP 工具面 / 工作流与编排链路 / 知识沉淀与 skills 体系）+ skills 包与 task 容器集成点补充调研。本文档供 `$gsd-new-milestone` 消费。

## 一句话目标

把 Friday 现有的多套"知识/经验/沉淀"收敛成**一个统一知识库**（单一摄取入口 + 单一检索面），对外经 MCP + `@friday-ai-codes/skills` 提供服务、对内让 Chat/工作流/编排/编码容器**天然集成**；同时补齐"完工沉淀"闭环（编码完成 → 经验入库 + 业务侧回写），并给编码容器**内置 Friday MCP 与 skills**，让最需要上下文的角色（容器内编码代理）能主动查知识、被动沉淀经验。

## 背景：为什么立这个里程碑（调研结论）

系统底座已统一得很好——检索（RAG/codegraph）、方案编排（`services/process_runtime/`）、编码派发（`runners.dispatcher` → Go runner → task 容器）三块被 MCP / Chat / 工作流三条链路共享。**"功能孤立感"来自三类"最后一公里"断点**：

### A. 知识飞轮转不起来（写了没人读 / 读时缺源）

1. **`McpLearningCase` 是孤岛**：独立表 + token 打分检索（非向量），只有 MCP `search_learning_cases` 和 `create_feishu_technical_plan` 自动召回能碰到；Chat、工作流节点、编码容器全都读不到（`server/mcp_tools/models.py`、`learning_case_service.py`）。与 `delivery_knowledge`（Qdrant 向量 + 知识图谱）是平行两套"历史经验"，无法统一排序。
2. **MCP 产物不入知识图**：`McpCodingPlan` / `McpRepositoryAnalysis` / `McpCodingExecutionTrace` 均无 `knowledge/sources/` normalizer；讽刺的是 Chat 侧 `chat.CodingPlan` 反而入图（`knowledge/sources/coding_plan.py`）。同样的"方案"，走 MCP 入口就成检索盲区。
3. **编排召回不含项目沉淀**：`DeliveryKnowledgeRecallAdapter`（`services/process_runtime/recall_adapter.py`）recalling stage 只召回 `work_item`/`tech_plan`/`code_change`，刻意不含 `document`——v0.15/v0.16 沉淀的项目记忆、ProjectDoc、外部工件在方案生成时召不回来。
4. **`ProjectStateApi` 写多读少**：IDE hook 大量写入，仅 `grep_project` / STATE 文档渲染间接可见，不进向量库。
5. **Chat 工具面缺知识读工具**：`agents/chat_runner.py` 白名单无 `read_project_doc` / `search_project_context` / `search_learning_cases`；`get_project_overview` 记忆只报 count 不给正文。

### B. 完工沉淀与业务回写只在 MCP 一条链闭环

1. **工作流 `ai_coding` 完成默认不回写飞书工作项**：只交给下游 `notify_feishu_im` 推群卡片；只有 MCP `execute_work_item_repo_tasks(write_back=True)` 有工作项评论/文档回写（`server/mcp_tools/work_item_execution_service.py`）。同一件"跑完编码"，走工作流和走 MCP，飞书上看到的结果完全不同。
2. **Chat 编码路径（`orchestration/coding_graph.py`）不写飞书**，PR 不强制关联 `delivery.WorkItem` / `initiatives.Project`。
3. **没有自动"经验沉淀"**：`create_learning_case` 只能靠外部 MCP 调用方（如 Cursor 里的 friday-memory skill）自觉调用；编码完成回调（`subagent/api/callbacks.py`）不产 learning case。
4. **审查环断开**：`ai_code_review` 节点已下线（`server/workflows/nodes/ai/code_review.py` 仅剩 prompt 常量）。

### C. 编码容器是"知识贫民区"

1. task 容器内的 claude-agent-sdk 代理**默认不能**调服务端任何知识工具：RemoteTool 种子几乎只有 `fetch_feishu_document`；无法主动 `search_rag_chunks` / `search_delivery_knowledge` / `search_learning_cases` / `search_project_context`。
2. 上下文靠派发时 prepend 的 `pack_project_context` 文本——且**只有 Chat 路径有**（`chat/coding_session_service.py` 的 `_resolve_project_context_for_dispatch`）；工作流 `ai_coding` 节点（`workflows/nodes/ai/coding.py`）不做这个 prepend。
3. skills 只有仓库自带 `.claude/skills`（`setting_sources=["project"]`）+ 可选 openspec 指引；Friday 自己的 `skills/skills/`（friday-code/friday-memory 等）没给容器用。

### D. 工具面分裂与"同名不同物"

1. Chat 的 `create_coding_plan`（写 `chat.CodingPlan`）≠ HTTP MCP 的 `create_coding_plan`（走 `process_runtime` 落 `McpCodingPlan`）：同名、不同模型、不同落库，执行靠 bridge 拷贝（`mcp_tools/execution_service.py`）。
2. MCP `improve_coding_plan` / `analyze_repository` 停在旧"确定性缝"（`mcp_tools/planning_service.py`），没跟 `create_*` 一起收敛到 `orchestration_delegate.delegate_process_runtime`；`analyze_repository` 产物几乎不再驱动生成。
3. `report_project_state` 已落地但未进 `TOOL_SCHEMA_SNAPSHOT`（`mcp_tools/serializers.py`）；`reverse_lookup_requirements` 未暴露到对外（Cursor）工具面。
4. `services/plan_orchestration/` 目录仅剩 `__pycache__` 空壳（真源已迁 `process_runtime`），文档引用未清。

## 关键既有资产（复用坐标，严禁重复造）

| 资产 | 位置 | 复用方式 |
|------|------|----------|
| 知识摄取适配器模式 | `server/knowledge/sources/` 注册表 + `normalize()` 契约 + `aschedule_ingestion`（`knowledge/ingestion.py`） | 新增 source 只需注册 + 实现 normalize；learning_case / mcp_coding_plan / execution_trace 走这条 |
| 统一检索服务 | `knowledge/retrieval.py` `DeliveryKnowledgeSearchService`（向量 + 图 + bi-temporal） | learning case 检索换底层；对外知识 API 复用 |
| 编排召回适配器 | `services/process_runtime/recall_adapter.py` | 扩 kinds（document / learning_case），可配置 |
| 项目上下文打包 | `services/project_context_packer.py` + `chat/coding_session_service.py` `_resolve_project_context_for_dispatch` | 工作流 `ai_coding` 对齐同一 packer |
| 飞书回写能力 | `mcp_tools/work_item_execution_service.py`（write_back 评论/文档）、`services/feishu_im.py`（CardKit） | 抽公共 write-back service 供三链路复用 |
| task 容器 MCP 挂载机制 | `task/core/executor.py`：`build_remote_tools_mcp_server` → `ClaudeAgentOptions(mcp_servers=..., allowed_tools=...)`，`extra_mcp_servers` 参数已存在 | 新增"Friday 知识 MCP server"构建器（HTTP 调 `/api/mcp/tools/*`，PAT 鉴权），同机制挂载 |
| 容器 skills 加载 | `task/core/executor.py` `setting_sources=["project"]` 原生加载工作区 `.claude/skills/` | 派发时把 Friday skills 物料写入 workspace（或 SDK 注入） |
| 对外 skills 包 | 仓库根 `skills/`（npm `@friday-ai-codes/skills`）：`friday` / `friday-code` / `friday-memory` / `friday-feishu` + `@friday-ai-codes/mcp` setup 向导 + `.mcp.json` | 容器内置 skills 与该包同源（单一事实源），避免两套漂移 |
| 平台 Skill（RemoteTool） | `server/tools/sources/skill.py`（`RemoteTool.Source.SKILL` 多步 steps）+ `/api/tools/execute/` | 内置"编码前调研"、"完工沉淀"两个种子 Skill |
| 事件回调 | `subagent/api/callbacks.py`（TaskResult → 工作流 resume / coding_graph barrier；已触发 `task_result` 入图） | 完工沉淀钩子挂这里 |
| MCP 编排委托 | `mcp_tools/orchestration_delegate.py` `delegate_process_runtime` | improve/analyze 收敛到此 |
| 对外 MCP 工具面 | `server/mcp_tools/urls.py` + `views.py` + `serializers.py` `TOOL_SCHEMA_SNAPSHOT`（约 30 工具，`/api/mcp/tools/<name>/`） | 新增/调整工具在此注册并进 snapshot |

## 里程碑范围（4 大块）

### 1. KNOW — 统一知识库（收敛 + 消费面补齐 + 对外服务）

- learning case 入图：新增 `knowledge/sources/learning_case.py` normalizer；`create_learning_case` 写库后投递 `IngestionRequest`；`search_learning_cases` 底层切换 `DeliveryKnowledgeSearchService`（kind 过滤），对外 API 契约不变（token 打分退役）。
- MCP 产物入图：`McpCodingPlan`（版本要点）、`McpRepositoryAnalysis`、`McpCodingExecutionTrace`（执行摘要）各补 normalizer；与 chat `coding_plan` / `task_result` 的实体去重/关联（复用既有实体 natural key 约定）。
- 编排召回扩容：`recall_adapter` kinds 增加 `document`（项目记忆/工件物化）与 learning_case（可配置开关，默认开）。
- Chat 工具面补齐：白名单加 `search_learning_cases`、`read_project_doc`、`search_project_context`（复用既有 service，薄封装）。
- 对外知识服务面：`reverse_lookup_requirements` 与 `report_project_state` 补进 `TOOL_SCHEMA_SNAPSHOT` 与对外文档；`@friday-ai-codes/skills` 的 friday-memory 技能文档与新检索行为对齐。
- ProjectStateApi 可检索：STATE/API 清单纳入 `grep_project` 之外的向量检索路径（经 STATE 文档物化即可，明确验收）。

### 2. LOOP — 完工沉淀与回写闭环（三链路一致）

- 公共回写服务：从 `work_item_execution_service` 抽出 write-back（飞书工作项评论 + 可选文档），落 `delivery/services/`（或等价位置）；工作流 `ai_coding` 完成、Chat `coding_graph` 建 PR 后、MCP 执行三处统一调用（节点/会话级开关，默认开且 fail-soft）。
- 自动经验沉淀：编码完成回调（`subagent/api/callbacks.py`）best-effort 触发 learning case 生成（LLM 从 TaskResult/diff/plan 提炼 outcome/root_cause/solution，赋新 `call_source`），入统一知识库；失败吞掉不反噬。
- 内置平台 Skill 两枚（RemoteTool SKILL 种子）：
  - `pre_coding_research`（编码前调研）：`route_repositories → search_rag_chunks → search_delivery_knowledge → search_learning_cases` 串行聚合；
  - `post_coding_capture`（完工沉淀）：`summarize_branch → create_learning_case → report_project_knowledge` 串行。
  两者对 Cursor（经 `/api/tools/execute/`）与容器内代理均可调。
- 审查环恢复（轻量）：PR 创建后可选触发 review（工作流节点或回调钩子），review 结论沉淀为 learning case——作为 LOOP 的增值项，范围控制在"能跑通 + 沉淀"，不做完整 review 产品化。

### 3. AGENT — 编码容器内置 MCP + Skills + 上下文对齐

- 容器内置 Friday 知识 MCP：task 侧新增 `build_knowledge_mcp_server`（进程内 SDK MCP server，HTTP 调服务端 `/api/mcp/tools/*` 白名单子集：`search_rag_chunks`/`grep_repository`/`get_repository_file`/`search_delivery_knowledge`/`search_learning_cases`/`search_project_context`/`lookup_project_by_branch`，PAT=任务 user_token 鉴权），经既有 `extra_mcp_servers`/`allowed_tools` 机制挂载；server 侧派发时下发开关与 endpoint（对齐 RemoteTool 的 config 传递方式）。排除文件 denylist 天然生效（工具层 fail-closed 已有）。
- 容器内置 skills：派发准备 workspace 时注入 Friday skills 物料（`friday-code`/`friday-memory` 精简容器版）到 `.claude/skills/`（与仓库自带 skills 共存、不覆盖）；skills 内容与根 `skills/` 包同源生成，避免两套漂移。
- 工作流编码上下文对齐：`ai_coding` 节点派发前 prepend `pack_project_context`（对齐 Chat 的 `_resolve_project_context_for_dispatch`），并确保飞书工作项原始上下文（若有 work_item）注入。

### 4. UNIFY — 工具面收口（小而关键）

- `improve_coding_plan` / `analyze_repository` 收敛到 `delegate_process_runtime`，退役 `planning_service.py` 确定性缝（分析结果作为编排输入证据）。
- 清理 `services/plan_orchestration/` 空壳目录与文档残留引用。
- Chat `create_coding_plan` 与 MCP 同名工具的落库路径书面对齐说明 + 最小趋同（不强行合表，两套 CodingPlan 全量合并显式 Out of Scope，仅要求：Chat 侧 plan 与 MCP 侧 plan 都稳定入统一知识库、可互相检索到）。

## 显式 Out of Scope（本里程碑不做）

- `chat.CodingPlan` 与 `McpCodingPlan` 合并为单一表/canonical `ArtifactVersion`（改动面大，单独立项）。
- Interaction Ledger 反哺检索（规范明确指标/留痕/日志分离，保持纯审计）。
- 完整 code review 产品化（评审 UI/规则引擎）；本里程碑只做"PR 后可选 review + 结论沉淀"最小环。
- 图片/UI 稿多模态召回；原生定时触发恢复。
- 对外知识库独立开放平台（计费/租户/配额）；对外服务 = 既有 MCP 工具面 + skills 包对齐 + schema snapshot 完整。

## 关键设计决策（预设默认，可在 plan-phase 推翻）

1. **统一知识库 = 现有 `knowledge/` 体系，不新建存储**：一切收敛到 `KnowledgeEntity` + Qdrant `delivery_knowledge` + 既有图边；"统一"的含义是**单一摄取入口（ingestion sources）+ 单一检索服务（DeliveryKnowledgeSearchService）**，各域操作态表（McpLearningCase 等）保留为写模型。
2. **容器 MCP 走服务端 HTTP 工具面复用**，不给容器直连 Qdrant/DB；鉴权用既有任务 PAT（user_token），权限/排除/脱敏天然继承。
3. **skills 单一事实源**：容器内置 skills 与 `@friday-ai-codes/skills` 包同源（构建/同步脚本或直接引用包内文件），禁止手工维护两份。
4. **回写与沉淀一律 best-effort fail-soft**：绝不阻断编码主流程；带 `initiated_by_user_id`（无则 `system`）。
5. **观测规范强制**（`.cursor/rules/observability-logging.mdc`）：新增 LLM 调用点（learning case 提炼、review）赋新 `call_source` 并登记 LOGGING-SPEC §4.1；新增召回（容器 MCP 检索、learning_case 向量检索）写 `RetrievalTrace` 并上报条数/耗时/score；新增请求入口（容器 MCP 代理调用）纳入 QPS/错误率统计；事件 `category`/`component` 齐全；凭证/上游响应脱敏。
6. **INV-6 单一写入入口**沿用：learning case 入图走 ingestion 唯一入口；回写走公共 service 唯一入口。
7. async ORM 走 `sync_to_async`；i18n 默认中文；MCP 工具 schema 变更必须同步 `TOOL_SCHEMA_SNAPSHOT` + 快照测试。

## 依赖与风险

- **风险 1**：learning case 检索底层切换后的召回质量回归——保留 API 契约 + 增加对照测试（token 版结果作为基线断言可召回集合非空）。
- **风险 2**：容器内 MCP 增加编码时延与服务端负载——工具白名单收窄 + 每任务调用配额/超时；观测埋点先行。
- **风险 3**：三链路回写开关默认值影响存量用户——工作流节点上提供显式配置，模板默认开，升级说明写清。
- **风险 4**：skills 同源机制若走构建脚本，需防 CI 漂移——加一致性测试（容器物料 == 包内文件 hash）。
- **依赖**：无外部凭证依赖（飞书/Git 均用既有凭证体系）；不依赖未交付里程碑。

## 验收面（成功标准草案，供 requirements 细化）

1. 在 Chat / 工作流节点 / MCP / 编排召回四处检索"历史经验"，能召回同一条 learning case（统一排序，向量检索）。
2. MCP 建的 coding plan 与执行 trace 摘要，可被 `search_delivery_knowledge` 召回并带关联边（plan→execution→PR）。
3. 工作流跑完 `ai_coding` 后，飞书工作项上自动出现结果评论（与 MCP write_back 同格式）；Chat 编码建 PR 后同样回写（若绑定 work_item）。
4. 任一路径编码完成后，自动产生一条 learning case（可检索），失败不影响主流程。
5. 容器内编码代理能主动调用 `search_rag_chunks` / `search_delivery_knowledge` / `search_learning_cases`（日志可见工具调用 + RetrievalTrace），且被排除文件不可见。
6. 容器内代理可见并遵循 friday-code / friday-memory skills（容器物料与 skills 包同源校验通过）。
7. 工作流路径派发的编码容器 prompt 中含 `pack_project_context` 输出（与 Chat 路径一致）。
8. `improve_coding_plan` 走 `process_runtime`（trace 中可见编排 session），`planning_service` 确定性缝删除。
9. `TOOL_SCHEMA_SNAPSHOT` 覆盖全部注册工具（含 `report_project_state`、`reverse_lookup_requirements`），快照测试通过。
10. 内置 `pre_coding_research` / `post_coding_capture` 两个 Skill 在 `/api/tools/execute/` 可调、多步 trace 完整。
