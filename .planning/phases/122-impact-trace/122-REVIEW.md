---
phase: 122-impact-trace
reviewed: 2026-08-10T01:54:00+08:00
depth: standard
files_reviewed: 22
files_reviewed_list:
  - server/services/code_graph/symbol_resolve.py
  - server/services/code_graph/impact.py
  - server/services/code_graph/trace.py
  - server/services/code_graph/__init__.py
  - server/services/code_graph_tools.py
  - server/services/code_graph_cross_repo.py
  - server/mcp_tools/serializers.py
  - server/mcp_tools/views.py
  - server/mcp_tools/urls.py
  - server/agents/tools/graph_tools.py
  - server/agents/tools/schemas/graph_tools.py
  - server/agents/tools/__init__.py
  - server/agents/chat_runner.py
  - server/agents/tools/delivery_knowledge_tools.py
  - server/tests/services/code_graph/conftest.py
  - server/tests/services/code_graph/test_symbol_resolve.py
  - server/tests/services/code_graph/test_impact.py
  - server/tests/services/code_graph/test_trace.py
  - server/tests/services/code_graph/test_cross_repo_hop.py
  - server/tests/services/code_graph/test_impact_shell.py
  - server/tests/mcp_tools/test_impact_trace_tools.py
  - server/tests/agents/tools/test_graph_tools.py
findings:
  blocker: 1
  high: 2
  medium: 3
  low: 2
  info: 3
  critical: 1
  warning: 5
  info_legacy: 5
  total: 11
status: issues_found
fix_status: partial_fixed
fixed:
  - BL-01
  - HI-01
  - HI-02
  - ME-01
  - ME-02
  - ME-03
  - LO-02
skipped:
  - LO-01
  - IN-01
  - IN-02
  - IN-03
---

# Phase 122: Code Review Report

**Reviewed:** 2026-08-10T01:54:00+08:00  
**Depth:** standard  
**Files Reviewed:** 22  
**Status:** issues_found  
**Fix status:** 7 fixed (BL/HI/ME + LO-02)；LO-01 / INFO 未改（见 `122-REVIEW-FIX.md`）

## Summary

Phase 122 的 impact/trace 内核、共享编排（`run_impact` / `run_trace`）与双面薄壳整体结构清晰：D-19 歧义短路、D-24 种子+深度、D-23 数值 `resolution_rate`、D-25 跨仓走 ORM 而非图边、对话 owner fail-closed 与 MCP PAT `_begin` 闸大多到位。但对着威胁模型 T-122-exclusion / 「`get_graph` 是唯一权限+exclusion 收口」审下来，**ORM 侧符号解析在取图之前、且区分 `symbol_not_found` vs `symbol_not_in_graph`**，会把被 exclusion 挡掉的符号存在性（以及歧义候选的 `file_path` / `signature`）送出墙外——这是本相位最严重的缺陷。跨仓一跳在空种子与权限复核顺序上也有可证伪的正确性/授权问题；D-21 逐字节哨兵目前只覆盖 `impact_analysis`，未覆盖 `trace_call_path`。

## Narrative Findings (AI reviewer)

### BLOCKER

#### BL-01: ORM 解析绕过 exclusion，且 `symbol_not_found` / `symbol_not_in_graph` 区分泄漏被排除符号

**Status:** ✅ Fixed (`9b755623`)  
**File:** `server/services/code_graph_tools.py:748-798`  
**Also:** `server/services/code_graph_tools.py:434-587`（`resolve_symbol_candidates` 无 exclusion 过滤）  
**Issue:**  
图内解析器 `resolve_symbol_in_graph` 明确要求把「不存在」与「被 exclusion 挡住 / 不在子图」合并成同一出口，避免存在性预言机（见 `symbol_resolve.py` docstring）。但编排层却：

1. **先**用 `resolve_symbol_candidates` 直查 `Symbol` ORM（**不过** exclusion matcher）；
2. ORM 零命中 → `error_code=symbol_not_found`；
3. ORM 命中后取图、图内落空 → `error_code=symbol_not_in_graph`。

`test_symbol_not_in_graph_is_explicit` 已证明：exclusion 规则下的 `secret/hidden.py` 仍在 `Symbol` 表、经 `symbol_id` 可走进该分支。攻击者/agent 因此可以：

- 用名字/uid 探测「索引里有、图里没有」的符号（典型即后加 exclusion / 装配过滤掉的路径）；
- 在重名场景下，从 `ambiguous_symbol.candidates` 直接拿到被排除文件的 `file_path` + `signature`（D-19 候选面），绕过 loader 装配期 exclusion（GRAPH-04 / T-122-exclusion）。

这与相位自己写的「源码/路径不给 exclusion 第二条回流通道」相矛盾。

**Fix:**
```python
# 在 resolve_symbol_candidates 内（或 run_* 取图前）对每个候选 file_path
# 走 access.build_matcher_and_fingerprint + is_excluded；被排除的行视为不存在。
# 编排层对外只保留一种「未解析到可用种子」码，例如：
#   - 全部命中均被 exclusion / 不存在 → symbol_not_found（或统一 unresolved_symbol）
#   - ⛔ 删除或合并 symbol_not_in_graph 与 symbol_not_found 的可区分出口
# 若必须保留「子图边界」语义，仅在 ensure_repository_readable 已通过且
# 确认非 exclusion 后，再用 degraded/subgraph 声明表达，且不得回显排除路径。
```

---

### HIGH

#### HI-01: 跨仓 hop 在 `ensure_repository_readable` 之前 ORM 解析对端符号

**Status:** ✅ Fixed (`23bec676`)  
**File:** `server/services/code_graph_cross_repo.py:325-365`  
**Issue:**  
对每个 peer，循环先 `resolve_symbol_candidates(repository_id=peer_repo_id, …)` 读对端 `Symbol` 行，**之后**才 `fetch_graph_for_tool`（内部才跑 `ensure_repository_readable`）。当对端触发 `GraphAccessDenied` 时响应虽折叠为 `REDACTED_REPOSITORY`，但授权边界已被突破：无权限仓的符号表已被读取（含 signature）。当前 `_check_user_acl` 为空实现时风险潜伏；ACL 落地后这是确定性越权读。

**Fix:**
```python
# 每个 peer 先 fetch_graph_for_tool / ensure_repository_readable；
# 仅在权限通过后再 resolve_symbol_candidates。
# 若需种子才能取子图：可先 ensure_repository_readable(user, peer_repo_id)，
# 再解析种子，再 fetch；denied 路径不得触碰 peer Symbol ORM。
```

#### HI-02: 对端全部 call site 未解析时仍 `fetch_graph_for_tool(seed_symbol_ids=[])`

**Status:** ✅ Fixed (`a3cdc54b`)  
**File:** `server/services/code_graph_cross_repo.py:327-406`  
**Issue:**  
`seed_ids` 为空时仍取图。`get_graph` 在空种子时走**全量图**路径；超预算仓会抛 `GraphError`（`cache.py:970+`），被 catch 成 `unavailable_reason`——把「调用点二次解析全失败」误报成「对端图不可用」。小仓则返回 `impact` 空 groups，看起来像「对端无影响面」，尽管 `unresolved_call_sites` 可能 > 0，agent 极易误读。

**Fix:**
```python
if not seed_ids:
    success_entries.append({
        "cross_repo": True,
        "repository_id": peer_repo_id,
        "match_confidence": hits.max_match_confidence,
        "call_sites": list(hits.call_sites),
        "unresolved_call_sites": unresolved,
        "impact": _merge_impact_payloads([]),
        # 可选：显式 reason="call_sites_unresolved"
    })
    continue  # ⛔ 不要 fetch_graph_for_tool([])
```

---

### MEDIUM

#### ME-01: `_merge_impact_payloads` 丢失截断语义与「最浅优先」

**Status:** ✅ Fixed (`0cb89a97`)  
**File:** `server/services/code_graph_cross_repo.py:172-221`  
**Issue:**  
多种子合并时：`truncated_by_depth` 被写成全 0；`returned == total_found`；同 `symbol_id` 先到先得，不比较 `depth` / `path_confidence`。内核 `analyze_impact` 的 limit/截断声明在跨仓条目里被抹平，agent 会以为看到了完整对端影响面；多入口到达同一符号时也可能保留更深层/更弱路径。

**Fix:** 合并时按 `(depth, -path_confidence, symbol_id)` 重排序，保留更优 `_Reach`；按 `result_limit` 截断并重算 `truncated_by_depth` / `truncated_by_nodes`（OR 各种子）。

#### ME-02: D-21 双面逐字节哨兵未覆盖 `trace_call_path`

**Status:** ✅ Fixed (`0b291088`)  
**File:** `server/tests/mcp_tools/test_impact_trace_tools.py:301-407`  
**Issue:**  
`test_two_surfaces_same_payload` 只跑 `impact_analysis`（成功 + `ambiguous_symbol`）。`trace_call_path` 双壳同样声称 D-21 同源，但无对等哨兵；参数映射、`found=False` 信封、子图补充声明任一壳漂移都不会红。

**Fix:** 增加与 impact 同构的两轮用例（`found=True` + `ambiguous_symbol` 或 `found=False`），对 MCP body（去 `run_id`）与 `ToolResult.output["data"]` 做 `json.dumps(sort_keys=True)` 比对。

#### ME-03: 本仓编排同样在 ACL 闸之前做符号解析

**Status:** ✅ Fixed (`4ed4abc0`)  
**File:** `server/services/code_graph_tools.py:748-785`（`run_impact`）；`882-957`（`run_trace`）  
**Issue:**  
对话壳注释写明「真正的授权是 `get_graph` 内 `ensure_repository_readable`」，但 `ambiguous_symbol` / `symbol_not_found` 在取图前就返回完整候选（含 signature）。PAT 只证明「有 token」，不证明「可读该仓」。与 HI-01 同根：ACL 扩展点一旦启用，失败路径已越权。

**Fix:** 在 `resolve_symbol_candidates` 之前（或之内）对 `repository_id` 调用 `ensure_repository_readable(user, repository_id)`；壳层传入的 `user` 必须非空（对话面已保证）。

---

### LOW

#### LO-01: `groups` 键类型在双面消费者上不一致（int vs JSON string）

**Status:** ⏭ Skipped（API 契约面，风险/范围外）  
**File:** `server/services/code_graph/impact.py:548-551`；MCP `Response` JSON 化  
**Issue:**  
内核/`run_*` 使用 `dict[int, …]`；HTTP JSON 键变为 `"1"`/`"2"`。`test_two_surfaces_same_payload` 用 `json.dumps` 双方归一故能绿，但进程内消费 `ToolResult.output["data"]["groups"]` 与解析 MCP JSON 的代码若按 int 键索引会静默 miss。

**Fix:** 编排出口统一把 depth 键规范为 `str`（或双方文档约定并加契约测试）。

#### LO-02: 对话壳 `ValidationError` 路径 `error=str(exc)` 未脱敏

**Status:** ✅ Fixed (`8205a465`)  
**File:** `server/agents/tools/graph_tools.py:283-291`、`348-349`、`481-489`  
**Issue:**  
失败日志对通用异常走了 `redact_secrets_in_text`，但 pydantic `ValidationError` 返回/部分日志仍用裸 `str(exc)`。当前字段面风险低，与壳内其它路径及观测规范不一致。

**Fix:** `error=redact_secrets_in_text(str(exc))[:500]`。

---

### INFO

#### IN-01: D-27 `mcp` submodule 工作区脏，但不在本相位修复范围

**File:** git status `M mcp`  
**Issue:** 122-10 SUMMARY 已记账 npm 工具数 5→7 漂移且明确不改 submodule。本 review 未把 submodule 当缺陷展开；上线前需按 D-27 单独处理，避免误当成 Phase 122 已同步。

#### IN-02: D-23 / D-24 / D-19（图内）实现与观测契约大体合规

`degradation_payload` 无条件带数值 `resolution_rate`；`fetch_graph_for_tool` 强制 `seed_symbol_ids`+`depth`；`run_trace` 双种子 + `_TRACE_SEED_DEPTH=3`，子图无路径追加声明；包内/兄弟模块埋点 `component="code_graph"`、`category=sampling`、事件名 `code_graph_*`、循环内无 INFO 刷屏。MCP/对话 caller 事件在壳层，`tool_trace_payload` 只留计数分布——符合 LOGGING-SPEC 分工。

#### IN-03: D-26 跨仓能力仍依赖合成数据

`collect_cross_repo_impact` 与测试均承认生产 `CrossRepoApiCall` 零样本；不得宣传「跨仓 impact 已验证」。与 ROADMAP 挂 Phase 127 一致，记 INFO 以免误读本 review 为认可跨仓召回质量。

---

## Decision checklist (requested focus)

| Decision | Verdict |
|----------|---------|
| D-21 byte-identical dual-surface | Partial — impact 有哨兵；trace 无；`groups` 键类型见 LO-01 |
| D-19 never silently first candidate | Pass in graph+ORM resolve；跨仓未解析计 `unresolved` 不取第一条 |
| D-24 seed+depth + subgraph no-path | Pass for happy path；空种子跨仓见 HI-02 |
| D-23 degradation + numeric resolution_rate | Pass |
| D-27 mcp untouched | Bookkept；working tree `M mcp` is out-of-band |
| Observability | Mostly pass；shell `component` 用 `mcp_tools` / `agents.tools` 合理 |
| PAT / owner fail-closed | PAT `_begin` + conversation owner OK；仓级 ACL 前解析见 BL-01/ME-03/HI-01 |
| Fabricated cross-repo edges | Pass — ORM + peer `get_graph`，未沿 loader 同仓 `cross_repo` 边穿仓 |

---

_Reviewed: 2026-08-10T01:54:00+08:00_  
_Reviewer: Claude (gsd-code-reviewer)_  
_Depth: standard_  
