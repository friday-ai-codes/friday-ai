# Friday AI

## What This Is

Friday AI 是一个 AI 驱动的敏捷开发自动化系统：它把飞书（Lark）项目管理中的需求自动转化为代码合并请求（MR/PR），从需求触发、AI 技术方案生成、到容器化 AI 编码代理执行、再到自动建分支提交 PR，全链路可编排、可观测。面向需要把"需求→代码"流程自动化的研发团队与平台工程师，自托管部署（Docker Compose / k8s）。

系统由四个组件构成：Django 后端（`server/`，REST + WebSocket + 工作流引擎 + 代码智能/RAG）、Vue 3 前端（`web/`，控制台/流程编辑器/对话）、Go 运行器（`runner/`，调度并在 Docker/k8s 中运行任务容器）、Python 任务执行器（`task/`，容器内运行 claude-agent-sdk 编码代理）。

## Core Value

让团队"开箱即用、安全地"把需求自动变成代码：用户能顺利完成首次部署与登录、配好必备的 AI 供应商，然后让工作流把飞书需求自动跑成 PR。如果第一步进不去（登录/配置），后面一切都无从谈起。

## Current State

**Latest shipped:** v0.7.0 方案编排（需求 → 主方案）（2026-06-16）

里程碑演进：v0.5.0 索引/检索地基 + 排除文件 → v0.6.0 领域脊柱 + 知识图谱补全 → v0.7.0 方案编排（需求 → 主方案）。近三个里程碑要点：

- **v0.5.0 索引地基 + 排除文件**：排除配置单一事实源 + 单一匹配器 `is_excluded` 全链路 fail-closed（索引/RAG/MCP/grep/agent/容器六面不可见）；统一删除入口 `purge_file` + 两种 purge 模式（普通排除 / 敏感清理）+ 对账清理 UI；敏感文件 AI 识别建议名单；commit 历史 RAG 索引 + `ChunkRegistry` 行号回填 + `file:line→chunk` 反查；多仓 Git 凭证统一池（`GitInstanceCredential`）+ MCP 多仓检索参数。
- **v0.6.0 领域脊柱 + 知识补全**：新增 `delivery` app 立起以飞书 work item 为中心的操作态脊柱——canonical `WorkItem` + 单一 `WorkItemService.upsert` 入口 + source-of-truth 三分类 + `WorkItemSyncState`/`WorkItemRelation`（字段派生）/`WorkItemStatusEvent`/`WorkItemCommentEvent`（append-only 评论流 + 当前树投影）；`Document`/`DocumentVersion`（外部飞书/内部生成）+ `feishu_document` normalizer + `REFERENCES` 边；Release 账本宽容模型 + 飞书 Bitable adapter 骨架；(看板URL+MR URL) 一键摄取编排；历史 diff 冻结 + bi-temporal 失效对账（PF-08）；评论入图 + 片段→需求反查 API/MCP；截图识别需求（多模态 LLM）。飞书接口前置修复 PF-09/10/11/12 已落地。
- **v0.7.0 方案编排（需求 → 主方案）**：把「需求 → 一份高质量多仓主技术方案」做成可复用的 map-reduce 多 agent 编排引擎——`PlanOrchestrationEngine`（入口无关 + 4 可注入 stage 协议）+ `PlanSession` 8 态状态机（拆分→路由→召回→澄清→并行调研→架构师融合，可持久化可恢复）；canonical `TechnicalPlan`/`PlanVersion` + `TechnicalPlanService` 唯一写入入口（INV-6）+ 旧 3 路径软链/lazy 迁移；`RepoRouterV2` 路由 + `DeliveryKnowledgeSearchService` 召回接入；filter_then_container 并行调研子 agent（`RepoResearchTask`/`PartialPlan` + 单仓重试 + 重索引 stale 重跑）；架构师融合 + 结构化 `MergedPlan` + `PlanValidator`（5 类跨仓校验）+ 跨仓依赖 DAG 显式建模；HITL `Clarification` 澄清回路；§15 事件 taxonomy 全程持久化；工作流入口 + Chat 薄封装复用同一 engine。前置修复 PF-01/02 已落地。审计 passed（19/19 需求、INV-2/5/6 成立）。

**已知 follow-up（tech debt）：** v0.2.0 chat/MCP 编码 dispatch 路径的实时明文 PAT 注入未覆盖、RTOOL-02/03/04 容器端 E2E 待真实环境验收；部分里程碑的纯观感人工验收（UAT）顺延。详见 `.planning/MILESTONES.md` 与 `.planning/STATE.md`。

**Codebase 现状：** 后端 Django 5.1+/Python 3.14（adrf + channels）、前端 Vue 3 + TS + Tailwind 4、Go runner、Python task executor；测试基线后端 ~520 个 `test_*.py`、前端 ~130 个 spec。完整代码地图见 `.planning/codebase/`。

## Current Milestone: v0.8.0 多仓串行编码 → 融合 PR

**Goal:** 把 v0.7 产的主方案（`MergedPlan.execution_plan` + 跨仓依赖 DAG）落成多仓代码：按跨仓依赖分层 wave 执行、上游产物注入下游、关联多仓融合 PR、编码遇阻抛 question 给人。**显式非目标：不做编码中全自动回溯重规划。** 详细数据模型见 `.planning/DOMAIN-MODEL.md` §6（`RepoCodingTask`：wave/`depends_on` DAG/`produced_artifacts`），前置修复台账见 `PREFLIGHT.md`（PF-06/07）。

**Target features:**

- 前置修复 PF-06：workflow 编码路径 `AICodingNode` 注入 branch strategy / git token env（对齐 chat 路径），私有仓 clone 成功 + 用正确目标分支
- 通用 resume 回流通路：消化 v0.7 audit D-2（chat deep-research 自动回流接线缺口）——立 `coding`/`plan_session` → 工作流/会话的通用 resume 回流通路，为 callback 驱动的多 wave 铺底
- `RepoCodingTask` 模型（plan_version/repository/wave/`depends_on` DAG/status/`produced_artifacts`/`follow_openspec` 预留 SDD 扩展点）+ 按 `execution_plan[].dependencies` 拓扑分层（消化 PF-07，不再全并行）
- wave 式执行：wave N 全 done 才触发 wave N+1（拓扑顺序推进 + wave 失败/部分回滚语义）
- 上游产物提取（API 契约/OpenAPI/diff）→ 注入下游 wave prompt/global_context
- 多仓融合 PR：各仓产出关联 PR/MR，diff base 用各仓正确 `target_branch`（非假设 master）+ 跨仓 PR 关联（cross-ref）
- 编码遇阻 → question 抛人：task 侧发起 question 抛给用户/orchestrator（复用已有 question 协议、补 task 侧发起 + orchestrator resume），非全自动 replan
- SDD 扩展点预留：`RepoCodingTask.follow_openspec` 标记 → 编码容器注入 openspec 指引（v0.9 做全）

**Key context:**

- 设计底座已就绪：`ROADMAP-vNext.md` §v0.8（Target features/现状坐标/已确认决策/候选 phases）、`DOMAIN-MODEL.md` §6（`RepoCodingTask` wave/DAG/产物注入 + 可靠恢复规则 + SDD 扩展点）、`PREFLIGHT.md`（PF-06 should-fix-before-v0.8、PF-07 can-fix-in-milestone）。
- **关键约束 / 非目标**：scope=`plan_to_pr`（主方案 → 多仓 wave 编码 → 融合 PR）；**不做编码中全自动回溯重规划**——编码遇阻走已有 question 协议抛给用户/orchestrator，全自动 replan 留 backlog 避免范围爆炸。
- **复用底座（已交付）**：v0.7 canonical `TechnicalPlan`/`MergedPlan`（含 `execution_plan` 跨仓依赖拓扑）+ `PlanSession` 编排状态机 + §15 事件 taxonomy；既有 `DispatchTask` 协议、RemoteTool MCP、callback 驱动 workflow resume、`execution_plan` schema、`waiting_event`、`AICodingNode` 并行派发、chat `coding_session_service`（branch strategy / git token env 在 chat 路径已有）。
- **现状缺口**：跨仓/跨任务上下文传递完全没有（`execution_plan[].dependencies` 仅 schema + prompt，`AICodingNode` 只按 `repository_id` 全并行不读 dependencies、不传产物）；动态重规划编码层几乎没有；workflow 编码路径 env 不一致（PF-06）；chat deep-research 自动回流缺口（v0.7 D-2）。
- 复用 `waiting_event` + callback resume 扩成多 wave，避免另造调度；wave 失败的部分回滚语义需明确。

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

### Active (v0.8.0)

<!-- 本里程碑正式需求由 REQUIREMENTS.md 管理（REQ-ID 级），此处为目标级摘要。 -->

- [ ] 前置修复 PF-06（workflow 编码路径 branch strategy / git token env 对齐）+ 通用 resume 回流通路（消化 v0.7 audit D-2）
- [ ] `RepoCodingTask` 模型 + `execution_plan` DAG 拓扑分层 + wave 调度（消化 PF-07，不再全并行）
- [ ] 上游产物提取（API 契约/diff）+ 注入下游 wave prompt/global_context
- [ ] 多仓融合 PR（diff base 用各仓正确 target_branch）+ 跨仓 PR 关联
- [ ] 编码遇阻 → question 抛人（HITL 回路，非全自动 replan）

**Backlog 候选（未入本里程碑）：**

- v0.9 SDD / OpenSpec（重型：打标 + 产 spec + 状态机/gate/评审 + spec↔需求/PR 关联 + 交付验收）——v0.8 仅在 `RepoCodingTask.follow_openspec` 预留扩展点字段位
- 编码中全自动 replan/回溯（v0.8 用「抛 question 给人」过渡，全自动留后续）
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
*Last updated: 2026-06-16 — milestone v0.8.0 started*
