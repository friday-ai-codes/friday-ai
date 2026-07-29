# Phase 112: 规格门与双面路由调研（阶段 0+1） - Pattern Map

**Mapped:** 2026-07-30
**Files analyzed:** 10 类新建/修改文件
**Analogs found:** 10 / 10（全部命中强 analog）

## §13.2 冻结文件速查（只可读、禁改）

DESIGN.md §13.2 第 2 条：v0.20.0 **不改既有 `technical_plan` process 的文件**。下列 analog 全部为**只读参考**——照抄结构、另建 `blueprint_*` 新文件，绝不原地改：

| 冻结 analog | 本相位用途 |
|---|---|
| `server/services/process_runtime/clarify_adapter.py` | stage handler / HITL 回路范式 |
| `server/services/process_runtime/decompose_segments.py` | LLM 单调用 JSON 范式（间接，经 feature_classify） |
| `server/services/process_runtime/research_adapter.py` | 容器 fan-out dispatch 范式 |
| `server/services/process_runtime/architect_merge_adapter.py` | （113 用，本相位不碰） |
| `server/services/process_runtime/merged_plan.py` | schema 包装范式 |
| `server/services/process_runtime/render.py` | （不碰） |
| `server/codegraph/services/repo_router_v2.py` | 路由输出契约（只读调用，§13.2 + §5.7 第 4 条明令不改） |

**非冻结但受限**：`builtin_processes.py` 只允许**新增一个注册字典 + 一组 `_h_bp_*` handler**，`_TECHNICAL_PLAN_STAGES` 与既有 `_h_*` 一字不动（§13.2「冲突面收敛到注册字典一处」）。
`feature_classify.py` 不在冻结清单内，但它是 `technical_plan` 链路的运行文件，本相位同样**只读参考**。

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `services/process_runtime/blueprint_spec_gate.py`（stage adapter） | adapter | request-response + HITL | `clarify_adapter.py` | exact |
| `services/process_runtime/blueprint_ambiguity_score.py`（LLM 四维打分） | LLM helper | transform | `feature_classify.py` | exact |
| `services/process_runtime/blueprint_intent_classify.py`（feature_point 意图分类） | LLM helper | transform | `feature_classify.py` | exact |
| `services/process_runtime/blueprint_route.py` | adapter | transform + 证据融合 | `repo_router_adapter.py`（骨架）+ `recall_adapter.py`（history_match 分量） | role-match |
| `services/process_runtime/blueprint_research_adapter.py` | adapter | fan-out dispatch | `research_adapter.py` | exact |
| 回调消费（`subagent/api/callbacks.py` 新增 `_is_blueprint_research` 分支） | callback handler | event-driven | `callbacks.py:1699-1828`（plan_research）/ `:1830-1930`（repo_verify） | exact |
| 容器 token + env 注入（`blueprint_research_adapter` 内） | dispatch metadata | request-response | `workflows/nodes/ai/coding.py:1915-1940` + `access_tokens/services.py:32-64` | exact |
| `builtin_processes.py` 新增 `_TECHNICAL_BLUEPRINT_STAGES` + 注册项 | registry entry | config | `builtin_processes.py:207-252` + `:306-313` | exact |
| `repositories/blueprint_gate_views.py`（或 delivery 侧）确认门 5 动作 | view | request-response | `repositories/charter_views.py`（Phase 111 自产） | exact |
| `SettingKeys` 新键 + loader（歧义阈值/四维权重/charter 权重） | config | transform | `system/models.py:31-120` + `services/cursor_writeback.py:85-106` | exact |
| `tests/services/process_runtime/test_blueprint_*.py` | test | — | `test_classify_stage.py` | exact |
| delivery knowledge 检索消费（history_match） | service call | request-response | `recall_adapter.py` | exact |

---

## Pattern Assignments

### 1. process_runtime stage adapter → `blueprint_spec_gate.py`（含 HITL 挂起回路）

**Analog:** `server/services/process_runtime/clarify_adapter.py`（261 行，**§13.2 冻结**）

**结构要点：**
- 模块 docstring 是**契约书**而非说明：写清「替换谁」「fail-soft 回退到哪」「INV-6 落库经谁」「async 防裸 lazy-FK」四段（`clarify_adapter.py:1-30`）。类型别名 + 上界常量放模块级（`NeedsClarificationPolicy` / `_MAX_CLARIFY_ROUNDS = 6`，`:50-61`）。
- **策略可注入**：`__init__` 全 keyword-only、每个依赖 `x or DefaultX()` 兜底（`:95-107`）——测试可注 mock，生产零参构造。
- **回路顺序即正确性**：`clarify()` 的 6 步有显式编号注释，且注释解释「为什么是这个顺序」（`:132-137` 讲 builder 必须在 policy 之前，否则永不执行）。pending 短路（`:115`）→ 轮数上界（`:121-130`）→ 生成 → 落库 → emit。
- **上界兜底防自伤**：达 `_MAX_*_ROUNDS` 记 `xxx_cap_reached` 后**放行**而非挂死（`:122-130`）；重判时把已答内容拼进输入防同题死循环（`:170-175`）。
- 事件 emit 独立私有方法 + try/except 吞掉（`_emit_asked`，`:250-260`）；澄清正文**不进日志**，只记 `session_id` / 计数标量（`:119-120` 注释）。

**沿用：** `BlueprintSpecGateAdapter` 骨架照搬——「已有 open+blocking `BlueprintThread` → 短路挂起」对应 `ahas_pending`；「轮数上界」改为「歧义门重问上界」；「提问前查 `decision_log` 与 `resolved_thread_ids`」对应 `_collect_prior_answers` 的重判输入拼装。落库一律经 `BlueprintLifecycleService`（INV-6，对应 analog 的 `ClarificationService`）。
`BlueprintRepoConfirmAdapter`（确认门 stage）同一形态：pending 门 → 组装 options 快照 → 建 `BlueprintThread(kind=repo_confirmation, blocking=true)` → emit。

**避免：** 在新文件里 import/复用 `ClarificationService` 或 `delivery.Clarification`（CONTEXT 明令不复用）；把 stage 转移写在 adapter 里（engine 纯度——adapter 只返回 dict，转移由 handler 的 `StageOutcome` 决定）；异常上抛（会被 engine 通用 except 落 `failed`）。

---

### 2. LLM 打分/分类单调用 → `blueprint_ambiguity_score.py` / `blueprint_intent_classify.py`

**Analog:** `server/services/process_runtime/feature_classify.py`（307 行，只读参考；其自身即 `decompose_segments.py` 的逐段镜像，见 `feature_classify.py:6`）

**结构要点：**
- 模块级契约常量四件套：`__all__` 导出「异步入口 + normalize 纯函数 + key 组装器」、`_MAX_ITEMS`、`_VALID_*` 白名单元组、prompt 体积上限（`:36-42`）。
- **三层解析防御**：`_content_to_text`（兼容 reasoning 模型 content_blocks 列表，`:50-67`）→ `_parse_items_json`（```json 围栏 + 裸 JSON 双路，失败返 `[]` 不抛，`:70-86`）→ `normalize_*`（独立可测纯函数，`:89-147`）。
- **反幻觉归一**：白名单外的 key 丢弃、非法枚举回落保守值、`evidence_files` 经 `allowed_files` 过滤掉 LLM 编造路径、**「判 modify 但无证据 → 降级 unclear」**（`:114-135`）。这条「结论失去依据就降级、不猜」正是歧义打分要照抄的：分数无理由支撑 → 按保守分处理。
- prompt 拆 `_system_prompt()`（写死 JSON 形状 + 「判不出填 unclear，不要猜」）与 `_build_prompt()`（`### key` 分节 + 证据截断）（`:150-207`）。
- 异步入口五步骨架（`:226-259`）：`started = time.monotonic()` → try 内 lazy import → `ProviderConfigService.aresolve()` → 无 `default_model` 记 `xxx_no_default_model` 返 `None` → `build_chat_model(..., streaming=False)` → `with use_call_source(CallSource.XXX): await model.ainvoke(...)`。
- 观测三事件全带 `category="sampling"` / `component="process_runtime"` / `duration_ms`，completed 事件带**分桶计数**（`new_count/modify_count/unclear_count`，`:287-296`）；失败分支 `redact_secrets_in_text(str(exc))` 后 warning 返 `None`（`:298-306`）。

**沿用：** 歧义四维（goal/boundary/constraint/acceptance）打分用同一骨架：`normalize_ambiguity_scores()` 纯函数把每维强转 `float` 并 clamp 到 `[0,1]`、缺维补保守默认、`reason` 截断；`call_source=CallSource.BLUEPRINT_SPEC_GATE`（已注册，`agents/call_source.py:115`）。加权总分与阈值比较**放纯函数**（可单测、可被 golden set 评估），LLM 只出分数与理由。意图分类用 `CallSource.BLUEPRINT_DECOMPOSE`（`:112`）或按 LOGGING-SPEC 新登记值，`_VALID_INTENT = ("greenfield", "brownfield", "fix")` 对齐 schema 枚举。
completed 事件带 `above_threshold_count` / 各维均分等分桶指标（对齐 analog 的分桶计数），供 115 前端与 golden set 消费。

**避免：** 修改 `feature_classify.py` / `decompose_segments.py`（前者是 technical_plan 运行文件，后者 §13.2 冻结）；LLM 失败时抛异常或落 fail（必须返 `None` + 上游按保守值降级，本相位保守值 = 判定「需澄清」而非「放行」，规格门 fail-closed）；把阈值/权重硬编码进模块常量（见第 8 类，必须走 SystemSetting，模块常量只作缺省兜底）。

---

### 3. 路由证据融合与 breakdown 组装 → `blueprint_route.py`

**Analog:** `server/services/process_runtime/repo_router_adapter.py`（83 行，接线骨架）+ `recall_adapter.py`（273 行，history_match 分量的检索消费范式）+ `repo_router_v2.py:61-95`（输出契约，**§13.2 冻结**）

**结构要点（`repo_router_adapter.py`）：**
- 模块 docstring 写死边界：「本 adapter **不重写路由逻辑**——只做编排接线（取数 + 候选范围解析 + 结果映射）；RepoRouterV2 自带的降级链不另加容错」（`:8-10`）。
- 空 query 短路：不调 router，返回 `{"candidates": [], "router_version": "skipped", "auto_selected": False}`（`:36-38`）——保持 dict 形状恒定，下游无需判空分支。
- 结果映射是**显式逐字段列表推导**（`:44-51`），不 `to_dict()` 整包透传——新增分量时形状变更点唯一。
- 候选范围三级优先级解析独立成 `_resolve_repository_ids`（`include_repos` → work_item.space 仓 → None 全库，`:58-67`）；同步 ORM 经 `@sync_to_async` 私有方法（`:69-82`），绝不在 async 里裸访问 lazy-FK。

**RepoRouterV2 输出契约（只读）：** `RepoRouteCandidateV2{repo_id, repo_name, score, confidence, reasoning, sub_project, sub_project_paths, matched_node_paths}` + `to_dict()` 里 `score` 已 `round(..,4)`（`repo_router_v2.py:61-84`）；`RepoRouteResultV2{candidates, router_version ∈ v2|v2_stage0_only|v1_fallback, auto_selected}`（`:87-94`）。

**history_match 分量（`recall_adapter.py`）：**
- `search_similar(query, user=..., top_k=..., entity_kinds=[...], repository_ids=[...], include_document_kind=...)` 全 keyword-only（`:97-107`）；kinds 取 `code_change` / `tech_plan` 时 `include_document_kind=False`。
- 权限 fail-closed：actor 经 `@sync_to_async def _resolve_actor`（`:254-262`），`created_by` 为空**直接透传 None**（绝不伪造/提权）。
- 检索整段 try/except → warning（异常先 `redact_secrets_in_text`）+ 返回空 hits，best-effort 不阻断（`:108-119`）。
- 召回埋点 `_record_trace`：`arecord_retrieval_trace(None, kind=RetrievalTrace.Kind.CHUNK, payload={source, session_id, kinds, result_count, per_kind_counts, scores, top_score, duration_ms}, ...)`，整段吞异常（`:180-232`）——**LOGGING-SPEC 强制的召回埋点，新召回点必须照办**。

**沿用：** `BlueprintRouteAdapter` = `repo_router_adapter` 骨架 + 两个加性分量。调用 `RepoRouterV2.route(query, top_k=, repository_ids=, use_llm=True)` 取**原样输出**，在 adapter 内做：① 逐候选查 `RepoCharter` 算 `charter_match`（owned_domains 含 `status=planned` 加分 / boundaries 命中判负 / `evolution=maintenance_only|deprecated` 降权）；② 经 `DeliveryKnowledgeSearchService.search_similar(entity_kinds=[code_change, tech_plan])` 算 `history_match`；③ 按 feature_point `intent` 取权重向量加权。
breakdown 组装成独立纯函数 `build_score_breakdown(base: RepoRouteCandidateV2, charter_match: float, history_match: float, weights: dict) -> dict`——**各项之和恒等于总分**（写断言级单测，对齐 CONTEXT「断言写机制级」），`repo_associations.routing_evidence` 字段形状不变。事件写 `ConvergenceSessionEvent`（`blueprint_*` 类型，见 `event_taxonomy.py:115-128`，只新增不改既有）。
章程条目被引用 → 产 `citation.source_type=repo_charter`。

**避免：** 改 `repo_router_v2.py` 任何一行（§13.2 + §5.7 第 4 条双重明令）；把 charter/history 分量塞进 RepoRouterV2 的 Stage1 prompt 里改其内部（融合只在 adapter 层）；`to_dict()` 整包透传导致新字段污染既有 `routing` 形状；漏 `RetrievalTrace` 埋点（新增召回必写，MCP + AI 对话两条链都要覆盖）。

---

### 4. 容器 fan-out dispatch + 回调消费 → `blueprint_research_adapter.py` + `callbacks.py` 新分支

**Analog（派发侧）:** `server/services/process_runtime/research_adapter.py`（398 行，**§13.2 冻结**）

**结构要点：**
- 幂等白名单常量：`_DISPATCHABLE_STATUSES = (PENDING, STALE)`，注释写清「resume/re-advance 时跳过 running/done/failed，既不重派已完成容器也不重复合成」（`:40-43`）。
- filter → fan-out 两段：候选按 confidence 分 deep/light 两桶并**按 repo_id 去重**（`:76-90`）；deep 桶前先 `_count_online_runners()`（3 倍心跳窗口 120s，`:379-390`），**无 runner 则整体降级 light 不阻断**（`:92-100`）。
- **单仓错误隔离（WR-02）**：每个 task 的 dispatch 包 try/except → `mark_failed` + `_emit_failed` + `continue`，绝不上抛（上抛会被 engine 通用 except 拖垮整个 session，`:114-131`）。
- 派发五步（`_dispatch_deep_task`，`:153-222`）：缺 `git_url` 直接判失败不起占位容器（`:164-169`）→ `session_id = f"research-{task.id.hex[:12]}-{uuid4().hex[:6]}"`（**必须带 uuid 后缀**，否则 stale 重跑撞 UNIQUE，`:171-176`）→ 建 `AgentSession` + `SubAgentSession(TaskType.PLAN, node_execution_id=..., last_output={source, plan_session_id, research_task_id, repository_id})`（**回调路由靠 `last_output`，不靠 session_id 命名**，`:177-197`）→ `DispatchTask(...)` + `with use_call_source(...): await get_dispatcher().dispatch(...)` → `mark_running` + `_emit_started`。
- `_build_dispatch_metadata` 逐键 env（`:337-377`）：只读语义双层拦截 `env_FRIDAY_TASK_MODE=explore` + `env_FRIDAY_TASK_TASK_MODE=explore`；Claude runtime 与 git token 各自 try/except 吞掉（缺凭证容器内自报错，不阻断调度）；SSH→HTTPS 改写后经 `metadata.pop("_repo_url")` 传出。
- prompt 由 **server 端权威 session 状态**构造（`:256-288`），非外部用户原文拼执行指令；召回/verdict 摘要各自 `@staticmethod` 截断（`:290-314`）。

**Analog（回调侧）:** `server/subagent/api/callbacks.py:1699-1828`（plan_research）与 `:1830-1930`（repo_verify，第二个同构分支——证明「加一条新链」的标准做法）

**结构要点：**
- 三件套函数：`_is_xxx(session)` 路由判定（`task_type` + `last_output.source` 双条件，`:1702-1708`）→ `_aload_xxx_task(session)` 反查业务 task（缺 id / 已终态 → 返 None 使调用方 no-op 幂等，`:1711-1733`）→ `_handle_xxx_completion/_failure`（`:1745-1827`）。
- 挂载点：`_handle_completed` / `_handle_failed` 里各包一层 try/except 调用，注释「永不阻塞主流程」（`:969-984`、`:1042-1056`）；terminal 时先 `arevoke_task_tokens(session.session_id)`（`:945-947`、`:1029-1031`）。
- 结果解析失败 = 失败：`parse_partial_plan_content` 返 None → `mark_failed({"reason": "empty_or_unparseable_result"})` + emit failed（`:1773-1784`）；barrier 统一在末尾触发且幂等（`_trigger_research_barrier`，`:1736-1742`）。
- 写业务表**只经 service**（`ResearchService.record_partial` / `mark_failed`），回调不裸写 ORM（INV-6）。

**沿用：** 新建独立文件 `blueprint_research_adapter.py`（**复制范式，不 import 冻结模块**）。`last_output` 带 `{"source": "blueprint_research", "blueprint_session_id", "research_task_id", "repository_id"}`；callbacks.py 加 `_is_blueprint_research` / `_aload_blueprint_research_task` / `_handle_blueprint_research_completion|_failure` 三件套并在 `_handle_completed/_handle_failed` 各加一段 try/except 调用（与 repo_verify 分支完全对称，是 callbacks.py 上**唯一允许的改动形状**）。fitness 产物解析照 `parse_verify_verdict`（`:1842-1864`）——优先结构化透传（output 已含 `fitness`），否则从 `output["text"]` 提 JSON；缺 `verdict` 键即视为不可解析。
direct 深调研起容器 / indirect 轻量走 server 端合成，对应 analog 的 deep/light 双桶（`_synthesize_light_partial`，`:316-335`）；「人工升级为深调研」= 把该仓 task 置回 `PENDING` 后重跑 dispatch（幂等白名单天然支持）。
reroute ≤2 轮计数存 `ConvergenceSession.stage_state`，超限**升确认门**而非落 failed（对齐 analog 的 `_MAX_CLARIFY_ROUNDS` 放行语义）。

**避免：** 改 `research_adapter.py`（§13.2）；沿用确定性 `session_id`（stale 重跑撞 UNIQUE）；回调路由依赖 session_id 前缀（必须靠 `last_output`）；单仓失败上抛；在回调里裸写 `RepoResearchTask.objects.update`。

---

### 5. 任务 token + env 注入（PLAN 链补齐）

**Analog:** `server/workflows/nodes/ai/coding.py:1915-1940`（注入面）+ `server/access_tokens/services.py:32-102`（铸造/吊销）

**结构要点：**
- 注入片段逐字（`coding.py:1927-1940`）：

```python
tools_env: dict[str, str] = {}
base = getattr(settings, "FRIDAY_BASE_URL", "").rstrip("/")
if base:
    tools_env["env_FRIDAY_TASK_TOOLS_ENDPOINT"] = f"{base}/api/tools/execute/"
    tools_env["env_FRIDAY_TASK_KNOWLEDGE_ENDPOINT"] = base   # 不带路径，task 侧自拼 /api/mcp/tools/{name}/
if dispatch_user is not None:
    from access_tokens.services import mint_task_token
    plaintext = await mint_task_token(dispatch_user, session_id, config.get("timeout_seconds", 1800))
    tools_env["env_FRIDAY_TASK_USER_TOKEN"] = plaintext
```

- **契约：空值不注入该键**（向后兼容降级——task 侧无 endpoint 就不挂 MCP server；`dispatch_user` 为 None 则不注入 token，不阻塞 dispatch，`:1918-1922`）。
- endpoint 必须由 `settings.FRIDAY_BASE_URL` 推导，**绝不用 runner callback_url**（Pitfall 1：错用会打到 runner 中转 → 工具调用 404，`:1916-1918`）。
- `metadata` 用 `**xxx_env` 分组展开合并，每组带行尾注释标注来源 phase（`:1974-1986`）——新增分组不动既有键。
- `mint_task_token(user, session_id, timeout_seconds) -> str`：明文由 `generate_pat()` 内存生成、DB 只存 `hash_token(明文)`，`session_id` 即 SubAgentSession 的 session_id（终态吊销按此定位）；结构化事件只记 `session_id/user_id/expires_in_seconds`，**连指纹都不记**（`services.py:43-63`）。过期余量 `TASK_TOKEN_EXPIRY_MARGIN = 10min`（`:29`）。
- 吊销 `arevoke_task_tokens(session_id)` 幂等 best-effort，异常吞掉但留 warning（`:67-102`），已由 callbacks 终态统一调用——**新链路无需自己接**。

**沿用：** `blueprint_research_adapter._build_dispatch_metadata` 在 `research_adapter` 现有 metadata（explore 双键 + Claude runtime + git token）基础上**补 tools_env 三键**。`dispatch_user` 来源 = `ConvergenceSession.created_by`（经 `@sync_to_async` 解析，参照 `recall_adapter._resolve_actor`），为空则不注入（不伪造 actor）；`timeout_seconds` 传 `_RESEARCH_TIMEOUT`（30min）保持余量语义一致。章程内容随 prompt 注入。

**避免：** 明文 token 落盘 / 进日志 / 进 `ConvergenceSessionEvent` payload（PAT-02 底线）；扩容器 MCP 白名单（CONTEXT 明确留给 113 Context Bus）；从 DB 反取明文（不可能且被禁——DB 只有 sha256）；用 runner callback_url 拼 endpoint。

---

### 6. stage graph 注册项 → `builtin_processes.py` 新增 `technical_blueprint`

**Analog:** `builtin_processes.py:207-252`（`_TECHNICAL_PLAN_STAGES`）+ `:306-313`（注册）+ `registry.py:33-56`（`StageDef` / `ProcessDefinition` 契约）

**结构要点：**
- handler 签名恒为 `async def _h_xxx(session: Any, engine: Any) -> StageOutcome`；**handler 只跑 adapter 并返回转移 event，绝不自行 transition**（engine 纯度，模块 docstring `:11-12`）。
- handler 内部三动作：`result = await engine.deps.xxx.yyy(session)` → `await engine.session_service._emit_event(EVENT_XXX, session, trace)` → `return StageOutcome(event=..., stage_state_update={...})`（`_h_route`，`:107-117`）。
- **缺依赖 pass-through 不报错**：`getattr(getattr(engine, "deps", None), "classify", None) is None` → 直接返回 outcome（`_h_classify`，`:145-147`）——新 stage 必须能在 deps 未注入时安全穿过。
- 挂起类 stage：`StageDef(pausable=True, wait_status="waiting_clarification"|"waiting_event")` + transitions 里带 **self-loop**（`"needs_clarification": "clarify"` / `"research_dispatched": "research"`，`:230-241`）。
- 终态用 sentinel `STAGE_DONE` / `STAGE_FAILED`（`registry.py:29-30`）；限次回退用模块级常量（`MAX_MERGE_RETRIES = 1`，`:38-39`）+ handler 内比对 `attempt` 决定回退 or `exhausted`（`_h_merge`，`:179-204`）。
- 注册在文件尾部 `register_process_type(ProcessDefinition(process_type=, artifact_type=, initial_stage=, stages=))`（`:306-313`）；registry 靠 `_ensure_builtins()` 惰性 import 本模块触发（`registry.py:86-92`），**新注册项写进同一文件即自动生效**。

**沿用：** 新增 `_h_bp_intake / _h_bp_decompose / _h_bp_spec_gate / _h_bp_route / _h_bp_repo_research / _h_bp_reroute / _h_bp_repo_confirmation` 七个 handler + `_TECHNICAL_BLUEPRINT_STAGES` 字典 + 一条 `register_process_type(...)`。三个 pausable：`spec_gate`（`wait_status="waiting_clarification"`，self-loop `needs_clarification`）、`repo_research`（`wait_status="waiting_event"`，self-loop `research_dispatched`）、`repo_confirmation`（`waiting_confirmation` 或复用 `waiting_clarification`，self-loop `needs_confirmation`）。`reroute` 用 `MAX_REROUTE_ROUNDS = 2` 常量 + handler 内比对，超限转 `repo_confirmation`（**不转 `STAGE_FAILED`**——CONTEXT「绝不静默失败」）。113 的 `repo_plan / merge` 后续只往同一字典追加键。

**避免：** 改 `_TECHNICAL_PLAN_STAGES` 任何键值或既有 `_h_*` 函数（§13.2 收敛点）；在 handler 里调 `session_service.transition`；新 stage 硬依赖 deps 而不做 `getattr` 兜底；超限落 `STAGE_FAILED`。

---

### 7. HITL 门 REST 多动作端点 → 确认门 5 动作

**Analog:** `server/repositories/charter_views.py`（107 行，Phase 111 本里程碑自产，风格优先）

**结构要点：**
- 模块 docstring 列**端点清单 + 权限 + 写入纪律**三段：「视图零 XxxModel 写操作，全部委托 service（源码扫描守护会扫本文件）；读路径允许视图直接查询」（`:1-15`）。
- 一动作一 View 类，类 docstring 首行写死 `METHOD /path/ —— 语义`（`:29-30`、`:49-55`、`:81-86`）；`from adrf.views import APIView` + `permission_classes = [IsAuthenticated]` + `async def get/post(self, request, repository_id)`。
- **全部 import 在方法体内 lazy**（`:35-36`、`:60-62`）——规避 import 环。
- 序列化必须 `data = await sync_to_async(lambda: XxxSerializer(obj).data)()`（`:45`、`:77`、`:105`），绝不在 async 里裸取 `.data`。
- 状态码语义分层：不存在 → 404 + 中性 `{"detail": "..."}`；service 返 `None`（LLM/依赖不可用）→ 503；`ValueError` → 404（`:42-43`、`:71-75`、`:102-103`）。
- body 防御：`body = request.data if isinstance(request.data, dict) else {}`，非 dict 字段按缺省处理，**白名单归一放 service 层**（`:94-96`）。

**沿用：** 五动作（`confirm` / `remove_repo` / `add_repo` / `reclassify_role` / `edit_responsibility`）建 `blueprint_gate_views.py` 平级新文件，每动作一个 View 类 + 一条 `path(...)`（kebab-case name），或单 View + `action` 字段分派——若用后者，`action` 必须走视图内联 `serializers.Serializer` 的 `ChoiceField` 白名单校验（`route_views.py` 的内联 serializer 范式）。全部写操作委托 `BlueprintLifecycleService`（INV-6），视图零 ORM 写；确认动作执行者经 111 的 upsert 逻辑自动进 `BlueprintReviewer`。

**避免：** 同步 `rest_framework.views.APIView`（必须 adrf async）；视图里直接写 `repo_associations` / `RepoCharter`；裸取 serializer `.data`；往 `views.py` 巨石文件加代码；`add_repo` 等触发重调研的动作在视图里同步等待容器（应只置 task 为 PENDING + 推进 stage，由回调驱动）。

---

### 8. SystemSetting 新键注册与读取 → 歧义阈值 / 四维权重 / charter 权重

**Analog:** `server/system/models.py:31-120`（`SettingKeys` 常量声明）+ `server/services/cursor_writeback.py:85-106`（loader 范式）

**结构要点：**
- `SettingKeys` 是**纯常量类**（非 Enum），按功能分组、每组上方一段中文注释写清：value 的 JSON 形状、由谁写入/消费、未配置时的兜底行为。样板见 `CURSOR_WRITEBACK_CONFIG`（`models.py:72-76`：「value 为 JSON：{min_length:int, ...}」+「未配置时用 xxx 的合理默认值」）与 `CODE_INDEX_EXCLUSION_GLOBAL_DEFAULTS`（`:91-95`，键名带点分命名空间 `code_index.exclusion.global_defaults`）。
- loader 是 `@sync_to_async def _load_xxx() -> Frozen配置对象`（`cursor_writeback.py:85-106`）：`SystemSetting.objects.filter(key=...).first()` → 空/空值返默认 → `json.loads` → **非 dict 返默认** → 逐字段 `int()/float()` 强转带默认 → **整段 `except Exception` 返默认**，注释「配置异常回退默认，绝不反噬」。
- 配置对象与**纯函数判定**分离：`evaluate_quality_sync(content, existing, thresholds)` 是可单测纯函数，异步入口只负责「读配置 + 调纯函数」（`:64-82`、`:109-124`）。
- 另一种口径（Django settings + env 覆盖）见 `repo_router_v2.py:46-58` 的 `_STAGE1_DEFAULTS` + `_stage1_conf()`「调用时读取而非导入时」，以及 `recall_adapter.py:128-178` 的 `_resolve_recall_config`（畸形配置逐项 warning + 逐项降级）。**本相位按 CONTEXT 走 SystemSetting**（运行时可调，不需重启），但畸形配置的逐项降级 + warning 照抄 `recall_adapter`。

**沿用：** 新增 `BLUEPRINT_SPEC_GATE_CONFIG = "blueprint.spec_gate.config"`（`{threshold: float, weights: {goal, boundary, constraint, acceptance}}`，默认总分阈值 0.20）与 `BLUEPRINT_ROUTE_WEIGHTS = "blueprint.route.weights"`（`{greenfield: {...}, brownfield: {...}, fix: {...}}`），带点分命名空间 + 完整形状注释。loader 用 `@sync_to_async` + 全兜底，模块常量 `_DEFAULT_*` 作缺省；判定逻辑（加权求和 / 阈值比较 / breakdown 组装）留纯函数便于 golden set 评估。

**避免：** 阈值/权重硬编码在 adapter 里（CONTEXT 明确外置）；loader 抛异常；配置读取放模块导入期（必须调用时读，否则 `override_settings`/运行时改值不生效）；判定逻辑与 IO 混在一个函数里（不可单测）。

---

### 9. pytest：编排 stage 测试（mock LLM + mock 容器）

**Analog:** `server/tests/services/process_runtime/test_classify_stage.py`（138 行，stage 行为测试权威样板）

**结构要点：**
- 模块 docstring 用编号列**这个文件守哪几件事**（`:1-8`）——第一条通常是「既有链路零扰动」。
- 每个 test 双装饰器 `@pytest.mark.django_db` + `@pytest.mark.asyncio`（本目录用装饰器而非 `pytestmark`），裸 async 函数无 class（`:40-42`）。
- 会话工厂私有 helper `async def _make_session(stage_state=None)` 直接 `acreate`（`:25-31`）；mock 依赖用 `SimpleNamespace(classify=AsyncMock())` 注入 engine 的 `deps`（`:34-37`、`:46-49`）——**不 patch 模块全局**。
- 断言经 `await Model.objects.aget(id=...)` 重读 DB（`:54-56`），不信内存对象。
- 事件断言：`engine.session_service._emit_event = AsyncMock()` 后按事件名过滤 `spy.call_args_list`，断言条数 == 1 且 `call.args[2] == {期望 payload}`（`:100-119`）。
- 必测四类：deps 未注入 pass-through（`:61-70`）、deps 整体 None（`:75-82`）、正常路径落 stage_state + emit（`:87-119`）、**依赖抛异常经 engine 兜底落 `failed` 且 `error["stage"]` 正确**（`:124-138`）。

**沿用：** 按 stage 拆文件 `test_blueprint_spec_gate_stage.py` / `test_blueprint_route_stage.py` / `test_blueprint_research_stage.py` / `test_blueprint_confirm_gate.py`，加纯函数测试 `test_blueprint_route_breakdown.py`（无 DB，断言**各分量之和 == 总分** + 章程分量对排序的可拆解影响，对齐 CONTEXT「断言写机制级而非结果级名次」）。
LLM mock：patch `aclassify_*` / `ascore_*` 异步入口返回固定 dict 或 `None`（**必测 `None` 降级路径**），不 mock `build_chat_model`。
容器 mock：patch `runners.dispatcher.get_dispatcher` 返回 `AsyncMock`，断言 `DispatchTask.metadata` 含 `env_FRIDAY_TASK_KNOWLEDGE_ENDPOINT` / `env_FRIDAY_TASK_USER_TOKEN`（断言口径见 `tests/test_task_token_lifecycle.py:264`、`tests/test_remote_tool_dispatch.py:306`）。
async service 跨线程写库的测试须加 `transaction=True`（111-PATTERNS 第 9 类的教训）。

**避免：** class 风格 TestCase；patch 模块级全局而非注入 deps；只断言内存对象不重读 DB；漏「依赖异常 → failed」与「LLM 返 None → 保守降级」两条负向路径。

---

### 10. delivery knowledge 检索消费（history_match）

**Analog:** `server/services/process_runtime/recall_adapter.py`（273 行，非冻结，可 import 复用其常量但**新建自己的 adapter**）

结构要点见第 3 类「history_match 分量」段（`:66-126` 主流程、`:180-232` 埋点、`:234-252` 按 kind 截断、`:254-262` actor 解析）。补充：

- **单查后按 kind 截断，不分 kind 多查**——注释解释了取舍：多查 N 倍成本且跨查 score 出自不同排序不可比（`:75-79`）。`top_k` 按 `sum(limits.values()) * 2` 超采样留截断余量（`:101`）。
- 用路由候选仓 `repository_ids` 收窄召回（`:87-90`）。

**沿用：** history_match 只取 `entity_kinds=[code_change, tech_plan]`（CONTEXT 明确），`include_document_kind=False`；查询 query 用 feature_point 文本而非整单需求（「同类需求近期实际合进哪个仓」的语义粒度）；埋点 payload 的 `source` 改为 `blueprint_route_history`，其余字段形状不变。

**避免：** 伪造 actor 提权（`created_by` 为空就传 None，让权限层返空）；把召回正文/query 原文写进 trace payload 或日志（只记指标与关联键）；检索异常上抛。

---

## Shared Patterns（跨文件通用）

### best-effort 不反噬业务
**Source:** `feature_classify.py:298-306`、`recall_adapter.py:231-232`、`research_adapter.py:121-131`、`access_tokens/services.py:91-102`
LLM / 检索 / 事件 / 埋点 / 凭证解析一律 `except Exception` 吞掉 + `logger.warning`（异常文本先 `redact_secrets_in_text`）+ 返回降级值。**唯一例外**：规格门的降级方向是 fail-closed（判「需澄清」），不是放行。

### structlog 三事件 + 分类
**Source:** `feature_classify.py:234-305`
`xxx_started / xxx_completed / xxx_failed`，全带 `category="sampling"`（编排内部步骤）、`component="process_runtime"`、`duration_ms=round((time.monotonic() - started) * 1000, 2)`；completed 带分桶计数。**用户可归因动作**（确认门 5 动作、token 铸造）用 `category="caller"` + `initiated_by_user_id`（见 `access_tokens/services.py:61-62`）。

### INV-6 单一写入
**Source:** `research_adapter.py:8-12`、`callbacks.py:1767-1786`、`charter_views.py:12-14`
adapter / 回调 / 视图**零 ORM 写**，全部委托 service（本相位 = `BlueprintLifecycleService` / `charter_service`）。模块 docstring 显式声明这条，配源码扫描守护测试。

### async ORM 防裸 lazy-FK
**Source:** `clarify_adapter.py:28-29`、`repo_router_adapter.py:69-82`、`recall_adapter.py:254-262`
用 `session_id` 标量 / `.values()` / `.acount()` / `.afirst()`；必须取 FK 对象时经 `@sync_to_async` 私有方法。

### 容器 metadata 逐键 env
**Source:** `coding.py:1974-1986`、`research_adapter.py:337-377`
`env_` 前缀（runner 侧自动 TrimPrefix）；**空值不注入该键**（向后兼容降级）；按来源分组 `**xxx_env` 展开并注释来源 phase。

---

## No Analog Found

| 内容 | 说明 |
|---|---|
| 「五动作单端点分派」的 REST 形态 | 代码库现有 HITL 端点都是一动作一 View（charter 三端点、route_views）。建议**沿用一动作一 View**（analog 完备）而非发明 action 分派；若坚持单端点，`action` 走内联 `ChoiceField` 白名单。 |
| `charter_match` 加性分量的打分算法本体 | 无先例（章程是 111 新产物）。算法自写为纯函数（owned_domains/boundaries/evolution 三规则 + intent 权重向量），形态沿用 `wave_layering.py` 纯函数范式（见 111-PATTERNS 第 2 类）。 |
| `blueprint_*` 事件类型的新增 | `event_taxonomy.py:115-128` 已有 4 个 `blueprint_*` 常量与独立 `BLUEPRINT_EVENTS` frozenset（不计入 `ALL_EVENTS`）。本相位往同一集合追加（`blueprint.spec_gate.*` / `blueprint.route.*` / `blueprint.repo_research.*` / `blueprint.confirmation.*`），**不改既有类型与 payload**（§13.2 第 3 条）。 |

## Metadata

**Analog search scope:** `server/services/process_runtime/`、`server/subagent/api/`、`server/access_tokens/`、`server/workflows/nodes/ai/`、`server/repositories/`、`server/system/`、`server/codegraph/services/`、`server/tests/services/process_runtime/`
**Files scanned:** 约 60 个候选路径，精读 13 个 analog 文件/切片
**Pattern extraction date:** 2026-07-30
