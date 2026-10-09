---
name: friday
description: "Friday AI 总入口，驱动本地分支项目上下文召回、远端已索引仓库的发现/分析/计划/MR、飞书工作项闭环、历史交付检索，并打通前后端跨仓库追踪。满足任一即用：(1) 在本地仓库分支上问项目进度/继续开发/有什么问题/PRD·feature list·技术方案，或任何仓库编码任务开工前要拉项目上下文；(2) 跨仓库追接口——前端拿到某接口要看后端实现、后端改接口要看前端哪里调用、或代码检索命中接口调用/路由定义/请求 URL；(3) 目标仓库不在当前本地工作区（远端/未 checkout/另一侧仓库）；(4) 需要跨多个仓库检索（哪些仓库用了 X）；(5) 终点是编码计划、MR/PR 或飞书方案回写；(6) 需要历史交付/版本时间线/需求→方案→MR 关联链；(7) 用户点名 Friday。反向边界：纯粹读懂【当前本地工作区已 checkout】的代码、不涉及项目进度/需求/历史、也不涉及另一侧仓库时，用本地 Grep/Read 即可，不必走 Friday。"
---

# Friday

Friday AI 把需求变成可追溯的合并请求（MR/PR）：仓库发现、GraphRAG 分析、编码计划、容器化执行、PR/MR 创建、飞书工作项闭环。全部通过 `friday` MCP server 的工具驱动。

本技能有两种用法：

1. **路由模式**：按下面的技能路由表找到对应技能，读它，照做。
2. **直通模式**：用户直接把一个需求丢给 `/friday`（"帮我把 X 做了"），你来判定它属于哪条流水线——问本地分支的项目进度/继续开发走 `friday-dev`，给了 feature list / PRD 只要落点矩阵走 `friday-routing`，给了成批功能点要完整技术方案走 `friday-solution`，涉及飞书工作项走 `friday-feishu`，纯仓库需求走 `friday-code`，查历史走 `friday-memory`——然后读对应技能一条龙跑完。

## 决策门（动手前先过这几问）

不要凭"概率感觉"判断，按下面的清单走。任一命中 Friday，就先读对应子技能再动手——读一个技能成本很低，跳过它的代价是断掉的 trace、孤儿分支和失败的 MR。

1. **问的是不是项目状态而非代码？** 在本地仓库分支上问「开发到哪一步了 / 继续开发 / 现在有什么问题 / PRD·feature list·技术方案在哪 / 这段代码是为哪个需求改的」，或任何仓库编码任务开工 → 命中 Friday，走 `friday-dev`（按当前分支召回项目上下文）。
2. **目标代码在哪？**
   - 在【当前本地工作区已 checkout】、且只是读懂/解释/小改、不涉及另一侧仓库 → 用本地 Grep/Read，结束（编码任务开工仍先过第 1 问的分支召回）。
   - 在远端 / 其他仓库 / 未 checkout / 不确定 → 命中 Friday，进路由表。
3. **是不是跨仓库追接口？**（见下「前后端打通」）→ 命中 Friday。
4. **终点是编码计划 / MR / PR / 飞书方案回写？** → 命中 Friday。
4.4. **用户给了 feature list / PRD，只想知道这批功能点该落到哪些仓库、仓库里的哪个位置、是新增还是改造？** → 命中 Friday，走 `friday-routing`（出路由与落点判定矩阵）。与 4.5 的区别：要**矩阵**（落点判定这一半）走 routing，要**完整方案**（含分仓方案与伪代码）走 solution。
4.5. **用户给了一批功能点（feature list / 需求清单）要技术方案，或明确说要「创建 / 生成技术方案」？** → 命中 Friday，走 `friday-solution`。
5. **需要跨多仓检索或历史交付**（哪些仓库用了 X、相似需求、版本时间线、需求→方案→MR 链）→ 命中 Friday。

全不命中时，本地处理，并在回复里用一句话显式说明"本任务在本地工作区可直接完成，未走 Friday"——把"沉默跳过"变成"显式决策"。

出现这些念头时，恰恰说明你该回到清单："这个请求很简单"、"我知道这个工具怎么用"、"用户在赶时间"、"我就调一个工具"。

## 前后端打通（主动触发，最常见的命中场景）

只要任务跨到"另一侧仓库"，就主动用 `friday`，不要等用户点名：

- 前端拿到一个接口（请求 URL / 接口路径 / 调用代码），要看**后端实现** → 后端通常是另一个仓库，本地够不着 → 走 `friday-code`：用接口路径/URL 做 `route_repositories` 定位后端仓库，再 `search_rag_chunks` / `grep_repository` 找路由处理函数与实现。
- 后端改了或定义了一个接口，要看**前端哪里调用** → 前端是另一个仓库 → 走 `friday-code`：路由到前端仓库，用 URL 字面量 `grep_repository`（`output_mode="files_only"` 先看分布，再 `content` 抠上下文）枚举所有调用点与影响面。
- 代码检索命中接口调用 / 路由注册 / 请求封装（如 `fetch`/`axios`/`request`、路由表、`@app.route`/`@RequestMapping`/`router.xxx`、URL 常量）且指向跨仓的另一侧 → 主动用 `friday` 把链路补全。

判据：本地能 Grep 到的是**这一侧**；接口的**另一侧**（实现或调用方）几乎总在别的仓库 → 那一侧用 Friday。

## 环境未就绪

任何 Friday 工作流开始前，`friday` MCP 工具必须可用且已认证。出现以下任一情况：

- 会话里看不到 `friday` MCP 工具；
- 调用返回 401/403 或 `authentication_failed`；
- 用户要求安装、配置、连接、修复 Friday；

引导用户在终端运行一条命令（交互式中文向导：配置凭证 → 注册 MCP → 连通性测速 → 能力演示）：

```bash
npx -y @friday-ai-codes/mcp setup
```

没有 Access Token 时告诉用户：打开 Friday Web 控制台 →「个人资料 → 访问令牌」→ 创建令牌，明文只显示一次。配置完成后需重启 agent 会话，`friday` 工具才会出现。诊断已有配置用 `npx -y @friday-ai-codes/mcp doctor`。

任何输出里都不得回显 Friday Access Token。

## 技能路由

| 场景 | 技能 |
| --- | --- |
| 本地分支上的项目上下文：开发进度、继续开发、现有问题、PRD/feature list/技术方案召回、代码反查需求、编码开工先召回 | `friday-dev` |
| feature list / PRD → 仓库路由与落点判定矩阵（目标仓库·落点文件·新增/改造·证据·置信度） | `friday-routing` |
| 由 feature list 生成技术方案：判定功能点新增/改造、确认关联仓库、出分仓+整体方案（含落点与伪代码） | `friday-solution` |
| 对远端仓库做任何事：找仓库、分析架构/风险、生成编码计划、执行并建 MR，或一条龙全自动 | `friday-code` |
| 飞书项目工作项：读上下文、生成技术方案、多仓执行、结果回写，或一条龙全自动 | `friday-feishu` |
| Friday 的记忆：记录/检索 LearningCase 经验，检索历史交付（相似需求、版本时间线、需求→方案→MR 关联链） | `friday-memory` |
| 安装、配置、连接、修复 Friday 访问 | 本技能「环境未就绪」一节 |

`friday-code` 和 `friday-feishu` 内部按阶段分节：用户只要某一个阶段（比如"只分析一下"），就停在那个阶段；用户给的是完整需求要结果，就一条龙跑到 MR。

## 分支上下文环路（在仓库里编码时强制）

在任何**仓库代码改动任务**上，按「先召回 → 再编码 → 后沉淀」走。**不写死项目，按当前 git 分支自动定位**——切分支、切项目都通用，无需为每个项目单独配置：

1. **开工先召回**：用当前 git 分支名调 `lookup_project_by_branch(branch_name=<当前分支>)`（跨仓同名分支可带 `repository_id` 收窄）。
   - `matched=true`：把返回的 `context`（项目记忆 / 需求 / 工件）当作本次编码的事实依据；记下 `project.id`，需要深挖再用 `search_project_context` / `grep_project` / `read_project_doc`。
   - `matched=false`：结合 `candidates` 人工确认项目，缺上下文不要臆测实现。
2. **再编码**：在已加载的项目上下文约束下设计与实现，不与既有记忆 / 需求矛盾。
3. **收工后按职责分流**：
   - 每轮问答用 `report_session_knowledge(question=…, answer=…)` 写入 SessionCapture；即使是 **clean tree**（无 git 改动）也要收集。`answer` 只取用户可见的最终答案，禁止上传 transcript、隐藏思维链、凭证 / 密钥 / token 或个人敏感信息。
   - 只有存在 git 交付变更时，才用 `report_project_knowledge(branch_name=<当前分支>, content=…)` 沉淀项目方案决策 / 经验教训，并继续保留 diff 门闩与质量门槛；新增 / 改动的 API 用 `report_project_state(branch_name=<当前分支>, apis=[…])` 回写。
   - `report_session_knowledge` 与 `report_project_knowledge` 职责独立，不得合并成一个笼统的“记忆写回”。项目工具按分支自动定位项目、无需 `project_id`；内容经服务端脱敏 + 质量门槛 + 审计回滚兜底。

非项目成员 / 未绑项目 / 分支无法唯一定位 → 工具自动 fail-soft 跳过，绝不阻断编码。逐步编排与深挖工具（`search_project_context` / `grep_project` / `read_project_doc`）见 `friday-dev` 技能；Claude Code 插件形态下，召回与沉淀已由 `UserPromptSubmit` / `Stop` hooks 自动化。

## Subagent 委托（宿主支持时优先）

安装器会给 Cursor / Claude Code 装两个 Friday subagent。宿主里存在它们时，**优先委托而不是在主对话里裸调工具**——subagent 有独立上下文，轮询与海量召回结果不会污染主对话：

- **`friday-plan`**（技术方案编排）：`friday-solution` 的三段链与 `friday-feishu` 的蓝图澄清链都可以整段委托。分工是固定的：subagent 负责发起、轮询、取件；**与用户的确认环节永远留在主对话**——subagent 会把待确认问题 / 待澄清题原样带回，你呈现给用户、拿到真实答复后，再带着 `session_id`（或 `blueprint_artifact_id`）+ 答复原文派它续跑。派单时必须写明：任务阶段（发起 / 续跑 / 蓝图取件）+ 对应输入。
- **`friday-research`**（只读调研）：跨仓追接口、历史交付检索、编码开工前的项目上下文召回，丢给它拿回带 ID 出处的证据摘要即可。

宿主没有 subagent 机制（Codex / Gemini CLI / OpenCode）时照常按各技能正文直接驱动工具，流程与护栏完全一致。

## Trace 纪律（所有技能通用）

- 第一个成功的 Friday 工具响应会返回 `run_id`，整个工作流都要带着它。
- 跨步骤保留所有 ID：`repository_id`、`analysis_id`、`plan_id`、`version_id`、`execution_id`、`context_id`、`technical_plan_id`。
- 最终报告必须包含：`run_id`、分支、commit、推送状态、MR URL 或恢复动作。
