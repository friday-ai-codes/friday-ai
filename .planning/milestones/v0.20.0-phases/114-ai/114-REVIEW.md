---
phase: 114-ai
status: fixed
reviewed: 2026-07-31
fixed: 2026-07-31
findings_total: 11
fixed_count: 10
skipped_count: 1
---

# Phase 114 Code Review — AI 对抗审查 + 人审操作面（阶段 4）

**审查基线：** `41309ccc` → `HEAD`（`milestone/v0.20.0-blueprint` worktree）
**审查范围：** `git diff 41309ccc..HEAD -- server/` 的 29 个文件（源 17 / 测试 12），~10405 insertions；`.planning` 文档不审
**深度：** deep（跨模块调用链追踪：REST 端点 → service → lifecycle 守卫 → 回灌 → 线程状态 → 续驱 → 状态机）
**立场：** 对抗性复核。五份 SUMMARY 自述的变异验证（8 处）已覆盖「桶不互相覆盖 / 轮次真递增 / 处置不走作答通道 / 统计不换字段 / 周期锚点真写回」等**单模块内**的失效模式，本轮刻意不复算它们，只打**跨模块合成**的面：一个模块的「合法调用」如何让另一个模块的不变式失守。

**结论：1 CRITICAL / 4 MAJOR / 6 MINOR。** 冻结纪律 13 项全部守住、migration 恰好一条且 `makemigrations --check` 干净（见文末）。

CRITICAL 与 MAJOR-1/2 **三条全部经真实代码路径实测复现**（探针用例已跑通并删除，无残留改动，`git status` 干净）：

| # | 实测结果 |
|---|---|
| CR-01 | approve **409** → 对同一条 BLOCKER finding 线程调 answer 端点答一句「知道了」→ 线程 DB 重读 **`resolved`** → approve **200**，DB 重读 **`confirmed`** |
| MJ-01 | 对已 `pending_review` 的蓝图调 reject → 200 且响应 `current_status: drafting`，但会话仍 `done / __done__`（**零 advance**），DB 里蓝图实际是 **`needs_clarification`** |
| MJ-02 | 一条无 `anchor` 的澄清线程，`areanchor_threads` 一跑即由 `anchored` 变 **`orphaned`**（report `{'checked': 1, 'orphaned': 1}`） |

---

## CRITICAL

### CR-01：answer 端点经回灌链把 BLOCKER finding 推到 `resolved`，无理由、无处置人地解开 confirm 守卫

**文件：** `server/delivery/api/blueprint_review_views.py:516`（`_aload_thread` 无 `kind` 过滤）、`:534`（回灌接线）；`server/services/process_runtime/blueprint_reflow.py:507`（消费集合含 `AI_REVIEW_FINDING`）、`:738-744`（无条件 `resolve_thread`）

**问题：**

114-01/03/05 三份 SUMMARY 反复写死同一条不变式——**「⛔ 绝不能用作答通道处置 finding：`record_answer` 只把线程推到 `answered`，而 `answered` 仍在守卫判据②里，根本解不开死锁」**，并据此把「必填 `reason` + `resolve`/`dismiss` 语义区分 + 处置人写进结论文本」的审计控制全部放在 `_adispose_finding` 里。

但 answer 端点走的**不是**只到 `answered` 为止的那条路。它在 `record_answer` 之后同请求内接了回灌：

```516:539:server/delivery/api/blueprint_review_views.py
        thread = await _aload_thread(artifact_id, thread_id)
        if thread is None:
            return Response(_THREAD_MISSING_DETAIL, status=status.HTTP_404_NOT_FOUND)
        ...
        await lifecycle.record_answer(thread, body=answer, ...)
        try:
            reflow = await aapply_thread_answers(
                artifact, threads=[thread], session=session, ...
            )
```

`_aload_thread` 只约束 `artifact_id`，**不校验 `kind`**；`aapply_thread_answers` 拿到显式 `threads=[...]` 时也不过滤 `kind` / `status`（`blueprint_reflow.py:510-511`）。落版本成功后它对全部被消费线程无条件收尾：

```738:744:server/services/process_runtime/blueprint_reflow.py
        for row in consumed:
            try:
                await lifecycle.resolve_thread(
                    row,
                    resolution=f"答案已回灌，产出版本 v{version.version_no}。",
```

`_resolve_thread_sync` 的条件是 `status__in=[open, answered]` ⇒ 一条 `severity=blocker` 的 `ai_review_finding` 就此落 **`resolved`** 终态，`_has_confirm_blockers_sync` 的两条判据同时失配，approve 放行。

这不是理论推演。**实测链路**（`pending_review` + 一条 open BLOCKER finding，段落重产打桩不触 LLM）：

```
approve             → 409
answer(body="知道了") → 200, reflow.status = "applied", 版本 1 → 2
thread DB 重读        → resolved
approve             → 200, blueprint_status = confirmed
```

即便 LLM 不可得、正文一字未改，`content["decision_log"]` 的合并本身就会改 `content_hash` ⇒ 必然翻版本 ⇒ 必然走到收尾分支。换句话说 **BLOCKER finding 的「处置」只需要在它上面回一句任意文本**，而这条路径：

1. **绕开 `reason` 必填**——`_adispose_finding` 的 `reason` 空即 `invalid` 且不落库，本路径只要 `body` 非空即可；
2. **绕开 resolve/dismiss 的语义区分**——结论文本是 AI 写的「答案已回灌，产出版本 vN」，**既没有 `[已修复]` / `[误报忽略]` 标签，也没有「处置人：{uid}」**，而 SUMMARY 明写「结论文本是唯一留痕位」；
3. **绕开 reviewer 归因**——`first_action` 记成 `thread_answer` 而非 `finding_resolve` / `finding_dismiss`；
4. **语义上更严重**：回答一条「关键结论缺 citations」的 finding 并不等于补上了 citations。审查规则没有重跑（超界后 stage 已 `__done__`），缺陷仍在蓝图里，门却开了。

同一根因还有**第二个入口**：114-03 的 ai_review 入口 0-a 调 `aapply_thread_answers(threads=None)`，其默认查询集**显式包含** `ai_review_finding`：

```504:508:server/services/process_runtime/blueprint_reflow.py
            async for row in BlueprintThread.objects.filter(
                artifact=artifact,
                status=ThreadStatus.ANSWERED,
                kind__in=[ThreadKind.AI_CLARIFICATION, ThreadKind.AI_REVIEW_FINDING],
            ).order_by("created_at")
```

⇒ 任何以任何方式落到 `answered` 的 finding，下一轮审查入口也会把它自动 `resolved` 掉。

**为什么测试没逮住：** `test_answer_is_consumed_into_a_new_version_with_decision_log`（`test_blueprint_review_views.py:466`）跑的正是这条链，断言的正是「线程 DB 重读 `RESOLVED`」——只不过它用的是 `_open_clarification`（`ai_clarification`）。把工厂换成 `_open_finding` 就是本条 CRITICAL，两者代码路径**逐字相同**。114-01 立的 `test_record_answer_on_finding_breaks_legacy_gate_but_new_guard_holds` 也只验到「`record_answer` 之后守卫仍挡」，没有继续走完同一请求里的下一步。

**建议修法（两处都要堵，缺一即漏）：**

① answer 端点按 `kind` 分流——澄清线程才回灌，finding 只留痕：

```python
# blueprint_review_views.BlueprintReviewThreadAnswerView.post
if str(getattr(thread, "kind", "") or "") == ThreadKind.AI_REVIEW_FINDING:
    return Response(
        {"detail": "审查发现请走 resolve/ 或 dismiss/ 处置（需填写理由）"},
        status=status.HTTP_400_BAD_REQUEST,
    )
```

② 回灌链自身 fail-closed，不依赖调用方自觉（第二入口同样受益）——`_aload_thread_payloads` 对**显式传入**的 `threads` 也按 `kind` 过滤，且把 `ai_review_finding` 整体移出消费集合：

```python
_REFLOW_KINDS = (ThreadKind.AI_CLARIFICATION,)
...
rows = [row for row in threads if row is not None and str(row.kind or "") in _REFLOW_KINDS]
```

若产品上确实希望「回答 finding 也算处置」，那也必须走 `_adispose_finding`（强制 `reason`、写 `[已修复] …（处置人：X）`、`first_action=finding_resolve`），**而不是让 AI 的一句「答案已回灌」冒充人的裁决**。

补两条断言：① answer 端点打 finding 线程 → 400 且线程仍 `open`；② `aapply_thread_answers(threads=[finding])` → 该线程状态不变（与现有的 clarification 正路用例并列，证明分流非恒真）。

---

## MAJOR

### MJ-01：驳回后没有任何重跑路径——会话在 ai_review 收官时已 DONE，`_aresume` 必然空转

**文件：** `server/delivery/api/blueprint_review_views.py:415`（reject 的续驱接线）、`server/services/process_runtime/blueprint_resume.py:130`（`while session.status not in terminal`）、`server/services/process_runtime/builtin_processes.py` 的 `ai_review.transitions`（`review_passed` / `review_exhausted` 均 `STAGE_DONE`）

**问题：**

reject 的全部设计前提是「转 `drafting` 之后 AI 会拿新轮次重跑」。`areject_blueprint` 的 docstring 逐字写着「先转状态会留下『状态已 `drafting` 而轮次未加』的窗口，**AI 在该窗口里会拿旧轮次重跑**」，端点也照 112 的体例接了 `_aresume`。

但 `pending_review` **只能**由 ai_review 的两条出边到达，而它们都是 `STAGE_DONE`：

```
"review_passed": STAGE_DONE,     # 全清 → pending_review
"review_exhausted": STAGE_DONE,  # 超界 → pending_review 携未决清单
```

`convergence_session_service` 把 `__done__` 落成 `status=done`。于是人审能点驳回的那一刻，会话**必定是终态**，而续驱驱动器第一件事就是终态短路：

```130:131:server/services/process_runtime/blueprint_resume.py
    while session.status not in terminal:
        steps += 1
```

`engine.advance` 同样对终态直接 return。**全仓没有第二条把 DONE 会话拉回运行的路径。**

实测（`pending_review` + DONE 会话 + 一条未决 BLOCKER）：

```
POST reject → 200 {"status": "rejected", "revision_round": 1, "current_status": "drafting"}
会话         → done / __done__     （零 advance，融合与审查都不会重跑）
蓝图 DB      → needs_clarification （不是响应里说的 drafting）
```

两个后果：

1. **驳回是空动作。** 它只做了「版本 +1 + `revision_round` +1 + 开一条评论线程」，然后蓝图停在 `drafting`/`needs_clarification`，**没有任何进程会再碰它**。用户点了「驳回并说明理由」，AI 永远不会看到那条理由。这让 FLOW-07 的人审闭环缺了回边——`revision_round` 这个本相位新引入的字段因此也永远只会是 1。
2. **响应体与 DB 不一致。** `result["current_status"] = _current_status(artifact)`（`blueprint_review_action.py:340`）在 `_aresume` **之前**取值，而 `_aresume` → `_amap_blueprint_status` 会因为还有 open+blocking 线程把它推成 `needs_clarification`。前端拿到 `drafting`，刷新一下变 `needs_clarification`。

顺带暴露的第三点：`_amap_blueprint_status` 的 `_resolve_stage_status` 只登记了 `repo_plan` / `merge` / `ai_review` 三个 stage，`__done__` 回落 `researching`，而 `drafting → researching` 与 `pending_review → needs_clarification` 都是**非法边** ⇒ 每次驳回/续驱都会白吞一次 `ValueError` 并刷一条 `blueprint_status_map_skipped` warning。

**建议修法：**

reject 必须显式把会话拉回可运行态，而不是指望终态会话自己动。最小改法是在 `areject_blueprint` 转 `drafting` 成功后，经 `ConvergenceSessionService` 把会话从终态复位到 `merge`（或 `ai_review`）stage 并置 `RUNNING`，再由现有 `_aresume` 接管：

```python
# 落版本 + transition(drafting) 成功之后
if str(getattr(session, "status", "")) in ("done",):
    await session_service.reopen(session, stage="merge", reason="human_reject")
```

若不想新增 `reopen` 语义，另一条同等有效的做法是让 `review_exhausted` / `review_passed` 不落 `STAGE_DONE` 而落一个 `pending_review` 的 pausable self-loop stage（`wait_status=waiting_clarification`），让会话停在「等人审」而不是「结束」——那正是它真实的语义，也顺带修好上面第三点的状态映射。

另外把 `result["current_status"]` 挪到续驱之后重读（或直接不回该键），避免响应与 DB 打架。补一条断言：驳回后会话可被续驱且 `current_stage` 回到 `merge`/`ai_review`。

---

### MJ-02：`areanchor_threads` 把所有**本来就没有 anchor** 的线程标成 `orphaned`，CLAR-02 的失锚清单被噪声淹没

**文件：** `server/delivery/services/blueprint_lifecycle_service.py:1356-1406`（`_reanchor_threads_sync` 对 artifact 全量线程无差别调用 `reanchor`），判据来源 `server/delivery/services/blueprint_anchor.py:75-76`

**问题：**

`reanchor` 的第一条分支是：

```75:76:server/delivery/services/blueprint_anchor.py
    if not isinstance(anchor, dict) or not anchor:
        return (anchor, ANCHOR_STATUS_ORPHANED)
```

即「没有 anchor」被算作「失锚」。而 `_reanchor_threads_sync` 取的是 `BlueprintThread.objects.filter(artifact=artifact)` ——**全量线程，不筛 anchor 是否存在**，随后把 `status` 直接写库：

```1387:1406:server/delivery/services/blueprint_lifecycle_service.py
                new_anchor, status = reanchor(anchor, blocks)
                ...
                if thread.anchor != resolved or thread.anchor_status != status:
                    thread.anchor = resolved
                    thread.anchor_status = status
```

本仓大量线程天然无 anchor：`_abp_ensure_blocking_clarification` 开的「自动推进在 X 阶段停下了」线程（`builtin_processes.py:588`，不传 `anchor`）、112 规格门与确认门线程、`_aopen_reject_comment` 在用户没划线时开的评论线程、以及 114-03 对无 `block_id` finding 开的线程（anchor 三键全空串 ⇒ `anchor` 非空 dict，这类反而走模糊分支后同样失锚）。

实测：一条无 anchor 的 `ai_clarification` 线程，`areanchor_threads` 跑一次即 `anchored → orphaned`（`{'checked': 1, 'reanchored': 0, 'orphaned': 1, 'skipped': 0}`）。

而 `areanchor_threads` 现在挂在**每一条产版本路径**上（人工编辑 / 答案回灌 / 人工块写回 / ai_review 入口的版本推进重锚），所以这是**必然发生且持久落库**的。后果落在 114-05 唯一的消费点上：

```284:286:server/delivery/api/blueprint_review_views.py
            "orphaned_threads": [
                row for row in rows if row["anchor_status"] == ThreadAnchorStatus.ORPHANED
            ],
```

CLAR-02 明令「批注不得静默消失」，`orphaned_threads` 就是那条保证的呈现面。现在它混进了一堆**从来就没锚过、也不该锚**的系统线程，真正「块被删掉导致批注错位」的那几条被埋在噪声里——这条保证等于失效，而且是 115 直接消费的字段。`orphaned` 计数同时污染了 `blueprint_threads_reanchored` 事件的指标口径。

**建议修法：** 在批量层加一道「没有可锚定位就跳过，不判失锚」的前置分支（`blueprint_anchor.py` 是 111 冻结面，改批量侧即可）：

```python
                anchor = thread.anchor
                if not isinstance(anchor, dict) or not (
                    str(anchor.get("block_id") or "") or str(anchor.get("quoted_text") or "")
                ):
                    counts["skipped"] += 1
                    continue          # 无锚点线程不参与重锚，anchor_status 保持原值
```

补两条断言：① 无 anchor 线程在重锚后 `anchor_status` **不变**；② 有 anchor 且块被删的线程仍变 `orphaned`（证明判据非恒真）。

---

### MJ-03：七个端点只有 `IsAuthenticated`，无项目/成员范围校验——A 项目成员可确认、驳回、改写 B 项目的蓝图

**文件：** `server/delivery/api/blueprint_review_views.py:251 / 324 / 379 / 441 / 505 / 637 / 651`（七处 `permission_classes = [IsAuthenticated]`）

**问题：**

七个端点的授权判据只有「登录了」。`_aload_action_context` 只校验 artifact 存在，`_aload_thread` 只校验线程属于该 artifact——**URL 里的 `artifact_id` 就是全部范围约束，而它是攻击者可控的**。于是任意登录用户只要拿到一个 artifact UUID，就能：

- `approve/` → 把别人项目的蓝图推到 `confirmed`（下游 implementing 链据此启动）；
- `reject/` → 把别人的蓝图打回并落一条署他名的版本；
- `edit-blocks/` → **改写别人蓝图的任意 block 正文**（`produced_by_ref = human_edit:{他的 uid}`，且该前缀是「人工块保护」的判据源，改完还会被 B3 当成必须保护的人工内容）；
- `threads/<id>/answer|resolve|dismiss/` → 处置别人的审查发现。

同文件 docstring 自述这是「与 delivery/repositories 既有 view 同级——『项目成员皆可确认/评论/编辑』的低门槛决策」。核对属实：`blueprint_gate_views.py` 八个 View 也全是 `IsAuthenticated`，全仓 `rg 'ProjectMember|project_member|has_object_permission'` 零命中——**本仓目前没有项目成员闸这个概念**。所以这条不是 114 引入的回归，但 114 是第一次把「确认蓝图」与「改写蓝图正文」这两个**不可逆写动作**放到这张零范围校验的网上，风险量级与阶段 1 的确认门不在一个档位。同相位的 `blueprint_gate_views.BlueprintRejectedToBoundaryView:383-395` 反倒是全仓唯一做了范围约束的那个（按蓝图 `meta.project_id` 校验并 403），说明「按蓝图自身 project_id 收范围」这条路是走得通的、也已有先例。

**建议修法：** 复用已有先例，抽一个共用 helper 并挂到七个端点的入口：

```python
async def _aassert_scope(request, artifact) -> Response | None:
    project_id = await _ablueprint_project_id(artifact)     # gate_views:511 已有实现
    if not _is_uuid(project_id):
        return Response({"detail": "无法确定项目范围"}, status=400)   # fail-closed
    if not await _ais_project_member(request.user, project_id):
        return Response(_ARTIFACT_MISSING_DETAIL, status=404)        # 中性 404，不泄露存在性
    return None
```

⚠️ 成员判据必须 **fail-closed**（读不到 `meta.project_id` 一律拒，不能放行），否则等于把闸门建在「蓝图恰好写了 project_id」这个可缺失字段上。若产品确实要维持「全员可读写」的低门槛，那也应当把这条决策写进 `.planning` 的显式风险登记，而不是散落在一句 view docstring 里。补一条负向断言：非本项目成员调 approve / edit-blocks → 403/404 且 DB 不变。

---

### MJ-04：`edit-blocks` / `answer` 无蓝图状态闸，可静默改写 `confirmed` / `implementing` / `archived` 的蓝图正文

**文件：** `server/delivery/api/blueprint_review_views.py:443-462`（edit-blocks）、`server/delivery/services/blueprint_block_edit.py:230-359`（`aapply_block_edit` 全程不读 `blueprint_status`）

**问题：**

approve / reject 的合法性由 `_ALLOWED_TRANSITIONS` 兜住（非法边 → 400/409）。但 `edit-blocks` **根本不碰状态机**：它读最新版本 → apply ops → `validate_blueprint` → `add_version` → 重锚定，全程没有一处读 `artifact.blueprint_status`。

于是一份已 `confirmed`（甚至 `implementing` / `implemented` / `archived`）的蓝图，任何登录用户都能继续往上面落 `human_edit:` 版本，而：

- 蓝图状态**不变**（仍是 `confirmed`），没有任何「内容变了但确认还在」的信号；
- 下游 implementing 链拿到的 `artifact.current_version` 已经不是当初被确认的那一版——**「确认」这个动作所锚定的内容被事后掉包**，且没有留下需要重新确认的痕迹；
- `human_edit:` 前缀同时是 B3 人工块保护的判据源，事后编辑会让保护集在下一次审查入口凭空扩大。

这与本相位对「AI 不得覆盖人工」的极度小心恰好是对称的一面：**人也不该在确认之后无声覆盖已确认内容**。answer 端点同理（它也会经回灌落新版本）。

**建议修法：** 在 `aapply_block_edit` 入口加一道可编辑状态白名单（service 层收口，端点只映射状态码），并在越界时返回可回显的 `invalid`：

```python
_EDITABLE_STATUSES = frozenset({
    BlueprintStatus.DRAFTING, BlueprintStatus.AI_REVIEWING,
    BlueprintStatus.NEEDS_CLARIFICATION, BlueprintStatus.PENDING_REVIEW,
})
if str(getattr(artifact, "blueprint_status", "") or "") not in _EDITABLE_STATUSES:
    return _edit_result("invalid", detail="当前蓝图状态不允许编辑，请先驳回或新建修订")
```

若确实要允许确认后编辑，则必须同时把状态推回 `drafting`（`confirmed → drafting` 是合法边）并重新走人审——绝不能让内容变了而「已确认」的结论原地不动。补一条断言：`confirmed` 蓝图调 edit-blocks → 400 且版本数不变。

---

## MINOR

### MN-01：提醒扫描是**无序** `LIMIT 100`，超过 100 条时既不确定又会永久饿死后来的线程

**文件：** `server/delivery/services/blueprint_review_action.py:580-586`

```580:586:server/delivery/services/blueprint_review_action.py
    return list(
        BlueprintThread.objects.filter(
            artifact__blueprint_status=BlueprintStatus.NEEDS_CLARIFICATION,
            status=ThreadStatus.OPEN,
            blocking=True,
        ).select_related("artifact")[:limit]
    )
```

`BlueprintThread.Meta` **没有 `ordering`**（只有 `db_table` / `indexes`），所以这条 `[:100]` 是无 `ORDER BY` 的 `LIMIT` —— 返回哪 100 条由存储层决定，跨版本/跨引擎不稳定。更实际的问题是**饿死**：被提醒过的线程写回 `last_reminded_at` 后仍然满足过滤条件、仍然占着这 100 个名额（只是每轮记 `skipped`），一旦全站未应答的 blocking 澄清线程超过 100 条，排在后面的线程可能**永远拿不到一次提醒**，而 job 每小时照跑、日志照报「completed」，失效完全静默。

**建议修法：** 按「最该被提醒的排前面」显式排序，让每轮扫描窗口自然滚动：

```python
        ).select_related("artifact").order_by(F("last_reminded_at").asc(nulls_first=True), "created_at")[:limit]
```

补一条断言：造 `limit + 1` 条到期线程，跑两轮后**全部**被提醒过至少一次。

---

### MN-02：三处新增日志的异常文本未脱敏，与本相位自己刚补的纪律相反

**文件：** `server/delivery/services/blueprint_lifecycle_service.py:1303`、`server/delivery/services/blueprint_block_edit.py:200`、`server/services/process_runtime/builtin_processes.py:543`

三处都是 `error=str(exc)` 裸写：

```1303:1303:server/delivery/services/blueprint_lifecycle_service.py
                error=str(exc),
```

`.cursor/rules/observability-logging.mdc` 明令异常文本走 `redact_secrets_in_text`，本相位 114-05 的 Task 0 恰好就是为同一类问题给 `blueprint_transition_event_persist_failed` 补上脱敏（commit `6f91f778`）——同一份 diff 里新写了三处一样的裸写。`blueprint_threads_reanchor_failed` 尤其值得堵：它兜的是整段重锚（含 DB 异常与上游内容异常），`anchor.quoted_text` 是半可信蓝图正文的截取，可能夹带凭证样本。

（`builtin_processes.py:543` 的 `_abp_mark_ai_reviewing` 是照抄既有的 `_abp_mark_drafting:503`，属沿袭而非新造，但既然在改这一段，两处一起补更省事。）

**建议修法：** 三处统一改 `error=redact_secrets_in_text(str(exc))`（前两个文件已 import 或已有函数内 import 先例）。更根本的做法是加一条「新增段的 `logger.*(... error=` 必须经脱敏函数」的 AST 守卫，本相位已有多条同款源码扫描用例可以照抄。

---

### MN-03：`gate_lock_violation` 的角色偏离与职责偏离共用同一个 dedupe key ⇒ 重复线程，且第二条**永远不会被自动收尾**

**文件：** `server/services/process_runtime/blueprint_review.py:657-684`（两条 finding 的 `section_path` / `block_id` 逐字相同）、`:2013-2040`（落线程）、`:2109`（`index.setdefault`）

`check_gate_lock` 对同一个仓可以同时产出两条 finding（`role` 偏离 + `responsibility` 文本偏离），而两条的 `rule_id` / `section_path` / `block_id` **完全相同**：

```python
section_path = f"repo_associations[{repository_id}].responsibility"
block_id = f"blk_gate_resp_{repository_id}"
```

⇒ `finding_dedupe_key` 对它们返回同一个键 `gate_lock_violation|blk_gate_resp_{rid}`。后果分两轮：

- **第一轮**：`existing` 是循环**之前**一次性查好的索引，新开的线程不会进去，所以第二条 finding 又开了一条**内容不同的重复线程**；`landed[key]` 被第二条覆盖 ⇒ 第一条的 thread_id 从 `thread_ids` / `unresolved` 快照里**消失**，人审面板上有这条线程却在未决清单里找不到它。
- **第二轮起**：`_aload_finding_threads` 用 `index.setdefault` 只保留其中一条，另一条既拿不到「第 N 轮仍存在」留痕，也**不会进入「本轮已消失 → resolve」的收尾循环**（它压根不在 `existing` 里）。它是一条 `open + blocking` 的 BLOCKER 线程 ⇒ **永久挡住 confirm，只能靠人工 dismiss 才能清掉**。

**建议修法：** 让同一 rule 的不同形态可区分。最小改法是把形态写进 `section_path` 尾段（`…responsibility#role` / `…responsibility#text`），或给 `_finding` 加一个可选的 `variant` 并纳入 `finding_dedupe_key`。补一条断言：同一仓同时角色与职责都偏离时，两条 finding 的 `finding_dedupe_key` 不相等，且第二轮两条都拿到留痕。

---

### MN-04：`reminded` 计数在周期锚点写回**之前**累加，`bulk_update` 失败时统计虚高

**文件：** `server/delivery/services/blueprint_review_action.py:680-693`

```680:693:server/delivery/services/blueprint_review_action.py
                due_rows.append(thread)
                counts["reminded"] += 1
            ...
        if due_rows:
            await _write_reminder_anchors(due_rows, moment)
```

`_write_reminder_anchors` 抛异常时被外层 `except` 接住并 `return counts`——此时 `counts["reminded"]` 已经是满值，而 `last_reminded_at` 一条都没写。对运维呈现的是「本轮提醒了 N 条」，实际是「一条锚点都没落、下一轮会把同样这 N 条再提醒一遍」。日志里同时有 N 条 `blueprint_clarification_reminded`，与真实状态同样对不上（这条更根本：事件在写回之前就发了）。

**建议修法：** 把 `reminded` 的口径改成「锚点已写回」，即写回成功后再 `counts["reminded"] = len(due_rows)`；写回失败时保留 `due` 但把 `reminded` 归零并记一条 warning。

---

### MN-05：`blueprint_quality` 三项统计实装了但**全仓零消费方**，「度量面闭环」只兑现到「可被调用」

**文件：** `server/services/process_runtime/blueprint_quality.py:116 / 145 / 170`

三项 DB 统计写得很扎实（三态并列、`None` ≠ `0`、逮住了 111 的 `created_by_user_id` 偏差），但 `rg` 全仓（排除 tests）对 `ai_rejection_rate` / `human_edit_volume` / `clarification_rounds` 的命中**只有它们自己的定义**——`delivery/management/commands/evaluate_blueprint_golden.py` 里的两处命中是 docstring 的用法示例，命令体并未调用它们。也就是说这三个指标目前既不进离线评估、也不进任何 API 或大盘。

这不是 bug（114-05 的边界本就是「实装口径，消费留给 115/116」），但 SUMMARY 的「度量面闭环」表述会让后续相位误以为已有消费面。建议在 `evaluate_blueprint_golden` 里接上（它是这三项唯一自然的消费者，且是同步命令、无 async ORM 问题），或在 Deferred Issues 里显式登记「零消费方」。

---

### MN-06：`_amap_blueprint_status` 对 `pending_review` 必然尝试一条非法边，每次续驱刷一条 warning

**文件：** `server/services/process_runtime/blueprint_resume.py:307-316`

审查收官后蓝图落 `pending_review`，而未决 BLOCKER finding 让 `ahas_open_blocking_threads` 恒为真 ⇒ `target = NEEDS_CLARIFICATION`。但 `_ALLOWED_TRANSITIONS[PENDING_REVIEW] = {DRAFTING, CONFIRMED, SUPERSEDED}`，**不含 `needs_clarification`** ⇒ 每一次续驱都会白抛一次 `ValueError` 并吞成 `blueprint_status_map_skipped`。

行为上无害（状态正确地留在 `pending_review`），但它说明状态映射表没有跟上 114 新增的终态语义：映射器现在会对一个**完全正常**的状态反复报「映射被跳过」，真正的映射故障因此淹没在噪声里。

**建议修法：** 映射前先短路终审态——`if artifact.blueprint_status in (PENDING_REVIEW, CONFIRMED, ...): return`（这些状态不由续驱驱动），或把 `_resolve_stage_status` 补上 `__done__ → pending_review` 的登记。

---

## 冻结纪律与门禁复核（`git diff 41309ccc..HEAD`）

| # | 项 | 结论 |
|---|---|---|
| 1 | `codegraph/services/repo_router_v2.py` | ✓ `--numstat` 零输出 |
| 2 | 六个 legacy `technical_plan` process 文件（`decompose_segments` / `research_adapter` / `architect_merge_adapter` / `merged_plan` / `clarify_adapter` / `render`） | ✓ 逐个零输出 |
| 3 | `blueprint_merge.py` 被 114-03 零改动 | ✓ 零输出（B3 的人工块保护确实挂在审查入口而非融合里） |
| 4 | `blueprint_anchor.py`（server/delivery 与 services 两处）、`blueprint_schema.py`、`agents/call_source.py`、`resume.py` | ✓ 全部零输出 |
| 5 | `ConvergenceSessionEvent` 既有类型/字段未改 | ✓ `event_taxonomy.py` 删除行 **0**，三个 `blueprint.review.*` 为纯追加，`BLUEPRINT_EVENTS` 18 → 21 |
| 6 | migration | ✓ 全相位**恰好一条** `delivery/0033_blueprintthread_last_reminded_at`（单个 `AddField`，依赖 `0032`）；编号无碰撞（`0032` 之后无其它 `0033*`）；`AddField(null=True, blank=True)` 天然可逆 |
| 7 | `makemigrations --check --dry-run` | ✓ 实跑 `No changes detected` |

## 复核过、确认干净的面（不计入 findings）

- **跨 process 污染（本仓 112 的历史 CRITICAL）**：`_aload_session`（`blueprint_review_views.py:100-107`）与 `_list_recipients`（`blueprint_review_action.py:607-610`）**都带了** `process_type=BLUEPRINT_PROCESS_TYPE`；`blueprint_reflow` / `blueprint_review` 的基线读取全部走 `artifact` 维度而非 session 维度。全 diff 内没有第三处「取最近一条会话」的写法。
- **approve 的 TOCTOU**：视图与 service 双侧确认零事务外预查询，`aunresolved_blocker_count` 只出现在 GET 快照与 409 响应体的呈现路径上；守卫的两条判据仍是 `_apply_transition_sync` 事务内的单次 `Q`。
- **有界回退计数**：`_bucket` 只回写 `{"ai_review": …}` 增量，engine 侧是顶层浅合并（`engine.py` 只透传 `stage_state_update`），融合桶不会把 `round` 抹掉；`round + 1` 只在 `_atransition` 成功时才生效，转移失败降级为 `needs_clarification` 且不递增——不会出现「转移失败但轮次白烧」。`ai_review.transitions` 五条出边确认**不含 `failed`**。
- **INV-6**：新增的两个 view 模块零 ORM 写；`blueprint_reflow` / `blueprint_block_edit` / `blueprint_review` adapter 的线程与版本写入全部经 `BlueprintLifecycleService` / `ArtifactService`；线程行的唯一新写通道是 `_reanchor_threads_sync` 内的 `bulk_update`（在 service 内）。
- **async / ORM 纪律**：`_load_thread_rows` / `_list_pending_threads` / `_list_recipients` / `_write_reminder_anchors` / `_reanchor_threads_sync` 全部 `@sync_to_async` 包同步体，`transaction.atomic()` 完整落在被装饰函数**内部**；跨 FK 访问一律 `select_related`（`_aload_thread` 的 `artifact`、`_aload_latest_version` 的 `supersedes`、`_list_pending_threads` 的 `artifact`），未见 async 上下文里的裸 lazy-FK。`blueprint_quality` 三项是同步函数但只被同步管理命令调用，无 `SynchronousOnlyOperation` 风险。
- **观测规范**：本相位新增的全部结构化事件抽查下来 `category` + `component` 无缺漏；`approve` / `reject` / `dispose` / `remind_completed` / `review_completed` / `block_edit_applied` / `reflow_applied` 等生命周期事件带 `duration_ms`；两个新 LLM 调用点（`agoal_backward_review`、`_arewrite_block_text`）都在 `use_call_source(CallSource.BLUEPRINT_AI_REVIEW)` 内，无新增枚举值；日志与事件 payload 只见计数、分级分布与关联键，**未发现 finding 正文 / 澄清问答正文 / block 正文进日志**（唯一的脱敏缺口是 MN-02 的三处异常文本）。
- **`_MAX_*` 上界**：`_MAX_FINDINGS=50` 截断只影响详尽度不影响处置（有一条 BLOCKER 结论就已成立）；`unresolved`/`thread_ids` 的 30 条上界只作用于 `stage_state` 快照，线程本身不丢——与 113-MJ-04 那类「截断导致处置遗漏」的形状不同，此处成立。

---

_Reviewed: 2026-07-31_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_

---

## Fix Log

**修复于：** 2026-07-31 · 分支 `milestone/v0.20.0-blueprint`（worktree `v0.20-blueprint`）
**结论：10 fixed / 1 skipped。** CRITICAL 与全部 4 条 MAJOR 已修；MINOR 修 5 条、跳 1 条
（MN-05，两条建议修法中的可行那条已改为显式登记，理由见下）。

CR-01 / MJ-01 / MJ-02 的复现探针已**转成永久回归用例**（不是一次性探针），且每条都实测过
「修前红 / 修后绿」。

### CRITICAL

| ID | 结论 | commit | 说明 |
|---|---|---|---|
| CR-01 | **fixed** | `fbcdc36d` | 两处都堵：answer 端点按 `kind` 分流（finding → 400 且不改线程状态）；回灌链新增 `REFLOW_KINDS`（仅 `ai_clarification`），**显式传入的 `threads` 也按 kind 过滤**，并把 `ai_review_finding` 移出默认查询集（堵住 ai_review 入口 0-a 的第二个入口） |

**修前红 / 修后绿证据（CR-01）**：三条新用例在只回滚源码（保留用例）时全红——
`test_answer_endpoint_refuses_finding_threads_and_the_confirm_guard_holds`、
`test_reflow_never_consumes_an_explicitly_passed_finding_thread`、
`test_reflow_default_queryset_excludes_finding_threads`；修后连同既有 80 条一起全绿。
第一条同时复刻了评审实测的完整链路（approve 409 → answer → 线程仍 `open` → approve 仍 409
→ DB 仍 `pending_review`），并配了「澄清线程走 answer 仍 200」的非恒真对照。

### MAJOR

| ID | 结论 | commit | 说明 |
|---|---|---|---|
| MJ-01 | **fixed** | `183fab1f` | `ConvergenceSessionService` 新增 `areopen_stage`（只从 `done` 复位、stage 必须在 stage graph 内、CAS 以 `status==done` 为前置、不碰 `stage_state`/`current_artifact_version`/`error`）；`areject_blueprint` 在「版本已落 + 轮次已加 + 状态已 drafting」之后复位到 `merge`；approve/reject 的 `current_status` 改为**续驱之后重读** |
| MJ-02 | **fixed** | `b2249004` | 批量层前置 `_has_anchor_locator`（`block_id` 或 `quoted_text` 非空）：无定位即 `skipped` 且 `anchor_status` 保持原值，不进 `reanchor`。**不改** 111 冻结面 `blueprint_anchor.py` |
| MJ-03 | **fixed** | `087b2a2a` | 抽 `_aassert_project_scope` 挂到 `_aload_action_context` 与只读快照：范围只从蓝图 `meta.project_id` 推导（不接受请求体）、fail-closed（读不到/非 UUID → 400）、越权回中性 404、superuser 直通；成员判据与 `chat.conversation_service._is_project_member` 同源 |
| MJ-04 | **fixed** | `bbf71ac5` | `blueprint_lifecycle_service` 新增 `EDITABLE_BLUEPRINT_STATUSES` / `is_blueprint_editable` / `NOT_EDITABLE_DETAIL`；`aapply_block_edit` 第 0 步即状态闸 → `invalid`；answer 端点的状态闸放在 `record_answer` **之前**（越界时线程状态也一字未动） |

**修前红 / 修后绿证据**

- **MJ-01**：`test_reject_reopens_a_terminal_session_so_the_ai_can_actually_rerun` 与
  `test_reject_reports_the_status_the_db_actually_lands` 在只回滚三个源码文件时**双红**，
  修后全绿。前者断言驳回后会话 `RUNNING` 且 `current_stage == "merge"`、`stage_state`
  原样保留；后者用「续驱把状态推成 `needs_clarification`」的桩复现响应/DB 打架。
- **MJ-02**：`test_threads_without_any_locator_are_skipped_not_marked_orphaned` 与
  `test_a_thread_with_a_real_but_deleted_anchor_still_becomes_orphaned` 修前双红，修后
  18 条全绿。第二条是非恒真对照——跳过判据只筛「没有可锚定位」，真失锚仍必须落 `orphaned`。
- **MJ-03**：七条参数化负向断言（每端点一条：404 且 DB 一字未动）+ fail-closed 400 共
  **8 条修前全红**；另加超管直通一条证明闸门非「一律拒」。
- **MJ-04**：`confirmed`/`implementing`/`archived` 三态 edit-blocks + answer 共 **4 条修前红**；
  第五条「四个可编辑态一律 200」修前即绿（非恒真对照，本就该绿）。

### MINOR

| ID | 结论 | commit | 说明 |
|---|---|---|---|
| MN-01 | **fixed** | `d5fc3fe4` | 提醒扫描显式 `order_by(F("last_reminded_at").asc(nulls_first=True), "created_at")`：已提醒的自然沉底、扫描窗口逐轮滚动。补「`limit+2` 条到期线程跑两轮后全部至少被提醒过一次」 |
| MN-02 | **fixed** | `42167fac` | 蓝图链八处 `error=str(exc)` 统一走 `redact_secrets_in_text`，顺带补 `convergence_session_event_persist_failed`；**并加根治面**：新增 `test_blueprint_log_redaction_guard.py`，AST 遍历蓝图链九个模块的 `logger.*` 调用，任何 `error=` 实参必须经脱敏出口，自带「规则真能逮住裸写」的反向自证 |
| MN-03 | **fixed** | `7c461f1d` | 拆 `RULE_GATE_LOCK_MISSING`（保留原值 `gate_lock_violation`，兼容既有线程）/ `RULE_GATE_LOCK_ROLE` / `RULE_GATE_LOCK_RESPONSIBILITY`。形态写进 `rule_id` 而非 `section_path`（后者不影响 dedupe key，见下），`block_id` 不动 ⇒ 锚定仍指向同一真实块 |
| MN-04 | **fixed** | `3955eeb8` | `counts["reminded"]` **与逐条 `blueprint_clarification_reminded` 事件**都改到 `_write_reminder_anchors` 成功之后；写回失败时 `due` 如实保留、`reminded` 归零、一条事件都不发 |
| MN-05 | **skipped** | `aec3ef14`（仅登记） | 见下方完整理由 |
| MN-06 | **fixed** | `0ae50026` | `_amap_blueprint_status` 前置短路 `_HUMAN_OWNED_STATUSES`（`pending_review`/`confirmed`/`implementing`/`implemented`/`archived`/`superseded`），改记一条 sampling 的 `blueprint_status_map_human_owned`（可归因，不再伪装成故障） |

### 跳过项的完整理由

#### MN-05（三项质量统计零消费方）—— **skipped**

评审自己写明「这不是 bug（114-05 的边界本就是「实装口径，消费留给 115/116」）」，并给了两条
处置：① 接进 `evaluate_blueprint_golden`；② 在 Deferred Issues 里显式登记。

**① 经核实不可行，且硬接会让情况更糟。** `ai_rejection_rate` / `human_edit_volume` /
`clarification_rounds` 三项全部按 `artifact_id` 查 delivery models，而
`evaluate_blueprint_golden` 的 golden case 是**静态 JSON fixture**——实测
`tests/fixtures/blueprint_golden/gaokao_boost.json` 顶层只有
`{name, description, blueprint, expected}`，**没有 `artifact_id`**，DB 里也不存在对应
artifact；该 command 的 docstring 还明写「全程无 LLM / 无网络 / 无 DB 写，天然过
`--disable-socket`」。硬接的结果只会是三个**恒 `None`** 的 report 键——那比不接更糟：报表上
看着有指标，实则永远无数据，正是本节 docstring 自己警告的「指标看着漂亮而实际什么都没测」。
这属于**设计决策而非缺陷**（消费面需要真实 artifact_id 在手，那是 115/116 的运行时大盘 /
人审面板），不在 MINOR 的风险预算内。

**② 已执行**：在 `blueprint_quality.py` 的 DB 统计节源码处显式登记「零消费方 + 为何不能接
golden 评估 + 正确消费面在 115/116」，并同步进 `.planning/STATE.md` 的 Deferred（115/116 起手
即可见），杜绝后续相位据 SUMMARY 的「度量面闭环」表述误判已有消费面。零行为改动。

### 判断调用与登记在案的取舍

1. **MJ-01 复位目标取 `merge` 而不是 `ai_review`**：只回审查 stage 等于拿同一份内容再审一遍，
   必然复现同样的 findings。`merge` 与 `ai_review` 既有的 `remerge` 出边**同目标**——「重跑
   融合再重审」在本 stage graph 里已是登记在案的返工路径，不新造语义；人工块保护（B3）挂在
   审查入口，重跑融合不会覆盖人工编辑。
2. **MJ-01 未采纳「让 `review_passed`/`review_exhausted` 落 pausable `pending_review` stage」**
   那条备选：它要改 `ai_review` 的两条收官出边语义 + 新增一个 stage + 新 handler，会让所有
   「审查收官后会话为 `done`」的既有断言集体翻盘，血溅面远超一条 MAJOR 的预算。`areopen_stage`
   是更小的等效改法。MN-06 的状态映射噪声已由 MN-06 自己单独修好，不必绑在这条上。
3. **`areopen_stage` 只从 `done` 复位、不动 `failed`**：失败有首因、要留痕，复位会把「为什么
   失败」冲掉；重开失败会话是另一个语义，需要显式决策。
4. **`areopen_stage` 不发 `ConvergenceSessionEvent`**：新事件类型属纯追加、本可做，但 §13.2 把
   既有事件类型/字段定为 consume-only，而复位已由结构化日志
   （`convergence_session_reopened`）+ 驳回自身的 `blueprint_review_rejected` 双重可归因。
   为一条 MAJOR 引入新事件常量并牵动 `event_taxonomy` 的守护测试不划算。
5. **MJ-03 的成员判据用「一人一项目一行的 `ProjectMember`」而非 `SpaceRole` 层级**：与
   `chat.conversation_service._is_project_member` / `services.project_context_packer._is_member`
   同源（项目内不再分角色，对齐原 docstring 的「项目成员皆可确认/评论/编辑」低门槛决策，只是
   把「成员」这道闸真的建起来）。
   ⚠️ **评审的一处事实订正**：正文说「全仓 `rg 'ProjectMember|project_member|
   has_object_permission'` 零命中——本仓目前没有项目成员闸这个概念」。实测**有**命中：
   `initiatives.models.ProjectMember`、`permissions/api_permissions.py:34 IsProjectMember`、
   `services/project_context_packer.py:88`、`chat/conversation_service.py:808`。所以这条不需要
   发明新概念，直接复用既有判据即可——修法因此比评审预估的更轻。
6. **MJ-04 白名单含空串 `""`**：`""` = v0 数据 / 未进状态机。把它算作不可编辑会让升级前建的
   蓝图突然不可编辑，属**行为回退**（硬约束「已有部署升级后行为不得回退」）。
7. **MJ-04 的 answer 侧闸放在端点而非 `aapply_thread_answers`**：状态白名单已覆盖 AI 编排链
   会经过的全部状态（`drafting`/`ai_reviewing`/`needs_clarification`），端点闸已完整覆盖人工
   写路径；再往回灌链加一道只会给 AI 编排链新增一个失败模式，收益为零。
8. **MN-03 把形态写进 `rule_id` 而不是评审建议的 `section_path` 尾段**：`finding_dedupe_key`
   **优先取 `block_id`**（`block_id or section_path`），而两条 finding 的 `block_id` 逐字相同
   ⇒ 只改 `section_path` **根本不改变键**，建议修法的第一条形态无效。`rule_id` 则是
   `_aload_finding_threads` 唯一能从线程首条消息 `[rule_id]` 前缀反查回来的段，改它才能让
   **第二轮**的键也真的分开。也因此未选「给 `_finding` 加 `variant` 键」：`variant` 无法从线程
   行反查，第二轮的 `index` 仍会折叠。
   修前碰撞已直接实测坐实：两条 finding 的键同为
   `gate_lock_violation|blk_gate_resp_repo-a`。
9. **MN-02 的扫描面只含蓝图链九个模块**：全仓还有大量早于本纪律的同款 `error=str(exc)` 裸写
   （`crawl_service` / `work_item_service` / `coding_completion` / … 二十余处），一次性收口不在
   本相位风险预算内，登记为后续独立清理。
10. **MN-02 顺带修了 `convergence_session_event_persist_failed`**（评审未列，属同类）：它在本轮
    因 MJ-01 已被触及，且新增的 AST 守卫把该文件纳入扫描面，不补即红。
11. **MN-06 / MJ-01 引入常量的用例「修前红」形态是 collection error**：新用例 import 的常量
    （`_HUMAN_OWNED_STATUSES` / `RULE_GATE_LOCK_*`）在修前不存在 ⇒ 回滚源码后整文件收集失败而
    非「断言失败」。这两条的缺陷因此**另用直接探针坐实**：
    `_ALLOWED_TRANSITIONS[PENDING_REVIEW] == {confirmed, drafting, superseded}`（不含
    `needs_clarification` ⇒ MN-06 的非法边必然发生）、以及上面第 8 点的键碰撞实测。

### 相位门

- `uv run pytest tests/ -q` → **8546 passed / 63 skipped / 1 xfailed / 1 failed**，489s。
  唯一 failure 是 `tests/mcp_tools/test_skills_snapshot_guard.py::test_skill_files_discovered`
  —— worktree 的 `skills/` 子模块未初始化，登记在册的环境产物，与本轮改动无关。
  **基线 8507 passed / 1 failed → 现 8546 passed / 1 failed**：净增 39 条用例，failure 集合逐字
  未变（零回归）。
- `uv run python manage.py makemigrations --check --dry-run` → **No changes detected**；
  `server/delivery/migrations/` 仍止于 `0033_blueprintthread_last_reminded_at`，**本轮零新增
  migration**（全部修法均无模型字段变更）。
- 改动的 17 个文件（源 10 / 测试 7）`uv run ruff check` + `ruff format --check` 全 clean。

### 冻结纪律复核（`git diff c9385e24..HEAD`，逐个 `--numstat` 零输出）

`codegraph/services/repo_router_v2.py` ✓ ｜六个 legacy `technical_plan` process 文件
（`decompose_segments` / `research_adapter` / `architect_merge_adapter` / `merged_plan` /
`clarify_adapter` / `render`）✓ ｜`blueprint_anchor.py` ✓（MJ-02 刻意改批量侧）｜
`blueprint_schema.py` ✓ ｜`blueprint_merge.py` ✓ ｜`event_taxonomy.py` ✓（`ConvergenceSessionEvent`
既有类型/字段零改动，本轮**未新增**任何事件常量）。

_Fixed: 2026-07-31_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
