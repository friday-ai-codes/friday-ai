# Phase 113: 分仓方案与融合（阶段 2/3）+ Blueprint Context Bus - Research

**Researched:** 2026-07-30
**Domain:** `server/services/process_runtime` 蓝图流水线 —— RepoPlan 落位 / 容器 plan 模式 / 融合装配 / stage 追加
**Confidence:** HIGH（全部结论来自本 worktree 源码逐行核对，附文件:行号；无外部依赖查询）
**Scope:** 本文只覆盖 4 个指定主题 + Pitfalls，**不**覆盖 Context Bus 模型设计、MCP 工具扩展、波次预排算法（属 planner/discretion 面）

## Summary

四个融合面全部**已具备可直接消费的稳定契约**，无需改动任何冻结文件即可接续：

1. **RepoPlan 落位**：`PartialPlan.content` 是无 schema 约束的 `JSONField`（模型层不校验），112 的 fitness 段与 §7 五键平级共存 —— 新增 `repo_plan` 段是纯加性动作，`record_partial(task, content)` **整体覆写 content 并置 task=DONE**，这是本相位最大的一处陷阱（见 Pitfall P-1/P-2）。
2. **容器 plan 模式**：`dispatch()` 已有 `force_deep_repository_ids` 这一 keyword-only 先例；`_build_prompt` / `_build_dispatch_metadata` / `last_output.source` 三处是精确扩展点，**默认值兼容策略 = 新增 `mode: str = "research"` 关键字，缺省逐字等价于 112 现有路径**。
3. **融合装配**：`validate_blueprint` / `citation_coverage` 均为**零 ORM 纯函数**、签名简单、绝不外抛；`ArtifactService.add_version` 自带 content_hash 幂等（同 hash 复用 current 不翻版本），融合重试的幂等风险因此**已被上游消除**。`must_haves` 在 111 **只有 jsonschema 定义、没有派生代码** —— 需新写。
4. **stage 追加**：接续点只有两处物理改动（一个 transitions 值 + 追加两个 StageDef），`entrypoint.build_blueprint_engine` 的 deps 名单需同步加两个属性名（有等价性断言守护）。

**Primary recommendation:** 新建 `blueprint_repo_plan.py` + `blueprint_merge.py` 两个独立文件；对 `blueprint_research_adapter.py` 只做**加性关键字扩展**（`mode="research"` 默认值），对 `builtin_processes.py` / `entrypoint.py` 只做纯追加。

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**RepoPlan 分仓方案**
- 载体沿用 `PartialPlan.content`，在其中新增 `repo_plan` 段（同一仓的 fitness 调研结论与方案同源可追溯，无需新表）
- 产出方式：direct 仓起容器（复用 112 的 `blueprint_research_adapter` 派发面，新增 plan 模式参数区分调研/拟方案两类 prompt）；indirect 仓由服务端 LLM 合成能力引用清单（轻量，不起容器）
- 澄清与补调研复用既有机制：`BlueprintThread(kind=ai_clarification, blocking)` + dispatch 增量能力；单仓定向补调研走已有 `force_deep_repository_ids` 通路，不新建机制
- RepoPlan 按 DESIGN §5.3 形状做 jsonschema 校验（新增 `blueprint_repo_plan_schema` 或并入 blueprint_schema 模块的独立 schema 常量）：`repository_id/role/responsibility/fitness/current_state/impl_items/apis_provided/apis_consumed/local_impact/risks/open_question_thread_ids`；不合格触发有界重试（≤2 轮），仍不合格开澄清线程而非静默降级

**Blueprint Context Bus（会话级共享上下文）**
- 新模型 `delivery.BlueprintContextEntry`：`convergence_session FK / project FK / key / kind(finding|api_surface|contract|decision|dependency_claim|question) / repository_id / content JSON / produced_by / seq(会话内单调) / status(active|superseded)`；**不复用 `ProjectMemory`**
- key 约定前缀：`repo:{id}.api_surface` / `contract:{name}` / `decision:{thread_id}` / `dependency:{from}->{to}`
- 容器实时读写：扩容器知识 MCP 白名单新增 `read_blueprint_context` 与 `report_blueprint_context`（服务端校验只能写本会话、内容过 `redact_secrets_in_text`）；写入即对所有并行容器可见（server-authoritative）
- 等待原语两档：**短等待** `await_blueprint_context(key_pattern, timeout)`（对齐 `ask_user` 保活轮询，超时未命中由 agent 降级，绝不无限挂）；**长等待** 容器以 `waiting_context` 结构化结果退出（携 partial 产物 id + 等待声明），编排层登记依赖，就绪后重新派发该仓容器（prompt 带 partial 引用续作）
- 第一道防线是 wave 预排：repo_plan 阶段按 API provider/consumer 关系预排波次（provider 仓先行）
- 死锁防护：编排层检测互相等待环 → 立即判定并抛澄清由用户裁决，不靠超时兜底
- 沉淀：会话结束后有长期价值的条目走 distill 管道产 `ProjectMemory` 草案（人工 confirm 生效）

**merge 融合装配**
- 新建 `blueprint_merge.py`：**绝不修改**冻结的 `architect_merge_adapter.py`；主 agent 分节多次调用而非单次巨 prompt
- 六段来源分工——确定性投影优先，LLM 只写需要推理的部分：`repo_associations` ← 确认门锁定产物直接投影；`current_state_analysis` ← 各仓 `PartialPlan.content.current_state` 直接投影（citations 一并带上）；`implementation_overview`/`api_contracts`/`interaction_flows`/`impact_analysis` ← LLM 分节起草后装配；`must_haves` ← 由 requirement_spec 与实现项确定性派生（复用 111 的派生思路）
- 跨仓 API 对账用**纯函数**（非 LLM 自查）：consumed 契约找不到 provider → 标 `availability=needs_support` 且要求 `support_repository_id` 出现在 `repo_associations`（缺失即抛澄清）；provider/consumer 字段不一致抛澄清，绝不静默拍板
- 装配后强制门：过 `validate_blueprint`（111）+ 引用覆盖率门（复用 111 的 `blueprint_quality`，阈值走 SystemSetting 可配）；不达标按归因回退——单仓问题回该仓 `repo_plan`、融合问题重融合，合计上界 2 轮，超界带未决项进入 114

**状态、stage 与观测**
- 阶段 2/3 蓝图状态 = `drafting`（一律经 `BlueprintLifecycleService`）；有 open+blocking 线程时派生显示 `needs_clarification` 并记 `return_stage`
- `builtin_processes.py` 的 `technical_blueprint` 追加 `repo_plan → merge` 两 stage，**只加不改**，`_TECHNICAL_PLAN_STAGES` 零触碰
- `call_source` 复用 111 已注册的 `blueprint_repo_plan` / `blueprint_merge`，**不新增枚举值**
- 观测：总线条目读写记 `sampling`，waiter 登记/命中/超时与「谁在等谁」记 `caller`（`component=process_runtime`）并写 `ConvergenceSessionEvent`

### Claude's Discretion
- 分节 LLM prompt 的具体切分与措辞、对账函数内部结构、总线 key 命名细节、波次预排算法实现、测试组织自行决定，遵循 CONVENTIONS.md 与 111/112 已建立的 `blueprint_*` 模块风格。

### Deferred Ideas (OUT OF SCOPE)
- 母子蓝图拆分（schema 支持互引，编排级拆分另议）→ Future Requirements
- 总线条目的跨会话复用（当前仅会话级）→ 观察 distill 效果后再议
- FLOW-02 的「替代建议」结构化字段（Phase 112 残留 PARTIAL）→ 若本相位需机器消费该建议则一并补，否则留 115
</user_constraints>

---

## 主题 1：RepoPlan 落位

### 1.1 `PartialPlan` 字段清单（模型层零校验）

`server/delivery/models/research_task.py:89-118` [VERIFIED: 源码]

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `UUIDField(pk, default=uuid4)` | — |
| `research_task` | `FK(RepoResearchTask, CASCADE, related_name="partial_plans")` | **一 task 可多行**（见 Pitfall P-3） |
| `content` | `JSONField(default=dict)` | **模型层不校验**（`:100` 注释「校验/写入归 39-02 ResearchService，模型层不校验」）→ 加 `repo_plan` 段零 migration |
| `valid` | `BooleanField(default=True)` | RESEARCH-03 stale 失效位 |
| `invalidated_reason` | `CharField(64, blank, default="")` | `"clarification"` / `"repo_reindexed"` |
| `content_hash` | `CharField(64, blank, default="")` | sha256 hex，由 service 本地算 |
| `created_at` | `DateTimeField(auto_now_add)` | **取最新的唯一排序依据** |

Meta：`db_table="delivery_partial_plan"`，`indexes=[Index(fields=["research_task", "valid"])]`（`:109-115`）。
**结论：新增 `repo_plan` 段无需 migration。** `makemigrations --check` 应保持退出码 0。

### 1.2 `content` 现状结构（112 的 fitness 段长什么样）

深调研与轻量合成**同形**，权威样本见 `blueprint_research_adapter.py:702-720`（轻量合成 return）与 `callbacks.py:1999-2006`（容器解析归一）[VERIFIED: 源码]：

```jsonc
{
  // ── §7 既有五键（39-02 起就有，architect_merge 消费）──
  "repository_id": "<uuid str>",          // 服务端权威写入，不采信容器上报
  "research_summary": "…",
  "proposed_changes": [],
  "candidate_files": [],
  "api_contracts_exposed": [],
  "dependencies_on_other_repos": [],
  // ── 112-04 新增四键（与 §7 键平级）──
  "fitness": {
    "verdict": "suitable | partial | unsuitable",   // 缺此键 = 不可解析 → mark_failed
    "reasons": ["…"],
    "citations": ["<裸文件路径/符号名>"]             // 注意：不是 citation id（见 P-5）
  },
  "role_suggestion": "direct | indirect",           // 非法回落 "direct"
  "responsibility": "一段话",
  "findings": [{"title": "…", "detail": "…", "citations": ["…"]}]
}
```

### 1.3 `record_partial` 签名（含 mark_done 语义）

`server/delivery/services/research_service.py:101-124` [VERIFIED: 源码]

```python
async def record_partial(self, task: RepoResearchTask, content: dict) -> PartialPlan
```

内部 `_record_partial_sync`（`:112-124`）做三件事：
1. `content_hash = sha256(json.dumps(content, sort_keys=True, ensure_ascii=False))`（`:107-109`，本地算）
2. `PartialPlan.objects.create(research_task=task, content=content, content_hash=..., valid=True)` —— **每次都 `create` 新行，从不 update**
3. `task.status = DONE; task.save(update_fields=["status","updated_at"])` —— **自带置 done**

`callbacks.py:2154` 注释明写：「`record_partial`（**已含置 done，不再调 mark_done**）」。

**关联签名**（同文件）：
- `create_tasks_for_session(self, session, deep_repos: list[dict]) -> list[RepoResearchTask]`（`:40-42`，`get_or_create(session, repository_id)` 幂等，每项 `{"repository_id","routed_confidence"}`）
- `mark_running(task, subagent_session) -> None`（`:72`）／`mark_done(task) -> None`（`:82`）／`mark_failed(task, error) -> None`（`:91`）
- `mark_stale(task_ids: list) -> int`（`:172`，置 task=STALE 且其 valid PartialPlan 失效，`invalidated_reason="clarification"`）
- `retry_task(task)`（`:126`）**不可用于蓝图链** —— 其重试入口硬编码 stage 名 `"research"`，蓝图 stage 为 `repo_research`/`repo_plan` 会恒 raise（112-04 SUMMARY 已实测记录）

### 1.4 新增 `repo_plan` 段的最小侵入写法

**推荐：读-合并-写（read-merge-write），绝不裸传新 dict。**

```python
# blueprint_repo_plan.py（新文件）
prev = await self._aload_latest_valid_content(task)      # 复用 acollect_fitness 的取最新口径
content = {**prev, "repo_plan": repo_plan_section}       # 浅合并：保留 fitness/findings/§7 五键
await self.research_service.record_partial(task, content)
```

理由（三条硬事实）：
- `record_partial` 是**整体覆写语义**（新建一行，content 全量），不合并旧段 → 直接传 `{"repo_plan": …}` 会让 112 的 fitness 段在「最新一行」里消失，而 `acollect_fitness`（`blueprint_research_adapter.py:793-831`）只取最新一行 → 确认门/投影全线失血。
- `content` 无 schema 约束（模型层 + service 层均不校验），加段是纯加性。
- `repo_plan` 段自身的 jsonschema 校验按 CONTEXT 锁定放在 `blueprint_schema` 侧（独立常量），**在调用 `record_partial` 之前**做，不合格走有界重试（≤2 轮）→ 开澄清线程。

`repo_plan` 段形状（DESIGN §5.3，`DESIGN.md:478-491`）[CITED: DESIGN.md]：
`repository_id / role / responsibility(Block[]) / fitness{verdict,reasons,citations} / current_state[] / impl_items[] / apis_provided[] / apis_consumed[] / local_impact{} / risks(Block[]) / open_question_thread_ids[]`

---

## 主题 2：容器 plan 模式（本相位的核心扩展点）

### 2.1 派发面签名与调用链现状

`server/services/process_runtime/blueprint_research_adapter.py` [VERIFIED: 源码]

| 位置 | 签名 | 备注 |
|------|------|------|
| `:98-113` | `__init__(self, *, research_service=None, session_service=None, dispatcher_factory=None, charters_loader=None, route_adapter=None, node_execution_id="")` | 5 个可注入依赖 + 1 标量，全 keyword-only，生产零参构造 |
| `:117-119` | `dispatch(self, session, *, force_deep_repository_ids: set[str] \| None = None) -> dict` | 返回形状恒定 `{dispatched, synthesized, degraded, tasks}`（`:135` 零候选路径与 `:242-247` 正常路径逐键一致） |
| `:268-271` | `_collect_candidates(session, *, allow_repository_ids=None) -> dict[str, dict]`（staticmethod） | 候选并集：`stage_state["routing"].candidates` ∪ `stage_state["confirmation"]` 内 `pending_research`，减去 `stage_state["reroute"]["excluded"]` |
| `:329-332` | `_bucket(candidates, *, forced) -> (deep, light)`（staticmethod） | `forced` 无条件进 deep（`:341-343`）；否则按 `role_suggestion`，缺失才回退 `confidence ∈ {high,medium}` |
| `:365-367` | `_dispatch_deep_task(self, session, task, *, candidate, charter) -> bool` | 派发五步（见下） |
| `:458-460` | `_build_dispatch_metadata(self, session, task, *, repo, subagent_session_id) -> dict[str,str]` | **env metadata 唯一构造点** |
| `:540-548` | `_build_prompt(self, session, task, repo, charter, *, candidate) -> str` | **prompt 唯一构造点** |
| `:635-643` | `_synthesize_light_partial(self, session, task, repo, *, candidate, charter) -> dict` | indirect 服务端合成（不起容器、不调 LLM） |
| `:724` | `aupgrade_to_deep(self, session, repository_id) -> bool` | 内部调 `dispatch(session, force_deep_repository_ids={repository_id})`（`:750`） |
| `:774` | `acollect_fitness(self, session) -> dict[str, dict]` | 每 task 只取 `valid=True` 的最新一条 |
| `:833` | `aadvance_reroute(self, session) -> dict` | — |

派发五步（`:365-456`，顺序即正确性）：① 缺 `git_url` 判失败不起占位容器（`:381-386`）→ ② `session_id = f"bp-research-{task.id.hex[:12]}-{uuid4().hex[:6]}"`（`:388`）→ ③ `AgentSession.acreate` + `SubAgentSession.acreate(task_type=PLAN, last_output={source, blueprint_session_id, research_task_id, repository_id})`（`:389-410`）→ ④ `_build_prompt` + `_build_dispatch_metadata` → `DispatchTask(task_type="plan", timeout=_RESEARCH_TIMEOUT, …)` → `use_call_source(CallSource.BLUEPRINT_REPO_RESEARCH)` 下 `dispatch`，失败先 `arevoke_task_tokens` 再上抛（`:412-440`）→ ⑤ `mark_running` + emit started（`:442-456`）。

### 2.2 metadata 现状取值（`env_FRIDAY_TASK_MODE` 等）

`_build_dispatch_metadata` 逐键 `env_` 前缀，**空值一律不注入该键**（`:474-536`）[VERIFIED: 源码]：

| metadata 键 | 现取值 | 来源 |
|-------------|--------|------|
| `repository_id` | `str(repo.id)` | `:475` |
| `env_FRIDAY_TASK_MODE` | **`"explore"`（硬编码）** | `:477` |
| `env_FRIDAY_TASK_TASK_MODE` | **`"explore"`（硬编码）** | `:478` |
| `env_FRIDAY_TASK_CLAUDE_API_KEY / _BASE_URL / _MODEL / _SMALL_MODEL` | `aget_claude_code_runtime_config()` | `:481-490`（空值不注入） |
| `env_FRIDAY_TASK_GIT_ACCESS_TOKEN / _GIT_AUTH_TYPE / _GIT_SSL_VERIFY` | `aresolve_git_token(repo)` | `:502-506` |
| `_repo_url`（私有，`DispatchTask` 构造时 `pop`） | git@ → https 归一后的 url | `:520`、`:422` |
| `env_FRIDAY_TASK_TOOLS_ENDPOINT` | `f"{settings.FRIDAY_BASE_URL}/api/tools/execute/"` | `:522-524` |
| `env_FRIDAY_TASK_KNOWLEDGE_ENDPOINT` | 裸 base（task 侧自拼 `/api/mcp/tools/{name}/`） | `:526` |
| `env_FRIDAY_TASK_USER_TOKEN` | `mint_task_token(dispatch_user, subagent_session_id, _RESEARCH_TIMEOUT)` 明文 | `:528-535` |

`:476` 注释明写 `"explore"` 的语义是「只读 explore 语义：双层 git 写操作拦截（调研阶段绝不写 git）」。
**阶段 2 拟方案同样不写 git**（产物是 JSON 方案，不是代码）→ **`explore` 应保持不变**，plan 模式**不要**改这两个键。

### 2.3 「调研 vs 拟方案」两类 prompt 的确切扩展点（含默认值兼容策略）

**四个扩展点，全部走「新增 keyword-only 参数 + 默认值 = 现状」，缺省路径逐字等价于 112：**

| # | 位置 | 现签名 | 建议扩展 | 默认值兼容 |
|---|------|--------|----------|-----------|
| E-1 | `:117` `dispatch` | `(session, *, force_deep_repository_ids=None)` | 追加 `mode: str = "research"` | `mode="research"` 时全链路与 112 逐字一致（`aupgrade_to_deep:750`、`_h_bp_repo_research:380` 两个既有调用方零改动） |
| E-2 | `:540` `_build_prompt` | `(session, task, repo, charter, *, candidate)` | 追加 `mode: str = "research"`；内部 `if mode == "plan": return self._build_plan_prompt(...)` | 现有 return 体（`:556-572`）一字不动 |
| E-3 | `:388` session_id 前缀 + `:404-409` `last_output` | `f"bp-research-{…}"` / `source="blueprint_research"` | plan 模式用 `f"bp-plan-{…}"` + `source="blueprint_repo_plan"`（新常量） | **必须区分** —— `callbacks._is_blueprint_research`（`:1986-1996`）唯一路由依据就是 `last_output.source`；不区分则 plan 容器的产物会被调研解析器按 `fitness.verdict` 解析、缺该键即 `mark_failed`（P-4） |
| E-4 | `:432` `use_call_source` | `CallSource.BLUEPRINT_REPO_RESEARCH` | plan 模式用 `CallSource.BLUEPRINT_REPO_PLAN`（111 已注册，CONTEXT 明令不新增枚举值） | — |

**不建议的扩展点（会破坏 112 既有路径）：**
- 改 `_build_dispatch_metadata` 的 `env_FRIDAY_TASK_MODE`（见 2.2，语义是 git 写拦截，与「调研 vs 拟方案」正交）
- 改 `_bucket` 的分桶规则（plan 阶段的 direct/indirect 来自**确认门锁定的 `role`**，不是路由期 `role_suggestion` —— plan 阶段应从 `repo_associations` 取仓集，不复用 `_collect_candidates`）
- 复用 `_collect_candidates`（它读的是 routing/confirmation 候选面；阶段 2 的输入面是**确认门锁定后的 `repo_associations`**，语义已不同）

**推荐结构（结论）**：新建 `BlueprintRepoPlanAdapter`（`blueprint_repo_plan.py`），**组合**而非继承 `BlueprintResearchAdapter`；把 `_dispatch_deep_task` 的五步 + `_build_dispatch_metadata` 通过给 `dispatch`/`_build_prompt` 加 `mode` 关键字复用；仓集来源、prompt 正文、产物解析、callbacks 第四条链各自独立。这样 `blueprint_research_adapter.py` 的改动收敛为「两个函数各加一个带默认值的关键字 + 三处 `mode` 分支」，`git diff | rg "^-"` 可保持极小。

**回调链**：`callbacks.py` 需加**第四条链**（`_is_blueprint_repo_plan` / `_parse_blueprint_repo_plan` / `_aload_blueprint_plan_task` / `_handle_*_completion|_failure` + barrier），形状照 `_is_blueprint_research` 一组（`:1986-2006`、`:2152-2163`）。112-04/05 已确立「`callbacks.py` 纯追加、只跑 `ruff check` 不跑 `ruff format`」的纪律（112-04 SUMMARY Deviation 4 —— 该文件有先于蓝图链的 format 漂移，跑 format 会打破纯追加断言）。

---

## 主题 3：融合装配可用件

### 3.1 `validate_blueprint`

`server/services/process_runtime/blueprint_schema.py:793-806` [VERIFIED: 源码]

```python
def validate_blueprint(content: Any) -> tuple[bool, str | None]
```

- **同步纯函数**，零 ORM，**绝不外抛异常**（docstring `:805` 明写）
- `content.get("schema_version") != "blueprint/v1"` → 直接 `(True, None)` pass-through（`:809-810`，v0 交给 `validate_technical_plan`）
- 校验两层：① 预编译 `jsonschema.Draft202012Validator`（`_VALIDATOR`，`:754`）② 后置检查 (a) 引用完整性 —— 全文档任何 `citations` 列表里的 id 必须存在于顶层 `citations` 引用池（`:817-819`，走 `_iter_citation_refs`，`:778-790`）
- 报错经 `_format_error`（`:764-775`）脱敏（`redact_secrets_in_text`）+ 截断 500 字（`_MAX_ERROR_CHARS = 500`，`:760`）
- 模块导出面 `__all__ = ["BLUEPRINT_SCHEMA_VERSION", "BLUEPRINT_JSON_SCHEMA", "validate_blueprint", "iter_blocks", "diff_blueprint_blocks"]`（`:29-35`）；`BLUEPRINT_SCHEMA_VERSION = "blueprint/v1"`（`:37`）
- 其余导出：`iter_blocks(content) -> list[tuple[str, dict]]`（`:919`）、`diff_blueprint_blocks(old, new) -> dict`（`:1044`）

**RepoPlan schema 照此加的写法**：`blueprint_schema.py` 内 schema 是**模块级 dict 常量 + 预编译 validator + 校验函数**三件套（`BLUEPRINT_JSON_SCHEMA` → `_VALIDATOR` → `validate_blueprint`）。RepoPlan 照同一形状加 `BLUEPRINT_REPO_PLAN_SCHEMA` + `_REPO_PLAN_VALIDATOR` + `validate_repo_plan(content) -> tuple[bool, str|None]`，`__all__` 用 `__all__ += [...]` 追加语句（112-05 已确立的「受限文件纯追加」范式）。⚠️ 但 `blueprint_schema.py` 在 112-05 的**冻结面自检清单内**（112-05 SUMMARY「冻结面自检」列了 `blueprint_schema.py` 零命中）—— 若本相位要改它需在 PLAN 里显式解冻并声明纯追加；**更安全的选择是 CONTEXT 提供的备选：新建 `blueprint_repo_plan_schema.py` 独立模块**（见 Open Question OQ-1）。

### 3.2 `blueprint_quality`（引用覆盖率门）

`server/services/process_runtime/blueprint_quality.py` [VERIFIED: 源码]

```python
def citation_coverage(blueprint: dict) -> float                                    # :68
def target_repo_hit_rate(blueprint: dict, expected_direct_repo_names: list[str]) -> float  # :82
def ai_rejection_rate(artifact_id: str) -> float | None                            # :111 —— 恒 None（114 填）
def human_edit_volume(artifact_id: str) -> int | None                              # :122 —— 恒 None（114 填）
def clarification_rounds(artifact_id: str) -> int | None                           # :132 —— 恒 None
```

`citation_coverage` 入参形状 = **完整蓝图 content dict**（不是片段）。分母口径固定为三类关键结论条目（`_iter_key_conclusion_citations`，`:39-65`）：

1. `current_state_analysis[].findings[].citations`（`:50-55`）
2. `repo_associations[].rationale.citations`（`:56-60`）—— 注意读的是 **`rationale.citations`**，不是 `fitness.citations`
3. `impact_analysis.affected_features[].citations`（`:61-65`）

判定：`citations` 为**非空 list** 即算已引用（`_cited`，`:34-36`）；**分母为 0 返回 `1.0`**（`:76-77`，「不惩罚未写内容」）。

⚠️ **融合门的隐患**：`repo_associations` 的 citations 走 `rationale.citations`，而 112 确认门 `build_locked_associations` 落的是 `fitness.citations`（112-05 SUMMARY Deviation 2）。若融合投影只搬 `fitness`，`repo_associations` 这一类条目的分子恒为 0，覆盖率被系统性拉低。**融合投影必须同时填 `rationale.citations`**。

### 3.3 `must_haves` 派生：111 **没有**派生代码，需新写

`rg must_haves --glob '!tests/**' -l` → 全仓**只有** `blueprint_schema.py` 一个文件命中（`:7` docstring / `:133` required 项 / `:713-732` schema 定义）[VERIFIED: rg]。

schema 形状（`:713-732`）：`{"type":"object", "required":["truths","artifacts","key_links"], properties: truths: string[], artifacts: array（path+provides）, key_links: array（from/to/via）}`。
语义（`DESIGN.md:304-314`）[CITED: DESIGN.md §3.12]：`truths` = 可观察行为断言；`artifacts` = `{path, provides}`；`key_links` = `{from, to, via}`。

**结论：`must_haves` 只有 jsonschema 契约，零派生实现。本相位必须新写**（CONTEXT 说「复用 111 的派生思路」—— 可复用的是**思路与 schema**，不是代码）。参照的确定性派生先例是 `execution_plan`（`DESIGN.md:326` §3.14：从 `implementation_overview.items` 按仓聚合 + `depends_on/wave` 拓扑排序，**无 LLM 参与**）。

### 3.4 `ArtifactService` 落新版本

`server/delivery/services/artifact_service.py:117-162` [VERIFIED: 源码]

```python
async def add_version(
    self, artifact: Artifact, content: dict, *,
    produced_by_session_id: str = "", produced_by_ref: str = "",
) -> ArtifactVersion
```

行为（`:126-162`）：
1. `validate_content(artifact.artifact_type, content)` → 不过则 `raise ArtifactContentInvalid(f"{artifact_type} content 校验失败：{err}")`（`:126-130`）。`artifact_type` 恒为 `"technical_plan"`（`builtin_processes.py:545`），blueprint/v1 由 `delivery/artifacts/builtin_types.py` 的 `schema_version` 判别分支路由到 `validate_blueprint`。
2. `_add_version_sync` 在 `transaction.atomic()` 内：`refresh_from_db(["current_version"])` → **`current.content_hash == new_hash` 则直接返回 current，不翻版本**（`:148-149`，天然幂等）→ 否则 `version_no+1`、`supersedes=current`、推进 `artifact.current_version`（`:150-162`）。

**融合产物落库路径**：`await self.artifact_service.add_version(artifact, blueprint_content, produced_by_session_id=str(session.id), produced_by_ref="blueprint_merge")`。
`class ArtifactService`（`:50`，docstring「通用交付物唯一写入入口」）；`create(...)` 在 `:53`。

### 3.5 冻结的 `architect_merge_adapter.py`：可借鉴的组织范式（只读参考）

`server/services/process_runtime/architect_merge_adapter.py` [VERIFIED: 源码，**不修改**]

| 结构 | 位置 | 可借鉴点 |
|------|------|---------|
| `MergedPlanSynthesizer` Protocol | `:88-91` | 合成器抽象成 Protocol，测试注替身 |
| `LLMMergedPlanSynthesizer.synthesize(session, partials) -> dict` | `:94-117` | `ProviderConfigService.aresolve()` → `build_chat_model(resolved, model_name, streaming=False)` → `use_call_source(...)` 包住 `ainvoke` → `_content_to_text` → `_parse_merged_json`，parse 失败 `raise ValueError("merged_plan_parse_failed")` |
| `_system_prompt()` / `_build_prompt(session, partials)` | `:119-164` | system 与 human 分离；prompt 段落用「可空串 section」拼接（`evidence_section` `:134-139`、`classification_section` `:143`）—— **非该场景时该段为空串，prompt 与既有逐字一致（零扰动）**，这是分节 prompt 的关键范式 |
| `ArchitectMergeAdapter.MAX_MERGE_RETRIES = 1` | `:170` | 重试上界是**类属性常量** |
| `__init__(*, synthesizer=None, session_service=None, artifact_service=None, clarification_service=None, spec_generation_hook=None)` | `:172-193` | 全 keyword-only `x or DefaultX()` 兜底 |
| `merge(session) -> dict` 校验重试骨架 | `:195-237` | ① `_collect_valid_partials` ② `attempt = ArchitectMerge.objects.filter(session_id).acount()`（**轮次由 DB 计数得出，不存 stage_state**）③ emit started ④ synthesize（异常 → `{"validation_status":"failed","report":…,"back_target":"research","attempt":…}`，**graceful 降级不上抛**）⑤ `validate_merged_plan` schema 门 ⑥ `validate_plan` 语义门 ⑦ `_handle_pass`/`_handle_fail` |
| `_handle_pass` / `_handle_fail` / `_create_reclarify` | `:239 / :344 / :361` | pass → 落 ArtifactVersion + `ArchitectMerge(passed)`；fail → `ArchitectMerge(failed)` + 按归因产澄清 |

**融合返回形状先例**：`{"validation_status", "report", "back_target", "attempt"}`（`:219-224`）—— 本相位 `blueprint_merge` 的 `back_target` 需支持「单仓归因」（`repo_plan` + `repository_id`）与「融合归因」（`merge`）两档。

---

## 主题 4：stage 追加

### 4.1 `technical_blueprint` 注册字典的确切位置与形状

`server/services/process_runtime/builtin_processes.py` [VERIFIED: 源码]

- `_TECHNICAL_BLUEPRINT_STAGES = {…}` 定义在 **`:453-516`**（七个 StageDef）
- `register_process_type(ProcessDefinition(process_type="technical_blueprint", artifact_type="technical_plan", initial_stage="intake", stages=_TECHNICAL_BLUEPRINT_STAGES))` 在 **`:542-549`**（第三次注册；`technical_plan` 在 `:521-528`、`echo` 在 `:530-537`）
- 冻结的 `_TECHNICAL_PLAN_STAGES` 在 `:208-301`（含 `merge.exhausted: STAGE_FAILED` @ `:249` —— 是**旧链**的行，不可改，验收 rg 时需排除）
- `MAX_BLUEPRINT_REROUTE_ROUNDS = _MAX_REROUTE_ROUNDS` 在 `:447-451`（中段 import + `# noqa: E402`，守「本文件纯追加」纪律的既有范式）

`StageDef` 形状（`server/services/process_runtime/registry.py:34-44`）：
```python
@dataclass(frozen=True)
class StageDef:
    key: str
    handler: StageHandler
    transitions: dict[str, str] = field(default_factory=dict)   # {event -> next_stage | STAGE_DONE | STAGE_FAILED}
    pausable: bool = False
    wait_status: str = "waiting_event"
```
`ProcessDefinition`（`registry.py:47-54`）：`process_type / artifact_type / initial_stage / stages`。

### 4.2 七个 `_h_bp_*` handler 的签名与 `StageOutcome` 用法

统一签名：`async def _h_bp_<stage>(session: Any, engine: Any) -> StageOutcome`

| handler | 行号 | deps 属性 | 产出 |
|---------|------|-----------|------|
| `_h_bp_intake` | `:319` | — | `StageOutcome(event="intaken")` 零副作用 |
| `_h_bp_decompose` | `:324` | — | `StageOutcome(event="decomposed")` 零副作用 |
| `_h_bp_spec_gate` | `:332` | `spec_gate` | `event ∈ {spec_locked, needs_clarification}` + `stage_state_update=result.get("stage_state") or None` |
| `_h_bp_route` | `:347` | `route` | `stage_state_update={"routing": routing}`（**routing 唯一写入方**；缺依赖时 `stage_state_update` 为 `None`，绝不写半截键） |
| `_h_bp_repo_research` | `:367` | `research` | `dispatch(session)` → `aall_research_tasks_terminal(session.id)` 判 `research_complete` / `research_dispatched` |
| `_h_bp_reroute` | `:386` | `research` | `event=result["event"]`，`stage_state_update` 用 `aadvance_reroute` 返回的**整份浅合并结果**（只取增量会清空 routing/decomposition），`escalation` 非空时并入 |
| `_h_bp_repo_confirmation` | `:408` | `confirm_gate` | 判定顺序**固定**「先 `research_required` 再 `awaiting_confirmation`」；`research_required` 分支用 `acollect_confirmation_state` 刷 `stage_state[STAGE_STATE_KEY]` |

`StageOutcome`（`server/services/process_runtime/engine.py:34-46`）：
```python
@dataclass
class StageOutcome:
    event: str
    stage_state_update: dict | None = None       # 合并进 session.stage_state 的增量 dict（None 不改）
    current_artifact_version: Any = None          # 本步产出的 ArtifactVersion id（merge 段产出主产物时用）
    error: dict | None = None                     # 仅 fail/exhausted 路径
```
**`merge` handler 是本蓝图链第一个需要用 `current_artifact_version` 的 handler**（其余六个都没用）—— 落新蓝图版本后必须回填它，否则 `session.current_artifact_version` 不推进（112-05 Deviation 3 记录过同源坑：`session` 钉住的版本会落后于 artifact 最新版本）。

三条 handler 纪律（`:304-316` 注释）：① **软取依赖** `getattr(getattr(engine,"deps",None),"<name>",None)`，缺依赖返回默认 pass-through 不报错；② **绝不自行 transition**（engine 纯度）；③ **不重复 emit 事件**（adapter 已 emit，engine 的 transition 也记一条）。

### 4.3 追加 `repo_plan → merge` 两 stage 需要动的确切行

**改动 A（唯一一处修改行）** — `builtin_processes.py:511`：
```python
            # 113 接续点：把该值改为 "repo_plan" 并追加两个 StageDef 即可
            "confirmed": STAGE_DONE,          # ← 改为 "repo_plan"
```
（`:509-510` 的注释就是 112-05 给 113 留的接续点标记，`:511` 是唯一要改的一行）

**改动 B（纯追加）** — `builtin_processes.py:515` 之后、`:516` 的 `}` 之前，追加两个 StageDef；`_h_bp_repo_plan` / `_h_bp_merge` 两个 handler 追加在 `:442` 之后（`_h_bp_repo_confirmation` 尾）与 `:445` 中段 import 之前。

**改动 C（纯追加）** — `entrypoint.py:168-173` 的 `SimpleNamespace(...)` 加两个属性：
```python
    deps = SimpleNamespace(
        spec_gate=…, route=…, research=…, confirm_gate=…,
        repo_plan=BlueprintRepoPlanAdapter(node_execution_id=node_execution_id),   # 新增
        merge=BlueprintMergeAdapter(),                                              # 新增
    )
```
⚠️ `entrypoint.py:153-155` docstring 明写 deps 名单与 handler `getattr` 取名**逐字一致**，且**有等价性断言守护**（112-05 `test_blueprint_process_graph.py`）—— 名单漂移 = 「注册了但恒 pass-through」的静默失败。同步改 docstring 名单。

**验收 rg 口径变化**（112-05 已有的守护断言会因本相位变红，需同步更新期望值）：
- `rg -c "^async def _h_bp_" builtin_processes.py`：**7 → 9**
- `rg -c "^register_process_type\(" builtin_processes.py`：保持 **3**（不新增 process）
- `git diff builtin_processes.py | rg "^-"`：本相位会有 **1 行**（`:511` 的 `STAGE_DONE` → `"repo_plan"`）+ 可能的 docstring 计数行 —— PLAN 需显式允许这一行

**stage graph 目标形状**（建议）：
```python
    "repo_plan": StageDef(
        key="repo_plan", handler=_h_bp_repo_plan,
        transitions={"plan_dispatched": "repo_plan", "plan_complete": "merge",
                     "needs_clarification": "repo_plan"},
        pausable=True, wait_status="waiting_event",
    ),
    "merge": StageDef(
        key="merge", handler=_h_bp_merge,
        transitions={"merged": STAGE_DONE, "repo_rework": "repo_plan",
                     "remerge": "merge", "needs_clarification": "merge"},
        pausable=True, wait_status="waiting_clarification",
    ),
```
（`merge` **绝不落 `STAGE_FAILED`** —— 与 `reroute.exhausted → repo_confirmation` 同源纪律（`:492-494`）：超界带未决项进 114，不是「流程失败」。旧链 `_TECHNICAL_PLAN_STAGES` 的 `merge.exhausted: STAGE_FAILED`（`:249`）是**另一个字典**，不受影响也不可改。）

### 4.4 `stage_state` 现有键清单（新增键不得冲突）

[VERIFIED: `rg` 扫 `blueprint_*.py` + `builtin_processes.py`]

| 键 | 写入方 | 定义处 | 内容 |
|----|--------|--------|------|
| `spec_gate` | `blueprint_spec_gate` | `blueprint_spec_gate.py:66` `STAGE_STATE_KEY = "spec_gate"` | 规格门 |
| `routing` | `_h_bp_route`（**唯一写入方**） | `builtin_processes.py:348,364`；读 `blueprint_research_adapter.py:293` | 112-03 路由契约（candidates 等） |
| `confirmation` | `_h_bp_repo_confirmation` | `blueprint_confirm_gate.py:65` `STAGE_STATE_KEY = "confirmation"` | `{thread_id, thread_status, repos[]}` |
| `reroute` | `aadvance_reroute` | `blueprint_research_adapter.py:81` `_REROUTE_STATE_KEY = "reroute"` | `{count, excluded[], last_reason}` |
| `repo_research_fitness` | `aadvance_reroute` | `blueprint_research_adapter.py:82` `_FITNESS_STATE_KEY` | `{repository_id: {verdict, role_suggestion, task_status}}`（只存标量摘要） |
| `escalation` | `_h_bp_reroute` | `builtin_processes.py:400-402` | reroute 超限时的全量快照 |
| `decomposition` | 入口/上游 | 读 `blueprint_route.py:855` | 需求装配 |
| `include_repos` | 入口 | 读 `blueprint_route.py:853` | 项目 include 仓 |
| `blueprint` | 入口 | 读 `blueprint_route.py:445,849`、`blueprint_research_adapter.py:1213` | 蓝图上下文（`requirement_spec` 来源） |

**共 9 个已占用键。** 建议本相位新增键（无冲突）：`repo_plan`（分仓方案进度摘要）、`merge`（融合轮次与归因）、`context_bus`（waiter 登记与等待关系摘要）。三者均须遵守「只存 id / 计数 / 小摘要，单字段 < 2KB」（`DESIGN.md:472` 上下文纪律）。

⚠️ **`stage_state` 是整字典替换语义**（112-04 SUMMARY 与 `builtin_processes.py:389-391` 注释）：`aadvance_reroute` 用 `{**state, ...}` 浅合并后回写整字典。本相位任何 `stage_state_update` 若来自「重读 session 后浅合并」路径，必须同样返回整字典；若走 handler 的 `StageOutcome.stage_state_update` 增量路径，engine 会做合并 —— **两条路径不可混用**（混用会丢键）。

---

## Pitfalls

### P-1 `record_partial` 是整体覆写，不合并旧段 —— repo_plan 会吃掉 fitness
**根因**：`_record_partial_sync`（`research_service.py:112-124`）`PartialPlan.objects.create(content=content)`，content 全量新建。
**后果**：只传 `{"repo_plan": …}` → 新行没有 `fitness`/`findings`/§7 五键 → `acollect_fitness`（只取最新一行）读到空 fitness → 确认门快照与 `current_state_analysis` 投影全线失血。
**规避**：写前先读最新有效 content 做浅合并（见 1.4）。**可证伪断言**：写入 repo_plan 后 `acollect_fitness(session)[repo_id]["verdict"]` 仍等于写入前的值。

### P-2 `record_partial` 自带 `task.status = DONE` —— 多阶段共用同一 task 会提前终态
**根因**：`research_service.py:122-123` 无条件置 DONE；`callbacks.py:2154` 注释「已含置 done，不再调 mark_done」。
**后果**：若阶段 2 复用阶段 1 的同一 `RepoResearchTask`，派发 plan 容器前须先 `mark_stale`（否则 `_DISPATCHABLE_STATUSES = (PENDING, STALE)`（`:67`）判定为 done 直接 skip，plan 容器永不启动 —— 与 112-04 Deviation 1 同源的静默失效模式）。
**规避**：明确决策「阶段 2 复用同一 task（需 `mark_stale`）还是建新 task 行」（见 OQ-2）。

### P-3 一仓多条 PartialPlan 取最新：112 **已有约定**，必须逐字复用
**约定出处**：`blueprint_research_adapter.py:774-779` docstring + `_collect_fitness_sync`（`:793-831`）实现：
```python
PartialPlan.objects.filter(research_task__session_id=session_id, valid=True)
    .order_by("-created_at").values("research_task_id", "content")
# 降序取首见即最新（每 task 只取一条）
latest.setdefault(row["research_task_id"], row["content"] or {})
```
三条要素缺一不可：① `valid=True` 过滤（重索引/澄清失效行必须忽略）② `-created_at` 降序 ③ 每 `research_task_id` 只取首见。
`architect_merge_adapter._collect_valid_partials`（`:388`）是**旧链**的另一份实现（冻结，不复用）。
**风险**：`created_at` 是 `auto_now_add`，同一事务内秒级并发写两行时排序不稳定 —— 本相位若在同一请求内先写 fitness 再写 repo_plan，须保证串行且间隔可分辨，或改用 `-created_at, -id` 复合排序（**注意：改排序会触碰 112 的既有实现，属受限面**）。

### P-4 plan 容器不换 `last_output.source` → 被调研解析器抢走并判失败
**根因**：`callbacks._is_blueprint_research`（`:1986-1996`）唯一判据是 `task_type == PLAN and last_output["source"] == "blueprint_research"`；`_parse_blueprint_fitness`（`:1999-2006`）**缺 `fitness.verdict` 即返回 None → `mark_failed({"reason":"empty_or_unparseable_result"})`**。
**后果**：plan 产物没有 `fitness.verdict` → 每个 plan 容器回调都判失败，且不产生 PartialPlan 行。
**规避**：plan 链用独立 `source`（如 `"blueprint_repo_plan"`）+ 独立 `_is_blueprint_repo_plan` 判据，与既有两链三向互斥（`_is_plan_research` / `_is_blueprint_research` / 新链）。**可证伪断言**：给 plan 容器 session 跑 `_is_blueprint_research` 必须为 `False`。

### P-5 引用池白名单：裸文件路径直接落蓝图 = 整份非法
**根因**：`validate_blueprint` 后置检查 (a)（`blueprint_schema.py:817-819`）要求任何块内 `citations` id 必须存在于顶层 `citations` 引用池；而调研/方案产出的 citations 是**裸文件路径/符号名**。
**先例**：112-05 Deviation 2 为此给 `build_locked_associations` 加了 `citation_pool` 白名单过滤参数，否则确认门「永远锁不上」。
**规避**：融合装配时必须**先建引用池**（把各仓 citations 归一成 citation id 落顶层 `citations`），再把 id 填进各段 —— 或沿用 112 的白名单过滤（丢弃池外引用）。**两者选一必须在 PLAN 里显式定，不能两边都不做。**

### P-6 融合重试的幂等：`ArtifactVersion` 重复落版本 —— **上游已消除，但有两个残留口**
**已消除**：`_add_version_sync`（`artifact_service.py:145-149`）在 `transaction.atomic()` 内比对 `current.content_hash == new_hash`，相等直接返回 current，**不翻版本**。故「重融合产出逐字相同的 content」不会造版本膨胀。
**残留口 1（真风险）**：LLM 分节起草有随机性，重试产出的 content 只要有一个字不同 hash 就变 → 每轮重试都翻一个版本。上界 2 轮 ⇒ 最多 3 个版本，可接受但需在事件里可归因。**建议**：`produced_by_ref` 带轮次（如 `"blueprint_merge#attempt=1"`），并把「本轮是重试」记进 `stage_state["merge"]`。
**残留口 2（版本基线）**：112-05 Deviation 3 记录 —— **`session.current_artifact_version` 会落后于 `artifact.current_version`**（session 那一版只在 handler 显式给 `StageOutcome.current_artifact_version` 时才更新）。融合读基线必须取 `ArtifactVersion.objects.filter(artifact_id=…).order_by("-version_no").afirst()`，读 session 那一版会把确认门锁定的 `repo_associations` 覆盖回旧内容。
**轮次持久化**：旧链用 `ArchitectMerge.objects.filter(session_id).acount()` 从 DB 计数得轮次（`architect_merge_adapter.py:199`）—— 蓝图链没有对应表，**轮次须落 `stage_state["merge"]["count"]`**，且递增点必须**单点串行**（照 112-04 `aadvance_reroute` 的范式：重读 session 新实例 → `{**state, ...}` 浅合并整体回写；回调路径永不触碰计数）。

### P-7 引用覆盖率门阈值走 SystemSetting：键命名建议
**既有范式**（`server/system/models.py:180-187`）[VERIFIED: 源码]：
```python
    # 消费方：services/process_runtime/blueprint_spec_gate.py（112-02）。
    BLUEPRINT_SPEC_GATE_CONFIG = "blueprint.spec_gate.config"
    # 消费方：services/process_runtime/blueprint_route.py（112-03）。
    BLUEPRINT_ROUTE_WEIGHTS = "blueprint.route.weights"
```
命名规律：**常量名 `BLUEPRINT_<STAGE>_<WHAT>`，值 `"blueprint.<stage>.<what>"`（点号分段小写）**，且**必须**带一行 `# 消费方：<模块路径>（<phase>）` 注释。

**建议**：
```python
    # 消费方：services/process_runtime/blueprint_merge.py（113）。
    # value 为 JSON：{citation_coverage_min: float, max_merge_rounds: int}
    BLUEPRINT_MERGE_CONFIG = "blueprint.merge.config"
```
（用 JSON 单键而非多个标量键 —— 与 `BLUEPRINT_SPEC_GATE_CONFIG` 的 JSON 范式一致，且未来加阈值不需再动 `SettingKeys`。`system/models.py` 与 `system/settings_service.py` 在 112-05 冻结面清单内 —— 加常量属**纯追加**，PLAN 需显式声明。）

读取 API（`server/system/settings_service.py`）：`aget_json_setting(key, default: dict|None=None) -> dict`（`:139`）／`aget_float_setting(key, default=0.0) -> float`（`:124`）／`aget_int_setting`（`:113`）／`aget_setting`（`:96`）；同步版 `get_*_setting`（`:44-80`）。缺省兜底照 112 范式**留模块常量**（如 `_DEFAULT_CITATION_COVERAGE_MIN = 0.8`）。

### P-8 `repo_associations` 的 citations 走 `rationale.citations`，不是 `fitness.citations`
见 3.2。融合投影若只搬 `fitness`，覆盖率分子恒 0。**可证伪断言**：投影后 `citation_coverage(blueprint)` 对含 N 个 repo_associations 的样本 > 0。

### P-9 `entrypoint` deps 名单漂移 = 静默空转
`build_blueprint_engine`（`entrypoint.py:144-177`）的 `SimpleNamespace` 属性名与 handler `getattr` 取名必须逐字一致（`:153-155` docstring）。handler 软取依赖的设计使**名字写错不会报错，只会永远 pass-through**。112-05 已有等价性断言测试守护 —— 本相位追加两个属性时必须同步扩这个断言。

### P-10 `callbacks.py` 只跑 `ruff check`，绝不跑 `ruff format`
112-04 Deviation 4：该文件有**先于蓝图链**的 format 漂移（三处），跑 `ruff format` 会顺手重排，直接打破「纯追加、`git diff | rg "^-"` 为空」的硬约束。新增 elif 写成单行条件形态，避免 formatter 波及紧随其后的既有 elif。

### P-11 §13.2 冻结清单（再列一遍）

**绝对冻结（v0.20 只读，`git diff --name-only` 必须零命中）** —— `DESIGN.md:772` [CITED: DESIGN.md §13.2 第 2 条]：

| # | 文件 | 说明 |
|---|------|------|
| 1 | `server/services/process_runtime/decompose_segments.py` | 旧 technical_plan process |
| 2 | `server/services/process_runtime/research_adapter.py` | 旧派发面（112-04 的 analog，**复制不 import**） |
| 3 | `server/services/process_runtime/architect_merge_adapter.py` | 旧融合面（本相位**只读参考**，`blueprint_merge.py` 是新文件） |
| 4 | `server/services/process_runtime/merged_plan.py` | 旧 MergedPlan schema |
| 5 | `server/services/process_runtime/clarify_adapter.py` | 旧澄清 |
| 6 | `server/services/process_runtime/render.py` | 旧渲染 |
| 7 | `_TECHNICAL_PLAN_STAGES`（`builtin_processes.py:208-301`） | 旧 stage 字典**零触碰**（CONTEXT 明令） |
| 8 | `server/services/process_runtime/resume.py` | 112-05 冻结面自检项（蓝图走 `blueprint_resume.py`） |
| 9 | `server/repositories/services/repo_router_v2.py` | `DESIGN.md:596` 明令不改（章程证据在 adapter 层融合） |
| 10 | `server/repositories/services/charter_service.py` | 112-05 冻结面自检项 |
| 11 | `server/delivery/services/event_taxonomy.py` | §13.2 第 3 条：只新增 `blueprint_*` 类型，不改既有类型与字段 |

**112 自产、本相位视为「受限面」（只允许纯追加，`git diff | rg "^-"` 应为空）**：
`blueprint_schema.py`（见 OQ-1）／`blueprint_route.py`／`blueprint_spec_gate.py`／`blueprint_confirm_gate.py`／`blueprint_resume.py`／`blueprint_lifecycle_service.py`／`entrypoint.py`／`system/models.py`／`system/settings_service.py`／`subagent/api/callbacks.py`。

**本相位允许的非纯追加改动（须在 PLAN 显式登记）**：
`builtin_processes.py:511` 一行（`STAGE_DONE` → `"repo_plan"`）+ `blueprint_research_adapter.py` 的 `mode` 关键字扩展（两个函数签名 + 三处分支，改动行数应可枚举）。

**其他 §13.2 纪律**：第 4 条前端只新建不改旧（本相位无前端）；第 5 条 migration 在同步点 rebase 时重新生成序号（`BlueprintContextEntry` 是本相位唯一新模型）；第 6 条 worktree 每同步点 rebase 一次。

---

## Open Questions

**OQ-1（推荐答案：新建独立模块）** RepoPlan schema 放 `blueprint_schema.py` 还是新建 `blueprint_repo_plan_schema.py`？
- 已知：CONTEXT 给了两个选项；`blueprint_schema.py` 的三件套范式（常量 → 预编译 validator → 校验函数）易照搬；但该文件在 112-05 的**冻结面自检清单**内（零命中断言）。
- **推荐：新建 `blueprint_repo_plan_schema.py`**，导出 `BLUEPRINT_REPO_PLAN_SCHEMA` + `validate_repo_plan(content) -> tuple[bool, str|None]`。理由：保住 112-05 已建立的守护断言（改它要先改断言，是净负债）；RepoPlan 是**中间产物**不是蓝图文档，语义上本就该分开；`__all__` 冲突面归零。

**OQ-2（推荐答案：复用同一 task + `mark_stale`）** 阶段 2 是复用阶段 1 的 `RepoResearchTask`，还是为每仓新建 plan task 行？
- 已知：`RepoResearchTask` 按 `(session, repository_id)` `get_or_create` 幂等（`research_service.py:46`），**无 stage/kind 字段**区分阶段 → 新建等价物需改模型（触发 migration + 影响 `aall_research_tasks_terminal` 的 barrier 判据）。
- **推荐：复用同一 task**，派发 plan 容器前 `mark_stale([task_id])` 置回 `_DISPATCHABLE_STATUSES`，阶段区分靠 `PartialPlan.content` 里有无 `repo_plan` 段 + `last_output.source`。代价：`stage_state["repo_plan"]` 需自记「本仓已产 plan」的完成集，不能只看 `task.status`（`done` 在两阶段都出现）。
- 反对项：`aall_research_tasks_terminal(session.id)` 被 `_h_bp_repo_research` 复用（`builtin_processes.py:375,381`）—— 若 `_h_bp_repo_plan` 也用它，两 stage 的 barrier 判据同源，`mark_stale` 后 stage 1 的判据会短暂为假。**规避：`_h_bp_repo_plan` 用自己的完成判据（读 `PartialPlan.content` 有无 `repo_plan` 段），不复用 `aall_research_tasks_terminal`。**

**OQ-3（推荐答案：`merge` 不落 `STAGE_FAILED`）** 融合超界（2 轮）后 stage 走向？
- CONTEXT 说「超界带未决项进入 114 的审查/人审而非静默通过」，但 114 的 `ai_review` stage 本相位不注册。
- **推荐：`merge` 的超界事件转 `STAGE_DONE`（带 `stage_state["merge"]["unresolved"]` 未决项快照 + 开澄清线程）**，与 `reroute.exhausted → repo_confirmation` 同源纪律（不落 failed）。114 追加 `ai_review` 时把 `merge.merged` 从 `STAGE_DONE` 改为 `"ai_review"` 即可 —— 与 112-05 留给 113 的接续点形状完全一致。

**OQ-4（推荐答案：都要）** 引用覆盖率门不达标时，归因判「单仓」还是「融合」？
- `citation_coverage` 返回单个 float，无逐条归因。
- **推荐：新写一个 `_coverage_gaps(blueprint) -> list[{section, index, repository_id}]` 纯函数**（复用 `_iter_key_conclusion_citations` 的同一遍历口径，只是产出定位而非布尔），按 gap 的 `repository_id` 是否可解析决定回 `repo_plan`（带 repo id）还是 `merge`。避免「阈值卡住但不知道回哪」。

---

## Sources

### Primary（HIGH，本 worktree 源码逐行核对）
- `server/delivery/models/research_task.py:89-118`（PartialPlan）
- `server/delivery/services/research_service.py:40-180`（record_partial / create_tasks_for_session / mark_* / retry_task）
- `server/delivery/services/artifact_service.py:50-162`（ArtifactService.add_version）
- `server/services/process_runtime/blueprint_research_adapter.py:51-1247`（派发面全貌）
- `server/services/process_runtime/blueprint_schema.py:29-1044`（validate_blueprint / must_haves schema）
- `server/services/process_runtime/blueprint_quality.py:20-140`（citation_coverage 等五个指标）
- `server/services/process_runtime/architect_merge_adapter.py:50-460`（**只读参考、冻结**）
- `server/services/process_runtime/builtin_processes.py:208-549`（stage 注册与 handler）
- `server/services/process_runtime/engine.py:34-46`（StageOutcome）／`registry.py:34-54`（StageDef / ProcessDefinition）
- `server/services/process_runtime/entrypoint.py:144-181`（build_blueprint_engine）
- `server/subagent/api/callbacks.py:1775-2163`（第二/三条链与解析器）
- `server/system/models.py:31-187`（SettingKeys）／`server/system/settings_service.py:23-143`（读取 API）

### Secondary（HIGH，项目内权威设计文档与已验收 SUMMARY）
- `.planning/technical-blueprint/DESIGN.md` §5.2（`:453-472`）／§5.3（`:474-491`）／§3.12（`:304-314`）／§3.14（`:326`）／§13.2（`:769-777`）
- `.planning/phases/112-1/112-04-SUMMARY.md`（派发面契约、6 处 Deviations、可调旋钮）
- `.planning/phases/112-1/112-05-SUMMARY.md`（确认门契约、七 stage、10 处 Deviations、113 接续点）
- `.planning/phases/113-2/113-CONTEXT.md`（锁定决策）

### 未使用
无外部检索（Context7 / WebSearch / npm）—— 本相位零新增外部依赖，所有事实来自本仓源码。

## Metadata

**Confidence breakdown:**
- 主题 1 RepoPlan 落位：**HIGH** —— 模型/service 签名逐行读过，无推断
- 主题 2 容器 plan 模式：**HIGH**（现状事实）／**MEDIUM**（扩展点方案是设计建议，非既存事实；已标注推荐理由与反对项）
- 主题 3 融合装配：**HIGH** —— 四个可用件签名与返回逐行核对；`must_haves` 无派生代码经全仓 rg 确认
- 主题 4 stage 追加：**HIGH** —— 行号精确，接续点由 112-05 显式留注释
- Pitfalls：**HIGH** —— 全部有源码或已验收 SUMMARY 的 Deviation 记录支撑

**Assumptions Log:** 无 `[ASSUMED]` 标记条目（本相位零新增外部包，无需 Package Legitimacy Audit / Environment Availability 审计）。

**Research date:** 2026-07-30
**Valid until:** 本 worktree 内 112 相关文件未被 rebase 改动前有效（同步点 rebase 后需复核行号）
