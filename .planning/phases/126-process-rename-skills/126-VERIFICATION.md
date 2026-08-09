---
phase: 126-process-rename-skills
verified: 2026-08-09T21:48:16Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
re_verification: false
gaps: []
deferred:
  - truth: "npm publish @friday-ai-codes/skills with friday-impact / friday-refactoring"
    addressed_in: "Deferred (D-15) — ops follow-up"
    evidence: "CONTEXT D-15：验收以源目录存在 + hash 绿 + 容器注入测为准；npm bump 不阻断相位"
  - truth: "mcp/ npm client entries for list_processes / get_process / rename_preview"
    addressed_in: "Deferred (D-16 / 122 D-27)"
    evidence: "本相位只动 server/mcp_tools 薄壳；npm 客户端漂移记账，不改 mcp/ submodule"
---

# Phase 126: 执行流 + rename_preview + skills Verification Report

**Phase Goal:** 以 `Endpoint` 为入口的执行流可追踪可查询并回填影响面叙事层；改名前有只读双源清单；工作流经验固化为 skill 对内外分发

**Verified:** 2026-08-09T21:48:16Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | ------- | ---------- | -------------- |
| 1 | Endpoint 正向 BFS → `ProcessTrace`；硬闸 maxDepth=10 / maxBranching=4 / minSteps=3 / conf≥0.5 + 去重；环/async 显式标注（SC1 / EXEC-01 / D-01..D-04） | ✓ VERIFIED | `ProcessTrace` 模型+`0013` 加表迁移（无 Endpoint FK）；`process_trace.py` 常量与 `collect_process_paths`；环标 `cycle`、async 标 `boundary: async_dispatch`；WR-01 去掉 `seen_global`（`MAX_PATHS_PER_ENTRY`/`MAX_FRONTIER_SIZE`）；WR-04 `_ASYNC_BOUNDARY_RE`；`durable_process_rebuild` on `QUEUE_GRAPH` + `process:{repo}:{branch}` lock；社区失败仍链式 enqueue（WR-02） |
| 2 | 执行流 `intra_community` / `cross_community`（或 unknown 降级）；可经 MCP/对话查询（SC2 / EXEC-02 / D-05/D-06） | ✓ VERIFIED | `CommunityClass` 封闭枚举 + blank 降级；`run_list_processes` / `run_get_process`；MCP urls `tools/list_processes/` `tools/get_process/`；agents `@tool` 薄壳 call-through 测绿 |
| 3 | `detect_changes` / `impact` 回填 `affected_processes`；MR `## 影响面` 渲染受影响执行流（SC3 / EXEC-03 / D-07/D-08） | ✓ VERIFIED | `assemble_affected_processes` 单方言；`code_graph_tools` 两处调用；`impact_report`「受影响执行流」段；源码无「待 Phase 126」占位（`test_impact_report_source_no_phase126_placeholder`） |
| 4 | `rename_preview` 只读双源清单（graph + grep_mirror），`graph\|text_search`、context、按文件、coverage_limitations；`applied` 恒 false（SC4 / RENAME-01 / D-09..D-12） | ✓ VERIFIED | `rename_preview.py` + `run_rename_preview` 经 `grep_mirror`+exclusion；成功/失败/GraphError 路径均 `applied: False`（WR-05）；MCP/agents/knowledge_tools 白名单；无 apply/rewrite API |
| 5 | `friday-impact` / `friday-refactoring` 进 skills 同源分发；`SKILL_NAMES` + sha256 一致（SC5 / SKILL-01 / D-13..D-15） | ✓ VERIFIED | 源目录 + `task/assets` 镜像 sha256 一致；`sync_skills.py` / `test_skills_injection.py` 含二者；`TestSkillsHashConsistency` 8 passed |

**Score:** 5/5 truths verified

### Review WR Fixes (126-REVIEW → 126-REVIEW-FIX)

| WR | Claim | Status | Evidence |
| --- | ----- | ------ | -------- |
| WR-01 | 去掉全局 `seen_global`，钻石交替终点可探索 | ✓ VERIFIED | 代码无 `seen_global`；path_ids 环检测 + 路径预算；spot-check diamond → terminals `{D,F}` |
| WR-02 | 社区硬失败仍 enqueue Process | ✓ VERIFIED | `tasks_impl` finally-style best-effort；`test_community_success_chains_process_enqueue` 断言 failure 仍链式 |
| WR-03 | RetrievalTrace 计 rename edits | ✓ VERIFIED | `tool_trace_payload` `elif tool == "rename_preview"` → `total_edits`/`files_affected` |
| WR-04 | async 边界非裸子串 | ✓ VERIFIED | `_ASYNC_BOUNDARY_RE`；`delay_response`/`group_sender` 不截断；`foo.delay` 命中 |
| WR-05 | GraphError 亦 `applied: false` 软信封 | ✓ VERIFIED | `run_rename_preview` + MCP/agents 壳 |
| WR-06 | max_processes 按 cross_community / step_count 排序后截断 | ✓ VERIFIED | `_build_process_rows` sort+slice + `truncated_by_max_processes` |

### Frozen Surfaces (D-16)

| Surface | Status | Evidence |
| -------- | ------ | -------- |
| `repo_router_v2.py` | ✓ VERIFIED | AST：process_trace/rename_preview/process_enqueue 无 import；`git log --grep=126-` 无触碰该路径；`test_frozen_surface_126` 绿 |
| `mcp/` submodule | ✓ VERIFIED | 同上；仅 `server/mcp_tools` adapter |

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | npm publish skills bump | D-15 Deferred | 验收不以 npm 发版为准 |
| 2 | mcp/ npm 客户端新工具名 | 122 D-27 / D-16 | 本相位只记账漂移 |

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/codegraph/models.py` | `ProcessTrace` | ✓ VERIFIED | class + unique_together；无 `class Process` |
| `server/codegraph/migrations/0013_processtrace.py` | 加表 | ✓ VERIFIED | CreateModel only；FK 仅 repository |
| `server/services/code_graph/process_trace.py` | BFS+rebuild | ✓ VERIFIED | 669 行；`get_graph_service`；硬闸导出 |
| `server/services/process_enqueue.py` | QUEUE_GRAPH enqueue | ✓ VERIFIED | `idempotency_key=process:{id}:{branch}` |
| `server/durable/tasks_impl.py` | run_process_rebuild + chain | ✓ VERIFIED | success+failure enqueue |
| `server/services/code_graph/affected_processes.py` | assemble helper | ✓ VERIFIED | 单方言纯函数 |
| `server/services/code_graph/rename_preview.py` | 双源内核 | ✓ VERIFIED | `applied: False` 硬锁 |
| `server/services/code_graph/impact_report.py` | 执行流段 | ✓ VERIFIED | 「受影响执行流」 |
| `server/services/code_graph_tools.py` | run_list/get/rename + 回填 | ✓ VERIFIED | 编排+观测 |
| MCP/agents shells + urls | 双面薄壳 | ✓ VERIFIED | urls + `@tool` + chat_runner 注册 |
| `task/core/knowledge_tools.py` | rename 白名单 | ✓ VERIFIED | `name: rename_preview` |
| skills + assets + sync | SKILL-01 | ✓ VERIFIED | hash match |
| Wave 0 七测试文件 | 验收节点 | ✓ VERIFIED | 无 skip；收集并执行绿 |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| community rebuild | `enqueue_process_rebuild` | success + failure | ✓ WIRED | WR-02 |
| `rebuild_processes` | `get_graph_service().get_graph` | barrel | ✓ WIRED | 无 loader/cache/router |
| `run_impact` / `run_detect_changes` | `assemble_affected_processes` | single helper | ✓ WIRED | lines ~950 / ~1500 |
| MCP/agents | `run_list_processes` / `run_get_process` / `run_rename_preview` | thin shell | ✓ WIRED | call-through tests |
| rename text half | `grep_mirror` + exclusion | no bare walk | ✓ WIRED | orch + static test |
| skills source | `task/assets/skills` | sync + sha256 | ✓ WIRED | hash equal |
| `build_impact_report_section` | `affected_processes` | 受影响执行流 | ✓ WIRED | empty → 短声明 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| ProcessTrace persist | `steps` / `community_class` | Endpoint → BFS → SymbolCommunity 对账 | 合成图+ORM 测绿 | ✓ FLOWING |
| `affected_processes` | envelope field | impact/detect hits ∩ ProcessTrace.steps | assemble 单测 + orch 接线 | ✓ FLOWING |
| rename_preview `files` | dual-source edits | graph sites + grep_mirror hits | merge 测 + orch | ✓ FLOWING |
| impact_report 段 | markdown lines | envelope.affected_processes | 有数据清单 / 空态声明 | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Scoped process/rename/frozen/impact_report | `uv run pytest` 8 files under `server/tests/...` | 42 passed | ✓ PASS |
| Skills hash/injection | `cd task && uv run pytest tests/test_skills_injection.py -q` | 8 passed | ✓ PASS |
| Diamond alternate spines | inline `collect_process_paths` on E→A/C/D vs E→B/C/F | terminals D+F | ✓ PASS |
| Async false-positive | `is_async_boundary_name('delay_response')` | False | ✓ PASS |
| Skills sha256 | python hashlib source vs assets | match both skills | ✓ PASS |

### Probe Execution

| Probe | Command | Result | Status |
| ----- | ------- | ------ | ------ |
| — | — | Phase declares no `scripts/*/tests/probe-*.sh` | SKIPPED |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| EXEC-01 | 126-02 | Endpoint BFS → ProcessTrace + 硬闸 | ✓ SATISFIED | model/migration/BFS/durable/tests |
| EXEC-02 | 126-02/03 | community_class + MCP/对话查询 | ✓ SATISFIED | classify + list/get dual-face |
| EXEC-03 | 126-03 | affected_processes → MR 段 | ✓ SATISFIED | assemble + impact_report |
| RENAME-01 | 126-04 | 只读双源 rename_preview | ✓ SATISFIED | kernel+orch+shells+whitelist |
| SKILL-01 | 126-05 | impact/refactoring skills 同源 | ✓ SATISFIED | submodule+sync+hash |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| — | — | No TBD/FIXME/XXX in phase production kernels | — | — |
| `test_frozen_surface_126.py` | ~76-101 | git `--grep=126-` fragile (IN-02) | ℹ️ Info | AST 主守卫仍有效；不阻断目标 |
| `process_enqueue.py` | — | 缺 `*_started` lifecycle（IN-01） | ℹ️ Info | completed/failed 存在；与 community enqueue 同构 |

### Human Verification Required

None required for phase gate. MR 真仓渲染与 MCP 实机 PAT 调用可由运维抽检，但不阻塞 SC1–5（已有自动化钉死契约）。

### Gaps Summary

无阻断缺口。ROADMAP SC1–5、REQUIREMENTS EXEC-01..03 / RENAME-01 / SKILL-01、CONTEXT D-01..D-16 核心验收、以及 REVIEW WR-01..06 修复均在代码与 scoped 测试中得到证据。D-15 npm 发版与 mcp/ npm 客户端漂移为显式 Deferred，不计入 gaps。

---

_Verified: 2026-08-09T21:48:16Z_
_Verifier: Claude (gsd-verifier)_
