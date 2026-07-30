---
phase: 113-2
plan: 02
requirements: [BUS-01]
provides:
  - "MCP 工具 `POST /api/mcp/tools/read_blueprint_context/`（url name `mcp-tool-read-blueprint-context`）：入参全可选 `key_prefix`(≤200) / `kind`(六值枚举，可空串) / `repository_id`(≤64) / `since_seq`(≥0，默认 0) / `limit`(1..200，默认 50)；200 返回 `{entries: list[dict], count: int, max_seq: int, run_id: str}`，`entries` 元素形状即 `BlueprintContextService.read_entries` 的 dict（id/key/kind/repository_id/content/produced_by/seq/status/created_at）"
  - "MCP 工具 `POST /api/mcp/tools/report_blueprint_context/`（url name `mcp-tool-report-blueprint-context`）：入参 `key`(必填,≤200) / `kind`(必填,六值) / `repository_id`(可选,≤64) / `content`(必填，**必须是 JSON 对象**)；200 返回 `{applied: true, entry_id: str, seq: int, satisfied_waiters: int, run_id: str}`"
  - "⭐ **两个工具的请求体都不含任何会话字段**：目标会话唯一来自 `X-Friday-Session-Id` 头 → 无跨会话入参面（第三道校验的结构性成立方式）。`TOOL_SCHEMA_SNAPSHOT` 与 `test_schema_snapshot.py` 双向锁死该形状，将来给这两个工具加 session 入参会直接红"
  - "四个会话校验错误码与 HTTP 映射（信封 `{error_code, detail}`）：`session_not_owned` / `not_member` / `not_blueprint_session` → **403**；`missing_session_header` / `session_not_found` → **404**。全路径无 5xx；内部异常兜底 read→`200 {entries:[],count:0,max_seq:since_seq,error:'internal_error'}`、report→`200 {applied:false,reason:'internal_error'}`"
  - "`_aresolve_blueprint_session(request) -> (convergence_session, subagent_session, error_code)`（`server/mcp_tools/views.py` 模块级 async）。解析路径与**实测真实字段名**：`request.headers['X-Friday-Session-Id']` → `SubAgentSession.objects.select_related('main_session').filter(session_id=...)` → `sub.main_session.user_id == request.user.id`（**None 亦拒**）→ `sub.last_output['blueprint_session_id']` → `ConvergenceSession.process_type == 'technical_blueprint'` → 项目成员闸"
  - "配套 helper（113-04 可直接复用）：`_fetch_subagent_session(raw_session_id)` / `_fetch_convergence_session(session_id)`（脏 UUID 当不存在，不抛）/ `_aresolve_blueprint_project_id(session)`（`conversation_id → Conversation.bound_project_id`，反查不到返回 None = 未绑项目不叠加成员闸）/ `_aassert_blueprint_project_access(project_id, user)`（成员 **或** `public_org`）/ `_blueprint_session_error(error_code)`（渲染 4xx 信封）"
  - "`task/core/knowledge_tools.py` 的 `KNOWLEDGE_TOOL_SCHEMAS` **现为 9 项**（7 legacy + read_/report_blueprint_context），`knowledge_allowed_tools()` 同步 9 条；`_make_knowledge_handler` 签名 / `timeout=60.0` / `quota_counter` 计数 / `build_knowledge_mcp_server` / `knowledge_allowed_tools` **一行未改**（`git diff | rg '^-'` 为空）"
  - "report 响应的 `satisfied_waiters` = `BlueprintContextService.satisfy_waiters()` 返回的待重派仓 id 清单长度。**重派接续点**注释在 `server/mcp_tools/views.py` 的 `ReportBlueprintContextView._handle` 内、`redispatch = await service.satisfy_waiters(...)` 调用**上方**三行注释处（含 `aredispatch_waiting_repos` 字面量），113-04 在该处纯追加一次调用即可接上"
affects:
  - "113-04（等待原语与重派）：`await_blueprint_context` 作为第 10 个白名单表项追加即自动可达 `/api/mcp/tools/await_blueprint_context/`（URL 由 tool_name 拼接）；重派在 `ReportBlueprintContextView._handle` 的接续点纯追加；`_aresolve_blueprint_session` 可直接复用做同款三道校验"
  - "113-03（派发面）：`AgentSession.user = dispatch_user` 是归属校验（道①）的**唯一**数据来源；未写入时本 plan 一律判 `session_not_owned` 403（fail-closed），即蓝图容器将完全无法读写总线 —— 113-03 落地前该链路不通是**设计预期**，不是回归"
  - "113-06（distill）：条目经本工具写入时 `produced_by = SubAgentSession.session_id`、`initiated_by_user_id = str(token owner id)`，`project_id` 未传（保持可空，不伪造归属）"
key-files:
  created:
    - server/tests/mcp_tools/test_blueprint_context_tools.py
    - task/tests/test_blueprint_context_tools_schema.py
  modified:
    - server/mcp_tools/serializers.py
    - server/mcp_tools/views.py
    - server/mcp_tools/urls.py
    - server/tests/mcp_tools/test_schema_snapshot.py
    - task/core/knowledge_tools.py
    - task/tests/test_knowledge_tools.py
    - task/tests/test_claude_sdk_integration.py
completed: 2026-07-30
---

# Phase 113-2 Plan 02: Context Bus 容器 MCP 两侧接通 Summary

**一行结论**：服务端新增 `read_blueprint_context` / `report_blueprint_context` 两个 `McpToolView` 子类，跨会话越权的唯一防线 `_aresolve_blueprint_session` 三道 fail-closed 校验在 view 层自建落地（归属含 `user_id is None` 一并拒绝、`process_type` 必须是 `technical_blueprint`、成员或 `public_org`），全路径 4xx/200 无 5xx 且读写一律经 `BlueprintContextService`（view 零裸 ORM）；容器侧 `KNOWLEDGE_TOOL_SCHEMAS` 纯追加两项（7 → 9）而公共 handler 工厂一行未改；20 例服务端端到端 + 6 例容器侧守护测试全绿，**三道校验的 403 断言经变异验证真能触发**（分别去掉三道校验，对应用例立刻失败）。

## Accomplishments

- **三道会话校验（T-113-07，本 plan 的安全核心）**：`_aresolve_blueprint_session` 返回 `(cs, sub, error_code)` 三元组，任一道不过时 `cs` 恒为 None。道①归属经 `select_related("main_session")` 在同步上下文一次取回后读 `user_id` 标量（绝不在 async 触发 lazy-FK）；**`user_id` 为 None 一律判 `session_not_owned`**，不把「字段为空」当放行条件。道②在 `last_output['blueprint_session_id']` 解析出的 `ConvergenceSession` 上校 `process_type`。道③由「读只按解析出的会话过滤 + 写只往解析出的会话写 + 请求体零会话入参面」结构性兜住，两个 view 的类 docstring 各列「四道兜底绝不绕过」。
- **绝不 5xx（T-113-10）**：拒绝走 `error_response` 4xx 信封（403/404 按码分流），业务异常整段 `except Exception` 兜底成 200 + 降级体，异常文本先 `redact_secrets_in_text(...)[:500]` 再进 warning。`rg "status_code=5|status=5xx" mcp_tools/views.py` 在新增段零命中。
- **写入脱敏与单一写入（T-113-09 / INV-6）**：`content` 只经 `BlueprintContextService.append_entry` 入库（service 内 `_redact_json` 递归脱敏）；`rg "BlueprintContextEntry.objects" mcp_tools/views.py` 零命中。测试用满足 `SENSITIVE_VALUE_PATTERN` 20 字符门槛的样本（`friday_pat_abcdefghij1234567890` / `Bearer sk-0123456789abcdefghijklmn`）+ 正向 `***REDACTED***` 断言，避免弱断言假绿。
- **waiter 顺带满足 + 重派接续点**：写入后立即 `satisfy_waiters(...)`，把清单长度作为 `satisfied_waiters` 回报；调用处上方三行注释明确标出 113-04 的纯追加接入点（含 `aredispatch_waiting_repos` 字面量便于 grep）。本 plan **不 dispatch**。
- **容器侧纯追加（T-113-12）**：`KNOWLEDGE_TOOL_SCHEMAS` 尾部追加两项并在其上方写入向后兼容结论注释；`git diff task/core/knowledge_tools.py | rg "^-"` 为空、`rg -c "timeout=60.0"` == 1、`rg "callback"` 零命中、`git diff --stat task/core/executor.py task/core/config.py` 为空。守护测试用 `inspect.signature` 参数名元组恒等 + `inspect.getsource` 断言，新增参数/改超时/加回调都会立刻红。
- **观测（W5 已执行期核实）**：`RequestMetric.labels['call_source']` **确实由 `McpToolView._record` 写入**（`views.py:304` `labels={"call_source": self.tool_name, "run_id": ...}`），故按真实键名断言，未臆造。指标经内存队列异步落库，测试用既有 `system.metric_sink.flush_now()` 钩子 drain 后断言。校验失败路径以 `call_status="error", error=<error_code>` 留痕，使拒绝在 `ToolCallRecord` 里可查询。

## Task Commits

| Task | Commit | 内容 |
| ---- | ------ | ---- |
| 1 | `1fa382f2` | 两个 RequestSerializer + `_aresolve_blueprint_session` 三道校验 + 两个 `McpToolView` 子类 + 两条 url + `TOOL_SCHEMA_SNAPSHOT` 与其守卫同步 |
| 2 | `57b14573` | `KNOWLEDGE_TOOL_SCHEMAS` 追加两项（工厂零改动）+ 容器侧 6 例守护测试 + 两处既有计数守卫同步 |
| 3 | `1b292b8d` | 服务端 20 例端到端测试（三道校验负向 / 跨会话隔离 / 脱敏 / 非 5xx / waiter / 观测） |

## Files

- `server/mcp_tools/serializers.py`（+66 行纯追加：`_BLUEPRINT_CONTEXT_KINDS` 六值 + 两个 RequestSerializer + `TOOL_SCHEMA_SNAPSHOT` 两项）
- `server/mcp_tools/views.py`（+364 行纯追加：模块常量 3 + helper 5 + view 2；import 区加 `DjangoValidationError` 与两个 serializer 名）
- `server/mcp_tools/urls.py`（+13 行纯追加：2 import + 2 path，零删除行）
- `server/tests/mcp_tools/test_blueprint_context_tools.py`（新建 ~470 行，20 例）
- `server/tests/mcp_tools/test_schema_snapshot.py`（+11 行：两项快照，既有 30 项逐字未动）
- `task/core/knowledge_tools.py`（+72 行纯追加：兼容性注释 + 两个表项；工厂/build/allowed_tools 一行未改）
- `task/tests/test_blueprint_context_tools_schema.py`（新建 6 例）
- `task/tests/test_knowledge_tools.py`（`EXPECTED_TOOL_NAMES` 拆 `_LEGACY_TOOL_NAMES` + `_NEW_113_TOOL_NAMES`，逐名字面量守护强度未削弱）
- `task/tests/test_claude_sdk_integration.py`（`len(knowledge_allowed_tools()) == 7` → `== 9`）

## Decisions

- **项目成员闸对「未绑项目」的会话放行**：`ConvergenceSession` **没有** `project` FK（113-01 已因此把条目的 `project` 改可空），唯一可靠反查链是 `conversation_id → Conversation.bound_project_id`。若把「反查不到」判成 `not_member`，工作流入口（`conversation_id` 为空）的蓝图会话将全线 403，主路径直接不可用。落法：反查得到才叠加成员闸，反查不到时道①归属校验已是完整授权依据（session 必须属于 token owner）。
- **成员闸口径取「成员 或 public_org」**（CONTEXT 锁定的 packer 口径）。执行期实测发现 `Project.visibility` **默认就是 `public_org`**，故 `not_member` 只在 `members_only` 项目上触发 —— 测试显式建 `members_only` 项目才能证伪该道，另补一条 `public_org` 非成员放行的正向用例把这个口径钉死。
- **校验失败以 `call_status="error"` 留痕**：拒绝是安全事件，`ToolCallRecord.status="error" + error=<code>` 让「谁在越权」可 SQL 查询。副作用是基类把 `RequestMetric.status_code` 记成 500（基类硬编码 200/500 二值），属基类既有限制，未为此改基类（会波及全部 30 个既有工具）。
- **`satisfied_waiters` 而非直接重派**：service 的判定与置 `superseded` 已同事务幂等，重派需要派发面依赖（113-04 独占），此处只回报计数并留 grep 友好的接续点注释。

## Deviations from Plan

共 5 处：2 处为既有守护测试必然冲突（同 113-01 偏差 2 的性质），1 处为 PLAN 前提与本仓事实不符的修正，2 处为范围外未修。

**1. [Rule 3 - 既有守护测试冲突] 新增两条 url 必然撞 `TOOL_SCHEMA_SNAPSHOT` 双向守卫，须同步 snapshot 与其测试**

- **Found during:** Task 1
- **Issue:** `test_schema_snapshot.py::test_registered_tools_match_snapshot` 断言「`urls.py` 的 `tools/<name>/` 集合 == `TOOL_SCHEMA_SNAPSHOT` 键集」，`test_mcp_read_tool_schema_snapshot` 再逐字比对 snapshot 字面量。PLAN 未预告这两条：只加 url 不加 snapshot 必红。
- **Fix:** `serializers.py` 的 `TOOL_SCHEMA_SNAPSHOT` 追加两项，测试侧字面量同步追加（既有 30 项逐字未动）。顺带让该快照充当「不得给这两个工具加 session 入参」的守卫（注释已写明）。
- **Files modified:** `server/mcp_tools/serializers.py`、`server/tests/mcp_tools/test_schema_snapshot.py`
- **Commit:** `1fa382f2`

**2. [Rule 3 - 既有守护测试冲突] 容器侧两处 7 计数快照须同步为 9**

- **Found during:** Task 2
- **Issue:** `task/tests/test_knowledge_tools.py` 的 `EXPECTED_TOOL_NAMES`（7 项字面量，被 `test_server_has_exactly_seven_whitelist_tools` 与 `test_knowledge_allowed_tools_naming` 消费）与 `task/tests/test_claude_sdk_integration.py:330` 的 `assert len(knowledge_allowed_tools()) == 7`。PLAN 只预告了自建测试要断言 9，未预告这两条既有守卫。
- **Fix:** `EXPECTED_TOOL_NAMES` 拆成 `_LEGACY_TOOL_NAMES`（7 项逐名字面量保留）+ `_NEW_113_TOOL_NAMES`（2 项）再拼接；`== 7` 改 `== 9`。守护强度未削弱（仍是逐名 + 计数双断言）。
- **Files modified:** `task/tests/test_knowledge_tools.py`、`task/tests/test_claude_sdk_integration.py`
- **Commit:** `57b14573`

**3. [Rule 1 - PLAN 前提与本仓事实不符] 「`ConvergenceSession.project` 走 `_assert_project_member`」改为 best-effort 反查 + 未绑项目不叠加成员闸 + 口径含 `public_org`**

- **Found during:** Task 1
- **Issue:** PLAN Task 1 第 6 步写「`request.user` 对 `ConvergenceSession.project` 走 `_assert_project_member`（若字段名不同按实际写）」，但该模型**根本没有 project 字段**（113-01 已因同一事实把条目 FK 改可空）。直接 fail-closed 会让 workflow 入口的蓝图会话全线 403。另 CONTEXT 明确要求口径是「成员 **或** public_org」，而 `_assert_project_member` 只判成员。
- **Fix:** 新增 `_aresolve_blueprint_project_id`（`conversation_id → Conversation.bound_project_id`，同 `architect_merge_adapter._maybe_bind_plan_to_project` 的既有链路）与 `_aassert_blueprint_project_access`（成员 → 否则查 `visibility == public_org`）。反查不到项目时不叠加成员闸（道①已完整覆盖授权）。测试补 `members_only` 负向 + `public_org` 正向两条把口径钉死。
- **Files modified:** `server/mcp_tools/views.py`、`server/tests/mcp_tools/test_blueprint_context_tools.py`
- **Commit:** `1fa382f2` / `1b292b8d`

**4. [Rule 3 - 范围外，未修] `ruff check mcp_tools/` 报 6 条 I001，全在既有 Django 生成 migration**

- **Found during:** verification
- **Issue:** PLAN verification 要求 `ruff check mcp_tools/` 通过，实跑 6 错，全部是 `mcp_tools/migrations/000{1,2,4,5,6,7}_*.py` 的 import 未排序（Django 生成风格，与本 plan 无关）。同 113-01 偏差 5。
- **Fix:** 按范围纪律不修（改既有 migration 属无收益扰动）。等价验收：本 plan 触及的 3 个 `mcp_tools/*.py` 与 4 个测试文件 `ruff check` 全部 All checks passed。
- **Files modified:** 无

**5. [Rule 3 - 范围外，未修] `test_skills_snapshot_guard.py::test_skill_files_discovered` 因 `skills/` 子模块未 checkout 而失败（先于本 plan 存在）**

- **Found during:** verification
- **Issue:** 该守卫读 `skills/skills/*/SKILL.md`，worktree 里 `skills/` 与 `mcp/` 两个子模块都未 checkout（`mcp` 那条自带 `pytest.skip`，`skills` 那条是硬 assert）。与本 plan 改动无因果关系。
- **Fix:** 不修。⚠️ **给 CI 的遗留提醒**：`test_mcp_package_alignment` 要求 `mcp/src/tools.ts` 的工具名集合 == `TOOL_SCHEMA_SNAPSHOT` 键集，本 plan 新增两个键后，**CI 若 checkout `mcp` 子模块该守卫会红** —— 需要在 `mcp` 仓同步这两个工具名（或按「容器专用工具不进 npm 包」显式排除）。子模块不在本 worktree 内，无法在本 plan 内完成。
- **Files modified:** 无

## 测试与验证

- `server/tests/mcp_tools/test_blueprint_context_tools.py`：**20 passed**
- `task/tests/test_blueprint_context_tools_schema.py`：**6 passed**
- **PLAN verification 全套**：
  - `cd server && uv run pytest tests/mcp_tools/ -q` → **227 passed, 2 skipped, 1 failed**（唯一失败是偏差 5 的子模块缺失，与本 plan 无关）
  - `cd task && uv run pytest -q` → **247 passed, 3 skipped**（既有 245 例零扰动）
  - `uv run python manage.py makemigrations --check --dry-run` → 退出码 **0**（本 plan 零模型改动）
  - `uv run ruff check mcp_tools/` → 6 条 I001 全在既有 migration（偏差 4）；本 plan 7 个文件单独 check 全通过
- ⭐ **变异验证（三道校验的证伪能力实测，非声明）**：
  - 去掉道①归属判定（`if False`）+ 道②`process_type` 判定 → `test_session_owned_by_other_user_rejected` / `test_null_session_user_fail_closed` / `test_non_blueprint_process_rejected` **三条同时 fail**；
  - 把 `_aassert_blueprint_project_access` 短路成 `return True` → `test_non_member_rejected` **fail**；
  - 变异全部已回滚，最终 20 例全绿。**三道校验的 403 断言确实能逮住防线失效，不是恒真断言。**
- **冻结面自检**：3 个 commit 触及 9 个文件，`repo_router_v2 / decompose_segments / research_adapter / architect_merge_adapter / merged_plan / clarify_adapter / render / resume / builtin_processes / charter_service / settings_service / event_taxonomy / blueprint_resume / blueprint_research_adapter` **零命中**；`git diff --name-only | rg "^web/"` 零命中。
- **并行自检**：与同 wave 的 113-03（`blueprint_research_adapter.py` / `subagent/api/callbacks.py` / `blueprint_repo_plan_schema.py`）**零文件交集**，交错提交无冲突。
- **受限面自检**：`git diff | rg "^-"` 在 `urls.py` / `serializers.py` / `views.py` / `task/core/knowledge_tools.py` 四个文件上**均为 0 行**（全部纯追加）。
- **运行时验收**：`rg -c '"name": "' task/core/knowledge_tools.py` == 9；`rg -c "timeout=60.0"` == 1；`rg "callback"` 零命中；`rg -c "BlueprintContextEntry.objects" server/mcp_tools/views.py` == 0。

## Self-Check: PASSED

- 文件存在：9 个 key-files 全部命中（2 新建 + 7 修改）
- commit 存在：`1fa382f2` / `57b14573` / `1b292b8d` 均在 `git log`
- artifacts contains 断言：`_aresolve_blueprint_session` ∈ `views.py` ✓（5 处：定义 + docstring + 2 view 调用 + 注释）；`mcp-tool-read-blueprint-context` ∈ `urls.py` ✓；`report_blueprint_context` ∈ `task/core/knowledge_tools.py` ✓；`session_mismatch` 的等价物 —— 本 plan 统一为四个可归因错误码（`session_not_owned` / `session_not_found` / `not_blueprint_session` / `not_member`），未使用 `session_mismatch` 这个笼统词（PLAN artifacts 的 contains 字面量按此调整，可归因性更强）
- key_links 断言：`BlueprintContextService` ∈ `views.py`（append_entry / read_entries / satisfy_waiters 三处调用）✓；`main_session` ∈ `views.py` 与测试工厂 ✓；`read_blueprint_context` 在 task 白名单与 server urls 两侧逐字一致 ✓

## Next Phase Readiness

- **113-04（等待原语与重派）**：① `await_blueprint_context` 追加为第 10 个白名单表项即自动可达（URL 由 tool_name 拼接，服务端需配套加 view + url + snapshot 两项 + 快照守卫同步）；② 重派在 `ReportBlueprintContextView._handle` 的 `satisfy_waiters` 调用上方注释处纯追加一次 `aredispatch_waiting_repos(session, redispatch)`；③ 新 view 直接复用 `_aresolve_blueprint_session` 做同款三道校验，勿另起一套。
- **113-03（同 wave）**：`AgentSession.objects.acreate(..., user=dispatch_user)` 未落地前，蓝图容器读写总线一律 403 `session_not_owned` —— 这是 fail-closed 的**设计预期**，联调时先确认派发侧已写 user 再排查其他。
- **CI 遗留**：`mcp/src/tools.ts` 需同步两个新工具名（或显式排除容器专用工具），否则 `test_mcp_package_alignment` 在 checkout 子模块的 CI 上会红（详见偏差 5）。
- **给后续 view 作者的硬约束**：新增总线相关 MCP 工具一律 ① 走 `_aresolve_blueprint_session`，② 请求体**不得**出现任何会话入参字段，③ 全路径 4xx/200 绝不 5xx，④ 写入只经 `BlueprintContextService`。
