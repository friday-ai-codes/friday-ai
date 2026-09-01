---
status: resolved
trigger: "完全修复 MCP/AI 对话技术蓝图的错误 Project 硬关联、Team 范围失真、Top 10 不可逆截断、direct 粗暴判定与上下文证据未进入路由约束问题。"
created: 2026-09-01
updated: 2026-09-01T17:20:00+08:00
---

# Debug Session: MCP Blueprint Routing Scope

## Symptoms

- Expected behavior: MCP/AI 对话入口不强制绑定 Project；只有显式 Project UUID 或唯一、严格的 WorkItem 关联才能绑定。Team 可确定时作为硬范围，不确定时先向用户澄清。Top 10 仅是首轮候选预算，显式仓、团队核心仓与可信历史证据可补入。路由阶段只产 candidate，direct/indirect/irrelevant 由逐仓调研基于具体代码证据判定。PRD、feature list、测试 case、飞书字段、技术文档与显式仓名全部进入带来源/置信度的路由上下文。
- Actual behavior: AGE-64 被错误绑定到已归档的“AI私教动画课” Project；TeamGate 把“学习工具”Space 的 30 个仓整体当作 team_core；shortlist Top 10 成为不可逆 hard_scope；任何 high confidence 或 charter_match>0 的仓直接标 direct；六个能力相似但无实际归属的仓进入确认门，study-course 与 study-config 缺失。
- Error messages: 无运行时异常；属于静默错误关联与错误路由。AGE-64 artifact `b36ffd68-d3d2-4ebc-a929-4f6c82c33585` 停在 repo_confirmation。
- Timeline: v0.25.0/Phase 128-132 漏斗上线后，合成高三回归通过，但真实 Space 用例被 skip；2026-09-01 AGE-64 Opus canary 首次完整暴露生产路由偏差。
- Reproduction: 通过 Multica 技术方案 Agent 调 `get_feishu_work_item_context` 与 `create_feishu_technical_plan` 生成“高三提分专项”蓝图，不显式传可靠 Project/Team/仓库白名单；观察 Project 解析、team_core、shortlist、逐仓角色与 repo_confirmation。

## Current Focus

- hypothesis: 已确认并修复：Project ownership、Space authorization universe、Team responsibility、route candidate 与 research-owned role 被错误合并。
- test: change-owned 248/248、route 22/22、focused 112/112、Team 10/10、authorization boundary 5/5 全绿；ruff check/format 与 git diff --check 通过。
- expecting: 本地契约与回归验证完成；仅生产登记名称/索引状态需只读 live canary 验证。
- next_action: 如获单独授权，执行只读 live canary 验证 study-course/backend-config 实际登记与 AGE-64 路由形状；本轮禁止远端操作，故不执行。
- reasoning_checkpoint:
    hypothesis: "Project ownership、reference context 与 repository routing 三个概念被合并，是全部症状的共同根因。"
    confirming_evidence:
      - "TeamGate RED：仅 space_id 时实际 team_core=['repo-x','repo-y']，违反 Space 仅为可访问宇宙的契约。"
      - "Callback RED：非法/缺失 role、无具体代码落点 direct、显式 irrelevant 均被实际归一为 direct。"
      - "源码确认 aresolve_project_id 从 Space 猜首 Project，route 按 confidence/charter 预判 direct。"
      - "并行 DB focused tests 争用同一 test_friday，属于测试隔离问题，不反驳业务假设。"
    falsification_test: "若最小修复后同一 focused 回归仍呈现 Space 猜 Project/Team、route 预判角色或无落点 direct，则组合根因不完整并退回 investigating。"
    fix_rationale: "把 Project/Space/Team/候选/调研结论拆成独立事实：Project 只接收显式或唯一关系，Space 只限定可访问仓库，Team 由可信字段或已确认项目仓解析，shortlist 允许证据强制补回，最终角色只接受带代码位置的调研结论。"
    blind_spots: "生产 study-config 实际登记名称/索引状态仅能通过另行只读 canary 验证；本轮明确禁止连接远端。"

## Evidence

- timestamp: 2026-09-01T13:57:00+08:00
  checked: AGE-64 持久化 routing、Project/WorkItem/Space 关系、TeamGate、shortlist、role suggestion、confirm gate 与高三合成测试。
  found: 错误 Project 为 c8feeca8；正确高三 Project 为 75248ff9 且无 WorkItem link；学习工具 Space 有 414 Projects/30 indexed repositories；production team_core=30、shortlist=10、history_match 全 0；真实 Space 测试被 skip。
  implication: 必须做契约级修复，不能只通过 prompt、权重或人工确认兜底。
- timestamp: 2026-09-01T14:08:00+08:00
  checked: 当前分支/工作区、Friday 分支召回、blueprint_intake、team_gate 与 MCP delegate。
  found: 工作区除本 debug 文件外干净；main 分支被 Friday 显式绑定到无关“小学思维培优-刷题入口”，进一步证明分支/Space/弱引用不能替代蓝图 Project 身份。intake 当前明确把 MCP context.space 与 chat conversation.space 转成首个 Project，并在无 Project 时拒绝；TeamGate 当前把 Project.space/显式 Space/context Space 全仓挂载直接返回 team_core。
  implication: Project 与 Team 两处根因已由代码直接确认；修复必须把 Space 降为授权仓库宇宙，并允许未绑定 Project 的蓝图骨架与后续授权链。
- timestamp: 2026-09-01T14:22:00+08:00
  checked: schema、session/intake handler、仓库 facets、ProjectWorkItemLink/RepoAssociation、shortlist/place_units、research callback/confirm gate 与蓝图 API 授权。
  found: schema 强制 project_id 非空且 intake handler 无 project 不建 artifact；Repository.facets 的“团队归属”是现有真实 Team 数据源；shortlist 已支持 force include 突破 Top 10，但 route 只传历史/planned 且 placement 将 shortlist 固化为 hard_scope；callback 接受无具体文件/API 落点的 direct，confirm gate 仅对 unsuitable 预移除；artifact 自带 created_by_user_id，SpaceMembership 可支持未绑定 Project 的授权。
  implication: 根因机制已足够具体且可证伪，进入 RED 回归与最小修复阶段。
- timestamp: 2026-09-01T14:32:00+08:00
  checked: 新增 Project/Team/route/research focused RED tests，并执行最小选择集。
  found: Team 的 Space→team_core、callback 的 direct fallback/无落点 direct/irrelevant 丢失均稳定失败；其余 DB tests 因并行 pytest 争用同一 test_friday 而在 setup 阶段失败，未产生业务判断。
  implication: 直接失败已确认 scope/role 根因；后续测试改为单进程串行加 --reuse-db，避免基础设施竞争污染结果。
- timestamp: 2026-09-01T14:42:00+08:00
  checked: optional Project/Space skeleton、唯一 ProjectWorkItemLink、Team facet/Space universe、route candidate、research direct 证据门及完整 route suite。
  found: 身份 focused 7/7 通过；route suite 20/20 通过。为保持路由证据可解释性，placement 候选重新继承 shortlist signal 的 confidence/reasoning/matched_node_paths/router_version。
  implication: Project/Team/route 三层修复已转绿；继续验证 research 与完整 intake 邻域。
- timestamp: 2026-09-01T14:52:00+08:00
  checked: intake、team gate、route、research stage、research callback 五文件串行 focused suite，以及生产 diff 的身份/授权/异步 ORM/可观测性边界。
  found: 112 passed（12 个既有 warning），无失败；发现 project_id-only Team 解析虽正确使用 confirmed/verified associations，但 accessible_repository_ids 错误复用了 responsibility 集合，已改为独立读取 Project.space.repositories 并增加断言；同步修正 optional Project 的过时 docstring。
  implication: focused 契约已稳定；必须回跑受补丁影响的 Team suite，再扩大到入口、API 与邻接 process runtime 回归。
- timestamp: 2026-09-01T15:25:00+08:00
  checked: optional Project 人审 API 授权顺序、Team 补丁回归及 1257 项 broad collection。
  found: Team 10/10 通过。diff review 发现 creator fallback 在 ProjectMember 检查前执行，可让 Project-bound creator 绕过项目成员闸；已限制 creator/SpaceMembership 仅用于 project_id 为空，并新增 creator、Space member、outsider 与 project-bound creator 四个安全回归。首次 broad run 与随后一次 review run受共享 --reuse-db 并行污染：前者大量 PostgreSQL “another command is already in progress/Can't assign requested address”，后者 63 passed、1 setup error（残留 username=testuser），均非业务断言失败。
  implication: 授权绕过已封堵且新增用例本身均通过；测试库需 --create-db 清理后严格串行复验，污染结果不得计入产品失败或最终绿灯。
- timestamp: 2026-09-01T17:20:00+08:00
  checked: 串行 change-owned suites、MCP/API/chat 邻域、schema、response compatibility、diff、ruff check/format 与敏感路由上下文过滤。
  found: change-owned 248 passed；route 22 passed；ruff check 全绿、ruff format --check 19 files already formatted、git diff --check 通过。broad -x 在 623 passed 后命中本变更引入的 response key 字面量兼容失败，已把 blueprint_status 改为既有 blueprint_current_status 并单测转绿。后续邻域 314 passed，剩余 5 个失败均位于未改动基线：BLUEPRINT_EVENTS 既有计数 29 与旧断言 27 不符；四个 blueprint_gate_scope fixture 把无具体代码落点的 direct 当有效，触发现有 confirm gate 的 evidence-incomplete 404。另补 access_token/client_secret 等复合敏感键不得进入 routing context 的回归并转绿。
  implication: 本变更范围内无剩余本地失败；保留五个非本变更基线失败，不为追求全绿修改无关事件目录或放松 direct 证据门。

## Eliminated

- hypothesis: Opus 模型或仓库调研 callback 故障导致错误仓。
  reason: AGE-64 十个调研任务全部 done；错误候选在 route 阶段已经形成。

## Resolution

- root_cause: Project ownership、Space 可访问范围、Team 责任范围、路由候选与调研角色被压成同一概念：Space 首 Project 被当身份，Space 全仓被当 Team，Top 10 被固化为 hard scope，route confidence/charter 被当 direct 结论。
- fix: MCP/chat 仅接受显式 Project 或唯一 ProjectWorkItemLink；unbound 蓝图保留 Space 并按 creator/SpaceMembership 授权；Project-bound 仍严格 ProjectMember。Team 从 confirmed/verified associations 或 Repository.facets 解析，Space 独立返回 accessible universe。显式/Team/历史仓可突破 Top 10，route 只产 candidate，research 以具体 file/API/model 落点裁定 direct/indirect/irrelevant；上下文带来源/置信度进入软路由且过滤复合敏感键。
- verification: focused 112 passed；Team 10 passed；authorization boundary 5 passed；change-owned 248 passed；route 22 passed；response compatibility 1 passed；ruff check、ruff format --check、git diff --check 全通过。broader 邻域另有 314 passed 与五个未改动基线失败，已记录且未越界修复。
- files_changed:
  - .planning/debug/mcp-blueprint-routing-scope.md
  - server/delivery/api/blueprint_review_views.py
  - server/mcp_tools/orchestration_delegate.py
  - server/mcp_tools/technical_plan_service.py
  - server/services/process_runtime/blueprint_intake.py
  - server/services/process_runtime/blueprint_research_adapter.py
  - server/services/process_runtime/blueprint_route.py
  - server/services/process_runtime/blueprint_schema.py
  - server/services/process_runtime/builtin_processes.py
  - server/services/process_runtime/entrypoint.py
  - server/services/process_runtime/team_gate.py
  - server/subagent/api/callbacks.py
  - server/tests/delivery/test_blueprint_review_views.py
  - server/tests/mcp_tools/test_create_feishu_technical_plan_delegate.py
  - server/tests/services/process_runtime/test_blueprint_intake.py
  - server/tests/services/process_runtime/test_blueprint_repo_alias.py
  - server/tests/services/process_runtime/test_blueprint_research_stage.py
  - server/tests/services/process_runtime/test_blueprint_route_stage.py
  - server/tests/services/process_runtime/test_team_gate.py
  - server/tests/subagent/test_blueprint_research_callback.py
