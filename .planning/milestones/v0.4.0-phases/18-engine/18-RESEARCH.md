# Phase 18: 执行引擎状态机修复 - Research

**Researched:** 2026-06-13
**Domain:** Django 异步工作流引擎调度语义（纯内部代码改造，零新依赖）
**Confidence:** HIGH（全部关键结论来自本仓库代码逐行核实，附文件行号）

## Summary

本阶段是执行引擎运行态状态机的契约修复。研究确认了五条故障链的精确根因，全部 `[VERIFIED: codebase]`：

1. **ENG-01**：主循环对 `waiting_event` 节点"从 pending 移除且不加回"（scheduler.py:822-825），末端等待节点会让 `while pending_nodes` 直接退出 → `amark_completed`（:842-851）——这就是"显示完成实际没跑完"的精确根因。有下游时则永久 5s 轮询（`all_blocked` 检查 :639-650 永远为 False，因为下游 NE 状态是 PENDING 而非 waiting）——`amark_suspended`（:659）在 waiting_event 场景**实际不可达**。更严重的是：SubAgent 容器回调路径（subagent/api/callbacks.py:177-260）只往 output_data 写 `_resume_from_callback` 标记后调 `_continue_after_node`，但该函数不会重新执行节点本身，且下游依赖检查（:1517-1532）要求 dep 为 COMPLETED（coding 节点还是 WAITING_EVENT）——容器完成后的自动续跑链路静态分析判定为**断裂**。
2. **ENG-02**：主循环就绪判定（:565-586）完全不看 handle——条件节点完成后**所有分支同时就绪并执行**；回调续跑路径（:1411-1420）按 `next_handle × source_handle` 路由但**不标记未选中分支 skipped**（残留 PENDING → `_check_execution_complete` 永不满足 → 永远 running）。两条路径是两套独立实现。
3. **ENG-03**：三种触发方式经 TriggerDispatcher 都已把 `trigger_data={"raw_payload": ...}` 写入 WorkflowExecution（dispatcher.py:107-115），但 `_execute_node` 构造 ExecutionContext 时**不传 trigger_data**（scheduler.py:928-938）——`{{trigger.*}}` 在所有真实执行中永远解析空 dict。修复主体是一行注入 + 形状统一。
4. **ENG-04**：主循环已有死锁判定（:679-697）但错误信息只列节点名不列依赖；回调续跑路径完全没有死锁检测。
5. **ENG-05**：`target_handle` 全链路落库/序列化/快照齐备，但 DAG 构建丢弃它（dag.py:64,89 只记 source id），`_collect_inputs`（:1093-1107）扁平合并所有上游输出——端口名存实亡。现状能跑全靠上游节点"输出键碰巧等于下游端口名"（plan_generation 输出含顶层 `plan` 键）+ 下游兜底（code_review 的 merge_requests 扁平兼容分支）。

**Primary recommendation:** 抽取 `server/workflows/engine/routing.py`（纯函数：handle 路由 + skipped 级联 + 死锁诊断 + 边感知输入收集），主循环与回调续跑共用；回调续跑改为"标记节点终态 → 重建状态重入 `_run_execution`"以最大化两路径语义一致（需执行级互斥防双循环并发）；`_execute_node` 一行注入 `trigger_data`。

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### waiting_event 完成判定（ENG-01）
- 调度主循环结束时若存在 waiting_event 节点：执行整体状态必须为 suspended，绝不判 completed
- suspended 状态通过现有 API 序列化与 WS hooks（execution_suspended 事件已存在）对前端真实可见；本阶段保证后端状态与事件正确，前端展示细节归 Phase 21
- 回调续跑（事件到达）后从挂起点恢复调度，恢复后语义与主循环一致

#### 分支路由一致性（ENG-02）
- 以 `next_handle` × 边 `source_handle` 匹配为唯一路由语义；调度主循环与回调续跑两条路径共用同一路由函数（消除重复实现）
- 未选中分支的下游节点标记 skipped（级联：仅当节点所有入边都来自 skipped/未选中路径时才 skip；汇合节点只要有一条活路径就执行）
- skipped 是终态之一，参与"执行完成"判定

#### trigger_data 注入（ENG-03）
- 任意触发方式（飞书事件、手动、API）创建 WorkflowExecution 时统一写入 trigger_data；手动/API 触发缺省注入 `{source: "manual"|"api", ...payload}`
- `{{trigger.*}}` 解析复用 Phase 17 定稿的 template_resolver 路径与失败语义（trigger 前缀字段缺失维持现状宽松语义——Phase 17 已锁定，不在本阶段扩大严格化）

#### 死锁诊断（ENG-04）
- 判定条件：有 pending 节点但无 ready 节点且无 waiting/running 节点 → 执行明确转 failed
- 错误信息列出每个 pending 节点在等待哪些未满足的依赖（节点 short_id + 缺失的上游/handle），结构化写入 execution.error_message（与 Phase 17 错误结构风格一致）
- 不做自动恢复/破环，只诊断报错

#### target_handle 语义（ENG-05）
- 决策：保留字段并实现其语义——节点输入收集时按入边 target_handle 将上游输出归集到对应输入端口名下（与 Phase 19 的 NodePort 定义对齐）；若实现成本超预期，回退方案为显式移除字段并统一文档/前端，但优先实现
- 调度、分支、死锁、等待四类引擎核心路径必须有自动化回归测试（pytest，server/tests/workflows/）

### Claude's Discretion
- 路由函数抽取位置（scheduler 内部函数 vs engine 子模块）
- skipped 级联算法实现细节
- 测试夹具组织方式

### Deferred Ideas (OUT OF SCOPE)
- 执行级重试/断点续跑增强（非本阶段需求）
- 前端 suspended 态 UI 设计（Phase 21）
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ENG-01 | waiting_event 不被误判 completed；suspended 对前端真实可见 | 根因三处全定位（§1）：末端等待→误判 completed、有下游→永久轮询不挂起、容器回调续跑链断裂；`execution_suspended` hook 事件与 WS 广播已验证存在（hooks/base.py:34、builtin.py:38-75） |
| ENG-02 | 主循环与回调续跑均按 next_handle × source_handle 路由，未选中分支 skipped | 两路径漂移逐行定位（§2）；`dag.get_successors(node_id, handle)` 已可复用（dag.py:189-196）；skipped 级联需新建（现仅有"前置失败→skip"ANY 语义 :576-583） |
| ENG-03 | 所有触发方式下 {{trigger.*}} 可解析 | 写入侧已统一（dispatcher.py:112），缺口唯一在读取侧 `_execute_node` 不传 trigger_data（§3）；resolver trigger 前缀宽松语义已定稿（template_resolver.py:219-220） |
| ENG-04 | 死锁明确转 failed 并附结构化诊断 | 现有判定 :679-697 仅主循环、仅节点名；诊断所需的 forward_incoming/handle 信息均在 DAG 中可得（§4）；Phase 17 结构化 error_message 编码约定可直接复用 |
| ENG-05 | target_handle 语义落地（或显式移除）+ 四类路径回归测试 | target_handle 全链路数据完备仅引擎不消费（§5）；两个真实节点链（plan→coding、coding→review）的输入端口期望已核实，给出非破坏性归集规则（Pattern 5）；现有引擎测试覆盖盲区清单（§6） |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 完成/挂起/死锁判定 | Backend（engine/scheduler） | — | 执行态唯一事实源 |
| handle 路由 + skipped 级联 | Backend（engine 新路由模块） | — | 主循环与回调续跑共用，纯函数可测 |
| trigger_data 写入 | Backend（TriggerDispatcher / start_execution） | — | 触发入口统一收口 |
| trigger_data 读取（{{trigger.*}}） | Backend（_execute_node → ExecutionContext → template_resolver） | — | Phase 17 resolver 已就绪，只缺注入 |
| 边感知输入收集（target_handle） | Backend（_collect_inputs，两路径共用） | Phase 19 对齐 NodePort 定义 | 输入端口语义归引擎 |
| suspended 可见性 | Backend（hooks WS 广播 + DRF serializer status 字段） | Phase 21 前端展示 | 事件与字段已存在，本阶段保证状态真实 |

## 现状链路（核心调查结论，全部 [VERIFIED: codebase]）

### §1 ENG-01：waiting_event / 完成判定 / 挂起的完整故障链

**主循环状态机**（`_run_execution`，scheduler.py:505-859）用五个内存集合驱动：`pending/completed/failed/skipped/tolerated`，节点被调度时即从 pending 移除（:783）。

1. **waiting_event 末端节点 → 误判 completed**：节点返回 waiting_event 时"不加回 pending"（:822-825，注释声称"循环会检测到 waiting 节点并挂起"）。若它无下游（或其余节点已终态），`while pending_nodes` 条件为假直接退出 → failed_nodes 空 → `amark_completed`（:842-851）。NodeExecution 永远停在 WAITING_EVENT，而执行显示 completed。
2. **waiting_event 有下游 → 永久轮询，挂起不可达**：下游节点仍在 pending 但其 NE 状态是 PENDING；`all_blocked` 检查（:639-650）遍历 pending 节点查 NE 状态，要求**全部**处于 WAITING_* 才挂起——PENDING ≠ waiting → all_blocked 恒 False → 进入 5s 轮询分支（:663-677）。执行状态停留 running，线程永不退出；服务重启后该执行变成"无限 running"僵尸。
3. **轮询刷新分支的双键缺失**：:668-676 轮询发现 waiting 节点 COMPLETED 后 `node_outputs[str(ne.node_id)] = ne.output_data`——**只写 UUID 键不写 short_id 键**（主路径 :798-802 和 `_collect_all_outputs` :1534-1554 都是双键），该路径推进后下游 `{{nodes.<short_id>.*}}` 解析必失败（Phase 17 严格语义下直接报错）。
4. **waiting_approval 热循环**：waiting_approval 节点被**加回 pending**（:819-821），下一轮其前置依赖仍 completed → 再次 ready → `_execute_node` 重跑 → `amark_started` 把 WAITING_APPROVAL 打回 RUNNING → 节点重发审批通知（approval.py:94-124 无幂等保护）→ 又返回 waiting_approval——**无 sleep 的无限热循环**，且与 `approve_node` 回调竞态（回调 amark_completed 后主循环又覆盖状态）。
5. **`amark_suspended` 的实际可达性**：仅当"所有 pending 节点的 NE 都处于 waiting 状态"——即只有 waiting_approval 末端节点场景（被加回 pending 且自身状态 waiting）。waiting_event 场景永远到不了。
6. **容器回调续跑链路断裂**：`subagent/api/callbacks.py:177-260 _schedule_workflow_resume` 在所有 SubAgentSession 终态后只做两件事：往 NE.output_data 写 `_resume_from_callback=True` / `_session_results`，然后 `_continue_after_node`。但 ai_coding 的恢复逻辑 `_resume_after_containers`（coding.py:226,507）只在 `execute()` 开头消费该标记——**没有任何代码重新调用 execute()**：`_continue_after_node` 不重跑节点本身，其后继的 `_check_dependencies_ready`（:1517-1532）要求 dep COMPLETED 而 coding 节点还是 WAITING_EVENT → 后继不执行；若 coding 是末端 → `_check_execution_complete` 因 waiting=1 不完成。对照可工作的同类路径——agent 会话路径（tasks/agent_tasks.py:240-264）先 `amark_completed` 再 `_continue_after_node`；分支确认路径（feishu/callbacks/coding_callback.py:203-325）**手动重置 NE 为 RUNNING、手动构建 ExecutionContext、手动重跑 execute() 并复刻 `_next_handle` 写入逻辑**——第三套迷你调度器实现（其 ExecutionContext `previous_outputs={}` 且无 trigger_data，又一处漂移源）。
7. **挂起可见性基础设施已齐备**：`execution_suspended` 在 HookManager.EVENTS（hooks/base.py:34）；`WebSocketBroadcastHook` 对全部事件注册并广播 `{event, execution_id, status}`（builtin.py:38-75，scheduler.py:97-99 注册）；`mark_suspended/amark_suspended` 模型方法齐备（execution.py:307-315）。各回调已有 SUSPENDED→RUNNING 翻转（coding_callback.py:251-253、chat_question_callback.py:272-274、feishu/views.py:1012-1014）。缺的只是"挂起判定正确发生"。

**恢复路径全景**（统一路由函数必须同时服务两种恢复形态）：

| 恢复入口 | 恢复形态 | 现状 |
|---|---|---|
| `approve_node`/`reject_node`（scheduler.py:1208-1327） | 标记 completed（写 `_next_handle: approved/rejected`）→ `_continue_after_node` | 可用，handle 路由正确 |
| wait_feishu 事件匹配（feishu/views.py:1002-1029） | 手写 status=COMPLETED + output_data → `_continue_after_node` | 可用（绕过 amark_completed，completed_nodes 手动 +1） |
| chat_question 末轮（chat_question_callback.py:262-309） | 经 `approve_node` | 可用 |
| agent 会话完成（agent_tasks.py:212-272） | `amark_completed` → `_continue_after_node`；失败走 `_handle_node_failure`（一律 fail 整个执行，无 on_error 策略，代码内有 TODO :1468-1470） | 可用 |
| 容器全部终态（callbacks.py:177-260） | 仅写恢复标记 → `_continue_after_node` | **断裂**（需重跑节点才能消费标记） |
| 分支确认（coding_callback.py:203-325） | 手动重跑节点（第三套实现） | 可用但漂移 |
| 人工 skip-wait / resume-wait（workflows/api/views.py:1964-2042） | 手写 COMPLETED → `_continue_after_node` | 可用（运维逃生门） |

### §2 ENG-02：两条路由路径的精确漂移清单

| 维度 | 主循环 `_run_execution` | 回调续跑 `_continue_after_node` |
|------|------------------------|--------------------------------|
| 分支路由 | **完全无视 handle**：就绪判定只看 `forward_incoming` 集合（:565-586），条件节点完成后所有 handle 的后继全部就绪并**并行执行**（条件分支两边都跑） | 按 `output_data._next_handle` × `dag.get_successors(node_id, handle)` 路由（:1411-1416），未命中回退 "default"（:1419-1420） |
| 未选中分支 | 不存在"未选中"概念（全跑） | 不执行但**不标记 skipped**，残留 PENDING → `_check_execution_complete` 的 pending>0 永不满足 → 执行永远 running |
| skipped 依赖满足 | `dep in completed or dep in skipped` 均算满足（:571-574） | `_check_dependencies_ready` 仅认 COMPLETED（:1529）——skipped/tolerated 依赖会**永久阻塞**后继 |
| 容错失败（on_error=ignore） | tolerated 入 completed 集合 + fallback 输出（:804-811） | `_handle_node_failure` 一律 fail 整个执行（:1459-1486，TODO 注明） |
| 执行方式 | ready 批量 `asyncio.gather` 并行（:774-785） | 逐个串行 + 递归下钻（:1431-1457），深链有递归深度与无并行差异 |
| 完成判定 | 内存集合 + 循环退出（:838-851），不查 DB waiting | DB 统计 pending/running/waiting/failed 全零判定（:1488-1515），**不含 QUEUED**，且无死锁分支 |
| next_handle 来源 | `_execute_node` 返回 dict 的 `handle` 键（:966-970）——注意内存 `node_outputs` 存的是 `result["output"]`，**不含** `_next_handle`（仅 DB output_data 有 :952-955） | DB `output_data._next_handle`（:1412-1413） |
| 输出双键 | 主路径双键（:798-802）；轮询刷新路径只有 UUID 键（:672） | `_collect_all_outputs` 双键（:1534-1554） |

**路由可用的既有原料**：`DAGNode.outgoing: dict[handle, set[target]]`（dag.py:20）、`get_successors(node_id, handle)`（:189-196）、`get_all_successors`（:198-208）、`forward_incoming`（排除反馈环 back-edge，:31-37）、`_detect_back_edges`（非 default handle 指向 DFS 祖先即 back-edge，:100-126）。**注意环语义**：审批驳回回退等反馈环是合法模式（`has_cycle` 只判 default 环 :152-183），skipped 级联必须基于 `forward_incoming` 且不得把"暂未被选中的回退目标"误标 skipped（回退边目标节点可能已 COMPLETED，重入语义现状本就不完整——`_continue_after_node` 只找 PENDING 后继 :1437-1441，已完成的回退目标不会重跑，列为已知缺口不在本阶段扩大）。

### §3 ENG-03：trigger_data 写入/读取全链路

**写入侧（已基本统一）**：所有触发方式（manual/API、webhook、feishu）都经 `TriggerDispatcher.dispatch` → `start_execution(trigger_data={"raw_payload": context.raw_payload})`（dispatcher.py:107-115）。manual 入口在 workflows/api/views.py:400-410（raw_payload = 用户 input_data），feishu 入口在 feishu/views.py:693-708，webhook 在 views.py:1394-1404。retry 入口复用原 trigger_data（views.py:884-894）。

**两个写入侧缺口**：
1. `resume_from_node` 创建新执行时 trigger_data 被**整体替换**为 `{"metadata": {resumed_from, failed_node_id}}`（scheduler.py:1720-1725）——恢复执行中 `{{trigger.raw_payload.*}}` 必然丢失，应继承原 trigger_data 再附加 metadata。
2. 锁定决策要求 manual/API 缺省注入 `{source: "manual"|"api", ...payload}`——现状无 `source` 键。

**读取侧（唯一根因）**：`ExecutionContext` 定义了 `trigger_data: dict = field(default_factory=dict)`（base.py:85），resolver 的 `trigger` 前缀宽松下钻该字段（template_resolver.py:219-220，Phase 17 已锁定宽松语义）；但 `_execute_node` 构造 ExecutionContext **不传 trigger_data**（scheduler.py:928-938）→ 真实执行中永远空 dict。同样不传的还有 `coding_callback._schedule_branch_confirmation` 的手工 context（coding_callback.py:279-288，连 previous_outputs 也是空）。修复 = `trigger_data=execution.trigger_data or {}` 注入（execution 对象在该作用域必有）。

**形状兼容性约束（重要，勿"顺手统一"）**：
- views.py:884-885（retry）读 `trigger_data["raw_payload"]`；knowledge 摄取 normalizer 兼容 `trigger_data.raw_payload` 与 `payload` 双键（v0.3.0 Phase 14-04 既定决策）；
- 节点经 `get_trigger_data` 读的键各不相同：coding.py:775-777 读 `payload.work_item_id`/`payload.id`（在 `{"raw_payload"}` 形状下永远 miss → 落入分支确认流程，这是**现状有意依赖的降级行为**）；feishu_workitem.py:152-166 读顶层 `work_item_type`/`project_key`。
- 推荐形状：保留 `raw_payload` 键不动，**新增** `source` 键（`{"source": "manual"|"api"|"feishu"|"webhook", "raw_payload": {...}, "event_type": ...}`），满足锁定决策且零破坏；`{{trigger.raw_payload.x}}` 与 `{{trigger.source}}` 都可解析。是否给 `payload` 设别名键属计划决策——若加，coding 节点分支确认降级行为会改变（work_item_id 突然可解析），必须配 characterization 测试显式决定。
- 入口节点输出已含 `raw_payload`（BaseTriggerNode.execute，triggers/base.py:56-60），`{{nodes.<trigger短id>.raw_payload.*}}` 现状可用——ENG-03 修的是 `{{trigger.*}}` 这条独立通路。

### §4 ENG-04：死锁现状

- 主循环已有判定（:679-697）：`not ready_nodes` 且无 waiting 节点且 pending 非空 → `amark_failed("工作流死锁：N 个节点无法调度 (名字列表)")`。缺陷：只有节点 name，没有 short_id、没有"在等哪个上游/哪个 handle"；非结构化（Phase 21 无法解析）。
- 判定条件与锁定决策对齐情况：决策是"有 pending 但无 ready 且无 waiting/running 节点"。主循环是串行的，到达该分支时无并发 running（gather 已结束），现有条件成立时机正确；但 **waiting 节点存在 + 部分 pending 永不可达** 的混合场景现状走 5s 轮询永不报错（§1.2）——ENG-01 的"立即挂起"改造会让这类场景在恢复续跑后暴露为纯死锁，需要在恢复后的调度中同样判定。
- 回调续跑路径完全无死锁检测：`_check_execution_complete`（:1488-1515）pending>0 时静默返回。ENG-02 的 skipped 级联落地后，路由正确时不应再有"被遗弃的 PENDING"；在 `_check_execution_complete` 增加同一死锁判定函数调用即可兜底。
- 诊断信息所需数据都在手边：每个 pending 节点的 `forward_incoming`（dag.py:31-37）+ 各依赖 NE 当前状态 + 连接边的 source_handle（dag.edges 持有完整 WorkflowEdge）。结构化编码沿用 Phase 17 约定："中文一句话 + `\n` + JSON（ensure_ascii=False，最后一行可 json.loads）"，已有先例见 scheduler.py:1020-1032 的 TemplateResolutionError 处理。

### §5 ENG-05：target_handle 与输入收集

**数据链路完备、消费缺失**：模型字段（models/node.py:221-224，default="default"，unique_together 含它 :246）、serializer（api/serializers.py:287,302）、模板 loader（templates/loader.py:184,272）、执行快照 targetPort（scheduler.py:252）、前端真实写入（WorkflowCanvas.vue:127-133 connection.targetHandle → targetPort；useWorkflowsStore.ts:217-221 落 target_handle；用户连到 ai_code_review 的 coding_result 输入桩时 target_handle 即为 "coding_result"）。但 `DAG.afrom_workflow` 只把 source_id 放进 `incoming` 集合（dag.py:88-93），`_collect_inputs` 对 incoming 逐个 `inputs.update(node_outputs[source_id])` 扁平合并（scheduler.py:1093-1107，两路径共用此函数——这点是好消息）。

**两个关键节点链的端口期望（决定归集规则的兼容性）**：
- `ai_plan_generation → ai_coding(plan 端口, required)`：coding 读 `context.get_input("plan")` 期望**方案对象本身**（coding.py:706-712）；现状可用是因为 plan_generation 的输出 dict 顶层就有 `plan` 键（plan_generation.py:329-352）——扁平合并后键名碰巧对上。**若把整个上游输出嵌套到 `plan` 名下会变成 `{plan:{plan:...}}`，直接打破该节点**。
- `ai_coding → ai_code_review(coding_result 端口, required)`：review 读 `get_input("coding_result")` 期望**整个上游输出对象**，取不到时兜底"扁平 merge_requests 直连兼容"（code_review.py:308-322）；coding 输出顶层无 `coding_result` 键 → 现状**靠兜底分支活着**。
- 两个节点对"端口收什么"的期望**互相矛盾**（一个要字段、一个要整包）——任何单一嵌套规则都无法同时满足，除非采用非破坏性叠加规则（见 Pattern 5）。

### §6 引擎测试现状（覆盖盲区清单）

- `server/tests/workflows/` 共 368 个用例全绿（Phase 17 后基线）。引擎直接相关：`test_engine.py`（启动/简单完成/审批/取消）、`test_error_handling.py`（on_error 三策略、超时、重试、TemplateResolutionError 结构化落盘——Phase 17 新增，含 run_sync=True 范式）、`test_dag.py`（DAG 构建/环检测/get_successors by handle）、`test_engine_resume.py`（仅 paused-resume 校验 2 例）、`test_hooks.py`（事件注册契约）。
- **盲区（本阶段四类回归测试的对象，现覆盖为零）**：waiting_event 挂起/完成判定（`test_approval_node_waits` 的断言是 `waiting_count >= 0` **恒真**，test_engine.py:281）；条件分支路由与 skipped 标记（任意路径）；死锁转 failed；`_continue_after_node` 回调续跑（仅 test_node_migration.py 的可导入性冒烟）；trigger_data 注入（test_coding_node.py 等直接构造 ExecutionContext 传 trigger_data，从未经过 scheduler）；target_handle（无任何测试）。
- 可复用测试资产：test_engine.py 的 workflow 工厂 fixture 范式（trigger+节点+边，db fixture）；test_error_handling.py 的 `start_execution(run_sync=True)` 同步执行范式（新测试应优先 run_sync，避免线程+轮询不确定性）；根 conftest.py:866-878 的 make_context 工厂（支持 trigger_data）；节点结果可用 `code` 节点或 monkeypatch NodeRegistry 制造任意 next_handle/waiting 行为。
- 运行命令：`cd server && uv run pytest tests/workflows/ -x`（368 例约可接受）；pytest-socket 网络隔离开启，路由/级联做成纯函数可零 DB 单测。

## Standard Stack

### Core（全部为既有依赖，零新增安装）

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Django ORM（async）+ asgiref sync_to_async | django>=5.1 既有 | NE/Execution 状态迁移 | 项目既定栈 [VERIFIED: codebase] |
| asyncio + `_run_in_thread` | stdlib | 主循环线程模型（保持现状） | scheduler.py:36-50 既有模式 |
| structlog | 既有 | 结构化日志 | 既有约定 |
| pytest>=9 + pytest-django + pytest-asyncio | 既有 | 四类路径回归测试 | `server/pyproject.toml` [VERIFIED] |
| Phase 17 `template_resolver` | 本仓库 | trigger 前缀解析与错误结构 | 已定稿，本阶段只注入数据源 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 内存集合 + DB NE 状态双轨 | 引入正式状态机库（transitions 等） | 改动面巨大且与 async ORM 摩擦，**不采用**——本阶段是修语义不是换架构 |
| 回调续跑重入主循环 | 继续修补 `_continue_after_node` 递归 | 修补可满足"共用路由函数"的字面要求，但完成判定/容错/并行三类漂移仍要逐项同步两份逻辑；重入主循环一次性消除（代价：需执行级互斥）。两案均可行，见 Pattern 2 |

**Installation:** 无需安装。

## Package Legitimacy Audit

本阶段**不安装任何外部包**（纯内部引擎改造）。无需 slopcheck。

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```text
触发入口（统一写入侧）                         调度（统一读取/路由侧）
┌─────────────────────────┐    start_execution   ┌──────────────────────────────────────┐
│ TriggerDispatcher        │  trigger_data=       │ _run_execution 主循环                 │
│  manual/API → +source 键 │  {source, raw_payload}│  ready 判定 = routing.is_node_ready  │
│  feishu / webhook        ├─────────────────────▶│  (边感知: 入边终态 + ≥1 条选中活路)    │
└─────────────────────────┘                       │  节点完成 → routing.apply_routing     │
                                                  │   ├ 选中: get_successors(next_handle) │
       回调续跑（事件到达）                         │   └ 未选中: skipped 级联标记           │
┌─────────────────────────┐                       │  循环出口 = routing.judge_final       │
│ approve/reject/wait_feishu│  标记节点终态         │   ├ waiting 存在 → amark_suspended    │
│ chat_question / agent     ├──────────────┐      │   ├ 死锁 → amark_failed(结构化诊断)    │
│ 容器回调(修复: 重跑节点)   │              ▼      │   └ 全终态 → completed/failed          │
└─────────────────────────┘        ┌──────────────┴───────────┐
                                   │ resume: 重建状态(DB→集合)  │   _collect_inputs(边感知,
                                   │ → 重入 _run_execution      │   target_handle 归集) 两路径共用
                                   │ (执行级互斥防双循环)        │
                                   └──────────────────────────┘
                                                  │ hooks.trigger("execution_suspended"/…)
                                                  ▼
                                   WS 广播 {event, execution_id, status} + DRF status 字段（已存在）
```

### Recommended Project Structure

```
server/workflows/engine/
├── scheduler.py          # 主循环瘦身：状态集合驱动，判定/路由委托 routing
├── routing.py            # 新增：纯函数路由核心（推荐方案，属 discretion）
│   ├─ select_successors(dag, node_id, next_handle)   # handle 匹配 + default 回退(兼容)
│   ├─ cascade_skip(dag, node_id, selected, statuses) # 未选中分支级联 skip 集合计算
│   ├─ is_node_ready(dag_node, statuses, handles)     # 边感知就绪判定
│   ├─ diagnose_deadlock(dag, statuses) -> 结构化诊断 # ENG-04
│   └─ collect_inputs(dag, node_id, node_outputs)     # target_handle 归集（迁自 _collect_inputs）
├── template_resolver.py  # Phase 17 产物，不动
└── dag.py                # DAGNode 增加入边明细 (source_id, source_handle, target_handle)
```

纯函数 + 显式 statuses/handles 入参（dict），零 DB 即可单测（同 Phase 17 resolver 的可测性策略，规避 pytest-socket/django_db 开销）。

### Pattern 1: 完成/挂起判定收口（ENG-01）

**What:** 主循环维护 `waiting_nodes_mem: set[str]`（waiting_approval/waiting_event 都加入，**都不加回 pending**——同时消灭 §1.4 热循环）；循环出口与"无 ready"分支统一走一个判定函数：waiting 非空 → `amark_suspended` + `execution_suspended` hook + return（删除 5s 轮询分支）；waiting 空且 pending 非空 → 死锁 failed；否则按 failed/completed 收尾。
**When to use:** 这是锁定决策"等待就是 suspended"的直接实现。轮询分支删除后，审批推进完全依赖回调（`approve_node` 已具备完整闭环），与现网回调路径一致。
**Warning:** `test_engine.py::test_approval_node_waits`/`test_cancel_running_execution` 依赖旧行为的部分需同步改写（断言本就无效）；`run_sync=True` 调用方（含 debug 工作流执行）在挂起时将立即返回——属预期新语义。

### Pattern 2: 回调续跑重入主循环（ENG-01/02 推荐方案）

**What:** `_continue_after_node` 重构为薄入口：(a) 若节点带 `_resume_from_callback` 类标记且仍 WAITING_*，先重置 RUNNING 并经 `_execute_node` 重跑（消费标记，复用重试/超时/on_error 全套逻辑，替代 coding_callback 的手工迷你调度器）；(b) 节点终态后**重建状态重入** `_run_execution(is_resume=True)`——从 DB NE 状态恢复 completed/failed/skipped 集合与 `_collect_all_outputs` 双键输出（含 `_next_handle`），路由/就绪/死锁/挂起判定与主循环字面同源。
**When to use:** 满足"恢复后语义与主循环一致"的最强形式；`resume_execution`（:1131-1181）已示范"重建 initial_outputs → 重入"的模式（但其 COMPLETED→SKIPPED 改写手法应废弃，直接按真实状态重建，skipped 语义本阶段已是正式终态）。
**Warning:** 必须加执行级互斥（并发回调/审批同时到达会起两个循环线程）：用 DB 原子条件更新（`filter(status=SUSPENDED).update(status=RUNNING)` 抢锁，抢不到即放弃）最简单可靠。若计划评估重入成本超预期，回退方案：保留 `_continue_after_node` 递归骨架，但路由/级联/完成判定三处全部调用 routing 纯函数（与主循环同源），并补 skipped 级联与死锁兜底——此为满足锁定决策的最小实现。

### Pattern 3: 边感知就绪判定 + skipped 级联（ENG-02，算法属 discretion）

**What:** DAGNode 增加 `incoming_edges: list[(source_id, source_handle, target_handle)]`（构建时顺手收集，dag.py:83-95 处）。定义：
- 入边已解析 := 源节点 ∈ {completed, skipped, failed-tolerated}；
- 入边选中 := 源 completed 且 (源的 next_handle == 边 source_handle，或回退兼容：源 next_handle 无任何匹配边时 default 边视为选中)；
- 节点 ready := 所有 forward 入边已解析 且 ≥1 条入边选中；
- 节点 skip := 所有 forward 入边已解析 且 0 条选中（汇合节点一条活路即执行——锁定决策原文）。级联自然发生：被 skip 的节点终态化后其出边全部"已解析未选中"。
**Why:** 把"分支路由"从"完成后主动推下游"改为"下游就绪时拉取判定"，主循环只需在每轮把"可 skip 节点"标记掉（`_skip_node` 已有 :1109-1120，含 node_skipped hook），无需改 gather 并行骨架。next_handle 的内存来源用 `_execute_node` 返回的 `handle` 键（:969），DB 来源用 `output_data._next_handle`——重入重建时从 DB 读。
**现状保留项:** "前置 failed（非 tolerated）→ skip 下游"的 ANY 语义（:576-583）保持不变，与分支级联并存。

### Pattern 4: trigger_data 注入（ENG-03，最小改动）

```python
# scheduler.py _execute_node 构造 ExecutionContext 处（:928-938）增加一行
context = ExecutionContext(
    ...,
    trigger_data=execution.trigger_data or {},   # ENG-03 唯一读取侧缺口
)
```

外加：(1) dispatcher 统一补 `source` 键（manual/api/feishu/webhook 按 trigger_type 写入，保留 raw_payload/event_type 现有键零破坏）；(2) `resume_from_node` 的 trigger_data 改为继承原执行 + 附加 metadata（:1720-1725）；(3) `coding_callback._schedule_branch_confirmation` 的手工 context 同步注入（若 Pattern 2 落地，该手工路径整体删除）。

### Pattern 5: target_handle 非破坏性归集（ENG-05）

**What:** `collect_inputs` 规则（按入边逐条处理，顺序按 source_id 排序保证确定性）：
1. 扁平合并上游输出（现状语义，保底兼容）；
2. 若边 `target_handle` 非空且非 "default"：再设 `inputs[target_handle] = 上游完整输出`，**但同一上游的扁平输出中已存在同名键时不覆盖**（防 plan_generation 输出 `plan` 键 + 边 target_handle="plan" 时双重嵌套打破 ai_coding，§5）。
**Effect:** `ai_coding.get_input("plan")` 继续拿到方案对象（不覆盖规则生效）；`ai_code_review.get_input("coding_result")` 开始命中主路径（coding 输出无同名键，端口键被补上），兜底分支可保留为兼容；多上游汇合时端口键天然消歧。
**When to use:** 这是"实现其语义"与"存量不回退"的交集；配 characterization 测试把 plan→coding、coding→review 两条链锁死。若计划判定该精细规则成本超预期，锁定决策给了回退选项（显式移除字段），但移除涉及前端/序列化/模板多点，预估成本更高——**优先实现归集**。

### Anti-Patterns to Avoid

- **在 `_continue_after_node` 里再长出第二套就绪/路由 if-else**：审计定性的漂移根源就是重复实现；一切判定进 routing 纯函数。
- **把 waiting 节点加回 pending 让循环"自己转"**：这正是 waiting_approval 热循环根因（§1.4）。
- **删除 default 回退路由**："next_handle 无匹配边时回退 default"承载存量工作流（节点返回 success/error 而用户只连了 default 边）；按 characterization 保留，两路径行为一致即可。
- **借机收紧 trigger 前缀解析严格性**：Phase 17 已锁定宽松语义，resolver 不动。
- **重写 resume_from_node / 失败重跑语义**：属 deferred（执行级重试增强）；只修它的 trigger_data 继承缺口。
- **给 `_handle_node_failure` 顺手实现 on_error 策略**：代码内 TODO 明示是未来工作，本阶段只保证它不被新路由破坏。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| handle→后继查询 | 自写边遍历 | `dag.get_successors(node_id, handle)` + `DAGNode.outgoing` | 已含 handle 分桶（dag.py:189-208） |
| 反馈环识别 | 新写环检测 | `forward_incoming` / `_detect_back_edges` | 已处理"非 default handle 指向祖先"语义（dag.py:100-126） |
| 双键输出重建 | 新写收集 | `_collect_all_outputs`（:1534-1554） | UUID+short_id 双键已实现，重入重建直接用 |
| 结构化 error_message | 新设计编码 | Phase 17 约定："中文一句话\nJSON(ensure_ascii=False)" | scheduler.py:1020-1032 已有先例，Phase 21 按此消费 |
| 挂起事件广播 | 新 WS 通道 | `hooks.trigger("execution_suspended")` + WebSocketBroadcastHook | 事件已注册、广播含 status（builtin.py:38-75） |
| 节点重跑（含重试/超时/on_error） | coding_callback 式手工 execute | `engine._execute_node` | 手工路径缺 trigger_data/previous_outputs/重试，就是漂移源 |

## Common Pitfalls

### Pitfall 1: 删轮询分支后 waiting_approval 回调成为唯一推进通道
**What goes wrong:** 现状 5s 轮询"顺带"兜住了部分状态推进；删除后若某回调忘记翻转 SUSPENDED→RUNNING 或忘记续跑，执行将停在 suspended。
**How to avoid:** §1 恢复路径全景表中 7 条入口逐一过一遍"翻转状态 + 续跑"两件事；Pattern 2 重入式续跑天然把翻转收进重入入口。
**Warning signs:** 集成测试中审批通过后执行停在 suspended。

### Pitfall 2: 内存 node_outputs 与 DB output_data 的 `_next_handle` 不对称
**What goes wrong:** 主循环内存输出（result["output"]）不含 `_next_handle`（仅 DB 有，:952-955），重入重建用 DB、热路径用内存——路由函数若只认一种来源，两路径又漂移。
**How to avoid:** routing 函数显式接收 `handles: dict[node_id, next_handle]` 入参；主循环从 result["handle"] 填，重建从 output_data 填。顺手修复轮询遗留的单键写入点（若保留任何刷新路径，:672 必须补 short_id 键）。

### Pitfall 3: skipped 级联误伤反馈环与汇合节点
**What goes wrong:** 用 `incoming`（含 back-edge）而非 `forward_incoming` 判定会让回退目标永远不 ready；级联用 ANY 而非 ALL 语义会把汇合节点错杀（锁定决策明确"一条活路即执行"）。
**How to avoid:** 级联只看 forward 入边；纯函数单测覆盖：菱形汇合（一支 skip 一支活）、双支全 skip、链式级联、含 back-edge 的审批驳回环。

### Pitfall 4: `_check_dependencies_ready` 只认 COMPLETED
**What goes wrong:** skipped 成为正式终态后，回调续跑路径中"汇合节点的 skipped 依赖"会永久阻塞（:1529）；tolerated 失败（NE 状态是 FAILED）同样阻塞。
**How to avoid:** 该函数随 Pattern 2/3 一并替换为边感知 ready 判定；若走回退方案则至少把判定改为 终态∈{COMPLETED, SKIPPED}（tolerated 的 fallback 输出在重建时需特殊处理——NE FAILED 但主循环曾给下游 fallback 值，重入重建拿不到该内存值，计划需显式决策：tolerated fallback 持久化到 output_data 或限制范围）。

### Pitfall 5: 误判 completed 的修复必须覆盖"循环正常退出"与"stop_before 提前退出"两个出口
**What goes wrong:** 只修 :842-851 出口，漏掉 stop_before_node_id 提前完成出口（:611-621）——该出口同样 `amark_completed` 不查 waiting。
**How to avoid:** 完成判定收口为单函数（Pattern 1），两个出口都走它。

### Pitfall 6: 并发续跑双循环
**What goes wrong:** 容器回调与人工审批几乎同时到达（或用户狂点 resume-wait），两个线程各自重入 `_run_execution`，同一 PENDING 节点被 `_execute_node` 跑两次（amark_started 无并发护栏）。现状 `_continue_after_node` 递归路径同样存在此竞态（与主循环轮询并发），只是无人观测。
**How to avoid:** 执行级抢锁：`WorkflowExecution.objects.filter(pk=..., status=SUSPENDED).aupdate(status=RUNNING)` 返回行数为 0 即放弃续跑；NE 级可加 `filter(status=PENDING).aupdate(status=QUEUED)` 原子认领（QUEUED 状态已存在 :34）。
**Warning signs:** 日志中同一 node_execution 出现两次 node_started。

### Pitfall 7: 并发上限放走 suspended
**What goes wrong:** `max_concurrent_executions` 守卫只数 PENDING/RUNNING（:180-186）；挂起执行不占名额，海量挂起 + 同时恢复可超限。属现状既有行为，本阶段挂起会更常见使其放大。
**How to avoid:** 本阶段不改并发语义（避免破坏存量预期），在计划中记录为已知行为并在续跑抢锁处保留单执行互斥即可；若要纳入需用户决策（Open Questions #3）。

### Pitfall 8: trigger_data 形状"顺手修复"破坏降级行为
**What goes wrong:** 给 trigger_data 补 `payload` 别名键会让 coding.py:775 突然解析出 work_item_id，跳过分支确认卡片流程——行为变化未经决策。
**How to avoid:** 本阶段只加 `source` 键 + 注入读取侧；`payload`/`raw_payload` 键名收敛列为 Open Question，配 characterization 测试锁现状。

### Pitfall 9: 既有测试对旧语义的隐性依赖
**What goes wrong:** 条件分支"两边都跑"的旧行为可能被某些工作流/模板隐性依赖（如把 condition 当 fan-out 用）；改为真分支后这类工作流行为改变。
**How to avoid:** 全量跑 `uv run pytest`（368+ 用例）+ 检查内置模板（templates/）中 condition 节点的连线方式；发现 fan-out 用法时在计划中显式列出迁移说明。skipped 参与完成判定后，`resume_execution` 的 COMPLETED→SKIPPED 改写（:1151-1156）语义混淆必须一并处理（按真实状态重建，废弃改写）。

## Code Examples

### 现状：waiting_event 不加回 pending → 末端节点误判 completed 的根因

```822:851:server/workflows/engine/scheduler.py
                    elif result.get("status") == "waiting_event":
                        # 节点正在等待外部事件，不加回 pending
                        # 循环会检测到 waiting 节点并挂起 workflow
                        pass
                    else:
                        failed_nodes.add(dag_node.id)

                # 检查超时
                await execution.arefresh_from_db()
                if execution.timeout_at and timezone.now() > execution.timeout_at:
                    execution.status = ExecutionStatus.TIMEOUT
                    await execution.asave(update_fields=["status"])
                    await self.hooks.trigger("execution_timeout", execution=execution)
                    return

            # 执行完成
            if failed_nodes:
                await execution.amark_failed(f"失败节点: {len(failed_nodes)}")
                hook_execution = await self._load_execution_for_hooks(execution)
                await self.hooks.trigger("execution_failed", execution=hook_execution)
            else:
                # 收集最终输出（终端节点的输出）
                final_output = {}
                for node_id in completed_nodes:
                    dag_node = dag.nodes.get(node_id)
                    if dag_node and not dag_node.outgoing:
                        final_output.update(node_outputs.get(node_id, {}))
                await execution.amark_completed(final_output)
                hook_execution = await self._load_execution_for_hooks(execution)
                await self.hooks.trigger("execution_completed", execution=hook_execution)
```

### 现状：主循环就绪判定无视 handle（条件分支两边都跑）

```565:586:server/workflows/engine/scheduler.py
                for node_id in pending_nodes:
                    dag_node = dag.nodes[node_id]

                    # 用 forward_incoming 检查依赖（排除反馈环 back-edge）
                    forward_deps = dag_node.forward_incoming

                    all_deps_completed = all(
                        dep_id in completed_nodes or dep_id in skipped_nodes
                        for dep_id in forward_deps
                    )

                    any_dep_failed = any(dep_id in failed_nodes for dep_id in forward_deps)

                    if any_dep_failed:
                        # 前置失败，跳过此节点
                        await self._skip_node(execution, dag_node, "前置节点失败")
                        skipped_nodes.add(node_id)
                        nodes_to_remove.append(node_id)
                        continue

                    if all_deps_completed:
                        ready_nodes.append(dag_node)
```

### 现状：回调续跑按 handle 路由但不 skip 未选中分支

```1411:1424:server/workflows/engine/scheduler.py
        # Read next_handle from output_data for handle-based routing
        output_data = node_execution.output_data or {}
        next_handle = output_data.get("_next_handle", "default")

        # Use dag.get_successors() to route by handle
        successors = dag.get_successors(completed_node_id, next_handle)

        # Fallback to "default" handle if specified handle has no successors
        if not successors and next_handle != "default":
            successors = dag.get_successors(completed_node_id, "default")

        if not successors:
            # Terminal node - check if execution is complete
            await self._check_execution_complete(execution)
            return
```

### 现状：输入收集扁平合并（target_handle 名存实亡）

```1093:1107:server/workflows/engine/scheduler.py
    def _collect_inputs(
        self,
        dag_node,
        dag: DAG,
        node_outputs: dict,
    ) -> dict:
        """收集节点的输入数据（从上游节点输出）"""
        inputs = {}

        for source_id in dag_node.incoming:
            if source_id in node_outputs:
                # 合并上游输出到输入
                inputs.update(node_outputs[source_id])

        return inputs
```

### 死锁诊断结构化编码（沿用 Phase 17 约定，示意）

```python
# routing.diagnose_deadlock 输出示意（中文一句话 + JSON 行，最后一行可 json.loads）
msg = f"工作流死锁：{len(stuck)} 个节点无法调度，详见诊断"
detail = json.dumps({
    "reason": "deadlock",
    "pending": [
        {
            "node": dn.node.name,
            "short_id": dn.node.short_id,
            "waiting_on": [
                {"node": dep.node.name, "short_id": dep.node.short_id,
                 "status": statuses.get(dep.id, "unknown"), "handle": edge_handle}
                for dep, edge_handle in unmet_deps(dn)
            ],
        } for dn in stuck
    ],
}, ensure_ascii=False)
await execution.amark_failed(f"{msg}\n{detail}")
```

## State of the Art

| Old Approach（现状） | Current Approach（本阶段目标） | When Changed | Impact |
|--------------|------------------|--------------|--------|
| waiting=5s 轮询/误判 completed/热循环 | waiting ⇒ 立即 amark_suspended + 事件广播 | Phase 18 | Phase 21 前端直接消费 suspended 状态 |
| 两套路由（主循环无视 handle / 回调有 handle 无 skip） | routing 纯函数单源，边感知就绪 + skipped 级联 | Phase 18 | Phase 20 模板端到端依赖此正确性 |
| {{trigger.*}} 永远空 | ExecutionContext 注入 execution.trigger_data + source 键 | Phase 18 | 模板/文档可承诺 trigger 引用可用 |
| 死锁报"名字列表"或永远 running | 结构化诊断转 failed（Phase 17 编码风格） | Phase 18 | Phase 21 错误展示直接 JSON.parse |
| target_handle 落库不消费 | 归集到输入端口名（非破坏性叠加规则） | Phase 18 | Phase 19 NodePort SSOT 的运行时落点 |

**Deprecated/outdated（本阶段后不应再出现）：**
- `coding_callback._schedule_branch_confirmation` 的手工迷你调度器（改走 `_execute_node` 重跑）
- `resume_execution` 的 COMPLETED→SKIPPED 状态改写手法（按真实 NE 状态重建）
- 主循环 5s 轮询分支（:663-677）

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 容器回调→workflow 自动续跑链路在现网即为断裂（静态分析结论，未在运行环境复现验证；不排除存在未发现的重跑入口） | §1.6 | 若另有隐藏路径，Pattern 2 改造需先兼容该路径再删除；计划应先写"复现断裂"的回归测试坐实 |
| A2 | 没有存量工作流把 condition 当 fan-out（两分支都执行）使用 | Pitfall 9 | 真分支语义会改变此类工作流行为；需在计划中检查内置模板与提供迁移说明 |
| A3 | 删除 5s 轮询后无其他组件依赖"running 态下轮询推进"（如超时调度器 test_timeout_scheduler 涉及 waiting_event 超时处理） | Pattern 1 | wait 节点 timeout_at 机制若依赖执行线程存活，挂起后超时需由 django-apscheduler 类外部调度兜底；计划需核查 `WorkflowEventSubscription.timeout_at` 的处理者 |

## Open Questions

1. **trigger_data 的 `payload` 键是否补别名？**
   - What we know: 节点读 `payload.*`（coding.py:775）现状永远 miss 并触发分支确认降级；normalizer 兼容双键。
   - What's unclear: miss→降级是否为有意设计的长期行为。
   - Recommendation: 本阶段只加 `source` 键，`payload` 别名不加；characterization 测试锁定现状，留 Phase 21（触发模型）决策。
2. **审批驳回反馈环的"重入已完成节点"语义**：`_continue_after_node` 只找 PENDING 后继，回退目标若已 COMPLETED 不会重跑（§2 注）。
   - Recommendation: 超出 ENG-01..05 范围（属执行级重试/断点续跑增强，已 deferred）；计划中作为已知缺口记录，路由函数设计预留 handle 指向非 PENDING 节点时的明确日志。
3. **suspended 是否计入 max_concurrent_executions**：现状不计（:180-186）。
   - Recommendation: 维持现状（兼容优先），续跑抢锁保证单执行互斥即可；如需收紧属产品决策。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| uv（pytest 运行） | 后端回归测试 | ✓ | 0.10.2 | — |
| pytest 收集 | tests/workflows 基线 | ✓ | 368 例收集通过（本机实测） | — |

**Missing dependencies with no fallback:** 无（纯内部代码改造，无外部服务依赖）。

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest>=9.0.2 + pytest-django + pytest-asyncio（既有） |
| Config file | `server/pyproject.toml`（[tool.pytest]） |
| Quick run command | `cd server && uv run pytest tests/workflows/test_engine_routing.py -x` |
| Full suite command | `cd server && uv run pytest tests/workflows/ -x`（368+ 例）；阶段门禁全量 `uv run pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ENG-01 | 末端/带下游 waiting_event ⇒ suspended（绝不 completed）；execution_suspended hook 触发；回调续跑重跑节点并恢复语义一致；waiting_approval 不再热循环 | integration（django_db, run_sync） | `cd server && uv run pytest tests/workflows/test_engine_waiting.py -x` | ❌ Wave 0 |
| ENG-02 | 条件分支仅选中支执行；未选中支级联 skipped（含菱形汇合一活一死）；主循环与回调续跑同工作流同结果 | unit（routing 纯函数）+ integration | `cd server && uv run pytest tests/workflows/test_engine_routing.py -x` | ❌ Wave 0 |
| ENG-03 | manual/API/feishu 触发下 {{trigger.source}}/{{trigger.raw_payload.*}} 可解析；resume_from_node 继承 trigger_data | integration | `cd server && uv run pytest tests/workflows/test_engine_trigger_data.py -x` | ❌ Wave 0 |
| ENG-04 | 人造死锁 DAG ⇒ failed + error_message 末行 json.loads 含 pending/waiting_on/short_id/handle | unit + integration | `cd server && uv run pytest tests/workflows/test_engine_deadlock.py -x` | ❌ Wave 0 |
| ENG-05 | target_handle 归集（coding_result 命中主路径、plan 不双重嵌套——characterization）；四类路径回归集合全绿 | unit（collect_inputs 纯函数）+ integration | `cd server && uv run pytest tests/workflows/test_engine_inputs.py tests/workflows/ -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `cd server && uv run pytest tests/workflows/test_engine_routing.py tests/workflows/test_engine_waiting.py -x`（纯函数 + run_sync，<30s）
- **Per wave merge:** `cd server && uv run pytest tests/workflows/ -x`
- **Phase gate:** `cd server && uv run pytest` 全量绿后进入 `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `server/tests/workflows/test_engine_waiting.py` — ENG-01（含"复现容器回调断裂"的红测先行，坐实 A1）
- [ ] `server/tests/workflows/test_engine_routing.py` — ENG-02 路由/级联纯函数 + 双路径一致性
- [ ] `server/tests/workflows/test_engine_trigger_data.py` — ENG-03
- [ ] `server/tests/workflows/test_engine_deadlock.py` — ENG-04
- [ ] `server/tests/workflows/test_engine_inputs.py` — ENG-05 归集规则 + 两条真实节点链 characterization
- [ ] 夹具：建议在 tests/workflows/conftest.py 增加"条件分支工作流/等待工作流/死锁工作流"工厂（范式照抄 test_engine.py 局部 fixture；用 code 节点或注册测试节点制造任意 next_handle/waiting 行为，规避真实 AI/飞书依赖）
- [ ] 框架安装：无需

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | 引擎内部改造；审批/续跑 API 既有 IsAuthenticated + ApprovalPermission 不动 |
| V3 Session Management | no | — |
| V4 Access Control | yes | 续跑/重跑入口（callbacks、feishu 回调）既有鉴权与 project 归属校验不得绕过；新增重入入口不暴露新 API |
| V5 Input Validation | yes | trigger_data 来自外部 webhook/feishu payload，只透传不执行；死锁诊断 available 候选只列节点名/short_id/handle，**不含节点输出值**（信息泄露防线，同 Phase 17 约定） |
| V6 Cryptography | no | — |

### Known Threat Patterns for Django 异步工作流引擎

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 并发回调致重复执行（重复发卡/重复 dispatch 容器） | Tampering/DoS | 执行级原子抢锁 + NE 原子认领（Pitfall 6） |
| 伪造回调推进他人执行 | Spoofing | 既有回调鉴权（runner token / feishu 验签）不动；`_continue_after_node` 调用方均在鉴权后 |
| 错误信息泄露上游输出内容 | Information Disclosure | 诊断 JSON 仅含拓扑元数据（名称/short_id/状态/handle） |

## Sources

### Primary (HIGH confidence — 全部为本仓库代码逐行核实)
- `server/workflows/engine/scheduler.py` 全量 1789 行（主循环 :505-859；_execute_node :861-1091；_collect_inputs :1093-1107；审批 :1208-1327；_continue_after_node :1371-1457；完成判定 :1488-1515；resume_from_node :1644-1788）
- `server/workflows/engine/dag.py` 全量（outgoing 分桶 :20；forward_incoming :31-37；back-edge :100-126；get_successors :189-208）
- `server/workflows/models/execution.py`（状态枚举 :17-43；mark_suspended :307-315；amark_waiting_event :742-747）
- `server/workflows/nodes/base.py`（ExecutionContext.trigger_data :85；get_trigger_data :161-177）+ `engine/template_resolver.py`（trigger 前缀 :219-220）
- `server/workflows/triggers/`（dispatcher.py :107-115；handlers/{manual,feishu,webhook}.py prepare_input；nodes/triggers/base.py :36-87）
- 回调路径：`server/subagent/api/callbacks.py`（:177-260, :585-679）、`server/feishu/callbacks/{coding_callback,chat_question_callback}.py`、`server/feishu/views.py`（:693-708, :1002-1029）、`server/tasks/agent_tasks.py`（:212-272）、`server/workflows/api/views.py`（:400-410, :872-894, :1964-2042）
- waiting_event 生产者：`nodes/ai/coding.py`（:218-233, :455-504, :1034-1039）、`nodes/ai/plan_approval.py`、`nodes/control/wait_feishu.py`、`nodes/integrations/chat_question.py`、`nodes/ai/base_agent.py`（:721-729）、`nodes/control/approval.py`（:94-124）
- target_handle 链路：`models/node.py`（:221-246）、`api/serializers.py`（:287,302）、`web/src/components/workflow/editor/WorkflowCanvas.vue`（:127-133）、`web/src/stores/useWorkflowsStore.ts`（:217-221）；端口期望：`nodes/ai/coding.py`（:159-167, :706-712）、`nodes/ai/code_review.py`（:215-331）、`nodes/ai/plan_generation.py`（:225-352）
- hooks：`workflows/hooks/base.py`（:28-47）、`workflows/hooks/builtin.py`（:38-75）
- 测试基线：`server/tests/workflows/`（368 例收集实测；test_engine.py、test_error_handling.py、test_dag.py、test_engine_resume.py、test_node_migration.py）
- 本机环境探测：uv 0.10.2、pytest 收集通过

### Secondary / Tertiary
- 无（纯内部契约修复，不依赖网络资料）

## Metadata

**Confidence breakdown:**
- 现状链路与五条根因: HIGH — 每条结论附文件行号逐行验证
- 推荐架构（routing 抽取 + 重入式续跑 + 非破坏性归集）: HIGH — 由已验证事实与锁定决策推导；重入方案的互斥要求已识别
- Pitfalls: HIGH — 来自代码事实；三项不确定项已入 Assumptions Log（A1 容器续跑断裂为静态结论、A2 condition fan-out 存量、A3 轮询删除的超时兜底）

**Research date:** 2026-06-13
**Valid until:** 2026-07-13（内部代码契约，随 Phase 19-21 演进需复核）
