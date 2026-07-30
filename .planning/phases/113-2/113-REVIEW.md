---
phase: 113-2
status: findings
reviewed: 2026-07-30
---

# Phase 113 Code Review — 分仓方案与融合（阶段 2/3）+ Context Bus

**审查基线：** `0ce64322`（Phase 112 `docs(112): review fix log`）→ `HEAD`（`e6bb8a04`）
**审查范围：** Phase 113 feat/fix commits 触及的 `server/` 与 `task/` 源文件与测试（44 个 py 文件）；`.planning` 文档不审
**深度：** deep（跨文件调用链追踪：容器 MCP 写入 → service → waiter → 回调 → barrier → engine）
**立场：** 对抗性复核。113-VERIFICATION 已判 54/54 passed，本轮**刻意不复算它已覆盖的面**（存在性 / 接线 / 冻结面 / 断言可证伪性），只打它没覆盖的维度：**跨模块存活性（liveness）、越权与伪造、静默丢弃**。

**结论：1 CRITICAL / 4 MAJOR / 9 MINOR。** 冻结纪律 4 项全部守住（见文末）。CRITICAL 与 MAJOR-1/2/3 全部是 VERIFICATION 的证据口径（存在 + 接线 + 单点断言）在结构上照不到的类别：它们要么跨 3 个模块才成立，要么是「本该被写入的字段没被覆写」这种"缺失的否定"。

---

## CRITICAL

### CR-01：总线写入采信容器上报的 `repository_id`，可伪造他仓接口契约并误唤醒其等待者

**文件：** `server/mcp_tools/views.py:4296`（`ReportBlueprintContextView._handle`），配合 `server/mcp_tools/serializers.py:ReportBlueprintContextRequestSerializer`

**问题：**

写入路径把 `key` 与 `repository_id` **原样**交给 service：

```4294:4306:server/mcp_tools/views.py
            key = str(input_data.get("key") or "")
            repository_id = str(input_data.get("repository_id") or "")
            entry = await service.append_entry(
                session=convergence_session,
                key=key,
                kind=str(input_data.get("kind") or ""),
                content=input_data.get("content") or {},
                repository_id=repository_id,
                produced_by=str(getattr(sub, "session_id", "") or "container"),
```

只有 `produced_by` 是服务端权威的；`key` 与 `repository_id` 全部来自请求体，且 serializer 只校验长度、**不校验前缀归属**。后果：

1. **跨仓契约伪造。** 仓 A 的容器可写 `key="repo:{B 的 uuid}.api_surface"` + `repository_id="{B 的 uuid}"`，内容为它自己编的接口形状。第三个仓按 `repository_id` 或 `key_prefix` 过滤读取时拿到的就是这条伪造条目——`read_entries` 的过滤器建立在不可信字段上。
2. **误唤醒 + 烧容器额度。** 该伪造 key 会命中 `satisfy_waiters(key=…)`（`blueprint_context_service.py:518`），把真正在等 B 的仓的 waiter 置 `superseded` 并触发 `aredispatch_waiting_repos` 重派容器。等待方拿着假契约继续拟方案，且**真契约到达时 waiter 已被消耗，不会再重派一次**。
3. **这条不变量本仓已有先例，只在总线这一处漏了。** 同相位的 `blueprint_repo_plan._apply_authoritative_fields`（`:1032`）与 `callbacks._handle_blueprint_repo_plan_completion`（`section["repository_id"] = str(task.repository_id)`）都明确写了「`repository_id` 不采信容器上报值」；总线是唯一破例的写入面，而它恰恰是本相位新增的、并行容器共享的面。

VERIFICATION 的 BUS-01 证据（三道会话校验 + 项目成员闸 + 全路径非 5xx）全部是**会话边界**的证据，跨会话确实堵住了；但**会话内的仓间伪造**不在它的口径里，`test_blueprint_context_tools.py` 也没有对应负向用例。

**建议修法：**

服务端权威推导本容器的仓，拒绝越界写：

```python
# _aresolve_blueprint_session 已取回 sub；沿用它的 last_output 反查本容器的仓
task_id = (sub.last_output or {}).get("research_task_id")
own_repo_id = await _afetch_task_repository_id(task_id)   # RepoResearchTask.repository_id

# ① repository_id 一律覆写为服务端值，不采信上报
repository_id = str(own_repo_id or "")

# ② key 的 repo: 前缀必须与本仓一致（contract:/decision: 等非仓前缀照旧放行）
if key.startswith("repo:") and not key.startswith(f"repo:{own_repo_id}."):
    return _blueprint_session_error("key_not_owned")   # 403，与三道校验同一错误信封
```

`own_repo_id` 反查不到时（非 repo_plan 链的容器）应 fail-closed 拒绝 `repo:` 前缀写入，而不是放行。补两条负向断言：跨仓 `repository_id` 被覆写、跨仓 `repo:` key 被 403。

---

## MAJOR

### MJ-01：会话隔离的第一道校验建在攻击者可控的 header 上，而 `token → session` 绑定其实存在（调研前提有误）

**文件：** `server/mcp_tools/views.py:4075-4118`（`_aresolve_blueprint_session`），`server/mcp_tools/views.py:4090`（注释）

**问题：**

道①的实现是「header 里的 session → 它的 `main_session.user_id` == token owner」：

```4095:4109:server/mcp_tools/views.py
    raw_session_id = str(request.headers.get("X-Friday-Session-Id", "") or "").strip()
    if not raw_session_id:
        return None, None, "missing_session_header"

    sub = await _fetch_subagent_session(raw_session_id)
    if sub is None:
        return None, None, "session_not_found"

    owner_id = getattr(sub.main_session, "user_id", None)
    request_user_id = getattr(request.user, "id", None)
    if owner_id is None or request_user_id is None or str(owner_id) != str(request_user_id):
        return None, sub, "session_not_owned"
```

这条判定的语义是「**同一用户的任意会话**」，不是「**本会话**」。header 完全由容器构造，所以一个容器只要知道同一用户另一个蓝图会话的 subagent `session_id`（UUID），就能读写那条会话的总线——而当那条会话的 `conversation` 未绑项目时 `_aresolve_blueprint_project_id` 返回 None，成员闸被整段跳过（`:4118` 的 `if project_id is not None`），道②又只校验 `process_type`，于是三道全过。这与本相位自述的不变量「只能读写本会话总线」不符。

关键在于：**`:4085-4091` 的注释与 113-CONTEXT 的调研前提「不存在 `token → session`」是错的。** `AccessToken` 有 `session_id` 列，`mint_task_token` 就是按它写入并按它吊销的：

```45:53:server/access_tokens/services.py
    await AccessToken.objects.acreate(
        name=f"task:{session_id}",
        ...
        kind="task",
        session_id=session_id,
```

而 `AccessTokenAuthentication` 返回 `(token.created_by, token)`，`request.auth` 就是那个 `AccessToken`（`mcp_tools/views.py:262` 已在读 `request.auth`）。所以绑定链是现成的，只是没被用上。

**建议修法：** 在道①之前加一道「header 必须等于本 token 自己的 session」，让 header 退化为纯冗余字段：

```python
auth = getattr(request, "auth", None)
if str(getattr(auth, "kind", "")) == "task":
    bound = str(getattr(auth, "session_id", "") or "")
    if not bound or bound != raw_session_id:
        return None, None, "session_not_owned"   # header 与 token 绑定的会话不一致
```

同时把 `:4085-4091` 的注释与 CONTEXT 的「不存在 token → session」订正掉，否则后续相位会继续沿用这个错误前提。补一条负向断言：用 A 会话的 token + B 会话的 header → 403。

---

### MJ-02：互等环命中时 `RepoResearchTask` 停在非终态，人裁决后该仓**永远无法重派**

**文件：** `server/subagent/api/callbacks.py:2461-2466`（`_ahandle_blueprint_waiting_context`）

**问题：**

长等待退出的两条分支不对称——只有非成环分支把 task 落终态：

```2461:2466:server/subagent/api/callbacks.py
    if not cycle_detected:
        research_service = ResearchService()
        await research_service.mark_failed(
            task, {"reason": "waiting_context", "detail": reason}
        )
        await research_service.mark_stale([task.id])
```

成环分支什么都不做，task 停在 `RUNNING`（`_aload_blueprint_plan_task` 已排除 DONE/FAILED/STALE，所以此处必为 PENDING/RUNNING）。而 `mark_stale` 按 WR-01 **只动终态 task**：

```217:225:server/delivery/services/research_service.py
        # WR-01：只对已终态（done/failed）的 affected 任务置 stale 重跑，跳过在途
        terminal_ids = list(
            RepoResearchTask.objects.filter(
                id__in=task_ids,
                status__in=[
                    RepoResearchTaskStatus.DONE,
                    RepoResearchTaskStatus.FAILED,
                ],
```

于是人裁决完澄清、续驱重进 `_h_bp_repo_plan` 后：`_adispatch_direct_plan` 见 task 非 PENDING/STALE → 调 `mark_stale` → 被 WR-01 跳过 → task 仍 `RUNNING` → 派发面的 DISPATCHABLE 白名单（pending/stale）跳过该仓 → `dispatched=0`。同时 `_abp_repo_plan_is_stuck` 因 `aall_research_tasks_terminal` 为 False（这条 RUNNING task）判定「有在途容器」→ 返回 False → event 落 `plan_dispatched` → self-loop 挂 `waiting_event`。**容器早已退出、澄清已关闭、没有任何回调会再来**，会话就此静默悬挂，且无阻塞线程可让用户看出问题。只能改库恢复。

这是 SC-2 第三条路径（互等环）**裁决之后**的续作面。VERIFICATION 对该路径的断言是 `cycle_detected is True` 且**不 dispatch**——它只验到了"停下来"，没验"还能不能起来"，所以照不到这一条。

**建议修法：** 成环分支同样把 task 落终态，只是不重派：

```python
    research_service = ResearchService()
    reason_code = "waiting_context_cycle" if cycle_detected else "waiting_context"
    await research_service.mark_failed(task, {"reason": reason_code, "detail": reason})
    # 成环时也置 stale：裁决后要能被重派；重派由 `_h_bp_repo_plan` 的波次门控决定何时发生，
    # 而不是靠让 task 卡在 RUNNING 来"物理阻止"重派。
    await research_service.mark_stale([task.id])
```

若确实要在裁决前阻止重派，应当用显式的门控（如 waiter 仍 active / 有 open blocking 线程时波次不推进），而不是把它编码成一个非终态的 task。补一条断言：成环退出后 task 为 STALE，且澄清关闭后 `dispatch_plans` 能重派该仓。

---

### MJ-03：全员长等待时 `expire_waiters` 不可达 —— 超时兜底挂在只能由容器回调驱动的 barrier 上

**文件：** `server/services/process_runtime/builtin_processes.py:591-664`（`_h_bp_repo_plan`），`server/subagent/api/callbacks.py:2519`（`_handle_blueprint_repo_plan_completion` 的早退），`server/services/process_runtime/blueprint_repo_plan.py:476`（`aexpire_stale_waiters`）

**问题：**

超龄 waiter 的清理**唯一**挂载点在 `_h_bp_repo_plan` 内：

```server/services/process_runtime/builtin_processes.py
    try:
        expired = await adapter.aexpire_stale_waiters(session)
        if expired:
            await adapter.aredispatch_waiting_repos(session, expired)
```

而 `_h_bp_repo_plan` 只能由 engine advance 驱动，engine advance 在本链**只有两个触发源**：`callbacks.py:2170` / `:2389` 的 `aresume_blueprint_session`（全部在容器回调里）。同时 `_ahandle_blueprint_waiting_context` 返回 True 后，调用方**直接 return，跳过 `_trigger_blueprint_repo_plan_barrier`**（有意为之：该仓未完成，barrier 判据仍为假）。

于是存在一条闭合的死路：当**当前波次的全部容器都以 `waiting_context` 退出**（互相等对方、或等一个永不出现的 key，正是 `await` 兜的场景），所有容器已退出 ⇒ 不会再有回调 ⇒ 不会再 advance ⇒ `expire_waiters` 永不执行 ⇒ 会话永久停在 `waiting_event`，无澄清线程、无失败、无用户可见信号。CONTEXT 锁定的「超时清理挂在 barrier 续驱路径上（不新起定时任务）」这条决策本身没错，但实现让 barrier 在最需要它的那个状态下恰好不可达。

**建议修法（二选一，均不新起定时任务）：**

1. **在 `waiting_context` 分支保留一次续驱**——把 waiter 登记完后仍调一次 barrier，并把 barrier 的判据从「`aall_repo_plans_ready`」放宽为「ready **或** 无在途容器」：无在途容器时 advance 一次，正好让 `_h_bp_repo_plan` 跑到 `aexpire_stale_waiters` 并由 `_abp_repo_plan_is_stuck` 兜出澄清线程。
2. 或在 `_ahandle_blueprint_waiting_context` 内检测「本会话所有锁定仓的 task 均已非在途且均有 active waiter」时，直接 `_abp_ensure_blocking_clarification`（stage=`repo_plan`，reason=`all_repos_waiting`）——让死锁至少**可见**。

优先做 1（能自愈），把 2 作为兜底。补一条断言：两仓都以 `waiting_context` 退出且 key 永不出现时，会话最终落到 open blocking 线程而非无声悬挂。

---

### MJ-04：对账结论上界 50 会**静默丢弃** `gaps`，超出部分的契约既不标 `needs_support` 也不抛澄清

**文件：** `server/services/process_runtime/blueprint_reconcile.py:37`、`:330-333`（`_append`），消费侧 `server/services/process_runtime/blueprint_merge.py:1646-1654`

**问题：**

```330:333:server/services/process_runtime/blueprint_reconcile.py
def _append(bucket: list[dict], entry: dict) -> None:
    """有界追加（超出 :data:`_MAX_FINDINGS` 静默丢弃：结论已足够开澄清）。"""
    if len(bucket) < _MAX_FINDINGS:
        bucket.append(entry)
```

注释的理由「结论已足够开澄清」对 `conflicts` / `missing_support_repos` 成立（这两桶只要非空就开阻塞澄清，丢弃只影响问题文本的详尽度）。但对 `gaps` **不成立**——`gaps` 不开澄清，它是 `_apply_needs_support` 的**逐条驱动源**：

```1646:1654:server/services/process_runtime/blueprint_merge.py
        report = reconcile_cross_repo_apis(assembled)
        applied = _apply_needs_support(
            assembled[SECTION_API_CONTRACTS], report["gaps"], _support_hints(repo_plans)
        )
```

第 51 条及以后的「consumed 找不到 provider」契约因此**不会**被标 `data_source.availability = needs_support`，也不会进 `missing_support_repos`（那道检查只对已标 needs_support 的条目生效），最终原样落进 `ArtifactVersion` —— 114/115 按 schema 读到的是「可用性未标注」，等价于默认可用。这正是 FLOW-06 明令禁止的「静默拍板」，且它在契约多的真实项目里（`api_contracts` 上界是 200）很容易触发。

**建议修法：** 把「上报上界」与「处置完整性」解耦——`gaps` 按全量返回给调用方（或至少让 `_apply_needs_support` 拿到全量），只在**进澄清问题文本 / 日志**时截断；同时在 `reconcile_cross_repo_apis` 的返回里补一个 `truncated: bool` 让调用方知道自己拿到的不是全量：

```python
_MAX_FINDINGS = 50            # 仅用于 conflicts / missing_support_repos 的 HITL 文本
_MAX_GAPS = 200               # 与 api_contracts 的 _MAX_LIST_ITEMS 对齐，保证逐条可处置
```

若坚持统一上界，则必须在截断发生时把 `truncated` 升级为一条阻塞澄清（「契约缺 provider 的条目超过可自动处置上界」），绝不能落版本。补一条断言：51+ 条 gap 时，第 51 条契约也带 `data_source.availability == "needs_support"`（或整轮不落版本）。

---

## MINOR

### MN-01：`await_blueprint_context` 无法区分「对方还没写」与「配额耗尽 / 老服务端 404 / 401」，一律回 `reason="timeout"` 诱导 agent 记下错误假设

**文件：** `task/core/blueprint_context_wait.py:141-147`、`:180-187`

```141:147:task/core/blueprint_context_wait.py
        except Exception:  # noqa: BLE001 — 单轮读失败当未命中继续等（handler 本已 return-not-raise）
            raw = {}
        # 带工具错误标记的返回体（HTTP 非 200 / 解析失败 / 401）→ 本轮未命中，**不中断等待**：
        # 服务端瞬时不可用不应让长依赖直接降级。
        body = {} if (isinstance(raw, dict) and raw.get("is_error")) else _parse_handler_body(raw)
```

「瞬时不可用不中断等待」是对的，但**持续**不可用被折叠进了同一个出口：知识配额耗尽（工厂的 `quota_counter` 打满后每轮都回 `is_error`）、老服务端未部署这两条 path（每轮 404）、token 过期（每轮 401）三种情况，都会把整个 deadline 空转到底（默认 3 分钟 = 36 轮，最长 5 分钟 = 60 轮，每轮仍计一次配额），然后返回 `reason="timeout"`。而 `timeout` 的语义已在工具描述里写死为「请记录假设并继续」，于是 agent 会把「我读不到总线」记成「B 仓没有发布契约」——一个错误的技术结论会被写进 RepoPlan 并一路进融合。约束 ④ 只覆盖了 `read_handler is None`（整个知识 MCP 未挂），覆盖不到 handler 在但上游一直失败。

**建议修法：** 统计连续 `is_error` 轮数，超阈值就带**正确的 reason** 提前返回（仍不带 `is_error`，不破坏约束 ②）：

```python
consecutive_errors = 0
...
if isinstance(raw, dict) and raw.get("is_error"):
    consecutive_errors += 1
    if consecutive_errors >= 3:
        return {"hit": False, "reason": "tool_error", "waited_ms": …, "polls": polls, "max_seq": last_seq}
else:
    consecutive_errors = 0
```

并在工具 description 里把 `reason` 的三个值（`timeout` / `tool_error` / `tool_unavailable`）与各自的降级动作分开写明。

---

### MN-02：`_redact_json` / `_truncate_content` 递归无深度上界，深嵌套 content 触发 `RecursionError` 后被折叠成不可归因的 `internal_error`

**文件：** `server/delivery/services/blueprint_context_service.py:69-108`

`content` 是容器上报的半可信 JSON（`serializers.ReportBlueprintContextRequestSerializer` 只要求它是 dict，无深度/体积限制），`_redact_json` 的 dict/list 分支与 `_truncate_content` 的 `json.dumps` 都是无界递归。嵌套深度接近解释器上限时抛 `RecursionError`（属 `Exception`），被 view 的兜底 `except` 吞成 `{"applied": False, "reason": "internal_error"}`：写入方拿不到可归因的原因，`_MAX_CONTENT_BYTES` 这道体积闸也压根没执行到。这条不构成 DoS（单请求、有兜底、返 200），但它让「脱敏 fail-closed」这条安全边界在极端输入下变成「整条写入 fail-silent」。

**建议修法：** 给 `_redact_json` 加 `depth` 参数，超界回落截断标记（与 `_truncate_content` 同一口径），并在 serializer 侧对 `content` 加一次深度/序列化体积预检，让拒绝发生在 4xx 而不是兜底 200：

```python
_MAX_CONTENT_DEPTH = 32

def _redact_json(value: Any, *, depth: int = 0) -> Any:
    if depth > _MAX_CONTENT_DEPTH:
        return {"_truncated": True, "_reason": "too_deep"}
```

---

### MN-03：`_normalize_api_contracts` 漏掉另两段都做的 `assoc_ids` 过滤，非关联仓的契约仍落蓝图

**文件：** `server/services/process_runtime/blueprint_merge.py:1136-1139`

`_normalize_implementation_overview`（`:967`，`if repository_id not in inputs.assoc_ids: continue`）与 `current_state`（`:1594-1598` 的列表推导）都按 `repo_associations` 过滤，只有 API 段没有：

```1136:1139:server/services/process_runtime/blueprint_merge.py
    for repository_id in sorted(str(rid) for rid in (inputs.repo_plans or {})):
        section = (inputs.repo_plans or {}).get(repository_id)
        if not isinstance(section, dict):
            continue
```

`blueprint_schema` 的后置检查 (c) 只覆盖 `items` 与 `current_state_analysis`（`blueprint_schema.py:848-876`），不覆盖 `api_contracts`，所以确认门之后被移除的仓（`_normalize_locked_repos` 会因 `removed is True` 剔除它，但它的旧 `PartialPlan.repo_plan` 仍在）留下的契约会带着一个不在 `repo_associations` 里的 `repository_id` 过门落版本，并经 `_api_key_links` 进 `must_haves.key_links`，形成悬空仓引用。

**建议修法：** 与另两段对齐，在循环首行加一句 `if repository_id not in inputs.assoc_ids: continue`。

---

### MN-04：`derive_must_haves` 对缺 `path` 的 dict 型 `files_touched` 产出字面量路径 `"None"`

**文件：** `server/services/process_runtime/blueprint_merge.py:638`

```638:641:server/services/process_runtime/blueprint_merge.py
            path = str(entry.get("path") if isinstance(entry, dict) else entry or "").strip()
            if not path or path in artifacts:
                continue
            artifacts[path] = {"path": path, "provides": provides}
```

`entry` 是 dict 但没有 `path` 键时 `entry.get("path")` 为 None，`str(None)` == `"None"`，非空且不被 `if not path` 拦住，于是产出 `{"path": "None", "provides": …}`。生产链路上 `_project_files_touched`（`:1097` 会跳过空 path）保证了不会走到这一支，但 `derive_must_haves` 是 `__all__` 导出的公开纯函数，其 docstring 承诺「确定性派生」，这条使它在任何未经 `_project_files_touched` 归一的输入上产出垃圾锚点。

**建议修法：** `path = str((entry.get("path") if isinstance(entry, dict) else entry) or "").strip()`（把 `or ""` 移到条件表达式**外面**，让 None 归一为空串）。

---

### MN-05：`BlueprintContextService._open_cycle_clarification` 缺幂等闸，可叠开多条阻塞澄清线程

**文件：** `server/delivery/services/blueprint_context_service.py:659-709`

同相位的兄弟实现 `blueprint_repo_plan._aopen_cycle_clarification`（`:361`）先查 `_acount_open_blocking_clarifications(artifact.id)`，有 open blocking 就不叠开；service 侧这一份**没有**这道检查。`register_waiter` 会在每次登记时重跑环检测（`:445`），而成环时只把**自己这一条** waiter 置 `superseded`（`:455`），对侧的 waiter 仍 active，所以同一个环在下一次 `register_waiter` 时会再次命中并再开一条线程。多容器并行退出时 HITL 面板会被同一个环刷成多条。

**建议修法：** 与兄弟实现对齐，在 `open_thread` 之前加一次「该 artifact 已有 OPEN blocking 线程则返回空串」的幂等闸（`BlueprintThread.objects.filter(artifact_id=…, blocking=True, status=OPEN).aexists()`）。

---

### MN-06：`_abp_mark_drafting` 在阻塞线程探测**之前**执行，会把 `needs_clarification` 展示态回刷成 `drafting`

**文件：** `server/services/process_runtime/builtin_processes.py:611`、`:697`

两个 handler 都在入口无条件 `await _abp_mark_drafting(session)`，而 `_h_bp_repo_plan` 的阻塞线程探测在其后（`if await _abp_has_open_blocking_threads(session): event = "needs_clarification"`）。于是「有 open+blocking 线程」的会话每次进 handler 都会先被转成 `drafting`，再返回 `needs_clarification` 事件——展示态与实际语义在两次 `_amap_blueprint_status` 之间是矛盾的（用户看到"起草中"，实际在等他回答）。

**建议修法：** 把探测提到 `_abp_mark_drafting` 之前，仅在**将要真正推进**时才 mark：

```python
blocked = await _abp_has_open_blocking_threads(session)
if not blocked:
    await _abp_mark_drafting(session)
```

---

### MN-07：`_h_bp_repo_plan` 在 `deps.repo_plan` 缺失时返回 self-loop 事件，与 `_h_bp_merge` 明文论证过的取舍相反

**文件：** `server/services/process_runtime/builtin_processes.py:607-609`

```607:609:server/services/process_runtime/builtin_processes.py
    adapter = getattr(getattr(engine, "deps", None), "repo_plan", None)
    if adapter is None:
        return StageOutcome(event="plan_dispatched")
```

`_h_bp_merge` 的 docstring（D-W4）逐条论证了为什么依赖缺失时**不能**返回本 stage 的良性推进事件（自旋 / 假装成功），最终选了 `needs_clarification`。repo_plan 这一支走的恰是被否掉的形态：`plan_dispatched` → self-loop 到 `repo_plan` 且 `wait_status="waiting_event"`，但**没有任何容器被派出**，也没有阻塞线程，会话静默挂在等事件态。虽有 `test_repo_plan_handler_passes_through_without_deps` 背书，但它锁定的是这个有问题的形状本身。

**建议修法：** 与 merge 对齐——`await _abp_ensure_blocking_clarification(session, stage="repo_plan", reason="deps_unavailable")` 后返回 `needs_clarification`，并同步更新那条守护测试的期望。

---

### MN-08：`redispatched` 出现在真实响应体但不在 `TOOL_SCHEMA_SNAPSHOT` 声明的契约里

**文件：** `server/mcp_tools/serializers.py:938-941`（snapshot）vs `server/mcp_tools/views.py:4331-4338`（响应体）

snapshot 声明 `report_blueprint_context` 的响应键为 `["applied", "reason", "entry_id", "seq", "satisfied_waiters", "run_id"]`，而 113-04 在响应里追加了 `redispatched` 却没同步 snapshot。`test_schema_snapshot.py` 只做「snapshot 与测试内字面量相等」和「snapshot 键集 == 注册路由集」两条断言，**不比对 view 的真实响应键**，所以这条漂移不会被任何测试逮住。snapshot 是给容器侧/外部客户端看的已发布契约，漂移会让消费方以为该键不存在。

**建议修法：** snapshot 补上 `redispatched`（并同步 `test_schema_snapshot.py` 的字面量）；更根本的做法是加一条「view 响应键 ⊆ snapshot 声明键」的守卫断言，让这类漂移在源头被拦。

---

### MN-09：`_acount_blueprint_plan_containers` 把长等待重派的容器计入 schema 无效重试预算

**文件：** `server/subagent/api/callbacks.py:2521`，计数源 `:2374-2381`

```2521:2521:server/subagent/api/callbacks.py
        attempt = max(0, await _acount_blueprint_plan_containers(task) - 1)
```

计数口径是「本 task 起过的 `bp-plan-*` 容器总数」，它把 `aredispatch_waiting_repos` 因 waiter 被满足而起的续作容器也算进去。于是一个正常参与了两轮跨仓协商（两次 `waiting_context` 退出 + 两次重派）的仓，只要**首次**产出 schema 不合格就直接判超界 → `mark_failed` + 开澄清，完全没用上 `MAX_REPO_PLAN_ATTEMPTS` 允许的重试。docstring 已解释为何不用 `RepoResearchTask.attempt`（跨阶段共用）与 `stage_state`（lost-update），但容器计数同样不是「校验失败次数」的正确代理。

**建议修法：** 让重派容器带上可区分的 `session_id` 前缀（如 `bp-plan-{hex}-r*` 用于 redispatch），计数时只数非重派前缀；或在 `last_output` 里显式携带 `plan_attempt` 由派发侧递增（派发侧是服务端单点，不存在 lost-update）。

---

### MN-10：`_layer` 把成环仓的依赖边整段剔除，导致「依赖环的下游仓」被排到环之前

**文件：** `server/services/process_runtime/blueprint_repo_waves.py:178-181`

```178:181:server/services/process_runtime/blueprint_repo_waves.py
    remaining = [rid for rid in nodes if rid not in cyclic]
    pending = {
        rid: {p for p in providers_of.get(rid, set()) if p not in cyclic} for rid in remaining
    }
```

成环仓统一挂最后一波（`:198-200`，不丢仓，正确），但**依赖它们的非环仓**因为依赖被过滤掉而落到了 wave 1——顺序恰好反了：D 依赖环中的 A，D 却先被派发，开工时 A 的契约必然不在总线上，只能退化成 `await` 或长等待退出。这不影响正确性（有 `await` 兜底、且成环本身已抛澄清），但它让第一道防线在这条分支上失效，并直接放大 MJ-03 的触发概率。

**建议修法：** 分层时保留成环依赖但把整个环视作一个"超级节点"排在其全部下游之前（先按 SCC 缩点再 Kahn），或简单起见把「依赖任一成环仓的仓」也一并推到成环波次之后。

---

## 冻结纪律复核（`git diff 0ce64322..HEAD`）

| # | 项 | 结论 |
|---|---|---|
| 1 | 11 项冻结面零改动 | ✓ `repo_router_v2` / `decompose_segments` / `research_adapter` / `architect_merge_adapter` / `merged_plan` / `clarify_adapter` / `render` / `resume` / `charter_service` / `blueprint_schema` / `blueprint_quality` —— `--numstat` **逐个零输出** |
| 2 | `task/core/knowledge_tools.py` 公共 handler 工厂零改动 | ✓ `+171/-0` 纯追加；diff 内 `timeout=` / `quota_counter` / `callback` 的命中**仅一条禁令注释**（`:134`），工厂本体与 `timeout=60.0`、计数逻辑一字未动，未加 callback 参数。`_attach_await_handler` 走「替换 `SdkMcpTool.handler`」而非改工厂，方向正确 |
| 3 | `_TECHNICAL_PLAN_STAGES` / `_ECHO_STAGES` 零改动 | ✓ `builtin_processes.py` 的 `-U0` diff 中两个符号**零命中**；该文件总删除行 = **3**，全是 `"confirmed": STAGE_DONE` 及其 2 行 113 接续点注释（即蓝图链自己的接续点） |
| 4 | `blueprint_resume` 删除行 ≤8 且全在 `_amap_blueprint_status` | ✓ `+38/-4`；4 行删除 = 2 行 docstring 措辞 + `target = …RESEARCHING` + `return_status=…RESEARCHING`，**全部落在 `_amap_blueprint_status` 内**。`_resolve_stage_status` 为纯追加，`aresume_blueprint_session` 签名与分支语义未动 |

**共享面修复复核（VERIFICATION 已判无回归，本轮只看方向）：** `engine.py:108-119` 的条件透传是正确的最小修法——`StageOutcome.current_artifact_version` 默认 None 而 service 用 `_UNSET` 哨兵，无条件透传确实等于每步清指针；改为「仅在非 None 时传」使 `_UNSET` 语义生效，未引入新分支。**无隐藏行为变更。**

**观测规范抽查：** 新增事件全部带 `category`（读写 `sampling` / waiter 与容器动作 `caller`）与 `component`，关键生命周期带 `duration_ms`，`initiated_by_user_id` 贯穿到 waiter 行与事件 payload。`except Exception` 的宽度都配了 `# noqa: BLE001` + 理由注释，且落在 best-effort 边界（事件留痕 / 状态映射 / distill / 重派 / 归因），未见吞掉主链错误的用法——**唯一例外见 MN-02**（兜底 except 把 `RecursionError` 折叠成不可归因的 `internal_error`）。

**INV-6 收口：** 全仓 grep `BlueprintContextEntry.objects` 的写操作（`create` / `update`），命中全部在 `blueprint_context_service.py` 内；view / callbacks / adapter 侧只经 service 公开方法。**未发现绕过 `BlueprintContextService` 直写总线的路径。**

**`sync_to_async` 抽查：** `_append_entry_locked` / `_satisfy_waiters_locked` / `_expire_waiters_locked` 把 `transaction.atomic()` 完整包在被装饰的同步函数**内部**（而非跨 await 边界），事务边界正确；`select_for_update` 均在 atomic 内。`_fetch_subagent_session` 的 `select_related("main_session")` 在同步上下文一次取回，避免 async lazy-FK。默认 `thread_sensitive=True` 与 Django 的连接/事务语义一致，未见误用。

---

_Reviewed: 2026-07-30_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_

---

## Fix Log

**修复于：** 2026-07-30 · 分支 `milestone/v0.20.0-blueprint`
**结论：14 fixed / 1 skipped。** CRITICAL 与全部 MAJOR 已修；MINOR 修 9 条、跳 1 条（MN-09，理由见下）。

> **计数订正：** 正文实际列出 **10** 条 MINOR（MN-01…MN-10），文首摘要的「9 MINOR」少计了一条；
> 全篇 finding 总数为 **15**（1 + 4 + 10），本 Fix Log 按正文逐条收口。

### CRITICAL

| ID | 结论 | commit | 说明 |
|---|---|---|---|
| CR-01 | **fixed** | `45759e8c` | 总线写入的仓归属改服务端权威推导：`repository_id` 一律覆写为反查值、跨仓 `repo:` 前缀 key 拒绝（fail-closed，反查不到即拒 `repo:` 写入），补跨仓伪造负向断言 |

### MAJOR

| ID | 结论 | commit | 说明 |
|---|---|---|---|
| MJ-01 | **fixed** | `021c80bf` | 会话寻址改用 token 自带 `session_id` 作权威，`X-Friday-Session-Id` header 退化为冗余字段（不一致即 403）；同步订正「不存在 token → session」的错误前提注释 |
| MJ-02 | **fixed** | `09a3751d` | 成环分支与非成环分支对称落终态：`mark_failed(reason="waiting_context_cycle")` + `mark_stale`，裁决后该仓可重派；「裁决前不重派」改由显式门控承担，不再靠 task 卡在 RUNNING 物理阻止 |
| MJ-03 | **fixed** | `09a3751d` | 超龄清理 + 死锁探测增设**可达**挂载点 `callbacks._amaintain_blueprint_waiters`（容器退出瞬间执行）：全波容器都以 `waiting_context` 退出时，先试超龄清理重派（自愈），无仓可清且判定死锁则开 blocking 澄清（可见）。未新起定时任务 |
| MJ-04 | **fixed** | `4160815d` | `gaps` 上界与 `api_contracts` 的 `_MAX_LIST_ITEMS` 对齐，`_apply_needs_support` 拿到全量、逐条可处置；截断只作用于 HITL 文本，杜绝 `needs_support` 被静默丢弃后原样落版本 |

### MINOR

| ID | 结论 | commit | 说明 |
|---|---|---|---|
| MN-01 | **fixed** | `977ba36e` | 连续 3 轮读失败（配额耗尽 / 401 / 404）提前返回 `reason="tool_error"`，不再空转到 deadline 再回 `timeout`；仍不带 `is_error`（约束 ②）。工具 description 按 `timeout` / `tool_error` / `tool_unavailable` 三值分开写降级动作。公共 handler 工厂零改动 |
| MN-02 | **fixed** | `668f2ae9` | `_redact_json` 加 `depth` 上界（32）超界回落截断标记；`_truncate_content` 的 `json.dumps` 递归失败按「超限」处理，不再让 `RecursionError` 被折叠成不可归因的 `internal_error` |
| MN-03 | **fixed** | `668f2ae9` | `_normalize_api_contracts` 补 `assoc_ids` 过滤，与 `_normalize_implementation_overview` / `current_state` 对齐，杜绝悬空 `repository_id` 契约过门落版本 |
| MN-04 | **fixed** | `668f2ae9` | `derive_must_haves` 把 `or ""` 移到条件表达式外，缺 `path` 键的 dict 归一为空串，不再产出字面量路径 `"None"` |
| MN-05 | **fixed** | `668f2ae9` | `_open_cycle_clarification` 补幂等闸（该 artifact 已有 OPEN blocking 线程则不叠开），与兄弟实现 `blueprint_repo_plan._aopen_cycle_clarification` 同口径 |
| MN-06 | **fixed** | `09a3751d` | 阻塞线程探测提到 `_abp_mark_drafting` 之前：有 open+blocking 线程时整轮不 mark drafting、不派发，展示态不再与 `needs_clarification` 语义矛盾 |
| MN-07 | **fixed** | `09a3751d` | `deps.repo_plan` 缺失时与 `_h_bp_merge`（D-W4）对齐：先 `_abp_ensure_blocking_clarification` 再返 `needs_clarification`，不再用 `plan_dispatched` self-loop 静默悬挂；同步更新守护测试期望 |
| MN-08 | **fixed** | `668f2ae9` | `TOOL_SCHEMA_SNAPSHOT` 补 `redispatched`，并加「view 响应键 ⊆ snapshot 声明键」守卫，让这类契约漂移在源头被拦 |
| MN-09 | **skipped** | — | **两条建议修法都撞硬约束，不在 MINOR 的风险预算内。** ① 「重派容器带可区分 `session_id` 前缀」要改 `blueprint_research_adapter.py:459` 的 `bp-plan` 前缀生成——该文件属本相位 11 项冻结面（零改动）；② 「`last_output` 里带 `plan_attempt` 由派发侧递增」会把重试预算的判据从「服务端生成、runner 不可篡改的 `session_id` 前缀计数」换成 runner 可经 progress 回调篡改的字段（本仓多处注释明确点名 `last_output` 不可信），是**安全性倒退**——容器可借此获得无界重试。现状影响有界：已参与跨仓协商的仓在首次 schema 不合格时被判超界 → `mark_failed` + 开 blocking 澄清，**不静默降级、人可见可续**。正解需要一张服务端权威的「校验失败次数」承载（如 `RepoResearchTask` 加列或独立计数表），应作为独立小相位处理 |
| MN-10 | **fixed** | `7cee8db4` | `_layer` 改按 SCC 缩点思路分三段（环的上游 → 环整体一波 → 环的传递下游），依赖环的下游仓不再被排到环之前；补上游 / 直接下游 / 传递下游三条断言 |

### 相位门

`server`: `pytest tests/services/process_runtime/ tests/delivery/ tests/mcp_tools/ tests/subagent/ tests/repositories/`
→ **1767 passed / 2 skipped / 1 failed（已登记忽略项）**，159s。

- 唯一 failure：`tests/mcp_tools/test_skills_snapshot_guard.py::test_skill_files_discovered` —— `skills/` 子模块未初始化，与本轮改动无关（登记在册）。
- `test_threaded_concurrent_appends_*` 本轮**未复现** flake。

`task`: `pytest tests/test_blueprint_context_wait.py tests/test_knowledge_tools.py tests/test_blueprint_context_tools_schema.py` → **49 passed**（含工厂零改动守护三条）。

### 冻结纪律（本轮新增两 commit 复核）

- 11 项冻结面零改动 —— 本轮只触 `task/core/blueprint_context_wait.py`、`task/core/knowledge_tools.py`（仅 await 工具 **description** 文案，`_make_knowledge_handler` 工厂本体 / `timeout=60.0` / `quota_counter` / 无 callback 参数一字未动，守护测试三条绿）、`server/services/process_runtime/blueprint_repo_waves.py` 及各自测试。
- `_TECHNICAL_PLAN_STAGES` / `_ECHO_STAGES` 零触碰；`blueprint_resume.py` 本轮零改动。
- 提交前对改动文件跑过 `uv run ruff format` + `uv run ruff check --fix`（均 clean）。

_Fixed: 2026-07-30_
_Fixer: Claude (gsd-code-fixer)_
