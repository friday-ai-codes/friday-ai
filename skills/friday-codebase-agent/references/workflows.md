# Friday Workflow 详解

六个 workflow 的逐步操作、参数选择策略与示例对话。工具参数细节见 [tools.md](tools.md)。

## discover — 仓库发现

**何时用**：用户不确定需求落在哪个仓库，或你需要 repository_id 作为后续输入。

1. 用需求原文（保留业务名词，不要过度概括）调 `route_repositories`，`top_k` 默认 3。
2. 对得分接近的候选，调 `get_repository` 看默认分支与索引健康度。
3. 向用户呈现候选与理由；得分悬殊时可直接采用第一名并说明。

> 用户："订单超时自动取消这个需求应该改哪个服务？"
> 调用：`route_repositories {"query": "订单超时自动取消，定时任务扫描未支付订单并关闭"}`
> 回复：列出 top 3 仓库 + 各自得分与索引状态，建议采用哪个。

索引健康度差的仓库要提醒用户先重建索引再继续。

## analyze — 代码分析

**何时用**：调用链、影响面、"现在是怎么实现的"。

1. `search_rag_chunks` 召回证据。query 用"业务词 + 技术词"组合（如 "支付回调 webhook handler"）。
2. 对关键符号 / 文件调 `find_related_chunks` 看上下游：
   - 改函数行为 → `direction: "upstream"`（谁调用我，影响面）
   - 查依赖 → `direction: "downstream"`
   - 不确定 → `both`，`hops: 1` 起步，证据不足再升 2
3. 需要看完整实现时用 `get_repository_file`（带行范围，避免拉全文件）。
4. 要产出结构化报告（架构 / 风险 / 测试建议）时，把第 1 步的 `results` 作为 `context_chunks` 喂给 `analyze_repository`，并设置 `focus`。

回答时引用具体文件路径与符号名，不要凭空概括。

## plan — 生成编码计划

**何时用**：用户要方案 / 改造计划，但还没要执行。

1. 没有 repository_id → 先跑 discover。
2. `search_rag_chunks` 收集证据；复杂需求加 `analyze_repository` 拿 `analysis_id`。
3. `create_coding_plan`：`requirement` 放需求全文（含验收标准），传 `analysis_id` 或 `context_chunks` 复用证据。
4. 把返回的 `plan` 以可读形式呈现：步骤、涉及文件、风险、测试建议。**记下 plan_id / version_id**，用户后续说"执行"或"改一下"都要用。

> 用户："给购物车加优惠券校验，出个方案"
> 调用链：`route_repositories` → `search_rag_chunks {"query": "购物车 结算 优惠券 校验"}` → `create_coding_plan {"requirement": "<需求全文>", "context_chunks": [...]}`
> 回复：呈现计划步骤与风险，问用户"确认执行还是需要调整？"

## improve — 修订计划

**何时用**：用户对已有计划给出反馈。

1. `improve_coding_plan`，`feedback` 放用户反馈原文（不要转述损耗信息）；反馈涉及新代码区域时先补一轮 `search_rag_chunks` 并带上 `context_chunks`。
2. 呈现新版本时突出 `change_summary` 与 `risk_delta`，告知新 version_id。

可多轮迭代，每轮产生新版本，旧版本保留可回退。

## execute — 执行与 MR

**何时用**：用户明确同意执行某个计划。

1. **闸门**：未确认过计划内容则先呈现并取得明确同意。
2. `execute_coding_plan {"plan_id": ...}`，按需指定 `branch_name` / `target_branch`。告知用户已开始、预计耗时。
3. 轮询 `get_coding_execution`（30-60 秒间隔），按 `status` 分支：
   - `completed` → 下一步
   - `failed` → 呈现 `runner_logs` 摘要与 `recovery_state`，与用户商定修正（通常 improve 后带 `retry_of_execution_id` 重试）
   - `partial` → 代码已推送，**不重跑**，直接进第 4 步
4. `summarize_branch {"execution_id": ...}` 生成摘要与 MR 草稿。
5. 用户确认草稿后 `create_merge_request`（title/description 省略即用草稿；按需加 `reviewer_usernames`）。
6. 回复 MR 链接、分支名、改动摘要与测试结果。

## full_auto — 飞书需求一路到 MR

**何时用**：用户给出飞书工作项，要求端到端推进。本质是带确认点的编排，**不是无人值守**。

1. `get_feishu_work_item_context`：传 `work_item_id` + `project_id` 或 `project_key`（用户给 URL 时从中提取），建议 `include_comments: true`。
2. `search_learning_cases` 查相似历史经验（query 用工作项标题 + 关键词）。
3. `create_feishu_technical_plan`：传 `context_id`，相似案例放 `similar_cases`；知道目标仓库就传 `repository_ids`，否则给 `repo_hints`。方案会写回飞书文档 / 评论。
4. **确认点**：把方案（`markdown`）与 `repository_tasks` 呈现给用户。
5. `create_work_item_repo_tasks` 拆任务矩阵（create_feishu_technical_plan 已返回 tasks 时可跳过）。
6. **确认点**：列出将执行的任务清单，取得同意。
7. `execute_work_item_repo_tasks {"technical_plan_id": ...}`，按需传 `reviewer_usernames`。完成后呈现 `summary`（各仓库分支 / MR / 状态）。
8. 收尾（可选但推荐）：`create_learning_case` 沉淀本次经验（成功失败都值得记）。

部分任务失败时：失败任务用 `task_ids` 单独重试，成功任务不要重跑。

## 通用策略

- **证据复用**：`search_rag_chunks` 的 `results` 可直接作为后续工具的 `context_chunks`，避免重复检索。
- **run_id**：MCP 模式自动透传；降级 HTTP 时必须手动带 `X-Friday-Run-ID`（见 SKILL.md）。
- **大需求拆小**：`requirement` 上限 8000 字符；超长需求先摘要关键约束，完整文档链接留在飞书侧。
