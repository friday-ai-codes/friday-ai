# Pitfalls Research

**Domain:** 公开 MCP 全链路开放与长任务稳定性（Friday AI v0.26.0）
**Researched:** 2026-09-14
**Confidence:** HIGH（本仓现行实现 + 里程碑已知债 + MCP 规范/生产运维共识交叉；npm 已发布版本与本 worktree 是否同步属 MEDIUM，须以 registry 实查为准）

> 相位代号仅供 roadmap 编排，不预占具体相位号。建议依赖序：
> **P1 契约三面对齐** → **P2 公开 HITL 控制面** → **P3 分仓方案/合成 MCP** → **P4 长任务异步 job / 未知结果** → **P5 诊断、回调与恢复** → **P6 范围闸 / 预言机 / 密钥** → **P7 真依赖 canary 与发版钉扎**。
> 「Phase to address」对应此序。

本文只谈**把内部已齐备的蓝图/编排链当成「外部 Agent 仅靠公开 MCP 即可跑完」时**会让链路看起来完整、实际不安全、不可观测、非幂等或不可恢复的坑。不复述通用 Web 安全清单。

## Critical Pitfalls

### Pitfall 1: 静态白名单漂移 —— 服务端 55、npm 43、测试还锁「一致」

**What goes wrong:**
HTTP `/api/mcp/tools/<name>/` 与 `TOOL_SCHEMA_SNAPSHOT` 已注册约 **55** 个工具（含 `graph_query`、impact/detect/process 族、`report_session_knowledge`、`approve_technical_blueprint` / `request_technical_blueprint_changes` 等）。`mcp/src/tools.ts` 的 `FRIDAY_TOOLS` 是**静态白名单**，未知名直接 `未知工具` 拒绝；当前清单 **43** 个。`mcp/tests/server.test.ts` 仍断言「定义了与服务端一致的 43 个工具」。结果：Cursor / Claude Code 经 `npx -y @friday-ai-codes/mcp` **调不到**终审、图查询、会话知识回写等；直打 HTTP 的容器/内部 Agent 却能调。产品口径「MCP 全链路开放」在 stdio 面上是假的。

**Why it happens:**
历史上 `test_skills_snapshot_guard` 只验 SKILL.md ⊆ snapshot；`test_mcp_package_alignment` 才验包名 == snapshot，但 **mcp 子模块未 checkout 时 pytest.skip**（v0.20.0 审计已坐实：全里程碑空跑后首次实跑转红）。npm 测试把「43」写成成功契约，后续加服务端工具时实现者只改 Django + snapshot，以为对齐守卫会拦。字段级对齐目前只锁少数新工具（如 session knowledge 三件套），其余工具 properties 可静默漂。

**How to avoid:**
单一事实源：注册表（`urls.py`）== `TOOL_SCHEMA_SNAPSHOT` == `FRIDAY_TOOLS` == annotations 键集，**CI 无 skip 后门**。禁止「43」这类绝对计数当绿；改成集合差断言。新工具同一 PR 必须带：serializer、snapshot 字面量（`test_schema_snapshot` 独立字面量，不得从源码再 import 比较）、npm `name`+`inputSchema.properties`+`TOOL_ANNOTATIONS`、skills 文档子集。HTTP 直打与 stdio 不得成为两套产品面。

**Warning signs:**
- `test_mcp_package_alignment` skip / `TOOLS_TS.exists()` 为假仍判绿。
- npm 测试 `toHaveLength(43)` 仍在，而 snapshot 键已 >43。
- skills/`SKILL.md` 写了 `approve_technical_blueprint` 但 `FRIDAY_TOOLS` 无该项。
- 演示走 HTTP curl 绿、Cursor 调同名工具红。

**Phase to address:**
P1 契约三面对齐。P2/P3 新工具若先只落服务端，会立刻再漂一次。

---

### Pitfall 2: 固定 120s 客户端超时把「进行中」变成「失败」，Agent 盲目重试

**What goes wrong:**
`mcp/src/server.ts` `REQUEST_TIMEOUT_MS = 120_000`，`AbortSignal.timeout` 切断的是 **stdio 进程的等待**，不是 Django 视图、durable job、runner 容器。`execute_coding_plan` / `execute_work_item_repo_tasks` 的 schema 允许 `timeout_seconds` 60–21600、默认 **3600**。调研/融合/编码经常 >120s。Agent 收到 `Friday 请求失败（网络 / 超时）` + `isError: true`，按 MCP 规范会把 tool execution error 交给模型自纠 —— 典型动作是**再调一次写工具**。服务端可能已经 dispatch 成功。这是「未知结果（unknown outcome）」而不是失败。

**Why it happens:**
MCP 规范（2026-07-28 tools）要求客户端实现超时；取消是 best-effort，接收方可以忽略。实现者把「别把 stdio 挂死」做成全局 120s，没有按工具分级，也没有「超时 = unknown，先查 job」协议。编排侧 `delegate_process_runtime` 在 MCP 入口甚至 `skip_clarification=True` 同步 `adrive` 到终态，把分钟级工作塞进一次 `tools/call`。

**How to avoid:**
写工具（生成/执行/确认）**禁止**依赖同步跑完：立即返回 `job_id`/`session_id` + `status=accepted|running`，配套只读 `get_*` 为权威结果。stdio 超时后返回稳定机器码 `outcome_unknown`（不要伪装成业务失败），并提示用同一 idempotency key / job_id 查询。读工具可保留短超时。取消不得假定副作用已回滚。

**Warning signs:**
- 新 MCP 写工具没有配对的 get/status。
- 日志出现同一 `idempotency_key` 未命中却连续 `create_*` / `execute_*`。
- 容器/会话已 running，Agent 对话里却是「工具超时失败，我再试一次」。
- 单测只 mock 200 JSON，从不模拟 abort 后的权威查询。

**Phase to address:**
P4 长任务异步契约。P1 可先给超时错误码，但若仍同步跑编排，P2/P3 的 HITL 会在 120s 墙外不可达。

---

### Pitfall 3: 幂等键缺失或「键相同参数不同」—— 重复 MR、重复调研、重复审查

**What goes wrong:**
`create_feishu_technical_plan` 已有 `idempotency_key`（唯一约束 + pending/conflict/cancelled 态）。多数公开写工具没有：`create_merge_request`、`execute_coding_plan`、`apply_repo_association`、`start_repo_research`、确认门动作。超时重试或 Agent 换措辞重试会建第二份 PR、第二波容器。即便有键：第二次请求参数不同却复用键，若实现「覆盖旧意图」或「返回第一次失败缓存」，会把错误结果锁死；若第一次仍 pending 时第二次 409 提前返回，调用方停止重试而第一次随后失败 —— 消息丢失（业界幂等经典坑）。

**Why it happens:**
MCP annotations 把生成类标 `idempotentHint: false`，执行类同样。实现者理解为「不用做幂等」。驱动多入口（durable worker、回调 barrier、确认门、僵尸扫描）叠加后，`ProcessEngine.advance` 曾经只在写回瞬间 CAS —— **handler 本体跑了 N 遍**（本仓实证：AI 审查并发 7 次、token 烧掉、BLOCKER 线程翻倍）。`drive_lease` 是补丁；其 DB 异常还 **fail-open「当作抢到了」**，抖动时仍会重复跑。

**How to avoid:**
所有有外部副作用或贵 LLM 的 MCP 写工具：调用方或服务端稳定 `idempotency_key`（或确定性业务键：work_item × repo × wave）。原子插入 reservation；pending 返回 in-progress 而非「失败」；完成则回放原响应；键+参数哈希不一致 → 稳定 conflict，不覆盖。Git/飞书侧用 provider 去重查询做对账。测试必须含：超时切断响应路径后同键重试 ⇒ 副作用仍为 1。

**Warning signs:**
- 同一 work item 两条 `McpWorkItemTechnicalPlan` / 两个 MR URL。
- `drive_lease` 日志 `fail-open` 后审查线程数倍增。
- 幂等测试只覆盖「第二次 200 同结果」，没有「pending 时并发」和「参数漂移 409」。

**Phase to address:**
P4（job 与键）必须先于把更多写工具公开到 npm。P5 的回调重入会放大无键工具。

---

### Pitfall 4: 回调丢失与电平 barrier —— 任务「完成了」编排仍 running，或完成一次驱动七次

**What goes wrong:**
容器终态有 Runner 事件，但 structured business callback 丢了（网络、5xx 禁令导致 handler 吞错、callback_url 打到 runner 中转 404）。`areconcile_stalled_blueprint_research_tasks` 已识别 `completed_without_structured_result_callback`，用 Runner 终态把调研 task 标失败/完成 —— **这是恢复，不是主路径**。主路径若仍等 callback，MCP 的 `get_repo_research` / 蓝图 get 会永远 `running`。反面：barrier 是电平（「都产出了吗」一旦真就恒真），每个后到的 callback 再入队续驱 → 与 Pitfall 3 叠加。编码节点注释已记：错用 runner `callback_url` 会 404。INGEST-02 纪律：完成锚点不能挂在「绝不能 5xx」的容器回调上。

**Why it happens:**
跨进程契约（server ↔ runner ↔ task）三套代码；测试用 mock callback 直调 service，不模拟「Runner 已 TASK_COMPLETED、业务 callback 未到」。MCP 诊断面缺失时，外部 Agent 只能盲轮询或重派。

**How to avoid:**
公开诊断工具：按 `session_id` / `task_id` 返回 stage、逐仓 task、最后 RunnerEvent、callback 是否落地、lease 持有者、可安全 `retry`/`recover` 的动作。恢复扫描必须可被 MCP 触发或至少可观测（计数进 gauge）。新回调路径 AST/契约测试：禁止 runner 中转 URL。主完成锚点继续放在 MR 已知/业务状态机，callback 只是加速。

**Warning signs:**
- `RepoResearchTask` RUNNING 且已有 `TASK_COMPLETED`。
- 无 `completed_without_callback` 指标却有僵尸会话。
- MCP 只有 `start_*` 没有「为何卡住」。

**Phase to address:**
P5 诊断与恢复。P7 canary 必须包含「杀掉业务 callback、仍能靠 Runner 事件收敛」。

---

### Pitfall 5: CAS 只挡住写坏，挡不住「看起来失败其实已确认」

**What goes wrong:**
蓝图生命周期、`SddSpec`、确认门快照都用条件更新。REST 确认后若续驱失败，视图纪律是 **动作已落库、响应仍成功、续驱失败只打日志**（`_aresume`）。MCP 若把续驱失败映射成 tool error，Agent 会再点确认；第二次因已锁定走 stub `{"repos": []}`（v0.20 tech_debt：锁定后 stage_state 回退恒空）。反过来：Agent 超时发生在 CAS 成功之后，查询若只看 HTTP 错误会以为未确认。`expected_version` / `content_hash` 若不随公开 MCP 暴露，终审会覆盖人工块或打到过期版本。

**Why it happens:**
「服务端状态机很严」被当成「客户端不必处理 409」。MCP 工具常省略 version 参数以「简化 Agent」。

**How to avoid:**
公开确认/审批/finding 处置一律带 CAS 令牌（`artifact_version_id` + `content_hash` 或 `updated_at`）。冲突返回 409 + 当前观察，**禁止当 400 让模型改参数重放同一变迁**。get 工具必须能回答「门是否已过、锁是否已落、续驱是否还在跑」。动作成功与编排推进分成两个字段，避免「确认了但 stage 没动」被当成失败。

**Warning signs:**
- `approve_technical_blueprint` 无 version 字段。
- 确认后门的 `dispatch_plans` 归零并开阻塞线程（回退分支失效的可见态）。
- 测试只断言状态码，不断言第二次确认是 no-op/conflict。

**Phase to address:**
P2 HITL 控制面与 P4 未知结果协议一起做。不要在 P2 先公开无版本的 approve。

---

### Pitfall 6: 跳过仓库确认门 / finding 走错通道 / 无最终审批 —— 编码吃未审蓝图

**What goes wrong:**
阶段 1 出口硬门、AI review finding 的 `resolve`/`dismiss`（**禁止作答通道**）、人类终审，是 RELY-01 / FLOW 的安全内核。当前公开 MCP 有澄清作答与（服务端）`approve`/`request_changes`，**缺仓库确认门与 finding 处置**；分仓 `RepoPlan` 发起/查询/重试/读产物仍偏内部 REST。Agent 会：用 `answer_blueprint_clarification` 把 BLOCKER 推到 `answered`（绕开 `reason` 与留痕）；或走 `create_coding_plan` 旧执行桥在蓝图未 `confirmed` 时开工；或只跑 sandbox `apply_repo_association` 当「确认门」。npm 连已有的 approve 都调不到（Pitfall 1）。看起来链路工具很多，安全门全在 SPA。

**Why it happens:**
v0.20 把 HITL 做在 REST + 前端；MCP 先做「能建会话和澄清」。GATE-01 曾把 `DONE` 映射成 completed 喂 `ai_coding`。实现者复制 clarifications 通道给 finding。

**How to avoid:**
公开 MCP 最小闭集：`confirm_blueprint_repos`（硬门）、`resolve|dismiss_blueprint_finding`、`approve|request_changes`（CAS）、只读 `get` 含 pending gates。编码/MR 工具 fail-closed：未确认蓝图 → 稳定机器码，零写入。守卫测试：finding 不得出现在 `answer_*` 可接受的 thread 类型里。分仓计划工具与 HITL 同里程碑公开，否则 Agent 在确认后仍卡在内部 API。

**Warning signs:**
- Agent trace 里 `create_coding_plan` 早于 `confirmed`。
- finding 行 `status=answered` 且无 `dismiss/resolve` actor。
- 文档写「MCP 可完成交接」但工具列表无 repo confirmation。

**Phase to address:**
P2 控制面；P3 分仓方案/合成。二者缺一则「全链路」仍断。

---

### Pitfall 7: 信息预言机与角色/项目范围 —— 404/400 分裂、仓库 ACL 名存实亡

**What goes wrong:**
蓝图闸 `_aassert_project_scope`：越权中性 **404**；`meta.project_id` 非空但非法 **400**（v0.20 明确记为存在性预言机：攻击者可区分「坏 UUID 格式的项目绑定」与「没有这份蓝图」）。MCP 复用同源闸，暴露面从 REST 扩到 PAT 自动化调用，枚举成本下降。平台级 `RepositoryPermission` 是「任意登录用户可读任意存在的仓库」，MCP `search_rag_chunks` / `grep_repository` / `get_repository_file` 继承该口径 —— 外部 Agent 的 PAT 只要是登录用户，即可当全库 oracle。跨仓 impact 曾把无权仓的计数当规模预言机（已在图工具侧折叠，MCP 新工具容易再引入）。exclusion 路径必须与「不存在」同出口，否则成敏感文件预言机。

**Why it happens:**
400 对调试更友好；实现者在 MCP 上返回 serializer 校验细节。PAT = 用户全量 RBAC（v0.2 刻意不做细 scope）。

**How to avoid:**
四语义契约整体改版（不存在 / 无权限 / 非法 id / 校验失败）在 REST+MCP **同一套状态码**，非法 project_id 也走中性 404。新 MCP 读工具：项目绑定对象按 ProjectMember fail-closed；全库 grep 保持显式 opt-in 且审计。不要在本里程碑假装做出仓库 ACL；但文档与 canary 必须写明威胁模型。exclusion 测试继续锁「同出口」。

**Warning signs:**
- 同一 UUID 对非成员 400、对成员 200。
- 新工具错误体含 `project_id is not a valid UUID` vs `not found` 分流。
- PAT 文档承诺「项目级隔离」但实现只 `IsAuthenticated`。

**Phase to address:**
P6。P2 每加一个写门都必须走同源闸，禁止复制第四份。

---

### Pitfall 8: 密钥与交接包泄漏 —— PAT、handoff 文件、error=str(exc)

**What goes wrong:**
stdio 层纪律：PAT 不进返回文本/日志；401 文案也不回显 token。但仍有洞：`get_confirmed_blueprint_handoff` 把完整 JSON 写到 `tmpdir/friday-mcp-handoffs/`（mode 0o600），Agent 若把 `handoff_file` 路径贴进对话或再 `read_file` 进模型上下文，等于把方案+可能的内部引用送进 LLM。HTTP 错误体 `bodyText.slice(0, 2000)` 可能含上游异常；平台债 `redact_secrets_in_text` 不覆盖数据库连接串，`error=str(exc)` 二十余处仍在。容器总线 `report_blueprint_context` 依赖 service 脱敏，schema 漂移时原文可进总线。`npx` 配置文件里的 PAT 与 Cursor mcp.json 是本机新泄漏面。

**Why it happens:**
交接包为防模型改写正文而落地文件，是正确动机；未定义「文件不得再被模型ingest」。观测 best-effort 与「异常原文方便排障」冲突。

**How to avoid:**
handoff 工具响应只给路径+hash+任务摘要，skills 明确禁止把文件内容贴回对话。错误体继续脱敏；MCP view 出站统一 `redact_secrets_in_text`。新增工具的异常测试用带 `postgres://` / `sk-` 的假异常，断言日志与 tool 文本已打码。PAT 轮换路径写进 doctor。

**Warning signs:**
- tool result 含 `friday_pat_` 或完整 markdown 蓝图。
- canary 日志能 grep 到连接串。
- 交接测试断言「返回完整 content」而非「落盘+摘要」。

**Phase to address:**
P6；P1 改 handoff 客户端时不要为「方便」改回内联全文。

---

### Pitfall 9: 轮询风暴 —— get 当 busy-loop，打穿编排与 Qdrant

**What goes wrong:**
`get_feature_tech_plan`、`get_repo_research`、`get_technical_blueprint`、`get_coding_execution` 被设计成轮询点。Agent 在 120s 墙内每 1s 打一次；多会话 × 多仓调研会把 `adrive`、lease 心跳、Qdrant 检索打满。读工具若内部触发「顺便续驱」或重算路由，轮询变成写放大。`grep_repository all_repositories=true` 被 Agent 当探活。

**Why it happens:**
没有 `Retry-After` / `poll_after_ms` 字段；也没有 MCP 级 rate limit（规范要求服务端限流，本仓工具面基本未做）。

**How to avoid:**
所有长任务 get 返回 `status` + `poll_after_ms`（随 age 指数退避）+ `terminal` 布尔。文档/skill 写死最小间隔。get **纯读**，续驱只走 callback/worker/显式 recover 工具。限流按 PAT + tool 维度，超限 429 且不可用「换个参数」绕过。高频路径 `category=sampling`，禁止 INFO 刷屏。

**Warning signs:**
- 单会话每秒多次 `get_technical_blueprint`。
- get 处理函数里调用 `adrive` / `dispatch`。
- 没有 429 测试。

**Phase to address:**
P4 契约带 poll 字段；P5 诊断工具同样要退避。P7 canary 盯 QPS。

---

### Pitfall 10: 合成测试绿、真依赖 canary 缺席 —— 发布后才发现回调/飞书/Qdrant 洞

**What goes wrong:**
v0.19–v0.23 反复：27 项人工验收零执行、`live_space` 默认 skip、IMPACT-03 无生产跨仓样本、多仓 wave 真容器 E2E 挂账、飞书导出只验 markdown 不验 `markdown_to_blocks`。MCP「全链路」若仍用 mock runner + 空 Qdrant + 无飞书交互，会漏：索引为空时路由恒降级、callback 签名、CardKit 交互、handoff 文件、PAT 真鉴权。更糟的是把 skip 的 live 标记当「已覆盖」。

**Why it happens:**
CI 无凭证/无 Docker socket 策略；Nyquist VALIDATION 长期 draft。实现者用「结构断言 + vitest」代替挂载宿主上的真实点击（v0.19 教训：`RoutingDecisionPanel` 零挂载仍判绿）。

**How to avoid:**
本里程碑 canary **显式、默认可 skip，但 skip 不得叫 passed**：真实 Qdrant 检索、runner 起容器、**故意丢掉一次业务 callback**、飞书一次交互、最终 `get_confirmed_blueprint_handoff` 落盘校验 hash。报告分 `synthetic` / `live` 两栏。禁止用叶子组件测试冒充 Agent 工具链。

**Warning signs:**
- `@pytest.mark.live_*` 全 skip 且审计写 Complete。
- canary 不包含 timeout→get 对账、callback loss、跨 npm/HTTP 同一工具名。
- 只 curl 内部 URL，不经 stdio `CallTool`。

**Phase to address:**
P7。P1–P6 的自动化仍要绿；P7 是发布门，不是「有空再跑」。

---

### Pitfall 11: 发版与版本谎言 —— `npx -y` 拉最新、SERVER_VERSION 0.2.0、包 0.6.0、实例 API 另一代

**What goes wrong:**
`register.ts` 默认 `npx -y @friday-ai-codes/mcp`（**永远最新**）。本仓 `mcp/package.json` version `0.6.0`，stdio `SERVER_VERSION = '0.2.0'`。用户 Friday 实例可能停在旧 snapshot。新客户端调未部署的 `approve_*` → HTTP 404；旧客户端对已部署实例则看不到新工具。skills 文档与 snapshot 对齐但用户装的是 registry 旧 tarball。子模块指针、npm publish、server 镜像 **三轨版本号** 无人钉扎。GSD 里程碑刻意不打 git tag（发布轨 `v*`），更容易让「v0.26.0 研究」与用户装的包对不上。

**Why it happens:**
stdio 版本忘随包 bump；文档推荐 `-y` 图省事；对齐测试只跑 worktree 源码不跑 published dist。

**How to avoid:**
`SERVER_VERSION` == `package.json` version；`doctor` 调实例 `schema`/`health` 比对工具名集合，打印 diff。文档给 **版本钉扎**（`npx -y @friday-ai-codes/mcp@<ver>`）与「server 最低版本」。CI：alignment 在 submodule 必 checkout；publish 作业跑同一守卫。HTTP 404 工具名要回「实例过旧或客户端过新」而不是泛失败。

**Warning signs:**
- doctor 只测 `/health` 200。
- changelog 写 55 工具，npm latest 仍 43。
- `SERVER_VERSION` 与 `package.json` 不一致（现状即是）。

**Phase to address:**
P1 修谎言计数与 SERVER_VERSION；P7 把 doctor/canary 当发布门。

---

### Pitfall 12: 「结构合法、语义为空」的静默降级 —— Agent 以为拿到了方案

**What goes wrong:**
G3 类事故：MCP 映射读 `content['execution_plan']`，blueprint/v1 无该顶层键 → `repository_tasks: []`，HTTP 200。markdown 用 v0 渲染器得到空文档仍回写飞书。`get_confirmed_blueprint_handoff` 若在未确认状态返回带水印或不返回，客户端若只看 `current_status` 字符串 loosely 匹配会交错误包。`partial` + 空 `content` 被模型当成「没有仓库」。这比硬错误更危险：不可观测、Agent 继续往下编码。

**Why it happens:**
「兼容旧键 / fail-soft 渲染」没有 `truncated`/`empty_reason`/`schema_version` 守卫。测试断言键集合 ⊆ snapshot，不断言「确认后 tasks 非空」。

**How to avoid:**
响应加 `schema_version` + `completeness`（empty/partial/complete）+ 空时必填 `empty_reason`。snapshot 测试加语义：confirmed handoff 在 fixture 下 `repository_tasks` 长度与蓝图仓集一致。禁止 200 + 空主载荷表示失败。

**Warning signs:**
- 200 且 `repository_tasks == []` 同时 `status=completed`。
- 飞书文档只有水印没有六段。
- 映射函数仍 `content.get("execution_plan")` 无 blueprint 分支。

**Phase to address:**
P1 载荷映射；P2/P3 每个新 get 都要 completeness。P7 交接 canary 锁 hash 与 task 数。

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| mcp 子模块未 checkout 则 skip 对齐测试 | 本地少 git submodule | 全里程碑假绿，npm 永久漂 | **never**（CI 必须 fail；本地 skip 需显式 env） |
| 把工具数写死为 43 | 测试好写 | 与 snapshot 脱钩后仍绿 | **never** |
| 全局 120s fetch timeout | stdio 不挂死 | 所有长写变 unknown + 重试放大 | 仅只读探活；写路径必须 job |
| `drive_lease` fail-open | DB 抖动编排不停 | 重复 LLM/重复线程 | 可保留，但必须有重复度量与 MCP 可见 |
| finding 复用 clarifications 通道 | 少一个工具 | 绕开 reason/CAS，确认门失效 | **never** |
| live_* 默认 skip 当 Complete | CI 稳定 | 生产洞进审计 passed | skip 可以，status 必须 live_unrun |
| `npx -y` 不钉版本 | 安装短 | 实例/客户端交叉 404 | 文档与 register 必须钉或 doctor 比对 |
| 同步 `adrive` 塞进一次 tools/call | Agent 一次拿终稿 | 必撞 120s | 仅本地 debug 开关，默认异步 |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| npm stdio MCP | 只改服务端 + snapshot | 同步 `FRIDAY_TOOLS` + annotations + 禁止 skip 的集合差测试 |
| HTTP `/api/mcp/tools/*/` | 当成「完整产品面」验收 | 外部 Agent 主路径是 stdio；HTTP 是容器/内部。两面工具名必须相等 |
| Runner / task callback | 完成挂在 callback；失败返回 5xx | 业务状态机 + RunnerEvent 对账；callback 加速；永不 5xx 风暴 |
| 飞书 CardKit / 工作项 | 只测聚合读，不测交互回调 | canary 含一次真实或录制回放的门动作 |
| Qdrant | mock 空集合当「无结果」 | live canary 断言 ranked_repos / chunks 非空（已知索引仓） |
| GitHub/GitLab MR | 超时后重调 `create_merge_request` | idempotency + 按 branch 查询已有 MR |
| PAT | 工具错误回显 Authorization | 401 固定文案；doctor 只显示指纹 |
| skills 文档 | ⊆ snapshot 但 ⊈ npm | 文档工具名必须 ⊆ **已发布** 客户端白名单 |
| durable / Procrastinate | 当 exactly-once | at-least-once + 幂等；MCP job 同样 |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Agent 1s 轮询 get_* | worker CPU、lease 心跳写放大 | `poll_after_ms` + 429 | 十几个并行蓝图会话即卡 scheduler |
| 超时同步编排 | 连接占满、无进度 | 立即 accepted + 后台 drive | 单次调研 >120s 必现 |
| `all_repositories` grep/RAG | Qdrant/磁盘打满 | 默认单仓；跨仓 opt-in + max_repos | 数百仓实例 |
| 电平 barrier 重复 drive | 审查跑 7 遍 | lease + 边沿触发 + 幂等落库 | 多仓并行回调汇聚时 |
| 交接包塞进 tool JSON | 上下文爆、模型改写 | 落盘 + 摘要 | 六段蓝图 + execution_plan 已超上下文 |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| 非法 `project_id` 返回 400 | 蓝图/项目存在性预言机 | 与越权同一中性 404 |
| PAT=全仓库可读当「项目 MCP」 | 跨组代码与需求泄漏 | 文档威胁模型；绑定项目的对象强制成员；全库检索审计 |
| finding 经 answer 通道 | 未审 BLOCKER 当已处理 → 编码 | 通道拆分 + 测试锁 thread type |
| 未确认蓝图可 `execute_*` / 建 MR | 违反 RELY-01 | fail-closed 机器码 + 零写入 |
| 超时后重放写工具 | 重复 PR/飞书文档/容器 | 幂等键 + unknown 协议 |
| 错误体/日志带 secret | PAT、DB URL、Git token | 出站统一 redact；连接串纳入规则 |
| handoff 文件被模型回读 | 敏感引用进第三方模型 | skill 禁止；响应不内联正文 |
| MCP 限流缺失 | PAT 被盗后自动化枚举 | 每 token QPS；写工具更严 |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Cursor 报未知工具，HTTP 却通 | 「MCP 坏了」与「其实没装齐」分不清 | doctor 打印三方 diff；安装钉版本 |
| 超时 isError 无下一步 | Agent 编造失败原因或狂重试 | `outcome_unknown` + 查询指令 |
| 确认成功但流程不走 | 用户连点确认，第二次空仓 | 响应区分 action_committed vs drive_pending |
| 空 `repository_tasks` 当完成 | 下游空编码 | completeness + 空原因 |
| 43 vs 55 无用户可见说明 | 技能文档教了调不到的工具 | 文档只列出客户端真实白名单 |

## "Looks Done But Isn't" Checklist

- [ ] **工具面对齐：** `urls` == snapshot == `FRIDAY_TOOLS` == annotations；CI 在 mcp 未 checkout 时 **失败** 而非 skip；npm 测试无写死 43。
- [ ] **字段契约：** 每个公开工具 request/response 键三面一致，不只新工具。
- [ ] **HITL 闭集：** 仓库确认、finding resolve/dismiss、终审 approve/request_changes、CAS 版本字段，均在 **stdio** 可调用。
- [ ] **分仓方案：** 发起/查询/重试/读产物不是「仅 REST」。
- [ ] **长任务：** 写路径 accepted+job；stdio 超时 = unknown；同键重试不复制副作用。
- [ ] **诊断：** stage、逐仓 task、callback/Runner 对账、lease、可 recover 动作可经 MCP 读到。
- [ ] **空载荷：** confirmed/completed 不得 200+空 tasks；必有 `empty_reason`/`schema_version`。
- [ ] **范围闸：** MCP 与 REST 同源；无第四份；非法 id 非预言机。
- [ ] **限流与 poll_after_ms：** get 纯读；busy-loop 429。
- [ ] **脱敏：** 超时/502 文本、handoff 摘要、日志无 PAT/连接串。
- [ ] **版本：** `SERVER_VERSION` == 包版本；doctor 比对实例工具集；文档非无钉 `npx -y`。
- [ ] **Canary：** Qdrant + runner + 丢 callback + 飞书 + handoff hash；skip ≠ passed。
- [ ] **文档/skills：** 引用 ⊆ **客户端**白名单，不只 ⊆ snapshot。
- [ ] **测试债：** `test_schema_snapshot` 独立字面量仍与 urls 同步更新，避免「改测试当改契约」。

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| npm/服务端工具漂 | MEDIUM | 补白名单、发 mcp 补丁版、doctor 提示升级；旧实例返回工具级 404 说明 |
| 120s 后重复执行 | HIGH | 按 idempotency/业务键对账 MR/会话；关停重复容器；泄漏的 PR 标 superceded |
| 回调丢失、会话卡住 | MEDIUM | 跑 `areconcile_stalled_*`；用 RunnerEvent 收敛；MCP recover 重入 drive |
| CAS 后超时误判未确认 | LOW | get 观察门状态；已锁定则禁止再确认，只 recover drive |
| finding 被 clarifications 吃掉 | HIGH | 人工在 SPA 纠状态；代码修通道；已编码分支暂停 |
| 轮询打满 | LOW | 429 + 临时降并发；修 skill 间隔 |
| 密钥进模型/日志 | HIGH | 吊销 PAT、轮换 Git/飞书、红线审计导出 |
| 客户端/实例版本交叉 | LOW | 钉版本或升级实例；doctor diff |
| 空 payload 已回写飞书 | MEDIUM | 重渲 blueprint markdown 覆盖导出；修映射后重跑 get |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| 静态白名单 55 vs 43、skip 假绿、写死 43 | P1 契约三面对齐 | CI 无 skip；集合差空；stdio ListTools 与 snapshot 相等 |
| 字段/文档漂移、空 execution_plan 映射 | P1 | 独立字面量 snapshot；confirmed fixture tasks 非空；skills ⊆ 客户端 |
| SERVER_VERSION 与包版本、npx 无钉 | P1 + P7 | 版本字符串相等；doctor 打印 diff；文档含 `@version` |
| 缺确认门/finding/终审；作答通道误用 | P2 公开 HITL | 四工具在 stdio；finding 不能 answer；未确认 execute 零写入 |
| 分仓计划/合成仅内部 | P3 | MCP 可 start/get/retry/read artifact |
| 120s unknown、无 job、盲目重试 | P4 | abort 后 get 恢复；同键副作用=1；写工具无同步 adrive |
| 幂等键/pending 409 过早 | P4 | 并发 pending 回 in-progress；参数漂移 conflict |
| 回调丢失、电平 barrier、无诊断 | P5 | 丢 callback canary 收敛；诊断字段齐全；重复 drive 有度量 |
| CAS 与「动作成功/续驱失败」混淆 | P2 + P4 | 二次确认 conflict/noop；响应分字段 |
| 预言机、项目范围、全库 oracle | P6 | 非法 id 中性 404；同源闸无副本；exclusion 同出口 |
| PAT/handoff/异常明文 | P6 | 假 secret 测试；handoff 非内联 |
| 轮询风暴 | P4 + P5 | poll_after_ms；get 无 adrive；429 |
| 合成绿 live 缺席 | P7 | 双栏报告；callback loss + 飞书 + Qdrant + handoff hash |
| 发版交叉 | P7 | publish 跑 alignment；doctor 为发布门 |

## Sources

- 本仓：`mcp/src/server.ts`（120s `AbortSignal.timeout`、未知工具拒绝、handoff 落盘）、`mcp/src/tools.ts`（43 工具静态白名单）、`mcp/tests/server.test.ts`（锁 43）、`mcp/package.json`（0.6.0）vs `SERVER_VERSION`（0.2.0）、`mcp/src/register.ts`（`npx -y`）
- 本仓：`server/mcp_tools/urls.py` + `serializers.TOOL_SCHEMA_SNAPSHOT`（~55）、`tests/mcp_tools/test_mcp_package_alignment.py`（子模块缺失 skip）、`test_schema_snapshot.py`、`test_skills_snapshot_guard.py`
- 本仓：`server/services/process_runtime/drive_lease.py`（并发审查跑 7 遍、fail-open）、`blueprint_resume.py`（`completed_without_structured_result_callback`）、`orchestration_delegate.py`（G3 空载荷/跳过澄清同步 drive）
- 本仓：`delivery/api/blueprint_review_views.py`（范围闸 404 vs 非法 id 400、续驱失败不改动作结果）
- 本仓审计：`.planning/milestones/v0.20.0-MILESTONE-AUDIT.md`（npm 四工具漂、确认门 stub、预言机）；`.planning/PROJECT.md`（v0.26.0 目标、RELY-01、finding 禁止作答通道、at-least-once）
- MCP 规范：<https://modelcontextprotocol.io/specification/2026-07-28/server/tools>（超时、取消 best-effort、tool execution error 给模型重试、服务端须鉴权限流）
- 未知结果与幂等：<https://rokoss21.tech/en/posts/uncertain-tool-outcomes/>；生产 MCP 恢复分类 <https://www.thepromptbuddy.com/insights/mcp-servers-in-production-authentication-permissions-logging-failure-recovery>；幂等 pending 不得过早 409（HN/业界共识，LOW–MEDIUM，与 AWS idempotency 指南同构）

---
*Pitfalls research for: Friday AI 公开 MCP 全链路与稳定性*
*Researched: 2026-09-14*
