# Phase 113: 分仓方案与融合（阶段 2/3）+ Blueprint Context Bus - Pattern Map

**Mapped:** 2026-07-30
**Files analyzed:** 11 类新建/修改文件
**Analogs found:** 11 / 11（全部命中强 analog；1 项算法本体无先例，见 No Analog Found）

---

## §13.2 冻结文件速查（只可读、禁改）

DESIGN.md §13.2 第 2 条：v0.20.0 **不改既有 `technical_plan` process 的文件**。下表全部为**只读参考**——照抄结构、另建 `blueprint_*` 新文件，绝不原地改，`git diff --name-only` 必须零命中：

| # | 冻结 analog | 本相位用途 |
|---|---|---|
| 1 | `server/services/process_runtime/architect_merge_adapter.py` | **本相位主 analog（第 2 类）**，融合装配范式；`blueprint_merge.py` 是全新文件 |
| 2 | `server/services/process_runtime/research_adapter.py` | 旧派发面（112-04 已复制不 import） |
| 3 | `server/services/process_runtime/decompose_segments.py` | 旧 technical_plan LLM 单调用 |
| 4 | `server/services/process_runtime/merged_plan.py` | 旧 MergedPlan schema |
| 5 | `server/services/process_runtime/clarify_adapter.py` | 旧澄清 |
| 6 | `server/services/process_runtime/render.py` | 旧渲染 |
| 7 | `server/services/process_runtime/resume.py` | 旧续驱（蓝图走 `blueprint_resume.py`） |
| 8 | `_TECHNICAL_PLAN_STAGES`（`builtin_processes.py:208-301`） | 旧 stage 字典**零触碰**；其 `merge.exhausted: STAGE_FAILED`（`:249`）属旧链，验收 rg 时须排除 |
| 9 | `server/repositories/services/repo_router_v2.py` | 路由输出契约（只读调用） |
| 10 | `server/repositories/services/charter_service.py` | 章程写入 service |
| 11 | `server/delivery/services/event_taxonomy.py` | 只新增 `blueprint_*` 类型，不改既有类型与 payload |

### 🔒 硬约束：公共 handler 工厂 `timeout=60.0` 禁改

禁改点在 `task/core/knowledge_tools.py:253-298`：

```289:299:task/core/knowledge_tools.py
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url,
                    json=args,  # MCP 工具视图直接吃业务参数（无 {name, arguments} 信封）
                    headers={
                        "Authorization": f"Bearer {user_token}",
                        "X-Friday-Session-Id": session_id,
                        "Content-Type": "application/json",
                    },
                    timeout=60.0,
                )
```

`_make_knowledge_handler(tool_name, endpoint_base, user_token, session_id, quota, quota_counter)`（`:253-260`）是**全部 7 个既有工具共用的唯一 handler 工厂**：

- **`timeout=60.0`（`:298`）写死在工厂里，禁止改、禁止加 per-tool 覆盖参数** —— 改它 = 改工厂签名/行为 = 波及 `search_rag_chunks` / `grep_repository` / `get_repository_file` / `search_delivery_knowledge` / `search_learning_cases` / `search_project_context` / `lookup_project_by_branch` 全部 7 个既有工具。因此**不做服务端长轮询**（单次响应必须 < 60s 且留网络余量 ≈ ≤25s），短等待改为**容器侧有界轮询**（第 7 类）。
- **`quota_counter = [0]`（`:409`）是 7 工具共享的闭包计数器，禁止改计数逻辑**（不加 per-tool 单独计数）。轮询开销靠**派发时提高配额**吸收：`env_FRIDAY_TASK_KNOWLEDGE_QUOTA=400`（默认 200，`task/core/config.py:108`）。
- **禁止给工厂加 `callback` 参数**（短等待不发心跳）—— 轮询本身每 5s 一次 HTTP 出站即保活。

### 受限面（112 自产，只允许纯追加，`git diff | rg "^-"` 应为空）

`blueprint_schema.py`（故第 1 类另建独立模块）/ `blueprint_route.py` / `blueprint_spec_gate.py` / `blueprint_confirm_gate.py` / `blueprint_resume.py` / `blueprint_lifecycle_service.py` / `entrypoint.py` / `system/models.py` / `system/settings_service.py` / `subagent/api/callbacks.py`（⚠️ 只跑 `ruff check`，**绝不跑 `ruff format`**，该文件有先于蓝图链的 format 漂移）。

### 本相位唯一允许的非纯追加改动（须在 PLAN 显式登记）

- `builtin_processes.py:511` **一行**：`"confirmed": STAGE_DONE` → `"confirmed": "repo_plan"`
- `blueprint_research_adapter.py` 的 `mode` 关键字扩展（2 个函数签名 + 3 处分支）

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| 1. `services/process_runtime/blueprint_repo_plan_schema.py` | schema module | transform（纯函数） | `blueprint_schema.py`（111 自产） | exact |
| 2. `services/process_runtime/blueprint_merge.py` | adapter | 分节 LLM + 确定性投影 + 校验重试 | `architect_merge_adapter.py`（**冻结**）+ `blueprint_route.py`（112 风格） | exact |
| 3. `services/process_runtime/blueprint_reconcile.py`（跨仓 API 对账 + `_coverage_gaps`） | pure functions | transform | `blueprint_quality.py`（111 自产纯函数） | exact |
| 4. `delivery/models/blueprint_context_entry.py` + `migrations/0032_*.py` | model + migration | CRUD（append-only） | `blueprint_thread.py` + `0031_blueprint_models.py` | exact |
| 5. `task/core/knowledge_tools.py` 追加 3 个工具 schema | MCP client tool | request-response | `KNOWLEDGE_TOOL_SCHEMAS` 任一项（`:53-80`） | exact |
| 6. `mcp_tools/{views,serializers,urls}.py` 新增 2 个 view | view | request-response | `ReportProjectStateView`（`views.py:3330-3364`） | exact |
| 7. `task/core/blueprint_context_wait.py`（有界轮询） | container loop | polling（await 原语） | `question_loop.py:59-121` | exact |
| 8. `builtin_processes.py` 追加 `_h_bp_repo_plan` / `_h_bp_merge` | stage handler | control flow | `_h_bp_repo_confirmation`（`:408-442`） | exact |
| 9. `delivery/services/blueprint_context_service.py`（waiter 登记/满足/超时） | service | CRUD + 事务 | `BlueprintLifecycleService.open_thread` 一组（`:347-530`） | exact |
| 10. distill 沉淀调用点（`blueprint_merge` 或 barrier 收尾） | service call | transform | `MemoryService.create_draft`（`memory_service.py:338-388`） | exact |
| 11. `tests/mcp_tools/test_blueprint_context_tools.py` + `tests/services/process_runtime/test_blueprint_{repo_plan,merge}_stage.py` + 并发 seq 测试 | test | — | `test_report_project_state.py` + `test_blueprint_research_stage.py` | exact |

---

## Pattern Assignments

### 1. RepoPlan jsonschema 独立模块 → `blueprint_repo_plan_schema.py`

**Analog:** `server/services/process_runtime/blueprint_schema.py`（1060 行，**112-05 受限面**——本相位不碰它，另建独立模块；见 113-RESEARCH OQ-1）

**结构要点：**

- **三件套 + `__all__` 契约**：`__all__` 只导出「schema 常量 + 校验函数 + 走查/diff 纯函数」（`:29-35`）→ 版本常量（`:37` `BLUEPRINT_SCHEMA_VERSION = "blueprint/v1"`）→ 模块级 schema dict（`:41`）→ **预编译 validator**（`:754` `_VALIDATOR = jsonschema.Draft202012Validator(...)`，注释写清「schema 体量大，避免每次调用重新编译」）→ `validate_*` 函数。
- **模块 docstring 是契约书**：`:1-20` 四段——列出每个导出物的职责、后置检查清单（五项）、「无 `schema_version` 的旧形状 pass-through，零迁移」、以及「**纯函数**（无 IO / 无 ORM / 无 LLM），仅依赖 stdlib + jsonschema」+「与 `merged_plan.py` 平级并存，绝不修改它（§13.2 冻结纪律）」。
- **报错出口唯一且脱敏+截断**：`_MAX_ERROR_CHARS = 500` + `_TRUNCATED_SUFFIX`（`:760-761`），注释解释「jsonschema 对 type/enum 类失败会把被校验实例 repr 整段拼进 message 且不截断，而 content 是半可信正文（可能夹带凭证样本）」；`_format_error`（`:764-775`）内部 `redact_secrets_in_text` 且**脱敏失败也不抛**（`except Exception: pass`，fail-safe）。
- **校验函数签名与不抛契约**：

```793:815:server/services/process_runtime/blueprint_schema.py
def validate_blueprint(content: Any) -> tuple[bool, str | None]:
    """校验 blueprint/v1 content：jsonschema 结构 + 后置引用完整性。
    ...
    Returns:
        ``(True, None)`` 合法；``(False, error_message)`` 非法（报错经
        :func:`_format_error` 脱敏 + 截断，绝不原样回显整段被校验实例）。绝不外抛异常。
    """
    if not isinstance(content, dict):
        return False, "content 必须是 JSON 对象"
    if content.get("schema_version") != BLUEPRINT_SCHEMA_VERSION:
        return True, None
    try:
        errors = sorted(_VALIDATOR.iter_errors(content), key=lambda e: e.json_path)
        if errors:
            first = errors[0]
            return False, _format_error(first.json_path, first.message)
```

- **后置检查排在 jsonschema 之后、逐项带编号注释**（`:817-834`：「后置检查 (a) 引用完整性」/「(b) items[].feature_point_id 可解析」），每项失败返回**可定位**的中文错误串（`f"引用 {cid} 不存在于文档级引用池"`）。
- **`description` 兼作 LLM prompting 说明**（`:39-40` 注释），`additionalProperties` 保持默认允许（兼容演进）。

**沿用：** 新建 `blueprint_repo_plan_schema.py`，导出 `BLUEPRINT_REPO_PLAN_SCHEMA` + `_REPO_PLAN_VALIDATOR` + `validate_repo_plan(content) -> tuple[bool, str | None]`。字段按 DESIGN §5.3（`DESIGN.md:478-491`）：`repository_id / role / responsibility(Block[]) / fitness{verdict,reasons,citations} / current_state[] / impl_items[] / apis_provided[] / apis_consumed[] / local_impact{} / risks(Block[]) / open_question_thread_ids[]`。复用 `_MAX_ERROR_CHARS = 500` + `redact_secrets_in_text` 的报错出口形状（**复制这 12 行，不 import 受限模块的私有函数**）。`role` 枚举对齐 `direct|indirect`，`fitness.verdict` 对齐 `suitable|partial|unsuitable`（与 `callbacks.py:1972-1983` 的 `_BLUEPRINT_VERDICTS` 白名单同值）。

**避免：** 改 `blueprint_schema.py`（112-05 有「冻结面自检零命中」断言，改它要先改断言 = 净负债）；`validate_repo_plan` 外抛异常（调用方靠 `(ok, err)` 决定有界重试 ≤2 轮 → 开澄清线程）；把裸文件路径当 citation id 直接落蓝图（见第 3 类 P-5）。

---

### 2. 融合装配 adapter → `blueprint_merge.py`

**Analog A（范式来源，`server/services/process_runtime/architect_merge_adapter.py`，466 行，§13.2 **冻结只读**）**

**结构要点：**

- **合成器抽象成 `Protocol` + 默认实现**（`:87-117`）：`@runtime_checkable class MergedPlanSynthesizer(Protocol)` 只声明 `async def synthesize(session, partials) -> dict`；`LLMMergedPlanSynthesizer` 五步骨架 `ProviderConfigService.aresolve()` → 取 `extra.default_model`，缺则 `raise RuntimeError("no_default_model")` → `build_chat_model(resolved, model_name, streaming=False)` → `with use_call_source(CallSource.X): await model.ainvoke([system, human])` → `_content_to_text` → `_parse_merged_json`，parse 失败 `raise ValueError("merged_plan_parse_failed")`。
- **⭐「可空串 section」是分节 prompt 的关键范式**（本相位第一继承点）—— 非该场景时该段为空串，prompt 与既有逐字一致（零扰动）：

```50:58:server/services/process_runtime/architect_merge_adapter.py
def _classification_prompt_parts(session: ConvergenceSession) -> tuple[str, str]:
    """feature list 分类结果 → (证据段, execution_plan 附加字段说明)；无分类返回 ``("", "")``。

    非 feature list 会话恒返回两个空串——merge prompt 与既有逐字一致（零扰动）。
    """
    classification = getattr(session, "classification", None) or {}
    items = classification.get("items") or []
    if not items:
        return "", ""
```

拼装侧（`:134-148`）把每个可空段落作为 f-string 插槽：`f"{evidence_section}" f"{classification_section}"`。
- **重试上界是类属性常量**：`MAX_MERGE_RETRIES = 1`（`:170`）；`__init__` 全 keyword-only、每依赖 `x or DefaultX()` 兜底，重依赖用方法内 lazy import（`:172-193`）。
- **`merge()` 七步骨架 + graceful 降级**（`:195-237`）：① `_collect_valid_partials` ② `attempt = await ArchitectMerge.objects.filter(session_id=...).acount()`（**轮次由 DB 计数得出，不存 stage_state**）③ emit started ④ synthesize 包 `except Exception` → 返回 `{"validation_status": "failed", "report", "back_target", "attempt"}` **不上抛** ⑤ schema 门 ⑥ 语义门 ⑦ `_handle_pass` / `_handle_fail`。
- **返回形状恒定四键** `{validation_status, report, back_target, attempt}`（`:219-224`、`:354-359`），pass 分支换成 `{validation_status, artifact_version_id, attempt}`（`:282-286`）。
- **pass 分支的落库与钩子**（`:239-286`）：`ArtifactContentInvalid` 被 catch 后转 `_handle_fail`（**不上抛**）；`version_id = artifact.current_version_id`（注释「async 安全标量」）；后置 hook 全部 `except Exception` 吞掉 + warning（`:272-279` spec 生成、`:288-334` 项目绑定，两处都写「best-effort，绝不反噬融合主链」）。
- **`_emit` 统一包 try/except**（`:431-436`）；`_record_*` 落库经 `@sync_to_async` 且 docstring 声明「INV-6 唯一写入入口」（`:413-429`）。
- **健壮 JSON 解析**（`:439-466`）：`_content_to_text` 兼容 `str` / `list[block]`；`_parse_merged_json` 取首 `{` 到末 `}`、**不 eval**、非 dict 返 None。

**Analog B（本里程碑自产风格基准，`blueprint_route.py`，894 行）** —— 命名 / docstring 语气 / 观测三事件 / `stage_state` 契约表注释的现行态基准；`blueprint_route` 已确立「adapter 返回 dict，转移由 handler 的 `StageOutcome` 决定」。

**沿用：** `BlueprintMergeAdapter.merge(session) -> dict`，返回沿用四键并把 `back_target` 扩为两档：`{"back_target": "repo_plan", "back_repository_id": "<uuid>"}`（单仓归因）/ `{"back_target": "merge"}`（融合归因）。

- **分节多调用**：每段一个 `_draft_<section>()`（`implementation_overview` / `api_contracts` / `interaction_flows` / `impact_analysis`），各自 `use_call_source(CallSource.BLUEPRINT_MERGE)`（111 已注册，**不新增枚举值**）；每段的补充证据用 Analog A 的**可空串 section** 形态拼装。
- **确定性投影不经 LLM**（可断言项）：`repo_associations` ← 确认门锁定产物逐字段投影；`current_state_analysis` ← 各仓 `PartialPlan.content.current_state` 投影；`must_haves` ← 由 `requirement_spec` + `implementation_overview.items` 确定性派生（**111 只有 jsonschema 无派生代码**，`blueprint_schema.py:713-732` 是唯一契约，须新写）。
- **轮次持久化**：蓝图链无 `ArchitectMerge` 对应表 → 轮次落 `stage_state["merge"]["count"]`，递增点**单点串行**（照 `aadvance_reroute` 的「重读 session 新实例 → `{**state, ...}` 浅合并整体回写」，回调路径永不触碰计数）。
- **基线读取**：`ArtifactVersion.objects.filter(artifact_id=...).order_by("-version_no").afirst()`——**不读 `session.current_artifact_version`**（它会落后，112-05 Deviation 3）。落库经 `ArtifactService.add_version(artifact, content, produced_by_session_id=str(session.id), produced_by_ref="blueprint_merge#attempt=N")`（自带 content_hash 幂等）。
- **超界出口**：`STAGE_DONE` + `stage_state["merge"]["unresolved"]` 未决项快照 + 开澄清线程，**绝不 `STAGE_FAILED`**。
- ⭐ **`merge` handler 必须回填 `StageOutcome.current_artifact_version`**——本蓝图链首个用到该字段的 handler（其余七个都没用）。

**避免：** 修改 `architect_merge_adapter.py` 任何一行（§13.2 第 3 项）或 import 其私有函数（`_content_to_text` / `_parse_merged_json` 请复制）；单次巨 prompt（CONTEXT 明令分节）；投影只搬 `fitness` 而漏 `rationale.citations`（见第 3 类 P-8）；LLM 合成失败上抛（必须 graceful 返 failed dict）。

---

### 3. 纯函数对账/归因模块 → `blueprint_reconcile.py`（跨仓 API 对账 + `_coverage_gaps`）

**Analog:** `server/services/process_runtime/blueprint_quality.py`（140 行，111-04 自产，纯函数范式的现行基准）

**结构要点：**

- **模块 docstring 显式分节 + 声明依赖上界**（`:1-14`）：「本模块分两节：**纯函数节**（无 IO / 无 ORM / 无 LLM，stdlib only）… **DB 统计接口节**（占位）… 顶层零 ORM import，未来实装时依赖 delivery models 走函数内懒 import」+ 末句「半可信输入（LLM 装配产物 / golden fixture）逐字段 `.get` 防御，**绝不抛**」。
- **`__all__` 只列公开指标**（`:20-26`），私有判定与走查器 `_` 前缀（`_cited` / `_iter_key_conclusion_citations`）。
- **走查器是 generator 且口径写进 docstring**（这正是 `_coverage_gaps` 要复用的同一遍历）：

```39:65:server/services/process_runtime/blueprint_quality.py
def _iter_key_conclusion_citations(blueprint: Any) -> Iterator[Any]:
    """走查三类关键结论条目，逐条产出其 citations 值（可能为 None / 非 list）。

    三类口径（CONTEXT 锁定）：

    - ``current_state_analysis[].findings[]``——citations 取 ``finding.citations``；
    - ``repo_associations[]``（rationale 级）——citations 取 ``rationale.citations``；
    - ``impact_analysis.affected_features[]``——citations 取 ``feature.citations``。
    """
    if not isinstance(blueprint, dict):
        return
    for analysis in blueprint.get("current_state_analysis") or []:
        if not isinstance(analysis, dict):
            continue
        for finding in analysis.get("findings") or []:
            if isinstance(finding, dict):
                yield finding.get("citations")
    for assoc in blueprint.get("repo_associations") or []:
        if not isinstance(assoc, dict):
            continue
        rationale = assoc.get("rationale")
        yield rationale.get("citations") if isinstance(rationale, dict) else None
```

- **逐层 `isinstance` + `or []` 防御**，非 dict 直接 `continue`（半可信输入零假设）。
- **边界返回值写进 docstring 并解释为约定**（`:68-79`）：「**分母为 0 返回 1.0**——空文档视为无引用缺口，**约定而非巧合**：golden 门槛是『已写下的关键结论必须有据』，不惩罚未写内容」。
- **占位接口也给完整 docstring + `TODO(Phase 114)`**（`:111-140`），返回 `None` 表「指标不可用」而非 0。

**沿用：** 新建 `blueprint_reconcile.py`，纯函数节导出：

- `reconcile_cross_repo_apis(blueprint) -> dict` —— consumed 契约找不到 provider → 标 `availability="needs_support"` 且要求 `support_repository_id` 出现在 `repo_associations`（缺失 = 缺协作仓 → 抛澄清）；provider/consumer 字段不一致（schema / 字段名 / 方向）→ 抛澄清，**绝不静默拍板**。返回 `{"gaps": [...], "conflicts": [...], "missing_support_repos": [...]}`，恒定键形状（对齐 `blueprint_route` 的「形状恒定，下游无需判空分支」）。
- `_coverage_gaps(blueprint) -> list[dict]` —— **复用 `_iter_key_conclusion_citations` 的同一遍历口径，只是产出定位而非布尔**：每项 `{"section", "index", "repository_id"}`；`repository_id` 可解析 → 回 `repo_plan`（带 repo id），否则回 `merge`。
- ⚠️ **P-8**：`repo_associations` 的 citations 走 **`rationale.citations`**（`blueprint_quality.py:59-60`），而 112 确认门 `build_locked_associations` 落的是 `fitness.citations`。融合投影必须**同时填 `rationale.citations`**，否则该类条目分子恒 0、覆盖率被系统性拉低。**可证伪断言**：投影后 `citation_coverage(blueprint)` 对含 N 个 `repo_associations` 的样本 > 0。
- ⚠️ **P-5**：`validate_blueprint` 后置检查 (a)（`blueprint_schema.py:817-826`）要求任何块内 citations id ∈ 顶层引用池，而调研/方案产出的 citations 是**裸文件路径/符号名** → 融合装配必须先建引用池（归一成 citation id 落顶层 `citations`）**或**沿用 112 的白名单过滤（丢弃池外引用）。**两者选一必须在 PLAN 显式定。**

**避免：** 在本模块 import ORM / LLM（顶层零 ORM，必要时函数内懒 import）；对账用 LLM 自查（CONTEXT 明令纯函数）；异常上抛（`.get` 防御 + 返回结构化 gaps）；把阈值写死（阈值走 `SettingKeys.BLUEPRINT_MERGE_CONFIG = "blueprint.merge.config"`，JSON `{citation_coverage_min, max_merge_rounds}`，模块常量 `_DEFAULT_CITATION_COVERAGE_MIN` 只作兜底）。

---

### 4. delivery 新模型 + migration → `BlueprintContextEntry`

**Analog:** `server/delivery/models/blueprint_thread.py`（160 行，111 自产）+ `server/delivery/migrations/0031_blueprint_models.py`（115 行）

**结构要点（模型）：**

- **模块 docstring 声明「本模型层零业务方法」+ 唯一 writer + 守护测试名**（`:1-14`）：「状态与业务流转唯一 writer = `BlueprintLifecycleService`；本模型层**零业务方法**，旁路写表由 `test_blueprint_inv6_guard` 源码扫描锁死」。
- **枚举用 `models.TextChoices` 子类 + 中文 label + 类 docstring**（`:22-59`，五个枚举类）；类型标注 `objects: "models.Manager[BlueprintThread]"`（`:65`）；`id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)`。
- **每个非显然字段上方一行注释解释形状/取值/为什么**（`:74`「删版本不删线程」、`:82-83`「锚点 JSON（null = 全局线程）；形状 {section_path, block_id, ...}」、`:90`「max_length=24：ai_review_finding / repo_confirmation 长 17 字符（P5）」、`:109`「观测规范：绑定触发用户；AI 侧标 system」）。
- **观测字段固定**：`initiated_by_user_id = models.CharField(max_length=64, default="system")`（`:110`）+ `created_at(auto_now_add)` / `updated_at(auto_now)`。
- **Meta 四件套 + 索引带「驱动查询」注释**：

```115:122:server/delivery/models/blueprint_thread.py
    class Meta:
        db_table = "delivery_blueprint_thread"
        verbose_name = "蓝图澄清线程"
        verbose_name_plural = "蓝图澄清线程"
        indexes = [
            # confirm 守卫查询驱动：filter(artifact, status=open, blocking=True)
            models.Index(fields=["artifact", "status", "blocking"]),
        ]
```

- `__str__` 返回 `f"Model({self.id}, {self.kind}/{self.status})"`（`:124-125`）；append-only 表加 `ordering`（`:156`，见 `convergence_session_event.py:44-53` 的 `ordering = ["created_at"]` 先例）。

**结构要点（migration）：**

- `dependencies = [('delivery', '0030_humantask'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]`（`:11-14`）→ **本相位为 `0032_blueprint_context_entry.py`，`dependencies = [("delivery", "0031_blueprint_models")]`**。
- `CreateModel` 只带非 FK 字段 + `options{verbose_name, verbose_name_plural, db_table, ordering}`，FK 与索引/约束走独立 `AddField` / `AddIndex` / `AddConstraint`（`:67-113`）。
- **索引名让 Django 自动生成**（`:74` `name='delivery_ar_artifac_3c2419_idx'`），**唯一约束显式命名**（`:108` `name='uq_blueprint_reviewer_artifact_user'`）。

**沿用（Meta 建议，`convergence_session` 恒为复合索引最左列——所有查询必先按会话隔离）：**

```python
class Meta:
    db_table = "delivery_blueprint_context_entry"
    verbose_name = "蓝图上下文总线条目"
    verbose_name_plural = "蓝图上下文总线条目"
    ordering = ["seq"]                       # 会话内单调序即读取序（append-only）
    indexes = [
        # ① since_seq 增量拉取（await/read 轮询主路径，最高频）
        models.Index(fields=["convergence_session", "seq"]),
        # ② key 前缀查（repo:{id}.api_surface / contract:{name}）走左前缀 range scan
        models.Index(fields=["convergence_session", "key"]),
        # ③ kind + status 过滤（环检测读 active dependency_claim）
        models.Index(fields=["convergence_session", "kind", "status"]),
    ]
    constraints = [
        models.UniqueConstraint(
            fields=["convergence_session", "seq"],
            name="uq_blueprint_context_session_seq",
        ),
    ]
```

**seq 并发分配（锁父行，不锁子表）** —— 本仓无运行时 `Max("seq")` 先例，方案由 delivery 层 `select_for_update` 范式外推（`document_service.py` / `release_service.py` / `sdd_spec_service.py`）：

```python
@sync_to_async
def _append_entry_locked(*, session_id, key, kind, ..., content) -> BlueprintContextEntry:
    with transaction.atomic():
        # 锁父 ConvergenceSession 行 —— 同会话 seq 分配串行化；
        # 不锁子表：select_for_update 对空结果集不产生可靠 gap lock（MySQL/PG 行为不一）
        ConvergenceSession.objects.select_for_update().get(pk=session_id)
        next_seq = (
            BlueprintContextEntry.objects.filter(convergence_session_id=session_id)
            .aggregate(Max("seq"))["seq__max"] or 0
        ) + 1
        return BlueprintContextEntry.objects.create(
            convergence_session_id=session_id, seq=next_seq, key=key, kind=kind, ...
        )
```

`UniqueConstraint` 是**兜底不是主手段**：捕 `IntegrityError` 重试一次（`mcp_tools/views.py:14-15` 已 import `IntegrityError, transaction, Max`）。字段按 CONTEXT 锁定：`convergence_session FK / project FK / key / kind(finding|api_surface|contract|decision|dependency_claim|question) / repository_id / content JSON / produced_by / seq / status(active|superseded)`。

**避免：** 用全局 `AutoField`/DB 序列（跨会话空洞让 `since_seq` 增量语义失效）；`repository_id` 单独建索引（`kind` 过滤后基数已低，实测慢再补）；在模型层写业务方法（写入收口 `BlueprintContextService`，见第 9 类）；waiter 状态放 `stage_state`（并行容器高频写 = 单行 JSON 的 lost-update，`blueprint_research_adapter.py:834` 的「单点串行」缓解手段在此不适用）。

---

### 5. 容器知识 MCP 新工具（客户端侧）→ `KNOWLEDGE_TOOL_SCHEMAS` 追加 3 项

**Analog:** `task/core/knowledge_tools.py:53-80`（`search_rag_chunks`，**完整模板贴下**）

```53:80:task/core/knowledge_tools.py
    {
        "name": "search_rag_chunks",
        "description": (
            "语义检索代码库：用自然语言问题召回相关代码片段（RAG）。"
            "适合「某功能在哪实现」「某概念相关代码」类问题。"
            "必须提供 repository_id / repository_ids，或设 all_repositories=true 跨仓检索。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "自然语言检索问题（必填）"},
                "repository_id": {"type": "string", "description": "单仓 UUID"},
                "repository_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "多仓 UUID 列表",
                },
                "all_repositories": {
                    "type": "boolean",
                    "description": "显式跨全部已索引仓检索",
                },
                "branch": {"type": "string", "description": "分支名（仅单仓时可指定）"},
                "top_k": {"type": "integer", "description": "返回条数上限（默认 30，最大 50）"},
                "max_tokens": {"type": "integer", "description": "结果 token 预算（默认 8000）"},
            },
            "required": ["query"],
        },
    },
```

**结构要点：**

- **表驱动、零 handler 代码**：新增一项即自动获得 handler（`:410-425` 列表推导逐 schema 造 `SdkMcpTool`）+ URL（`:267` `url = f"{endpoint_base.rstrip('/')}/api/mcp/tools/{tool_name}/"`，**tool_name 拼接，零改动可达**）+ allowed_tools（`:436-440` `f"mcp__{KNOWLEDGE_MCP_SERVER_NAME}__{name}"`）。
- **`description` 面向 agent 写「何时用哪个」**（`:51` 注释），三句式：做什么 / 适合什么问题 / 必填约束；每个 property 的 `description` 标「（必填）」与默认值/上界。
- **`input_schema` 字段须逐一对照服务端 RequestSerializer**（`:49-50` 注释）——见第 6 类。

**🔒 公共 handler 工厂的共享点（改它会波及 7 个既有工具，禁止改）：**

| 共享点 | 坐标 | 纪律 |
|---|---|---|
| `timeout=60.0` | `:298` | **禁改** —— 故不做服务端长轮询，短等待走容器侧轮询（第 7 类） |
| `quota_counter = [0]`（7 工具共享闭包计数器） | `:409`、`:272-285` | **禁改计数逻辑** —— 轮询开销靠派发时 `env_FRIDAY_TASK_KNOWLEDGE_QUOTA=400` 吸收 |
| 工厂签名（无 `callback` 参数） | `:253-260` | **禁加参数** —— 短等待**不发心跳**，靠每 5s 一次 HTTP 出站保活 |
| 鉴权头三件套 | `:293-297` | `Authorization: Bearer` / `X-Friday-Session-Id` / `Content-Type`；PAT 只进 header |
| 错误约定（return-not-raise） | `:300-360` | 传输错→`is_error`；401/403→固定文案；其余非 200→**只回显 HTTP code 不回显响应体**；非 JSON→解析失败文案 |
| 日志字段白名单 | `:362-368` | **只记 `tool` / `status` / `duration_ms` / `quota_used`** —— `report_blueprint_context` 的 content 绝不进容器侧日志 |
| 三要素空值短路 | `:394-406` | endpoint/token 任一空 → `return None` 不挂 server（老镜像零回归） |

**沿用：** 追加 `read_blueprint_context`（`key_prefix` / `kind` / `repository_id` / `since_seq` / `limit`）、`report_blueprint_context`（`key` / `kind` / `repository_id` / `content`）、`await_blueprint_context`（`key_pattern` / `timeout_minutes` 默认 3 上界 5 / `poll_interval_s` 默认 5.0）。三者**都走 knowledge 白名单，不走 extra 源**——extra 源（`ask_user` 那样）必须自带 `_BUILTIN_CODING_TOOLS`（`executor.py:106-107`、`:152-158`），漏列会连带禁掉 Bash/Edit/Write（WR-02 前科）。`await_blueprint_context` 的 handler 是唯一例外：它不能只是表项，需要循环包装（第 7 类），但**仍复用 `_make_knowledge_handler` 造的 `read_blueprint_context` handler 作为数据源**，不新造 HTTP 调用。

**向后兼容（P1）：** 老镜像无新工具 = 只是不调，天然安全 → **prompt 措辞必须用条件式**（「若 `await_blueprint_context` 可用则…否则记录假设并继续」），服务端不依赖容器一定写总线；新镜像 + 老服务端 = POST 到不存在 path → 404 → `:329-340` 只回显 `HTTP 404` + `is_error`，容器不崩（已被既有约定兜住）。

**避免：** 改 handler 工厂任何一行；把新工具做成 extra 源；`is_error` 用于「等待超时」（超时应返回**正常结果** `{"hit": false, "waited_ms": ...}`，`is_error` 会诱导模型重试而非降级）。

---

### 6. 容器 MCP 服务端 view（新工具入口 + 三道会话校验）

**Analog:** `server/mcp_tools/views.py:3330-3364`（`ReportProjectStateView`，写类工具 + fail-soft 范式）+ 基类 `McpToolView`（`:235-339`）+ `serializers.py:609-636` + `urls.py:41-127`

**结构要点：**

- **新增一个工具动 4 个位置，无注册表**：`serializers.py` 加 RequestSerializer → `views.py` 加 `McpToolView` 子类 → `urls.py` import + `path("tools/<name>/", XView.as_view(), name="mcp-tool-<kebab-name>")` → `task/core/knowledge_tools.py` 白名单加一项。
- **`post` 四步固定骨架**：

```3350:3364:server/mcp_tools/views.py
    tool_name = "report_project_state"

    async def post(self, request: Request) -> Response:
        run, err = await self._begin(request)
        if err is not None:
            return err
        assert run is not None
        input_data, err = await self._validate(
            ReportProjectStateRequestSerializer, request
        )
        if err is not None:
            return err
        assert input_data is not None
        started_at = time.perf_counter()
        return await self._handle(run, request, input_data, started_at)
```

- **基类白拿的四件事**（`:235-339`）：`authentication_classes = [AccessTokenAuthentication, CookieJWTAuthentication]` + `permission_classes = [IsAuthenticated]`（`:238-239`）；`handle_exception` 把认证异常统一成 `authentication_failed` 401（`:242-249`）；`_begin` 做 `bind_source(LogSource.MCP)` + `request.auth is None` 纵深防御 + `begin_interaction_run(request, source="mcp")`（`:251-265`）；`_record` 一次性写 `arecord_request_metric(source=mcp, route=f"mcp:{tool_name}", labels={call_source, run_id})` + `arecord_tool_call` + 逐条 `arecord_retrieval_trace`（`:283-322`）。**观测埋点零手写。**
- **类 docstring 列「N 道兜底绝不绕过」**（`:3339-3347`）；`_handle` 内定义 `_finish(output_data)`（`_record` 后 200）与 `_skip(reason)`（`{"applied": False, "reason", "run_id"}`）两个闭包（`:3377-3394`）。
- **全路径 fail-soft，任何异常 → 200 + `applied=false`，绝不 5xx**（`:3346`）—— 因为 5xx 会被容器 handler `:329` 吞成「调用失败: HTTP 500」文案，agent 拿不到原因。
- **成员校验 fail-closed 但静默**（`:3404-3412`）：未认证 / 非成员 → `_skip("unauthenticated")` / `_skip("not_member")`，不写、不抛、不阻断。
- **Serializer 宽松 + 归一放 view**（`serializers.py:615-617`）：「单项缺字段**不**整批 400 拒绝，而是在 view 内逐条校验/规范化，非法项标失败、合法项照写」；`ChoiceField(choices=[...])` 做枚举白名单（`:565-571`）；`validate()` 做跨字段互斥校验（`:633-636`）。
- **异常入日志必脱敏 + 截断**：`error=redact_secrets_in_text(str(exc))[:500]`（`views.py:2684` / `:3612` 先例）。

**⭐ 沿用 + 本相位必须自建的三道会话校验（鉴权链纠偏，最重要一条）：**

鉴权链是 **token → owner(User)**，**不存在** token → session → user（`access_tokens/authentication.py:103` `return (token.created_by, token)`）。`X-Friday-Session-Id` 仅是**关联键**（`knowledge_tools.py:386` 明示入 `InteractionRun.raw_request['task_session_id']` 供关联查询），**不可信作授权依据**（P5）。故「只能读写本会话总线」必须在 view 层自建：

1. **会话归属**：header `X-Friday-Session-Id` → `SubAgentSession.objects.filter(session_id=...)` → `last_output["blueprint_session_id"]`（派发侧写入坐标 `blueprint_research_adapter.py:404-409`）→ 且该 SubAgentSession 属 `request.user`（token owner）。**不可只信入参**——入参可伪造，header 值是派发时服务端自己写的。
2. **流程类型**：该 session 关联的 `ConvergenceSession.process_type == "technical_blueprint"`，且 `request.user` 对 `ConvergenceSession.project` 通过成员校验（`_assert_project_member` 形状，`views.py:3320-3327`）。
3. **目标条目同会话**：`BlueprintContextEntry.convergence_session` 与解析出的会话一致。

**缺任一条拒绝（403/404），绝不放行跨会话读写。** ⚠️ 但拒绝**不能是 5xx**——按第 6 类 fail-soft 约定返回 `error_response(...)` 4xx（容器 handler `:315-326` 对 401/403 有固定文案）或 200 + `{"applied": false, "reason": "session_mismatch"}`，二者选一须在 PLAN 定；未知工具名 / 新工具缺失一律**结构化错误而非 500**（CONTEXT 向后兼容锁定项）。

**写入脱敏（P2）：** `content` 是 **JSON dict 不是 str** —— `redact_secrets_in_text(json.dumps(content))` 再 `loads` 会破坏结构且可能产生非法 JSON。**必须递归遍历 dict/list，对每个字符串叶子单独调用**（本仓无现成 JSON 递归脱敏函数，需自建 helper），并覆盖 `key` 与容器传入的自由文本字段。脱敏位置在 **service 层**（先例 `memory_service.py:356` 在 `create_draft` 内部），调用前再来一次是本仓认可的**双保险**（`memory_distill.py:95`）。

**避免：** 同步 `rest_framework.views.APIView`（必须 `from adrf.views import APIView`）；view 里裸写 ORM（写入经 `BlueprintContextService`，INV-6）；任何路径返回 5xx；把 `content` 明文或 query 原文写进日志 / `ConvergenceSessionEvent` payload。

---

### 7. 容器侧有界轮询循环（await 原语）→ `await_blueprint_context`

**Analog:** `task/core/question_loop.py:59-121`（`ask_user_and_wait` 的 deadline 骨架）

**关键片段（逐字，骨架照抄）：**

```59:72:task/core/question_loop.py
async def ask_user_and_wait(
    callback: "CallbackClient",
    question: str,
    *,
    options: list[str] | None = None,
    context: str = "",
    code_snippet: str = "",
    default_option: str = "",
    timeout_minutes: int = 10,
    protocol_dir: str = DEFAULT_PROTOCOL_DIR,
    poll_interval_s: float = 3.0,
    _now: Callable[[], float] | None = None,
    _sleep: Callable[[float], Awaitable[None]] | None = None,
) -> str:
```

```97:121:task/core/question_loop.py
    # ② 有界轮询等回答（期间心跳保活，使 SubAgentSession 保持 RUNNING）。
    deadline = now() + max(0, timeout_minutes) * 60
    while now() < deadline:
        answer = _read_answer(answer_path)
        if answer:
            # 消费后清除 answer.json，避免多轮提问时下一轮误读上一轮的陈旧回答。
            try:
                os.remove(answer_path)
            except OSError:
                pass
            log.info("ask_user_answer_received", has_answer=True)
            return answer
        # 心跳保活（失败不阻断等待）。
        try:
            await callback.report_status(status="progress", message="等待人工回答中")
        except Exception:  # noqa: BLE001 — 心跳失败不影响等待
            pass
        await sleep(poll_interval_s)

    # ③ 超时：default_option 续跑，否则抛 QuestionTimeout（不挂起、不 replan）。
    if default_option:
        log.info("ask_user_timeout_default", timeout=True)
        return default_option
    log.warning("ask_user_timeout_no_default", timeout=True)
    raise QuestionTimeout("未在限定时间内收到人工回答")
```

**结构要点：**

- **`_now` / `_sleep` / `poll_interval_s` 全部可注入**（`:70-71`，docstring `:76-77` 写明「单测无需真实 sleep」）—— 「命中 / 超时」两条断言零成本可证伪。
- `deadline = now() + max(0, timeout_minutes) * 60`（`:98`）—— `max(0, ...)` 兜负值，**while 条件即上界，绝不无限等**。
- **命中即返回 + 消费后清位**（`:100-108`）——防下一轮误读陈旧数据；对应本相位的 `last_seq` 递增（增量幂等，避免重复拉全量）。
- **心跳与轮询解耦，心跳失败 `except: pass` 不阻断等待**（`:109-113`）。
- **模块 docstring 把约束编号列清**（`:7-15`）：向后兼容 / handler 永不 raise（RTOOL-04）/ 脱敏（正文绝不入日志，只记 `has_answer` / `timeout`）/ 不挂起（T-47-03）/ 保活。
- handler 三段防御（`:130-161`）：缺必填 → `is_error`；专用超时异常 → 固定文案 + `is_error`；兜底 `except Exception` → `is_error`（**永不 raise**）。

**沿用（差异点必须逐条落到实现）：**

| 项 | `ask_user` | `await_blueprint_context` |
|---|---|---|
| 数据源 | 共享卷 `answer.json` | **`read_blueprint_context(key_prefix=…, since_seq=last_seq)`**（复用同文件工厂造的 handler） |
| `poll_interval_s` | `3.0`（读本地文件） | **`5.0`**（HTTP + DB 查询，3s 太密） |
| `timeout_minutes` | `10` | **默认 3、硬上界 5**（超 5 分钟应走长等待退出重派） |
| 心跳 | `callback.report_status` | **不发**（工厂无 `callback`，加参数会波及 7 工具；轮询自身的 HTTP 出站即活动性） |
| 超时语义 | `raise QuestionTimeout` → `is_error` | **返回正常结果** `{"hit": false, "waited_ms": …}`，**不是 `is_error`** —— CONTEXT 要求 agent 自行降级（记假设 + 开澄清线程），`is_error` 会诱导重试 |
| 状态推进 | 消费后删文件 | `last_seq` 单调递增 |

**避免：** 服务端长轮询（60s 硬超时 + ASGI 协程占用 + 本仓零先例，P4）；无界 while；把命中的条目 content 写进容器侧日志；超时抛异常。

---

### 8. stage handler 追加 → `_h_bp_repo_plan` / `_h_bp_merge`

**Analog:** `builtin_processes.py:408-442`（`_h_bp_repo_confirmation`，七个 `_h_bp_*` 中形态最全的一个）

```408:442:server/services/process_runtime/builtin_processes.py
async def _h_bp_repo_confirmation(session: Any, engine: Any) -> StageOutcome:
    """repo_confirmation stage：阶段 1 出口硬门 + **五动作驱动重调研的出边判定**。

    判定顺序**固定**为「先 research_required 再 awaiting_confirmation」——否则
    ``add_repo`` 后会被 self-loop 挂起而永远到不了调研（SC-4 断链）。
    ...
    """
    from services.process_runtime.blueprint_confirm_gate import (
        STAGE_STATE_KEY,
        acollect_confirmation_state,
        acollect_pending_research_repos,
    )

    pending = await acollect_pending_research_repos(session)
    if pending:
        # 回 repo_research 增量派发新增/待重调研仓；同时把最新快照刷进 stage_state——
        # 112-04 的 dispatch 只认 stage_state["confirmation"]，不刷就派不到新仓。
        state = await acollect_confirmation_state(session)
        return StageOutcome(
            event="research_required",
            stage_state_update={STAGE_STATE_KEY: state} if state else None,
        )

    adapter = getattr(getattr(engine, "deps", None), "confirm_gate", None)
    if adapter is None:
        return StageOutcome(event="awaiting_confirmation")
    result = await adapter.open_gate(session)
    result = result if isinstance(result, dict) else {}
    event = "confirmed" if result.get("event") == "confirmed" else "awaiting_confirmation"
    return StageOutcome(event=event, stage_state_update=result.get("stage_state") or None)
```

**结构要点：**

- **签名恒为** `async def _h_bp_<stage>(session: Any, engine: Any) -> StageOutcome`。
- **三条 handler 纪律**（区段注释 `:304-316`）：① **软取依赖** `getattr(getattr(engine, "deps", None), "<name>", None)`，缺依赖返回默认 pass-through **不报错**（属性名与 `entrypoint.build_blueprint_engine` 的 deps 逐字一致，防「注册了但恒 pass-through」的静默空转）；② **绝不自行 transition**（engine 纯度）；③ **不重复 emit 事件**（adapter 已 emit，engine 的 transition 也记一条）。
- **`StageOutcome` 四字段用法**（`engine.py:34-46`）：`event`（必填，须在 `transitions` 中登记，未登记会 `ValueError`）/ `stage_state_update: dict | None`（**合并进 `session.stage_state` 的增量 dict；`None` 表不改**）/ `current_artifact_version`（产出主产物时回填）/ `error`（仅 fail 路径）。
- **⭐ `stage_state` 读写约定（两条路径不可混用）**：走 `StageOutcome.stage_state_update` 增量路径 → engine 做合并；走「重读 session 后浅合并」路径（如 `aadvance_reroute`）→ **必须返回整字典**（`_h_bp_reroute:389-391` 注释「它已是 `{**state, ...}`，只取增量会清空 routing / decomposition」）。混用会丢键。
- **绝不写半截键**：缺依赖时 `stage_state_update=None`（`_h_bp_route:357-358` 注释「半截 `routing` 键会让下游把『没跑路由』误当成『跑了但零候选』」）。
- **`result = result if isinstance(result, dict) else {}`** 归一 adapter 返回值；event 用白名单三元式而非直接透传。
- **上界常量复用而非复制字面量**（`:445-451`）：中段 `import ... # noqa: E402` 守「本文件纯追加」纪律。

**已占用 `stage_state` 键（9 个，新增不得冲突）：** `spec_gate` / `routing` / `confirmation` / `reroute` / `repo_research_fitness` / `escalation` / `decomposition` / `include_repos` / `blueprint`。
**本相位新增：** `repo_plan`（分仓方案进度摘要 + 已产 plan 的仓集合）/ `merge`（`{count, unresolved, last_attribution}`）/ `context_bus`（waiter 汇总视图 + 波次预排结果）。三者遵守「只存 id / 计数 / 小摘要，单字段 < 2KB」（`DESIGN.md:472`）。

**沿用（stage graph 目标形状）：**

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

- `_h_bp_repo_plan` **自写完成判据**（读 `PartialPlan.content` 有无 `repo_plan` 段），**不复用 `aall_research_tasks_terminal`**——两 stage barrier 判据同源 + `mark_stale` 会让 stage 1 判据短暂为假（OQ-2 反对项）。
- `_h_bp_merge` **必须回填 `StageOutcome.current_artifact_version`**（本链首个用到它的 handler）。
- `merge` **绝不落 `STAGE_FAILED`**（与 `reroute.exhausted → repo_confirmation` 同源纪律，`:492-494`）。114 追加 `ai_review` 时只需把 `merged` 的 `STAGE_DONE` 改为 `"ai_review"`——与 112-05 留给 113 的接续点形状一致。
- 同步改动：`builtin_processes.py:511` 一行（`STAGE_DONE` → `"repo_plan"`）；`entrypoint.py:168-173` 的 `SimpleNamespace` 加 `repo_plan=` / `merge=` 两属性**并同步改 `:153-155` docstring 名单**（112-05 有等价性断言 `test_blueprint_process_graph.py` 守护，P-9）。验收 rg 口径：`rg -c "^async def _h_bp_"` **7 → 9**；`rg -c "^register_process_type\("` 保持 **3**。

**避免：** 改 `_TECHNICAL_PLAN_STAGES` 或既有 `_h_*`；在 handler 里调 `session_service.transition`；handler 内再 emit adapter 已发的事件；新 stage 硬依赖 deps 而不做 `getattr` 兜底；超限落 `STAGE_FAILED`。

---

### 9. waiter 登记/满足/超时的 service → `BlueprintContextService`

**Analog:** `server/delivery/services/blueprint_lifecycle_service.py:347-530`（`open_thread` / `record_answer` / `resolve_thread` 三方法 + `_*_sync` 三事务，112-02 追加的「唯一 writer」范式）

**结构要点：**

- **区段注释先声明所有权与观测纪律**（`:340-345`）：「`BlueprintThread` / `Message` 的**唯一 writer**；规格门与确认门共用同一套 API；adapter 侧一律**零 ORM 写**（INV-6），只经下列四个方法开/答/解线程。观测规范：日志只记 `thread_id` / `kind` / 计数等标量与关联键，**澄清问题与回答正文绝不进日志**」。
- **公开 async 方法 = 校验 + 委托 `@sync_to_async` 事务 + 结构化日志三段**，全 keyword-only：

```365:423:server/delivery/services/blueprint_lifecycle_service.py
    async def open_thread(
        self,
        artifact: Artifact,
        *,
        kind: str,
        blocking: bool,
        question: str,
        options: list | None = None,
        initiated_by_user_id: str = "system",
        ...
    ) -> BlueprintThread:
        """开一条线程并同事务写入首条 AI 提问消息。

        - ``kind`` 必须 ∈ ``ThreadKind.values``，否则 ``raise ValueError``（DB 不写）。
        - 线程行与首条消息在同一 ``transaction.atomic``：杜绝「有线程无问题」的半截
          线程——那会让 HITL 侧看到一条空白阻塞线程且永远答不了。
        - ``return_stage`` 超 ``max_length=16`` 截断并记 warning（开不出线程 = 规格门
          静默放行，宁可截断也不抛）。
        """
        if kind not in ThreadKind.values:
            raise ValueError(f"非法线程 kind={kind!r}；合法值={sorted(ThreadKind.values)}")
        ...
        logger.info(
            "blueprint_thread_opened",
            category="caller",
            component="blueprint_lifecycle",
            artifact_id=str(artifact.id),
            kind=kind,
            blocking=bool(blocking),
            initiated_by_user_id=initiated_by_user_id or "system",
            thread_id=str(thread.id),
            option_count=len(options or []),
        )
```

- **每条日志五件套固定**：事件名 snake_case + `category="caller"` + `component="<模块>"` + `initiated_by_user_id=... or "system"` + 只含标量/关联键（`option_count` 而非 options 正文）。
- **幂等/防回退写进 docstring 且由事务条件保证**（`:434-437` 「已是 answered/resolved/dismissed 的线程只追加消息、状态不变——重复作答不得把已解决线程拉回待处理」；`:464` 「终态重复调用为幂等 no-op」）。
- **多写同事务**（`:500-517`）：`with transaction.atomic():` 内建线程行 + 首条消息，docstring 解释「半截线程不可接受」；状态推进以 DB 现值为条件（`:528` 注释「防回退」）。
- **CAS + 并发异常**（`:262-270`）：`Model.objects.filter(id=..., field=from_value).update(field=to_value, updated_at=timezone.now())`，`updated != 1` → `raise ConcurrentBlueprintTransitionError`（注释：`updated_at` 是 `auto_now`，`.update()` 绕过它，**必须显式带上**）。
- **事件落库 best-effort**（`:281-337`）：structlog `caller` 事件**必打**；`session` 为空时只 warning 不落 `ConvergenceSessionEvent`（并解释为何用 warning 让这种调用可被发现）；`ConvergenceSessionEvent.objects.acreate(...)` 整段 `except Exception` 吞掉 + warning，「绝不阻断转移」。
- **守卫查询独立成方法可复用**（`:347-363` `ahas_open_blocking_threads(artifact, *, kind=None)`，`kind` 可选以免规格门/确认门互相误挡）。

**沿用：** 新建 `delivery/services/blueprint_context_service.py`，四个公开方法：

- `append_entry(...)` —— 见第 4 类 seq 锁父行事务；**入库前递归脱敏**（P2）；日志 `blueprint_context_entry_appended` 带 `category="sampling"`（CONTEXT：条目读写记 sampling）+ `component="process_runtime"` + `key` / `kind` / `seq`，**content 不进日志**。
- `read_entries(...)` —— `since_seq` / `key_prefix` / `kind` / `repository_id` 过滤，走建议索引；`sampling` 事件。
- `register_waiter(...)` —— 写 `kind="dependency_claim"` 行（key 前缀 `dependency:{from}->{to}`）；**登记时同步做环检测**（读全部 active `dependency_claim` → 建 `{from_repo: {to_repo,…}}` 有向图 → DFS 找环 → 命中即 `BlueprintLifecycleService.open_thread(kind=ai_clarification, blocking=True)` 抛用户裁决，**不 dispatch**，不靠超时兜底）。`caller` 事件 + `ConvergenceSessionEvent`（blueprint_* 既有类型，供 115 时间线可视化「谁在等谁」）。
- `satisfy_waiters(...)` —— `report_blueprint_context` 写入侧**同事务内**把被满足的 waiter 置 `superseded`，然后触发重派 `dispatch(session, force_deep_repository_ids={waiting_repo_id})`（复用 `blueprint_research_adapter.py:750` 的单仓定向通路，`:66` 的增量白名单自动跳过已完成仓）。
- **超时清理挂在 barrier 续驱路径上**（`blueprint_resume.aresume_blueprint_session`，`:154`），**不新起定时任务**。

**避免：** waiter 状态放 `stage_state`（lost-update，P3）；view / 回调裸写 ORM（INV-6）；日志带 content / query 正文；环检测靠定时扫描（CONTEXT 明令登记时判定）；waiter 满足与置 `superseded` 分两个事务（会重复重派）。

---

### 10. distill 沉淀 ProjectMemory 草案

**Analog:** `server/initiatives/services/memory_service.py:338-388`（`create_draft`）+ `memory_distill.py:62-111`（`distill_to_draft`）

```338:371:server/initiatives/services/memory_service.py
    async def create_draft(
        self,
        *,
        project_id: Any,
        content: str,
        proposed_by: Any = None,
        source_conversation_id: Any = None,
        actor: Any = None,
        initiated_by_user_id: Any = None,
        _skip_member_check: bool = False,
    ) -> ProjectMemoryDraft:
        """创建记忆草稿（pending，MEM-04）。脱敏入库，**绝不自动写 active**。

        LLM 蒸馏（``MemoryDistiller``）调本入口产 pending 草稿；人工确认才入库。
        ``_skip_member_check`` 供蒸馏器内部使用（成员校验已在蒸馏入口完成）。
        """
        if not _skip_member_check and proposed_by is not None:
            await self._assert_member(project_id, proposed_by)
        redacted = redact_secrets_in_text(content or "")
        draft = await self._create_draft_locked(
            project_id=project_id,
            content=redacted,
            proposed_by=proposed_by,
            source_conversation_id=source_conversation_id,
        )
        await self._emit(
            taxonomy.ACTION_PROJECT_MEMORY_DRAFT_CREATED,
            actor=actor or proposed_by,
            initiated_by_user_id=initiated_by_user_id,
            ...
        )
        return draft
```

**结构要点：**

- **入库前脱敏不可绕过**且在 service 内部（`:356`）；`_create_draft_locked` 是 `@sync_to_async` 且**只做 `objects.create(..., status=DraftStatus.PENDING)`**（`:373-388`）——业务判断全在 async 层。
- **成员校验 fail-closed**（`:354-355`），`_skip_member_check` 只给已在上游校验过的蒸馏器用（`memory_distill.py:96-103` 传 `True`）。
- **审计事件带 actor 与 `initiated_by_user_id`**（`:363-370`，`actor or proposed_by` 兜底）。
- **`distill_to_draft`（`memory_distill.py:62-111`）**：`:77-79` 成员校验 fail-closed（非成员 `raise MemoryPermissionError`）；`:82-92` LLM 无候选 / 输出 `NONE` → `return None` + 埋点 `memory_distill_no_candidate`（`category="sampling"`）；`:95` 再来一次 `redact_secrets_in_text`（**双保险**）；`:104-110` 埋点 `memory_distill_draft_created`（`category="caller"`）。

**沿用：** 会话结束（barrier 收尾或 `merge` 完成）时，取 `kind ∈ {decision, contract, api_surface}` 且 `status="active"` 的 `BlueprintContextEntry` 拼成 `conversation_text` → `await MemoryDistiller().distill_to_draft(project_id=session.project_id, conversation_text=…, proposed_by=<dispatch 用户>, initiated_by_user_id=…)`。条目本身已是结论文本时可直接 `MemoryService().create_draft(...)` 跳过 LLM。`proposed_by` **必须是真实项目成员 User**（否则 `distill_to_draft:77-79` fail-closed 抛错）——用 `blueprint_research_adapter.py:1103` 的 `_resolve_dispatch_user(session)` 解析；解析不到则**跳过沉淀**（不伪造 actor）。整段 best-effort，失败只 warning，绝不反噬 merge 主链（照 `architect_merge_adapter.py:272-279` 的 hook 形态）。

**避免：** 调 `append` / `confirm_draft` / `record_hook_writeback`（前者直写 active、中者是人工动作入口、后者不产草案）——违反「AI 不覆盖人工」；伪造 `proposed_by`；沉淀失败上抛。

---

### 11. pytest：容器 MCP 工具测试 + 编排 stage 测试 + 并发 seq 测试

**Analog A（MCP 工具测试）:** `server/tests/mcp_tools/test_report_project_state.py`（280 行）

**结构要点：**

- **模块 docstring 用「覆盖：」+ 破折号清单列守护点**（`:1-12`），一条一句，含正/负向与观测项。
- `pytestmark = pytest.mark.django_db(transaction=True)`（`:27`）；`_URL = "/api/mcp/tools/report_project_state/"`（`:30`）——**真打 URL 路径，端到端过认证 + serializer + view**。
- **fixture 是 `mcp_client, access_user` 两件套**（`:65`），`client, _ = mcp_client`；请求经 `await sync_to_async(client.post)(_URL, {...}, format="json")`。
- `@sync_to_async` 包的**独立查询 helper**（`:43-62`：`_state_apis` / `_state_api_count` / `_audit_count` / `_first_audit`）—— 断言从 DB 重读，**不信响应体**。
- 断言分层：`resp.status_code == 200` → `body = resp.json()` 逐键 → 独立查询验行数与规范化结果（`:85-95`）。
- 必测负向：非成员 / 未认证 → `applied=false` + 200 + 不写不抛；逐条 fail-soft；幂等重复写；观测留痕（`ToolCallRecord` / `RequestMetric` 的 `call_source`）。

**Analog B（编排 stage 测试）:** `server/tests/services/process_runtime/test_blueprint_research_stage.py`（699 行，112-04 自产）

**结构要点：**

- **模块 docstring「守 N 件事」编号清单**（`:1-20`），第 1 条通常是「容器上下文接通」/「既有链路零扰动」，并把**可证伪断言写进条目**（如「**明文不等于 DB 任何存储值**（只有 sha256）」）。
- `pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]`（`:45`）—— ⚠️ **async service 跨线程写库必须 `transaction=True`**（111-PATTERNS 第 9 类教训）。
- **patch 目标存为模块常量**（`:47-48` `_RUNTIME_CFG` / `_GIT_TOKEN`），便于集中维护。
- **「工厂与替身」独立区段**（`:51-122`）：`_FakeDispatcher` 手写替身（记录每次 `DispatchTask` + 可对指定 `repo_url` 抛异常，供单仓隔离测试）；`_make_online_runner` / `_make_user` / `_make_repo` / `_make_session(stage_state, *, user=None)` 全部 `acreate`；`_candidate(repo, *, role=, confidence=)` / `_routing_state(*candidates, spec=None)` 造契约形状的 fixture 数据。
- **mock 依赖注入 engine 的 `deps`**（`SimpleNamespace(x=AsyncMock())`，见 `test_classify_stage.py:34-49`），**不 patch 模块全局**；事件断言用 `engine.session_service._emit_event = AsyncMock()` 后按事件名过滤 `call_args_list` 并断言条数 == 1。
- **必测四类**（`test_classify_stage.py:61-138`）：deps 未注入 pass-through / deps 整体 None / 正常路径落 `stage_state` + emit / **依赖抛异常经 engine 兜底落 `failed` 且 `error["stage"]` 正确**。

**沿用（本相位测试组织）：**

| 文件 | 守护点（写进 docstring 编号清单） |
|---|---|
| `tests/mcp_tools/test_blueprint_context_tools.py` | 三道会话校验各一条负向断言（**跨会话读/写必须被拒**，不同 token owner 的 session id → 403/404）；`process_type != technical_blueprint` 被拒；`content` 含 `friday_pat_`/密钥样本 → 入库后已脱敏且 JSON 结构未破坏；未知工具名/新工具缺失 → 结构化错误**非 500**；观测 `call_source` 留痕 |
| `tests/services/process_runtime/test_blueprint_repo_plan_stage.py` | `_h_bp_repo_plan` 四类（deps 未注入 / deps None / 正常落 `stage_state["repo_plan"]` / 依赖异常落 failed）；⭐ **P-1 断言**：写入 `repo_plan` 后 `acollect_fitness(session)[repo_id]["verdict"]` 仍等于写入前的值（read-merge-write 未吃掉 fitness）；⭐ **P-4 断言**：给 plan 容器 session 跑 `_is_blueprint_research` 必须为 `False` |
| `tests/services/process_runtime/test_blueprint_merge_stage.py` | 六段装配「确定性投影不经 LLM」——mock LLM 只覆盖四段，投影两段结果与上游产物**逐字段一致**；`citation_coverage(blueprint) > 0`（P-8）；超界 → `STAGE_DONE` + `unresolved` 非空（**不是 `STAGE_FAILED`**）；`StageOutcome.current_artifact_version` 已回填 |
| `tests/services/process_runtime/test_blueprint_reconcile.py` | 无 DB 纯函数：consumed 无 provider → `needs_support` + 缺 `support_repository_id` 抛澄清；字段不一致 → conflicts 非空；`_coverage_gaps` 能把 gap 定位到具体 `repository_id` |
| `tests/delivery/test_blueprint_context_seq.py` | **并发 seq**：`transaction=True` + 并发/串行多次 `append_entry` → `seq` 严格 1..N 无重复无空洞；构造 `IntegrityError` 后重试一次仍成功；`UniqueConstraint` 名存在 |
| `tests/task/test_blueprint_context_wait.py`（或 task 侧既有测试目录） | 注入 `_now` / `_sleep` 断言：命中即返回且不再轮询；**超时返回 `{"hit": false}` 且不带 `is_error`**；`last_seq` 递增（不重复拉全量）；7 个既有工具的 schema 数量与 `knowledge_allowed_tools()` 长度断言（`7 → 10`，守「工厂零改动」） |

**避免：** class 风格 `TestCase`；patch 模块级全局而非注入 deps；只断言内存对象不重读 DB；漏「依赖异常 → failed」与「LLM 返 None → 保守降级」两条负向路径；并发测试忘加 `transaction=True`；断言「结果级名次」而非「机制级」（如断言覆盖率具体数值而非「投影后 > 0」）。

---

## Shared Patterns（跨文件通用）

### best-effort 不反噬业务
**Source:** `architect_merge_adapter.py:272-279`、`:328-334`、`:431-436`；`blueprint_lifecycle_service.py:331-337`；`memory_distill.py:82-92`；`knowledge_tools.py:300-360`
LLM / 检索 / 事件 / 埋点 / 沉淀 / 凭证解析一律 `except Exception` 吞掉 + `logger.warning`（异常文本先 `redact_secrets_in_text` 并截断 500）+ 返回降级值。容器侧 handler **return-not-raise**。**唯一例外**：跨会话读写校验是 fail-closed 拒绝（安全边界不降级）。

### structlog 三事件 + 分类
**Source:** `blueprint_lifecycle_service.py:294-304`、`feature_classify.py:234-305`
`xxx_started / xxx_completed / xxx_failed`，带 `component="process_runtime"`（或 `"blueprint_lifecycle"`）+ `duration_ms=round((time.monotonic() - started) * 1000, 2)`；completed 带分桶计数。**本相位分类口径（CONTEXT 锁定）**：总线条目读写 = `category="sampling"`；waiter 登记/命中/超时与「谁在等谁」= `category="caller"` + `initiated_by_user_id`（容器动作归属 dispatch 用户，经 `_resolve_dispatch_user`）+ 写 `ConvergenceSessionEvent`（blueprint_* **既有**类型，只新增不改）。

### INV-6 单一写入
**Source:** `architect_merge_adapter.py:14`、`blueprint_lifecycle_service.py:340-342`、`blueprint_thread.py:11-13`
adapter / 回调 / view **零 ORM 写**，全部委托 service（本相位 = `BlueprintLifecycleService` / `BlueprintContextService` / `ResearchService` / `ArtifactService`）。模块 docstring 显式声明这条，配源码扫描守护测试（`test_blueprint_inv6_guard`）。

### async ORM 防裸 lazy-FK
**Source:** `architect_merge_adapter.py:267`（`artifact.current_version_id` 注释「async 安全标量」）、`:388-399`（`.values()` + `async for`）、`blueprint_lifecycle_service.py:230+`（`@sync_to_async` 私有方法）
用标量 id / `.values()` / `.aexists()` / `.afirst()`；必须取 FK 对象时经 `@sync_to_async` 私有方法；事务型多写全在一个 `@sync_to_async` + `transaction.atomic()` 内。

### 容器 metadata 逐键 env（空值不注入）
**Source:** `blueprint_research_adapter.py:474-536`
`env_` 前缀（runner 侧自动 TrimPrefix）；**空值不注入该键**（向后兼容降级）；按来源分组 `**xxx_env` 展开并注释来源 phase。本相位新增 `env_FRIDAY_TASK_KNOWLEDGE_QUOTA="400"`；⚠️ **`env_FRIDAY_TASK_MODE` / `env_FRIDAY_TASK_TASK_MODE` 保持 `"explore"` 不动**（`:476-478`，语义是 git 写拦截，与「调研 vs 拟方案」正交）。

### 受限文件的纯追加纪律
**Source:** `builtin_processes.py:445-451`（中段 `import ... # noqa: E402`）、112-05 的 `__all__ += [...]` 范式
受限面只允许追加：既有 import 块一字不动、新 import 走模块中段 + `# noqa: E402`；`__all__` 用 `+=` 追加。`callbacks.py` **只跑 `ruff check`，绝不跑 `ruff format`**（该文件有先于蓝图链的 format 漂移，format 会打破「`git diff | rg "^-"` 为空」的硬约束）；新增 elif 写单行条件形态避免 formatter 波及紧随的既有 elif。

---

## No Analog Found

| 内容 | 说明 |
|---|---|
| **波次预排算法本体**（按 API provider/consumer 关系预排波次，provider 仓先行） | 无直接先例。最近的形态是 `services/process_runtime/wave_layering.py` 的**纯函数拓扑分层**范式（111-PATTERNS 第 2 类）——沿用其「输入 dict → 输出 `{wave: [ids]}`、零 ORM、可单测」形态自写；输入取各仓 `apis_provided` / `apis_consumed`，环由第 9 类的环检测兜（预排阶段成环即抛澄清，不静默打平）。 |
| **JSON 递归脱敏 helper** | `server/common/logging.py` 只有 `redact_credentials`（`:69`，structlog processor）与 `redact_secrets_in_text`（`:362`，吃 str）两个顶层 `redact*` 函数，**无 JSON 递归版**。须在 `BlueprintContextService` 内自建 `_redact_json(value)`：递归 dict/list、对每个字符串叶子（含 `key` 与 `content.description` / `content.raw` 等自由文本）单独调 `redact_secrets_in_text`。**禁止** `redact_secrets_in_text(json.dumps(content))` 再 `loads`（破坏结构 + 可能产生非法 JSON）。 |
| **`must_haves` 确定性派生** | 全仓 `rg must_haves` 只命中 `blueprint_schema.py`（`:713-732` schema 定义）—— **111 只有 jsonschema 契约，零派生实现**。CONTEXT 说「复用 111 的派生思路」指的是**思路与 schema**，不是代码。参照 `DESIGN.md:326` §3.14 `execution_plan` 的派生口径（从 `implementation_overview.items` 按仓聚合 + `depends_on`/`wave` 拓扑排序，**无 LLM 参与**）。 |
| **`waiting_context` 结构化退出的 source 值** | 沿用 `source="blueprint_research"`（**不新增 source 值**，否则 `callbacks.py:1986` 的三向互斥判定与 `:991`/`:1075` 两个钩子都要加分支），在容器 output 里加与 `fitness` 平级的 `waiting_context` 段 `{"keys": [...], "partial_plan_id": "...", "reason": "..."}`；回调侧在 `_handle_blueprint_research_completion` 内**先探测 `waiting_context`** → 走「登记 waiter + 不判完成」分支。⚠️ 但 plan 链（第 8 类）**必须**换 `source="blueprint_repo_plan"`（P-4），两者不冲突：`waiting_context` 是 output 内的段，`source` 是链路路由键。 |

---

## Metadata

**Analog search scope:** `server/services/process_runtime/`、`server/delivery/{models,migrations,services}/`、`server/mcp_tools/`、`server/access_tokens/`、`server/initiatives/services/`、`task/core/`、`server/tests/{mcp_tools,services/process_runtime}/`
**Files scanned:** 约 45 个候选路径，精读 15 个 analog 文件/切片（`blueprint_schema.py` 与 `blueprint_lifecycle_service.py` 为非重叠定向切片）
**上游输入:** `113-CONTEXT.md`、`113-RESEARCH.md`、`113-RESEARCH-BUS.md`、`112-PATTERNS.md`
**Pattern extraction date:** 2026-07-30
