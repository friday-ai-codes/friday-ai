---
phase: 116-entry
status: findings
reviewed: 2026-08-01
findings_total: 9
critical: 0
major: 3
minor: 6
depth: deep
---

# Phase 116 Code Review — 四入口收编 + 蓝图 intake / 图谱 / 导出 / MCP 澄清 / 源码正文读面

**审查基线：** `0e208ba9` → `HEAD`（`milestone/v0.20.0-blueprint` worktree，分支实测 `milestone/v0.20.0-blueprint`）
**审查范围：** `git diff 0e208ba9..HEAD -- server/ web/` 的 81 个文件，**+12640 / −378**；`.planning` 文档不审
**深度：** deep（跨模块调用链：入口开关 → 分派器 → 八个续驱点 → intake → stage handler → 图谱 normalizer → 渲染器 → 两个导出端点 / 两个 MCP 工具 / 一个源码读面 → 前端消费方；七份 SUMMARY 的自述契约逐条与代码对账）
**立场：** 对抗性复核。七份 SUMMARY 已用**实跑变异**背书了 12 条自述失效模式（错工厂、错 driver、漏 tier 实参、水印白名单、项目边 ensure、finding 分流、双路径复判、三态同形……），本轮逐条复验后**不复算它们**（结论见文末「复核过、确认干净的面」）。主打的是 **SUMMARY 没有覆盖的那一类：一条链上每个文件各自都对，但两端没接上 / 派生数据的坐标系是错的**。

**结论：0 CRITICAL / 3 MAJOR / 6 MINOR。** 授权面（八个 gate 端点 + 两个导出端点 + 两个 MCP 工具 + `file-lines`）、`file-lines` 的三态同形与 fail-closed、水印的结构性不可关闭、开关四键默认、冻结纪律、脱敏守卫**全部干净**（见文末两节）。

三条 MAJOR 里 **一条经真实代码路径实测复现**（探针已删除，`git status --short` 空输出）：

| # | 实测结果 |
|---|---|
| MJ-01 | 造两个真实形态的 chunk（`_split_large` 默认 `overlap_lines=5` 产出的 100..150 / 146..196 两片），请求 148..155 → 实测返回 `[{148,"L148"},{149,"L149"},{150,"L150"},{151,"L146"},{152,"L147"},{153,"L148"},{154,"L149"},{155,"L150"}]` —— **后三行的行号与正文对不上，且 L148/L149/L150 被重复渲染两次**。另一形态（chunk 有空洞 1..5 与 40..44，请求 3..42）实测返回 8 行、行号 `3..10`，即**第 40–44 行的源码被贴上了第 6–10 行的号** |

另两条 MAJOR 是**「写了但没人读」的断链**，各自由一次全仓 `rg`（剔 tests）确证零生产消费方。

---

## MAJOR

### MJ-01：`file-lines` 走索引回退时，行号是「从首个 chunk 的 start_line 连续数下去」推出来的 —— chunk 一重叠或有空洞，前端就把**别的行的源码**贴上被引行的行号并高亮

**文件：** `server/services/repo_file_read.py:415-445`（索引回退段：`texts` 拼接 → `base_line_no` → `_number_lines`）、`:111-131`（`_number_lines` 的连续编号与区间过滤）；消费方 `web/src/components/blueprint/citation/CitationCodePreview.vue:200-202`（`row.line_no` 逐字渲染 + `isCited(row.line_no)` 高亮）

**问题：**

索引回退路径把选中 chunk 的 `content` **首尾相接**拼成一个平坦的行数组，然后假定它是从第一个 chunk 的 `start_line` 开始的**连续区间**：

```415:434:server/services/repo_file_read.py
    chunks_raw.sort(key=lambda chunk: chunk.get("chunk_index", 0))
    selected_chunks: list[dict[str, Any]] = []
    ...
    texts: list[str] = []
    for chunk in selected_chunks:
        ...
        texts.extend(str(chunk.get("content") or "").splitlines())
    truncated = len(texts) > limit
    returned_texts = texts[:limit]
    base_line_no = int(selected_chunks[0].get("start_line") or 0) or 1 if selected_chunks else 1
```

`_number_lines` 随后 `line_no = base_line_no + offset` 逐行加一。**这个假定对本仓的 chunker 不成立**，两条独立证据：

1. **重叠是默认行为。** `services/symbol_chunker.py:81-100` 的 `build_chunks_from_spans(..., overlap_lines: int = 5)`，`_split_large:277` 每切一片就 `i = max(j - overlap_lines, i + 1)` 回退 —— 大符号的相邻子 chunk **默认重叠 5 行**，`_module_chunks` 同样吃这个参数。
2. **空洞可达。** 顶层归一只丢弃**完全嵌套**的 span（`:126-130`），部分重叠的 span 两条都留；`_merge_small_adjacent:182-205` 允许 `gap <= 2` 的合并组，合并后 `start_line`/`end_line` 取组的首尾，而 `covered` 是按合并后的区间算的（`:149-151`）⇒ 组内空隙不会再被 `_module_chunks` 补回来。

**实测复现**（探针：patch 掉镜像与匹配器，喂两个真实形态的 chunk）：

```
# 形态 A：一个大符号被 overlap_lines=5 切成 100..150 与 146..196，请求 148..155
[{"line_no":148,"text":"L148"},{"line_no":149,"text":"L149"},{"line_no":150,"text":"L150"},
 {"line_no":151,"text":"L146"},{"line_no":152,"text":"L147"},{"line_no":153,"text":"L148"},
 {"line_no":154,"text":"L149"},{"line_no":155,"text":"L150"}]
# 形态 B：chunk 1..5 与 40..44 之间有空洞，请求 3..42
[{"line_no":3,"text":"G3"},{"line_no":4,"text":"G4"},{"line_no":5,"text":"G5"},
 {"line_no":6,"text":"G40"},{"line_no":7,"text":"G41"},{"line_no":8,"text":"G42"},
 {"line_no":9,"text":"G43"},{"line_no":10,"text":"G44"}]   status="ok" truncated=false
```

**为什么这是本相位引入的、而不是下沉带来的回退**：下沉前 `GetRepositoryFileView` 只回一个 `content` 字符串（`0e208ba9:server/mcp_tools/views.py:1119-1135`），拼接口径完全一样但**从不派生行号**，误差不可见。116-07 在同一段拼接结果上新造了 `lines[].line_no` 这份**派生数据**，并让前端**逐字**渲染它：

```200:202:web/src/components/blueprint/citation/CitationCodePreview.vue
            :class="isCited(row.line_no) ? 'bg-primary/10' : ''"
            :data-citation-highlight="isCited(row.line_no) ? 'true' : 'false'"
            :data-line-no="row.line_no"
```

⇒ 用户看到的是「第 151 行」旁边写着第 146 行的代码，而 `isCited` 用同一个错号判高亮 —— 高亮框**框住的不是被引用的那几行**。这比「读不出来」糟：读不出来会落 quote 快照（用户知道这是快照），读错会被当成当前源码。116-07 的用例 5/8/9 全部走**镜像路径**（行号本就精确，`slice_start+1` 是恒等映射），索引回退路径的行号从未被断言过。

⚠️ 还有一个同源的次生形态：`returned_texts = texts[:limit]` 的**截断发生在区间过滤之前**（`:432-433` 早于 `_number_lines` 的 `line_start/line_end` 过滤）。当选中 chunk 的正文行数超过 `_MAX_LINES=400` 而被引区间落在后半段时，过滤后 `lines` 为空、`status` 仍是 `"ok"` ⇒ 前端 `usable=false` 落快照。这一档不产生错误内容，但会让「明明能读到」表现成「读不到」。

**建议修法（两步，缺一不可）：**

① **行号必须来自 chunk 自身的 `start_line`，⛔ 不许跨 chunk 连续数。** 把「拼行 + 编号」改成逐 chunk 编号后合并，重叠行按 `line_no` 去重（后写覆盖或先写保留都行，但要显式）：

```python
numbered: dict[int, str] = {}
for chunk in selected_chunks:
    start = int(chunk.get("start_line") or 0) or 1
    for offset, text in enumerate(str(chunk.get("content") or "").splitlines()):
        numbered.setdefault(start + offset, text)
rows = [{"line_no": n, "text": numbered[n]} for n in sorted(numbered)]
```

② **先按区间过滤、再按 `limit` 截断**（顺序反过来），`truncated` 据过滤**之后**的条数判定。

⚠️ MCP 面的 `content` 键必须**保持现有拼接口径**（`"\n".join` 原样），否则 `get_repository_file` 的对外契约漂移 —— 两份产出可以共存：`content` 走旧拼接，`lines` 走新编号。

补三条断言：① 形态 A（重叠）⇒ 每个 `line_no` 只出现一次且 `text == f"L{line_no}"`；② 形态 B（空洞）⇒ 返回的 `line_no` 集合恰为 `{40,41,42}`（⛔ 不含 3..5 被错号的那批）；③ **非恒真对照**：单 chunk 覆盖整个区间时结果与修改前逐字相同（证明新实现没把镜像路径那条也改坏）。

---

### MJ-02：assumptions 三档在生产里**没有任何写入方** —— `stage_state.decomposition.assumptions_tier` 永远不存在，档位恒为默认、`SettingKeys.BLUEPRINT_ASSUMPTIONS_TIERS` 是一个读不到的配置键

**文件：** `server/services/process_runtime/blueprint_spec_gate.py:89`（`_TIER_STATE_KEY`）、`:143`（`tier = self._assumptions_tier(session)`）、`:670-681`（读取实现）；`server/services/process_runtime/blueprint_ambiguity_score.py:379-382`（`if str(tier or ""):` 才叠加覆盖）；写入方：`server/services/process_runtime/entrypoint.py:374-387`（`start_blueprint_orchestration` 装配 `decomposition` 的全部键）

**问题：**

档位的**唯一读取口**是会话 `stage_state` 里的一个键：

```670:681:server/services/process_runtime/blueprint_spec_gate.py
    def _assumptions_tier(self, session: Any) -> str:
        """本次会话生效的 assumptions 档位（116-06）；非三档之一一律回 ``""``（默认档）。
        落点是 ``stage_state["decomposition"]["assumptions_tier"]`` —— 入口建会话时写进
        ``decomposition`` …"""
        state = getattr(session, "stage_state", None)
        bucket = (state or {}).get("decomposition") if isinstance(state, dict) else None
        tier = (...)
        return tier if tier in ASSUMPTIONS_TIERS else ""
```

docstring 说「入口建会话时写进 `decomposition`」。**没有任何入口写它。** `start_blueprint_orchestration` 装配的 `decomposition` 是一个闭集：`requirement_text` / `include_repos` / `project_id`，加上四个 `if` 才写的 `extra_evidence` / `mode` / `feature_segments` / `feature_meta`（`entrypoint.py:374-387`）—— 没有 `assumptions_tier`，四个入口也都不传。

全仓核算（剔 `tests/`）：

```
$ rg -n "assumptions_tier" --glob '*.py' | rg -v '^tests/'
blueprint_spec_gate.py:89,143,198,670,673,738      ← 读 + 留痕
blueprint_ambiguity_score.py:295,310,563           ← 日志字段
system/models.py:212                               ← 键名声明
```

**零写入点。** 唯一写它的是测试夹具 `tests/services/process_runtime/test_blueprint_assumptions_tiers.py:121`（`stage_state["decomposition"] = {"assumptions_tier": tier}`）—— 29 条用例全绿，但它们证明的是「**如果**有人把这个键写进去，档位会生效」，而生产里没有那个「如果」。

后果是三连的静默无效：

1. `_assumptions_tier(session)` 恒返 `""`；
2. `aload_spec_gate_config(tier="")` 的 `if str(tier or ""):` 恒假 ⇒ `_aload_tier_overrides` **永不被调用**；
3. ⇒ `SettingKeys.BLUEPRINT_ASSUMPTIONS_TIERS` 这个键**读它的代码路径不可达**：运维照 `system/models.py:207-212` 的注释去配 `{"assume_more": {...}}`，改完什么都不会发生，也不会有任何日志说「档位没生效」（`blueprint_assumptions_tier_unknown` 只在 `tier` 非空且不在三档内才发）。

这条与 116-06 SUMMARY 的 GATE-01 自评「✅ **assumptions 档位真的可运行时调**」直接矛盾 —— 可调的只有「三档各自的参数值」，**选哪一档无从表达**。`_MAX_SPEC_GATE_ROUNDS` 已经被删掉换成 `config["max_rounds"]`，所以轮数上界现在只能靠 `spec_gate.config.max_rounds` 调（那条是通的），但**档位维度整个是死的**。

**建议修法：** 补上缺的那一半 —— 档位需要一个「选哪一档」的入口。两种形态择一，⛔ 不要两个都做：

- **(a) 全局设置键**（最小改动，与 `blueprint.entry.switch` 同款）：`_assumptions_tier` 读不到会话级覆盖时，回落读一个 `blueprint.assumptions_tier`（单数）设置键。这样「运行时可调」一句话成立，且回滚仍是改一个设置值。
- **(b) 入口级形参**：`start_blueprint_orchestration(..., assumptions_tier: str = "")` 并在 `decomposition` 里「非空才写键」（与既有四个 `if` 同款），四个入口按需传。表达力更强（不同入口可用不同档），代价是四个入口都要接线。

⚠️ 无论哪种，都要补一条**会话级留痕**：档位已经进了 `ambiguity_report`（`_ambiguity_report:738`），但那要等第一次打分之后才有 —— 建会话时就该能看出这条会话用的是哪一档。

补两条断言：① 不做任何配置时 `_assumptions_tier` 返 `""` 且 `_aload_tier_overrides` **零调用**（这条现在就该绿，是现状的锁）；② 按新入口设成 `assume_more` 之后，`spec_gate` 实际用的 `threshold` 是 `0.45`（⛔ 断言 `config` 的取值，不要只断言 `stage_state` 里那个字符串 —— 那正是这次漏掉的那一环）。

---

### MJ-03：`DelegateResult.error_detail` 写了没人读 —— MCP 入口「推不出 `meta.project_id` ⇒ 如实回错」到调用方那里变成了「编排未产出 canonical 方案」+ `retryable: True`，中性文案被丢弃

**文件：** `server/mcp_tools/orchestration_delegate.py:296-306`（构造 `error_detail=exc.detail`）；应当消费它的 `server/mcp_tools/technical_plan_service.py:474-478`（`delegate.status == "failed"` 分支）与 `:544-560`（`output` 装配）

**问题：**

116-03 把中性 detail 一路送到了 delegate 边界：

```296:306:server/mcp_tools/orchestration_delegate.py
    except BlueprintIntakeRejected as exc:
        # ⭐ 推不出 meta.project_id ⇒ **拒绝发起**（此刻 ⛔ 会话与 artifact 都尚未建立）。
        ...
        result = DelegateResult(
            session=SimpleNamespace(id=""),
            status="failed",
            ...
            error_detail=exc.detail,
        )
```

116-03 SUMMARY 的「跨相位交接登记 ①」把消费方明确交给了 116-06，三条：① 补 `work_item_context=`；② 追加三键 + `status=partial`；③ **「把 `DelegateResult.error_detail` 接进失败响应体」**。①② 做了（`technical_plan_service.py:426` / `:463-468`），**③ 没做**。

全仓核算（剔 `tests/`）：`rg -n "error_detail" --glob '*.py'` 在 `mcp_tools/` 下只有 `orchestration_delegate.py` 自己的定义（`:49` docstring / `:60` 字段 / `:305` 赋值）。唯一的读取方是 116-03 自己的用例 `tests/services/process_runtime/test_entry_dispatch_wiring.py:495` —— **零生产消费方**。

于是 mcp 开关切到蓝图、而工作项所属 Space 下没有 Project 时，`create_feishu_technical_plan` 的调用方看到的是：

```474:478:server/mcp_tools/technical_plan_service.py
    elif delegate.status == "failed":
        retry_state.update({"retryable": True, "failed_stage": "orchestration"})
        error_stage = "orchestration"
        error = "编排未产出 canonical 方案"
```

三处都不对：

- **`error` 这句话是错的原因**（真实原因是「这个需求推不出所属项目」），而且它**只落 `McpWorkItemTechnicalPlan` 行**（`:533-534`），`output` 里根本没有 `error` 键（`:544-560`）⇒ agent 拿到的响应**一个字的解释都没有**；
- **`retryable: True` 是错的建议**：这是**确定性**失败（Space→Project 换算不出来），重试一百次结果一样。116-05/06 反复强调的「配置类失败重试也不会好 ⇒ 400」在这里被反过来了；
- `session_id` 是空串（`str(SimpleNamespace(id="").id)`），调用方也无从续推。

⇒ 116-03 精心保住的「⛔ 不含内部路径/异常原文的中性 detail」在最后一跳被丢掉，`BlueprintIntakeRejected` 的可回显价值等于零。

**建议修法：** 在 `technical_plan_service` 的 failed 分支里区分「拒绝发起」与「编排跑了但没产出」：

```python
    elif delegate.status == "failed":
        rejected = bool(getattr(delegate, "error_detail", ""))
        retry_state.update({
            "retryable": not rejected,          # 拒绝发起是确定性失败，⛔ 不诱导重试
            "failed_stage": "blueprint_intake" if rejected else "orchestration",
        })
        error_stage = retry_state["failed_stage"]
        error = delegate.error_detail or "编排未产出 canonical 方案"
```

并把 `error` / `error_stage` **加进 `output`**（当前只落库、不回传）—— ⛔ 只改 `retry_state` 不够：agent 读的是响应体。⚠️ 追加响应键要同步 `tests/mcp_tools/test_schema_snapshot.py` 的字面量副本（116-06 已踩过这个坑并登记）。

补两条断言：① mcp 开关开 + 工作项 Space 无 Project ⇒ 响应体含中性 detail 逐字、且 `retry_state["retryable"] is False`；② **非恒真对照**：编排真的跑了但没产出 canonical（`delegate.error_detail == ""`）⇒ `retryable` 仍为 `True`、文案仍是既有那句（证明没把两类失败一锅端）。

---

## MINOR

### MN-01：入图实体的 `title` 是全链**唯一没过脱敏**的半可信文本，而它就是搜索结果里显示的那一行

**文件：** `server/knowledge/sources/blueprint.py:395`

`content` 过了（`:354` `redact_secrets_in_text(_content_text(content))`），`payload` 只有标量与计数，日志只记 id 与计数 —— 唯独 title 直通：

```395:395:server/knowledge/sources/blueprint.py
        title=str(meta.get("title") or artifact.title or "未命名技术蓝图")[:500],
```

`meta.title` 的生产来源是 `blueprint_intake.aseed_blueprint_artifact:359`：缺省取**需求原文的首行**（`_first_line(goal_text)`）。用户把一段带 `sk-ant-…` / `Bearer …` 的排障上下文粘成需求首行，这串就原样进 `KnowledgeEntity.title`，并出现在知识库搜索结果与「关联知识」列表里。对照组：同一份 title 在 MCP 侧是过了脱敏的（`mcp_tools/views.py:4604` `redact_secrets_in_text(str(meta.get("title") or ""))[:500]`）—— 两个消费面口径不一致，说明这不是有意豁免。

**建议修法：** `title=redact_secrets_in_text(str(...))[:500]`，与同文件 `content` 那行同款。⛔ 不必改 `artifact.title`（那是 delivery 侧的既有面，不在本相位边界内）。

---

### MN-02：蓝图入图的后台任务没带发起用户，图谱侧全链日志归因到 `system`

**文件：** `server/delivery/services/artifact_service.py:68`（两个调用点 `:107-109` / `:165-167` 共用）

```68:68:server/delivery/services/artifact_service.py
    await aschedule_ingestion(IngestionRequest("blueprint", str(artifact_id), trigger))
```

`aschedule_ingestion` 的第二个 keyword-only 形参 `initiated_by_user_id` 专门用来让 worker `bind_task_context` 重绑发起用户（`knowledge/ingestion.py:118-140` 的 docstring 逐字写明这是 CTX-02）。仓内已有五个调用点在传它（`mcp_tools/views.py:1855` / `:2107`、`work_item_execution_service.py:276` / `:684`、`learning_case_extraction.py:333`）。蓝图这两处**都没传**，而两处**都拿得到**触发用户：`create` 的形参里就有 `created_by_user_id`，`add_version` 的调用链上有 `produced_by_session_id` → 会话的 `initiated_by_user_id`。

⇒ 「谁触发了这次入图」在图谱侧不可回答，正是 `.cursor/rules/observability-logging.mdc`「后台任务**必须**显式携带 `initiated_by_user_id`」那一条。风险低（不影响业务），但这是本相位新增的后台任务面，现在补成本最低。

**建议修法：** `_amaybe_schedule_blueprint_ingestion(..., initiated_by_user_id: str = "")` 纯追加形参，`create` 传 `created_by_user_id`、`add_version` 传 `produced_by_session_id` 对应会话的发起人（取不到记 `"system"`）。

---

### MN-03：`blueprint_notify` 有五条**完全静默**的早退 —— 卡片没发出去时，日志里连一条记录都没有

**文件：** `server/services/process_runtime/blueprint_notify.py:161-162`（无题）、`:171-172`（推不出 project）、`:174-175`（无 space）、`:178-179`（无收件人）、`:190-191`（建群失败）

五条 `return` 全部裸退，只有**抛异常**那条路径才有 `blueprint_clarification_card_failed`（`:217-227`）。而这五条恰恰是生产上最可能命中的：项目没建飞书群、`BlueprintReviewer` 名单为空且会话 `created_by` 为空、`resolve_or_create_group` 返回空 chat_id ……

后果是 CLAR-04 的用户可感知价值「静默地兑现不了」：用户没收到卡片，运维在日志里既看不到 `blueprint_clarification_card_sent`，也看不到任何失败记录 —— 只能靠「没有 sent 事件」反推，而那与「本来就没开澄清」同形。本模块的 docstring 自己把「每一步取不到就 return 的早退形态」当成设计，但**早退不等于不留痕**。

**建议修法：** 五条早退各带一条 `sampling` 事件，共用一个 `reason` 枚举（`no_questions` / `no_project` / `no_space` / `no_recipients` / `no_chat_id`）：

```python
def _skip(reason: str, **kv) -> None:
    logger.info("blueprint_clarification_card_skipped", category="sampling",
                component=_COMPONENT, reason=reason, **kv)
```

⛔ 仍然只记标量（`reason` / `artifact_id` / `session_id` / `question_count`），题面正文不进日志的纪律不变。

---

### MN-04：chat 蓝图会话在调研之后**重新挂起**时，之前注册的 chat blocking task 永远等不到 —— 且这一档连 analog 都有的那条日志都没有

**文件：** `server/subagent/api/callbacks.py:2181`（`_afeedback_chat_blueprint_barrier` 定义）与 `:2220-2226`（非终态守门）；对照 analog `:457-466`（`_schedule_chat_plan_resume` 的 e2 守门）

守门本身是对的（非终态回灌会把 waiter 误解析成失败）：

```2220:2226:server/subagent/api/callbacks.py
        if session.status not in (
            ConvergenceSessionStatus.DONE,
            ConvergenceSessionStatus.FAILED,
        ):
            # 仍在挂起（等澄清 / 等下一批调研）⇒ 不回灌，否则会以 success=False 提前把 chat
            # 阻塞任务误解析为失败（与 _schedule_chat_plan_resume 的 e2 守门同口径）。
            return
```

但**没有第二条出路**：会话此后若由 REST / MCP / 查看器的作答链（`aresume_after_gate_action`）驱到 `DONE`，那条链上没有任何一处调 `_afeedback_chat_blueprint_barrier` —— 两个调用点只有 `_trigger_blueprint_research_barrier:2178` 与 `_trigger_blueprint_repo_plan_barrier:2481`，都挂在**容器回调**上。⇒ 对话里的「深入调研容器运行中…」占位永久停在那里（115-MJ-02 的同一形状）。

这条**与 analog 同构**（旧链的 `_schedule_chat_plan_resume` 在 clarifying 重挂起后同样不回灌），所以不算本相位引入的回退，登记为 MINOR。但有一处**比 analog 弱**：analog 在这一档打了 `chat_plan_resume_resuspended`（`:461-466`），蓝图这条是**裸 `return`** ⇒ 排查时连「它到过这里并决定不回灌」都看不出来。

**建议修法（两步，第一步现在就该做）：** ① 这一档补一条 `sampling` 事件（字段 `session_id` / `status`），与 analog 对齐；② 顺延项：把 `_afeedback_chat_blueprint_barrier` 挂到蓝图会话**每一条**通向终态的路径上（最省的落点是 `blueprint_resume.aresume_after_gate_action` 的收尾，那是全部作答链的共同出口），使「谁把它推到终态」与「谁负责回灌」解耦。⚠️ 该 helper 自带 chat 守门 + 终态守门 + barrier 去重，多挂几处是幂等安全的。

---

### MN-05：引用预览的顶层渲染门是 **`chunk-at` 的 `usable`** —— `chunk-at` 不可用时，即使 `file-lines` 读得到正文也一律落快照

**文件：** `web/src/components/blueprint/citation/CitationCodePreview.vue:165`（`v-else-if="!usable"` → `CitationFallback`）与 `:188`（`v-if="sourceUsable"` 在它内部）

两个数据源的可用性判据是**串联**的：`usable`（`chunk-at`）为假即整块落 `CitationFallback`，`sourceUsable`（`file-lines`）根本没机会参与。可达且不罕见 —— `chunk-at` 依赖 Qdrant 索引命中，而 `file-lines` 的**首选路径是本地 bare 镜像**（`repo_file_read.py:328-372`），一个「镜像有、索引里没有 / 被索引排除」的文件会让 VIEW-02 的核心交付（源码正文 + 行高亮）**完全不出现**，用户看到的仍是 115 时代的 quote 快照。

116-07 SUMMARY §8 把这条登记为「判断调用（非缺陷，登记备查）… 记在此处备里程碑收尾定夺」。本轮复核认为它值得一条 MINOR：它不是实现瑕疵，而是**本 plan 交付的价值在一整类文件上静默不可达**，而症状（落快照）与「这个引用本来就没源码」完全同形。

**建议修法：** 把顶层门从 `!usable` 改成 `!usable && !sourceUsable`，让两个数据源各自独立降级（`chunk-at` 只驱动 chunk 计数徽标那一行）。⚠️ 这会动 115-03 建的渲染门结构，须同步 `citationPreview.spec.ts` 的用例 2c/4（它们断言 `chunk-at` 不可用即整块落快照）—— 改判据时把那两条改成「`chunk-at` 与 `file-lines` **都**不可用才落快照」，并补一条正向：`chunk-at` 空 + `file-lines` 有正文 ⇒ `citation-code-source` 存在。

---

### MN-06：MCP `get_technical_blueprint` 对任意 artifact 都走蓝图渲染器，没有 `schema_version` 判别 —— 拿一个 v0 技术方案的 id 调它，会得到一份「带未经确认水印的空蓝图」

**文件：** `server/mcp_tools/views.py:4562`（`content = await _alatest_content(artifact)`）与 `:4597`（无条件 `render_blueprint_markdown`）、`:4606`（`_blueprint_section_summary`）

仓内另外两个渲染入口都先判别再分派：`delivery/artifacts/builtin_types.py:39-50`（`if content.get("schema_version") == BLUEPRINT_SCHEMA_VERSION` 才走蓝图渲染器，否则回 v0 渲染器）、`delivery/api/artifact_serializers.py:126-139`（同款判别 + `return render_markdown(...)` 兜底）。MCP 这一处**没有**。

`delivery.Artifact` 里同时住着旧链 merge 产出的 v0 `technical_plan` content（`architect_merge_adapter` 仍在生产），拿它的 id 调本工具：`render_blueprint_markdown` 对 v0 content 的每一段都 `.get` 取不到 ⇒ 十段全是 `—`、`# —` 的标题，外加一行 `> ⚠️ 未经确认`；`sections` 六段全 `{count: 0, titles: []}`。agent 拿到的是一份**看起来渲染成功、实则一无所有**的方案，且没有任何字段能让它分辨「这不是蓝图」。

**建议修法：** 在 `_handle` 里加同款判别，非 `blueprint/v1` 走 `error_response("not_found", …)`（与「artifact 不存在」同一句中性文案 —— 该 artifact 对本工具而言确实不存在，且不新增可区分状态）。⛔ 不要回一个 `is_blueprint: false` 之类的新键：那会给出一个「这个 id 存在但不是蓝图」的存在性差分。

补一条断言：v0 content 的 artifact ⇒ 404 且响应体与「artifact 不存在」逐字相同；对照组 v1 ⇒ 200。

---

## 冻结纪律与门禁复核（`git diff --name-only 0e208ba9..HEAD`）

| # | 项 | 结论 |
|---|---|---|
| 1 | `codegraph/services/repo_router_v2.py` | ✓ 零输出 |
| 2 | 六个 legacy `technical_plan` process 文件（`decompose_segments` / `research_adapter` / `architect_merge_adapter` / `merged_plan` / `clarify_adapter` / `render`） | ✓ **逐个零输出** |
| 3 | `delivery/services/event_taxonomy.py`（`ConvergenceSessionEvent` / `BLUEPRINT_EVENTS`） | ✓ 零输出 —— 本相位**未新增任何事件常量**，`len(BLUEPRINT_EVENTS) == 21` 双断言仍成立 |
| 4 | `agents/call_source.py` | ✓ 零输出（decompose 复用已注册的 `BLUEPRINT_DECOMPOSE`，零新增枚举） |
| 5 | MCP 公共 handler 工厂（`knowledge_tools` / `handler_factory`） | ✓ `--name-only \| rg` 零命中 |
| 6 | 四个 0.19 前端组件（`chat/TechPlanCard.vue` / `chat/RoutingDecisionPanel.vue` / `execution/NodeDataTab.vue` / `delivery/ArtifactTimeline.vue`） | ✓ **零输出** |
| 7 | `knowledge/related.py`（`_DEFAULT_RELATIONS`）/ `knowledge/ingestion.py`（`apply_edge_specs`）/ `repositories/chunk_at_views.py` / `services/chunk_lookup.py` | ✓ 全部零输出 |
| 8 | `web/package.json` / `web/pnpm-lock.yaml` / `server/pyproject.toml` | ✓ 零输出（**零新增运行时依赖**） |
| 9 | migration | ✓ `--name-only \| rg migrations` **零命中**，相位内零 migration |
| 10 | 后端门 | ✓ 实跑 `uv run pytest tests/services/process_runtime tests/delivery tests/knowledge tests/repositories tests/mcp_tools tests/agents -q` → **2943 passed / 1 failed / 2 skipped**；唯一失败是既知环境项 `test_skills_snapshot_guard::test_skill_files_discovered`（本 worktree `skills/` 为空目录） |
| 11 | 前端门 | ✓ 实跑 `pnpm exec vitest run` → **1704 passed / 1 skipped（215 文件）**，与 116-07 SUMMARY 登记的数值逐字一致 |
| 12 | 探针清理 | ✓ `git status --short` **空输出**（MJ-01 的探针 `tests/repositories/test_probe_tmp_linenos.py` 已删除） |

⚠️ 一处需登记而非缺陷：`server/mcp_tools/serializers.py` 在 116-06 被改过（追加两个工具的 request/response snapshot 与 `create_feishu_technical_plan` 的三键）。116-07 SUMMARY 把它列为「冻结面 0 行」—— 那是相对 **116-07 自己的 PHASE_BASE** 成立，相对相位基线 `0e208ba9` 是 +62 行纯追加，属 116-06 的声明面，两份记账都对，不构成矛盾。

## 复核过、确认干净的面（不计入 findings）

- **开关默认值（本轮头号靶子）**：`DEFAULT_ENTRY_SWITCH` 四键**全 `technical_plan`**（`blueprint_entry_switch.py:60-65`），且三层 fail-soft 的**每一条回落都是 `PROCESS_TECHNICAL_PLAN`**（未知 entry / 读设置异常 / 外层非 dict / 内层值域外，共 4 个 return 点，逐个核过）。⇒ 不配置、配错、配坏一律走旧链，**没有任何一条路径能让蓝图链意外成为默认**。`_map_terminal`（`plan_research.py:619-625`）确认**函数体一行未改**，上方的同步点 2 边界注释解释了为什么默认不能翻。
- **`entry_key` 字面量纪律**：四个开关调用点（`plan_research.py:304` / `plan_research_tools.py:122` / `orchestration_delegate.py:151` / `technical_plan_service.py:71` / `feature_solution_service.py:265`）与六个 `entry_key=` 实参**全部是字符串字面量**，`rg` 全仓零处写成 `session.entrypoint`；MCP 的 `entrypoint="workflow"` 既有约定一字未改（`orchestration_delegate.py:232`）。116-01 的 ast 扫描此刻覆盖的是真实调用点而不再是空扫描。
- **分派器与八个续驱点**：`build_engine_for_session` 返回 `(engine, driver)`，`rg` 确认全仓生产代码里 `build_orchestration_engine(` 的 `ast.Call` 只剩**两处有意保留**（`plan_deepen_service.py:99` 非蓝图入口、`subagent/api/callbacks.py:447` 对蓝图三重不可达），`adrive_convergence_session_to_pause_or_terminal(` 的直接调用同样只剩这两处。六个改造点里 `plan_clarify_callback.py:262` 虽然丢弃了 driver（`engine, _adrive = …`），但它把驱动委托给 `aanswer_round_and_resume`，后者在 `answer_resume.py:110` **重新分派**并 `engine = engine or dispatched_engine` —— driver 恒用分派出的那个，语义正确。
- **`file-lines` 的存在性防线（本 plan 头号靶子）**：`excluded` / `not_found` / `unavailable` 三态在 View 里共用**唯一一个**构造函数 `_neutral_payload`（`repo_file_views.py:63-71`，`else` 分支只有它一条出口），响应体逐字相同；service 侧 `_neutral()` 是这三态的唯一构造入口且 `content` / `lines` 恒空。`_acheck_excluded` 对 **requested + resolved 双路径**复判，匹配器构造异常一律 `return True`（fail-closed）—— 本轮探针在无 DB 环境下**实测触发了这条**（输出 `repo_file_read_matcher_build_failed` + `exclusion.blocked` 后返 `excluded`），证明 fail-closed 不是恒假分支。源码级守卫 `"HTTP_404" not in src` / `"file_excluded" not in src` 仍在。
- **源码正文与路径不入日志**：`_emit`（`repo_file_read.py:244-269`）与 View 侧埋点（`repo_file_views.py:135-151`）只记 `path_len` / `content_len` / `line_count` / `truncated` 等标量；`log_exclusion_blocked(rel_path=…)` 是 Phase 22 既有审计面且本轮实测输出为 `***REDACTED***`。两个新模块已进 `test_blueprint_log_redaction_guard._SCANNED_MODULES`（116-07 收口 fix `0b7b6e52`）。
- **「未经确认」标注结构性不可关闭**：`render_blueprint_markdown(content, *, blueprint_status)` 的 `blueprint_status` 实测是 `KEYWORD_ONLY` 且 `default is Parameter.empty`（`test_blueprint_render.py:152-159` 的 `inspect.signature` 断言）；抑制集合是**闭合白名单** `{confirmed, implementing, implemented}`，判据 `if status not in _SUPPRESS_WATERMARK_STATUSES` ⇒ 空串 / `None` / 未知串**全部**渲染标注；签名里**没有第三个参数**，四个候选布尔开关名源码零命中。逐个核过四个调用点：`builtin_types:50` 传 `""`（fail-safe）、`artifact_serializers:138` 与 `blueprint_export_views:298` 传 `blueprint_status_of(artifact)`（纯 `getattr` 归一）、`mcp_tools/views:4597` 传 `artifact.blueprint_status` 原值 —— **没有任何一个调用点能传出白名单内的假值**（三个真实调用点都直读模型字段）。
- **授权面**：`blueprint-gate/` 八个 View **逐个**挂闸（五个改快照动作经 `_aapply_action:183` 一处生效，`Snapshot:223` / `RejectedToBoundary:408` / `UpgradeResearch:491` 各自直挂），判据只有 `_aassert_gate_scope` 一份，两个失败分支回**同一个常量对象** `_GATE_NOT_OPEN_DETAIL` ⇒ 零新增存在性暴露面。两个导出端点与两个 MCP 工具 **import 复用** `blueprint_review_views._aassert_project_scope`（⛔ 未造第四份），且 `_ARTIFACT_MISSING_DETAIL` 一并 import 复用同一常量对象。`file-lines` 走 `[IsAuthenticated, RepositoryPermission]` + `aget_object_or_404(is_deleted=False)`，严格**强于**它声明的 analog `chunk_at_views`（只有 `IsAuthenticated`）。
- **导出的失败纪律与不污染**：上游异常经 `_classify_upstream_error` 分档 400/502，**没有任何一条路径回 200**；异常原文只经 `redact_secrets_in_text(str(exc))[:500]` **逐字内联**进日志（不包 helper，守卫认得出），响应体两档都是中性常量。`create_document` 在缺 `document_id` 时自身 `raise FeishuDocAPIError`（`feishu_doc.py:381-382`）⇒ 不存在「成功但 document_id 为空的 200」。留痕落 Interaction Ledger 且 `record_event` 内部**必经** `redact_for_ledger`（`interactions/ledger.py:122`）；`_arecord_export_ledger` 整段 `try/except: pass`，⭐ 而业务主体没有 —— best-effort 的边界画得对。⛔ 不写 `ArtifactVersion.content`（AST 扫描断言模块标识符里无 `add_version`）⇒ 导出不翻版本、不churn `content_hash`。
- **图谱边的四条结构约束**：citation 派生的目标**先批量 `filter(id__in=…)` 预过滤再交给 `apply_edge_specs`**（`blueprint.py:225-240`），丢弃计入 `dropped_by_source_type`；项目边走 `ensure_project_node` 且**不进过滤器**（`:370`）；同目标多条 citation 按 target 分组聚合成**一条** `EdgeSpec`，`citation_ids` / `source_types` **排序后**写入（重摄取 metadata 幂等）；`RELATES_TO` 出边恰 1 条（`exclusive=True` 的作用域是 `(source, relation)`）；边 metadata 里 `first_seen_version_no` **代码区零使用**（仅 docstring 约束 ④ 标题行 1 处命中）。`url` 与未知 `source_type` 不成边（`_aresolve_target_entity_id:191-193` 的兜底 `return None`）。
- **入图门控的幂等**：`add_version` 侧先记 `previous_version_id` 再比对返回 version 的 id（`artifact_service.py:160-167`）⇒ `content_hash` 相等复用 current 时**不投递**；`create` 侧对称挂同一条判别（P-10）。`_amaybe_schedule_blueprint_ingestion` **不包 try**（`aschedule_ingestion` 内部已吞），normalizer 注册漏行这类错误仍会响亮。
- **intake 的幂等与 fail-closed**：`_h_bp_intake` 首行读 `session.current_artifact_version_id`，非空即原样带回**不重复建 artifact**；`aresolve_project_id` 在 `create_session` **之前**调用（`entrypoint.py:363-372`），抛 `BlueprintIntakeRejected` 时三张表计数与调用前逐字相等；MCP 分支唯一的赋值是 `await _aproject_id_from_space(ctx_space)`，`space_id` 只出现在反查 Space 行的入参位（⛔ 从不作为返回值）。骨架的 `schema_version` 取自懒 import 的 `BLUEPRINT_SCHEMA_VERSION`（`blueprint_intake.py:103-112`，`rg '"blueprint/v1"'` 该文件零命中）⇒ P-2 的三链同时降级形态已堵死。`_feature_point_id` 是位序确定性 id，重跑 `content_hash` 相等不翻版本。
- **`relations` 三层真的通了**：view 解析 `?relations=`（白名单校验，非法 400）→ `retrieval.get_related(relations=…)` 透传 → `fetch_related_entities`；前端 `getRelated` 拼 query（`knowledge.ts:206`），`BlueprintAssociationsSection.vue:106-127` 两块**各自显式传** `relations: ['REFERENCES']` 与 `maxHops: 1`（`_DEFAULT_RELATIONS` 不含 `REFERENCES`、默认 `maxHops` 是 2，两个默认都会让这块变成恒空或多算二跳）。实参来自后端第 8 键 `knowledge_entity_id`（`blueprint_doc_views.py:279-282`，经 `knowledge.sources.blueprint.blueprint_entity_id` 而非 delivery 直 import `knowledge.models`，INV-3 未破）。`_DEFAULT_RELATIONS` 本身零改动。
- **两处 service 抽取的行为保真**：`aanswer_thread` 的三道闸顺序与改造前逐字一致（View 保留一次 `is_blueprint_editable` 前置调用只为保住「不可编辑 400 先于线程 404」的响应顺序），`ai_review_finding` 一律 `not_answerable` 且在 `record_answer` **之前**；`REFLOW_KINDS` 双重堵仍在；REST 侧 `test_blueprint_review_views.py` **零改动全绿**。`repo_file_read` 的下沉：`get_repository_file` 的 16 键响应体、`file_excluded` / `file_not_found` 两个 404 的错误码与**文案逐字未改**，`mcp_tools/serializers.py` 的 `get_repository_file` snapshot 条目相对 116-07 基线零行变更；「索引无命中先于排除判定」的既有顺序也逐字保留。曾担心的 `max_lines <= 0` 钳制差异由 serializer 的 `min_value=1` 证伪为不可达。
- **async / ORM 纪律**：新增的 ORM 访问全部在 `async def` 内走 `a*` API（`afirst` / `aexists` / `acount` / `async for`）或 `@sync_to_async`；`artifact_service` 的两个门控落在 `async def create` / `async def add_version` 体内，`_create_sync` / `_add_version_sync` 仍是 `@sync_to_async` 包的事务块；normalizer 与两个 stage handler 内零裸 lazy-FK（`_aproject_id_from_space` / `_aload_space` / `_aresolve_project_from_artifact` 全部按标量 id 反查）。`BlueprintThread` 的三处查询都显式 `order_by("created_at")`（`Meta` 无 `ordering`）。
- **观测与脱敏**：本相位新增的 30 余条事件逐条带 `category` + `component`，生命周期事件带 `duration_ms`；正文类实参**一律只记长度或条数**（`goal_len` / `point_count` / `body_len` / `markdown_len` / `question_count` / `path_len` / `content_len`），逐个 `logger.*` 调用核对**未发现需求原文 / 蓝图正文 / 澄清题面 / 答案正文 / 源码正文 / 上游响应体进日志**；四个新模块（`blueprint_intake` / `blueprint_notify` / `blueprint_answer_action` / `repo_file_read` / `repo_file_views`）与模块创建同 commit 进了 `_SCANNED_MODULES`。`blueprint_entry_switch` 刻意不进扫描面并做到 `error` 实参零命中，与 analog 同口径。
- **INV-6**：新增模块零裸写 `blueprint_status`；响应键统一 `current_status` / `blueprint_current_status`；116-05 为 `blueprint_status=` kwarg 加的逐行豁免收得极窄（同行必须出现 `render_blueprint_markdown(` 且不得出现任何写表形态），并配了三条伪装行的「守护的守护」。`test_blueprint_inv6_guard` / `test_artifact_inv6_guard` 全绿。
- **业务 vs 观测的失败纪律**（115-MJ-04 的对称面）：本轮逐个核过本相位新增的 11 处 `except Exception` —— 8 处是纯观测/留痕（`_safe_log` ×4、`_arecord_export_ledger`、`_emit`、两个 `_record`），3 处是**分档回错而非吞掉**（导出上游 → 400/502、MCP 两个工具 → 结构化 503 信封、`get_technical_blueprint` 的 pending 读失败 → 503 且响应体逐字不含 `items` / `total`）。**没有发现任何一条把业务失败吞成 200/空的新路径。**

---

_Reviewed: 2026-08-01_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
