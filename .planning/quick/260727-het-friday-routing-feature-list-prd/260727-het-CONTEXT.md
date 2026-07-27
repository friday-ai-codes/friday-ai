# Quick Task 260727-het: 新增 friday-routing 技能 - Context

**Gathered:** 2026-07-27
**Status:** Ready for planning

<domain>
## Task Boundary

把「仓库路由 / 架构落点判定」从 `friday-solution` 的服务端黑盒里拆出来，做成一个可独立调用的 Agent Skill：`friday-routing`。

输入是 feature list 或 PRD（成批功能点），输出是一份**路由与落点判定矩阵**——每个功能点该落到哪个仓库、落到仓库里的哪个位置、是新增还是改造、依据是什么、有多确定。判不准的地方主动带选项问用户。

本任务**只做技能文档与接入面**，不改服务端编排、不新增 MCP 工具、不改 `RepoRouterV2`。

</domain>

<decisions>
## Implementation Decisions

### 执行方式：纯 agent 驱动（锁定）

技能自己编排既有的原子 MCP 工具做系统性调研，过程与证据对用户全透明。**不**走 `create_feature_tech_plan` / `confirm_feature_tech_plan` / `get_feature_tech_plan` 三段式服务端编排——那是 `friday-solution` 的路径。

澄清由 agent 自己发起并直接问用户，不依赖服务端组装的确认题。

可用的原子工具（全部已在 `TOOL_SCHEMA_SNAPSHOT` 中）：
`route_repositories`、`get_repository`、`search_rag_chunks`、`grep_repository`、`list_repository_files`、`get_repository_file`、`find_related_chunks`、`reverse_lookup_requirements`、`search_delivery_knowledge`、`search_learning_cases`、`lookup_project_by_branch`、`search_project_context`、`grep_project`、`read_project_doc`、`report_project_knowledge`。

### 产物边界：只出路由/落点矩阵（锁定）

矩阵每行至少含：功能点 → 目标仓库（含 monorepo 子应用）→ 目录/文件落点 → `new` / `modify` / `unclear` → 证据（真实文件路径或 chunk）→ 置信度 → 风险与跨仓依赖。

**不出**伪代码、不出模块详细设计、不出完整技术方案文档。
- 要完整方案（含伪代码）→ 转 `friday-solution`
- 要编码计划 → 转 `friday-code` 阶段三

### 技能命名：`friday-routing`（锁定）

目录 `skills/skills/friday-routing/`。

### 结论沉淀：写回 Friday（锁定）

跑完用 `report_project_knowledge`（按当前 git 分支自动定位项目，无需 `project_id`）把路由结论写回项目记忆，供后续 `friday-solution` / `friday-code` 召回复用。沿用既有 fail-soft 语义：非项目成员 / 分支未绑定时静默跳过，绝不阻断。

**绝不上报任何凭证 / 密钥 / token / 个人敏感信息。**

### 调研维度（Claude's Discretion — 用户要求「从各个维度确认」，具体维度由实现定）

技能必须逐维度过一遍，每维度都要落到证据上：

1. **仓库维度** — 目标仓库，monorepo 要下钻到子应用
2. **落点维度** — 仓库内的目录/文件/模块，改造要指到既有文件
3. **变更类型维度** — `new` / `modify`，判 `modify` 必须有真实证据文件
4. **证据维度** — 每条判定挂 chunk / 文件路径；**无证据一律降级 `unclear`，不猜**（沿用 260726-t2f 的幻觉过滤原则）
5. **跨仓依赖维度** — 接口契约两侧（前端调用点 ↔ 后端实现），用 `grep_repository` 精确枚举
6. **影响面维度** — 改造点用 `reverse_lookup_requirements` 反查已交付需求，评估回归风险
7. **历史维度** — `search_delivery_knowledge` / `search_learning_cases` 找相似需求与历史踩坑
8. **索引健康度维度** — `get_repository` 确认仓库/分支已索引；未索引要停下告知，不能拿空检索下结论
9. **置信度维度** — high / medium / low；只有 low 与关键 medium 才问用户，不为问而问

### 澄清协议（用户明确要求）

- 有不确定就主动问，**每题必须给几个具体选项**，不能开放式提问
- 每题标出推荐项与推荐理由
- **批量问**：一轮把所有待澄清点摆出来，不要逐条来回
- 选项必须是具体选择（哪个仓库 / 哪个落点 / 新增还是改造），不是抽象类别
- 用户答复前不得替用户拍板

### 取数源

与 `friday-solution` 对齐的三源，外加本地文件：
`branch_name`（`lookup_project_by_branch` 反查项目）/ Friday `project_id` / 用户直接贴 feature list 或 PRD 原文 / 本地需求文档（读文件内容）。

</decisions>

<specifics>
## Specific Ideas

### 必须同步的接入面（漏一个就装不到 / CI 红）

| 文件 | 改什么 |
|---|---|
| `skills/skills/friday-routing/SKILL.md` | 新建，主文档 |
| `skills/skills/friday-routing/references/http-fallback.md` | 新建，MCP 不可用时的 HTTP 契约（对齐其余 5 个技能的写法） |
| `skills/skills/friday/SKILL.md` | 技能路由表 + 决策门增加 `friday-routing` 分流 |
| `skills/skills/friday-solution/SKILL.md` | 「与其它技能的边界」表加一行，讲清 routing 是它的上游 |
| `skills/skills/friday-code/SKILL.md` | 阶段一提一句：成批功能点的路由走 `friday-routing` |
| `skills/lib/installer.mjs` | 引导文案里的技能清单 6 → 7，加一条分流规则 |
| `skills/.claude-plugin/plugin.json` | description 里的技能清单与数量 |
| `skills/README.md` | 技能表加一行 |
| `docs/integrations/skills.md` | 用户文档补新技能 |

### 硬约束（CI 守卫）

1. **`server/tests/mcp_tools/test_skills_snapshot_guard.py`** — SKILL.md 里反引号包起来的、以 `search|create|get|list|execute|improve|analyze|summarize|route|find|grep|read|report|lookup|reverse|update|confirm` 开头的 snake_case token，必须 ⊆ `TOOL_SCHEMA_SNAPSHOT` 的键集 ∪ 各条目 request/response 字段名集。**写文档时不要用反引号包不存在的工具名。**
2. **`task/tests/test_skills_injection.py`** — `task/assets/skills/` 与子模块同源哈希守卫，目前只覆盖 `friday-code` / `friday-memory`。`friday-routing` **不进** task 容器（它是 IDE / CLI 侧的调研技能，容器里跑的是编码 agent），所以不要动 `task/assets/skills/`，也不要改 `task/scripts/sync_skills.py`。

### 子模块提交纪律

`skills/` 是 git 子模块（独立仓库 `friday-ai-codes/skills`），当前 **detached HEAD at `488d9c4`**，且 `488d9c4 == origin/main`。

提交顺序：
1. 在 `skills/` 里先 `git switch main`（或 `git checkout -B main origin/main`）脱离 detached HEAD，再提交子模块内的改动
2. 回主仓提交子模块指针 + 主仓侧文件（`docs/integrations/skills.md`）
3. 子模块**不推远端、不发版**——沿用 260726-uid 的做法，作为遗留项写进 SUMMARY，由用户决定何时推送与发 npm 包

本次 `workflow.use_worktrees=false`，executor 直接在主工作树跑，不触发子模块 worktree 守卫。

### 文风对齐

zh-CN，与既有 5 个技能同构：frontmatter 只有 `name` + `description`（description 写足触发场景与反向边界）；正文用「前置门槛 / 阶段分节 / 护栏 / 与其它技能的边界 / HTTP 兜底」的骨架。参考 `skills/skills/friday-code/SKILL.md` 与 `friday-solution/SKILL.md`。

</specifics>

<canonical_refs>
## Canonical References

- `.planning/quick/260726-uid-feature-list-mcp-skill/260726-uid-SUMMARY.md` — `friday-solution` 的接入面清单与遗留项，本次同步面照此对齐
- `.planning/quick/260726-t2f-feature-list/260726-t2f-SUMMARY.md` — 「判 modify 必须拿真实证据文件，否则降级 unclear」的原始设计决策
- `server/codegraph/services/repo_router_v2.py` — `route_repositories` 背后的两阶段路由：能力树 hybrid 粗筛 → LLM 树推理，返回 `score` / `confidence` / `matched_node_paths` / `sub_project`，仅 high 置信时 `auto_selected=true`
- `server/mcp_tools/serializers.py` — `TOOL_SCHEMA_SNAPSHOT`，工具名与字段名的唯一真源
- `.planning/feature-list-demo.md` — 现成的 feature list 样例，可用于文档示例

</canonical_refs>
