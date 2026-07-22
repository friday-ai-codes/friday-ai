---
name: friday-code
description: "当用户要 Friday 操作或追踪某个远端已索引仓库时使用：找仓库（哪个仓库负责 X、某接口的后端/前端在哪个仓库）、跨仓库追接口实现（前端接口→后端实现、后端接口→前端调用点、检索命中请求 URL/路由定义/接口调用）、分析架构/风险/影响面（X 在仓库 Y 里怎么实现的）、生成或修改编码计划、执行计划并创建 MR，或给一个具体需求一条龙跑到 MR。覆盖发现→分析→计划→执行全流程。反向边界：目标就在当前本地工作区、且不涉及另一侧仓库时用本地工具。"
---

# Friday Code

从一个需求到一个可追溯 MR 的完整流水线，按阶段分节。用户只要某一个阶段就停在那个阶段；用户给的是完整编码需求要结果，就按"一条龙模式"跑完全程。全程使用 `friday` MCP server 工具。

## 前置门槛

看不到 `friday` MCP 工具，或调用返回 401/403，引导用户运行 `npx -y @friday-ai-codes/mcp setup`（见 `friday` 技能「环境未就绪」一节）。

## 模式判定

| 用户意图 | 跑到哪 |
| --- | --- |
| "哪个仓库负责 X？" / "Friday 能操作这个仓库吗？" | 阶段一 |
| 前端拿到接口要看后端实现 / 后端接口要看前端调用点（跨仓追接口） | 阶段一定位另一侧仓库 → 阶段二查实现/调用点 |
| "分析一下仓库 Y 的架构 / X 是怎么实现的 / 改这个影响面多大" | 阶段二 |
| "这段代码对应哪个需求 / 为什么这么改" | 阶段二（`reverse_lookup_requirements`） |
| "给这个需求出个方案/计划" | 阶段三 |
| "执行这个计划 / 建个 MR" | 阶段四 |
| 给了具体需求，要的是结果（代码 + MR） | 一条龙模式 |

第一个成功响应返回的 `run_id` 全程保留；`repository_id`、`analysis_id`、`plan_id`、`version_id`、`execution_id` 跨阶段传递，不要重复路由。

## 阶段一 — 找仓库

1. `route_repositories`，用用户的需求原文做 `query`（可选 `top_k`）。保留返回的 `run_id`。
2. 第一名分数明显领先就直接选它；分数接近或都很弱时，问用户一个简洁的确认问题——除非用户要求全自动，那就选最高分并在报告里说明。
3. `get_repository` 读取所选 `repository_id` 的元数据、默认分支、索引状态。
4. 可选：`list_repository_files` 浅扫文件树，让用户确认仓库内容对得上。

护栏：

- `repository_not_indexed`：停下，告诉用户该仓库/分支需要先在 Friday 完成索引。
- `repository_not_found` 或路由结果为空：换种表述重试一次；仍为空时，让用户在 Friday 控制台确认仓库与"仓库摘要索引"状态——代码索引完成不代表路由索引就绪。

## 阶段二 — 分析

前置：需要 `repository_id`，没有就先跑阶段一。

1. `search_rag_chunks`，用需求或分析焦点做 `query`（`repository_id`，可选 `branch` / `top_k` / `max_tokens`）。这是主力证据工具——混合语义 + 关键词 + 图谱检索。
2. `grep_repository` 处理「穷举所有出现位置」类问题（字面量 / 符号引用 / 跳转路径枚举）：精确全量、确定性结果，语义检索保证不了全量时必须切换到它。支持正则、大小写开关、`paths` / `include_globs` / `exclude_globs` 过滤、最多 50 行上下文与 `max_tokens` 预算。推荐两步法：先 `output_mode="files_only"` 看命中分布，再 `output_mode="content"` + `context_lines` 抠关键上下文（可省掉大量 `get_repository_file` 往返）。跨仓问题（「哪些仓库在用 X」）传 `repository_ids` 数组或 `all_repositories=true`，结果按仓库分组。
3. `find_related_chunks` 从重要命中扩展：`chunk_id` / `file_path` / `symbol_name` 三选一。证据指向值得追踪的入口时使用。
4. `reverse_lookup_requirements` ——证据→需求反查：已知代码位置（`repository_id` + `file_path`/`line` 或 `chunk_id`，可选 `branch`），反查它关联的需求（`related_work_items`）、文档（`related_documents`）与追溯路径（`paths`）。回答「这段代码是为哪个需求/方案改的」「改这里会影响哪些已交付需求」时用。
5. `get_repository_file` 在 chunk 需要完整上下文时读取精确文件内容（支持行范围；优先 git 镜像全量读取，`source="git"` 时行号精确）。
6. `analyze_repository`，把筛选后的证据作为 `context_chunks`、用户的关注点作为 `focus` 传入。返回 `analysis_id` 及架构摘要、关键模块、入口、风险、测试策略、阅读顺序。

跨仓追接口（前后端打通）：

- 已知接口路径 / 请求 URL，要在另一侧仓库找实现或调用点时，`grep_repository` 比语义检索更准——用 URL 字面量或路由路径做精确检索，先 `output_mode="files_only"` 看命中分布，再 `content` + `context_lines` 抠上下文。
- 找后端实现：用接口路径匹配路由注册/处理函数（如 `@app.route` / `@RequestMapping` / `router.get` / handler 注册）。
- 找前端调用点：用 URL 常量或请求封装名（`fetch` / `axios` / `request` / 接口常量）枚举所有调用位置，得到完整影响面。
- 接口路径在前后端命名常有差异（前缀、版本号、path 参数占位）：命中为空时退一步，用更短的稳定片段（资源名/动词）重试。

护栏：

- 证据要诚实：引用工具返回的 chunk ID / 文件路径；不得编造证据里没有的代码结构。
- 检索为空：先放宽 query、用 `get_repository` 确认分支和索引状态，再下"代码不存在"的结论。
- 保留 `analysis_id`——阶段三要用。

## 阶段三 — 计划

前置：`repository_id` 必需；非平凡改动强烈建议带上阶段二的 `analysis_id`，计划质量差别很大。

新建：

1. `create_coding_plan`，传 `repository_id`、`requirement`，有则带 `analysis_id` 和 `context_chunks`。
2. 保存 `plan_id` 和 `version_id`，把实现步骤、涉及文件、测试、风险呈现给用户。

修订（已有计划 + 反馈）：

1. `improve_coding_plan`，传 `plan_id`、用户的 `feedback` 和新增 `context_chunks`。
2. 对比返回的 `change_summary` 和 `risk_delta`。
3. 最新 `version_id` 是执行默认版本，除非用户指定旧版本。

护栏：

- 计划只是提案：本阶段不触发执行，用户批准后才把 `plan_id` / `version_id` 交给阶段四。
- 计划有明显缺口（缺迁移、没有回滚、路径未测试）时指出来，最多做一轮精确反馈的 `improve_coding_plan`，不要循环。

## 阶段四 — 执行与 MR

前置：用户已批准的 `plan_id`（可选 `version_id`）。仓库 Git 凭证须已在 Friday 服务端配置。

1. `execute_coding_plan`，传 `plan_id`，可选 `version_id` / `branch_name` / `target_branch` / `timeout_seconds`。保存 `execution_id`。
2. 用 `get_coding_execution` 轮询 `execution_id` 直到 `completed` / `failed` / `partial`。汇报有意义的进展，不是每次轮询都汇报。
3. `completed` 且分支已推送：`summarize_branch`（传 `execution_id`）获取 diff 摘要和 MR 草稿。
4. 用户要 MR 时：`create_merge_request`，传 `execution_id`、来自草稿的标题/描述，可选 `reviewer_usernames`。

护栏：

- 没有已推送的分支（或用户明确给了源分支）绝不创建 MR。
- 执行 `failed`：报告 `error`、`runner_logs`、`last_diff`、`recovery_state`；仅当 recovery 标记可重试时用 `retry_of_execution_id` 重试。
- 执行 `partial`（代码已推送、后续步骤失败）：不要重跑编码，用已持久化的分支和 commit 重试 `summarize_branch` 或 `create_merge_request`。
- `create_merge_request` 返回 `success: false` 且 `execution_status: partial`：保留分支/commit 信息，等平台问题（凭证、权限、已存在的 MR）解决后只重试 MR 创建。

## 一条龙模式

按 阶段一 → 阶段二 → 阶段三 → 阶段四 顺序跑完，全程共用第一个 `run_id`。计划有明显缺口时做最多一轮 `improve_coding_plan`，不循环。

只在以下情况停下来问用户，其余一律继续——这个模式的意义就是不要人工干预：

- 仓库路由结果含糊（分数接近）且用户没有要求全自动；
- 仓库未索引；
- 执行失败且没有可重试的 `recovery_state`；
- MR 创建遇到不可重试的平台错误。

最终报告格式：

```text
Repository: <name> (<repository_id>)
Trace: <run_id>
Plan: <plan_id> version <version_id>
Execution: <execution_id> status <status>
Branch: <branch_name> -> <target_branch>
Commit: <commit_sha 或 none>
Push: <pushed/failed/skipped>
MR: <mr_url 或恢复动作>
Tests: <测试摘要或 runner 日志指引>
```

## HTTP 兜底

MCP 不可用时，所有工具都是 `POST {FRIDAY_BASE_URL}/api/mcp/tools/{tool_name}/` + Bearer 认证；`run_id` 通过 `X-Friday-Run-ID` 头传递。执行与 MR 工具的完整契约见 [references/http-fallback.md](references/http-fallback.md)。
