---
phase: 102-knowledge-consumption
reviewed: 2026-07-22T05:55:00Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - server/friday/settings.py
  - server/services/process_runtime/recall_adapter.py
  - server/tests/services/test_recall_adapter.py
  - server/agents/tools/knowledge_read_tools.py
  - server/agents/chat_runner.py
  - server/tests/agents/tools/test_knowledge_read_tools.py
  - server/initiatives/services/project_doc_service.py
  - server/knowledge/sources/project_doc.py
  - server/tests/initiatives/test_state_api_materialize_hook.py
  - server/tests/knowledge/test_project_doc_source.py
  - server/mcp_tools/serializers.py
findings:
  blocker: 0
  high: 1
  medium: 2
  low: 4
  total: 7
status: fixes_applied
fixed_at: 2026-07-22T06:20:00Z
fixed: 7
skipped: 0
---

# Phase 102: Code Review Report

**Reviewed:** 2026-07-22（commits d4a0881d / f4561acd / 676012fb / cdb7a253 / 19ff6302 / 0ce3c3de / b7cfc8cf / 73c4dac6 / 65d5922e / 104fe3a1）
**Depth:** standard
**Files Reviewed:** 11（另含 `server/tests/mcp_tools/test_schema_snapshot.py`、`test_skills_snapshot_guard.py`；`104fe3a1` 仅移动 `skills` 子模块指针，子模块内容不在本仓可审范围）
**Status:** findings

## Summary

Phase 102 三个 plan 的实现整体质量良好：recall_adapter 的单查后按 kind 截断逻辑正确（顺序遍历保持 RRF 降序、`total_cap = max(top_k, sum(limits))` 兜底）、超采样 2 倍取舍有据；三个 chat 工具本身的 fail-closed 分支完整（`_resolve_conversation_user` 返回 None 即拒绝、`_resolve_project_scope` 非成员非 `public_org` 即 `_deny`），且工具函数只从注入的 `conversation_id` 解析 acting user，不接受独立的 user 参数；trace 写入全部 best-effort 吞异常且 payload 不含召回正文；STATE live 行有 500 上限、拼接后全文过 `redact_secrets_in_text`；`TOOL_SCHEMA_SNAPSHOT` 的 `report_project_state` request/response 键已逐一对照 `ReportProjectStateRequestSerializer`（project_id/branch_name/repository_id/apis）与 `ReportProjectStateView` 实际输出（applied/reason/results/total_applied/run_id）核实一致，注册==snapshot 双向守卫与 skills grep 守卫（含防空跑假绿断言）逻辑正确。

主要问题集中在权限注入链的一个继承缺陷（HIGH-01，缺陷位于 `chat_runner` 既有共享闭包，但本 phase 新挂的三个工具全部暴露在该路径上）、物化钩子的幂等声明与批量放大（MED-01）、以及召回配置解析位于 best-effort 保护之外（MED-02）。

## High

### HI-01: chat_runner 工具参数合并顺序允许模型产出的 `conversation_id` 覆盖服务端注入值（confused-deputy）

**File:** `server/agents/chat_runner.py:702`（缺陷在既有共享闭包；Phase 102 经 `chat_runner.py:115-134` 把三个新工具挂上该路径）
**Issue:** 审查要求「三个新 chat 工具必须从服务端会话上下文解析 acting user，不得来自客户端参数」。工具函数本身满足——只消费注入的 `conversation_id`。但实际执行路径是 `_ChatToolSpec.execute`（`spec.execute(arguments)`，`chat_runner.py:792`），其中：

```701:708:server/agents/chat_runner.py
            merged = {**_injected, **arguments}
            # Pitfall #12：LLM 未提供 branch 时用 default，非无条件覆盖
            if "branch" in _props and _dsb:
                cur = merged.get("branch")
                if cur in (None, ""):
                    merged["branch"] = _dsb
            return await _tool_def.func(**merged)
```

> **✅ RESOLVED（commit `e16d2d52`）**：`_execute` 改为 `merged = {**arguments, **_injected}` 让服务端注入值终局生效，且 `allowed = set(_props) - set(_injected)` 使模型产出的 `conversation_id` / `space_id` 按未知字段 drop 并留 warning。新增回归测试 `test_tool_specs_injected_values_cannot_be_overridden_by_llm`（模型带受害者会话 UUID + 异 space_id 仍以服务端注入值执行，覆盖共享此闭包的三个新知识工具与既有 project_read 系工具）。

`arguments` 来自模型 tool_call 原始 args，**后展开覆盖 `_injected`**。虽然 `build_langchain_tools` 把 `conversation_id` 从 LLM 可见 `args_schema` 剔除（`langchain_adapter.py:127-128`），但 chat 路径不走 adapter 的 pydantic 校验闭包，而 L691-700 的未知字段过滤用的是**完整** `tool_def.parameters.properties`（含 `_CONV_ID_PARAM`），所以模型被诱导（prompt injection）产出的 `conversation_id` 不会被 drop，会覆盖服务端注入值。攻击者 A 在自己会话里诱导模型以受害者 B 的会话 UUID 调用 `search_project_context` / `read_project_doc` / `search_learning_cases`（以及既有的 `search_delivery_knowledge` / project_read 系工具），即以 B 的身份和 B 绑定的项目读取知识——`langchain_adapter.py:135-137` 声称的「不存在 kwargs 覆盖 injected 的越权路径」的 security mitigation 在 chat 路径不成立。前置条件是获知他人会话 UUID（不可枚举），故评 HIGH 非 BLOCKER。此为既有缺陷（Phase 80/85 工具同样暴露），非本 phase 引入，但本 phase 扩大了暴露面且触及本次审查的显式要求。
**Fix:** 在 `chat_runner.py` 的 `_execute` 里让注入值终局生效（一行改动，语义与 adapter 注释宣称的一致）：

```python
merged = {**arguments, **_injected}
```

或在未知字段过滤后显式剥离：`arguments = {k: v for k, v in arguments.items() if k not in _injected}`。同时建议把 L691 的 `allowed` 改为 `set(_props) - set(_injected)`，让注入字段直接按未知字段 drop 并留 warning 日志。

## Medium

### MED-01: `upsert_state_api` 物化钩子对批量上报无去抖——N 条 API 触发 N 次全量重摄取，幂等注释仅覆盖「内容未变」场景

**File:** `server/initiatives/services/project_doc_service.py:432-443`

> **✅ RESOLVED（commit `6333b1f6`，方案 ①）**：`upsert_state_api` 增加 `defer_materialize: bool = False` 参数；`ReportProjectStateView._handle` 批量循环逐条传 `defer_materialize=True`，循环结束后经新增的 `ProjectDocService.schedule_state_materialization` 合并调度一次（`total_applied > 0` 才调）。单条调用方默认路径不受影响，物化仍收口 INV-6 单一摄取管线。误导性注释已改写（明确 content_hash 短路只对内容未变成立）。新增测试：`test_batch_report_schedules_materialization_once`（5 条批量上报断言恰调度 1 次）、`test_upsert_state_api_defer_materialize_skips_scheduling`、`test_schedule_state_materialization_coalesced_entry`。

**Issue:** 注释声称「report_project_state 批量上报会逐条触发，摄取管线 content_hash 短路保证重复调度为幂等空操作，不需要额外去抖」。但 content_hash 短路（`knowledge/ingestion.py:229`）只对**内容未变**成立；批量上报中每条 `upsert_state_api` 都会新增一行 `ProjectStateApi`，使 STATE 文档 normalize 内容逐次变化 → 一次 200 条（serializer 上限）的 `report_project_state` 请求会调度最多 200 次**互不短路**的全量摄取，每次都对整篇 STATE 文档（snapshot + 至多 500 行 API 清单）重新 embedding 并翻转实体版本，产生 199 个只含部分清单的中间版本噪声。同一文件里的飞书推送走的是 `schedule_doc_push` debounce（L425），物化钩子却没有对等机制，两条写后通路的抖动治理不对称。
**Fix:** 二选一：① 把物化调度从 service 逐条钩子上提到 `ReportProjectStateView._handle` 循环结束后调度一次（单条 `upsert_state_api` 的其他调用方不受影响，可保留钩子但在 view 批量路径传入 `defer_materialize=True`）；② 复用 `doc_push_scheduler` 的 debounce 模式为物化调度加同款延迟合并。同时修正 L434-435 的注释，避免后续读者误信「无需去抖」。

### MED-02: recall_adapter 的 settings 解析在 try/except 之外——配置类型错误会冒泡进编排，违反模块自述的 RECALL-01 契约

**File:** `server/services/process_runtime/recall_adapter.py:83-87`

> **✅ RESOLVED（commit `5cf7e819`）**：kinds/limits 解析抽为 `_resolve_recall_config()`，内部三层防御：kinds 迭代失败降级默认集合；`limits_cfg` 非 dict 降级 `_DEFAULT_KIND_LIMITS`；单 kind limit 非数值（`TypeError`/`ValueError`）降级该 kind 默认限额——均记 `process_recall_config_invalid` 结构化 warning（`category=sampling`），绝不冒泡进 engine。新增畸形配置测试 `test_malformed_kind_limits_config_degrades_to_defaults`（list 型配置）与 `test_non_numeric_kind_limit_degrades_to_defaults`（"four" 型 value）。

**Issue:** 模块 docstring 与 `recall()` docstring 均承诺「任何异常 → log warning + 空 hits，不冒泡破坏编排」，但 kinds/limits 的读取与解析（L83-87，含 `limits_cfg.get(...)` 与 `int(...)`）位于 L98 的 try 块**之前**。`PROCESS_RECALL_KIND_LIMITS` 经 `env.json` 读取，env 里写成合法 JSON 但非 dict（如 `'[4,4,4]'` 或 `'"4"'`）即通过 settings 加载，运行时在 `limits_cfg.get` 处抛 `AttributeError` 直接冒泡进 engine，使 recalling stage 硬失败——恰是该模块承诺兜住的场景。`int()` 对非数值 value（如 `'{"work_item": "four"}'`）同理。
**Fix:** 把 L83-87 移入既有 try 块（except 分支已返回空 hits），或在解析处做类型防御：

```python
if not isinstance(limits_cfg, dict):
    limits_cfg = _DEFAULT_KIND_LIMITS
```

## Low

### LO-01: 异常文本未经 `redact_secrets_in_text` 即写日志与 ToolResult

**File:** `server/agents/tools/knowledge_read_tools.py:144-145, 216-217, 286-287`；`server/services/process_runtime/recall_adapter.py:117`

> **✅ RESOLVED（commit `16bf5e3e`）**：四处异常文本均改为 `redact_secrets_in_text(str(exc))` 后再写结构化日志字段与 ToolResult error（返回 LLM 的 `f"检索失败: {safe_err}"` 同步脱敏）。

**Issue:** 日志规范要求「上游响应体/异常文本手动用 `redact_secrets_in_text`」。这几处把 `str(exc)` 直接写进结构化日志字段，且 chat 工具还把 `f"检索失败: {exc}"` 原样返回给 LLM（进入对话消息与留痕）。上游是 Qdrant / DB / 内部 service，异常文本携带凭证概率低，且与既有 `delivery_knowledge_tools.py:129-131` 先例一致，故仅评 LOW。
**Fix:** `error=redact_secrets_in_text(str(exc))`（`server/common/logging.py`），ToolResult 的 error 同理。

### LO-02: chat 工具的 `limit` / `top_k` 无上限钳制

**File:** `server/agents/tools/knowledge_read_tools.py:123, 197`

> **✅ RESOLVED（commit `13fbfa1b`）**：`search_learning_cases` 入口钳 `limit = max(1, min(int(limit), 20))`，`search_project_context` 同理钳 `top_k`（上界 20 对齐 MCP serializer `max_value=20`）。新增测试 `test_search_learning_cases_clamps_oversized_limit`（limit=10000 → 20）与 `test_search_project_context_clamps_oversized_top_k`（top_k=99999 → 20）。

**Issue:** MCP 侧同名工具经 serializer 校验有边界，chat 侧参数由 LLM 直出：`search_learning_cases(limit=10000)` 会让 `learning_case_service` 以 `top_k=30000` 打 Qdrant（`learning_case_service.py:304` 的 `max(limit*3, 10)` 只有下限没有上限）；`search_project_context` 的 `top_k` 同理。
**Fix:** 工具入口钳一行：`limit = max(1, min(int(limit), 20))`（`top_k` 同理，对齐 MCP serializer 的上界）。

### LO-03: skills grep 守卫的动词前缀白名单会静默漏检新前缀工具；allowed 集并入字段名会掩蔽同名漂移

**File:** `server/tests/mcp_tools/test_skills_snapshot_guard.py:24-26, 29-36`

> **✅ RESOLVED（commit `b9511f35`）**：新增自检断言 `test_tool_token_prefixes_cover_all_snapshot_keys`，强制 `_TOOL_TOKEN_RE` 前缀表覆盖 `TOOL_SCHEMA_SNAPSHOT` 全部键（当前 30 键全匹配）——新前缀工具进 snapshot 时 CI 直接红提醒扩前缀表，守卫不再静默失效。allowed 集并入字段名的同名漂移风险当前无冲突实例，按 review 建议以前缀自检为主修。

**Issue:** `_TOOL_TOKEN_RE` 只识别 16 个动词前缀开头的 token——未来新增如 `pack_*` / `apply_*` / `submit_*` 前缀的工具在文档里被引用时，守卫直接不匹配、静默放行（守卫失效而非误报，无 CI 信号）。另外 `_allowed_tokens()` 把全部 request/response 字段名并入允许集，若某工具名恰与某字段名重合（当前无冲突），该工具从 snapshot 移除后文档残留引用也不会被抓到。
**Fix:** 在同文件补一条自检断言，强制前缀表覆盖 snapshot 全部键：`assert all(_TOOL_TOKEN_RE.fullmatch(f"`{name}`") for name in TOOL_SCHEMA_SNAPSHOT)`，新前缀工具进 snapshot 时 CI 即提醒扩前缀表。

### LO-04: `upsert_state_api` 的 doc_id 反查不在钩子的 fail-soft 保护内

**File:** `server/initiatives/services/project_doc_service.py:437-439`

> **✅ RESOLVED（commit `09500dc5`）**：doc_id 反查下沉进 `schedule_state_materialization`（MED-01 引入）并整体包进 try/except——查询瞬时失败记 `state_materialization_schedule_failed` warning（`error_type` 不带异常原文），绝不让已写入的 API 行被 view 误标 `applied=False`。新增测试 `test_doc_id_lookup_failure_does_not_break_upsert`（`ProjectDoc.objects.filter` 抛 RuntimeError 时 upsert 仍正常返回）。

**Issue:** `_schedule_materialization` 自身全吞异常，但其前置的 `ProjectDoc.objects.filter(...).afirst()` 查询裸奔——瞬时 DB 异常会让 `upsert_state_api` 在 API 行**已成功写入**后抛错，view 的逐条 except（`views.py:3256`）会把该条标成 `applied=False`，与实际写入结果不符（fail-soft 语义被击穿一半）。
**Fix:** 把 doc_id 反查与调度一并包进 try/except-pass，或下沉进 `_schedule_materialization`（传 `project_id` 让它自查 doc_id）。

---

## 审查焦点核验结论（无发现项部分）

- **per-kind 截断与超采样**：`_truncate_per_kind` 顺序遍历保持融合分降序、未知 kind 用 `_DEFAULT_KIND_LIMIT` 兜底、`total_cap` 兜底正确；`top_k=sum(limits)*2` 超采样与「单查后截断」取舍在 docstring 有充分论证。测试覆盖限额、排序、可配置 kinds 与 `include_document_kind` 动态传参。✓
- **三工具 fail-closed**：`search_learning_cases` 走 `_resolve_conversation_user`（空/不存在会话 → None → 拒绝）；`search_project_context` / `read_project_doc` 走 `_resolve_project_scope`（未绑项目/项目不存在/非成员非 public_org → `_deny`），均有正反路径测试。acting user 一律由注入的 `conversation_id` 服务端解析（唯一例外见 HI-01 的覆盖路径）。✓
- **STATE live 行**：500 行上限、`order_by("path")` 稳定输出、拼接后全文 `redact_secrets_in_text`、非 STATE 文档零变化（有测试锁定）。✓
- **convention**：structlog kv 事件均带 `category`/`component`（recall 链 `sampling`、工具链 `caller`）；trace 写入整段吞异常且有专门测试；ORM 全部经 `sync_to_async` / async API，`_resolve_actor` 显式规避 async 懒加载 FK。✓
- **snapshot 契约**：`report_project_state` request 键 == serializer 声明字段、response 键 == view `_skip`/成功输出的键集；注册==snapshot 双向守卫与整表断言同步更新。✓

---

## Fix Summary（2026-07-22）

全部 7 项 findings 已修复并原子提交（fixed 7 / skipped 0）：

| Finding | Commit | 摘要 |
|---------|--------|------|
| HI-01 | `e16d2d52` | chat 工具闭包注入值终局生效 + 注入字段从 allowed 集剔除 + confused-deputy 回归测试 |
| MED-01 | `6333b1f6` | `report_project_state` 批量上报合并为一次 STATE 物化调度（`defer_materialize` + view 循环后单次调度） |
| MED-02 | `5cf7e819` | recall 配置解析抽 `_resolve_recall_config`，畸形配置降级默认值 + 结构化 warning，不冒泡进 engine |
| LO-01 | `16bf5e3e` | 四处异常文本经 `redact_secrets_in_text` 脱敏后再写日志 / ToolResult |
| LO-02 | `13fbfa1b` | chat 知识工具 `limit` / `top_k` 钳上下界（上界 20 对齐 MCP serializer） |
| LO-03 | `b9511f35` | skills grep 守卫增加前缀表覆盖 snapshot 全键的自检断言 |
| LO-04 | `09500dc5` | STATE 物化 doc_id 反查纳入 fail-soft 保护，不反噬上报主流程 |

回归验证：`tests/test_chat_runner.py`、`tests/services/test_recall_adapter.py`、`tests/agents/tools/test_knowledge_read_tools.py`、`tests/initiatives/test_state_api_materialize_hook.py`、`tests/mcp_tools/test_report_project_state.py`、`tests/mcp_tools/test_skills_snapshot_guard.py`、`tests/mcp_tools/test_schema_snapshot.py`、`tests/knowledge/test_project_doc_source.py` 共 65 passed。

---

_Reviewed: 2026-07-22_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
_Fixes applied: 2026-07-22 (gsd-code-fixer)_
