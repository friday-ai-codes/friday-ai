---
phase: quick-260727-het-friday-routing-feature-list-prd
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - skills/skills/friday-routing/SKILL.md
  - skills/skills/friday-routing/references/http-fallback.md
  - skills/skills/friday/SKILL.md
  - skills/skills/friday-solution/SKILL.md
  - skills/skills/friday-code/SKILL.md
  - skills/lib/installer.mjs
  - skills/.claude-plugin/plugin.json
  - skills/README.md
  - docs/integrations/skills.md
  - task/assets/skills/friday-code/SKILL.md
autonomous: true
requirements: [QUICK-HET]
must_haves:
  truths:
    - "`skills/skills/friday-routing/SKILL.md` 存在，frontmatter 只有 name + description，正文覆盖 9 个调研维度、批量选项式澄清协议、路由矩阵输出格式与 report_project_knowledge 沉淀（CONTEXT decisions）"
    - "技能只出「路由/落点判定矩阵」，文档显式声明不出伪代码 / 模块详细设计 / 完整技术方案，并把这三类需求分流到 friday-solution / friday-code 阶段三"
    - "技能纯 agent 驱动：只编排 CONTEXT 列出的 15 个原子 MCP 工具，全文不出现 create_feature_tech_plan / confirm_feature_tech_plan / get_feature_tech_plan 三段式编排"
    - "无证据一律降级 unclear 的幻觉过滤原则写进护栏；未索引仓库必须停下告知而非拿空检索下结论"
    - "7 个接入面（friday 路由表+决策门 / friday-solution 边界表 / friday-code 阶段一 / installer.mjs / plugin.json / README.md / docs）全部含 friday-routing，技能总数一律 7"
    - "task/assets/skills/friday-code/ 与 skills/skills/friday-code/ 逐文件 sha256 恢复一致（改了源就必须重跑 sync_skills.py）"
    - "skills/ 子模块脱离 detached HEAD 处于 main 分支且工作区干净；子模块与主仓各自有提交，均未推远端"
  artifacts:
    - path: "skills/skills/friday-routing/SKILL.md"
      provides: "friday-routing 主文档（前置门槛 / 取数源 / 阶段分节 / 澄清协议 / 矩阵格式 / 护栏 / 技能边界 / HTTP 兜底）"
    - path: "skills/skills/friday-routing/references/http-fallback.md"
      provides: "MCP 不可用时原子工具的 HTTP 契约（端点 / 请求响应字段 / 错误码）"
    - path: "skills/README.md"
      provides: "技能表补齐 friday-solution（既有缺口）与 friday-routing，计数 5 → 7"
    - path: "docs/integrations/skills.md"
      provides: "用户文档技能表与计数 6 → 7，安装之后段落补分流"
  key_links:
    - from: "skills/skills/friday-routing/SKILL.md"
      to: "server/mcp_tools/serializers.py TOOL_SCHEMA_SNAPSHOT"
      via: "反引号工具名 ⊆ snapshot 键集 ∪ request/response 字段名集"
      pattern: "test_skills_snapshot_guard.py"
    - from: "skills/skills/friday-code/SKILL.md"
      to: "task/assets/skills/friday-code/SKILL.md"
      via: "python task/scripts/sync_skills.py 重新同步"
      pattern: "test_skills_injection.py TestSkillsHashConsistency"
    - from: "skills/skills/friday/SKILL.md 技能路由表"
      to: "friday-routing"
      via: "决策门新增分流问 + 路由表新增一行"
      pattern: "friday-routing"
---

<objective>
把「仓库路由 / 架构落点判定」从 `friday-solution` 的服务端黑盒里拆出来，做成可独立调用的 Agent Skill `friday-routing`：输入 feature list / PRD，输出**路由与落点判定矩阵**（每个功能点落到哪个仓库、仓库内哪个位置、新增还是改造、证据是什么、多确定）。

Purpose: `friday-solution` 的三段式服务端编排是黑盒——用户看不到调研过程与证据，也无法只要「落点判定」这一半产物。拆出纯 agent 驱动的 `friday-routing`，过程与证据全透明，判不准的地方主动带选项批量问用户。

Output: 1 个新技能目录（2 个文件）+ 7 处接入面同步 + friday-code 容器镜像物料重同步；子模块 1 个提交、主仓 1 个提交。

**明确不做（防画蛇添足）：**
- 不改服务端编排、不新增 MCP 工具、不动 `RepoRouterV2`——本任务纯文档 / 技能编写。
- 不把 `friday-routing` 加进 `task/assets/skills/`，也不改 `task/scripts/sync_skills.py` 的 `SKILL_NAMES`——它是 IDE / CLI 侧的调研技能，容器里跑的是编码 agent（Task 2 重跑 sync 脚本只是为了修复改动 `friday-code/SKILL.md` 带来的镜像漂移，不扩技能集）。
- 不走 `create_feature_tech_plan` / `confirm_feature_tech_plan` / `get_feature_tech_plan` 三段式——那是 `friday-solution` 的路径。
- 子模块**不推远端、不发 npm 版**（沿用 260726-uid 的做法，写进 SUMMARY 交由用户决定）。
- 不动 `docs/integrations/skills.md` 里既有的「33 个工具 / 30 个工具」计数不一致——那是历史遗留，超出本次范围。
</objective>

<execution_context>
@/Users/zaneliu/Projects/open-source/friday-clean/.cursor/gsd-core/workflows/execute-plan.md
@/Users/zaneliu/Projects/open-source/friday-clean/.cursor/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/quick/260727-het-friday-routing-feature-list-prd/260727-het-CONTEXT.md
@.cursor/rules/observability-logging.mdc
@skills/skills/friday-solution/SKILL.md
@skills/skills/friday-code/SKILL.md
@skills/skills/friday/SKILL.md
@skills/skills/friday-solution/references/http-fallback.md
@skills/lib/installer.mjs
@skills/.claude-plugin/plugin.json
@skills/README.md
@docs/integrations/skills.md
@server/mcp_tools/serializers.py
@server/tests/mcp_tools/test_skills_snapshot_guard.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: 子模块切回 main + 新建 friday-routing 技能</name>
  <files>skills/skills/friday-routing/SKILL.md, skills/skills/friday-routing/references/http-fallback.md</files>
  <action>
**第 0 步（必须先做，否则后续提交进不了分支）**：`skills/` 是 git 子模块，当前 detached HEAD at `488d9c4`，且 `488d9c4 == origin/main`。在 `skills/` 目录内执行 `git switch main`（若本地无 main 分支则 `git checkout -B main origin/main`），确认 `git -C skills status` 显示在 `main` 上、工作区干净、与 `origin/main` 同点后再动文件。本次 `workflow.use_worktrees=false`，直接在主工作树操作。

**第 1 步（写文档前的强制核对，CI 硬约束）**：`server/tests/mcp_tools/test_skills_snapshot_guard.py` 会用正则抓 SKILL.md 里**反引号包起来、以 `search|create|get|list|execute|improve|analyze|summarize|route|find|grep|read|report|lookup|reverse|update|confirm` 开头的 snake_case token**，要求它们 ⊆ `TOOL_SCHEMA_SNAPSHOT` 的键集 ∪ 全部条目的 request/response 字段名集。动笔前先读 `server/mcp_tools/serializers.py` 的 `TOOL_SCHEMA_SNAPSHOT`（约 L720 起），逐一核对本技能要引用的工具名拼写。CONTEXT 列出的 15 个原子工具（`route_repositories`、`get_repository`、`search_rag_chunks`、`grep_repository`、`list_repository_files`、`get_repository_file`、`find_related_chunks`、`reverse_lookup_requirements`、`search_delivery_knowledge`、`search_learning_cases`、`lookup_project_by_branch`、`search_project_context`、`grep_project`、`read_project_doc`、`report_project_knowledge`）全部已在 snapshot 键集内，可放心用反引号。**绝不反引号包裹不存在的工具名**（如自造的 route_features / get_routing_matrix）；描述矩阵字段、`ranked_repos` 条目里的 `score` / `confidence` / `matched_node_paths` / `sub_project` 等非动词前缀 token 不受守卫约束，正常写即可。

**第 2 步 — 写 `skills/skills/friday-routing/SKILL.md`**。文风与既有技能同构（zh-CN，参考 `friday-code` 的阶段分节骨架与 `friday-solution` 的护栏/边界写法）：

- frontmatter **只有** `name: friday-routing` 与 `description`。description 要写足触发场景（「这批需求该改哪些仓库」「feature list / PRD 的落点在哪」「哪些是新增哪些是改造」「给我一份路由矩阵」）与反向边界（要完整技术方案含伪代码 → `friday-solution`；单个需求要编码计划 / MR → `friday-code`；飞书工作项 → `friday-feishu`）。
- **前置门槛**：看不到 `friday` MCP 工具或返回 401/403 → 引导 `npx -y @friday-ai-codes/mcp setup`（指向 `friday` 技能「环境未就绪」一节）；保留首个响应的 `run_id` 全程携带。
- **铁律：纯 agent 驱动**。明确写清本技能自己编排原子工具做系统性调研、过程与证据对用户全透明，**不**调 `friday-solution` 的三段式服务端编排；澄清由 agent 自己发起、直接问用户，不依赖服务端组装的确认题。
- **取数源**（四选一，与 `friday-solution` 对齐再加本地文件）：当前 git 分支（`git rev-parse --abbrev-ref HEAD` 后用 `lookup_project_by_branch` 反查项目）/ Friday `project_id` / 用户直接贴的 feature list 或 PRD 原文 / 本地需求文档（读文件内容）。分支未绑定项目时提示去项目工作台「关联分支」或改用其它源，不要瞎猜项目。
- **阶段分节**，把 CONTEXT 的 9 个调研维度落进去，每维度都要求落到证据上：
  1. 阶段一 **索引健康度 + 候选仓收敛**（维度 8、1）：先用 `get_repository` 确认目标仓库 / 分支索引状态，未索引就停下告知用户去 Friday 完成索引，**不能拿空检索下结论**；再逐功能点用 `route_repositories` 做粗筛，读 `ranked_repos` 里的分数、置信度、命中节点路径与 monorepo 子应用信息，monorepo 必须下钻到子应用而不是停在仓库级。
  2. 阶段二 **落点下钻**（维度 2、3、4）：`search_rag_chunks` 做语义主力检索定位相关模块；需要穷举时切 `grep_repository`（推荐两步法：先 `output_mode="files_only"` 看命中分布，再 `output_mode="content"` + `context_lines` 抠上下文）；`list_repository_files` 浅扫目录结构确认落点形态；`get_repository_file` 读精确文件；`find_related_chunks` 从重要命中扩展。判 `modify` 必须指到**真实既有文件**；判 `new` 给建议落点目录并说明依据的是哪种既有同类结构。
  3. 阶段三 **跨仓依赖**（维度 5）：接口契约两侧（前端调用点 ↔ 后端实现）用 `grep_repository` 精确枚举，可传 `repository_ids` 数组或 `all_repositories=true` 跨仓检索；接口路径前后端命名常有差异（前缀、版本号、path 参数占位），命中为空时退一步用更短的稳定片段重试。
  4. 阶段四 **影响面与历史**（维度 6、7）：改造点用 `reverse_lookup_requirements` 反查已交付需求与文档，评估回归风险；`search_delivery_knowledge` / `search_learning_cases` 找相似需求与历史踩坑；有 Friday 项目上下文时可用 `search_project_context` / `grep_project` / `read_project_doc` 深挖 PRD 与项目记忆。
  5. 阶段五 **置信度定级与批量澄清**（维度 9 + 澄清协议）：每行定 high / medium / low；**只有 low 与关键 medium 才问用户，不为问而问**。澄清协议要写死四条：一轮把所有待澄清点**批量**摆出来（不逐条来回）；**每题必须给几个具体选项**（哪个仓库 / 哪个落点 / 新增还是改造），不能开放式提问；每题标出推荐项与推荐理由；用户答复前不得替用户拍板。
  6. 阶段六 **输出矩阵**：这是唯一产物。矩阵每行至少含——功能点 / 目标仓库（monorepo 含子应用）/ 目录·文件落点 / `new`·`modify`·`unclear` / 证据（真实文件路径或 chunk）/ 置信度 / 风险与跨仓依赖。给一个 markdown 表格示例（可参考 `.planning/feature-list-demo.md` 的功能点形态构造 2–3 行示例）。矩阵后附 `run_id`、涉及仓库清单、`new`/`modify`/`unclear` 计数。
  7. 阶段七 **结论沉淀**：跑完用 `report_project_knowledge` 把路由结论写回项目记忆，供后续 `friday-solution` / `friday-code` 召回复用；按当前 git 分支自动定位项目（传 `branch_name`），无需 `project_id`。沿用既有 fail-soft 语义：非项目成员 / 分支未绑定时静默跳过，绝不阻断。
- **护栏**（单列一节）：无证据一律降级 `unclear`，**不猜、不编造文件路径**；未索引仓库停下告知；不出伪代码 / 不出模块详细设计 / 不出完整技术方案；不替用户拍板；fail-soft（Friday 不可用时说明并退回本地处理）；**绝不上报也绝不回显任何凭证 / 密钥 / Access Token / 个人敏感信息**。
- **与其它技能的边界**（表格）：成批功能点 → 只要路由与落点矩阵 = 本技能；要完整技术方案（含分仓方案与伪代码）= `friday-solution`（本技能是它的上游，矩阵可直接喂进去）；单需求 → 编码计划 → 执行 → MR = `friday-code`；飞书工作项 = `friday-feishu`；项目进度 / 需求召回 = `friday-dev`；历史交付检索 = `friday-memory`。
- **HTTP 兜底**：一句话说明 MCP 不可用时所有工具都是 `POST {FRIDAY_BASE_URL}/api/mcp/tools/{tool_name}/` + Bearer 认证、`run_id` 经 `X-Friday-Run-ID` 头传递，完整契约链接到 `references/http-fallback.md`。

**第 3 步 — 写 `skills/skills/friday-routing/references/http-fallback.md`**。以 `skills/skills/friday-solution/references/http-fallback.md` 为版式模板（同样的端点块 + 工具契约表 + 请求示例 + 错误码表）；动笔前先读 `skills/skills/friday-code/references/http-fallback.md`，原子工具的写法要与它保持一致、不要给出互相矛盾的契约。覆盖本技能实际用到的原子工具：至少 `route_repositories`、`get_repository`、`search_rag_chunks`、`grep_repository`、`list_repository_files`、`get_repository_file`、`find_related_chunks`、`reverse_lookup_requirements`、`lookup_project_by_branch`、`report_project_knowledge`。请求 / 响应字段一律照抄 `TOOL_SCHEMA_SNAPSHOT` 对应条目，不要自己发挥。错误码表覆盖 `authentication_failed`(401) / `invalid_params`(400) / `repository_not_indexed` / `repository_not_found`(404) / `branch_not_bound`(400) / `forbidden`(403)。示例 curl 里绝不写入真实 token，一律用 `${FRIDAY_ACCESS_TOKEN}` 占位。
  </action>
  <verify>
    <automated>cd server && uv run pytest tests/mcp_tools/test_skills_snapshot_guard.py -q</automated>
  </verify>
  <done>`git -C skills status` 显示在 `main` 分支；`skills/skills/friday-routing/SKILL.md` 与 `references/http-fallback.md` 两个文件存在；snapshot 守卫 3 条断言全绿（含 `test_skill_files_discovered` 与工具名子集断言）。子模块内原子提交：`feat(friday-routing): 新增基于 feature list/PRD 的仓库路由与落点判定技能`</done>
</task>

<task type="auto">
  <name>Task 2: 同步 7 处接入面 + friday-code 容器镜像物料重同步</name>
  <files>skills/skills/friday/SKILL.md, skills/skills/friday-solution/SKILL.md, skills/skills/friday-code/SKILL.md, skills/lib/installer.mjs, skills/.claude-plugin/plugin.json, skills/README.md, docs/integrations/skills.md, task/assets/skills/friday-code/SKILL.md</files>
  <action>
逐个改，漏一个就装不到或 CI 红。技能总数统一口径为 **7**（friday / friday-dev / friday-routing / friday-solution / friday-code / friday-feishu / friday-memory）。

1. **`skills/skills/friday/SKILL.md`**（子模块）：
   - 「决策门」一节在现有第 4.5 问（feature list → `friday-solution`）附近新增一问，把「用户给了 feature list / PRD，只想知道**这批功能点该落到哪些仓库、仓库里的哪个位置、是新增还是改造**」分流到 `friday-routing`，并点明与 4.5 的区别：要矩阵走 routing，要完整方案（含伪代码）走 solution。
   - 「技能路由」表新增一行：场景「feature list / PRD → 仓库路由与落点判定矩阵（目标仓库·落点文件·新增/改造·证据·置信度）」→ 技能 `friday-routing`。放在 `friday-solution` 行之前（routing 是 solution 的上游）。
   - 「直通模式」那段的意图分流句里补一句 routing 的分支。

2. **`skills/skills/friday-solution/SKILL.md`**（子模块）：「与其它技能的边界」表加一行——「只要仓库路由与落点判定矩阵，不要完整方案」→ `friday-routing`，并在表下补一句：`friday-routing` 是本技能的**上游**，它的矩阵可以直接作为本技能第二步确认关联仓库时的输入依据。

3. **`skills/skills/friday-code/SKILL.md`**（子模块）：「阶段一 — 找仓库」一节末尾（护栏之前或之后）加一句：单个需求的仓库定位用本阶段；**成批功能点 / feature list / PRD 的路由与落点判定走 `friday-routing`**，它会逐功能点出矩阵，比在这里一个个 `route_repositories` 更系统。**注意：改了这个文件必须做第 8 步重同步**。

4. **`skills/lib/installer.mjs`**（子模块）：`bootstrapBody` 里的技能清单（约 L73）由 6 个改成 7 个，按 `friday / friday-dev / friday-routing / friday-solution / friday-code / friday-feishu / friday-memory` 顺序列出；决策门编号列表新增一条 routing 分流规则（放在现有第 5 条 `friday-solution` 之前或之后，**记得把后续条目重新编号**，现有第 6 条会变成第 7 条）。措辞与第 5 条同构、一句话说清「要矩阵不要完整方案」的分界。

5. **`skills/.claude-plugin/plugin.json`**（子模块）：`description` 里 `6 skills (friday / friday-dev / friday-solution / friday-code / friday-feishu / friday-memory)` 改为 `7 skills (... / friday-routing / ...)`，并在能力枚举里补一段 routing 的英文描述（feature-list/PRD-to-repository-routing matrix: target repo incl. monorepo sub-app, landing files, new-vs-modify with evidence, confidence）。**只改 description**，不动 `version` / `hooks` / `mcpServers` 等字段（本次不发版）。

6. **`skills/README.md`**（子模块）：注意这里有**既有缺口**——当前表只有 5 行、`friday-solution` 从未补进去。本次一并修：`## Skills（5 个）` → `## Skills（7 个）`，表格补 `friday-solution` 与 `friday-routing` 两行（顺序 friday / friday-dev / friday-routing / friday-solution / friday-code / friday-feishu / friday-memory）；「设计」一节的 `**好记**：5 个 skill` → `7 个 skill`；「本地验证」一节的注释 `# 应列出 5 个技能` → `7`；安装向导描述里的「把 5 个技能拷进各 agent 原生技能目录」→ `7`。

7. **`docs/integrations/skills.md`**（主仓，不是子模块）：`6 个职责清晰的 skill` → `7 个`；表格新增 `friday-routing` 行（放在 `friday-dev` 与 `friday-solution` 之间），文案描述「由 feature list / PRD 出仓库路由与落点判定矩阵：目标仓库（含 monorepo 子应用）→ 落点文件 → 新增 / 改造 → 证据 → 置信度；判不准主动带选项批量问，不猜」；「安装之后」一节（约 L88）的路由句里补一句 routing 分流。**不要动**该文件里既有的「33 个工具 / 30 个工具」计数不一致，那是历史遗留、超出本次范围。

8. **重同步容器镜像物料（关键，漏了 CI 必红）**：第 3 步改了 `skills/skills/friday-code/SKILL.md`，而 `task/tests/test_skills_injection.py::TestSkillsHashConsistency` 守卫 `task/assets/skills/{friday-code,friday-memory}/` 与源目录**逐文件 sha256 一致**。在主仓根执行 `python task/scripts/sync_skills.py` 重新同步，它会重建 `task/assets/skills/friday-code/`。**不要手工编辑 assets 副本**，也**不要**改脚本里的 `SKILL_NAMES`——`friday-routing` 刻意不进容器（容器里跑的是编码 agent，routing 是 IDE / CLI 侧的调研技能）。

9. 全部改完后，用 `node skills/bin/friday-ai-skills.mjs list` 确认列出 7 个技能（该命令扫目录，不读硬编码计数，可用于反查目录是否建对）。
  </action>
  <verify>
    <automated>cd server && uv run pytest tests/mcp_tools/test_skills_snapshot_guard.py -q && cd ../task && uv run pytest tests/test_skills_injection.py -q</automated>
  </verify>
  <done>7 处接入面均含 `friday-routing` 且技能计数统一为 7；README 的 `friday-solution` 既有缺口一并补齐；`task/assets/skills/friday-code/SKILL.md` 与源文件 sha256 一致（`test_skills_injection.py` 6 条全绿）；snapshot 守卫全绿。子模块内原子提交：`docs(skills): 接入面同步 friday-routing 并补齐 README 技能表`（`docs/integrations/skills.md` 与 `task/assets/` 属主仓，留到 Task 3 一起提）</done>
</task>

<task type="auto">
  <name>Task 3: 全量守卫回归 + 主仓提交与子模块指针</name>
  <files>（无源文件改动；git 提交与回归验证）</files>
  <action>
1. **全量守卫回归**，三条命令都要绿（后端测试从 `server/` 目录用 `uv run pytest`，任务侧从 `task/` 目录）：
   - `cd server && uv run pytest tests/mcp_tools/test_skills_snapshot_guard.py tests/mcp_tools/test_schema_snapshot.py -q` —— 文档工具名 ⊆ snapshot，且 snapshot 本身未漂移（本任务不应改动 snapshot，若 `test_schema_snapshot.py` 变红说明误改了 `serializers.py`，回滚）。
   - `cd task && uv run pytest tests/test_skills_injection.py -q` —— 双源 hash 一致性。
   - `node skills/bin/friday-ai-skills.mjs list` —— 输出 7 个技能。

2. **主仓提交**。先 `git status` 确认待提内容只有三类：子模块指针 `skills`（Task 1/2 在子模块内提交后指针自动前移）、`docs/integrations/skills.md`、`task/assets/skills/friday-code/`。逐一 `git add` 后单次提交，message 用中文约定式格式：`feat(skills): 新增 friday-routing 技能并同步接入面与文档`。**不要** `git add -A`（避免把无关的 `.planning/` 或本地脏文件带进来；`.planning/` 由 GSD 流程单独提交）。

3. **子模块提交纪律核对**（沿用 260726-uid 的做法）：
   - `git -C skills status` 必须显示在 `main` 分支且工作区干净——**不是 detached HEAD**。若 Task 1 第 0 步漏做导致提交落在 detached HEAD 上，现在补救：`git -C skills branch -f main <当前 HEAD>` 后 `git -C skills switch main`，再重新确认主仓指针。
   - `git -C skills log --oneline -3` 应能看到 Task 1 与 Task 2 的两个提交在 `main` 上。
   - **子模块不推远端、不发 npm 版**——这是**故意留给用户**的遗留项，必须写进 SUMMARY 的「遗留项」一节，注明需要用户自行决定何时 `git -C skills push origin main` 与是否 bump 版本发 `@friday-ai-codes/skills`（本次未动 `plugin.json` 的 `version` 与 `package.json`）。

4. **人工抽查**（自动化盖不到的语义面，逐条确认后写进 SUMMARY）：`friday-routing/SKILL.md` 全文不含 `create_feature_tech_plan` / `confirm_feature_tech_plan` / `get_feature_tech_plan`（可用 grep 自查）；不含伪代码 / 模块详细设计类产物承诺；澄清协议四条（批量 / 带具体选项 / 标推荐项与理由 / 不替用户拍板）齐备；9 个调研维度都能在正文找到落点；无任何明文 token / 凭证。
  </action>
  <verify>
    <automated>cd server && uv run pytest tests/mcp_tools/test_skills_snapshot_guard.py tests/mcp_tools/test_schema_snapshot.py -q && cd ../task && uv run pytest tests/test_skills_injection.py -q && cd .. && node skills/bin/friday-ai-skills.mjs list</automated>
  </verify>
  <done>三组守卫测试全绿且 list 输出 7 个技能；`git -C skills status` 干净且在 `main`；主仓单次提交含子模块指针 + `docs/integrations/skills.md` + `task/assets/skills/friday-code/`；子模块未推远端、未发版，遗留项已记录</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| SKILL.md 文档 → agent 运行时行为 | 技能文档是 agent 的执行指令，写错工具名 / 写错护栏会直接变成运行时错误调用或越权产物 |
| 技能编排 → Friday MCP / HTTP 端点 | HTTP 兜底文档示例中的凭证占位与错误码指引，决定用户是否会在终端明文粘贴 token |
| 技能沉淀 → Friday 项目记忆 | `report_project_knowledge` 把路由结论写回服务端，内容一旦含敏感信息即长期留痕 |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-het-01 | Information Disclosure | `references/http-fallback.md` curl 示例 | medium | mitigate | 示例一律用 `${FRIDAY_ACCESS_TOKEN}` / `${FRIDAY_BASE_URL}` 环境变量占位，绝不写入真实值；SKILL.md 护栏明写「任何输出不得回显 Access Token」（Task 1） |
| T-het-02 | Information Disclosure | `report_project_knowledge` 沉淀（阶段七） | medium | mitigate | 护栏明写「绝不上报任何凭证 / 密钥 / token / 个人敏感信息」，与 `friday` 技能「分支上下文环路」既有口径一致；服务端另有脱敏 + 质量门槛兜底（Task 1） |
| T-het-03 | Tampering | 文档写不存在的 MCP 工具名 → agent 调用失败 / 误导 | high | mitigate | 写前核对 `TOOL_SCHEMA_SNAPSHOT`，写后跑 `test_skills_snapshot_guard.py`；Task 1/2/3 三次验证（Task 3 兼跑 `test_schema_snapshot.py` 确认未误改 snapshot） |
| T-het-04 | Tampering | `skills/skills/friday-code/` 与 `task/assets/skills/` 双源漂移 | high | mitigate | Task 2 第 8 步强制重跑 `task/scripts/sync_skills.py`，`test_skills_injection.py` 逐文件 sha256 守卫 |
| T-het-05 | Repudiation | 子模块提交落在 detached HEAD 上 → 提交悬空不可追溯 | medium | mitigate | Task 1 第 0 步先 `git switch main`；Task 3 第 3 步复核并给出补救路径 |
| T-het-SC | Tampering | npm/pip/cargo installs | low | accept | 本任务零新增依赖，无任何包安装动作 |
</threat_model>

<verification>
1. `cd server && uv run pytest tests/mcp_tools/test_skills_snapshot_guard.py tests/mcp_tools/test_schema_snapshot.py -q`
2. `cd task && uv run pytest tests/test_skills_injection.py -q`
3. `node skills/bin/friday-ai-skills.mjs list` → 7 个技能
4. `git -C skills status --branch` → 在 `main`、工作区干净；`git status` 主仓待提内容仅子模块指针 + `docs/integrations/skills.md` + `task/assets/skills/friday-code/`

可观测性规范（`.cursor/rules/observability-logging.mdc`）自检：本任务为纯文档 / 技能编写，**未新增或修改任何 API / 工作流节点 / 服务 / 任务 / webhook / LLM 调用 / 召回**，无埋点面变更，日志规范条目不适用——此结论需写进 SUMMARY 备查。
</verification>

<success_criteria>
- [ ] `skills/skills/friday-routing/` 下 `SKILL.md` + `references/http-fallback.md` 两个文件齐备，frontmatter 只有 `name` + `description`
- [ ] SKILL.md 覆盖 9 个调研维度、四条澄清协议、矩阵七列格式、`report_project_knowledge` 沉淀与 fail-soft 语义
- [ ] SKILL.md 全文不出现三段式服务端编排工具，且显式声明不出伪代码 / 模块详设 / 完整方案并给出分流
- [ ] 「无证据降级 `unclear`」与「未索引停下告知」写进护栏
- [ ] 7 处接入面（friday / friday-solution / friday-code / installer.mjs / plugin.json / README.md / docs）全部同步，计数统一为 7，README 的 `friday-solution` 既有缺口一并补齐
- [ ] `python task/scripts/sync_skills.py` 已重跑，`task/assets/skills/friday-code/` 与源 sha256 一致；`SKILL_NAMES` 未被扩展
- [ ] 三组守卫测试全绿；`serializers.py` / `TOOL_SCHEMA_SNAPSHOT` 零改动
- [ ] `skills/` 子模块在 `main` 分支、两个原子提交；主仓一个提交含指针 + 主仓侧两处文件
- [ ] 子模块未推远端、未发 npm 版，作为遗留项写进 SUMMARY
</success_criteria>

<output>
完成后创建 `.planning/quick/260727-het-friday-routing-feature-list-prd/260727-het-SUMMARY.md`，记录：`friday-routing` 的最终章节骨架与矩阵列定义、7 处接入面的实际改法、`friday-code` 镜像重同步的原因（改源必重跑 sync 脚本，否则 hash 守卫红）、人工抽查结论、可观测性规范不适用的判定，以及**遗留项**：`skills/` 子模块的 `main` 分支未推 `origin`、npm 包未 bump 版本发布，交由用户决定时机。
</output>
