# Phase 112: 路由与容器面契约 - Research

**Researched:** 2026-07-30
**Domain:** 双面路由 adapter / 章程读写 / PLAN 容器派发与回调 / delivery knowledge 召回
**Confidence:** HIGH（全部事实来自本仓源码直读，带文件:行号）
**Scope:** 仅 5 个指定主题 + Pitfalls。analog 结构要点见 `112-PATTERNS.md`，本文不重复。

> 所有路径相对 worktree 根 `/Users/zaneliu/Projects/open-source/friday-clean/.claude/worktrees/v0.20-blueprint/`。

---

## ⚠️ 三个必须先纠偏的 CONTEXT 假设

planner 按 CONTEXT.md 字面写代码会撞的三处现状偏差：

| # | CONTEXT.md 表述 | 现状事实 | 影响 |
|---|-----------------|----------|------|
| C1 | 「breakdown 各项之和等于总分」 | `RepoRouteCandidateV2` **没有 breakdown 字段**，`score` 是单个 float，无任何分量拆解（`repo_router_v2.py:61-84`） | RepoRouterV2 原始「各信号」无法拆解，adapter 只能把整个 `score` 当作**一个**分量（建议命名 `capability_match`）。不能声称能拆出 RRF/命中数/facets 三项 |
| C2 | 「`RepoResearchTask.report` JSON 增 fitness…」 | `RepoResearchTask` **无 `report` 字段**（`research_task.py:38-74` 全字段清单见 §3.1）。结构化产物在 `PartialPlan.content`（`research_task.py:101`） | fitness/role_suggestion/responsibility/findings 必须挂 `PartialPlan.content`，经 `ResearchService.record_partial(task, content)` 写入 |
| C3 | 「PLAN 链现状缺 token 注入，本相位补齐」 | **注入**确实缺（`research_adapter.py:337-377` 无 `USER_TOKEN`/`KNOWLEDGE_ENDPOINT`），但**吊销已覆盖**：`arevoke_task_tokens` 在 `_handle_completed`/`_handle_failed` 的 task_type 分支**之前**无条件调用（`callbacks.py:945-947`、`1029-1031`） | 只需补 mint + 注入；**不要**新写吊销钩子（重复吊销幂等但属冗余代码） |

---

## 1. RepoRouterV2 输出契约

### 1.1 主函数签名

```python
# server/codegraph/services/repo_router_v2.py:99-107
class RepoRouterV2:
    @classmethod
    async def route(
        cls,
        query: str,
        *,
        top_k: int = 3,
        repository_ids: list[str] | None = None,
        use_llm: bool = True,
    ) -> RepoRouteResultV2:
```

- `repository_ids=None` → 全库；传 list 限定候选范围（`:113`）
- `use_llm=False` → 只跑 Stage 0（`:114`）

### 1.2 `RepoRouteResultV2` 字段（`:87-93`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `candidates` | `list[RepoRouteCandidateV2]` | 已按 score 降序 |
| `router_version` | `str` | 三个实际取值：`"v2"`（`:157`）/ `"v2_stage0_only"`（`:127`、`:150`）/ `"v1_fallback"`（`:463`） |
| `auto_selected` | `bool` | 仅 `llm_candidates[0].confidence == "high"` 时为 True（`:154`）；其余三条返回路径**恒 False**（`:128`/`:151`/`:464`） |

### 1.3 `RepoRouteCandidateV2` 字段 —— **planner 组装 breakdown 的唯一真实字段名**（`:61-72`）

| 字段名 | 类型 | 默认 | 说明 |
|--------|------|------|------|
| `repo_id` | `str` | 必填 | |
| `repo_name` | `str` | 必填 | v1_fallback 路径可能为 `""`（`:454`） |
| `score` | `float` | 必填 | **已 `min(..., 1.0)` 截顶**（`:252`、`:424`）；v1_fallback 例外，取 `final_score` 未截顶（`:455`） |
| `confidence` | `Confidence` = `Literal["high","medium","low"]` | 必填 | Stage0-only 与 v1_fallback 恒 `"low"`（`:253`、`:456`）；LLM 非法值回退 `"low"`（`:412-415`） |
| `reasoning` | `str` | 必填 | Stage0 为 `"命中能力节点: " + "; ".join(paths)`（`:254`） |
| `sub_project` | `str` | `""` | |
| `sub_project_paths` | `list[str]` | `[]` | |
| `matched_node_paths` | `list[str]` | `[]` | |

`to_dict()`（`:74-84`）序列化八个键同名，唯一差异：`score` 被 `round(self.score, 4)`。

**无 `breakdown` / 无 `signals` / 无 `facets` 字段**（`facets` 只在内部 stage0 dict 里，`:229`，不进候选对象）。

### 1.4 对 adapter 的结论（C1 的落地形态）

adapter 层组装 breakdown 时可用的**外部可见**分量只有一个：`candidate.score`。建议形状：

```python
breakdown = {
    "capability_match": float(c.score),   # RepoRouterV2 原样输出（唯一可得原始信号）
    "charter_match": <adapter 计算>,
    "history_match": <adapter 计算>,
}
total = sum(breakdown.values())   # 「各项之和等于总分」在 adapter 定义域内成立
```

同时透传 `router_version` / `auto_selected` / `confidence` / `reasoning` / `matched_node_paths` 作为证据字段（非分量）。

**降级可观测性要求**：`router_version == "v1_fallback"` 时 `matched_node_paths` 恒为空（`:451-459` 未赋值），`capability_match` 语义与 v2 不同源 —— breakdown 事件里必须带 `router_version`，否则 115 前端无法解释为何无能力节点证据。

---

## 2. charter_service API 与 RepoCharter 字段

### 2.1 公开函数（`server/repositories/services/charter_service.py`，`__all__` 见 `:38-39`）

```python
# :75
def normalize_charter_draft(data: Any) -> dict[str, Any]

# :359-361
async def adraft_charter(
    repository_id: str, *, initiated_by_user_id: str = "system"
) -> RepoCharter | None

# :458-460
async def aconfirm_charter(
    repository_id: str, user: Any, *, edits: dict[str, Any] | None = None
) -> RepoCharter
```

**没有读取函数。** 读章程走裸 ORM，参照 REST 视图范式：

```python
# server/repositories/charter_views.py:40-41
charter = await RepoCharter.objects.select_related("repository").aget(repository_id=...)
```

### 2.2 `adraft_charter` 的关键语义（回灌草案时必须知道）

- 仓库不存在 → `Repository.DoesNotExist` 上抛（`:376`）
- LLM 不可用/解析失败 → 返回 `None`，**零副作用不落行**（`:365-366`、`:393-394`）
- 落库失败 → `CharterPersistError`（`:45`、`:443`）
- 落库三分支（`:397-418`）：无 charter → `create(source=AI_DRAFT, version=1)`；已有且 `source=ai_draft` → 正式字段就地更新（version 不变）；已有 `human_confirmed` → **只写 `draft_content`，正式字段一个不碰**

> **回灌路线的硬约束**：`adraft_charter` 内部是「三源蒸馏 → LLM 单调用 → 归一化落库」（`:387`），**不接受调用方传入草案内容**。CONTEXT.md 要求「职责聚合 → owned_domains 草案 / 移除仓 → boundaries 草案，经 charter_service 产 `source=ai_draft`」——现有签名做不到定向注入。planner 必须选一：
> (a) 在 `charter_service` 新增一个接受 `draft: dict` 的写入函数（复用 `normalize_charter_draft` + 同一套三分支落库语义）；
> (b) 或在 blueprint 侧组装 draft 后走 (a)。
> **不要**直接 `RepoCharter.objects.update()` 旁路——违反 INV-6 且会绕过 `human_confirmed` 保护。

### 2.3 JSONField 内部结构 —— 由 `normalize_charter_draft` 白名单定义（唯一权威）

`owned_domains: list[dict]`（`:101-108`）
| 键 | 类型 | 约束 |
|----|------|------|
| `domain` | str | 截断 200；**空则整项跳过** |
| `status` | str | 只认 `"implemented"` / `"planned"`；非法回退 `"implemented"`（`:98-100`） |
| `note` | str | 截断 500 |
| `citations` | list[str] | 非 list → `[]`；空项剔除（`:68-72`） |

`boundaries: list[dict]`（`:119-125`）
| 键 | 类型 | 约束 |
|----|------|------|
| `rule` | str | 截断 500；**空则整项跳过** |
| `decided_by` | str | 截断 100 |
| `citations` | list[str] | 同上 |

`placement_preferences: list[dict]`（`:137-143`）
| 键 | 类型 | 约束 |
|----|------|------|
| `kind` | str | 截断 200 |
| `target` | str | 截断 200 |
| `note` | str | 截断 500 |
（`kind` 与 `target` 全空 → 整项跳过，`:135-136`）

标量字段：`positioning`（str，`_POSITIONING_MAX`，`:150`）、`audience` / `form`（str 截断 64，`:154-155`）、`evolution`（只认 `"active"` / `"maintenance_only"` / `"deprecated"`，非法回退 `"active"`，`:145-147`）。

### 2.4 `RepoCharter` 模型字段（`server/repositories/models.py:1091-1161`）

| 字段 | 定义行 | 类型 |
|------|--------|------|
| `id` | 1120 | UUID pk |
| `repository` | 1121 | **OneToOneField** → 一仓最多一章程 |
| `version` | 1126 | PositiveIntegerField default=1 |
| `source` | 1127 | CharField，choices=`Source`（`:1107`，值 `ai_draft` / `human_confirmed`） |
| `confirmed_by` | 1132 | FK → user |
| `positioning` | 1140 | TextField |
| `owned_domains` | 1142 | JSONField default=list |
| `boundaries` | 1144 | JSONField default=list |
| `placement_preferences` | 1146 | JSONField default=list |
| `audience` / `form` | 1148-1149 | CharField max_length=64 |
| `evolution` | 1150 | CharField |
| `draft_content` | 1156 | JSONField default=dict |
| `created_at` / `updated_at` | 1158-1159 | |

**`charter_match` 分量的读取口径**：正式字段（不是 `draft_content`）；`source == "ai_draft"` 的章程也在正式字段上（`:409-414` 就地更新），因此 adapter 不必区分 source 即可读——但**建议把 `source` 与 `version` 一起写进 breakdown 证据**，让 115 能标注「该分量依据的是未经人工确认的草案」。

---

## 3. RepoResearchTask / PartialPlan / ResearchService

### 3.1 `RepoResearchTask` 全字段（`server/delivery/models/research_task.py:35-83`）

| 字段 | 行 | 类型 / 约束 |
|------|----|-------------|
| `id` | 38 | UUID pk |
| `session` | 41 | FK → `delivery.ConvergenceSession`，CASCADE，`related_name="research_tasks"` |
| `repository` | 48 | FK → `repositories.Repository`，CASCADE，`related_name="+"` |
| `subagent_session` | 54 | FK → `subagent.SubAgentSession`，**SET_NULL**，null/blank |
| `status` | 61 | CharField(16)，choices=`RepoResearchTaskStatus` |
| `routed_confidence` | 67 | CharField(16) blank default=`""`（存 high/medium/low） |
| `attempt` | 69 | IntegerField default=0 |
| `error` | 71 | JSONField default=dict |
| `created_at` / `updated_at` | 73-74 | |

`RepoResearchTaskStatus`（`:25-32`）：`pending` / `running` / `done` / `failed` / `stale`。
`db_table = "delivery_repo_research_task"`（`:77`）。

**再次强调：无 `report` 字段。**

### 3.2 `PartialPlan`（`:89-115`）—— fitness 段的真实落点

| 字段 | 行 | 说明 |
|------|----|------|
| `research_task` | 93 | FK → RepoResearchTask，CASCADE，`related_name="partial_plans"`（一 task 可多行，`record_partial` 每次 `create`） |
| `content` | 101 | **JSONField default=dict —— fitness 挂这里** |
| `valid` | 103 | BooleanField default=True（重索引置 False） |
| `invalidated_reason` | 104 | CharField(64) |
| `content_hash` | 106 | CharField(64)，sha256 hex，**由 service 算**（`:105-106`） |
| `created_at` | 107 | |

`content` 既有 §7 schema 键（注释 `:98-99`）：`repository_id` / `research_summary` / `proposed_changes[]` / `candidate_files[]` / `api_contracts_exposed[]` / `dependencies_on_other_repos[]`。**模型层与 service 层都不校验 content**（`:100`、`:14-15`）→ 加 `fitness` / `role_suggestion` / `responsibility` / `findings` 是纯加性、无迁移、无校验改动。

**建议形状（加性，与既有键平级）：**
```python
content = {
    # ...既有 §7 键（PLAN 链路复用时保持）...
    "fitness": {"verdict": "suitable|partial|unsuitable", "reasons": [...], "citations": [...]},
    "role_suggestion": "direct|indirect",
    "responsibility": "...",
    "findings": [{"...": "...", "citations": [...]}],
}
```

### 3.3 `ResearchService` 签名（`server/delivery/services/research_service.py:37-227`）

```python
# :40  幂等 get_or_create(session, repository_id)；deep_repos 每项 {"repository_id": str, "routed_confidence": str}
async def create_tasks_for_session(self, session: Any, deep_repos: list[dict]) -> list[RepoResearchTask]

# :72  status→running + 回填 subagent_session FK
async def mark_running(self, task: RepoResearchTask, subagent_session: Any) -> None

# :82
async def mark_done(self, task: RepoResearchTask) -> None

# :91  非 dict error 包成 {"message": str}
async def mark_failed(self, task: RepoResearchTask, error: Any) -> None

# :101 ★ 写 PartialPlan(content + content_hash, valid=True) 且**顺带置 task.status=done**（:122-123）
async def record_partial(self, task: RepoResearchTask, content: dict) -> PartialPlan

# :126 failed|stale → pending + attempt+1；前置校验 session.current_stage == "research" 否则 raise ValueError（:152-156）
async def retry_task(self, task: RepoResearchTask) -> RepoResearchTask

# :172
async def mark_stale(self, task_ids: list) -> int

# :215
async def invalidate_for_repo(self, repository_id: str) -> int
```

**`record_partial` 已含 `mark_done`** → 调用方不要再调 `mark_done`（无害但冗余）。

**`retry_task` 的 stage 名硬编码为 `"research"`**（`:152`）。本相位新 process 的 stage 名是 `repo_research`（CONTEXT §stage graph），**直接复用 `retry_task` 会恒 raise**。planner 必须显式决策：新 adapter 自带重试路径，或让 `retry_task` 接受 stage 白名单参数（后者动的是 `research_service.py`，需确认是否在冻结面内）。

---

## 4. 容器派发接通（mint / env / 回调路由）

### 4.1 token 铸造与吊销（`server/access_tokens/services.py`）

```python
# :32
async def mint_task_token(user: Any, session_id: str, timeout_seconds: int) -> str
#   expires_at = now + timeout_seconds + TASK_TOKEN_EXPIRY_MARGIN(10min，:29)
#   落 AccessToken(kind="task", session_id=..., name=f"task:{session_id}")（:45-54）
#   返回明文（friday_pat_ 前缀）——**唯一一次暴露**，绝不落盘/进日志（:41）

# :67
async def arevoke_task_tokens(session_id: str) -> int
#   filter(kind="task", session_id=..., revoked_at__isnull=True).aupdate(...)（:78-80）
#   幂等（第二次 count=0）+ 整体吞异常返回 0（:70-72）
```

`user` 需 `.id`（`:59`）与可作 FK 的 `created_by`（`:50`）→ 必须是真实 `accounts.User` 实例，不能传 id 字符串。

### 4.2 现有编码链 env 注入键全清单（`server/workflows/nodes/ai/coding.py`）

metadata 键统一带 `env_` 前缀，Runner 侧转为容器环境变量。

| metadata 键 | 行 | 注入条件 |
|-------------|----|----------|
| `env_FRIDAY_TASK_PROJECT_CONTEXT` | 1859 | project_context 非空 |
| `env_FRIDAY_TASK_GIT_ACCESS_TOKEN` | 1887 | token 非空 |
| `env_FRIDAY_TASK_GIT_AUTH_TYPE` = `"token"` | 1888 | 同上 |
| `env_FRIDAY_TASK_GIT_SSL_VERIFY` = `"false"` | 1890 | 同上 |
| `env_FRIDAY_TASK_BRANCH_STRATEGY` | 1900 | 恒 |
| `env_FRIDAY_TASK_TARGET_BRANCH` | 1901 | 恒 |
| `env_FRIDAY_TASK_CLAUDE_API_KEY` | 1911 | api_key 非空 |
| `env_FRIDAY_TASK_CLAUDE_BASE_URL` | 1913 | **base_url 非空才注入**（空则不注入该键，`:1907`、`:70`） |
| `env_FRIDAY_TASK_TOOLS_ENDPOINT` = `f"{base}/api/tools/execute/"` | 1930 | base 可解析 |
| `env_FRIDAY_TASK_KNOWLEDGE_ENDPOINT` = `base`（**裸 base，无路径后缀**） | 1931 | 同上 |
| `env_FRIDAY_TASK_USER_TOKEN` | 1940 | 有触发用户；**无触发用户则省略该键降级不挂**（`:376`、`:1809`） |
| `env_FRIDAY_TASK_EXCLUDE_PATTERNS` | 1948 | JSON 串 |
| `env_FRIDAY_TASK_FOLLOW_OPENSPEC` = `"true"` | 1958 | 仅 approved SDD 仓 |

合并顺序见 `:1979-1985`。

### 4.3 PLAN 链现状（`server/services/process_runtime/research_adapter.py:337-377`）

现有 `_build_dispatch_metadata(repo) -> dict[str, str]` 只注入 6 个键：

| 键 | 行 |
|----|----|
| `env_FRIDAY_TASK_MODE` = `"explore"` | 348 |
| `env_FRIDAY_TASK_TASK_MODE` = `"explore"` | 349 |
| `env_FRIDAY_TASK_CLAUDE_API_KEY` | 353 |
| `env_FRIDAY_TASK_CLAUDE_BASE_URL` | 354 |
| `env_FRIDAY_TASK_CLAUDE_MODEL` | 355 |
| `env_FRIDAY_TASK_CLAUDE_SMALL_MODEL` | 356 |
| `env_FRIDAY_TASK_GIT_ACCESS_TOKEN` / `_AUTH_TYPE` / `_SSL_VERIFY` | 365-367 |
| `_repo_url`（**非 env，`dispatch_task` 构造时 `metadata.pop`**，`:376`、`:207`） | 376 |

**缺 `env_FRIDAY_TASK_TOOLS_ENDPOINT` / `env_FRIDAY_TASK_KNOWLEDGE_ENDPOINT` / `env_FRIDAY_TASK_USER_TOKEN`** → 这三个就是本相位「接通」要补的（复制 `coding.py:1925-1940` 范式）。

注意 PLAN 链 `metadata` 类型标注为 `dict[str, str]`，而 `coding.py` 的 base_url 空值不注入约定同样适用（`coding.py:70` 明确 contract），但 PLAN 链现状是**无条件写入可能为空的 base_url**（`:354`）——补注入时不要沿用这个瑕疵。

### 4.4 PLAN 容器回调链路关键字段

派发侧写入 `SubAgentSession.last_output`（`research_adapter.py:191-196`）：

```python
last_output={
    "source": "plan_research",          # ★ 路由约定
    "plan_session_id": str(session.id),
    "research_task_id": str(task.id),   # ★ 回调反查 task 的键（不依赖 session_id 命名）
    "repository_id": str(task.repository_id),
}
```

其他派发字段：`session_id = f"research-{task.id.hex[:12]}-{uuid4().hex[:6]}"`（**每次派发唯一**，`:176`，理由见 `:171-175`）、`task_type=SubAgentSession.TaskType.PLAN`（`:186`）、`node_execution_id`（`:190`，Chat 入口为 None）、`AgentSession.metadata={"source": "plan_research", ...}`（`:180`）。`DispatchTask(task_type="plan", ...)`（`:202-215`），`use_call_source(CallSource.PLAN_DEEPEN)` 包住 dispatch（`:217-218`）。

回调侧路由（`server/subagent/api/callbacks.py`）：

| 位置 | 内容 |
|------|------|
| `:1703-1707` | 路由判定 = `task_type == PLAN` **且** `last_output.get("source") == "plan_research"` |
| `:1712-1723` | 由 `last_output["research_task_id"]` → `RepoResearchTask.objects.filter(id=...).afirst()`；缺失/已终态返回 None |
| `:436-438` | 另一处同样按 `research_task_id` 反查 |
| `:1267-1280` | `last_output.source` → 容器 `CallSource` 四类映射；无法判定回退 `sdk_agent_task` |
| `:1834-1838` | 同构范式：`REPO_VERIFY` + `source == "repo_verify"` |

**本相位新增第三种 PLAN 用途** → 必须选一个**新的** `source` 值（如 `"blueprint_repo_research"`），否则与 `plan_research` 判定条件重叠，会被既有 `:1703` handler 抢走并试图落 §7 PartialPlan。同时需在 `:1267-1280` 的 CallSource 映射里补一条，否则该链 LLM 调用来源回退成 `sdk_agent_task`（观测规范要求显式 `call_source`）。

---

## 5. delivery knowledge 按 kinds 检索

### 5.1 可用函数签名（`server/knowledge/retrieval.py:30-45`）

```python
class DeliveryKnowledgeSearchService:
    async def search_similar(
        self,
        query: str,
        *,
        user,                                     # 必填 kwarg，权限 fail-closed（:47 resolve_allowed_project_ids）
        top_k: int = 10,
        entity_kinds: list[str] | None = None,    # ★ 按 kinds 过滤
        project_ids: list[str] | None = None,
        repository_ids: list[str] | None = None,
        as_of: datetime | None = None,
        include_superseded: bool = False,
        include_document_kind: bool = False,
    ) -> list[SearchResultDTO]:
```

参数名是 **`entity_kinds`**（不是 `kinds`）。

### 5.2 kinds 枚举实际取值（`server/knowledge/models.py:34-54` `EntityKind(models.TextChoices)`）

| 常量 | 字符串值 |
|------|----------|
| `WORK_ITEM` | `"work_item"` |
| `TECH_PLAN` | **`"tech_plan"`** |
| `CODE_CHANGE` | **`"code_change"`** |
| `DOCUMENT` | `"document"` |
| `PROJECT` | `"project"` |
| `REPOSITORY` | `"repository"` |
| `SPACE` | `"space"` |
| `LEARNING_CASE` | `"learning_case"` |

CONTEXT.md 的 `kinds=code_change/tech_plan` 与实际值**逐字一致**，可直接用。

### 5.3 `history_match` 召回的行为约束（分路语义，`server/knowledge/vector_recall.py`）

- `entity_kinds` 走 demand/code **分路白名单交集**（`:115`、`:240`）
- `entity_kinds=["code_change"]` → 仅 code 分路 1 次调用，demand 交集为空被跳过（测试断言 `server/tests/knowledge/test_vector_recall.py:289-302`）
- `entity_kinds=["tech_plan"]` → 走 demand 分路（`test_vector_recall.py:306-316`：demand 白名单含 `work_item`/`tech_plan`/`learning_case`）
- **未知 kind 绝不回退全量**：返回 `[]` + 0 次 hybrid 调用（`vector_recall.py:240` 注释，`test_vector_recall.py:274-282`）

→ `["code_change", "tech_plan"]` 一次调用即覆盖两条分路；无需拆两次调用。

**推荐调用点参考**：`server/services/process_runtime/recall_adapter.py:102`（`entity_kinds=kinds`）已是 process_runtime 内的既有范式，含 `RetrievalTrace` 落库与 `duration_ms` 上报（`:124`、`:224`）——本相位新增召回按观测规范也需上报召回条数/分层耗时/score 并写 `RetrievalTrace`，照抄此文件的埋点结构最省事。

`user` 是必填且 fail-closed —— **后台/系统触发的路由没有 user 时该分量不可得**。planner 必须定义降级：`history_match = 0.0` 且 breakdown 里标记 `history_match_unavailable: "no_acting_user"`，不能静默当 0 分（会让「历史落点」证据缺失伪装成「历史无命中」）。

---

## Pitfalls

### P1. 容器 token 吊销 —— PLAN 链**已复用**编码链吊销，不要重复实现

`arevoke_task_tokens(session.session_id)` 在两个终态回调里位于 **task_type 分支之前**、无条件执行：

- `callbacks.py:945-947`（`_handle_completed`，在 `amark_completed()` 之后、`repo_summary`/`chat_deep_analysis`/`plan_research` 分支之前）
- `callbacks.py:1029-1031`（`_handle_failed`，在 `amark_failed()` 之后）

WS/断连路径同样覆盖：`server/runners/consumers.py:425`、`:503`、`:873`。

→ 本相位只要 `mint_task_token` + 注入三个 env 键，吊销自动生效。
→ **残余风险**（源码注释 `callbacks.py:942-944` 已声明）：`amark_timeout` / `amark_cancelled` 路径**不吊销**，靠 `expires_at` 自过期兜底。PLAN 调研容器若走超时终态，token 会存活到 `timeout + 10min`。若判定不可接受，需显式加钩子——但那是改冻结面 `callbacks.py`，须先确认。
→ **顺序陷阱**：`mint` 必须在 `SubAgentSession` 建行**之后**（token 的 `session_id` 要与 session 一致，吊销按此定位），且 dispatch 失败时要主动 `arevoke`（编码链范式：`coding.py:2043-2047`；chat 链：`server/chat/coding_session_service.py:522-525`）。

### P2. async ORM 必须 `sync_to_async` 的位置

- **`transaction.atomic()` + `select_for_update()` 一律同步函数内 + `sync_to_async` 包**：`charter_service.py:397-431`（`_write`/`_persist` 同步，`await sync_to_async(_persist)()`）、`aconfirm_charter._confirm`（`:470-473`）
- **`ResearchService` 全部写操作**用 `@sync_to_async` 装饰的 `_xxx_sync` 私有方法（`research_service.py:51`、`:76`、`:86`、`:95`、`:112`、`:142`、`:191`、`:225`），公开 async 方法只做纯计算（如 `record_partial` 算 `content_hash`，`:107-110`）再 await
- **`ConvergenceSessionService` 同构**：`_apply_transition_sync`（`convergence_session_service.py:192-203`）、`_create_session_sync`（`:98-111`）
- 单行简单读写可直接用 async ORM API：`aget` / `afirst` / `acreate` / `aupdate`（`callbacks.py:1723`、`research_adapter.py:177`、`:182`、`access_tokens/services.py:45`、`:78-80`）
- **陷阱**：`F()` 表达式条件更新（`research_service.py:157` 的 `attempt=F+1` 范式）在同步块内做；跨 FK 读属性（`task.repository_id` 安全，`task.repository.name` 会触发同步查询）必须 `select_related` 或进 sync 块

### P3. reroute 计数存 `stage_state` 的并发风险 —— **整字典覆盖 + 只能随转移写**

两个硬约束（`server/delivery/services/convergence_session_service.py`）：

1. **`stage_state` 是整字典替换，不是深合并**：`:210-211` `update_values["stage_state"] = stage_state`，`:230-231` 同步内存对象。传入的 dict 会**整体覆盖** DB 里的旧值 —— 只写 `{"reroute_count": 1}` 会**清空** `decomposition` / `routing` / `recall_context` 等既有键（这些键正是 `ConvergenceSession` 只读属性的数据源，`convergence_session.py:136-151`）。
2. **`stage_state` 只能经 `transition()` 写**（`convergence_session.py:132-134` 明确：「写入恒经 `ConvergenceSessionService.transition(stage_state=)`」，INV-6）。没有独立的 `stage_state` 更新入口。

**并发风险场景**：repo_research 是按仓 fan-out 并行（CONTEXT §逐仓容器调研）。多个容器回调若各自 read-modify-write `stage_state`，形成经典 lost-update —— 后写者用陈旧快照覆盖先写者。

**缓解手段**：
- `transition` 的 CAS 前置条件是 `current_stage == from_stage`（`:204`、`:222-227`，冲突 raise），这只保护 **stage 推进**，**不保护同一 stage 内的 `stage_state` 并发写**。
- 因此 reroute 计数**只在单点串行处递增**：即 fan-out barrier 收敛后的那一次 stage 转移（`repo_research → reroute`），由主 agent 单线程读全量 `stage_state` → 浅合并 → 整体传回 `transition(stage_state=merged)`。**绝不**在各容器回调里各自加 1。
- 每次写务必 `merged = {**(session.stage_state or {}), "reroute_count": n}`，并且 `session` 是**刚从 DB 读的新实例**（不要用早先持有的陈旧对象）。
- reroute 上界 ≤2 的判定读同一份 `stage_state`，判定与递增在同一次转移里完成，避免 check-then-act 窗口。

### P4. `retry_task` 的 stage 名硬编码

`research_service.py:152` 断言 `current_stage != "research"` 即 raise。本相位 stage 名为 `repo_research` → 复用即恒失败。见 §3.3 末段。

### P5. `PartialPlan` 每次 `record_partial` 都 `create` 新行

`research_service.py:116-121` 是 `objects.create`（非 `update_or_create`）。重跑/重试同一 task 会产生多行 `PartialPlan`。读取 fitness 时必须按 `valid=True` 过滤并取最新（`created_at` 降序）——模型索引 `("research_task", "valid")` 已就位（`research_task.py:114`）。

---

## Sources

全部为本仓源码直读（HIGH confidence）：

| 主题 | 文件 |
|------|------|
| 1 | `server/codegraph/services/repo_router_v2.py`（:55-160, :206-262, :400-465） |
| 2 | `server/repositories/services/charter_service.py`（:38-157, :320-495）、`server/repositories/models.py`（:1091-1161）、`server/repositories/charter_views.py`（:40-106） |
| 3 | `server/delivery/models/research_task.py`（全文）、`server/delivery/services/research_service.py`（:30-160, :172-227） |
| 4 | `server/access_tokens/services.py`（:28-95）、`server/workflows/nodes/ai/coding.py`（:1809-1990, :2043-2047）、`server/services/process_runtime/research_adapter.py`（:160-222, :337-377）、`server/subagent/api/callbacks.py`（:436-438, :925-1035, :1267-1280, :1703-1723, :1834-1838）、`server/runners/consumers.py`（:425, :503, :873）、`server/chat/coding_session_service.py`（:433-525） |
| 5 | `server/knowledge/retrieval.py`（:30-47）、`server/knowledge/models.py`（:34-54）、`server/knowledge/vector_recall.py`（:55, :115, :219-240）、`server/tests/knowledge/test_vector_recall.py`（:260-316）、`server/services/process_runtime/recall_adapter.py`（:102-224） |
| Pitfalls | 上述 + `server/delivery/services/convergence_session_service.py`（:126-237, :304-316）、`server/delivery/models/convergence_session.py`（:12-22, :80-151） |

**Research date:** 2026-07-30
**Valid until:** 契约随代码变化——执行前若 `repo_router_v2.py` / `research_service.py` / `callbacks.py` 有新提交需复核。
