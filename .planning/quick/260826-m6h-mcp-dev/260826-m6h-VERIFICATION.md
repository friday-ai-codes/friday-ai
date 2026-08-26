---
phase: quick-260826-m6h-mcp-dev
verified: 2026-08-26T08:36:00Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
re_verification: false
---

# Quick 260826-m6h: MCP 与本地 dev 可用性收口 Verification Report

**Phase Goal:** 补齐 MCP 客户端与服务端工具契约（12 个缺口全量同步），bump 并重建 `@friday-ai-codes/mcp` dist；修正确认门章程回灌测试为侧信道契约；验证后端 / MCP / 前端与本地 `make dev` 可用。

**Verified:** 2026-08-26T08:36:00Z  
**Status:** passed  
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | MCP 客户端 `FRIDAY_TOOLS` 与服务端 `server/mcp_tools/urls.py` 公开工具名集合逐字一致 | ✓ VERIFIED | 独立 Python 双向差集：`len(server)=49`、`len(client)=49`、`missing=[]`、`extra=[]`。12 个计划缺口名均在两侧出现。 |
| 2 | 每个新增工具有非空 description、object 型 inputSchema，且在 `TOOL_ANNOTATIONS` 有中文 title + 行为提示 | ✓ VERIFIED | `mcp/tests/server.test.ts` 断言 description>10、`inputSchema.type==object`、annotations `title` 含 ` · `、key 集合与工具名双向相等。源码：12 工具均有 schema；`apply_repo_association` 用 `generator`（非 readOnly），其余 11 个用 `query`。 |
| 3 | `@friday-ai-codes/mcp` 版本 0.6.0，`SERVER_VERSION` 对齐，`pnpm build` 后 dist 含全部新工具名 | ✓ VERIFIED | `mcp/package.json` `"version": "0.6.0"`；`mcp/src/server.ts` `SERVER_VERSION = '0.6.0'`；`mcp/dist/cli.js`（mtime 2026-08-26 16:18，gitignore）含 12 新名且含 `0.6.0`。 |
| 4 | `test_rejected_to_boundary_never_overwrites_human_confirmed` 断言正式字段冻结 + 侧信道增长，不再读 `draft_content.boundaries` | ✓ VERIFIED | 测试 L724–741：冻结 `positioning/owned_domains/boundaries/evolution/version` + `source==HUMAN_CONFIRMED` + `draft_content == {}` + `appendices/change_proposals` 非空且含「该类需求不落此仓」。模块 docstring L13–14 已改为侧信道表述。未改生产 writeback。 |
| 5 | 后端确认门相关测试、MCP vitest、前端 typecheck 通过；本地 `make dev` 热加载可用 | ✓ VERIFIED | 本轮独立复跑：`mcp` 3 files / 28 tests passed；`pytest … -k rejected_to_boundary` **4 passed**。HTTP：`:10240`→200、`:10241/api/`→401；PID cwd 为当前仓库 `web/` 与 `server/`。整文件 53 + charter 62、web type-check、stdio listTools=49 由执行阶段记录，本轮未全量复跑；与本任务 diff 范围一致且无反证。 |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `mcp/src/tools.ts` | 49 工具定义 + TOOL_ANNOTATIONS，含 `graph_query` | ✓ VERIFIED | 文件头写 49；`FRIDAY_TOOLS` 49 条；`ListTools` 映射 annotations。L1 存在 / L2 非 stub（12 新定义均有 schema）/ L3 `server.ts` import + list/call 接线。 |
| `mcp/package.json` | 版本 0.6.0 | ✓ VERIFIED | `"version": "0.6.0"`；测试跑在 `@friday-ai-codes/mcp@0.6.0`。 |
| `mcp/dist/cli.js` | 重建 CLI 含 12 新工具名 | ✓ VERIFIED | 本地产物存在（`dist/` gitignore）；12 名字符串全在。 |
| `mcp/tests/server.test.ts` | `toHaveLength(49)` + 12 名 `toContain` | ✓ VERIFIED | L20–40；annotations 无多余条目 L75–83。 |
| `server/tests/delivery/test_blueprint_gate_api.py` | 侧信道契约断言 | ✓ VERIFIED | 未提交 diff 仅 docstring + 该测试体；无 `draft_content["boundaries"]`。 |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | --- | --- | --- | --- |
| `server/mcp_tools/urls.py` | `mcp/src/tools.ts` | 工具名集合双向 diff | ✓ WIRED | 49=49，差集空。 |
| `server/mcp_tools/serializers.py` | `mcp/src/tools.ts` inputSchema | 新工具字段/required/enum/default | ✓ WIRED | 抽查：`graph_query` required/min/max/default 对齐 manifest+`GraphQueryRequestSerializer`；`impact_analysis`/`detect_changes`/`list_processes`/`get_process`/`rename_preview`/`trace_call_path` required 与 min/max 对齐；蓝图五工具 required/enum/`maxItems` 对齐对应 `*RequestSerializer`。XOR（symbol_id vs symbol）在 serializer `validate()`，schema 仅描述——与文件头「服务端是校验唯一真源」一致。 |
| `server/contracts/graph-query.v1.json` | `graph_query` 定义 | description + inputSchema + annotations | ✓ WIRED | description 逐字相同；`additionalProperties: false` + 字段约束对齐；title「代码图谱 · 单仓统一查询」+ query 四 hint 与 manifest annotations 一致。 |
| `charter_draft_writeback` 契约 | gate 测试 | appendices/change_proposals，不写 draft_content | ✓ WIRED | 测试改断言侧信道；生产代码本任务未改。 |
| `mcp/src/tools.ts` | `mcp/dist/cli.js` | tsdown build | ✓ WIRED | dist 含 `graph_query` 与 `route_blueprint_repos` 等 12 名。 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `createServer` ListTools | `FRIDAY_TOOLS` + `TOOL_ANNOTATIONS` | 模块常量，非空数组 | 是（49 条定义，非 `[]`） | ✓ FLOWING |
| `callFridayTool` | `POST /api/mcp/tools/{name}/` | 运行时 `fetch` + PAT | 是（透传 args，非静态空 JSON） | ✓ FLOWING |
| gate 测试 `fresh` | ORM `RepoCharter` | `rejected-to-boundary` 后 `objects.get` | 是（断言正式字段与侧信道） | ✓ FLOWING |

MCP 工具定义本身不渲染 UI；动态数据在 IDE 调用时走 HTTP，源为 Django 视图而非客户端硬编码。

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| 工具名差集为空 | `python3` urls.py vs tools.ts | 49=49 missing/extra 空 | ✓ PASS |
| MCP 单测 | `cd mcp && pnpm test` | 3 files, 28 passed | ✓ PASS |
| 确认门 rejected 四用例 | `pytest … -k rejected_to_boundary` | 4 passed, 79.76s | ✓ PASS |
| dist 含 12 新名 | 读 `mcp/dist/cli.js` | missing=[]，含 `0.6.0` | ✓ PASS |
| dev HTTP | curl `:10240/` / `:10241/api/` | 200 / 401；cwd 当前仓库 | ✓ PASS |
| stdio listTools 端到端 | （本轮未复跑 MCP stdio 进程） | 执行阶段声称 count=49/version=0.6.0 | ? SKIP（代码路径已接线；进程级由执行记录） |

### Probe Execution

| Probe | Command | Result | Status |
| ----- | ------- | ------ | ------ |
| — | — | 计划未声明 `scripts/*/tests/probe-*.sh` | SKIPPED |

### Requirements Coverage

PLAN 声明的 ID 不在 `.planning/REQUIREMENTS.md`（quick 本地契约），按实现覆盖：

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| MCP-SYNC-01 | 260826-m6h-PLAN | 客户端与 urls 工具名全量同步 | ✓ SATISFIED | 双向差集空 + 12 名存在 |
| MCP-BUILD-01 | 260826-m6h-PLAN | 0.6.0 bump + dist 重建 | ✓ SATISFIED | package/SERVER_VERSION/dist |
| CHARTER-GATE-TEST-01 | 260826-m6h-PLAN | 侧信道断言替代 draft_content.boundaries | ✓ SATISFIED | 测试 + 4 passed |
| DEV-VALIDATE-01 | 260826-m6h-PLAN | 验证命令与本地 dev | ✓ SATISFIED | mcp test + HTTP/cwd；web type-check 执行阶段通过且本任务未改 `web/` |

无 REQUIREMENTS.md 映射到本 quick 的孤儿项。

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| `mcp/tests/server.test.ts` | 20–21 | 硬编码 `toHaveLength(49)`，未 import urls.py | ℹ️ Info | 改名但保持 49 可能漏检；Task 3 差集闸已独立跑过。 |
| `mcp/src/tools.ts` | impact/rename/trace | JSON Schema 未表达 XOR | ℹ️ Info | 与既有 `find_related_chunks` 模式相同；服务端 400 兜底。 |
| `mcp/src/tools.ts` | 896 | `start_repo_research` 标 query/readOnly | ℹ️ Info | 与 urls.py「前四个 dry-run / 只读提案面」及 PLAN 一致；若产品上会起容器，属契约分类而非本任务漏实现。 |

未发现 `TBD`/`FIXME`/`XXX` 债务标记。未改生产 charter/writeback（符合计划禁令）。

### Human Verification Required

无。PLAN 无 `<human-check>`。dev 健康可用 curl + `lsof` cwd 程序化确认。Cursor 会话级 MCP 工具缓存刷新是操作说明，不是本任务代码缺口。

### Gaps Summary

无阻塞缺口。目标在代码中成立：49 工具名与后端公开路由逐字一致，0.6.0 dist 含 12 新工具，确认门 human_confirmed 回归按 append-only 侧信道断言且本轮 4 用例通过，当前仓库上的 10240/10241 进程健康。

**Inversion 抽查（未构成 FAIL）：** (1) dist 未入库——预期 gitignore，本地文件已核。 (2) vitest 不读 urls.py——已用独立差集补。 (3) 测试曾依赖 SUMMARY「62 passed」——本轮至少复跑 rejected 子集与 MCP 全量。

---

_Verified: 2026-08-26T08:36:00Z_  
_Verifier: Claude (gsd-verifier)_
