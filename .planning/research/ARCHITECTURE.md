# Architecture Research

**Domain:** v0.17.0 统一知识库与全链路联动（brownfield 集成架构：KNOW / LOOP / AGENT / UNIFY）
**Researched:** 2026-07-15
**Confidence:** HIGH（全部集成点经读码核实，引用具体文件/函数；无外部生态依赖，纯内部集成）

> 本文回答：四块新能力如何与既有架构集成——每块的集成点（文件/服务/信号）、新增组件清单（放哪、循什么模式）、数据流变化（写入→摄取→检索→消费）、建议构建顺序。写给 roadmapper 与 plan-phase 消费。

## Standard Architecture

### System Overview（改动后的目标形态）

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 消费面（读）                                                                │
│  Chat 工具白名单        编排召回              MCP 工具面          容器内代理    │
│  agents/chat_runner   recall_adapter      mcp_tools/views    task 容器 MCP │
│  (+search_learning_   (+document/         (snapshot 补全)     (新: 知识 MCP │
│   cases 等 3 工具)      learning_case)                          server)     │
└──────────┬────────────────┬────────────────────┬───────────────┬──────────┘
           │                │                    │               │ HTTP+PAT
           ▼                ▼                    ▼               ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 单一检索面：knowledge/retrieval.py DeliveryKnowledgeSearchService           │
│ （向量 + 图扩散 + bi-temporal + fail-closed 权限）                           │
├──────────────────────────────────────────────────────────────────────────┤
│ 单一摄取入口：knowledge/ingestion.py aschedule_ingestion                    │
│  sources 注册表（现有 10 个 normalizer）＋ 新增：                            │
│    learning_case / mcp_coding_plan / mcp_repository_analysis /            │
│    mcp_execution_trace                                                     │
├──────────────────────────────────────────────────────────────────────────┤
│ 存储（不新建）：KnowledgeEntity/Version/Edge (PG) + Qdrant delivery_knowledge│
│ 写模型（保留）：McpLearningCase / McpCodingPlan / chat.CodingPlan / ...      │
└──────────────────────────────────────────────────────────────────────────┘
           ▲                                     ▲
           │ 写入（沉淀）                          │ 回写（业务侧）
┌──────────┴─────────────────────────────────────┴──────────────────────────┐
│ LOOP 完工闭环（三链路统一锚点）                                               │
│  workflow: AICodingNode._finalize_and_notify（MR 后锚点，已投 task_result）  │
│  chat:     orchestration/coding_graph.create_pr_or_skip_node（已投递）      │
│  MCP:      mcp_tools/work_item_execution_service（已投 mcp_technical_plan） │
│  → 新增共用：CodingCompletionService = 飞书回写 + 自动 learning case 提炼     │
└────────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities（新增/修改总表）

| 组件 | 新增/修改 | 位置 | 职责 | 遵循的既有模式 |
|------|----------|------|------|--------------|
| learning_case normalizer | **新增** | `server/knowledge/sources/learning_case.py` | `McpLearningCase` → 知识实体（+work_item 锚双事件） | `knowledge/sources/mcp_plan.py` 双事件先例 |
| MCP 产物 normalizer ×3 | **新增** | `server/knowledge/sources/mcp_coding_plan.py`、`mcp_repository_analysis.py`、`mcp_execution_trace.py` | McpCodingPlan/McpRepositoryAnalysis/McpCodingExecutionTrace 入图 | `knowledge/sources/coding_plan.py`（单事件）/ `mcp_plan.py`（带边） |
| `EntityKind.LEARNING_CASE` | **修改** | `server/knowledge/models.py` | 新实体分类字面值 | Phase 79 PROJECT/REPOSITORY/SPACE 增量扩枚举先例（不改既有四类、无 PK 漂移） |
| sources 注册表 | **修改** | `server/knowledge/sources/__init__.py` `_NORMALIZERS` | 登记 4 个新 source_kind | 现有惰性 import 注册表 |
| `search_learning_cases` 底层切换 | **修改** | `server/mcp_tools/learning_case_service.py` | token 打分退役 → `DeliveryKnowledgeSearchService.search_similar(entity_kinds=["learning_case"])`，回填 `learning_case_payload` 外形 | 对外契约不变（`TOOL_SCHEMA_SNAPSHOT` 键不动） |
| recall_adapter 扩容 | **修改** | `server/services/process_runtime/recall_adapter.py` `RECALL_ENTITY_KINDS` | kinds 增加 `document`/`learning_case`（可配置） | 现有 adapter 只做接线不重写检索 |
| Chat 知识读工具 ×3 | **修改** | `server/agents/chat_runner.py` `_INDEXED_TOOL_NAMES` + `server/agents/tools/` 薄封装 | `search_learning_cases`/`read_project_doc`/`search_project_context` 进白名单 | RECALL-02 先例（Phase 80 把 `search_delivery_knowledge` 挂进白名单的方式） |
| 完工回写+沉淀服务 | **新增** | `server/delivery/services/coding_completion.py`（建议） | 飞书工作项评论/文档回写 + LLM 提炼 learning case，三链路统一调用，全程 fail-soft | 从 `mcp_tools/work_item_execution_service._write_results_back` 抽取；INV-6 单一入口 |
| 平台 Skill 种子 ×2 | **新增** | `server/tools/` 种子数据（RemoteTool `Source.SKILL`，config.steps） | `pre_coding_research` / `post_coding_capture` 多步串行 | `server/tools/sources/skill.py` 既有 steps 顺序执行器 |
| 容器知识 MCP server | **新增** | `task/core/knowledge_tools.py`（建议） | 进程内 SDK MCP server，HTTP 调 `/api/mcp/tools/<name>/` 白名单子集，PAT 鉴权 | 镜像 `task/core/remote_tools.py`（handler/脱敏/graceful/端点校验全套约束） |
| 容器 skills 注入 | **新增** | task 镜像构建（`task/Dockerfile` COPY `skills/skills/`）+ `task/core/runner.py` workspace 准备段 | 把 friday-code/friday-memory 物料写入 `<workspace>/.claude/skills/`（不覆盖仓库自带） | `setting_sources=["project"]` 原生加载（v0.9.0 已验证）；同源=同一仓库路径构建 |
| workflow 编码上下文对齐 | **修改** | `server/workflows/nodes/ai/coding.py` `_run_repo_coding` / `_dispatch_wave` | dispatch 前 prepend `pack_project_context` 输出 | `chat/coding_session_service.py` `_resolve_project_context_for_dispatch` + `_prepend_project_context` 逐字对齐 |
| improve/analyze 收敛 | **修改** | `server/mcp_tools/views.py`（Improve/Analyze 两个 View） | 改走 `delegate_process_runtime`，退役 `planning_service.py` 确定性缝 | `create_coding_plan` View 已走 delegate + `map_canonical_to_coding_plan` 外形兼容（UNIFY-04 先例） |
| plan_orchestration 空壳清理 | **删除** | `server/services/plan_orchestration/`（已核实仅剩 `__pycache__`） | 删目录 + 清文档引用 | — |
| snapshot 补全 | **修改** | `server/mcp_tools/serializers.py` `TOOL_SCHEMA_SNAPSHOT` | 补 `report_project_state`（已核实缺失；`reverse_lookup_requirements` 已在） | MCP schema 变更同步快照测试（既有纪律） |

## 关键核实点（问题指定的 4 项，全部读码确认）

### 核实 1：learning case 入图的 normalizer 确切契约

**契约（`knowledge/ingestion.py:26-115` 已核实）**：normalizer 是 `async def normalize(request: IngestionRequest) -> list[IngestionEvent]` 协程；hook 只传 ID（`IngestionRequest(source_kind, source_id, trigger)`），normalizer 在后台 worker 内按 `source_id` 重读源模型（`select_related` 防 async 隐式同步访问）；源缺失返回 `[]` 不 raise（`knowledge_normalize_source_missing` warning）。

`IngestionEvent` 必填字段：`kind`（EntityKind 字面值）、`origin`、`source_kind`、`source_id`、`title`、`content`（embedding 输入全文）、`payload`（结构化快照，落 `KnowledgeEntityVersion.payload`）、`space_id`、`repository_id`、`event_time`（必须 aware）、可选 `edges: tuple[EdgeSpec, ...]`（以本事件实体为 source 的出边）与 `vectorize`（默认 True）。

**natural key 定法**：`generate_entity_id(kind, source_kind, source_id)` 是实体 id 派生唯一入口（`knowledge/models.py:92-124`），规则表 locked。learning case 建议登记为：

| 字段 | 值 |
|------|-----|
| source_kind | `learning_case`（新登记进 `_NORMALIZERS` 与 natural key 规则表 docstring） |
| source_id | `McpLearningCase` UUID str（稳定业务 ID，与 `coding_plan`/`mcp_technical_plan` 同款） |
| kind | `EntityKind.LEARNING_CASE`（新字面值，见下） |
| content | `title + problem + root_cause + solution + outcome` 拼接（可直接复用模型已有 `embedding_text` 字段，`learning_case_service.py:159-172` 生成逻辑） |
| payload | `case_body`（模型已有字段） |
| event_time | `case.created_at` |

**kind 决策（预设默认，可在 plan-phase 推翻）**：新增 `EntityKind.LEARNING_CASE = "learning_case"` 而非复用 `document`。理由：`search_learning_cases` 底层切换与 recall_adapter 可配置开关都靠 `entity_kinds` 过滤实现，复用 document 会让"项目记忆/工件/PRD"与"经验案例"在同一 kind 下无法区分排序。扩枚举走 Phase 79 先例（`knowledge/models.py:45-50` 注释明确：新增字面值不改既有四类，仅扩 `generate_entity_id` 派生空间与 `kentity_kind_valid` 约束，无 PK 漂移）——需要一个 migration 更新 CHECK 约束。

**边**：复用 `mcp_plan.py` 双事件先例（`knowledge/sources/mcp_plan.py:27-102`）——`McpLearningCase` 带 `work_item_id`/`work_item_type` 与 `technical_plan` FK 时：
- 产出 work_item 锚事件（`source_id = f"{feishu_project_key}:{work_item_type}:{work_item_id}"`，注意 `McpLearningCase` 无 `feishu_project_key` 字段，需经 `technical_plan.feishu_project_key` 或 `context` 取；取不到则不建锚，只产单事件——镜像 mcp_plan 的"锚缺料只产 tech_plan"防御）；
- learning_case —`RELATES_TO`→ work_item 锚 + —`REFERENCES`→ tech_plan（`generate_entity_id("tech_plan", "mcp_technical_plan", str(technical_plan_id))`）。批内先持久化全部实体再统一处理边（阶段 B），两端实体保证存在。

**触发点**：`create_learning_case_from_technical_plan`（`mcp_tools/learning_case_service.py:87-210`）在 `acreate` 之后追加 `await ingestion.aschedule_ingestion(IngestionRequest("learning_case", str(artifact.id), "learning_case_created"))`——与 `work_item_execution_service.py:605-610` 的 lazy import 投递写法逐字对齐。LOOP 自动提炼路径写库也经同一函数（INV-6）。

### 核实 2：容器 Friday 知识 MCP 的鉴权与配置传递路径

**既有链路（全部核实）**：server 派发 metadata 顶层 `env_FRIDAY_TASK_*` 键 → runner Docker executor `TrimPrefix("env_")` 注入容器环境变量 → task `TaskConfig`（pydantic `env_prefix="FRIDAY_TASK_"`，`task/core/config.py:22-26`）自动映射 → `ClaudeRunner._execute_claude` 构建 MCP server 并挂 `mcp_servers`/`allowed_tools`（`task/core/executor.py:582-629`）。RemoteTool 先例三要素：`user_token` + `tools_endpoint` + `remote_tools`，任一为空则不挂（向后兼容降级，`task/core/remote_tools.py:130-164`）。

**新链路设计（复用同一机制）**：
1. **server 侧**：三条派发路径（`workflows/nodes/ai/coding.py:_run_repo_coding` 的 `tools_env` 段、`chat/coding_session_service.py:build_dispatch_metadata`、`mcp_tools/execution_service.py:dispatch_execution`）新增注入 `env_FRIDAY_TASK_KNOWLEDGE_TOOLS`（白名单工具 schema JSON）与 `env_FRIDAY_TASK_MCP_ENDPOINT`（`{FRIDAY_BASE_URL}/api/mcp/tools/`，与 `env_FRIDAY_TASK_TOOLS_ENDPOINT` 派生方式一致，coding.py:1594-1599 先例）。
2. **task 侧**：`TaskConfig` 加 `knowledge_tools: list[dict]` + `mcp_endpoint: str` 字段（默认空 → 不挂，零回归）；新模块 `task/core/knowledge_tools.py` 提供 `build_knowledge_mcp_server(...)`，handler POST `{mcp_endpoint}{tool_name}/`、body 直接为工具 arguments、header `Authorization: Bearer <PAT>`——逐条镜像 `remote_tools.py` 的约束（PAT 只进 header 绝不进日志、401/403/非 200/非 JSON 一律返回 `is_error` 结构化错误 return 不 raise、端点 scheme/host 校验）。在 `run_execute_mode` 经既有 `extra_mcp_servers`/`extra_allowed_tools` 参数合并挂载（与 ask_user server 并存，`executor.py:262-281` 先例；allowed_tools 排他白名单必须并入 `_BUILTIN_CODING_TOOLS`，WR-02 已有防线）。
3. **鉴权**：`/api/mcp/tools/<name>/` 的 `McpToolView` 已是 PAT fail-closed 信任边界（v0.2.0），权限/排除/脱敏天然继承，server 侧无需新鉴权代码。

**⚠️ 关键缺口（必须在 roadmap 显式决策）**：PAT 明文的可用性三链路不一致。`AICodingNode._resolve_user_pat`（coding.py:1488-1506）只在"带 PAT 的实时请求线程"能拿到明文（PAT-02：绝不从 DB 反取）；实际上：
- **MCP 链**：请求本身就是 PAT 认证，实时明文在线程内可捕获——但 `mcp_tools/execution_service.py` dispatch 路径目前**未接** ContextVar 捕获（PROJECT.md 已列为 known follow-up"chat/MCP 编码 dispatch 路径的实时明文 PAT 注入未覆盖"）；
- **Chat 链**：用户经 cookie-JWT 触发，线程内**没有** PAT 明文；
- **Workflow 链**：仅 API+PAT 触发才有；飞书事件/定时触发没有。

即：若沿用"机会性 PAT"方案，容器知识 MCP 在 Chat 链和飞书触发的 workflow 链**默认不可用**。两个选项：
- **选项 A（最小改动）**：接受降级——MCP 链补 ContextVar 捕获，Chat/workflow 无 PAT 时容器只靠 prepend 的 `pack_project_context` 文本（AGENT-03 兜底）。验收面第 5 条只对有 PAT 的链路成立。
- **选项 B（推荐，需人确认）**：派发时为发起用户铸造**短 TTL 任务级 token**（新建一条 `AccessToken`：明文只在 dispatch 内存中生成后直进 env、DB 只存 sha256、`expires_at` = 任务 timeout + 余量、任务终态回调时吊销）。不违反 PAT-02（明文从未落盘、从未从 DB 反取），且与既有"令牌即用户身份"RBAC 完全复用；但与历史决策"短 TTL 派生凭证留 v2（PATX-04）"冲突，需要在 discuss-phase 显式推翻或选 A。

### 核实 3：公共 write-back service 抽取的依赖面

`_write_results_back`（`mcp_tools/work_item_execution_service.py:457-535`）的完整依赖：

| 依赖 | 来源 | 抽取影响 |
|------|------|---------|
| `technical_plan.space`（Space 实例） | `McpWorkItemTechnicalPlan.space` FK | 中性化为参数 `space` |
| `technical_plan.feishu_project_key / work_item_id / work_item_type` | 模型字段 | 中性化为工作项三元组参数（workflow/chat 链从各自锚取） |
| `technical_plan.feishu_document_id` | 模型字段 | 可选参数（无则跳过文档 append） |
| `create_feishu_doc_client_for_project(space)` | `agents/tools/feishu_doc_tools` | 直接复用 |
| `create_feishu_client_for_project(space)` + `client.add_comment(...)` | `services/feishu.py` | 直接复用 |
| markdown 渲染 `_execution_results_markdown(tasks)` | 同文件，输入是 `McpWorkItemRepoTask` 列表 | 中性化为行数据 `list[{repo_name,status,branch,commit,mr_url,error}]`，MCP/workflow/chat 各自映射 |
| 回写状态落 `technical_plan.comment_result / retry_state / error_stage` | MCP 模型专属 | **不进公共层**——公共 service 只返回 `{document_update, comment}` 两个结果 dict，MCP 调用方自行落自家 retry_state（保留既有 partial 语义零回归） |

**建议形态**：`server/delivery/services/coding_completion.py` 内 `CompletionWritebackService.awrite_back(space, feishu_project_key, work_item_type, work_item_id, rows, *, feishu_document_id="", markdown="") -> dict`。三链路锚点：
- **MCP**：`execute_work_item_repo_tasks` 的 `_write_results_back` 改为薄包装调公共 service（行为零回归，含 `write_back` 开关）。
- **Workflow**：`AICodingNode._finalize_and_notify`（coding.py:1180 起）——MR 创建 + cross-ref 之后、`_send_result_notification` 之前挂 best-effort 段；工作项三元组从 `context.get_trigger_data("payload.*")` 或 plan 追溯链取（`workflows/services/pr_cross_reference.py` 已实现 plan_version → TechnicalPlan → WorkItem 反查，直接复用）；节点 config 加 `write_back_feishu` 开关（模板默认开）。
- **Chat**：`orchestration/coding_graph.py:create_pr_or_skip_node`（:561 起）——PR 创建/skip 之后；Chat 会话多数无绑定 work_item，取不到三元组即 no-op（fail-soft）。

### 核实 4：workflow `ai_coding` prepend `pack_project_context` 的注入点

Chat 权威基线（`chat/coding_session_service.py:238-301, 404-408`）：`dispatch_coding_task` 在构建 metadata 后、dispatch 前，调 `_resolve_project_context_for_dispatch`（定位项目：`conversation.bound_project` 优先 → `(repository_id, branch_name)` 反查 `initiatives.ProjectBranch`）→ `pack_project_context(project, user, query=branch_name, conversation_id=...)` → `redact_secrets_in_text` → 注入 `env_FRIDAY_TASK_PROJECT_CONTEXT` + `_prepend_project_context(prompt, context)` 拼 prompt 头。全程 fail-soft 返回 ""。

**workflow 注入点**：`AICodingNode._run_repo_coding`（coding.py:1508 起）——`prompt = self._build_coding_prompt(...)` 之后、`DispatchTask` 构建之前，加同款 best-effort 段：
- 项目定位：workflow 无 conversation，两级 fallback——① `(repository.id, branch_name)` 反查 `ProjectBranch`（直接复用 `_lookup_project_by_branch`，建议把它从 chat 模块提到共享位置或在 initiatives 侧暴露）；② trigger 的 work_item → 项目（若 Phase 78 建立了 work_item↔project 关系边）。
- user 归因：`workflow_execution.triggered_by`（callbacks.py `_resolve_initiated_user` 同款权威来源）；packer 内置 visibility fail-closed 不能绕过。
- 注意 per-repo 粒度：`_run_repo_coding` 是逐仓调用，多仓场景 packer 会被调 N 次；`pack_project_context` 内部有 RAG 召回，建议在 `_dispatch_wave` 层按 (project, branch) 解析一次、逐仓复用文本（省 token 与时延）。
- 复用 `_prepend_project_context` 拼接函数（从 `coding_session_service.py:294-301` 提为共享 helper，避免两处漂移）。
- wave 推进路径 `_dispatch_next_wave` 走同一 `_dispatch_wave`，天然覆盖（不造两套）。

## Architectural Patterns

### Pattern 1: 触发点只投 ID，normalizer 后台重读（KNOW 全部入图沿用）

**What:** 业务写入点只调 `aschedule_ingestion(IngestionRequest(source_kind, source_id, trigger))`（`transaction.on_commit` + background runner，异常全吞）；重逻辑全在 normalizer。
**When to use:** 所有 4 个新 normalizer + LOOP 自动 learning case 的入图。
**Trade-offs:** 最终一致（非同步入图）；换来主流程零阻塞、幂等可重触发（六步版本翻转 + hash 短路已内建）。

### Pattern 2: 三链路共用完成锚点服务，锚点在"MR 已知"之后（LOOP）

**What:** 回写与沉淀不挂容器回调（callbacks.py `_handle_completed`），而挂三条链路各自的"MR 结果已知"锚点——workflow `_finalize_and_notify`、chat `create_pr_or_skip_node`、MCP `execute_work_item_repo_tasks`。这正是 INGEST-02 时序防线的既有结论（coding.py:1247-1249 注释："归档不挂容器回调"），学习案例需要 mr_url/diff，同理。
**When to use:** `CompletionWritebackService` 与自动 learning case 提炼共用同一组锚点（可合成一个 `on_coding_completed` 编排函数，两步各自独立 try/except）。
**Trade-offs:** 三处接线 vs 一处回调；但回调时刻拿不到 MR 结果，且回调 5xx 会触发重试风暴（Pitfall 4 已有教训），锚点方案是既有已验证路径。

**自动提炼的实现要点**：LLM 从 TaskResult/diff/plan 提炼 outcome/root_cause/solution → 落 `McpLearningCase`（复用/泛化 `create_learning_case_from_technical_plan`，workflow/chat 链无 `McpWorkItemTechnicalPlan` 时 `technical_plan`/`context` FK 允许为空——需核对模型字段 null 约束，必要时小 migration）→ 经核实 1 的 ingestion 入图。新 LLM 调用点赋新 `call_source`（如 `learning_case_extraction`）登记 LOGGING-SPEC §4.1；带 `initiated_by_user_id`（workflow 链用 `triggered_by`，无则 system）。

### Pattern 3: 容器能力 = 服务端 HTTP 工具面复用 + env 三要素开关（AGENT）

**What:** 容器不直连 Qdrant/DB；一切知识能力经 `/api/mcp/tools/*`（PAT fail-closed、排除文件、脱敏天然继承）。挂载由"endpoint + token + 工具清单"三个 env 控制，任一为空整体降级不挂（零回归）。
**When to use:** `build_knowledge_mcp_server`；未来任何容器新能力同款。
**Trade-offs:** 每次工具调用一跳 HTTP（时延 + 服务端负载）——用白名单收窄（7 个读工具）+ handler 60s timeout（remote_tools.py 先例）+ 观测埋点先行（新请求入口纳入 QPS/错误率）缓解。

### Pattern 4: skills 单一事实源 = 构建期从仓库同一路径 COPY（AGENT）

**What:** `skills/skills/{friday-code,friday-memory}`（各为 SKILL.md + references/，已核实）在 task 镜像构建时 COPY 进镜像（如 `/app/friday_skills/`）；运行时 `task/core/runner.py` 在 `GitOperations.setup()`（clone + prune，`task/git_ops/operations.py:99-117`）之后把物料复制进 `<workspace>/.claude/skills/`（目录已存在同名 skill 时跳过，不覆盖仓库自带）；`setting_sources=["project"]` 原生加载（executor.py:597，v0.9.0 已验证）。
**When to use:** 容器 skills 注入。**不要**走 env 传输（SKILL.md + references 体积会撞 ARG_MAX，sdk_resume transcript 已有此压力先例）。
**Trade-offs:** skills 更新需重建 task 镜像——可接受（skills 与镜像同 repo 同 release 节奏）；加一致性测试断言"镜像内物料 == `skills/skills/` 文件 hash"（风险 4 的 CI 防漂移）。注意精简容器版：friday-memory 的 setup 向导段对容器无意义，若需裁剪则用构建脚本生成"容器版"，同样以 `skills/` 包为唯一输入。

## Data Flow

### 写入 → 摄取 → 检索 → 消费（KNOW 打通后）

```
写入（各域写模型，不动）            摄取（单一入口）             检索/消费（单一检索面）
McpLearningCase ──┐
McpCodingPlan   ──┤  aschedule_ingestion      DeliveryKnowledgeSearchService
McpRepoAnalysis ──┼─→ (source_kind, id)  ──→  KnowledgeEntity + Qdrant ──┬→ Chat 工具（白名单+3）
McpExecTrace    ──┤   normalizer 后台          delivery_knowledge        ├→ 编排召回（kinds+2）
chat.CodingPlan ──┤   六步版本翻转                                        ├→ MCP search_* 工具
TaskResult      ──┘   （已有）                                            └→ 容器知识 MCP（新）
```

变化点：① `create_learning_case` 写库后新增投递；② MCP `execution_service` 建 trace / `create_coding_plan` 落库后新增投递；③ `search_learning_cases` 读路径从"全表扫 + token 打分"（`learning_case_service.py:213-245`，`order_by(-created_at)[:200]` 内存打分）切到向量检索 + 按 source_id 回捞 `McpLearningCase` 行渲染既有 payload 外形。

### LOOP 完工闭环（新）

```
容器 completed 回调（callbacks.py，不改）
  └→ 各链路 MR 锚点（finalize/_create_pr/execute_tasks）
       ├→ [已有] task_result 入图（aschedule_ingestion）
       ├→ [新] CompletionWritebackService.awrite_back  → 飞书评论 + 文档 append
       └→ [新] LearningCaseExtractor（LLM, best-effort）→ McpLearningCase → 入图
```

### AGENT 容器内数据流（新）

```
server dispatch (env: MCP_ENDPOINT + USER_TOKEN + KNOWLEDGE_TOOLS)
  → runner env 注入 → TaskConfig → build_knowledge_mcp_server
  → agent 调 mcp__friday-knowledge__search_rag_chunks 等
  → HTTP POST /api/mcp/tools/<name>/ (Bearer PAT)
  → McpToolView（RBAC + 排除 fail-closed + RetrievalTrace）→ 结构化结果回容器
```

## 建议构建顺序（依赖分析）

| 序 | 块 | 内容 | 依赖 | 可并行 |
|----|-----|------|------|--------|
| 1 | KNOW-基座 | `EntityKind.LEARNING_CASE` + migration + `learning_case` normalizer + `create_learning_case` 投递 + `search_learning_cases` 底层切换（含对照测试） | 无 | 与 2、4 并行 |
| 2 | KNOW-MCP 产物 | 3 个 MCP 产物 normalizer + 各写入点投递 | 无（不依赖 1） | 与 1、4 并行 |
| 3 | KNOW-消费面 | recall_adapter kinds 扩容 + Chat 白名单 3 工具 + snapshot 补 `report_project_state` + skills 包文档对齐 | 依赖 1（learning_case kind 存在才有意义） | 内部三件可并行 |
| 4 | LOOP-回写 | 抽取 `CompletionWritebackService` + MCP 改薄包装（零回归）+ workflow/chat 锚点接线 + 节点开关 | 无 | 与 1、2 并行 |
| 5 | LOOP-沉淀 | 自动 learning case 提炼（LLM + call_source）+ 三锚点接线；`McpLearningCase` FK 放松（如需） | 依赖 1（入图通路）+ 4（锚点管线成型） | — |
| 6 | LOOP-Skill 种子 | `pre_coding_research`/`post_coding_capture` 两个 RemoteTool SKILL 种子 | 弱依赖 1（`search_learning_cases` 已切换后体验才对）；机制本身无依赖 | 与 5 并行 |
| 7 | AGENT-决策+MCP | **先决策 PAT 方案（选项 A/B，见核实 2）**→ task `knowledge_tools.py` + TaskConfig 字段 + 三派发路径 env 注入 + 观测埋点 | 依赖 PAT 决策；工具面本身已存在，不依赖 KNOW（但 KNOW 完成后容器能查到 learning case） | 与 1–6 并行（除决策） |
| 8 | AGENT-skills+上下文 | 镜像 COPY skills + runner 注入 + 一致性测试；`ai_coding` prepend pack_project_context | 无硬依赖 | 两件互相独立，可并行 |
| 9 | UNIFY | improve/analyze 收敛 delegate + 退役 `planning_service` 缝 + 删 `plan_orchestration/` 空壳 + 文档 | 无（`map_canonical_to_coding_plan` 复用需保留在别处或随迁） | 全程可并行，建议早做（减少后续 rebase 面） |
| 10 | 收口验收 | 快照测试全绿 + 四处检索同一 learning case 的端到端验收 + review 沉淀增值项（可选） | 依赖 1–7 | — |

关键路径：**1 → 3/5 → 10**；**7 的 PAT 决策**是唯一需要提前到 discuss-phase 的架构决策（影响 AGENT 全块验收口径）。

## Anti-Patterns

### Anti-Pattern 1: 为 learning case 新建向量集合或平行检索服务

**What people do:** 给 learning case 单独建 Qdrant collection / 独立检索类。
**Why it's wrong:** 与"统一排序"目标直接冲突（历史经验必须与 tech_plan/document 同分布可比）；且违背 milestone 锁定的"不新建存储"决策。
**Do this instead:** 入 `delivery_knowledge` 同一 collection，靠 `entity_kinds` 过滤；`McpLearningCase` 表保留为写模型。

### Anti-Pattern 2: 回写/沉淀挂容器回调 `_handle_completed`

**What people do:** 在 callbacks.py 里加 write-back 与 learning case 提炼。
**Why it's wrong:** 回调时刻 MR 尚未创建（workflow 的 MR 在节点 resume 段才建），拿不到 mr_url；且回调 handler 已有"绝不 5xx / 重试风暴"硬约束，往里加重逻辑会放大风险。INGEST-02 已为此把归档锚点移到 MR 之后（coding.py:1247 注释）。
**Do this instead:** Pattern 2 三锚点方案。

### Anti-Pattern 3: normalizer 直接调 graph_store / 同步写实体

**What people do:** 在新 normalizer 里绕过 `ingest_events` 自己建边或写 KnowledgeEntity。
**Why it's wrong:** 破坏六步版本翻转/四层幂等/边精细置位不变量；`apply_edge_specs` 是 chunk/实体边写入唯一通路（ingestion.py:356-374 明文）。
**Do this instead:** normalizer 只返回 `IngestionEvent(+EdgeSpec)`，写入全交给核心。

### Anti-Pattern 4: 容器 MCP handler raise / 打印 token

**What people do:** 新 handler 遇 401 raise、或把 endpoint/PAT 写日志。
**Why it's wrong:** raise 会崩容器毁掉整次编码（RTOOL-04 graceful 教训）；PAT 入日志违反脱敏铁律。
**Do this instead:** 逐条镜像 `remote_tools.py` 的 return-not-raise + 日志只记 tool 名/status。

### Anti-Pattern 5: 手工维护"容器版 skills"第二份物料

**What people do:** 在 task/ 下另写一套精简 SKILL.md。
**Why it's wrong:** 与 `@friday-ai-codes/skills` 包必然漂移（风险 4）。
**Do this instead:** 构建期从 `skills/skills/` 同源 COPY/生成 + hash 一致性测试。

## Integration Points

### Internal Boundaries（本里程碑触碰的边界汇总）

| Boundary | Communication | Notes |
|----------|---------------|-------|
| 业务写模型 ↔ knowledge | `aschedule_ingestion`（ID-only，on_commit 异步） | 4 个新 source_kind；normalizer 全在 knowledge 侧，业务侧只加一行投递 |
| mcp_tools ↔ delivery | 抽取后 `mcp_tools/work_item_execution_service` import `delivery.services.coding_completion` | 方向正确（delivery 是领域脊柱层，mcp_tools 是入口层）；注意 lazy import 防循环（既有惯例） |
| workflows 节点 ↔ initiatives | `_lookup_project_by_branch` + `pack_project_context` | 建议共享 helper 上提，避免 workflow import chat 模块（chat 不应被 workflow 依赖） |
| server ↔ runner ↔ task | metadata 顶层 `env_FRIDAY_TASK_*` string 键 | runner 只透传非空 string；新键必须顶层（nested dict 被忽略——PF-06 教训，coding.py:1553-1556 注释） |
| task 容器 ↔ server 工具面 | HTTP + Bearer PAT，`/api/mcp/tools/<name>/` | PAT 可用性三链路不一致是本里程碑唯一悬置架构决策（核实 2） |
| 快照契约 | `TOOL_SCHEMA_SNAPSHOT` + 快照测试 | 已核实缺 `report_project_state`（urls.py:88 已注册但 snapshot 无键）；`reverse_lookup_requirements` 在 snapshot（:618）但未进对外 skills 文档 |

## Sources

- 一手代码核实（本文全部断言的依据）：`server/knowledge/ingestion.py`、`server/knowledge/models.py`（generate_entity_id 规则表 + EntityKind）、`server/knowledge/sources/{__init__,coding_plan,mcp_plan}.py`、`server/mcp_tools/{work_item_execution_service,learning_case_service,orchestration_delegate,planning_service,serializers,views,urls}.py`、`server/workflows/nodes/ai/coding.py`、`server/chat/coding_session_service.py`、`server/subagent/api/callbacks.py`、`server/orchestration/coding_graph.py`、`server/services/process_runtime/{recall_adapter,builtin_processes}.py`、`server/services/project_context_packer.py`、`server/agents/chat_runner.py`、`server/tools/sources/skill.py`、`task/core/{executor,config,remote_tools,runner}.py`、`task/git_ops/operations.py`、`skills/package.json` 与 `skills/skills/` 目录
- 里程碑与项目上下文：`.planning/MILESTONE-CONTEXT.md`、`.planning/PROJECT.md`
- 空壳确认：`server/services/plan_orchestration/` 仅剩 `__pycache__`（ls 核实）

---
*Architecture research for: Friday AI v0.17.0 统一知识库与全链路联动*
*Researched: 2026-07-15*
