# Phase 114: 审查与澄清收敛 - Pattern Map

**Mapped:** 2026-07-30
**Files analyzed:** 10 类新建/修改文件
**Analogs found:** 10 / 10（全部命中强 analog；2 项算法本体无先例，见 No Analog Found）

---

## §13.2 冻结清单 + 受限面纪律（本相位硬边界）

### 只读冻结（`DESIGN.md:772`，v0.20 全程禁改，`git diff --name-only` 必须零命中）

| # | 冻结文件 | 114 用途 |
|---|---|---|
| 1 | `server/services/process_runtime/decompose_segments.py` | 旧 technical_plan LLM 单调用（只读参考） |
| 2 | `server/services/process_runtime/research_adapter.py` | 旧派发面 |
| 3 | `server/services/process_runtime/architect_merge_adapter.py` | 旧融合装配 |
| 4 | delivery 侧 `merged_plan.py` | 旧 MergedPlan schema |
| 5 | `server/services/process_runtime/clarify_adapter.py` | 旧澄清（114 的澄清一律走 `BlueprintLifecycleService`） |
| 6 | `server/services/process_runtime/render.py` | 旧渲染 |
| 7 | `_TECHNICAL_PLAN_STAGES`（`builtin_processes.py:208-301`） | 旧 stage 字典**零触碰**（其 `merge.merged: STAGE_DONE` 在 `:246`，验收 rg 时须与蓝图链 `:809` 区分） |

§13.2 第 3 条（`:773`）：`ConvergenceSessionEvent` **只新增 `blueprint_*` 事件类型，不改既有类型与 payload 字段**（`blueprint_review_started/completed/failed` 是新增，合规）。
§13.2 第 5 条（`:775`）：`BlueprintThread.severity` 字段**已存在**（`blueprint_thread.py:92`）→ 本相位**零 migration**，只改 service 签名。给线程模型加字段会引入 migration，**不做**。

### 三条「改动上界」硬纪律（必须逐条登记进 PLAN）

#### ① `blueprint_resume.py` —— 仅限 `_amap_blueprint_status` 消费的映射表追加，**删除行上界 = 0**

允许的**唯一** diff 形状（一行新增，其余一字不动）：

```diff
 _STAGE_BLUEPRINT_STATUS: dict[str, str] = {
     "repo_plan": "drafting",  # == BlueprintStatus.DRAFTING
     "merge": "drafting",  # == BlueprintStatus.DRAFTING
+    "ai_review": "ai_reviewing",  # == BlueprintStatus.AI_REVIEWING
 }
```

- **值用字面量**而非 `BlueprintStatus.AI_REVIEWING` —— 本模块所有 Django import 都在函数内（lazy），模块级表拿不到枚举（`blueprint_resume.py:62-64` 注释已立此纪律）。
- **不改** `_resolve_stage_status`（`:71-82`）/ `_amap_blueprint_status`（`:273`）/ 三个 `a*` 入口的任何行为。
- `test_stage_status_table_matches_enum` 自动覆盖新行；`test_blueprint_status_stage_map` 的**七条参数化断言**（前七 stage 回落 `researching`）必须继续绿。
- 验收口径：`git diff server/services/process_runtime/blueprint_resume.py | rg "^-[^-]"` **必须为空**；任何删除行都要逐行登记并说明。

#### ② `builtin_processes.py` —— 只加注册与新 handler

允许的改动上界**三处**：

```diff
+async def _h_bp_ai_review(session: Any, engine: Any) -> StageOutcome: ...   # ← 新增（第 3 类）

     "merge": StageDef(
         transitions={
             # 114 接续点：追加 ai_review stage 时把该值改为 "ai_review" 即可
-            "merged": STAGE_DONE,
+            "merged": "ai_review",     # ← 113 在 :805-806 显式留好的接续点
             "repo_rework": "repo_plan",
             "remerge": "merge",
             "needs_clarification": "merge",
         },
+    "ai_review": StageDef(...),        # ← 新增一项（第 3 类给出目标形状）
```

前九个 stage 的 handler 与 transitions **一字不动**（对齐 `:786` 注释「上面七个 stage 一字未动」的 113 先例）。
验收：`rg -c "^async def _h_bp_"` **9 → 10**；`rg -c "^register_process_type\("` 保持 **3**；**不新增 `artifact_type`**（仍是 `technical_plan`，`:840-842`）。
同步改 `entrypoint.py` 的 deps `SimpleNamespace` 加 `review=` 属性 **并同步改其 docstring 名单**（112-05 的 `test_blueprint_process_graph.py` 有等价性断言守护）。
⚠️ 已知行为变更（登记在案）：`merge.merged` 改指 `ai_review` 后，已 `current_stage="merge"` 的在途会话下次 advance 会多走一个 stage。旧 `technical_plan` process 零感知。

#### ③ `record_answer` **禁用于 finding 留痕** —— 用新提炼的 `append_note`

```python
# blueprint_lifecycle_service.py:425  record_answer —— 追加消息 **并把 open 推到 answered**
# （_record_answer_sync:520-541 在同事务 filter(id=..., status=OPEN).update(status=ANSWERED)）
```

后果链（`_arecord_gate_note` docstring `:1046-1051` 已逐字写明，112 的教训）：

1. `ahas_open_blocking_threads`（`:347`，**只认 `status=open`**）判为无门 →
2. `transition(pending_review → confirmed)` 的事务内守卫（`_apply_transition_sync:252-259`，同样只认 `open`）放行 → **人审能通过带未决 BLOCKER 的蓝图**；
3. `blueprint_resume` 的 pause 判据（`:100-101` 只认 open+blocking）失守 → 续驱把会话一路 advance 到 `max_steps=20` 后落 FAILED。

**正确通道（四选一，写进 PLAN 的验收断言）：**

| 场景 | 用什么 | 线程状态 |
|---|---|---|
| 创建 finding | `open_thread(kind="ai_review_finding", severity=..., blocking=(severity=="blocker"), ...)` | `open` |
| 中间留痕（「第 2 轮仍未修复」） | **`append_note`**（本相位从私有 `_append_thread_message_sync`（`:1055-1064`）提炼的公开方法） | **不变** |
| finding 已修复 / 误报 | `resolve_thread(thread, resolution=..., dismissed=False\|True)` | `resolved` / `dismissed` |
| 人类回答 `ai_clarification` | `record_answer` ← **这才是它唯一的正当用法** | `open → answered` |

⚠️ `append_note` 必须**把 `_arecord_gate_note`（`:1043-1053`）改为调它**（纯增能力、不改既有语义），**绝不新增第二条旁路写表路径**（`test_blueprint_inv6_guard` 源码扫描会挂）。
⚠️ 配套不变式：**`blocking == (severity == "blocker")`**，用单测锁死。confirm 守卫因此收敛为「无 open+blocking 线程」一条，**直接复用事务内守卫**，不在视图层加事务外二次查询（否则 TOCTOU，P4）。

### 受限面（111/112/113 自产，只允许纯追加，`git diff | rg "^-[^-]"` 应为空）

`blueprint_schema.py` / `blueprint_quality.py` / `blueprint_anchor.py` / `blueprint_merge.py` / `blueprint_reconcile.py` / `blueprint_confirm_gate.py` / `blueprint_spec_gate.py` / `blueprint_repo_plan.py` / `blueprint_lifecycle_service.py`。

`blueprint_lifecycle_service.py` 的三项追加（都是纯追加，须在 PLAN 显式登记）：`open_thread` 加 `severity: str = ""` 形参 + 入参校验 `severity ∈ ThreadSeverity.values or ""`；新增 `append_note`；新增 `areanchor_threads`（第 7 类）。

### `stage_state` 顶层键占用表（新增不得冲突）

`decomposition` / `routing` / `spec_gate` / `repo_research_fitness` / `reroute` / `confirmation` / `repo_plan` / `merge` / `include_repos` / `blueprint`。
**`ai_review` 未被占用** → `blueprint_review.py` 定义 `STAGE_STATE_KEY = "ai_review"`（与三个既有模块的同名常量范式一致）。

⚠️ **绝不复用 `merge` 桶存审查轮次**：`blueprint_merge._build_stage_state`（`:2297`）整桶读改写（`{**state, STAGE_STATE_KEY: bucket}`，`:2330`），塞进去的键会在下次 merge 打回时被覆盖 → 计数归零 → **无限循环**（正是 CONTEXT specifics 第 2 条要证伪的场景）。
⚠️ `DESIGN.md:472`：`stage_state` 只存 id / 计数 / 小摘要（单字段 < 2KB）。**findings 正文绝不进 `stage_state`、绝不进事件 payload**，只存 `{round, thread_ids, blocker_count, warning_count, info_count, back_target, back_repository_id, unresolved}`。

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| 1. `services/process_runtime/blueprint_review.py` 六类机械规则节 | pure functions | transform | `blueprint_reconcile.py`（113-05/06 自产） | exact |
| 2. 同文件 goal-backward LLM 节（`agoal_backward_review`） | LLM adapter fn | request-response（单调用 + 降级） | `blueprint_ambiguity_score.ascore_ambiguity`（`:360-458`） | exact |
| 3. `builtin_processes.py` 追加 `_h_bp_ai_review` + `ai_review` StageDef | stage handler | control flow | `_h_bp_merge`（`:666-720`） | exact |
| 4. findings → 线程批量创建（`open_thread(severity=)` + `append_note`） | service call | CRUD（事务） | `blueprint_spec_gate._open_clarification`（`:284-341`）+ `blueprint_lifecycle_service.open_thread`（`:365`） | exact |
| 5. 有界回退 + 超界转终态携未决项 | adapter control flow | batch + 状态机 | `blueprint_merge` 覆盖率门（`:1692-1808`）+ `decide_back_target`（`:664`） | exact |
| 6. 澄清回灌产新版本（改 content → `add_version` → `transition`） | service chain | transform + CRUD | `blueprint_confirm_gate.alock`（`:492-621`）+ `blueprint_spec_gate._lock_spec`（`:343-462`） | exact |
| 7. 重锚定批量接线（`areanchor_threads`） | service | batch transform | `test_blueprint_anchor.py`（111 单测＝期望调用形状） | role-match（算法有、批量应用无先例） |
| 8. `delivery/api/blueprint_review_views.py`（人审 / patch / findings） | view | request-response | `blueprint_gate_views.py`（112 八端点） | exact |
| 9. `blueprint_resume.py` 映射表追加一行 | config table | — | 113-06 对同文件的改动（`:58-68`） | exact |
| 10. `tests/services/process_runtime/test_blueprint_review*.py` + `tests/delivery/test_blueprint_review_views.py` | test | — | `test_blueprint_reconcile.py` + `test_blueprint_gate_api.py`（+ `test_blueprint_merge_stage.py`） | exact |

---

## Pattern Assignments

### 1. 六类机械规则纯函数集 → `blueprint_review.py` 纯函数节

**Analog:** `server/services/process_runtime/blueprint_reconcile.py`（333 行，113-05/06 自产，**跨仓对账 + `coverage_gaps` 归因**，是本仓「半可信蓝图 → 结构化 findings」的现行基准）

**结构要点：**

- **模块 docstring = 编号契约书**（`:1-20` 三段）：① 「本模块只有纯函数节：无 IO / 无 ORM / 无 LLM，stdlib only；顶层零 ORM import」② 「输入是**半可信**的装配产物……逐字段 `.get` 防御、逐层 `isinstance` 检查，**绝不外抛**——对账结论是编排层『开澄清还是落版本』的判据，抛异常会把『有矛盾』升级成『整轮失败』」③ 「**不用 LLM 自查**：判定必须可复现、可单测、可解释。矛盾一律如实上报双方取值，**绝不静默拍板取其一**」。第 4 段专门纠偏字段路径（一律走 `data_source.*`，顶层同名键一概不读），并写明「按幻觉字段判定 = 让 SC-4 表面通过实际失效」。
- **`__all__` 只列公开判定**（`:28`），内部 helper 全 `_` 前缀并集中在文件尾部 `# ── 内部纯函数 ──` 区段（`:212`）。
- **恒定形状返回 + docstring 逐键解释语义与调用方动作**：

```40:72:server/services/process_runtime/blueprint_reconcile.py
def reconcile_cross_repo_apis(blueprint: Any) -> dict:
    """跨仓 API 对账：消费方是否找到提供方、字段是否一致、协作仓是否在关联清单里。

    Returns:
        **恒定三键形状**（下游无需判空分支，对齐 ``blueprint_route`` 的约定）::

            {
              "gaps": [{"repository_id", "api", "reason": "no_provider"}],
              "conflicts": [{"api", "provider_repository_id", "consumer_repository_id",
                             "field", "provider_value", "consumer_value"}],
              "missing_support_repos": [{"repository_id", "api", "support_repository_id"}],
            }
    """
    result: dict[str, list[dict]] = {"gaps": [], "conflicts": [], "missing_support_repos": []}
```

- **整函数包 `try/except` 兜底并返回已积累的结果**（不是空结果）：

```113:115:server/services/process_runtime/blueprint_reconcile.py
    except Exception:  # noqa: BLE001 — 半可信输入恒不抛：抛了会把「有矛盾」升级成「整轮失败」
        return result
    return result
```

- **有界追加防 HITL 刷屏**（本相位 findings 去重直接沿用）：

```330:333:server/services/process_runtime/blueprint_reconcile.py
def _append(bucket: list[dict], entry: dict) -> None:
    """有界追加（超出 :data:`_MAX_FINDINGS` 静默丢弃：结论已足够开澄清）。"""
    if len(bucket) < _MAX_FINDINGS:
        bucket.append(entry)
```

（`_MAX_FINDINGS = 50`，`:37`，注释「结论会进澄清问题文本与日志，无界列表会把 HITL 面板刷爆」。）

- **「一侧缺值 ≠ 矛盾」的降噪纪律**（`_field_conflicts:286-296`）：「半成品契约在阶段 2 是常态，把『还没写』当成『写错了』会让澄清线程刷满噪声」。114 的规则③⑤⑥必须照抄这条判据分层。
- **口径同源必须写进 docstring**（`_find_provider:269-274`、`coverage_gaps:129-131`）：「两处漂移会导致『预排说有 provider、对账说没有』的自相矛盾（那种矛盾无法被任何一侧的测试逮住）」。
- **逐 section 独立 `index` 计数器**（`coverage_gaps:154 / :173 / :192`）——序号与覆盖率分母逐条对齐。
- **归一化 helper 极小且单一职责**：`_cited`（`:215`，「与 `blueprint_quality._cited` 逐字同源」）/ `_absent`（`:312`）/ `_normalized`（`:322`，`method` 大小写不敏感）。

**沿用（六类规则的落地形状）：**

统一 finding dict：`{"rule_id", "severity", "section_path", "block_id", "repository_id", "detail"}`；每类一个公开纯函数 `check_xxx(content: dict, *, charters: dict[str, dict] | None = None) -> list[dict]`，总入口 `run_mechanical_rules(content, charters=None) -> list[dict]`。

| 规则 | 判据出处（RESEARCH §1 已实读） | 判定档 |
|---|---|---|
| **前置完整性**（P1 新增，短路） | `repo_associations` / `implementation_overview.items` / `requirement_spec.feature_points` 三者任一为空 | BLOCKER + **短路，不跑后五条**（避免一片假通过噪声） |
| ① schema 完整性 | `validate_blueprint`（`blueprint_schema.py:793`，含 5 项后置检查，报错已 `_format_error` 脱敏截断 500 字符） | BLOCKER |
| ② 引用覆盖 | **自写条目级走查**（复刻 `blueprint_quality._iter_key_conclusion_citations:39-47` 的三类口径，但同时 yield `section_path`） | 关键结论无引用 = BLOCKER；事实性断言无引用 = WARNING |
| ③ 角色一致性 | `repo_associations[].role`（`:247-251`）/ `capabilities_used`（`:300-303`）/ `items[].repository_id`（后置检查 (c) `:856-866` 已保证在 associations 内） | direct 仓零实现项 = BLOCKER；item 指向 `role=="indirect"` 的仓 = BLOCKER（纯集合运算）；`capabilities_used` 未被引用 = **WARNING**（唯一模糊匹配项，A4） |
| ④ API 闭环 | `steps[].api_ref`（`:684-687`）/ `api_contracts[].id`（`:509`）/ `direction` 枚举 **`provided`\|`consumed`**（`:522-524`，**不是 `produced`**）/ `data_source.availability`（`:555-559`）/ `support_repository_id`（`:560-563`） | 两条均纯集合运算 → BLOCKER |
| ⑤ 禁令 | `requirement_spec.boundaries`（`:216-219`，弱 schema）/ `constraints`（`:220-223`）/ `rationale.constraint_refs`（`:260-264`，唯一已存在的 constraint 引用通道） | 排期正则 `\d+\s*周` / `week` = BLOCKER；引用不存在的 constraint id = BLOCKER；**语义冲突交 LLM 一类**；扫 out_of_scope 引入时**排除 `deferred_ideas` 段**（`:737-740`）否则误报 |
| ⑥ 章程边界 | `aload_charters`（`blueprint_charter_match.py:288`，best-effort 异常返 `{}`，缺章程的仓**不出现**在结果里→跳过不判）；`RepoCharter.evolution`（`models.py:1150`）/ `boundaries`（`:1144`，`draft_content` `:1156` **不生效**） | direct 仓落在 `maintenance_only` / `deprecated` 且无 `decision_log` 支撑 = BLOCKER；「违背 `boundaries.rule`」是文本语义 → **WARNING 或交 LLM**（A4，强判 BLOCKER 会产生不可复现假阳性） |
| 确认门锁定校验 | `confirmed_at_gate`（`:313-316`）/ `responsibility`（`:272-275`）；写入侧口径 `blueprint_confirm_gate.py:264, :291-303`（block_id 稳定锚 `blk_gate_resp_{repository_id}`） | BLOCKER。**复用 `blueprint_repo_plan.py:165` / `:973` 的既有投影做对比基线**，避免两处口径漂移 |

**避免：** 改 `blueprint_quality.py`（111 已交付、有单测锁口径 —— 条目级走查在 `blueprint_review.py` 内自写）；只看 `citation_coverage` 比率（**分母为 0 返回 1.0**，`blueprint_quality.py:76`，空文档拿满分）；把 `validate_blueprint` 直接当规则①（`:809-810` 对**缺 `schema_version`** 的 content **直接 `return True, None`** → 必须先自行断言 `content.get("schema_version") == "blueprint/v1"`，否则半成品「假通过」）；被减集合为空时判 pass（应判 **skip 或 BLOCKER**，P1）；`direction` 写成 `"produced"`（永远匹配不到）；任何规则外抛异常。

---

### 2. LLM 单调用 + 结构化输出 + 降级（goal-backward 一类）

**Analog:** `server/services/process_runtime/blueprint_ambiguity_score.py:360-458`（`ascore_ambiguity`，112 规格门四维打分调用）

**结构要点（六步骨架，逐字照抄）：**

```360:373:server/services/process_runtime/blueprint_ambiguity_score.py
async def ascore_ambiguity(
    *,
    goal: str,
    feature_points: list[dict[str, Any]],
    constraints: list | None = None,
    prior_context: str = "",
    session_id: str = "",
) -> dict[str, Any] | None:
    """LLM 单调用产出四维歧义分数 + 理由 + 澄清问题；不可用时返回 ``None``。

    ``None`` 是「打分不可得」信号——上游规格门据此**判需澄清**（fail-closed），
    绝不当作「不歧义」放行。成功时返回经 :func:`normalize_ambiguity_scores` 归一的
    ``{"dimensions": ..., "questions": [...]}``。本函数 best-effort，不外抛。
    """
```

- **全 keyword-only 入参 + `-> dict | None` 返回**，`None` 的语义写进 docstring 并**明确要求上游 fail-closed**（不是「无问题」）。
- **重依赖全在函数内 lazy import**（`:376-380`：`langchain_core.messages` / `CallSource, use_call_source` / `build_chat_model` / `ProviderConfigService`）——模块顶层零 LLM 依赖。
- **六步固定顺序**：`started = time.monotonic()` → emit `*_started`（`category="sampling"`，只记计数与布尔：`feature_point_count` / `constraint_count` / `has_prior_context`，**正文不进日志**）→ `ProviderConfigService.aresolve()` 取 `extra.default_model`，**缺则 warning + `return None`**（`:392-402`，不 raise）→ `build_chat_model(resolved, model_name, streaming=False)` → `with use_call_source(CallSource.X): await model.ainvoke(messages)`（`:416-417`）→ `_parse_object_json(_content_to_text(response.content))`，**解析失败 warning + `return None`**（`:421-430`，`reason="unparsable_response"`）。
- **归一化是独立纯函数**（`normalize_ambiguity_scores`，`:153`），LLM 原始输出**从不直接进业务**；上界常量集中在模块头（`_MAX_QUESTIONS = 5` `:57` / `_MAX_QUESTION_CHARS = 300` `:59` / `_MAX_PROMPT_CHARS = 6000` `:63` / `_MAX_REASON_CHARS = 300` `:55`）。
- **completed 事件带归一后的标量与 `duration_ms`**（`:436-447`）。
- **兜底 `except Exception` 且异常文本脱敏**：

```449:457:server/services/process_runtime/blueprint_ambiguity_score.py
    except Exception as exc:  # noqa: BLE001 — best-effort：上游按 fail-closed 处理 None
        logger.warning(
            "blueprint_ambiguity_score_failed",
            category="sampling",
            component="process_runtime",
            session_id=session_id,
            error=redact_secrets_in_text(str(exc)),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
```

- **调用侧的 fail-closed 消费范式**（`blueprint_spec_gate.py:199-209`）：

```206:209:server/services/process_runtime/blueprint_spec_gate.py
        scorer_unavailable = not isinstance(scores, dict)
        if scorer_unavailable:
            scores = normalize_ambiguity_scores(None)
            scores["questions"] = [dict(_FALLBACK_QUESTION)]
```

用**保守常量**补齐（全 1.0 + 一条通用澄清题），**绝不当作通过**。

**沿用：** `blueprint_review.py` 内 `async def agoal_backward_review(*, feature_points, impl_items, test_strategy, must_haves, key_links, session_id="") -> list[dict] | None`：

- `call_source` 用 **111 已注册的 `CallSource.BLUEPRINT_AI_REVIEW`**（**不新增枚举值**）；模型档位与起草同档（§12 已定，走 `extra.default_model`，不强制换模型）。
- **独立 fresh context**：只喂 digest（feature_point / impl_item / test_strategy / must_haves.truths / key_links 的裁剪投影），**不带起草或融合的会话历史**（降相关性偏差，CONTEXT 锁定）。digest 构造照 `blueprint_merge._feature_point_digest`（`:771`）/ `_impl_items_digest`（`:787`）。
- **`None` 语义 = 「LLM 一类不可得」**：上游 **fail-closed 记一条 `severity="warning"` 的 meta finding**（「goal-backward 未能执行」），**不判通过**；机械六类照常跑，审查不因 LLM 挂掉而空转。
- 输出经 `_normalize_findings()` 归一到与机械规则**同一 finding dict 形状**（含条数上界与正文截断），再落线程。
- `sampling` 分类 + `duration_ms`；finding 正文只进线程 body，**不进日志、不进事件 payload**（CONTEXT 观测锁定）。

**避免：** 让 LLM 承担六类机械规则中的任何一条（CONTEXT 明令纯函数化，可复现可证伪是立项前提）；LLM 失败上抛或判通过；新增 `CallSource` 枚举值；把蓝图全文塞进单次 prompt（走 digest + 上界常量）。

---

### 3. 独立审查 stage handler（第 10 个 stage）→ `_h_bp_ai_review`

**Analog:** `server/services/process_runtime/builtin_processes.py:666-720`（`_h_bp_merge`，蓝图链形态最全、且 113 把「三条备选」的取舍逐条论证在 docstring 里）

**结构要点：**

```693:720:server/services/process_runtime/builtin_processes.py
    adapter = getattr(getattr(engine, "deps", None), "merge", None)
    if adapter is None:
        return StageOutcome(event="needs_clarification")

    await _abp_mark_drafting(session)

    result = await adapter.merge(session)
    result = result if isinstance(result, dict) else {}
    status = str(result.get("validation_status") or "")
    stage_state_update = result.get("stage_state") or None

    if status in ("passed", "exhausted"):
        return StageOutcome(
            event="merged",
            stage_state_update=stage_state_update,
            current_artifact_version=result.get("artifact_version_id") or None,
        )
    if status == "retry":
        event = "repo_rework" if str(result.get("back_target") or "") == "repo_plan" else "remerge"
        return StageOutcome(event=event, stage_state_update=stage_state_update)
    # 停在 merge 前先确保有阻塞线程：没有线程的 needs_clarification self-loop 会被续驱
    # 一路 advance 到步数上限，然后落 FAILED（见 `_abp_ensure_blocking_clarification`）。
    await _abp_ensure_blocking_clarification(
        session,
        stage="merge",
        reason=str((result.get("report") or {}).get("reason") or status or "merge_incomplete"),
    )
    return StageOutcome(event="needs_clarification", stage_state_update=stage_state_update)
```

- **签名恒为** `async def _h_bp_<stage>(session: Any, engine: Any) -> StageOutcome`；**软取依赖** `getattr(getattr(engine, "deps", None), "<name>", None)`（属性名与 `entrypoint.build_blueprint_engine` 的 deps 逐字一致，防「注册了但恒 pass-through」的静默空转）。
- ⭐ **`_h_bp_merge` docstring `:682-691` 的三条备选论证（D-W4），114 必须逐条照抄**：返自身 event → **引擎自旋**（每次 advance 重进同一 handler、依赖仍缺、永不收敛）；返终态 event → **假装成功**（「零蓝图产出、`current_artifact_version` 为空，却把会话判成完成 —— 这是最坏的静默失败」）；返 `needs_clarification` → 正确（停在本 stage 且 `wait_status=waiting_clarification`，人工可见、可处置、可续驱）。
- **`StageOutcome` 四字段**（`engine.py:34-46`）：`event`（必填，须在 `transitions` 中登记，未登记 → engine `ValueError`）/ `stage_state_update: dict | None`（**合并进 `session.stage_state` 的增量；`None` 表不改**）/ `current_artifact_version` / `error`（仅 fail 路径）。
- **event 走白名单三元式**，`result = result if isinstance(result, dict) else {}` 归一，**绝不透传** adapter 返回值。
- **绝不写半截键**（`_h_bp_repo_plan:658-662`）：摘要为空时 `stage_state_update=None`。
- **进入 stage 即转蓝图状态**（`await _abp_mark_drafting(session)`，`:697`；幂等 + best-effort，经 lifecycle service）。
- ⭐ **self-loop 前的最后一道防线** `_abp_ensure_blocking_clarification`（`:524-570`），docstring `:527-534` 写明：「`needs_clarification` 是 self-loop 出边，而续驱 helper 只在『有 open+blocking 线程』时才在 `waiting_clarification` 上短路。handler 返回 `needs_clarification` 却没有线程 ⇒ 续驱一路 advance 到 `max_steps` ⇒ 会话被落 `advance_step_limit` **FAILED** —— 明明只是『缺条件、等人处置』，却成了流程失败，蓝图成果一起报废」。且**幂等**（先 `BlueprintThread.objects.filter(blocking=True, status=OPEN).aexists()`，`:543-547`）、**`return_stage` 传本 stage**（漏传会让人审恢复后退回阶段 1）、**问题文本只含 stage 名与枚举化 reason，绝不夹带方案正文**（T-113-42）。
- **`_abp_has_open_blocking_threads`（`:507-521`）探测失败按 `False`（放行推进）** —— 「续驱侧自己有一道 fail-closed 的同款探测，这里再 fail-closed 会让 DB 抖动直接把 stage 钉死在澄清态」。

**沿用（`ai_review` StageDef 目标形状 + stage_state 约定）：**

```python
    "ai_review": StageDef(
        key="ai_review",
        handler=_h_bp_ai_review,
        transitions={
            "review_passed": STAGE_DONE,        # 全清 / 仅 WARNING+INFO → pending_review
            "review_exhausted": STAGE_DONE,     # 超 2 轮 → pending_review 携未决 BLOCKER
            "repo_rework": "repo_plan",         # 仓级 BLOCKER 归因打回
            "remerge": "merge",                 # 融合级 BLOCKER 打回
            "needs_clarification": "ai_review", # self-loop 等澄清
        },
        pausable=True,
        wait_status="waiting_clarification",
    ),
```

- ⚠️ **`transitions` 不含 `failed` 出边** —— 与 `merge`（`:807-808`）同纪律：超界是「待人审」不是「流程失败」。
- 进入即转 `ai_reviewing`（新增 `_abp_mark_ai_reviewing`，照 `_abp_mark_drafting:465` 的幂等 + best-effort 形态）；打回前转回 `drafting`；通过前转 `pending_review`。合法边**已全部存在**（`blueprint_lifecycle_service.py:89-121`：`DRAFTING → AI_REVIEWING`、`AI_REVIEWING → {NEEDS_CLARIFICATION, DRAFTING, PENDING_REVIEW}`），**状态机零改动**；`_CLARIFICATION_RETURN_TARGETS`（`:80-86`）已含 `ai_reviewing` → `return_stage="ai_reviewing"` 合法（`BlueprintThread.return_stage` `max_length=16`，`ai_reviewing` 12 字符，不触发截断）。
- `stage_state_update = {STAGE_STATE_KEY: {...}}`，`STAGE_STATE_KEY = "ai_review"`。
- ⚠️ **`transition` 的 CAS 异常必须处理**（P4）：`ConcurrentBlueprintTransitionError`（`:70`，来自 `_apply_transition_sync:261-269` 的 `updated != 1`）在 handler 内应 `refresh_from_db` 重试一次，或映射成 `needs_clarification` event，**绝不让 engine 落 FAILED**。

**避免：** 改 `_TECHNICAL_PLAN_STAGES` 或既有九个 `_h_bp_*`；在 handler 里调 `session_service.transition`（engine 纯度）；handler 内重复 emit adapter 已发的事件；新 stage 硬依赖 deps 而不 `getattr` 兜底；超界落 `STAGE_FAILED`；`needs_clarification` self-loop 前不 ensure 阻塞线程。

---

### 4. findings → 线程批量创建（`severity` 形参 + `append_note` 留痕）

**Analog:** `server/services/process_runtime/blueprint_spec_gate.py:284-341`（`_open_clarification`，112 的澄清 writer）+ `server/delivery/services/blueprint_lifecycle_service.py:365`（`open_thread`）

**结构要点：**

```299:341:server/services/process_runtime/blueprint_spec_gate.py
        question_text = "\n".join(f"{i}. {q['text']}" for i, q in enumerate(questions, start=1))
        thread = await self.lifecycle.open_thread(
            artifact,
            kind=ThreadKind.AI_CLARIFICATION,
            blocking=True,
            question=question_text,
            options=questions,
            initiated_by_user_id=self._initiated_by(session),
            created_on_version=version,
            return_stage=BlueprintStatus.RESEARCHING,
        )
        ...
        await self._emit(
            session,
            EVENT_BLUEPRINT_SPEC_GATE_CLARIFICATION_ASKED,
            {
                "thread_id": str(thread.id),
                "question_count": len(questions),
                "weighted_total": total,
            },
        )
        logger.info(
            "blueprint_spec_gate_clarification_asked",
            category="caller",
            component="process_runtime",
            session_id=str(session.id),
            artifact_id=str(artifact.id),
            thread_id=str(thread.id),
            question_count=len(questions),
            weighted_total=total,
            threshold=config["threshold"],
            round=round_no + 1,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        return self._result("needs_clarification", str(thread.id), ambiguity, round_no + 1)
```

- **零 ORM 写**：adapter 只调 `self.lifecycle.open_thread(...)`（INV-6，`test_blueprint_inv6_guard` 源码扫描守护）；`ThreadKind.X` 用**枚举常量**而非字面量。
- **`created_on_version` 必传**（`FK → ArtifactVersion`，`null=True` + `SET_NULL`，`blueprint_thread.py:75`）——115 的「这条 finding 是在哪一版提的」靠它。
- **`return_stage` 必传**（`max_length=16`，超长截断 + warning 不抛，`:390-399`）；114 一律传 `"ai_reviewing"`。
- **`initiated_by_user_id` 经统一 helper 解析**（`_initiated_by(session)`，`:629`），AI 侧回落 `"system"`。
- **双通道留痕**：`ConvergenceSessionEvent`（`_emit`，供 115 时间线）+ structlog（`category="caller"` + `component="process_runtime"` + `duration_ms`）。⚠️ **payload 与日志一律只放 `thread_id` / 计数 / 标量**（`question_count` 而不是问题正文）。
- `open_thread` 内部保证（`:365-423`、`_open_thread_sync:486-517`）：`kind ∉ ThreadKind.values` → `raise ValueError`（DB 不写）；**线程行与首条 AI 消息在同一 `transaction.atomic`**（杜绝「有线程无问题」的半截线程）。

**沿用（findings 落库的四条）：**

1. **`open_thread` 追加 `severity: str = ""` 形参**（受限面唯一签名改动，纯追加：默认空 = 既有 112/113 调用逐字等价），在 `_open_thread_sync` 的 `objects.create` 里带上，并补入参校验 `severity ∈ ThreadSeverity.values or ""`。**零 migration**（字段已存在，`blueprint_thread.py:92`）。
2. **调用形状**：

```python
thread = await self.lifecycle.open_thread(
    artifact,
    kind=ThreadKind.AI_REVIEW_FINDING,
    severity=severity,                          # ← 新形参
    blocking=(severity == ThreadSeverity.BLOCKER),   # ⭐ 强制不变式，单测锁死
    question=finding_body,
    anchor={"section_path": ..., "block_id": ..., "quoted_text": ...},
    created_on_version=version,
    initiated_by_user_id="system",
    return_stage="ai_reviewing",
)
```

3. **中间留痕走 `append_note(thread, *, body, author=None, author_type=ThreadAuthorType.AI)`**（本相位从私有 `_append_thread_message_sync`（`:1055-1064`，现硬编码 `author_type=HUMAN`）提炼），**绝不 `record_answer`**（见冻结清单 §③）。同时把 `_arecord_gate_note`（`:1043-1053`）改为调它——纯增能力，不新增第二条旁路写表路径。
4. **去重幂等键 `(rule_id, anchor.block_id or section_path)`**：开线程前查该 artifact 上 `kind="ai_review_finding"` 且 `status__in=[open, answered]` 的既有线程，命中则 `append_note("第 N 轮仍存在")` 而非新开；第 2 轮复检时已修复的走 `resolve_thread(resolution=...)`，误报走 `resolve_thread(dismissed=True)`（`:456`，幂等，终态重复调用 no-op 且不覆盖首次结论）。
5. **`anchor.section_path` 走 111 `iter_blocks` 的「点分 + [标识]」约定**（`blueprint_schema.py:919`，返回 `list[tuple[section_path, block]]`）——115 渲染消费同一路径约定，自写递归必漂移。

**避免：** `BlueprintThread.objects.create(...)` 直写（INV-6 扫描会挂）；`blocking` 与 `severity` 各写各的（会出现「blocker 不阻塞」/「warning 却阻塞」）；finding 正文进日志或 `ConvergenceSessionEvent` payload；同一 block 反复开线程（人审侧噪声爆炸）；`kind` 用字面量而非 `ThreadKind` 枚举。

---

### 5. 有界回退 + 超界转终态携未决项

**Analog:** `server/services/process_runtime/blueprint_merge.py:1692-1808`（113-06 覆盖率门）+ `decide_back_target`（`:664-694`）

**结构要点（整段贴出的是本相位要照抄的骨架）：**

```1692:1741:server/services/process_runtime/blueprint_merge.py
        # ── 引用覆盖率门（FLOW-06 后半，阈值可配）───────────────────────────
        # 位置严格在 `validate_blueprint` 之后、`add_version` 之前：schema 非法的产物连
        # 归因都不该做（缺口清单会指向一份本就非法的文档）。
        min_ratio, max_rounds = await self._aload_merge_config()
        coverage = citation_coverage(assembled)
        exhausted = False
        gate_gaps: list[dict] = []
        decision = {"back_target": "", "back_repository_id": "", "gap_count": 0}
        if coverage < min_ratio:
            gate_gaps = coverage_gaps(assembled)
            decision = decide_back_target(gate_gaps)
            if attempt + 1 <= max_rounds:
                # 有界回退：**不落版本**（未达覆盖率的中间产物不该进版本历史），
                # 轮次由本单点递增后整体回写 stage_state。
                ...
                return self._result(
                    "retry",
                    attempt=attempt + 1,
                    report={
                        "coverage": round(coverage, 4),
                        "min": min_ratio,
                        # 只带计数与前 N 条**定位**，绝不带结论正文（T-113-42）。
                        "gaps": len(gate_gaps),
                        "gap_locations": gate_gaps[:_MAX_UNRESOLVED],
                    },
                    ...
                )
            exhausted = True
```

```1756:1768:server/services/process_runtime/blueprint_merge.py
        if exhausted:
            # ⚠️ 超界出口是 **STAGE_DONE 带未决项**，绝不 failed（OQ-3 / T-113-37）：
            # 蓝图已成形，只是引用覆盖率没达标 —— 那是「待人审」，不是「流程失败」。
            # 版本照落（成果不许丢），未决项进 stage_state 快照供 114 接手。
            unresolved = [dict(gap) for gap in gate_gaps[:_MAX_UNRESOLVED]]
            thread_id = await self._aopen_coverage_clarification(
                session,
                artifact,
                new_version,
                coverage=coverage,
                min_ratio=min_ratio,
                unresolved=unresolved,
            )
```

- **门的位置固定**：`validate_blueprint` 之后、`add_version` 之前（注释解释「schema 非法的产物连归因都不该做」）。
- **轮次单点递增 + 整体回写**：`attempt` 从 `_attempt_of(state)`（`:2289`）读，`_build_stage_state(state, attempt=..., status=..., ...)`（`:2297`）整桶回写；**回退不落版本**，**超界落版本**（成果不许丢）。
- **阈值与轮上界都可配**（`_aload_merge_config`，`:1998`，`SettingKeys` JSON `{citation_coverage_min, max_merge_rounds}`），模块常量 `_DEFAULT_CITATION_COVERAGE_MIN = 0.8`（`:76`）只作兜底。
- **归因两档纯函数**（`decide_back_target:664-694`，恒定三键 `{back_target, back_repository_id, gap_count}`）：缺口全部落在同一 `repository_id` → `repo_plan` + 该仓 id；跨仓或解析不到 → `merge`。
- **未决清单有界 + 只带定位不带正文**（`gate_gaps[:_MAX_UNRESOLVED]`，`report` 里只有 `coverage` / `min` / `gaps` 计数 / `gap_locations`）。
- **超界同时开阻塞澄清线程**（`_aopen_coverage_clarification:1945-1983`），开不出线程也**不上抛**（`:1975` 「exhausted 出口仍成立」）。
- **两个 `_log` 都用 `level="warning"`**，带 `attempt` / `coverage` / `gap_count` / `unresolved_count` / `thread_id` / `back_target`。

**沿用（114 的审查回退，逐项映射）：**

| 项 | 113 覆盖率门 | 114 AI 审查门 |
|---|---|---|
| 触发判据 | `coverage < min_ratio` | 机械六类 + goal-backward 产出**任一 BLOCKER** |
| 轮次存放 | `stage_state["merge"]["count"]` | **`stage_state["ai_review"]["round"]`**（绝不复用 merge 桶） |
| 上界 | `max_merge_rounds`（可配） | **合计 ≤2 轮**（CONTEXT 锁定，同样走可配 setting + 常量兜底） |
| 回退归因 | `decide_back_target(coverage_gaps)` | **仓级 BLOCKER → `repo_rework`（带 `back_repository_id`）；融合级 → `remerge`**（复用同一两档纯函数形状，输入换成 findings 的 `repository_id` 分布） |
| 回退是否落版本 | 否 | **否**（审查未过的中间产物不进版本历史） |
| 超界出口 | `exhausted` → `merged` → `STAGE_DONE` | **`review_exhausted` → `STAGE_DONE`** ⇒ 蓝图转 `pending_review` 并携未决 BLOCKER 清单，**绝不落 FAILED** |
| 仅 WARNING/INFO | — | 直接 `review_passed` → `pending_review`，findings 作人审参考（**不打回**） |
| 未决快照 | `stage_state["merge"]["unresolved"]` | `stage_state["ai_review"]["unresolved"]`（只存 `{rule_id, severity, section_path, block_id, repository_id, thread_id}`，**无正文**） |

**可证伪断言（CONTEXT specifics 第 2 条）：** 构造持续 BLOCKER 的样例 → 断言第 3 次进入 `ai_review` 时走 `review_exhausted`、蓝图状态为 `pending_review`、`stage_state["ai_review"]["unresolved"]` 非空、会话**不是** FAILED；并断言 `stage_state["merge"]` 桶内容未被覆盖（P2）。

**避免：** 把审查轮次塞进 `merge` 桶（会被 `_build_stage_state` 整桶覆盖 → 计数归零 → 无限循环）；超界落 `STAGE_FAILED` 或 `failed` event；未决项带 finding 正文；回退时落版本；轮次上界写死不可配。

---

### 6. 澄清答案回灌产新版本（改 content → `add_version` → `transition` 三步）

**Analog:** `server/services/process_runtime/blueprint_confirm_gate.py:492-621`（`alock`，112 确认门作答→锁定→产物写入全链路）+ `blueprint_spec_gate._lock_spec`（`:343-462`，`decision_log` 合并形状）

**结构要点：**

```546:562:server/services/process_runtime/blueprint_confirm_gate.py
        # 锁定基线取 artifact 的**最新**版本而非 session 钉住的那一版：规格门放行时
        # add_version 已推进 current_version，而 session.current_artifact_version 只在
        # 显式 StageOutcome 里才更新——读 session 那一版会把规格门的成果覆盖回旧内容。
        latest = await self._aload_latest_version(artifact.id)
        base = latest if latest is not None else version
        content = copy.deepcopy(base.content if isinstance(base.content, dict) else {})
        pool = content.get("citations")
        citation_pool = set(pool.keys()) if isinstance(pool, dict) else set()

        associations = build_locked_associations(
            snapshot=snapshot, decisions=decisions, citation_pool=citation_pool
        )
        content["repo_associations"] = associations
        content["decision_log"] = _merge_decision_log(
            content.get("decision_log"),
            _build_decision_entries(snapshot, thread_id=str(thread.id)),
        )
```

```581:609:server/services/process_runtime/blueprint_confirm_gate.py
        try:
            new_version = await self.artifacts.add_version(
                artifact,
                content,
                produced_by_session_id=str(getattr(session, "id", "")),
                produced_by_ref="blueprint_confirm_gate",
            )
        except ArtifactContentInvalid as exc:
            logger.warning(
                "blueprint_confirm_gate_invalid_content",
                ...
                error=redact_secrets_in_text(str(exc)),
            )
            return self._result("awaiting_confirmation", str(thread.id), None, len(associations))

        await self.lifecycle.resolve_thread(
            thread,
            resolution="仓库集与职责已确认锁定。",
            initiated_by_user_id=self._initiated_by(session),
        )
        if acting_user is not None:
            await self.lifecycle.add_reviewer(artifact, acting_user, "repo_confirmation")
```

- **五步固定顺序**：读**最新**版本作基线（**不读 `session.current_artifact_version`**，注释已写明会覆盖回旧内容）→ `copy.deepcopy` 后改 content → `decision_log` 经 `_merge_decision_log` 去重合并 → `add_version(produced_by_session_id=..., produced_by_ref=...)` → 成功后才 `resolve_thread` + `add_reviewer` + `_emit`。
- **CAS 基线防交错**（`:543-545`、`:564-579`）：落库前比对 `thread.updated_at` 快照，「读快照之后又有动作提交」→ 拒绝 + `snapshot_changed` 理由，**不落半合法版本**。
- **`ArtifactContentInvalid` fail-closed**：warning（异常文本 `redact_secrets_in_text`）+ 返回「待处置」结果，**既不放行也不落 failed**（`:501-502` docstring）。
- **`decision_log` 去重合并是独立纯函数**（确认门 `_merge_decision_log:935`，去重键 `(thread_id, action, repository_id)`；规格门 `_merge_decision_log:497-510`，去重键 `thread_id`）。
- **`add_version` 自带幂等**（`artifact_service.py:145-162`，全程 `transaction.atomic`）：`refresh_from_db(fields=["current_version"])` → **同 `content_hash` 直接复用 current，不建行不推进 `version_no`**。hash 口径 `json.dumps(sort_keys=True, ensure_ascii=False, separators=(",",":"))` + sha256（`:43-47`）。
- **`add_version` 先校验后落库**（`:126-130`，`validate_content` 失败 → `raise ArtifactContentInvalid`）——「不合法直接拒绝、不落半合法版本」由这行天然保证。

**沿用（三条链路，共用一个 helper）：**

| 链路 | content 改什么 | `produced_by_ref` |
|---|---|---|
| 澄清答案回灌 | 对应段落由阶段代理重产 + `decision_log` 追加条目 | `"ai_review_reflow:{thread_id}"` |
| 人工 block 编辑 | 按 patch ops（`replace`/`insert`/`delete`）改块 | `"human_edit:{user_id}"` |
| 人审驳回 / AI 打回 | `content["meta"]["revision_round"] = 旧值 + 1` | `"blueprint_review_reject:{user_id}"` |

- ⚠️ **`decision_log` 用规格门形状的超集**（A5）：`{thread_id, question, **answer**, decided_at, decided_by, applied_in_version}`。**必须保 `answer` 键** —— `blueprint_spec_gate._collect_prior_answers:583-593` 读的是 `item.get("answer")`（`:587`），只写 `decision` 会让「同一问题不再重复问」这条已建立的纪律在审查阶段断链（CONTEXT specifics 第 3 条）。`decided_by` 口径：默认 `"human"`，有 `author_id` 取 `str(author_id)`，AI 侧写 `"ai"`（`blueprint_spec_gate.py:548, 558-559`）。按 `thread_id` 去重。
- ⚠️ **`decided_at` 取「线程作答消息的 `created_at`」而非 `timezone.now()`** —— 回灌是**可重放路径**，时间戳每次变会改 `content_hash`（`sort_keys=True` 只消除 key 顺序影响），每次都翻新版本，破坏「同 hash 不翻版本」的幂等意图。
- ⚠️ **`meta.revision_round` 是 content 的 `meta` 段字段**（`blueprint_schema.py:160-164`），**不是模型字段**，全仓无写入方（A6，本相位是首个写入方）。驳回必须走「读 current content → `meta.revision_round += 1` → `add_version` → `transition("drafting")`」三步，**不扩 `_apply_transition_sync`**。⚠️ **顺序：先落版本再转状态**（否则状态已 `drafting` 而轮次未加的窗口里 AI 会拿旧轮次重跑）；重试前**必须重读 current content**而非用内存副本（同 hash 复用只在轮次值相同时才保证不连加两次）。
- 线程收尾：`resolve_thread(thread, resolution=...)` 并把新版本 id 记进 `applied_in_version`（写在 `decision_log` 条目里，`BlueprintThreadMessage` 无「结论」字段）。

**避免：** 读 `session.current_artifact_version` 作基线；不 `deepcopy` 直接改 version.content；`add_version` 失败上抛让 engine 落 failed；`decision_log` 只写 `decision` 不写 `answer`；`decided_at` 用 `timezone.now()`；扩 `_apply_transition_sync` 加 `revision_round`；先 `transition` 再 `add_version`。

---

### 7. 重锚定接线（批量应用 `reanchor`）

**Analog:** `server/tests/delivery/test_blueprint_anchor.py`（154 行，111-02 单测 —— **它定义了期望的调用形状**；`blueprint_anchor.py:9-10` docstring 原文：「批量应用到线程行的调用方在 Phase 114，111 只交付算法与单测」）

**契约（`blueprint_anchor.py:66`，三分支已单测锁死）：**

```python
def reanchor(anchor: dict, new_blocks: list[dict]) -> tuple[dict, str]
# 返回 (new_anchor, anchor_status)；anchor_status ∈ {"anchored", "orphaned"}
# 常量：SIMILARITY_THRESHOLD = 0.85 (:28)，ANCHOR_STATUS_ANCHORED / _ORPHANED (:30-31)
```

**单测立的六条行为契约（114 的批量接线必须逐条保持）：**

```35:43:server/tests/delivery/test_blueprint_anchor.py
def test_exact_block_id_hit_keeps_anchor() -> None:
    anchor = _anchor(block_id="blk_a")
    blocks = [
        {"block_id": "blk_a", "type": "paragraph", "text": "内容已被大改也不要紧"},
        {"block_id": "blk_b", "type": "paragraph", "text": _PARA},
    ]
    new_anchor, status = reanchor(anchor, blocks)
    assert status == ANCHOR_STATUS_ANCHORED
    assert new_anchor is anchor  # 原样返回，未复制改写
```

```57:61:server/tests/delivery/test_blueprint_anchor.py
    new_anchor, status = reanchor(anchor, blocks)
    assert status == ANCHOR_STATUS_ANCHORED
    assert new_anchor["block_id"] == "blk_new"
    assert new_anchor["quoted_text"] == _PARA  # 保留原文
    assert anchor["block_id"] == "blk_gone"  # 入参不被原地修改
```

1. `block_id` 精确命中 → **原对象返回**（`new_anchor is anchor`），不进模糊分支；
2. 模糊命中（≥0.85）→ 换 `block_id`、**保留原 `quoted_text`**、**入参不被原地修改**；
3. 同分取 `block_id` **字典序小者**（确定性）；
4. 完全不同 / `quoted_text` 为空 / 非 dict anchor → `orphaned` 且 **anchor 原样不删不改**；
5. 阈值边界用 `difflib` 现算断言，**不硬编码猜测值**；
6. `_block_text` 覆盖 `paragraph` / `list`（items join）/ `pseudocode`（`code.source`）/ `table`（rows 展平）四型块。

**沿用（新增 `BlueprintLifecycleService.areanchor_threads(artifact, new_content, *, initiated_by_user_id)`）：**

- **输入 `new_blocks` 取法**：`new_blocks = [b for _path, b in iter_blocks(new_content)]`（`iter_blocks` 返回 `list[tuple[section_path, block]]`，`blueprint_schema.py:919`）。
- ⚠️ **`reanchor` 不更新 `anchor.section_path`**（只改 `block_id`）。批量侧必须用 `iter_blocks` 的 path **一并刷新 `anchor["section_path"]`**——115 渲染依赖它定位。
- ⚠️ **性能防护（P3）**：`reanchor:92-100` 对每条线程遍历全部新 block 做 `difflib.SequenceMatcher.ratio()`（准平方级），而它挂在**同步请求路径**（人工编辑 → 产新版本 → 重锚定）。**先用 `diff_blueprint_blocks`（`blueprint_schema.py:1044`）算出变动块集合，只对 anchor 落在变动块上的线程走 `reanchor`**，未变动的直接跳过 —— 把「改一两个块」的常见场景从 O(N×M) 降到 O(1)。**默认不改 `blueprint_anchor.py`**（111 交付、有单测）。
- **批量写回用 `bulk_update(["anchor", "anchor_status"])` 一次落库**，不逐行 `save`；写线程行仍须**经 service**（INV-6）。
- **失锚线程不删**（`anchor_status="orphaned"`）且可集中查询（115 展示「失锚评论」）。

**避免：** 自写模糊匹配（0.85 阈值 + 同分字典序已单测锁死）；原地修改入参 anchor；只更新 `block_id` 而漏刷 `section_path`；对全部线程无差别跑 `reanchor`；在 view / adapter 里直写 `BlueprintThread.anchor`。

---

### 8. 人审 / patch REST 端点 → `delivery/api/blueprint_review_views.py`

**Analog:** `server/delivery/api/blueprint_gate_views.py`（548 行，112 八端点；`:1-28` docstring 立了全部纪律）+ 路由 `server/delivery/urls.py:136-177`

**结构要点（七条惯例，逐条照抄）：**

| 惯例 | 出处 | 内容 |
|---|---|---|
| URL 形状 | `urls.py:139-176` | `artifacts/<uuid:artifact_id>/blueprint-gate/<动作段>/`，动作段字面 kebab-case，`name="blueprint-gate-<动作>"` |
| 一动作一 View | `:4` | 「一动作一 View、**不发明 action 分派**」 |
| 基类 | `:35` | `from adrf.views import APIView`（异步），**不是** `rest_framework.views.APIView` |
| 权限 | `:38, :206, :230, …` | `permission_classes = [IsAuthenticated]`（§6.4「项目成员皆可确认」的低门槛决策） |
| 写入纪律 | `:15-19` | **视图零 ORM 写**，全部委托 service；读路径允许直查；serializer `.data` 一律 `sync_to_async` 包裹 |
| 错误码分层 | `:43-62, :173-179` | 不存在类 → 404 中性消息常量（`_ARTIFACT_MISSING_DETAIL` / `_GATE_NOT_OPEN_DETAIL` / `_SESSION_MISSING_DETAIL`）；入参类 → 400；service 拒绝 → 409 + 码→中文映射表 |
| 续驱接线 | `:21-27` | 改状态的端点在**持久化成功之后**调 `blueprint_resume.aresume_after_gate_action`；失败隔离在 helper 内自带 try/except，视图**不重复包 try**、**不因续驱失败改响应码**；只读端点不接续驱 |

**共用前置 helper（返回三元组，把 404 / 400 统一收口）：**

```163:193:server/delivery/api/blueprint_gate_views.py
async def _aapply_action(request: Any, artifact_id: Any, action: str) -> tuple[Any, dict, Any]:
    """四个「改快照」动作的共用前置：装配上下文 → 委托 service → 归一错误。

    Returns:
        ``(error_response | None, result, session)``——``error_response`` 非 None 时
        调用方直接返回它（视图仍各自负责续驱接线与响应组装）。
    """
    from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService

    artifact, session, thread = await _aload_gate_context(artifact_id)
    if artifact is None:
        return Response(_ARTIFACT_MISSING_DETAIL, status=status.HTTP_404_NOT_FOUND), {}, None
    ...
    if session is None:
        # 拿不到蓝图会话就明确 404——绝不退化成「取别的 process 的会话」继续动作与续驱。
        return Response(_SESSION_MISSING_DETAIL, status=status.HTTP_404_NOT_FOUND), {}, None
    body = request.data if isinstance(request.data, dict) else {}
    try:
        result = await BlueprintLifecycleService().apply_gate_action(...)
    except ValueError as exc:
        return _gate_error_response(exc), {}, session
    return None, result, session
```

**改状态端点的完整形状（fail-closed 409 + 续驱在持久化之后）：**

```232:257:server/delivery/api/blueprint_gate_views.py
    async def post(self, request: Any, artifact_id: Any) -> Response:
        from services.process_runtime import blueprint_resume
        from services.process_runtime.blueprint_confirm_gate import BlueprintConfirmGateAdapter

        error, result, session = await _aapply_action(request, artifact_id, "confirm")
        if error is not None:
            return error
        if result.get("blocked_reason") == "pending_clarification":
            return Response({"detail": "存在未解决的阻塞澄清线程"}, status=status.HTTP_409_CONFLICT)
        ...
        lock = await BlueprintConfirmGateAdapter().alock(session, acting_user=request.user)
        if lock.get("event") != "confirmed":
            # fail-closed：内容非法 / 并发未收敛时不放行、不落 failed，等下一次重试。
            return Response({"detail": ...}, status=status.HTTP_409_CONFLICT)
        await blueprint_resume.aresume_after_gate_action(
            session, initiated_by_user_id=str(request.user.id)
        )
```

**沿用（新建文件 + 五端点，路由前缀 `artifacts/<uuid:artifact_id>/blueprint-review/`）：**

新建 `blueprint_review_views.py` 而非塞进 `blueprint_gate_views.py`（A3）：后者已有八 View + 一批门专属 helper，再塞 4–6 个语义不同的 View 会让「确认门」文件承担两个门的语义；URL 前缀区分也让 115 的数据面一目了然（`blueprint-gate/` = 阶段 1 门，`blueprint-review/` = 阶段 4 人审）。

| 方法 | URL 段 | service 收口 |
|---|---|---|
| GET | `blueprint-review/` | findings + 线程 + 失锚列表快照（**只读，不接续驱**，视图直查允许） |
| POST | `blueprint-review/approve/` | `transition(artifact, "confirmed", acting_user=request.user, initiated_by_user_id=...)` —— 守卫 + reviewer upsert 同事务 |
| POST | `blueprint-review/reject/` | 第 6 类三步链（`meta.revision_round += 1` → `add_version` → `transition("drafting")`）+ 划线评论经 `open_thread(kind="human_comment")` |
| POST | `blueprint-review/edit-blocks/` | 新建 service 方法收口 → `validate_blueprint` 回显中文错因 → `add_version(produced_by_ref=f"human_edit:{user_id}")` → 第 7 类批量重锚定 |
| POST | `blueprint-review/threads/<uuid>/answer/` | `record_answer` ← **此处才是它的正当用法** |

- ⚠️ **approve 不加事务外的「未决 BLOCKER」二次查询**（P4）：`transition(to_status=confirmed)` 的守卫与 CAS 在**同一 `transaction.atomic`**（`:251-269`），视图层先查再转会重新打开 TOCTOU 窗口。靠 `blocking == (severity=="blocker")` 不变式把两条判据收敛成一条，直接复用内建守卫。
- **两类异常错误码分开**：`ValueError`（非法转移，`:169-173`，状态不变 DB 不写）→ 400/409；`ConcurrentBlueprintTransitionError` → 409。
- **编辑者与人审操作者一并 `add_reviewer(artifact, user, first_action=...)` upsert**（`:215`，`aget_or_create`，已在名单原样返回、`first_action` 不覆盖）。
- **改状态端点在持久化后接续驱**（`aresume_after_gate_action`），失败隔离在 helper 内，**视图不重复包 try、不因续驱失败改响应码**；GET 不接。

**避免：** 同步 `rest_framework.views.APIView`；视图裸写 ORM；发明 action 分派参数；错误消息泄露资源存在性（用中性 404 常量）；approve 在事务外二次查询 BLOCKER；patch 不过 `validate_blueprint` 就 `add_version`。

---

### 9. `blueprint_resume` 映射表受限追加

**Analog:** 113-06 对同文件的改动（`blueprint_resume.py:58-68`，注释本身就是纪律书）

```58:68:server/services/process_runtime/blueprint_resume.py
# 113 追加（B3）：stage → 蓝图状态映射。**只登记阶段 2/3 两个 stage**——112 注册的前七个
# stage 不在表内，一律回落 `researching`，与改动前逐字等价（`test_blueprint_status_stage_map`
# 有七条参数化等价性回归断言背书）。
#
# 值用字面量而非 `BlueprintStatus.DRAFTING`：本模块所有 Django 模型 import 都在函数内
# （lazy），模块级表拿不到那个枚举。字面量与枚举值相等（`BlueprintStatus.DRAFTING ==
# "drafting"`，TextChoices）由 `test_stage_status_table_matches_enum` 锁死，防漂移。
_STAGE_BLUEPRINT_STATUS: dict[str, str] = {
    "repo_plan": "drafting",  # == BlueprintStatus.DRAFTING
    "merge": "drafting",  # == BlueprintStatus.DRAFTING
}
```

**结构要点：**

- **注释先声明改动范围与等价性背书**（「只登记 X 个 stage」「与改动前逐字等价，有 N 条参数化断言背书」），再解释**为什么用字面量**。
- **每行值后跟 `# == BlueprintStatus.XXX` 行内注释**，让字面量与枚举的对应关系在阅读时即可核对。
- 消费方 `_resolve_stage_status`（`:71-82`）的 docstring 解释「为什么必须 stage-aware」：「目标态写死 `researching`，已产出 RepoPlan 与融合蓝图的会话会被一路拉回『调研中』…… 用户看到的是『白干了』，114 拿到的状态也对不上（T-113-43）」。

**沿用（本相位的唯一 diff，见冻结清单 §① 的完整 diff 形状）：**

```python
    "ai_review": "ai_reviewing",  # == BlueprintStatus.AI_REVIEWING
```

**删除行纪律（硬约束）：**

- **删除行上界 = 0。** `git diff server/services/process_runtime/blueprint_resume.py | rg "^-[^-]"` 必须为空。
- 若因 formatter 产生任何删除行，**逐行登记并说明**；本文件**只跑 `ruff check`，不跑 `ruff format`**（沿用 113 对 `callbacks.py` 的同款纪律，防 format 漂移打破纯追加约束）。
- **不改** `_resolve_stage_status` / `_amap_blueprint_status` / `adrive_blueprint_session_to_pause_or_terminal` / `aresume_after_gate_action` / `aresume_blueprint_session` 的任何行为。
- 追加注释一行说明「114 追加：审查 stage 期间状态为 `ai_reviewing`」，与 113 的注释体例一致。

**避免：** 用 `BlueprintStatus.AI_REVIEWING`（模块级拿不到枚举）；顺手「整理」既有两行；改 `max_steps=20`；在本文件加新函数（新逻辑一律进 `blueprint_review.py`）。

---

### 10. pytest：机械规则逐条证伪 + stage 端到端 + 端点权限

**Analog A（纯函数逐条证伪，最规范）:** `server/tests/services/process_runtime/test_blueprint_reconcile.py`（332 行）

```1:21:server/tests/services/process_runtime/test_blueprint_reconcile.py
"""跨仓 API 对账纯函数测试（Phase 113-05，FLOW-06）。

**零 DB、零 mock**：`reconcile_cross_repo_apis` 是纯函数，所有断言直接喂 dict。

守八件事：

1. **consumed 无 provider** → `gaps` 命中且 `reason == "no_provider"`。
2. **needs_support 缺 support_repository_id** → `missing_support_repos` 非空。
3. **support_repository_id 不在 repo_associations** → 同样进 `missing_support_repos`
   （缺协作仓的两种形态都被捕获）。
4. ⭐ **顶层 availability 不被识别（B4 防回归）**：只写顶层同名键的那条**不进**
   `missing_support_repos`，把同样语义写进 `data_source` 的那条**进**——两条并列，
   杜绝「路径写错还看起来通过」。
5. **字段不一致**：`method` / `request_schema` / `response_schema` 各一例，
   `conflicts` 带 `provider_value` / `consumer_value` 双值。
6. **完全闭环**：逐字段一致 → 三键全空。
7. **绝不抛**：`None` / `{}` / 类型错乱 → 恒定三键空 dict。
8. **口径一致性**：同一组 provided/consumed 喂 `build_api_waves` 与
   `reconcile_cross_repo_apis`，「有 provider」的结论一致（防两套匹配规则漂移）。
"""
```

- **模块 docstring「守 N 件事」编号清单**，每条把**可证伪断言直接写进条目**（不是「测了对账」而是「`reason == "no_provider"`」）。
- **首行声明测试形态**（「零 DB、零 mock，直接喂 dict」）——纯函数测试**不加 `django_db`**。
- **正/负向成对并列**（第 4 条：写错路径的**不**命中、写对路径的命中）——「杜绝路径写错还看起来通过」。
- **模块级期望常量**（`_EMPTY = {"gaps": [], "conflicts": [], "missing_support_repos": []}`，`:31`）。
- **跨模块口径一致性断言**（第 8 条）：两个独立实现喂同一输入，断言结论一致。

**Analog B（端点权限 + 端到端，最规范）:** `server/tests/delivery/test_blueprint_gate_api.py`（1102 行）

```1:23:server/tests/delivery/test_blueprint_gate_api.py
"""确认门八端点 REST 测试（Phase 112-05 Task 2/3，FLOW-03 / FLOW-04 / CHARTER-03 / SC-4）。

守的是**契约与闭环**：

1. 鉴权：八端点未认证一律拒（``IsAuthenticated``，T-112-22）。
2. 只读快照：无门 404；有门 200 且每仓含 role / responsibility / fitness / routing_evidence。
3. ``confirm``：200 且重读蓝图最新版本 ``confirmed_at_gate is True`` / ``decided_by == "human"``；
   请求用户进 ``BlueprintReviewer``；存在未决阻塞澄清线程 → 409。
4. 五动作状态码分层：非法 role 400、仓不在快照 404、缺 ``repository_id`` 400。
5. **续驱接线**（本文件前半把续驱桩掉）：六个改状态端点各 ``await_count == 1`` 且入参
   session 是该 artifact 的会话；``GET`` 与 ``rejected-to-boundary`` 为 0。
6. **失败隔离**：续驱抛异常 → 六端点仍 2xx 且动作结果已持久化（不回滚、不回 5xx）。
...
9. 视图零 ORM 写：源码扫描断言。
10. **SC-4 端到端证伪线（真实入口，不桩续驱）**：经 REST ``add-repo`` → ...
    ``confirm`` 推进到阶段 2/3 ... 且**绝不静默落 FAILED**。
"""
```

- **鉴权是第 1 条**（未认证一律拒）；**状态码分层逐条列**（400/404/409 各一例）。
- **断言从 DB 重读，不信响应体**（「重读蓝图最新版本 `confirmed_at_gate is True`」）。
- **续驱接线正反都测**：该接的 `await_count == 1`、不该接的为 0；**失败隔离**单独一条（续驱抛异常 → 仍 2xx 且已持久化）。
- **视图零 ORM 写用源码扫描断言**（第 9 条）。
- **端到端证伪线不桩依赖**（第 10 条，「真实入口」），且断言「**绝不静默落 FAILED**」。

（stage 端到端的编号清单体例参见 `test_blueprint_merge_stage.py:1-40`「守十四件事」，其第 1/7/11/12 条示范了「确定性投影逐字段相等」「单段失败降级可证伪」「幂等落版本」「schema 不过不落版本」四种断言写法。`pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]` —— ⚠️ async service 跨线程写库必须 `transaction=True`。）

**沿用（本相位测试组织）：**

| 文件 | 守护点（写进 docstring 编号清单） |
|---|---|
| `tests/services/process_runtime/test_blueprint_review_rules.py`（纯函数，零 DB） | 六类规则**各一条证伪样例**（缺引用 / 角色不一致 / API 断链 / 超期排期 / 越确认门 / 违章程）；⭐ **空蓝图 → 六条全部 skip 或 BLOCKER，绝不 pass**（P1）；⭐ **缺 `schema_version` 的 content 不得靠 `validate_blueprint` 假通过**（`:809-810` 防回归，正反并列）；`direction` 枚举是 `provided` 不是 `produced`（防回归）；`deferred_ideas` 段不触发 out_of_scope 误报；章程缺失的仓规则⑥**跳过而非 BLOCKER**；恒不抛（`None`/`{}`/类型错乱 → `[]`） |
| `tests/services/process_runtime/test_blueprint_review_stage.py`（`transaction=True` + `asyncio`） | `_h_bp_ai_review` 四类（deps 未注入 → `needs_clarification` / deps 整体 None / 正常落 `stage_state["ai_review"]` + emit / 依赖异常经 engine 兜底落 failed 且 `error["stage"]` 正确）；⭐ **持续 BLOCKER → 2 轮后 `review_exhausted` + 状态 `pending_review` + `unresolved` 非空 + 会话不是 FAILED**（specifics 第 2 条）；⭐ **`stage_state["ai_review"]` 与 `merge` 桶互不覆盖**（P2）；仅 WARNING/INFO → `review_passed` 不打回；`needs_clarification` 前已 ensure 阻塞线程 |
| `tests/delivery/test_blueprint_review_threads.py` | ⭐ **`record_answer` 不被用于 finding 留痕**（行为断言：`append_note` 后线程仍 `open`；辅以源码扫描 `blueprint_review.py` 零 `record_answer`）；⭐ **`blocking == (severity=="blocker")` 不变式**；`severity` 落库正确且既有 112/113 调用行为不变（默认 `""`）；去重幂等（同 `(rule_id, block_id)` 第二轮不新开线程）；批量重锚定后 `section_path` 已刷新、失锚线程不删 |
| `tests/delivery/test_blueprint_review_views.py` | 五端点未认证一律拒（第 1 条）；approve 有未决 BLOCKER → 409、清空后 200 且 DB 重读状态 `confirmed`；reject → 版本 +1 且 `meta.revision_round` +1 且状态 `drafting`（**先版本后状态**）；⭐ **人工编辑不合法 content → 拒绝且版本数不变**；⭐ **同 content_hash 重复回灌 → 不翻版本**；编辑者进 `BlueprintReviewer`；视图零 ORM 写源码扫描；续驱接线正反 + 失败隔离 |
| 回归（不新建文件） | `test_blueprint_status_stage_map` 七条参数化断言仍绿；`test_stage_status_table_matches_enum` 自动覆盖新行；`test_blueprint_process_graph.py` 的 deps 名单等价性 |

**避免：** class 风格 `TestCase`；patch 模块级全局而非注入 `engine.deps`（`SimpleNamespace(review=AsyncMock())`）；只断言内存对象不重读 DB；漏「依赖异常 → failed」与「LLM 返 None → 保守降级」两条负向路径；async service 测试忘加 `transaction=True`；断言覆盖率/finding 的具体数值而非机制（应断言「BLOCKER 条数 ≥ 1 且 rule_id 命中」而非「恰好 3 条」）。

---

## Shared Patterns（跨文件通用）

### best-effort 不反噬业务
**Source:** `blueprint_reconcile.py:113-115`、`blueprint_ambiguity_score.py:449-457`、`blueprint_merge.py:1975-1983`、`builtin_processes.py:560-570`、`blueprint_resume.py:85-90`
LLM / 事件 / 埋点 / 开线程 / 章程读取一律 `except Exception` 吞掉 + `logger.warning`（异常文本先 `redact_secrets_in_text` 再截断）+ 返回降级值。纯函数返回**已积累的结果**而非空结果。**唯一例外**：人审 / 编辑端点的权限校验是 fail-closed 拒绝（安全边界不降级）。

### structlog 三事件 + 分类
**Source:** `blueprint_ambiguity_score.py:382-390 / :436-447`、`blueprint_spec_gate.py:328-340`、`blueprint_merge.py:1770-1781`
`xxx_started / xxx_completed / xxx_failed`，固定五件套：事件名 snake_case + `category` + `component="process_runtime"` + `initiated_by_user_id=... or "system"` + `duration_ms=round((time.monotonic() - started) * 1000, 2)`。
**本相位分类口径（CONTEXT 锁定）**：审查生命周期 `blueprint_review_started/completed/failed` = `category="caller"`；打回 / 超界 / 人审通过驳回 = `caller` + 绑定 `initiated_by_user_id`；**机械规则逐条判定 = `sampling`**（六类 × N 条目，高频，禁 INFO 刷屏）；LLM 单调用 = `sampling`。
⚠️ **findings 正文绝不进 payload**，只进计数与分级分布（`blocker_count` / `warning_count` / `info_count`）。

### INV-6 单一写入
**Source:** `blueprint_thread.py:11-13`、`blueprint_lifecycle_service.py:340-345`、`blueprint_confirm_gate.py:9`、`blueprint_gate_views.py:15-19`
adapter / handler / view **零 ORM 写**，全部委托 `BlueprintLifecycleService` / `ArtifactService`。模块 docstring 显式声明这条，配 `test_blueprint_inv6_guard` 源码扫描守护。**`append_note` 必须是从既有私有方法提炼的公开方法，不是新的旁路写表路径。**

### 脱敏不可绕过
**Source:** `blueprint_schema.py:760-775`（`_MAX_ERROR_CHARS = 500` + `_format_error` + 脱敏失败也不抛）、`blueprint_ambiguity_score.py:455`、`blueprint_confirm_gate.py:595`
`validate_blueprint` 的报错**已脱敏截断**，finding 正文可直接引用；任何入日志的异常文本走 `redact_secrets_in_text(str(exc))`；蓝图正文是**半可信**输入（可能夹带凭证样本），回显给端点前必须过同一出口。

### async ORM 防裸 lazy-FK
**Source:** `blueprint_lifecycle_service.py`（`@sync_to_async` 私有 `_*_sync` 方法 + `transaction.atomic`）、`blueprint_confirm_gate.py:549`（`_aload_latest_version`）
用标量 id / `.values()` / `.aexists()` / `.afirst()`；必须取 FK 对象时经 `@sync_to_async` 私有方法；事务型多写全在一个 `@sync_to_async` + `transaction.atomic()` 内。`.update()` **绕过 `auto_now`** → 必须显式带 `updated_at=timezone.now()`（`:243-244`）。

### 受限文件的纯追加纪律
**Source:** `builtin_processes.py:445-451`（中段 `import ... # noqa: E402`）、112-05 的 `__all__ += [...]` 范式
既有 import 块一字不动、新 import 走模块中段 + `# noqa: E402`；`__all__` 用 `+=` 追加；受限文件只跑 `ruff check`，**不跑 `ruff format`**；验收 `git diff <file> | rg "^-[^-]"` 为空。

---

## No Analog Found

| 内容 | 说明 |
|---|---|
| **`append_note` 的公开方法本体** | 现有唯一通道是私有 `_append_thread_message_sync`（`blueprint_lifecycle_service.py:1055-1064`，`author_type` **硬编码 `HUMAN`**），且只被 `_arecord_gate_note`（`:1043-1053`）一个调用方使用。本相位需**提炼**为 `append_note(thread, *, body, author=None, author_type=ThreadAuthorType.AI)` 并把 `_arecord_gate_note` 改为调它。形态照 `resolve_thread`（`:456`）的「公开 async 方法 = 校验 + 委托 `@sync_to_async` 事务 + 结构化日志三段」；**绝不新增第二条写表路径**。 |
| **线程 anchor 的批量重锚定** | `blueprint_anchor.reanchor` 是单条纯函数（111 交付 + 单测），**批量应用到线程行零先例**（`blueprint_anchor.py:9-10` docstring 明写「调用方在 Phase 114」）。须新增 `BlueprintLifecycleService.areanchor_threads(...)`：`diff_blueprint_blocks` 预筛变动块 → 只对受影响线程调 `reanchor` → 刷新 `section_path` → `bulk_update(["anchor", "anchor_status"])`。 |
| **`blueprint_quality` 三项 DB 统计接口的实装** | `ai_rejection_rate`（`:111`）/ `human_edit_volume`（`:122`）/ `clarification_rounds`（`:132`）当前都 `return None`，**本相位首次有真实数据**。⚠️ **A2 已知偏差**：`human_edit_volume` 的 docstring 口径写 `created_by_user_id`，但 `ArtifactVersion` **无该字段**（`add_version` 只写 `produced_by_session_id` / `produced_by_ref`，`artifact_service.py:151-159`）→ 实装必须改用 `produced_by_ref__startswith="human_edit:"`，并在 PLAN 里登记为「口径 docstring 同步修正」。保持**同步签名**不变（`evaluate_blueprint_golden` 离线评估在调），内部懒 import ORM（`:11` 顶层零 ORM import 的纪律），由调用方决定是否 `sync_to_async` 包裹。无数据时**继续返回 `None` 而不是 0**（否则 golden 评估会把「没数据」当「零打回」）。 |
| **pending 超时提醒** | 无定时任务先例可抄且**不新起 OS 级注册**（RESEARCH Runtime State Inventory）。提醒周期走 `SystemSetting`（§12 已定），挂载点建议在续驱路径（`blueprint_resume`）上顺带检查，与 113 的「超时清理挂在 barrier 续驱路径上、不新起定时任务」同源。**不自动作答、不判失败**；提醒对象 = `BlueprintReviewer` 名单 + 发起人。 |

---

## Metadata

**Analog search scope:** `server/services/process_runtime/`（`blueprint_*` 全套 17 个模块 + `builtin_processes.py` + `engine.py`）、`server/delivery/{models,services,api}/`、`server/repositories/models.py`、`server/tests/{delivery,services/process_runtime}/`
**Files scanned:** 约 30 个候选路径，精读 11 个 analog 文件/定向切片（`blueprint_merge.py` / `builtin_processes.py` / `blueprint_spec_gate.py` / `blueprint_confirm_gate.py` / `blueprint_gate_views.py` 均为**非重叠**定向切片）
**上游输入:** `114-CONTEXT.md`、`114-RESEARCH.md`（§1–§6 的行号已实读核对）、`113-PATTERNS.md`
**Pattern extraction date:** 2026-07-30
**Valid until:** 111/112/113 模块在 rebase 中改动即需重核行号
