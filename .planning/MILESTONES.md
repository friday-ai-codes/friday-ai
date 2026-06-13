# Milestones

## v0.4.0 工作流系统契约重构 (Shipped: 2026-06-13)

**Phases completed:** 5 phases, 25 plans, 58 tasks

**Key accomplishments:**

- 模板解析失败从静默空串/字面量保留改为三分类显式报错（中文 + 结构化 JSON 落 error_message），并落地嵌套 dict/list 路径下钻，两 API 共享同一纯函数解析核心。
- bulk-update 事务内实现客户端 short_id 权威落库 + 工作流内先到先得唯一性 + 缺失/冲突/非法时服务端重生成并全工作流重写 config 引用（复用公共化的 rewrite_template_refs），15 个集成测试锁定"保存成功 ⇒ 引用可解析"不变式。
- 新建 variableRef 单一构造 util 收口全部引用生成点（三入口 + schema 展示 + picker 前缀字面量），消灭 UUID 与 id.slice(0,8) 兜底；toBackendNodes 上送 short_id 补齐 VAR-01 前端半边；运行时 picker 双键去重。
- 逐文件核查 19 个 render_template/get_template_value 调用方：17 个 OK、2 个违规已最小修复（code_review chat_id 渲染前移、plan_generation as_of 渲染移出吞错 try），后端 workflows 358 测试 + 前端 983 测试全绿，A1 假设闭环。
- routing.py 边感知就绪/级联/死锁/target_handle 归集四类纯函数核心 + DAGNode.incoming_edges 入边明细，零 DB 单测全绿，为 18-02..05 主循环与回调续跑提供唯一语义源
- 调度主循环就绪/级联/后继/输入判定全部委托 18-01 routing 纯函数，条件分支真路由（仅选中支执行、未选中支级联 SKIPPED 且参与完成判定），target_handle 归集经端到端集成测试闭环；建立全阶段共享的 conftest 引擎测试基建。
- 主循环完成/挂起/死锁三类终局判定收口为单一 `_finalize_run_state`（双出口共用）：waiting_event/waiting_approval 统一挂起且不加回 pending（消灭热循环 + 永久 running 僵尸），死锁经 routing 诊断转 FAILED 写结构化 error_message，execution_suspended hook 打通；删除 5s 轮询分支与旧死锁分支。全量 tests/workflows/ 412 例零回归。
- `_continue_after_node` 退化为薄入口——执行级原子抢锁 → 带标记节点经 `_execute_node` 重跑（修复容器回调断裂 A1）→ `_rebuild_state_from_db` 重建真实 NE 状态重入 `_run_execution` 同一 while 调度循环与 `_finalize_run_state` 收口；coding_callback 第三套手工迷你调度器根除，三套回调收敛为一套统一入口。审计定性"两套路由实现漂移"最终消除。tests/workflows/ 419 例全绿、workflows+feishu+回调 519 例零回归。
- 后端 get_schema() 派生 default_config、NodeTypeSerializer 暴露 ui_schema/default_config（纯增量零回归），并新增 dump_node_fixture 管理命令把 33 个真实节点的精简定义快照入库，作为 CI 漂移守护对账基准。
- 幂等 Django 数据迁移 0026，把存量 `WorkflowNode.node_type='fetch_project_info'` 重写为真实节点 `fetch_space_info`，使老工作流收敛后仍能正确解析（D-03）。
- 把 `registry.ts` 对外 helper 改为从 `useNodeTypesStore`（唯一运行时源）读取并删除 `NODE_REGISTRY` legacy 硬编码区块，抽出前端专属 `CONFIG_COMPONENTS` 懒加载映射、降级 `validateNodeConfig` 为轻量 JSON-Schema 校验，并收敛全部消费方使 `pnpm type-check` 一次性通过。
- 把 `BaseWorkflowNode.vue` 的 Handle 改由 `useNodeTypesStore` 的 `inputs/outputs`（后端 NodePort）响应式渲染、store 未就绪时回退最小端口；`portConfig.ts` 的 `getDefaultPortsForNodeType` 退出正常渲染路径并保留 `migratePortId` 作存量 edge 兼容；`[id].vue` 取数顺序化（fetchNodeTypes 先行）并由后端 `category` 派生 `hasTriggers`。
- 前端展示层 `fetch_project_info` 全量改名 `fetch_space_info`、删除死代码 `IntegrationNode.vue`，并把 `node-sync.test.ts` 从手维 `EXPECTED_NODES` 重写为 fixture 驱动离线漂移守护、修正 `validate-node-definitions.ts` 的 API URL，同时修复 19-03 引入的 `workflow-data-table.test.ts` 缺 pinia 回归。
- 1. [Rule 2 - 缺失关键功能] bulk-update config 校验让位机制（serializer skip_config_validation context）
- 修复两个断裂内置模板（daily_summary 字段对齐 body/text；code_review_pipeline 按方案 A 去 http 中转节点、trigger→review[target_handle=coding_result]→notify、引 review_report、文档化 webhook payload 前提），让 loader 在 acreate 前调用与保存同源的 WorkflowGraphValidator 拒绝非法模板（TPL-03，无半残 workflow），并扩展 test_template_loader 守护每模板零 error + 5 类 schema 可判定断裂注入 + loader 拒绝（TPL-01/02/03）。
- 扩展 `useWorkflowValidationStore` 摄入后端 `WorkflowGraphValidator` 的 `{errors, warnings}`（severity + 多 reason，支持 node 级与 edge 级），让 `saveWorkflow` 在 bulk-update 返回 400 时解析结构化 body 灌入 store 并阻断保存，`IssuesPanel` 改由 store 真实驱动渲染并按 severity 区分 error/warning——消除「`useWorkflowValidationStore` 无调用方、`IssuesPanel` 的 `v-if=hasWarnings` 永 false」的死代码（VAL-03）。
- 为 TRIG-01/02/03 + OBS-01（后端）建立 13 个先行失败测试锚点：feishu 触发同步、schedule 枚举移除、dispatch 失败持久化、WS 失败广播——锁死修复后契约，待 21-03/04 转绿。
- 4 个 RED vitest spec 锁死 OBS-01/02/03 前端契约：ExecutionStatus 全覆盖 badge、node_failed 写 error 字段 + stats suspended 语义、WS 断线降级轮询、结构化变量错误 parse + error_code 行
- 修复触发链路根因：`async_sync_workflow_triggers` 改读单数 `event_type`（复数兜底）并把可正向表达的 filter 字段写入 `filter_config`，消除"读复数→恒空→trigger 被 deactivate→飞书事件无法匹配"；dispatch 失败不再静默吞掉——飞书路径落 `TriggerLog`（error/ignored + 截断 error_message），webhook 路径返回区分原因的结构化响应。
- 移除僵尸触发类型 schedule（枚举 + 0027 AlterField 安全收窄），并让 WebSocketBroadcastHook 在节点失败/超时时广播 error_message/error_code，将 21-01 的 RED 测试转绿。
- 前端移除所有工作流 schedule 假触发类型残留（联合类型/标签/图标 + 夹具），并将 executions 列表 statusOptions 与后端 ExecutionStatus 对齐（补 suspended/timeout）、stats 等待态按 execution 级 suspended + node 级 waiting_approval 区分
- NodeOverviewTab 展示 error_code + 结构化变量错误友好解析（非 JSON 回退纯文本）；DAG ExecutionNode 补 suspended/timeout 色 + 失败节点 error tooltip；useExecutionState 在 WS 断线时降级 REST 轮询（fetchExecution 权威值），重连/终态停止。

---

## v0.3.0 交付知识图谱 (Shipped: 2026-06-12)

**Phases completed:** 5 phases (12–16), 23 plans

**Delivered:** 把需求/缺陷、技术方案、编码 diff 全链路 RAG 化，并以带时间语义（bi-temporal）的知识图谱关联；任意入口可召回相似历史需求及其完整迭代轨迹。

**Key accomplishments:**

- 知识模型与图存储：四类实体 + bi-temporal 边 + supersedes 版本链 + GraphStore 递归 CTE 收口 + `delivery_knowledge` collection 生命周期
- 统一摄取与版本化：幂等异步摄取管线（chat/MCP/workflow/飞书/编码回调六类触发点），版本翻转与向量下线，全量 diff 归档与 MODIFIES_CHUNK 代码图谱对齐
- 时间感知混合检索：`DeliveryKnowledgeSearchService` 融合向量召回 + 图扩散 + 时间衰减 + LLM 二阶段分级，PG 轨迹/关联查询，fail-closed 权限过滤
- 多入口暴露：MCP PAT 三工具 / chat agent tools / workflow 检索节点 + ai_plan_generation 飞轮 / npm friday-knowledge skill，四入口复用 `exposure.py` 序列化
- 前端只读时间线：实体详情页 + 关联时间线 + as-of 时点查询，REST `/api/knowledge/*` 与 JWT 实体详情 API

**Stats:** 28/28 v1 requirements delivered, 2026-06-11 → 2026-06-12.

**Known deferred items at close:** 1 — Phase 14 真实 git platform 超大 diff 截断需 dev 环境人工验收（TD-14，详见 audit）

**Known follow-ups (tech debt):**

- W1: 前端 `searchDeliveryKnowledge` 无 UI 消费（index 为占位页）
- W2: timeline 节点级 `provenance` 未填充
- W3: graph enrich 边类型统一标为 RELATES_TO

---

## v0.1.0 首启初始化向导 (Shipped: 2026-06-09)

**Phases completed:** 5 phases, 9 plans

**Delivered:** 用「首次访问引导用户自设账号」替代启动期自动建管理员，并在向导内一次配好管理员、LLM 供应商、安全校验与可选的飞书/RAG 集成。

**Key accomplishments:**

- 首启门禁：无任何 superuser 时首次访问自动进入向导，已初始化实例 fail-closed 拒绝（防重入/防接管）
- 管理员自设：向导内自定义用户名+密码（强度校验），提交即建 superuser 并自动登录直达首页
- 供应商一键预设：DeepSeek V4 Pro / MiMo V2.5 Pro / Kimi 2.6 / Anthropic 官方 / 自定义端点，Fernet 加密落库 + 健康校验 + 绑定 Claude Code 模型映射
- 安全与可选集成：SECRET_KEY/FRIDAY_ENCRYPTION_KEY 风险校验（非阻塞）+ 可一键跳过的飞书、向量检索（Qdrant/Embedding）配置步骤
- 向后兼容：`entrypoint.sh` 默认不再自动建号，`init_superuser`/`reset_superuser_password` 保留为运维兜底，老部署升级不回退

**Known deferred items at close:** 2 — Phase 01 / 02 人工验收（UAT）签字未完成（功能已实现，详见 STATE.md Deferred Items）

---

## v0.2.0 用户身份令牌与 Agent 工具打通 (Shipped: 2026-06-10)

**Phases completed:** 6 phases (6-11), 21 plans

**Delivered:** 给每个用户一套 GitHub/GitLab 风格的个人访问令牌（PAT），以「用户身份 + 用户权限」贯通认证、会话隔离、管理员只读后台与 agent 工具链路，使 skill/mcp 能以用户令牌在容器内执行。

**Key accomplishments:**

- PAT 模型增强：令牌加名称/备注/可选有效期（默认永久、不可延期）+ 前缀…后缀指纹，明文仅展示一次（仅存 sha256），用户自助创建/吊销
- 令牌即用户身份（认证地基）：PAT 认证返回 owner 并施加其 RBAC（替代「有效即全权限」），friday_pat_ 前缀闸门让 PAT/JWT 互不干扰，MCP/工具入口收紧为 fail-closed
- 对话/会话用户隔离：Conversation 加 created_by + 历史回填最早 superuser，全 25 路径按 owner 过滤（含 SSE/WebSocket），越权 404 不泄漏存在性
- 管理员只读会话后台：物理隔离的 /api/admin/conversations/（IsSuperUser）浏览所有会话，只读防误操作，交互需 fork 到自己名下
- MCP 绑定 + RemoteTool 执行端点：ToolTokenBinding 持久绑定令牌给 skill/mcp，新增经 PAT 认证 fail-closed 的按工具 name 执行端点供容器回调
- task 容器接通（链路机制闭环）：容器消费 remote_tools 经 SDK MCP server 加载工具，PAT 经 server→runner→task 直传注入并全程脱敏，令牌吊销 graceful（在途跑完仅阻断新调用）

**Stats:** ~6,200 行净增（60 文件，server/web/runner/task），150 commits，2026-06-09 → 2026-06-10。

**Known deferred items at close:** 6 — Phase 6-11 人工验收（UAT）顺延（自动化全绿，浏览器/容器级 E2E 待人工确认，详见 STATE.md Deferred Items）。

**Known follow-ups (tech debt, by-design):**

- Phase 11 实时明文 PAT 通道（contextvar）未接入：_resolve_user_pat 恒返回 ''，RemoteTool 链路端到端休眠、ToolTokenBinding 暂未被执行路径消费（受 PAT-02 明文不落盘约束的有意推迟，Open-Q1 Option C）
- MCPB-02 集成 PARTIAL：执行端点已按 PAT 认证为 owner，但 execute_tool 未接收 user 上下文
- Nyquist 卫生：各阶段 *-VALIDATION.md frontmatter nyquist_compliant 仍为 false（仅标志位未回填）

---
