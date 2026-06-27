# Friday AI

## What This Is

Friday AI 是一个 AI 驱动的敏捷开发自动化系统：它把飞书（Lark）项目管理中的需求自动转化为代码合并请求（MR/PR），从需求触发、AI 技术方案生成、到容器化 AI 编码代理执行、再到自动建分支提交 PR，全链路可编排、可观测。面向需要把"需求→代码"流程自动化的研发团队与平台工程师，自托管部署（Docker Compose / k8s）。

系统由四个组件构成：Django 后端（`server/`，REST + WebSocket + 工作流引擎 + 代码智能/RAG）、Vue 3 前端（`web/`，控制台/流程编辑器/对话）、Go 运行器（`runner/`，调度并在 Docker/k8s 中运行任务容器）、Python 任务执行器（`task/`，容器内运行 claude-agent-sdk 编码代理）。

## Core Value

让团队"开箱即用、安全地"把需求自动变成代码：用户能顺利完成首次部署与登录、配好必备的 AI 供应商，然后让工作流把飞书需求自动跑成 PR。如果第一步进不去（登录/配置），后面一切都无从谈起。

## Current State

**Latest shipped:** v0.16.0 项目工作区（飞书文档双向同步 + IDE 上下文闭环 + feature list 交付流水线）（2026-06-26，审计 tech_debt，37/37 需求，Phases 82–89）。里程碑 v0.1.0–v0.16.0（Phases 1–89）均已交付，详见 `.planning/MILESTONES.md` 与 `.planning/milestones/`。**当前在建：v0.16.1 统一 AI 技术方案生成（图编排归一 + 插槽式澄清拼接 + 能力完善）（Phases 90+，planning）。**

里程碑演进：v0.7.0 方案编排（需求 → 主方案）→ v0.8.0 多仓串行编码 → 融合 PR → v0.9.0 SDD / OpenSpec 支持 → v0.10.0 操作审计治理 → v0.11.0 开放与协作。近六个里程碑要点：

- **v0.5.0 索引地基 + 排除文件**：排除配置单一事实源 + 单一匹配器 `is_excluded` 全链路 fail-closed（索引/RAG/MCP/grep/agent/容器六面不可见）；统一删除入口 `purge_file` + 两种 purge 模式（普通排除 / 敏感清理）+ 对账清理 UI；敏感文件 AI 识别建议名单；commit 历史 RAG 索引 + `ChunkRegistry` 行号回填 + `file:line→chunk` 反查；多仓 Git 凭证统一池（`GitInstanceCredential`）+ MCP 多仓检索参数。
- **v0.6.0 领域脊柱 + 知识补全**：新增 `delivery` app 立起以飞书 work item 为中心的操作态脊柱——canonical `WorkItem` + 单一 `WorkItemService.upsert` 入口 + source-of-truth 三分类 + `WorkItemSyncState`/`WorkItemRelation`（字段派生）/`WorkItemStatusEvent`/`WorkItemCommentEvent`（append-only 评论流 + 当前树投影）；`Document`/`DocumentVersion`（外部飞书/内部生成）+ `feishu_document` normalizer + `REFERENCES` 边；Release 账本宽容模型 + 飞书 Bitable adapter 骨架；(看板URL+MR URL) 一键摄取编排；历史 diff 冻结 + bi-temporal 失效对账（PF-08）；评论入图 + 片段→需求反查 API/MCP；截图识别需求（多模态 LLM）。飞书接口前置修复 PF-09/10/11/12 已落地。
- **v0.7.0 方案编排（需求 → 主方案）**：把「需求 → 一份高质量多仓主技术方案」做成可复用的 map-reduce 多 agent 编排引擎——`PlanOrchestrationEngine`（入口无关 + 4 可注入 stage 协议）+ `PlanSession` 8 态状态机（拆分→路由→召回→澄清→并行调研→架构师融合，可持久化可恢复）；canonical `TechnicalPlan`/`PlanVersion` + `TechnicalPlanService` 唯一写入入口（INV-6）+ 旧 3 路径软链/lazy 迁移；`RepoRouterV2` 路由 + `DeliveryKnowledgeSearchService` 召回接入；filter_then_container 并行调研子 agent（`RepoResearchTask`/`PartialPlan` + 单仓重试 + 重索引 stale 重跑）；架构师融合 + 结构化 `MergedPlan` + `PlanValidator`（5 类跨仓校验）+ 跨仓依赖 DAG 显式建模；HITL `Clarification` 澄清回路；§15 事件 taxonomy 全程持久化；工作流入口 + Chat 薄封装复用同一 engine。前置修复 PF-01/02 已落地。审计 passed（19/19 需求、INV-2/5/6 成立）。
- **v0.8.0 多仓串行编码 → 融合 PR**：把 v0.7 产的 `MergedPlan.execution_plan` + 跨仓依赖 DAG 真正落成多仓代码——前置修复 PF-06（workflow 编码 `_run_repo_coding` dispatch env 对齐 chat 基线：git token + branch strategy + SSH→HTTPS，私有仓 clone + 正确目标分支）+ 通用 resume 回流通路 `adrive_plan_session_to_pause_or_terminal`（节点/工具/回调三处同源，消化 v0.7 audit D-2）；`RepoCodingTask` 操作态模型（plan_version/repository/wave/`depends_on` M2M self DAG/`produced_artifacts`/`follow_openspec` SDD 预留）+ 消费 `execution_plan[].dependencies` 经 graphlib Kahn 拓扑分层成 wave（消化 PF-07，不再全并行）；`RepoCodingTaskService` 单一写入入口（INV-6）+ `aadvance_coding_waves` wave 推进（回填→传递闭包阻断→决策，wave N done → N+1，失败隔离不死锁）；`AICodingNode` 按 wave 分批 dispatch + callback 重入自驱（不另造调度）；上游产物提取（OpenAPI/契约/diff）落 `produced_artifacts` → 注入下游 wave prompt/`global_context`；各仓 MR `target_branch` 锚定各仓 `default_branch` + 跨仓 PR cross-ref + 追溯 `TechnicalPlan`/`WorkItem`（`pr_cross_reference.py`，≥2 守门 fail-soft）；编码遇阻 task 侧 `ask_user` 抛 question 给人（心跳保活容器 RUNNING）+ orchestrator resume，非全自动 replan。审计 passed（9/9 需求、integration_ok、Nyquist 5/5）。
- **v0.9.0 SDD / OpenSpec 支持（重型）**：让 spec-driven development 成为可治理过程资产——SDD 仓库索引后检测 `openspec/` 自动打标 `facets["methodology"]="SDD"` + 前端徽标；SDD 仓方案融合（`ArchitectMergeAdapter._handle_pass` best-effort 挂接）逐仓产 openspec spec draft，落 `SddSpec` 脊柱 + `Document(sdd_spec, internal_generated)` 经 `DocumentService.create_internal_spec`/`SddSpecService` 双单一写入入口（INV-6），关联 WorkItem/PlanVersion + emit `spec.drafted`；spec 完整状态机（draft→in_review→approved→implemented→archived，单一 service 入口、非法流转 fail-loud、条件更新防双推进）+ `SddSpecReview` 不可篡改评审记录（approve/reject 单一事务驱动状态）+ `/api/specs/` REST（superuser fail-closed 分流）+ spec 治理前端（列表/详情/状态流转/评审时间线）；编码前置 gate（`follow_openspec=True` 仓 `_dispatch_wave` 前校验 `SddSpec.status==APPROVED`，未批准/异常 fail-closed `mark_gate_blocked` 拦截 + 单仓隔离 + 下游阻断）+ openspec 指引注入（dispatch `env_FRIDAY_TASK_FOLLOW_OPENSPEC` → task `system_prompt` openspec 段 + `setting_sources=["project"]` 原生加载 `.claude/skills`）；spec↔实现 PR 关联（`_finalize_and_notify` best-effort 回填 `link_implementation_pr` + approved→implemented）+ 交付验收视图（spec→WorkItem→PR 追溯面板，fail-soft 降级）。非 SDD 仓全链路零回归。审计 passed（11/11 需求、integration_ok、INV-6/INV-2 成立）。
- **v0.10.0 操作审计治理**：立起统一横切审计能力——新建零业务依赖的 `audit` Django app + `AuditEvent` append-only 不可篡改模型（actor 标量软引用 + 双时间戳 + 5 查询索引 + 模型层 save/delete 守护）+ `AuditService.emit/aemit` 唯一写入入口（INV-6）+ 入口强制脱敏（key-name / 值级密钥正则 / 高熵）+ fail-soft 吞异常不阻断主操作 + 稳定 action taxonomy；全量覆盖敏感操作 emit——身份与权限类（accounts 建用户/启停/改资料/首启 superuser + projects/members 成员增删改/角色变更 + 空间配置/仓库权限）+ 凭证与数据治理类（Provider/Git 实例/per-repo Git/PAT/飞书凭证与同步 + 排除规则增删 + v0.5 `purge` 埋点收口统一表），凭证字段 DB 绝无明文；审计查询 REST（`/api/audit/`，IsSuperUser fail-closed、只读、过滤 + 分页）+ CSV/JSON 流式导出 + `/admin/audit` superuser 审计页（过滤/表格/分页/before-after 详情弹窗/导出/侧栏入口/i18n）。审计 passed。
- **v0.11.0 开放与协作**：对外开放与协作层——内部工具调用（RAG/grep/仓库分析）经 §15 事件 taxonomy 映射为 OpenAI 兼容流式 progress/`reasoning_summary`（INV-5 非 CoT、不误用 `tool_calls`）；新增 Anthropic 兼容 `/v1/messages` 端点（非流式 + SSE 流式 + thinking block trace）；飞书机器人对话改走原生 CardKit 流式增量卡片（替代 PATCH 全量替换）；工作流自动建群节点（建群 + 拉人 + chat_id 写回 `WorkItem.feishu_chat_id` fail-soft）。审计 passed（6/6 需求，INV-5/INV-6 成立）。

**已知 follow-up（tech debt）：** v0.2.0 chat/MCP 编码 dispatch 路径的实时明文 PAT 注入未覆盖、RTOOL-02/03/04 容器端 E2E 待真实环境验收；v0.8 多仓 wave 编码/PR/HITL 的真实 runner+Docker 容器端到端验收待真实环境；chat 编码入口（`coding_session_service`）的 cross-ref / 遇阻 HITL 接线为 follow-up（helper 入口无关已就绪）；Phase 26 遗留 `test_batch_pr.py` 5 例 stale patch target 失败待修；部分里程碑的纯观感人工验收（UAT）顺延。详见 `.planning/MILESTONES.md` 与 `.planning/STATE.md`。

**Codebase 现状：** 后端 Django 5.1+/Python 3.14（adrf + channels）、前端 Vue 3 + TS + Tailwind 4、Go runner、Python task executor；测试基线后端 ~520 个 `test_*.py`、前端 ~130 个 spec。完整代码地图见 `.planning/codebase/`。

## Current Milestone: v0.16.1 统一 AI 技术方案生成（图编排归一 + 插槽式澄清拼接 + 能力完善）

> v0.16.0 项目工作区（Phases 82–89）已 shipped + 归档（审计 tech_debt，37/37 需求）。本里程碑为 **patch 级优化/统一**（非新功能）：把分散的多套「AI 技术方案生成」统一到唯一图编排底座 `plan_orchestration`，并完善澄清/拆分能力 + 引入插槽式编辑范式。Phases 90+ 续号。需求 18 条见 `.planning/REQUIREMENTS.md`。

**Goal:** 把当前 4 套分散的「AI 技术方案生成」统一到唯一图编排底座 `plan_orchestration`（工作流 / 对话 / MCP 三入口归一、废弃旧 LangChain 单 agent `ai_plan_generation`），并完善该能力——LLM 跨仓拆分、结构化交互式澄清 + 多轮 resume 续推、方案推送渲染；引入「插槽式（形状端口磁吸）」工作流编辑范式，让澄清等子环节像拼图一样拖拽拼接到方案节点上。

**Target features（暂拟 Phase 90 起 / 4 类需求）:**
- **入口归一（UNIFY）**：工作流模板切 `ai_plan_research`、废弃 `ai_plan_generation`；MCP 方案生成 delegate 到 plan_orchestration；对话澄清挂起收口单一来源；done 出口接「推送方案到群」干净渲染。
- **澄清能力 + 出口面（CLARIFY）**：`Clarification` 结构化扩展（多问题/单多选/推荐 + 多答案）+ LLM 结构化问题 + 统一 `ask_clarification` 提问能力 + 双出口面（会话内联前端卡 / 工作流·群飞书交互卡）+ 答复回流 resume 续推 + 多轮。
- **插槽式编辑器（SLOT）**：端口「形状(shape)」语义 + `WorkflowGraphValidator` 形状校验；`ai_plan_research` 暴露 clarify/resume 插槽 + 「澄清卡」节点；@vue-flow 形状磁吸（对上才连）；澄清节点作为方案节点的附着子节点可视编组、可下接发飞书群聊。
- **拆分完善（DECOMP）**：`decompose` 从按行切升级为 LLM 跨仓业务线/模块/前后端拆分。

**Key context:** `plan_orchestration` 已是统一底座（**自研 PlanSession 状态机，非 langgraph**；工作流 `ai_plan_research` + 对话 `start_plan_research` 已在用；resume / 多 claude code 容器并行调研 / 架构师融合汇总均已具备；下游 `human_approval`/`ai_coding` 已兼容 `MergedPlan`+wave）。已落地并验证：LLM 结构化澄清问题生成器 + `CallSource.PLAN_CLARIFICATION`、交互澄清卡 `build_clarification_card`（飞书 App 渲染 2.0 表单、网页版不支持）、通知/方案卡渲染修复（markdown 组件 + `•`）。**缺口**：澄清「答→续推」目前仅对话有、工作流侧缺发卡/收答闭环；`Clarification` 仅单 question/answer 需结构化；`decompose` 仍是 stub。**插槽=端口 shape 语义 + 磁吸（输入输出形状对应才能拼）**，反馈环 resume 复用引擎「非 default handle 回边=合法反馈环」（同审批驳回）。约束沿用：INV-6 单一写入、async ORM 走 `sync_to_async`、脱敏不可绕过、新增 LLM 赋 `call_source`、新增召回写 `RetrievalTrace`、i18n 默认中文；**最大化复用 `plan_orchestration`，严禁重复造**。

**候选后续方向（v2）：** 方案文本流式卡片（STREAM，cardkit/v1 打字机）、插槽系统推广到更多节点类型（SLOTX，通用带槽节点 + 适配拼图生态）。

## Latest Milestone: v0.15.0 项目（交付上下文聚合根）— ✅ SHIPPED 2026-06-26（审计 passed）

> 6 个 Phase（76–81）线性交付，38/38 需求满足、integration_ok、逐 Phase 零新增回归。完整设计与调研基线见 `.planning/project-aggregate/MILESTONE-PROPOSAL.md`、归档见 `.planning/milestones/v0.15.0-{ROADMAP,REQUIREMENTS,MILESTONE-AUDIT}.md`。下一里程碑待 `$gsd-new-milestone` 立项（新 `REQUIREMENTS.md` 届时生成）。

**Goal（已达成）:** 把"需求 → 代码"全链路上下文统一收口到一个**在线协作的「项目」聚合根**——每个飞书"项目跟踪"看板对应一个项目，项目聚合需求/工件依赖/工作项(story·缺陷)/记忆/关联知识/仓库/分支/PR；项目对成员共享可参与，飞书人员经身份映射关联到 Friday 用户并带身份（主R/PM/前端/后端/测试）；任何对话、Cursor 编码、Agent 调用都能从项目加载完整上下文并把沉淀写回。

**Delivered features（6 Phase）:**
- **Phase 76 命名腾挪**：把现有 `projects.Project`（前端"空间"，历史命名债）重命名为 `Space`，全栈 `project→space` 引用一致更新，腾出 `Project` 名给新聚合根；数据零丢失、行为/测试零回归（独立前置）。
- **Phase 77 项目聚合根 + 身份映射 + 成员协作**：`Project` 聚合根（隶属 Space + 关联飞书项目跟踪 + 状态机 开发中/归档/终止）+ 飞书人员↔Friday 用户多对多映射 + 项目成员(多对多 + 身份角色) + CRUD/权限/实时推送。
- **Phase 78 飞书触发建项目 + 看板枚举 + 工作项组合**：飞书项目跟踪枚举子项/成员封装 + 事件幂等建项目(拉人带身份) + `create_project` 工作流节点 + WorkItem(story/缺陷)关系边挂入。
- **Phase 79 工件/依赖项 + 知识关联**：`ArtifactType` 可配置注册表(默认 8 类，后台增删禁用) + `Artifact` 实例(多载体) + 在线查看 + 文字载体 RAG/UI 稿仅元数据 + 项目↔知识多对多。
- **Phase 80 项目记忆 + MR 实体 + 召回接入会话**：项目记忆(自由文本 + 贡献者/时效，人工为主 + LLM 提议确认) + `MergeRequest` 实体 + 入站 webhook 状态同步 + context packer(grep+RAG) + 接入 chat runner。
- **Phase 81 Cursor 回流 + 前端项目工作台**：MCP 分支→项目反查召回 + Cursor rules 模板 + 沉淀上报写回 memory(归因/脱敏/质量门槛) + 项目列表/详情工作台/记忆编辑/工件类型管理页。

**Key context:** **命名已锁定大重构**（Project→Space，76 作独立前置 Phase，与新功能解耦）。**不做迭代实体**（用户决策：另一迭代 = 新建项目；"看历史迭代" = 项目↔项目关联链回看）。**记忆为自由文本**（条目 + 时间戳/贡献者，人工为主 + LLM 提议草稿经人工确认入库，不自动直接写）。**工件 RAG 物理边界**：文字载体（飞书文档/表格/md/Spec）可全文 RAG；UI 稿（figma/mastergo）是图形链接仅存元数据，多模态正文留 v2。**最大化复用脊柱**：`KnowledgeEntity/KnowledgeEdge`（交付知识图谱，bi-temporal/版本/边）做项目↔知识与项目间关联、`delivery.WorkItem`（三元组）做 story/缺陷、`delivery_knowledge` 做召回、`projects.Project`(→Space) 做组织单元。**三个净新增空白**：飞书人员↔Friday 用户映射（主R/协作/归因/Cursor 上报前置）、通用项目记忆、MR 实体 + 入站 webhook。**飞书无整板枚举 API**（项目跟踪子项/成员经子项关联字段派生逐项收集，拿不到降级半自动）。**Cursor 回流走 MCP + git + 上报 API**（专用插件留 v2），上报写回须认证 + 归因 + 脱敏 + 质量门槛。脱敏不可绕过；后台任务带 `initiated_by_user_id`；新增 LLM/召回埋点；异步 ORM 走 `sync_to_async`；i18n 默认中文。

**候选后续方向（v2）：** UI 稿多模态/figma 正文召回（PROJX-01）、结构化记忆 + 时效降权 + 矛盾消解（PROJX-02）、记忆全自动提炼无需人工确认（PROJX-03）、Cursor 专用插件/hook 主动采集（PROJX-04）、项目级看板可视/燃尽/进度（PROJX-05）。

## Requirements

### Validated

<!-- 已上线并被依赖的能力。锁定项，变更需显式讨论。 -->

- ✓ **工作流引擎**：以 DAG 编排可插拔、自动注册的节点，支持调度/重试/暂停/调试 — existing (`server/workflows/engine/`)
- ✓ **AI 编码执行**：编码节点经 WebSocket 派发到 Go runner，由 runner 在容器中运行 `friday-task` 代理，结果经 HTTP 回调持久化 — existing (`runner/`, `task/`)
- ✓ **飞书集成**：事件 webhook（签名校验）、IM 通知、文档读取、工作流状态回写 — existing (`server/feishu/`, `server/services/feishu_*.py`)
- ✓ **Git 平台集成**：GitHub / GitLab / 通用 Git（克隆/diff/提交、建 MR/PR），凭证按仓库加密存库 — existing (`server/services/git_platform/`)
- ✓ **多 Provider 配置**：5 种 ProviderType（anthropic / openai_responses / openai_chat / gemini / ollama），四层优先级解析（节点>对话>项目>系统），凭证 Fernet 加密存库 — existing (`server/services/provider_config.py`, `system.models.ProviderCredential`)
- ✓ **Claude Code 编码配置**：系统级 anthropic 凭证 + opus/sonnet/haiku 三档模型映射 — existing (`SettingKeys.CLAUDE_CODE_CONFIG`)
- ✓ **代码智能 / RAG**：tree-sitter AST 提取 + LSP + Qdrant 向量检索 + 混合检索/重排 — existing (`server/codegraph/`, `server/services/retrieval/`)
- ✓ **对话 / Chat**：流式对话、多模态、RAG 增强、OpenAI 兼容入站 API — existing (`server/chat/`, `server/compat/`)
- ✓ **认证与权限**：Cookie-JWT（HttpOnly + 刷新轮换/黑名单）、Argon2 密码、OIDC、RBAC 权限 — existing (`common.authentication`, `server/permissions/`)
- ✓ **实时推送**：channels/WebSocket 推送工作流与对话状态；Web Push（VAPID）通知 — existing (`server/workflows/consumers.py`)
- ✓ **自托管部署**：Docker Compose（server/web/runner/postgres/redis/qdrant），含 CI/CD 与预构建镜像 — existing (`docker-compose.yaml`, `.github/workflows/`)
- ✓ **首启初始化向导**：无 superuser 时首次访问进入向导，自设管理员并自动登录；向导内一键预设配 Anthropic 兼容供应商（Fernet 加密 + 健康校验 + 绑 Claude Code）+ 安全密钥校验 + 可选飞书/RAG 步骤；fail-closed 防重入/防接管；entrypoint 去自动建号、运维命令保留 — v0.1.0 (`server/accounts/`, `server/system/`, `web/src/pages/setup.vue`)
- ✓ **个人访问令牌（PAT）增强**：令牌加名称/备注/可选有效期（默认永久、不可延期）、明文仅展示一次（仅存 sha256）、前缀…后缀指纹区分，用户自助创建/吊销 — v0.2.0 (`server/access_tokens/`, `web/.../AccessToken*`)
- ✓ **令牌即用户身份**：携带 PAT 的请求以令牌所有者身份 + 其 RBAC 被鉴权（替代「有效即全权限」），friday_pat_ 前缀闸门使 PAT/JWT 互不干扰，MCP/工具入口 fail-closed — v0.2.0 (`server/access_tokens/authentication.py`, `McpToolView`)
- ✓ **对话/会话用户隔离**：Conversation.created_by + 历史回填最早 superuser，全 25 路径（含 SSE/WebSocket）按 owner 过滤，越权 404 不泄漏存在性 — v0.2.0 (`server/chat/`)
- ✓ **管理员只读会话后台**：物理隔离的 `/api/admin/conversations/`（IsSuperUser）浏览所有会话，只读防误操作，交互需 fork 到自己名下 — v0.2.0 (`server/chat/admin_views.py`, `web/.../admin/conversations.vue`)
- ✓ **MCP 绑定 + RemoteTool 执行端点**：ToolTokenBinding 持久绑定令牌给 skill/mcp；经 PAT 认证 fail-closed 的按工具 name 执行端点供容器回调 — v0.2.0 (`server/tools/`)
- ✓ **task 容器 RemoteTool 链路（机制层）**：容器消费 `remote_tools` 经 SDK MCP server 加载工具，PAT 经 server→runner→task 直传注入并全程脱敏，吊销 graceful — v0.2.0 (`task/friday_task/core/remote_tools.py`, `runner/`)（注：实时明文 PAT 通道接入为已知 follow-up）
- ✓ **交付知识图谱**：四类实体 + bi-temporal 边 + supersedes 版本链，GraphStore 递归 CTE，`delivery_knowledge` collection 生命周期 — v0.3.0 (`server/knowledge/`)
- ✓ **统一摄取与版本化**：幂等异步摄取管线（chat/MCP/workflow/飞书/编码回调六类触发点），版本翻转 + 向量下线，全量 diff 归档与 MODIFIES_CHUNK 代码图谱对齐 — v0.3.0
- ✓ **时间感知混合检索**：`DeliveryKnowledgeSearchService` 向量召回 + 图扩散 + 时间衰减 + LLM 二阶段分级，fail-closed 权限过滤 — v0.3.0
- ✓ **知识多入口暴露**：MCP PAT 三工具 / chat agent tools / workflow 检索节点 + ai_plan_generation 飞轮 / npm friday-knowledge skill — v0.3.0
- ✓ **前端只读时间线**：实体详情页 + 关联时间线 + as-of 时点查询，REST `/api/knowledge/*` — v0.3.0
- ✓ **工作流契约收敛**：节点定义以后端 registry 为唯一事实源，`WorkflowGraphValidator` 保存即校验（DAG/edges/config/变量引用），内置模板开箱可跑，变量引用所选即所得（解析失败显式报错） — v0.4.0 (`server/workflows/`)
- ✓ **执行引擎状态机 + 可观测**：waiting_event 完成判定、next_handle 分支路由、trigger_data 注入执行上下文、死锁/挂起可见；WS 断线降级轮询 + 节点错误展示 — v0.4.0
- ✓ **触发模型清理**：飞书 event_type/event_types 字段断裂修复、schedule 假功能处理 — v0.4.0
- ✓ **排除文件机制（fail-closed）**：排除配置单一事实源（`RepoExclusionRule` + 全局默认 `SystemSetting`）+ 单一匹配器 `is_excluded`，被排除文件在索引/RAG/MCP/grep/agent/容器六面均不可见（运行期 fail-closed、构造期非法 regex fail-loud） — v0.5.0 (`server/services/exclusion.py`)
- ✓ **两种 purge 模式 + 对账清理**：统一删除入口 `purge_file`（Qdrant 主+overlay/ChunkRegistry/codegraph 五面）+ 普通排除 / 敏感清理双模式 + `compute_reconciliation`/`run_cleanup` 对账 + `ReconcilePanel` UI（如实声明不承诺 git 物理消失） — v0.5.0 (`server/services/purge.py`, `sensitive_purge.py`)
- ✓ **敏感文件 AI 识别**：确定性检测器（文件名启发式 + 密钥内容扫描 + 全程脱敏 reason）+ 可选 LLM 二分类 + 「建议+确认」REST/UI（接受幂等建 `ai_suggested` 排除规则，绝不静默删） — v0.5.0 (`server/services/sensitive_detect.py`)
- ✓ **Commit 历史 RAG + 行级反查**：commit message/author/变更文件路径摘要入 Qdrant（kind=commit，增量 boundary..HEAD）；`ChunkRegistry` 行号回填 + `find_chunk_at` + `GET /api/repositories/<id>/chunk-at/` — v0.5.0
- ✓ **多仓凭证统一 + MCP 多仓检索**：`GitInstanceCredential` 按 host 集中存（Fernet 加密）+ 单一解析器 `aresolve_git_token`（per-repo 优先 → host 实例池 fallback），全链路取 token 收口；MCP `search_rag_chunks` 多仓/全仓参数 — v0.5.0 (`server/repositories/`)
- ✓ **飞书接口前置修复**：按真实 `work_item_type` 取数（不再默认 story 取错）、`get_work_item` 保留完整 `fields[]` 元数据、修复评论端点解析、工作项关系改 `work_item_related_multi_select` 字段派生（PF-09/10/11/12） — v0.6.0 (`server/services/feishu.py`, `server/feishu/client.py`)
- ✓ **`WorkItem` 操作态脊柱**：新增 `delivery` app + canonical `WorkItem`（三元组唯一 INV-1）+ 单一 `WorkItemService.upsert` 入口（INV-6）+ source-of-truth 三分类（mirror/friday_enhanced/writeback）+ `WorkItemSyncState` facet 完整度 + `WorkItemRelation` 字段派生 + `WorkItemStatusEvent` append-only — v0.6.0 (`server/delivery/`)
- ✓ **评论事件流**：append-only `WorkItemCommentEvent`（created/replied/edited/deleted/approval）+ `CommentEventService` 单一 append 入口 + 幂等去重 + 当前评论树读时投影 — v0.6.0 (`server/delivery/`)
- ✓ **Document + REFERENCES**：`Document`/`DocumentVersion`（外部飞书/内部生成 + content_storage + supersedes 版本链）+ `DocumentService` 单一入口 + `feishu_document` normalizer 摄取 PRD/技术方案 + `REFERENCES` 边关联 `WorkItem` — v0.6.0 (`server/delivery/`, `server/knowledge/sources/`)
- ✓ **Release 账本 + Bitable adapter 骨架**：宽容模型 `ReleaseBatch/Record/Artifact`（保留 `raw_row` 无损）+ `ReleaseService` 单一入口 + `BitableClient`（开放平台 token 独立解析）+ adapter 骨架 — v0.6.0 (`server/delivery/`)
- ✓ **一键摄取编排**：(看板URL, MR URL) → `IngestRun` 状态机 → 拉看板工作项（upsert）+ PRD/技术方案文档（REFERENCES）+ MR diff（RAG）三步 best-effort + 前端 `/knowledge/ingest` 面板 — v0.6.0
- ✓ **历史 diff 冻结 + bi-temporal 失效**：MR diff commit 锚定（`target_branch`+`merge_commit_sha` 不假设 master）+ `MODIFIES_CHUNK` 边冻结 chunk 指纹 + 重索引对账置 `invalid_at` + as-of 查询区分历史/当前（PF-08） — v0.6.0 (`server/knowledge/`)
- ✓ **片段→需求反查 + 评论入图**：复用 `find_chunk_at` + graph_store 逐跳反查需求/文档（REST + MCP `reverse_lookup_requirements`，fail-closed）+ 评论摄取进 work_item 知识投影 — v0.6.0
- ✓ **截图识别需求**：多模态 LLM（vision 提语义 → 文本 query → 既有交付知识检索召回 work_item）+ graceful 降级 + 前端「截图识需求」面板（非图片向量库） — v0.6.0
- ✓ **方案编排引擎（map-reduce 多 agent）**：`PlanOrchestrationEngine`（入口无关 + 4 可注入 stage 协议）+ `PlanSession` 8 态状态机（拆分→路由→召回→澄清→并行调研→架构师融合，可持久化可恢复、条件更新防双推进）；工作流入口 + Chat 薄封装复用同一 engine（不造两套） — v0.7.0 (`server/services/plan_orchestration/`, `server/delivery/`)
- ✓ **canonical 方案脊柱**：`TechnicalPlan`/`PlanVersion`（origin/status + supersedes 版本链 + content 存 MergedPlan schema）+ `TechnicalPlanService` 唯一写入入口（INV-6）+ 旧 3 路径（chat/mcp/workflow）软链 + read-time lazy 迁移（不全量双写）；方案可追溯 `WorkItem`（INV-2，chat 自然语言 null 显式标记） — v0.7.0
- ✓ **路由 + 召回接入**：`RepoRouterV2Adapter`（能力树 + LLM 路由候选仓 + confidence）+ `DeliveryKnowledgeRecallAdapter`（相似需求/缺陷/复盘/方案召回，created_by 透传 fail-closed） — v0.7.0
- ✓ **并行调研子 agent**：filter_then_container（high/medium 起隔离容器、low 轻量 partial）产结构化 `PartialPlan`（§7）+ 单仓 `RepoResearchTask` 失败隔离重试 + 仓库重索引使 `PartialPlan` 置 stale 融合前重跑 + barrier 聚合 — v0.7.0
- ✓ **架构师融合 + PlanValidator**：架构师子 agent 收齐 partial 产结构化 `MergedPlan`（跨仓契约/依赖 DAG/迁移/兼容风险/发布顺序/回滚/execution_plan）落 canonical；`PlanValidator` 5 类拦截（契约一致/依赖成环 DFS 三色/迁移顺序/发布顺序/缺回滚）+ 限次回退；跨仓依赖 `dependency_dag` 显式建模为 v0.8 wave 编码铺底 — v0.7.0
- ✓ **HITL 澄清 + 事件 taxonomy**：`Clarification` 挂起回路（回答后仅 affected_partials 重跑）+ `PlanSessionEvent` append-only 把 §15 trace 事件全程持久化为统一信封（稳定词表 event_taxonomy 收口全 emit 点，INV-5 progress/trace 非 CoT，为 v0.11 对外 adapter 备料） — v0.7.0
- ✓ **编码 env 对齐 + 通用 resume 回流**：workflow 编码 `_run_repo_coding` dispatch 逐键对齐 chat 基线（顶层 `env_FRIDAY_TASK_GIT_*` token/auth + `BRANCH_STRATEGY`/`TARGET_BRANCH` + SSH→HTTPS 改写，私有仓 clone + 正确目标分支，PF-06）+ 入口无关续驱 helper `adrive_plan_session_to_pause_or_terminal`（节点/工具/回调三处同源，`_schedule_chat_plan_resume` 消化 v0.7 audit D-2 chat 自动回流缺口） — v0.8.0 (`server/workflows/nodes/ai/coding.py`, `server/services/plan_orchestration/resume.py`)
- ✓ **多仓 wave 编码调度**：`RepoCodingTask` 操作态模型（plan_version/repository FK + wave int + `depends_on` M2M self DAG + `produced_artifacts`/`follow_openspec` 预留）+ 消费 `execution_plan[].dependencies` 经 graphlib Kahn 拓扑分层成 wave（同仓取 max，消化 PF-07）+ `RepoCodingTaskService` 单一写入入口（INV-6）+ `aadvance_coding_waves`（回填→传递闭包阻断→决策，wave N done → N+1、失败隔离不死锁）+ `AICodingNode` 按 wave 分批 dispatch + callback 重入自驱（不另造调度，空依赖退化全并行零回归） — v0.8.0 (`server/delivery/`, `server/services/plan_orchestration/wave_progression.py`)
- ✓ **上游产物注入下游 wave**：上游 wave done 后提取 `produced_artifacts`（OpenAPI/API 契约/diff，路径启发式归类）落库（`record_produced_artifacts` 单一入口）→ 注入下游 wave prompt/`global_context`（`render_upstream_artifacts_section`，空段守卫零回归、raw_output 不泄漏、fail-soft） — v0.8.0 (`server/services/plan_orchestration/artifact_extraction.py`)
- ✓ **多仓融合 PR + 跨仓关联**：各仓 MR `target_branch` 锚定各仓 `Repository.default_branch`（fallback `default_branch or base_branch or "main"`，非假设 master）+ 跨仓 PR cross-ref（`successful_mrs ≥2` 守门，回写「## 关联 PR」兄弟链接 + 「## 关联方案/工作项」追溯 `plan_version → TechnicalPlan → WorkItem`，全程 fail-soft，可复用 helper `pr_cross_reference.py`） — v0.8.0 (`server/workflows/services/pr_cross_reference.py`)
- ✓ **编码遇阻 HITL 抛人**：编码容器遇阻给 agent `ask_user` 工具（复用既有 question 协议 + `answer.json` 共享卷回灌，心跳保活容器 RUNNING，超时 default 续跑/优雅失败绝不挂起）+ server 侧 `_resolve_notification_chat_id` 统一解析（chat 路径零回归 + node 级 chat_id fallback）+ 回答后既有 resume 推进 wave；**显式非目标：不做编码中全自动 replan** — v0.8.0 (`task/core/question_loop.py`, `server/.../question_handler.py`)

- ✓ **SDD 仓库检测 + 打标**：索引完成 FINALIZING best-effort 检测仓库根 `openspec/` → `facets["methodology"]="SDD"`（幂等不漂移、删除取消标记、尊重 `_pinned`、不阻断索引 success）+ 前端 `SddMethodologyBadge`（仓库列表/详情 + 知识树，serializer 只读 `methodology` 透出） — v0.9.0 (`server/services/sdd_detect.py`)
- ✓ **方案产 openspec spec**：SDD 仓方案融合（`ArchitectMergeAdapter._handle_pass` best-effort 挂接，fail-soft 不阻断融合）逐仓经可注入 `SddSpecSynthesizer` 产 openspec change-proposal → 落 `SddSpec` 脊柱（每「方案版本×仓」一份，`unique_together` 幂等）+ `Document(sdd_spec, internal_generated)` 经 `DocumentService.create_internal_spec`/`SddSpecService.create_draft` 双单一写入入口（INV-6），关联 WorkItem/PlanVersion/Repository + emit `spec.drafted`；非 SDD/异常零回归 — v0.9.0 (`server/services/plan_orchestration/spec_generation.py`, `server/delivery/models/sdd_spec.py`)
- ✓ **spec 状态机 + 评审**：`SddSpecService` 状态机（draft→in_review→approved→implemented→archived，合法流转表、非法流转 `SddSpecTransitionError` fail-loud、条件更新防双推进）+ `SddSpecReview` append-only 不可篡改评审记录（approve/reject 单一事务驱动状态）+ `/api/specs/` REST（list/detail/transition，approve/reject/archive/mark_implemented superuser fail-closed 分流，全 read_only 序列化器）+ spec 治理前端（列表/详情/状态徽标/评审时间线/状态流转操作按状态×权限显隐） — v0.9.0 (`server/delivery/services/sdd_spec_service.py`, `web/src/pages/specs/`)
- ✓ **编码前置 gate + openspec 注入**：`RepoCodingTaskService.create_tasks_for_plan` 首次消费 `follow_openspec`（按 `facets.methodology=="SDD"` 置位）+ `AICodingNode._dispatch_wave` 前置 gate（`follow_openspec=True` 仓校验 `SddSpec.status==APPROVED` 才放行，未批准/异常 fail-closed `mark_gate_blocked` 拦截 + 单仓隔离不崩 wave + 下游传递闭包阻断）+ openspec 指引注入（dispatch `env_FRIDAY_TASK_FOLLOW_OPENSPEC` → task `TaskConfig.follow_openspec` → `_get_system_prompt` openspec 段 + `setting_sources=["project"]` 原生加载 `.claude/skills`）；非 SDD 仓零回归 — v0.9.0 (`server/workflows/nodes/ai/coding.py`, `task/core/executor.py`)
- ✓ **spec↔PR 关联 + 交付验收视图**：`SddSpec.implementation_prs` + `SddSpecService.link_implementation_pr`（去重幂等 + approved→implemented，无 spec no-op）经 `_finalize_and_notify` best-effort 回填（fail-soft 绝不阻断 PR 创建/通知）+ `SddSpecDetailSerializer` 追溯摘要 + 前端 `SpecDeliveryPanel`（WorkItem→spec→PR 链路，缺数据降级占位） — v0.9.0 (`server/delivery/services/sdd_spec_service.py`, `web/src/components/...SpecDeliveryPanel.vue`)

- ✓ **统一 `AuditEvent` 审计模型 + emit 地基**：零业务依赖的 `audit` Django app + `AuditEvent` append-only 不可篡改模型（actor 标量软引用 / action / target / before-after / source / 双时间戳 / metadata + 5 查询索引 + 模型层 save/delete 守护）+ `AuditService.emit/aemit` 唯一写入入口（INV-6）+ 入口强制脱敏（key-name / 值级密钥正则 / 高熵，凭证绝不落明文）+ fail-soft 不阻断主操作 + 稳定 action taxonomy — v0.10.0 (`server/audit/`)
- ✓ **敏感操作全量审计覆盖**：身份与权限类（accounts 建用户/启停/改资料/首启 superuser + projects/members 成员增删改/角色变更 + 空间配置/仓库权限）+ 凭证与数据治理类（Provider/Git 实例/per-repo Git/PAT/飞书凭证与同步 + 排除规则增删 + v0.5 `purge` 埋点收口统一表）经统一入口 emit，actor + 目标 + 前后值，凭证字段脱敏 — v0.10.0
- ✓ **审计查询 + 前端视图 + 导出**：审计查询 REST（`/api/audit/`，IsSuperUser fail-closed、只读、按 actor/action/target/时间过滤 + 分页）+ CSV/JSON 流式导出（`/api/audit/events/export/`）+ `/admin/audit` superuser 审计页（过滤/表格/分页/before-after 详情弹窗/导出/侧栏入口/i18n） — v0.10.0 (`server/audit/`, `web/src/pages/admin/audit*`)

- ✓ **Agent API trace 透出**：内部工具调用（RAG/grep/仓库分析）经 §15 事件 taxonomy 映射为 OpenAI 兼容流式 progress/`reasoning_summary`（`server/compat/progress.py`，INV-5 非 CoT、绝不发 `tool_calls`/`finish_reason=tool_calls`，缺事件优雅降级，`/v1/chat/completions` 零回归） — v0.11.0 (TRACE-01/02)
- ✓ **Anthropic 兼容端点 `/v1/messages`**：Messages 形状映射（system/messages/max_tokens）复用既有 chat/agent 内核，非流式 + SSE 流式可用，trace 经 thinking block adapter 透出（复用同一 taxonomy，thinking block 严格先于首个 text，INV-5） — v0.11.0 (ANTHROPIC-01/02)
- ✓ **飞书原生 CardKit 流式卡片**：机器人对话回复增量更新（CardKit v1 create/send/stream/settle 封装 + schema 2.0 流式卡），替代 PATCH 全量替换，失败降级既有卡片 — v0.11.0 (CARD-01, `server/services/feishu_im.py`)
- ✓ **工作流自动建群节点**：`CreateGroupChatNode` 建飞书群 + 拉成员（`FeishuIMClient.create_chat` 建群即拉人）+ chat_id 输出 + 可选写回 `WorkItem.feishu_chat_id`（`WorkItemService.awriteback_feishu_chat_id` 单一入口 INV-6，fail-soft 不阻断） — v0.11.0 (GROUP-01)

### Active（v0.15.0 项目 / 交付上下文聚合根）

<!-- 本里程碑在建需求（38 条，6 Phase 76–81）。详见 .planning/REQUIREMENTS.md 与 .planning/project-aggregate/MILESTONE-PROPOSAL.md。v0.14.0（CTX/LOG/RATE/RAG/SLA/SNAP/QUERY/ALERT/UI/SPEC）已交付，详见 MILESTONES.md 与 milestones/v0.14.0-*。 -->

**Phase 76 · 命名腾挪（RENAME）**
- ☐ **RENAME-01**: 后端 `projects.Project` 重命名为 `Space`，数据零丢失，既有"空间"功能行为零回归
- ☐ **RENAME-02**: 全栈 `project→space` 引用一致更新（serializers/views/permissions/space_tools/fetch_space_info/FK），对外仍称"空间"，测试基线零回归

**Phase 77 · 项目聚合根 + 身份映射 + 成员协作（PROJ/IDENT/MEMBER）**
- ☐ **PROJ-01**: `Project` 聚合根（隶属 Space + 关联飞书项目跟踪 + 状态/创建者），单一入口 `ProjectService`
- ☐ **PROJ-02**: 项目状态机（开发中/归档/终止，可扩展）非法流转 fail-loud + 接入审计
- ☐ **PROJ-03**: 项目 CRUD REST API，按 Space 成员权限 fail-closed
- ☐ **PROJ-04**: 项目可关联其他项目（多对多，历史迭代/相关项目回看）
- ☐ **PROJ-05**: 前端手动创建项目（Space + 飞书看板 + 名称），`(space, feishu_project_key)` 幂等
- ☐ **IDENT-01**: 飞书人员↔Friday 用户多对多映射（手动 + JIT），单一解析入口，未映射 fail-soft
- ☐ **MEMBER-01**: 项目成员（多对多 + 身份角色 主R/PM/前端/后端/测试），一人多项目
- ☐ **MEMBER-02**: 主R 唯一可转移 + 成员增删改 API + 审计 + 全成员可见可参与
- ☐ **MEMBER-03**: 成员/状态变更经 WebSocket 实时推送

**Phase 78 · 飞书触发建项目 + 看板枚举 + 工作项组合（FSPROJ/COMPOSE）**
- ☐ **FSPROJ-01**: 飞书"项目跟踪"枚举子项(story/缺陷)/人员(带角色)封装，无整板 API 经字段派生，fail-soft
- ☐ **FSPROJ-02**: 飞书事件触发幂等建同名项目 + 拉入看板人员(身份映射)，重复不重复建
- ☐ **FSPROJ-03**: 工作流 `create_project` 节点（看板名建项目 + 拉人带身份 + 关联子项）
- ☐ **COMPOSE-01**: 项目组合多个 WorkItem（story 复用 delivery.WorkItem 经关系边，可并入/移除）
- ☐ **COMPOSE-02**: 缺陷（看板类型=缺陷）经关系边挂入，不重复建模

**Phase 79 · 工件/依赖项 + 知识关联（ARTIFACT/KLINK）**
- ☐ **ARTIFACT-01**: `ArtifactType` 可配置注册表（内置 8 类，后台增删禁用）
- ☐ **ARTIFACT-02**: `Artifact` 实例（类型/载体 飞书文档·表格·外链·md·仓库文件/链接/版本/贡献者）
- ☐ **ARTIFACT-03**: 工件在线查看（飞书文档·表格渲染/外链跳转）+ md·内部工件可编辑
- ☐ **ARTIFACT-04**: 工件 RAG——文字载体全文进 delivery_knowledge；UI 稿外链仅存元数据
- ☐ **ARTIFACT-05**: 类型增删禁用即时生效，禁用类型不可新建、既有实例只读保留
- ☐ **KLINK-01**: 项目↔知识实体（KnowledgeEntity）多对多
- ☐ **KLINK-02**: 项目↔仓库/空间/知识/其他项目，经 KnowledgeEdge 统一建模、可视

**Phase 80 · 项目记忆 + MR 实体 + 召回接入会话（MEM/RECALL/MR）**
- ☐ **MEM-01**: 项目记忆（自由文本 append/edit + 时间戳/贡献者），全成员共享
- ☐ **MEM-02**: 贡献限成员；私聊/非成员会话不纳入
- ☐ **MEM-03**: 记忆可人工编辑/覆盖（方案推翻/需求变更），保留可追溯
- ☐ **MEM-04**: LLM 提炼记忆草稿→人工确认入库（不自动写）+ 脱敏不可绕过
- ☐ **RECALL-01**: 项目上下文打包器（grep+RAG 召回+排序+压缩，token 预算可降级）
- ☐ **RECALL-02**: Web 对话绑定项目自动加载上下文，search_delivery_knowledge 接入 chat runner
- ☐ **RECALL-03**: 召回覆盖项目全部文字工件/记忆/工作项，权限 fail-closed + 写 RetrievalTrace
- ☐ **MR-01**: `MergeRequest` 实体（关联项目/仓库/分支/工作项 + 状态 + review），单一入口
- ☐ **MR-02**: 入站 webhook 同步 MR 状态（GitHub/GitLab，脱敏原始 payload 落库）

**Phase 81 · Cursor 回流 + 前端项目工作台（CURSOR/UI）**
- ☐ **CURSOR-01**: MCP 分支→项目反查 + 召回需求/工件/记忆
- ☐ **CURSOR-02**: Cursor rules 模板（强制先关联分支召回再编码）
- ☐ **CURSOR-03**: Cursor 沉淀上报写回 memory/知识（认证 + 归因 + 脱敏 + 质量门槛）
- ☐ **UI-01**: 项目列表页（Space/状态/成员筛选）+ 创建入口
- ☐ **UI-02**: 项目详情工作台（概览/成员带身份/工作项/工件查看/记忆编辑/关联）
- ☐ **UI-03**: 记忆编辑 + LLM 提议确认 UI + 工件类型后台管理页

**Backlog 候选（后续里程碑）：**

- 项目进阶（v2 PROJX）：UI 稿多模态/figma 正文召回、结构化记忆 + 时效降权 + 矛盾消解、记忆全自动提炼（无人工确认）、Cursor 专用插件/hook 主动采集、项目级看板可视/燃尽/进度

- 开放进阶（v2 OPENX）：标准双向 `tool_calls`（客户端自带工具回传执行）、Anthropic 端点工具/多模态 content block 全量对齐、飞书卡片交互组件/多卡片编排
- 审计进阶（v2 AUDITX）：密码学级防篡改（hash chain / WORM）、实时告警 / SIEM / webhook 外发、审计保留/归档/自动清理策略
- SDD 进阶（v2 SDDX）：openspec spec 内容 lint 深度校验、spec↔代码双向 drift 检测、非 openspec 的其他 SDD 框架适配
- 编码中全自动 replan/回溯（v0.8 已用「抛 question 给人」HITL-01 过渡，全自动留后续）
- chat 编码入口（`coding_session_service`）的跨仓 PR cross-ref / 遇阻 HITL 接线收尾（v0.8 优先 workflow wave 入口，helper 入口无关已就绪以便复用）
- 多仓 wave 编码 / PR / HITL 的真实 runner+Docker 容器端到端验收（需真实环境）；Phase 26 遗留 `test_batch_pr.py` 5 例 stale patch target 修复
- 接入实时明文 PAT 通道剩余路径（chat/MCP 编码 dispatch）+ RTOOL-02/03/04 容器端 E2E 真实环境验收
- 令牌细粒度读写 scope / rotate / IP allowlist / 短 TTL 派生凭证（PATX-01~04）
- 图片向量库（视觉相似/标注）；补齐 v0.1.0 / v0.2.0 顺延的人工验收（UAT）
- Bitable 真实列映射（v2 REL-03，待开放平台凭证）

### Out of Scope

<!-- 明确边界，含理由，避免反复回炉。 -->

- 多管理员 / 团队批量初始化 — 首启只需建一个 superuser；后续成员管理走既有 `/admin/users` 页面
- 在向导内配置 OIDC/SSO — 已有独立 OIDC 设置页，首启聚焦"能进去 + 能跑 AI"
- 改动既有四层 Provider 解析逻辑 — 向导/令牌均复用既有 service，不重写
- 向导主题/品牌化深度定制 — 复用现有设计系统与 i18n，不做可配置主题
- 把基础设施密钥（SECRET_KEY 等）改为运行时 Web 设置 — 这些是启动期 env，向导只做校验提示
- 令牌读写/资源 scope 细分 — v0.2.0 明确不做，令牌继承所有者全部 RBAC（与 GitLab 默认一致），细分留 v2（PATX-01）
- 令牌延期/续期 — 与 GitHub/GitLab 一致：到期只能新建，不延长既有令牌寿命
- 短 TTL 派生凭证注入容器 — v0.2.0 选直传 PAT + 脱敏；派生凭证留 v2（PATX-04）
- 吊销中断在途任务 — 选 graceful：在途跑完仅阻断新调用，避免中断回滚复杂度

## Context

- **Brownfield**：已有完整代码地图见 `.planning/codebase/`（STACK / ARCHITECTURE / STRUCTURE / INTEGRATIONS / CONVENTIONS / CONCERNS / TESTING）。
- **凭证设计约束**：LLM/Git/飞书凭证一律加密存库、运行时按作用域解析，**不走环境变量**（`provider_config.py`、`ProviderCredential`）。
- **PAT 安全约束（v0.2.0）**：明文仅在创建响应一次性返回、仅存无盐 sha256 + 唯一索引；明文绝不进 logger/序列化器/前端 store/localStorage/URL；注入容器的直传 PAT 仅在实时请求线程可用时传递、绝不落盘、绝不从 AccessToken 反取（PAT-02）。
- **认证分层**：cookie-JWT（Web）与 friday_pat_ 前缀 PAT（程序化）经前缀闸门各走分支互不吞掉；MCP/工具 HTTP 入口为已认证信任边界（fail-closed）。
- **Claude Code 与第三方模型**：Claude Code 强制要求 `anthropic` 类型凭证；`AnthropicCredentialSchema` 支持 `base_url` 覆盖兼容端点 → DeepSeek/MiMo/Kimi 以"anthropic 类型 + 自定义 base_url + 指定 model"接入。
- **前端**：SPA 路由守卫在 `web/src/main.ts` + 各页 `definePage({ meta })`；认证状态在 `web/src/stores/auth.ts`。
- **测试基线**：后端 ~520 个 `test_*.py`、前端 ~130 个 spec，覆盖较广；薄弱点在 Go runner、容器级 E2E 与个别安全路径（见 CONCERNS.md）。

## Constraints

- **Tech stack**: 后端 Django 5.1+/Python 3.14（adrf 异步 DRF + channels），前端 Vue 3 + TS + Tailwind 4 + reka-ui，凭证用 `cryptography` Fernet 加密 — 必须沿用既有栈与异步约束（async ORM 走 `sync_to_async`）。
- **Security**: 初始化接口必须 fail-closed —— 仅当"无 superuser"时可用，存在 superuser 即拒绝；防止被用于重置/接管现有实例。PAT 认证按所有者 RBAC 施权，明文绝不落盘。
- **Compatibility**: 已有部署（已存在 superuser、或用 env/命令建过号）升级后行为不得回退；`init_superuser` / `reset_superuser_password` 命令保留。会话隔离迁移历史回填可逆、无 superuser 时留 null 不阻塞部署。
- **Convention**: 新增凭证/设置必须复用 `ProviderCredential` / `SystemSetting` / `SettingKeys` 与现有 service 层，不绕过加密与权限。
- **i18n**: 向导/令牌/管理后台文案接入既有 `vue-i18n`，默认中文。

## Key Decisions

<!-- 约束后续工作的关键决策。 -->

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| 用"首次访问设置向导"替代启动期自动建管理员 | 自动建号的随机密码只在日志，用户进不去；让用户自设账号即时可用 | ✓ Validated（v0.1.0） |
| 向导完成后接口/界面永久关闭并 fail-closed（无 superuser 才可用） | 防止被用于重置或接管已有实例（安全） | ✓ Validated（v0.1.0） |
| DeepSeek V4 Pro / MiMo V2.5 Pro / Kimi 2.6 以 anthropic 兼容端点做"一键预设" | Claude Code 必须 anthropic 类型；这些模型经 base_url 覆盖接入，用户只填 Key | ✓ Validated（v0.1.0） |
| 向导必配：管理员 + 至少一个 Anthropic 兼容供应商；飞书/RAG 为可选步骤；加密密钥仅校验提示 | 保证"能进去 + 能跑 AI"为最小闭环，其余可跳过后补 | ✓ Validated（v0.1.0） |
| 保留 `init_superuser` 命令但默认从 entrypoint 移除，仅作运维兜底 | 兼容老部署与运维场景，同时去掉令人困惑的自动建号默认行为 | ✓ Validated（v0.1.0，Phase 5） |
| 作为首个 GSD 里程碑 v0.1.0；既有能力记为 Validated 基线（已打基线 tag v0.0.1） | 项目为 brownfield，先建 GSD 基线再推进新特性；0.x 阶段里程碑走 minor、修复走 patch | ✓ Validated（v0.1.0 已归档） |
| 令牌即用户身份：`authenticate()` 返回 owner，施加用户 RBAC，暂不做读写 scope 细分 | GitHub/GitLab PAT 语义；用最小改动复用既有 IsAuthenticated/PermissionService | ✓ Validated（v0.2.0，Phase 7） |
| 历史无主会话回填给最早的 superuser | Conversation 无 owner 字段，最早 superuser 是最稳妥归属，不丢数据 | ✓ Validated（v0.2.0，Phase 8） |
| 默认所有人（含管理员）在 AI 对话只看自己；另设只读「管理员会话管理」后台查看他人会话，交互需 fork | 隐私默认隔离 + 运维/审计可见两不误；只读防误操作 | ✓ Validated（v0.2.0，Phase 8-9） |
| 用户令牌以直传 PAT 形态注入 task 容器，日志/审计脱敏 | 优先简单可落地；泄漏面以脱敏 + 后续短 TTL 缓解 | ✓ Validated（v0.2.0，Phase 11，机制层；运行时通道为 follow-up） |
| skill/mcp 以持久绑定表绑定用户令牌；吊销令牌时在途任务跑完仅阻断新调用（graceful） | 绑定可见可管理；graceful 避免中断在途任务的复杂回滚 | ✓ Validated（v0.2.0，Phase 10-11） |
| Open-Q1 Option C：完整交付 RemoteTool 机制 + 脱敏 + graceful，实时明文 PAT 通道留 follow-up | 受 PAT-02（明文绝不落盘/不读 DB）约束，机制先行、运行时通道待接入，不阻塞里程碑 | ⚠️ Revisit（v0.2.0 follow-up） |
| 复用 `waiting_event` + callback resume 扩成多 wave，不另造调度 | `_schedule_workflow_resume` 容器回调触发节点重入自驱（`while True`→有界 `for`，无 sleep/timer/apscheduler）；wave N→N+1 自然推进 | ✓ Validated（v0.8.0，Phase 44） |
| wave 分层用 task 级 DAG（`execution_plan[].dependencies`），仓 wave 取该仓所有 task 层级 max | dependencies 是 task id 引用（schema 权威），graphlib Kahn 分层；空依赖退化全 wave 0 保零回归 | ✓ Validated（v0.8.0，Phase 44） |
| wave 失败部分回滚语义：done 出 MR、failed/blocked 如实标注（`upstream_failed`），不自动回滚 | v0.8 非目标不做自动回滚；传递闭包阻断下游 + liveness 命门（阻断必在 early-return 前完成防死锁） | ✓ Validated（v0.8.0，Phase 44） |
| 各仓 MR `target_branch` 锚定各仓 `default_branch`（非假设 master），diff base per-repo | 对齐 v0.6 坐实的 MR target_branch 锚定；fallback `default_branch or base_branch or "main"` 保单仓/同 default 多仓零回归 | ✓ Validated（v0.8.0，Phase 46） |
| 编码遇阻走 HITL「抛 question 给人」，不做编码中全自动回溯重规划 | 全自动 replan 范围爆炸风险高；复用既有 question 协议 + 容器心跳保活 RUNNING，回答后续跑；全自动留 backlog | ✓ Validated（v0.8.0，Phase 47） |
| 跨阶段「不造两套」：续驱 helper / wave 推进 / 单一写入入口（INV-6）全程同源 | 节点/工具/回调三处复用同一 resume helper；状态只经 `RepoCodingTaskService` 条件更新；integration 审计 integration_ok | ✓ Validated（v0.8.0） |
| spec 生命周期独立建模（`SddSpec` + `SddSpecReview`），不复用 `TechnicalPlan` | spec 语义确需 `in_review`/`implemented` 态（区别于 `TechnicalPlan.status` 的 `under_review`/`superseded`），避免口径串味 | ✓ Validated（v0.9.0） |
| spec 产出/评审全 best-effort fail-soft、编码 gate fail-closed | 产 spec/PR 回填绝不阻断融合/PR 主流程；gate 未批准/异常一律拦截不放行（未批准的 SDD 仓不得编码） | ✓ Validated（v0.9.0） |
| spec 评审 approve/reject 限 superuser；spec 评审审计接入统一 `AuditEvent` 顺延 v0.10 | 复用「系统管理员=superuser，不新建角色」决策；本里程碑评审记录自持久化即留痕，统一审计是 v0.10 横切范围 | ✓ Validated（v0.9.0） |
| 编码 openspec 策略优先复用仓库内 `.claude/skills`（`setting_sources=["project"]`）+ system_prompt 注入点 | task 容器已原生加载克隆仓库内 skill，Friday 侧仅加 `follow_openspec` 条件 prompt 段，改动极小 | ✓ Validated（v0.9.0） |
| 内部工具调用对外透出为 progress/trace（reasoning_summary / thinking block），**不用标准 tool_calls、不暴露 CoT** | 内部工具是服务端闭环执行；标准 tool_calls 会让规范客户端误判挂起等待回传 → 卡死；INV-5 仅透出 progress/trace 非模型私有推理链 | — Pending（v0.11.0） |
| Agent API 对外复用 v0.7 起沉淀的 §15 事件 taxonomy，对外只是不同 adapter | taxonomy 已在 v0.7 稳定落地（`PlanSessionEvent`/`event_taxonomy`）；OpenAI/Anthropic 端点各做 adapter 映射，不另建词表 | — Pending（v0.11.0） |
| 标准双向 `tool_calls`（客户端自带工具）留 v2，本里程碑不做 | 当前无"客户端自带工具"诉求；先做单向 progress/trace 透出满足开放需求 | — Pending（v0.11.0，OPENX-01） |
| 采用 Procrastinate 作 durable queue，但藏在 `DurableTaskService` 适配层后 | PoC PASS（3.8.1/Py3.14/Django6/psycopg3.3）；适配层隔离实现，保留 SQLite dev 开箱路径与未来替换空间，业务代码不直接依赖 Procrastinate | ✓ Shipped v0.12.0 |
| 生产强制 durable（Postgres），SQLite 仅非 durable dev fallback；CI 增 Postgres 专项测试 | compose/helm 默认带 Postgres，durable 默认在线；SQLite 只影响 make dev/pytest；队列语义须在真实 Postgres 被测 | ✓ Shipped v0.12.0 |
| 不承诺 exactly-once，走 at-least-once + 幂等/fencing | DB claim 仅保证同轮单一领取；"慢≠死"误判与完成未标记即崩仍会重复执行——靠 checkpoint/upsert/deterministic key，外部副作用上 fencing/outbox | ✓ Shipped v0.12.0 |
| 一个底座、多条逻辑队列（index/graph/crawl_ingest/page_index/maintenance） | 不同队列独立并发与伸缩，避免长任务（索引）堵短任务（爬取/页面生成） | ✓ Shipped v0.12.0 |
| scheduler/rescue 单例改 DB leader（`queueing_lock`），弃用本地 `flock` | `flock` 仅单机有效、跨 Pod 失效；周期 rescue 与 cron 收敛到一个 leader workload | ✓ Shipped v0.12.0 |
| 收口 `ResumableTask`：Procrastinate/适配层接管生产职责，不三套并存 | `background_runner` 降级为 dev fallback/轻任务；存量在途行一次性迁移，不双跑 | ✓ Shipped v0.12.0 |
| workflow/RepoCodingTask 保留自有引擎，只做恢复桥接；chat/RAG 问答不进队列 | 有自有状态机的任务从持久化态重驱（非内存态恢复，`_debug_sessions` 丢失可降级）；流式问答请求级、断开让用户重试 | ✓ Shipped v0.12.0 |
| runner 改 k8s Job executor 纳入 v0.12.0（Phase 64），不拆后续里程碑 | 用户选 full 范围；k0s/containerd 下 docker.sock 是反模式，先抽 executor 接口再落 k8s 实现 | ✓ Shipped v0.12.0 |
| v0.15.0「项目」是聚合根，不是工作流节点；工作流只是写它的入口之一 | 项目是持续存在的领域数据 + 关系图；DAG 节点是一次性执行，语义不符 | — Pending（v0.15.0） |
| 后端 `projects.Project` 重命名为 `Space`，腾出 `Project` 名给新聚合根（大重构，76 独立前置） | 现状 `Project` model 映射前端"空间"是历史命名债；用户要中文"项目"指向新概念，必须腾名；独立 Phase 解耦降风险 | — Pending（v0.15.0，Phase 76） |
| 不做迭代实体：另一迭代 = 新建项目；历史迭代经项目↔项目关联回看 | 用户决策，避免多一层粒度；知识/记忆直接挂项目；复用 KnowledgeEdge 做项目间关联 | — Pending（v0.15.0） |
| 项目记忆为自由文本（条目 + 时间戳/贡献者），人工为主、LLM 仅产草稿经人工确认入库 | 用户选简单形态；矛盾消解靠人工覆盖；结构化 + 自动降权留 v2（PROJX-02） | — Pending（v0.15.0，Phase 80） |
| 工件统一抽象为可配置类型（ArtifactType 后台增删禁用）+ 实例（多载体）；文字载体 RAG、UI 稿仅元数据 | 避免为每种工件各建表爆炸；复用 KnowledgeEntity 思路；figma/mastergo 图形链接 RAG 不到正文，多模态留 v2（PROJX-01） | — Pending（v0.15.0，Phase 79） |
| 飞书人员↔Friday 用户映射作为主R/协作/归因/Cursor 上报的前置基础设施先建 | 现状无映射表；与可观测"谁触发"同源；多对多 + 手动 + JIT | — Pending（v0.15.0，Phase 77） |
| Cursor 回流先走 MCP + git + 上报 API，不做本地专用插件 | MCP/容器 user_token 地基已在（v0.2.0）；专用插件重、留 v2（PROJX-04）；上报写回须认证 + 归因 + 脱敏 + 质量门槛 | — Pending（v0.15.0，Phase 81） |
| 缺陷复用 `delivery.WorkItem` 经关系边挂项目，不重复建模为工件 | 缺陷（飞书看板类型=缺陷）与 story 同构；Artifact 只留给文档型依赖 | — Pending（v0.15.0，Phase 78） |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-27 — start milestone v0.16.1 统一 AI 技术方案生成（图编排归一 + 插槽式澄清拼接 + 能力完善）*
