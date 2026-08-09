# Phase 126: 执行流 + rename_preview + skills - Context

**Gathered:** 2026-08-10
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous，用户授权全量采纳推荐答案 — skip Sub-step 4 prompting）

<domain>
## Phase Boundary

本相位交付三件套，把 Phase 121–125 的图能力收成 **可查询执行流叙事 + 只读改名清单 + 可分发工作流 skill**：

**IN SCOPE（EXEC-01/02/03, RENAME-01, SKILL-01）:**
- 以既有 `Endpoint` 为确定性入口做正向 BFS，结果落独立 `ProcessTrace` 模型（摘要路径，非整图展开）
- BFS 纪律硬锁：maxDepth 10 / maxBranching 4 / minSteps 3 / 边置信度 ≥0.5 + 去重；环与 async 断链显式标注
- 执行流社区归属 `intra_community` / `cross_community`（消费 Phase 125 `SymbolCommunity`）
- MCP + 对话双面可查询 Process；`detect_changes` / `impact` 信封回填 `affected_processes`；`impact_report` MR 段消费该叙事
- `rename_preview` 只读双源清单（图引用 + `grep_mirror` 文本兜底），按文件分组，声明动态引用覆盖限制，**绝不改写**
- `impact-analysis` / `refactoring` 两个工作流 skill 进 `@friday-ai-codes/skills` 同源分发，复用 v0.17.0 hash 一致性机制，编码容器可注入

**OUT OF SCOPE:**
- ⛔ `server/codegraph/services/repo_router_v2.py` 零改动（冻结面延续）
- ⛔ `mcp/` git submodule 零改动（沿用 122 D-27 — 工具漂移只记账，本相位只动 `server/mcp_tools` 薄壳）
- Semgrep / LSP（Phase 127）；Galaxy / 前端执行流可视化
- rename apply / 批量改写；runner 硬门禁
- 与 `services.process_runtime`（`ProcessEngine` / `ProcessDefinition`）混名或合表
- 社区算法重开 / Leiden；摘要打分第四分量

</domain>

<decisions>
## Implementation Decisions

### Area 1: Process BFS 持久化 / 刷新 / 模型 schema（EXEC-01/02）

- **D-01 — 独立模型名锁定为 `ProcessTrace`（research ARCHITECTURE），落点 `server/codegraph/models.py`，纯加表、零改既有表。** ⛔ 不得命名为 `Process`（与 `services.process_runtime.ProcessEngine` / `ProcessDefinition` / delivery `process_type` 撞名）。字段最小集：`repository` FK、`branch_name`（`""`=基线，对齐 Symbol/Endpoint/SymbolCommunity）、`process_key`（稳定键）、`name`（展示名）、`entry_endpoint` JSON 快照（`{http_method,url_path,handler_name,file_path,line_number}`，⛔ 不对 `Endpoint` 建 FK——索引删建会牵连）、`steps` JSON（主干有序摘要，见 D-04）、`community_class`（封闭枚举 `intra_community` | `cross_community`）、`step_count`、`built_at_sha`（对齐 `last_indexed_commit_sha`）、时间戳。`unique_together = (repository, branch_name, process_key)`。
- **D-02 — 入口与 BFS 纪律硬锁 ROADMAP / GitNexus 同款数值，不作相位内再议。** 入口 = 该仓该分支已落库的 `Endpoint` 行映射到图上的 handler 符号（确定性，不做多因子入口打分）。遍历：正向 BFS；`maxDepth=10`；`maxBranching=4`；`minSteps=3`（滤掉平凡两步流）；只走置信度 ≥0.5 的边；visited 去重；同 entry→terminal 端点去重留最长 + 子集去重（短 trace 是长 trace 子串则删）。`maxProcesses` 初值按仓规模动态 `max(20, min(300, symbolCount/10))`（可 settings/env，Claude's Discretion 微调但不改成功标准四个硬闸）。环：检测后标 `cycle: true`（或等价字段），⛔ 不静默跳过。async 断链：识别已知派发模式（`sync_to_async` / durable `defer` / `.delay(` / channel `group_send` / workflow dispatch 等，词表 Claude's Discretion 扩展）在链路末端标 `boundary: async_dispatch`，v1 **不跨过**边界。
- **D-03 — 刷新语义照抄 Phase 125 社区：全仓全删全建，投 durable `QUEUE_GRAPH`，不在索引钩子内联跑。** 触发点 = 社区检测落库完成之后（Process 分类依赖 `SymbolCommunity`；若社区任务失败/空，Process 仍可建但 `community_class` 降级声明，见 D-05）。`queueing_lock=f"process:{repo_id}:{branch}"` 去重防抖；`initiated_by_user_id` 透传（无则 `system`）。任务内经 barrel `get_graph_service` 取图，⛔ 不直连 loader/cache，⛔ 不进 `repo_router_v2`。`built_at_sha` 落水位，查询方可判 stale。
- **D-04 — 落库存「入口 + 主干路径 + 统计」，不存全展开节点集（Pitfall 4）。** `steps[]` 每项至少 `{symbol_id?, name, file_path, line?, depth, community_key?}`——`symbol_id` 为 UUID 字符串软引用（对齐 125 D-02）。单行 JSON 体积纪律：主干截断 + summary 计数；超限标 `truncated`。`process_key` / `name` 启发式：优先 `METHOD path` 或 handler 名派生，须稳定可复现（细节 Claude's Discretion）。

### Area 2: MCP 查询 + `affected_processes` 回填进 impact_report（EXEC-02/03）

- **D-05 — 社区分类：路径上符号对账 `SymbolCommunity.members` 软引用。** 路径成员（可解析到的）落在同一 `community_key` → `intra_community`；跨越 ≥2 个社区 → `cross_community`（架构上更重要，查询默认可按此类优先排序）。无法对账（社区未建 / 成员孤儿）→ 仍落库 Process，但输出带 `community_class_unknown` / degradation 声明，⛔ 不编造社区。
- **D-06 — 双面查询照抄 122 D-21：共享编排 + MCP/对话薄壳，逻辑不许在壳里分叉。** 新增编排入口（建议 `run_list_processes` / `run_get_process`，落 `server/services/code_graph_tools.py` 旁路，与 `run_impact`/`run_detect_changes` 同级）；内核纯函数优先 `server/services/code_graph/process_trace.py`。MCP：`McpToolView` + PAT fail-closed + schema snapshot + `RetrievalTrace`；对话：`agents/tools` `@tool`。查询参数最小集：`repository_id` + 可选 `branch_name` / `community_class` / `symbol_id`（命中含该步的流程）/ `limit`。信封复用 122：`ok`/`error_code`/`error` + `staleness` + `degradation`；`as_of`=`built_at_sha` 或索引水位。⛔ 不碰 `mcp/` submodule（122 D-27）；SUMMARY 更新 snapshot 漂移计数即可。
- **D-07 — `affected_processes` 回填点 = `run_detect_changes` 与 `run_impact` 已预留的空数组字段（123 D-12 / 122 VERIFICATION），单一组装 helper，禁止第三套方言。** 匹配：变更/impact 命中符号的软 id（或 `file_path:name` 回退键）∩ `ProcessTrace.steps` → 产出 `{name, process_key, affected_steps[], total_steps, community_class, step?}`。无 Process 行 / 无交集 → `[]`（合法，fail-soft）。批量 detect_changes 路径：在 batch impact 汇总后一次查仓内 Process 集再对账，避免 N 次扫表（具体索引 Claude's Discretion）。
- **D-08 — MR `## 影响面` 消费：在 Affected 小节增值「受影响执行流」清单（名称 + 可选 step/totalSteps），由 `build_impact_report_section` 单一入口渲染。** 有数据则替换 Phase 124 占位句「执行流叙事待 Phase 126…」；仍为空则保留短声明「暂无匹配执行流 / 未构建 Process」，⛔ 不编造。体积纪律继承 124 D-08（top-N + truncated）。双链路（workflow coding MR + MCP create_merge_request）继续共用同一 formatter（124 D-14）。

### Area 3: rename_preview 双源合并 / 置信度 / 只读安全（RENAME-01）

- **D-09 — 只读预览工具，双源合并：图解析引用为主 + `grep_mirror` 文本兜底；按文件分组输出清单，`applied` 恒为 `false`。** 内核建议 `server/services/code_graph/rename_preview.py`；编排 `run_rename_preview` 进 `code_graph_tools.py`；MCP + 对话双面薄壳同 D-06。⛔ 本相位不提供 apply/rewrite API、不改工作树、不写 mirror。输入：目标符号（uid 优先，重名走 122 D-19 消歧）+ 新名；输出 edits 列表供编码代理自行改。
- **D-10 — 逐条置信标签二值：`graph` | `text_search`（RENAME-01 / GitNexus 同款），附 `context` 片段；同 `file:line` 双源命中时保留一条并以 `graph` 为准（或 `sources: ["graph","text_search"]` 但展示置信取 graph）。** summary 计数：`total_edits` / `files_affected` / `graph_edits` / `text_search_edits`。⛔ 不发明第三档「maybe」数值分掩盖不确定性。
- **D-11 — 安全与 exclusion：grep 半边必须走既有已拦截路径（`grep_mirror` + MCP grep 同款 exclusion fail-closed），禁止另起裸 grep（Pitfall）。** 输出头部/信封显式声明动态引用覆盖限制（字符串模板、反射、`getattr`、配置拼路径等 v1 不保证命中）。`include_content` 默认只给短 context，不灌全文。ACL / 未索引 / 消歧失败语义对齐 122/123（硬拒或 `ok=False`，不静默空清单假装「零引用」——空清单仅当双源都真实零命中且声明完整）。
- **D-12 — 容器白名单：`rename_preview` 可进 `task/core/knowledge_tools.py` 白名单（与 detect_changes 同路），skill 指引编码代理「先 preview 再自行编辑」；失败不阻断交付。** prompt 长文案放 skill 正文，不在 runner 硬编码改写逻辑。

### Area 4: Skills 打包 / hash / 容器分发（SKILL-01）

- **D-13 — 两个新 skill 落 `@friday-ai-codes/skills` 子模块源目录 `skills/skills/`，命名对齐既有 `friday-*` 惯例：`friday-impact`（impact-analysis 工作流）与 `friday-refactoring`（refactoring + rename_preview 工作流）。** 正文 zh-CN；内容 = 触发条件 + 工具调用顺序 checklist（先 context/staleness → detect_changes/impact/list_processes → rename_preview），不复制工具实现。更新 `skills/README.md` 技能表与安装器枚举面（照抄 friday-routing 接入先例）。⛔ 不在主仓手写第二份 skill 正文。
- **D-14 — 编码容器同源：扩展 `task/scripts/sync_skills.py` 与 `task/tests/test_skills_injection.py` 的 `SKILL_NAMES`，纳入 `friday-impact` / `friday-refactoring`（二者均为编码期工作流，与 friday-routing「仅 IDE」分流不同）。** 改源后必须重跑 `python task/scripts/sync_skills.py`；`TestSkillsHashConsistency` 逐文件 sha256 守卫防双源漂移。镜像 COPY 路径沿用 `task/assets/skills/`（v0.17.0 AGENT-03）。
- **D-15 — 分发契约：子模块内提交 skill 源 + 主仓提交子模块指针 + `task/assets/skills/` 同步结果 + 文档；npm 发版 `@friday-ai-codes/skills` 为运维 follow-up（可记 Deferred，不阻断相位验收——验收以源目录存在 + hash 绿 + 容器注入测为准）。** 外部 agent 经既有 `npx @friday-ai-codes/skills install` 路径获得；不另造安装器。
- **D-16 — 冻结与并发纪律延续：** ⛔ 不改 `repo_router_v2.py`；⛔ 不改 `mcp/` submodule。本相位若新增 server MCP 工具名，SUMMARY 记账 npm 客户端漂移即可。并发 WIP：提交本 CONTEXT / 后续相位文档时**只 stage 显式路径**，禁止 `git add -A`。

### Claude's Discretion

- `process_key` / `name` 启发式具体字符串；`maxProcesses` 与 settings 键名；async 断链词表扩写。
- Process durable 任务是独立 task name 还是挂在 community 完成回调链式 enqueue（须仍走 `QUEUE_GRAPH` + 独立 queueing_lock）。
- `steps` JSON 是否额外存边 reason；查询工具是 list+get 两个还是一个带 detail flag。
- rename_preview 参数命名（`old_name`/`new_name` vs `symbol_id`+`new_name`）、context 行窗大小、双源合并字段是单 `confidence` 还是 `confidence`+`sources[]`。
- skill 正文长度与是否附 `references/` 小抄；npm version bump 时机。
- 测试组织：BFS 合成图单测、社区分类、affected_processes 对账、rename 双源 fixture、skills hash、impact_report 快照。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Endpoint 入口**：`server/codegraph/models.py::Endpoint`（`http_method` / `url_path` / `handler_name` / `file_path` / `line_number` / `branch_name`）— EXEC 确定性入口，无需新建入口检测器。
- **SymbolCommunity（Phase 125）**：`codegraph.models.SymbolCommunity` + `services/code_graph/community.py` — soft-ref members、指纹/Jaccard、`QUEUE_GRAPH` 全删全建；Process 分类与刷新时序依赖它。
- **图工具双面范式（Phase 122/123）**：`server/services/code_graph_tools.py`（`run_impact` / `run_trace` / `run_detect_changes`）；MCP `McpToolView`；对话 `agents/tools/graph_tools.py`；信封 `staleness`/`degradation`/`affected_processes: []` 占位已在。
- **impact_report（Phase 124）**：`server/services/code_graph/impact_report.py` — `build_impact_report_section` / `append_impact_report`；Recommendations 现有占位句明确留给本相位；挂点已在 `workflows/nodes/ai/coding.py` 与 `mcp_tools/merge_request_service` / `mr_service`。
- **grep 兜底半边**：`services/repo_mirror.grep_mirror` + MCP grep exclusion 过滤 — rename 文本源必须复用，禁止裸 grep。
- **Skills 同源管线（v0.17.0）**：`skills/` 子模块（`@friday-ai-codes/skills`）、`task/scripts/sync_skills.py`（当前 `SKILL_NAMES=("friday-code","friday-memory")`）、`task/tests/test_skills_injection.py::TestSkillsHashConsistency`、`task/assets/skills/` 构建物料。

### Established Patterns
- 新持久化 → 独立模型 + JSON 软引用快照，不加在会被索引删建的行上（125 D-01/D-02；research Pattern 4）。
- 重计算 → 钩子/上游完成只 enqueue，`queueing_lock` 去重，`initiated_by_user_id` 必带。
- 工具面 → 内核纯函数 + 共享编排 + MCP/对话薄壳；逻辑不分叉；`component="code_graph"`；caller vs sampling。
- MR 增值段 → fail-soft、单一 formatter、不阻断建 MR。
- Skills → 子模块单一事实源 + sync 脚本镜像 + sha256 守卫；禁止手改 assets 副本。

### Integration Points
- NEW：`ProcessTrace` model + migration；`services/code_graph/process_trace.py`；`rename_preview.py`；durable process rebuild task
- MODIFY：`code_graph_tools.py`（回填 `affected_processes` + 新 run_*）；`impact_report.py`（Affected 执行流段）；MCP views/urls/serializers + agents tools；`task/core/knowledge_tools.py`（rename_preview 白名单）
- SKILLS：`skills/skills/friday-impact/`、`skills/skills/friday-refactoring/` + sync_skills `SKILL_NAMES` 扩展 + assets 重同步 + README
- ⛔ 不改：`repo_router_v2.py`；`mcp/` submodule；`ProcessEngine` 运行时域

</code_context>

<specifics>
## Specific Ideas

- research 模型草图用 `ProcessTrace`；ROADMAP/REQUIREMENTS 口语「Process 模型」= 同一物，实现与文档对外可称「执行流 / Process」，代码标识符用 `ProcessTrace`。
- BFS 四个硬闸（depth/branching/minSteps/conf≥0.5）与「只出清单不改写」是需求级验收，不是优化项——计划必须有自动化测试钉死。
- `affected_processes` 自 Phase 122/123/124 一路空数组占位到本相位，回填后 impact_report 占位句必须消失或变为真实清单/明确空态。
- Skills 命名用 `friday-impact` / `friday-refactoring` 对齐包内 7→9 的 `friday-*` 词表；ROADMAP 英文名 impact-analysis / refactoring 写进 skill description/触发词即可。
- 并发会话有其他 WIP：提交 CONTEXT 时**只 stage 本文件**（经 gsd-tools 显式路径）。

</specifics>

<deferred>
## Deferred Ideas

- `mcp/` npm 客户端为新 MCP 工具名补条目并发版（沿用 122 D-27）
- `@friday-ai-codes/skills` npm 正式 bump 发布时机（相位验收不阻塞）
- Galaxy / 前端执行流与社区着色可视化
- rename apply / 工作树自动改写；动态引用（反射/模板）增强命中
- Process 跨 async 边界的二段追踪；跨仓 Process（v1 本仓 Endpoint 入口）
- Semgrep「## 安全扫描」段 / LSP 基准（Phase 127）
- Runner/CI 硬门禁（HIGH/CRITICAL 阻断 commit）— 124 已明确 v2+
- `detect_impact` 式 MCP 编排 prompt（REQUIREMENTS Future）

</deferred>
