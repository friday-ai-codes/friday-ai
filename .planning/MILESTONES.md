# Milestones

## v0.5.0 索引检索地基与排除文件 (Shipped: 2026-06-15)

**Phases completed:** 5 phases, 23 plans, 54 tasks

**Key accomplishments:**

- 建立排除配置单一事实源（RepoExclusionRule + 全局默认 SystemSetting 键）与单一匹配器 `is_excluded(repository_id, rel_path)`：编译一次/复用、dir/glob/regex 三类规则、运行期 fail-closed、构造期非法 regex fail-loud，内置开箱即用安全默认。
- 把 Plan 01 的单一匹配器挂接到索引扫描面（full + incremental 两条 `scan_directory` 路径），被排除文件从源头不进 `files_to_process` / `local_hashes`，fail-closed；同时修正 PF-04 —— `scan_directory` 不再谎称已应用 `.gitignore`，注释/docstring 如实描述「目录名 + 扩展名白名单 + 排除匹配器」真实口径。
- 把 Plan 01 的单一匹配器挂接到 RAG 单一 chokepoint（`search_rag` + 图谱邻居 hop1/hop2/cross-repo 渲染）与进程内 chat/agent 工具读取面（`browse_file_content` 拒读、`list_space_structure` 文件树过滤、`search_repository_code` 兜底过滤）——被排除文件在检索 / 工具读取面 fail-closed 不可见，命中即拒读/丢弃，绝不降级泄漏明文；并落地跨面守护测试（索引扫描 + browse + RAG 三面同一文件均不可见）。
- 把排除过滤延伸到编码容器读取面：server 两条编码派发路径（chat `build_dispatch_metadata` + workflow `AICodingNode._run_repo_coding`）无条件下传有效排除规则经 `env_FRIDAY_TASK_EXCLUDE_PATTERNS` 注入；task 容器在 clone+checkout 后按规则物理删除工作树中被排除文件（跳过 `.git/`），删除持久失败时 fail-closed 抛错使 setup 失败——绝不让容器内 agent 看到被排除文件。
- 为排除配置提供 REST API（CRUD + regex fail-loud 校验 + 缓存失效）与仓库详情页最小编辑面板：列出全局默认（只读可关闭）+ per-repo 增删，保存即时生效，措辞如实（仅承诺 Friday 不可见，不承诺 git 物理删除），完成 EXCL-01「用户可配置」闭环。
- 把外部暴露的 MCP HTTP 直读面（grep_repository / get_repository_file / list_repository_files / find_related_chunks）挂接 Plan 01 的单一匹配器，对被排除文件 fail-closed 不可见——镜像直读与索引回退两条路径都拦，关闭 bare-mirror 残留泄漏通道（EXCL-02 工具面补齐）。
- 闭合 22-VERIFICATION 唯一阻断缺口（EXCL-02）：`CodeSearchView._search`（认证 REST 端点 `POST /api/repositories/<id>/search/`，前端 `searchCode` 在用）原直读 `BranchAwareSearchService.search` 返回 `content`/`file_path` 无任何 `is_excluded` 过滤，被排除文件明文与路径会经该 RAG 旁路直读面泄漏。本 gap 镜像 22-03 `search_rag` chokepoint 模式，给该端点自挂同一 `build_matcher_for_repo` + `matcher.is_excluded` 过滤——被排除文件 fail-closed 不可见，并补对称守护测试。
- 统一文件删除入口 purge_file 一次删净 Qdrant 主+overlay / FileIndex / ChunkRegistry(+ChunkEdge) / codegraph 五面，三条索引删除路径收敛收口 PF-03 + PF-05，删后无残留 + 幂等有守护测试证明。
- `compute_reconciliation`（已索引 ∪ ChunkRegistry ∩ 现行匹配器，列出已索引但现命中排除的差异，匹配器构造失败置 degraded 不谎报已一致）+ `run_cleanup(normal)`（逐差异文件 purge_file 删净四面、对账归零）+ `CleanupRun` 持久化 + 对账/清理/状态 REST API（GET 差异 / POST 派发后台返回 run_id / GET 状态回流敏感未清面）+ 审计埋点，敏感分支懒导入契约就位。
- `purge_sensitive_planes` 在普通排除清理之上额外清操作记录面——CodeChangeArchive file 级 scrub（剔除被排除文件 diff 段 + 重算计数，仅含该文件整行删，含他文件不误删）、TaskResult/ActionLog 经 repo_url↔git_url 归一关联本仓的可控清理（关联不确定保守不动）、message parts/content 子串脱敏；无精确 file 关联面（prompt snapshot/备份/git object）如实记 unscrubbed + caveat 绝不假装清除，兑现 23-02 sensitive 懒导入契约。
- `reconcileApi`（getReconcile/cleanup/getCleanupStatus，类型对齐 23-02/23-03 契约）+ `ReconcilePanel.vue`（对账差异展示 + degraded『对账不可信』警示并禁用清理 + 普通/敏感双清理入口分离 + 敏感强确认含不可逆/不承诺 git/备份物理消失如实措辞 + 派发后轮询 getCleanupStatus 如实回显 CleanupRun 真实 unscrubbed 面 + caveat）+ 仓库详情页挂载 + zh-CN 文案 + 5 例守护测试，兑现 EXCL-06 可见闭环（W1/W2/W3、§9.1/§9.2）。
- SensitiveFileSuggestion 模型 + 迁移 0034 + services/sensitive_detect.py 确定性检测器（独立有界遍历 + 文件名启发式复用 Phase 22 基线 + 内容密钥扫描 + 全程脱敏 reason + aupdate_or_create upsert）
- run_full_index FINALIZING 末尾经 run_in_background best-effort 触发确定性检测（检测失败不阻断索引 success），并新增可选 LLM 二分类段 classify_ambiguous_files（provider 缺失/失败 graceful 退化、强密钥绝不外送、最小化布尔特征）
- 为 EXCL-03「建议 + 确认」面提供 REST 工作流：列出某仓 AI 敏感文件建议（severity 排序、real_secret 优先、`?status` 过滤），接受（→ 幂等创建 `RepoExclusionRule(source=ai_suggested, rule_type=glob)` + 标 accepted + `invalidate_matcher_cache`），忽略（标 dismissed）。全程绝不静默删除已索引/派生数据——删除仍由既有 Phase 23 reconcile/cleanup 用户显式触发。
- 兑现 EXCL-03 用户可见闭环：仓库详情页排除区新增「AI 敏感文件建议」面板——按 severity 排序展示建议、real_secret 高优先级告警、接受（幂等建 `ai_suggested` 排除规则）/忽略（dismiss）操作，接受后引导用户用既有「对账与清理」面板做显式删除（绝不静默删）。接通 24-03 REST 契约与 Phase 22/23 既有面板。
- 索引时把每个 chunk 的 1-based 闭区间源码起止行写入 ChunkRegistry（line_start/line_end），打通 `file:line → chunk_id` 反查的数据地基——create + update 双路径落库，重切分行号位移触发更新，复用既有 CheckConstraint 无新 migration
- 给定 repo+file+line 定位覆盖该行的 chunk(s)：`find_chunk_at` 服务按 1-based 闭区间命中、最具体（区间最小）优先，复用 Phase 22 单一排除匹配器对被排除文件全程 fail-closed；`GET /api/repositories/<id>/chunk-at/` REST 端点认证保护，被排除文件与无命中对外同形返回空 chunks 不泄漏存在性。
- git 历史按 commit 产出 RAG 文档（message + author + 变更文件路径摘要），经 Phase 22 单一匹配器 fail-closed 剔除被排除文件、截断、embedding 入 Qdrant 主 collection 并打 kind=commit payload，确定性 uuid5 point id + 合成 file_path 保 dedup，增量 boundary..HEAD 只索引新 commit、upsert 成功才推进边界。
- 把 25-03 的 `index_commits` 以 best-effort 方式挂接进 `clone_and_index_repository`——仅 base 索引路径、紧随敏感检测之后、临时克隆 `rmtree` 之前 `await` 完成（沿用 Phase 24 BL-01 时序），全量与增量均流经；commit 索引失败仅 warning 绝不阻断索引 success；并以端到端守护测试验证 commit 文档经既有 `search_rag` 用关键字/author 召回、被排除文件不泄漏、增量只新增。
- GitInstanceCredential 按 host 维度集中存 Fernet 加密 token，配套单一解析器 per-repo 优先 → 实例池 host fallback，多仓复用一份凭证且向后兼容
- 把 26-01 解析器接入「克隆 / 索引 / bare 镜像 fetch / 图谱克隆」三条取 token 路径，消除散落的内联 `GitCredential → decrypt_value`，无 per-repo token 的同 host 多仓改为复用实例凭证，per-repo token 仍优先（向后兼容）
- 把 26-01 解析器接入「git 平台 MR/PR 客户端 + 编码容器 dispatch 的 git token 注入 + diff archive 拉取」五处取 token 路径，无 per-repo token 的同 host 多仓改为按 host 复用实例凭证，per-repo token 仍优先（向后兼容）；token 绝不进日志
- 实例级 Git 凭证 REST CRUD（token write-only Fernet 加密、IsSuperUser、API/DB/日志/前端全程无明文）+ Vue 3 管理页（has_token 徽标、token 不回显）+ base-branch 校验改经统一解析器
- 为 MCP RAG 检索工具 `search_rag_chunks` 增加多仓（`repository_ids`）/ 全仓（`all_repositories`，受 `max_repos` 限制）检索参数，跨多仓合并召回并按 `item.repository_id` 标注结果来源仓库；多仓解析严格对齐 `grep_repository` 范式（serializer 产出 `target_repository_ids`，view 逐仓校验 + 一次性 `HybridSearchService.search(repository_ids=valid_ids)`），每仓仍经 Phase 22 `search_rag` chokepoint `build_matcher_for_repo` fail-closed 排除——被排除文件跨仓不可见；省略多仓参数时维持既有单仓行为与响应形状（向后兼容）。
- 把 26-VERIFICATION 标记的残留 6 文件 ≥8 处内联 `decrypt_value(credential.encrypted_token)` 取 token 全部改经统一解析器 `aresolve_git_token`，使仅靠实例凭证池（无 per-repo token）的同 host 仓库在 PR 创建/cross-reference/冲突预检/code review diff 拉取/两处容器 dispatch/既有仓库测试连接路径不再失败或注入空 token

---

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

**Known follow-ups (tech debt):** — ✅ 全部已于 2026-06-14 解决（commit 5435fef23）

- ~~W1: 前端 `searchDeliveryKnowledge` 无 UI 消费（index 为占位页）~~ → index 改为真实搜索页
- ~~W2: timeline 节点级 `provenance` 未填充~~ → 前端渲染 + 修后端跨版本串味 bug
- ~~W3: graph enrich 边类型统一标为 RELATES_TO~~ → related.py 多跳取真实 edge.relation + 前端 relation 标签

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

**Known follow-ups (tech debt, by-design):** — 部分已于 2026-06-14 解决

- ✅ ~~Phase 11 实时明文 PAT 通道（contextvar）未接入：_resolve_user_pat 恒返回 ''，RemoteTool 链路休眠~~
  → 已接入（commit 8cb50e928）：请求级 ContextVar → ExecutionContext 瞬态字段，AICoding dispatch 注入 USER_TOKEN；
  明文绝不落库/进日志。剩余：chat/MCP dispatch 路径未覆盖；带 PAT 容器端 E2E 待真实环境验收

- MCPB-02 集成 PARTIAL：执行端点已按 PAT 认证为 owner，但 execute_tool 未接收 user 上下文（仍 deferred）
- ✅ ~~Nyquist 卫生：各阶段 *-VALIDATION.md frontmatter nyquist_compliant 仍为 false~~ → v0.4.0 的 18-21 已回填（commit 37a3bd6b2）

---
