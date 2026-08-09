# Phase 124: 编码链闭环 - Context

**Gathered:** 2026-08-10
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous，用户授权全量采纳推荐答案；跳过 Sub-step 4 交互）

<domain>
## Phase Boundary

本相位把 Phase 123 已交付的 `run_detect_changes` **真正挂进「需求→PR」编码链**（DIFF-03 / DIFF-04）：

1. **容器提交前自查（DIFF-03）**：编码任务容器经既有 MCP PAT + `friday-knowledge` 白名单可调 `detect_changes`；system prompt 指引 agent 在完成改动后、结束 turn 前自查；受影响清单进入提交决策——**v1 仅提示，不阻断** runner commit/push。
2. **MR 描述自动附影响面报告（DIFF-04）**：workflow（`AICodingNode`）与 MCP（`create_merge_request`）两条建 MR 链路，在创建 MR 前自动附 **Changes / Affected / Risk / Recommendations** 四段结构；报告生成失败 **fail-soft**——建 MR 主流程零阻断。

**明确不在本相位：**
- detect_changes 工具本体 / 交叠内核 / `diff_mirror`（Phase 123 已完成；本相位只消费 `run_detect_changes`）
- `affected_processes` 叙事回填（Phase 126 / EXEC-03；报告 Recommendations 不依赖 Process）
- runner 硬门禁（HIGH/CRITICAL 阻断 commit）——v1 不做；误报会卡死编码链
- `mcp/` git submodule 客户端补条目（沿用 122 D-27）
- ⛔ 不改 `server/codegraph/services/repo_router_v2.py`（冻结至 Phase 125 MOD-04）
- Semgrep / 安全扫描段（Pattern 6，后续相位）
- 前端 UI；零不必要 migration；不新增持久化模型

</domain>

<decisions>
## Implementation Decisions

### Area 1: 容器提交前自查（DIFF-03）— prompt 挂点 / 非阻断语义 / 仓与分支

- **D-01 — prompt 注入点 = `task/core/executor.py::_get_system_prompt`，照抄 `follow_openspec` 条件追加范式**：新增独立静态 helper（建议 `_detect_changes_guidance()`），在编码模式且 knowledge MCP 已挂载时追加「完成文件修改后、结束 turn 前，调用 `detect_changes` 自查受影响符号与风险；根据清单决定是否继续修补；结果仅供决策参考，不要因为工具失败而停止交付」。⛔ 不改 `runner.py` commit/push 路径做硬门禁（research Pattern 3；成功标准 1 明文 v1 提示不阻断）。静态可信文本，无外部输入拼接，无 prompt 注入面。
- **D-02 — 白名单：把 `detect_changes` 加进 `task/core/knowledge_tools.py` 的 `KNOWLEDGE_TOOL_SCHEMAS` + `knowledge_allowed_tools()`**：`input_schema` 对照 server `DetectChangesRequestSerializer`（已有 `/api/mcp/tools/detect_changes/` PAT 面）。工具 description 写清「编码完成后、提交前自查影响面；`compare` 用当前任务分支」。既有知识工具配额/配额耗尽文案沿用，不另造配额体系。
- **D-03 — 自查调用参数约定（写入 prompt，不硬编码 runner）**：`repository_id` = 本任务仓；`compare` = 当前任务功能分支（工作区已在该分支）；`base_ref` 可选透出 MR 目标分支语义，但行号交叠基线仍由 Phase 123 D-01 强制锚定 `last_indexed_commit_sha`——agent 不得也不必传「工作树 tip」当 base。未索引 / mirror 失败时工具返回明确 `ok=False`；prompt 指示「失败则记录原因并继续交付，不重试刷屏」。
- **D-04 — 非阻断语义（硬约束）**：detect_changes 结果（含 HIGH/CRITICAL、`staleness`、工具错误、配额用尽）**一律不**阻止 agent 结束 turn，也**不**改 runner commit 决策。v1 成功标准是「清单进入提交决策（指引）」而非门禁。未来硬门禁另开相位。

### Area 2: MR 影响面报告 — 共享 formatter / 双链路挂点 / 四段 schema

- **D-05 — 共享编排 + 共享 markdown formatter（单一事实源）**：新增纯函数/小模块（建议落点 `server/services/code_graph/impact_report.py`，或与 `code_graph_tools.py` 同级 helper）提供：
  1. `build_impact_report_section(...)` → 调已有 `run_detect_changes`（同源信封）→ 渲染 markdown 段；
  2. 输入最少：`repository` / `compare`（= source_branch）/ 可选 `base_ref`（= target_branch，仅声明）/ 调用方 `user`（ACL）。
  ⛔ 不得在 workflow 壳与 MCP 壳各写一套渲染；⛔ 不得在壳里重写 impact BFS。报告数据以 **建 MR 时服务端实时调用** `run_detect_changes` 为准（不依赖容器内 agent 是否真的自查过——自查是 DIFF-03 行为指引，报告是 DIFF-04 服务端保证）。
- **D-06 — 双链路挂点（既有缝，零新机制）**：
  - **Workflow**：`server/workflows/nodes/ai/coding.py` 的 `_create_mr_for_repo`（拼 `description`/`body` 处，约 2194–2219）在 `create_merge_request` **之前**追加影响面段；多仓 wave 路径与现有 `pr_cross_reference`「## 关联 PR」fail-soft 同姿态。`workflows/services/mr_service.py::build_mr_description` / `create_mr_for_task` 若仍被调用，同一 helper 挂接，避免第三条方言。
  - **MCP**：`server/mcp_tools/merge_request_service.py`——在 `_draft_from_summary` 与/或 `create_merge_request` 缺省 description 拼接点（`:65-71` / `:143-147`）追加同一段。调用方已显式传入完整 description 时：若尚未含影响面标记头，则 **append**；已含则不重复（幂等）。
- **D-07 — 四段结构（DIFF-04 明文）**：顶层标题统一 `## 影响面`（与 research / 中文 MR 既有段落风格一致）；其下固定四个小节：
  1. `### Changes` — 变更文件/符号摘要（`changeType`、行数、`file:line`；超阈值沿用 123 文件级摘要）
  2. `### Affected` — 批量 impact 受影响面（深度分组 / 关键符号；截断计数必给）
  3. `### Risk` — 确定性风险等级（LOW/MEDIUM/HIGH/CRITICAL）+ 简短可解释依据；透出 `staleness`（索引落后 N commits / as_of）
  4. `### Recommendations` — 行动建议（如「复核 d1 callers」「建议重索引后再信行号」）；`affected_processes` 仍为空占位，本相位不编造 Process 叙事（Phase 126）
  英文章节名保留（需求字面）；正文中文可混排。字段映射全部来自 123 信封，不发明第三套方言。
- **D-08 — 报告体积纪律**：单段 markdown 设软上限（初值建议 ~8–12KB 或符号/文件 top-N，具体 Claude's Discretion），超限截断并注明 `truncated`；⛔ 不把源码正文塞进 MR 描述（沿用 122 D-17 `include_content` 默认关）。

### Area 3: Fail-soft — 超时 / 错误分类 / 失败时写入内容

- **D-09 — MR 路径 fail-soft 契约（成功标准 3）**：影响面报告路径上任何失败——`run_detect_changes` 抛异常、`ok=False`、超时、ACL、未索引、mirror fetch 失败、渲染异常——**一律吞掉**，不得向上抛到 `create_merge_request` / `_create_mr_for_repo`。MR 仍按原 description 创建。观测 best-effort（见 D-12）。
- **D-10 — 超时预算**：建 MR 路径对 `run_detect_changes` 设显式超时（初值建议 **30s**，可 settings/env 化；Claude's Discretion 微调）。超时视同失败走 D-09。容器内 agent 自查走既有 MCP/知识工具超时与配额，不另加 runner 等待。
- **D-11 — 失败时写入内容**：优先写**短 stub** 而非静默省略，让 reviewer 知道系统尝试过：
  ```markdown
  ## 影响面

  _影响面报告未能生成（`{error_code}`）。MR 已照常创建，请人工复核变更影响。_
  ```
  `error_code` 取信封/异常映射的稳定码（如 `not_indexed` / `timeout` / `unavailable`）；⛔ 禁止把堆栈、token、绝对路径、凭证写入 MR 描述或日志明文。若连 stub 渲染也失败 → 完全省略影响面段（最后兜底，对齐 `pr_cross_reference` 空串语义）。
- **D-12 — 部分成功照常出报告**：`ok=True` 但带 `staleness` / `degradation` / 单符号 `impact_error` 时**仍渲染**完整四段，并在 Risk/Recommendations 醒目声明降级与 stale（继承 123 D-04/D-12）。只有整体失败才走 D-11 stub。

### Area 4: 观测 / 开关 / 双路径对等 / 冻结面

- **D-13 — 无新业务 kill-switch（v1 默认开）**：编码容器挂 knowledge 工具时白名单+prompt 默认生效；建 MR 路径默认尝试附报告。仅允许运维向超时/体积阈值 settings（若需要），⛔ 不为本相位新增「关闭影响面」产品开关（避免双路径一边开一边关导致漂移）。若未来需要，另开相位。
- **D-14 — 双路径对等**：workflow 与 MCP **必须**调用同一 `build_impact_report_section`（或等价单一入口）；验收含：两边对同一 `(repo, compare)` fixture 产出的 `## 影响面` 正文字节级或规范化后一致；失败 stub 文案一致。照抄 122/123 双面哨兵精神（此处是 MR 双链路，非 MCP+chat）。
- **D-15 — 观测契约**：`component="code_graph"`（报告生成/detect_changes 消费）或挂接点所在组件（`workflows` / `mcp_tools`）按入口记 `category=caller`；事件名静态字面量（如 `impact_report_started` / `impact_report_completed` / `impact_report_failed`），带 `duration_ms`、`repository_id`、`error_code`（失败时）、`section_chars`；高频细节 `category=sampling`。后台/任务路径带 `initiated_by_user_id`（无则 `system`）。观测代码 best-effort，绝不反噬建 MR。凭证/上游异常文本走既有 redact。
- **D-16 — 冻结与欠债延续**：⛔ 不改 `repo_router_v2.py`；⛔ 不改 `mcp/` submodule（122 D-27 / 123 延续；SUMMARY 若触及 snapshot 漂移只更新计数）。task 侧 schema 硬编码在 `knowledge_tools.py` 是合法接线（与 server MCP 面并行，非 npm 包）。并发 WIP：提交本 CONTEXT 时**只 stage 本文件**。

### Claude's Discretion

- `_detect_changes_guidance` 中文措辞细节、是否仅在 `task_mode` 实现路径追加（explore/readonly 不挂）。
- 报告 top-N / 字符软上限具体数字、超时初值微调、settings 键名。
- `impact_report` 模块文件名与是否再抽 `append_impact_report(description) -> str` 小工具。
- 测试组织：task 白名单单测、prompt 段零回归、MR 双链路 fail-soft / 对等哨兵、formatter 快照。
- CreatePRNode（手动 git 节点）是否顺手挂同一 helper——推荐挂以消方言，但不挂不算本相位缺口（wave/`AICodingNode` + MCP 是成功标准覆盖面）。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets

- **Phase 123 编排**：`server/services/code_graph_tools.py::run_detect_changes`；内核 `services/code_graph/detect_changes.py`；MCP `DetectChangesView`（`/api/mcp/tools/detect_changes/`，PAT fail-closed）；对话壳已双面暴露。
- **容器知识工具面**：`task/core/knowledge_tools.py` — `KNOWLEDGE_TOOL_SCHEMAS` + `knowledge_allowed_tools()` → `mcp__friday-knowledge__{name}`；经 HTTP 打 server MCP（PAT）。当前白名单含 RAG/grep/file/delivery/learning/project/blueprint 等，**尚无** `detect_changes`。
- **Prompt 注入先例**：`task/core/executor.py::_get_system_prompt` + `_openspec_guidance`（Phase 51 / follow_openspec）；git 写操作已被 wrapper 拦截，真正 commit 在 `task/core/runner.py`。
- **Workflow 建 MR**：`server/workflows/nodes/ai/coding.py::_create_mr_for_repo` / `_finalize_and_notify`；描述拼装 + `pr_cross_reference.py` fail-soft 追加段先例。
- **MCP 建 MR**：`server/mcp_tools/merge_request_service.py` — `summarize_branch` / `_draft_from_summary` / `create_merge_request`；`CreateMergeRequestView`。
- **通用 MR 描述**：`server/workflows/services/mr_service.py::build_mr_description`（飞书/方案/改文件三段）。

### Established Patterns

- **双面薄壳 / 共享编排**：122 D-21 — 逻辑不许在壳里分叉；本相位对「MR 双链路」套用同一纪律。
- **Fail-soft 追加段**：`pr_cross_reference.add_cross_references` / `render_traceability_section`（异常→空串，不阻断 MR）。
- **观测**：`component="code_graph"`；caller vs sampling；事件名静态字面量；best-effort 不反噬。
- **Research 落点**（`.planning/research/ARCHITECTURE.md` Pattern 3）：白名单 + prompt + 两处 MR description 挂点——与本 CONTEXT 决策一致。

### Integration Points

- MODIFY：`task/core/knowledge_tools.py`（白名单+schema）、`task/core/executor.py`（prompt 段）
- MODIFY：`server/workflows/nodes/ai/coding.py`（及必要时 `mr_service.py`）
- MODIFY：`server/mcp_tools/merge_request_service.py`
- NEW：共享 `impact_report` formatter/helper（消费 `run_detect_changes`）
- ⛔ 不改：`repo_router_v2.py`；`mcp/` submodule；runner 硬门禁

</code_context>

<specifics>
## Specific Ideas

- Phase 123 CONTEXT 已明文把「容器白名单 / system prompt / MR ## 影响面」留给本相位；VERIFICATION 将「生产 MR tip 端到端」记为 Phase 124 集成项——本相位验收应覆盖双链路自动化，不要求人工点生产仓。
- 成功标准强调 v1 **提示不阻断**：与 GitNexus pre-commit 硬门禁示例刻意分流——Friday 编码链误报成本更高。
- 报告以建 MR 时服务端重算为准，避免「agent 忘了自查 → MR 无影响面」的空洞。
- 并发会话有其他 WIP：提交 CONTEXT 时**只 stage 本文件**（经 gsd-tools 显式路径）。

</specifics>

<deferred>
## Deferred Ideas

- **Runner / CI 硬门禁**（HIGH/CRITICAL 阻断 commit 或 MR）— v2+；本相位明确不做。
- **EXEC-03 / Phase 126** — `affected_processes` 回填进 Recommendations 增值段。
- **`detect_impact` 式 MCP 编排 prompt** — REQUIREMENTS Future；等工具面稳定。
- **`mcp` npm 包补条目** — 沿用 122 D-27，本相位不改 submodule。
- **CreatePRNode 手动节点统一挂 impact report** — 推荐但非成功标准必达；可 backlog。
- **Semgrep「## 安全扫描」段** — research Pattern 6，另相。
- **影响面报告产品级 kill-switch / 灰度** — v1 默认开；若运维需要再开相位。

</deferred>
