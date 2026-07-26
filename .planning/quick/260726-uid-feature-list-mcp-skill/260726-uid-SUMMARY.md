---
quick_id: 260726-uid
slug: feature-list-mcp-skill
description: feature list 技术方案生成能力接入面（MCP + Skill + 对话）
date: 2026-07-26
status: complete
commits:
  - a2d88bf6 fix(process_runtime)：确认题组装器须先于 policy 执行
  - a6fae1a8 feat(initiatives)：feature list 取数、方案编排门面与完整方案渲染
  - a89bf052 feat(mcp_tools)：feature list 技术方案三工具（两段式，五处契约同步）
  - b7899893 feat(agents)：对话入口 start_feature_solution 与系统提示引导
  - 4c740057 docs：补 MCP 工具与 Skill 说明
  - 74a93f68 fix(agents)：对话入口须把 conversation_id 传进编排会话
submodules:
  - skills 0fb4d87 feat(friday-solution)：新增 feature list 技术方案技能
  - mcp ca7f1ea feat(mcp)：补 feature list 技术方案三工具（33 工具对齐）
---

# Quick Task 260726-uid 总结

把上一个任务（260726-t2f）建好的后端编排接到三个使用场景，使能力端到端可用：Cursor / Claude Code 走 MCP + Skill，Friday 对话走 agent tool。

## 用户流程

```
给 feature list（项目 / 分支 / 贴原文）
  ↓  判定每个功能点：新增 or 改造已有（带证据文件）
  ↓  给出关联仓库建议
  ↓  【强制】用户确认关联仓库 + 复核分类
  ↓  逐仓调研
  ↓  分仓方案 + 整体方案（落点文件 + 伪代码）
```

## 修掉的两个静默失效缺陷

这两个都不报错、测试不覆盖就发现不了，是本次最有价值的部分。

**1. 确认题组装器排在 policy 之后 → 强制确认永不生效**（`a2d88bf6`）

上一个任务把组装器放在 policy 判定之后。而默认 policy 见到全 high 置信路由会判「无需澄清」直接放行——组装器根本轮不到执行。表现是：编排照常出方案，只是少问了用户一次，没有任何报错。

改为组装器先于 policy：首轮必发确认题，第二轮起组装器按轮次返回空、自动回落默认 policy。顺带移除了 `feature_list_needs_clarification`——它原本是为了强行让 policy 返回 True，顺序修正后不再需要，留着反而会让第二轮多问一轮。

**2. 对话入口漏传 conversation_id → 确认卡渲染不出来**（`74a93f68`）

前端 plan 澄清卡由 `runtime.pending_plan_clarification` 驱动，而 runtime 是**按 conversation_id 反查 ConvergenceSession** 的；收答专路由同理。漏传同样不报错，但对话里看不到确认卡、用户无从作答——而强制确认恰恰是这条链路的核心。

## MCP 为什么是两段式

`create_feature_tech_plan` 只跑到强制确认就停，返回待确认项而非方案；必须再调 `confirm_feature_tech_plan` 才继续。这是「必须让用户确认关联仓库」的直接后果，不是可优化掉的往返。

第三个工具 `get_feature_tech_plan` 也是被迫的：调研阶段派容器后会话挂 `waiting_event`，而容器回调里的自动续驱（`_schedule_chat_plan_resume`）以 `entrypoint == CHAT` 守门——MCP 入口不在其列，`amaybe_complete_research` 只把 stage 推到 `merge` 就停了，没有消费者驱动 merge handler。所以非 chat 入口必须靠轮询驱动补上这一段。`adrive_convergence_session_to_pause_or_terminal` 自带「在途调研 / 未答澄清」短路，容器没跑完时轮询是安全空转。

## 三种取数源

| 来源 | 说明 |
|---|---|
| `project_id` | 项目已录入的 feature list 工件 |
| `branch_name` | 分支反查项目——**复用既有的手动绑定分支能力**（`ProjectBranch`，BIND-01），无需新建 |
| `feature_list_text` | 直接贴原文。有项目上下文走 LLM 逐字解析，没有则退启发式结构解析 |

启发式解析这条是刻意加的：IDE / CLI 场景常常还没建 Friday 项目，不能因为缺项目就不给用。

## 关于「允许用户手动绑定分支」

调研后确认**这个能力已经完整存在**，本次没有重复实现，而是把它接进 feature list 链路作为分支入口：

- 模型 `ProjectBranch`（`source`: manual / plan / coding）+ 唯一约束
- `ProjectBranchService.bind/unbind`（INV-6 唯一写入口，非成员 fail-closed）
- REST：`GET/POST /api/projects/{id}/branches/`、`DELETE .../branches/{branch_id}/`
- 前端：作战室右栏 `DependenciesSection` 的「关联分支」区块，含绑定表单与解绑
- 权限：View 层读权限进入 + Service 层项目成员 fail-closed

已跑测试确认完好：后端 17 个、前端 4 个。

## 改了哪些文件

**新建**

| 文件 | 作用 |
|---|---|
| `initiatives/services/feature_source.py` | 三源取数 + feature 树展平 + 启发式解析 |
| `initiatives/services/feature_solution_service.py` | start / confirm / get 三段式门面（MCP 与对话共用） |
| `initiatives/services/feature_solution_render.py` | 完整方案 Markdown（整体 + 分仓 + 落点 + 伪代码 + 分类表） |
| `agents/tools/feature_solution_tools.py` | 对话入口 `start_feature_solution` |
| `skills/skills/friday-solution/` | Skill 文档 + HTTP 兜底契约 |

**改动**

`mcp_tools/{serializers,views,urls}.py`（三工具 + snapshot）、`mcp/src/tools.ts`（33 工具）、`process_runtime/{clarify_adapter,entrypoint,feature_confirm_questions}.py`、`agents/chat_runner.py`（工具白名单）、`chat/conversation_service.py`（system prompt 分流规则）、`skills/skills/friday/SKILL.md` + `lib/installer.mjs` + `plugin.json`、`docs/integrations/{mcp,skills}.md`。

## 验证

- 新增测试 22 个：MCP 端到端 10（两段式全链路 + 三种取数源 + 越权 403）、对话工具 9、组装器顺序 4（其中一个是首轮/次轮回落的完整往返）
- 回归：`tests/{mcp_tools,services,delivery,initiatives,agents,chat}` + 澄清端点 **2167 passed**；此前含 workflows 的更大范围跑过 2846 passed
- npm 包 `mcp`：28 passed；前端分支绑定 UI：4 passed
- 改动文件 `ruff check` 全过；格式差异仅剩本次未触碰的既有代码行

## 端到端能力自检

| 需求 | 状态 |
|---|---|
| 判定新增 / 修改功能 | ✅ RAG 证据 + 能力树 + LLM，判 modify 必带真实文件，无依据降级 unclear |
| 结合仓库调研给出关联仓库 | ✅ RepoRouterV2 + 逐功能点混合检索 |
| 让用户选择 / 确认 / 澄清 | ✅ 三类确认题（选仓 / 复核改造 / 指认待定），全 high 置信也必问 |
| 分仓 + 整体方案 | ✅ `## 整体方案` + `## 分仓方案` 双层 |
| 伪代码 + 落点 | ✅ `change_type` / `touch_points` / `pseudocode` |
| Claude Code / Cursor | ✅ MCP 三工具 + friday-solution Skill |
| Friday 对话 | ✅ `start_feature_solution` + system prompt 分流 |
| 明确说「创建技术方案」时调用 | ✅ 写进 system prompt 与 Skill description |
| 方案沉淀 | ✅ `Artifact` / `ArtifactVersion`，自动进知识库 |
| 手动绑定分支 | ✅ 既有能力，已接为取数源之一 |

## 遗留

- **真实环境未验证**：全部测试都 mock 了 LLM、检索与调研容器。分类准确率、方案质量、容器调研耗时需真机跑一次 feature list（`.planning/feature-list-demo.md` 是现成样例）。
- **submodule 未推送**：`skills`（0fb4d87）与 `mcp`（ca7f1ea）已在各自本地 main 提交，需要推到各自远端并发版，IDE 侧才能装到新技能与新工具。
- **前端无专属 UI**：对话侧复用现有 plan 澄清卡与方案展示；项目页没有「生成技术方案」按钮入口。
- **既有缺陷未动**：`_h_decompose` 重建 decomposition 时会丢 `extra_evidence`（merge 阶段消费，可能从未生效）。属既有行为，改动会影响 MCP analyze 链路，应单独验证。
