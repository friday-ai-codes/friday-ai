---
phase: 17-varref
plan: 04
subsystem: workflow-engine
tags: [var-ref, fail-fast, call-site-audit, regression, pytest, vitest]

# Dependency graph
requires:
  - phase: 17-varref
    plan: 01
    provides: "严格解析语义（TemplateResolutionError fail-fast）——本计划核查其在调用面统一生效"
  - phase: 17-varref
    plan: 02
    provides: "bulk-update short_id 收敛（回归范围）"
  - phase: 17-varref
    plan: 03
    provides: "前端引用生成统一收口（回归范围）"
provides:
  - "调用面核查闭环：19 个调用方文件 × 渲染时机 × 吞错风险 全覆盖结论（RESEARCH 假设 A1 关闭）"
  - "code_review 节点 chat_id 渲染前移（fail-fast 先于逐 MR LLM 副作用）"
  - "plan_generation 节点 similar_history_as_of 渲染移出吞错 try（解析失败不被静默改写）"
  - "后端 workflows 套件 + 前端单测全量回归全绿"
affects: [phase-18-trigger, phase-20-validation, phase-21-error-display]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "渲染先于副作用：config 模板统一在 execute() 入口段渲染，broken 引用零外部开销 fail-fast"
    - "best-effort try 收窄：可选增强功能的吞错分支不得包裹模板渲染调用"

key-files:
  created: []
  modified:
    - server/workflows/nodes/ai/code_review.py
    - server/workflows/nodes/ai/plan_generation.py

key-decisions:
  - "prompts/services.py 排除出核查清单：rg 命中仅为日志事件名 prompt_render_template（Jinja2 提示词中心），不调用工作流模板解析 API"
  - "except ValueError/Exception → NodeResult(status='failed', error=...) 按计划判为非吞错（fail-fast 等价，CONVENTIONS 正路），不强行 re-raise"
  - "全量冒烟的 113 个 workflows 之外失败经三重证据查证与本阶段无关（文件足迹不相交 + 失败测试零引用 workflows 模块 + 失败子系统与并发会话脏文件重合），不予处置"

patterns-established: []

requirements-completed: [VAR-01, VAR-02, VAR-03, VAR-04]

# Metrics
duration: ~28min
completed: 2026-06-13
---

# Phase 17 Plan 04: 调用面核查与全链路回归 Summary

**逐文件核查 19 个 render_template/get_template_value 调用方：17 个 OK、2 个违规已最小修复（code_review chat_id 渲染前移、plan_generation as_of 渲染移出吞错 try），后端 workflows 358 测试 + 前端 983 测试全绿，A1 假设闭环。**

## Performance

- **Duration:** ~28 min
- **Started:** 2026-06-12T17:00:10Z
- **Completed:** 2026-06-12T17:28:00Z
- **Tasks:** 2/2
- **Files modified:** 2

## Accomplishments

- 调用面核查清单全覆盖（见下节）：`rg -ln "render_template\(|get_template_value\(" server/workflows/nodes/ server/prompts/` 输出的全部文件逐一定性，零遗漏
- 两处违规最小修复，无节点重构：
  - `code_review.py`：`chat_id` 模板从 `_send_review_notification`（步骤 5，逐 MR LLM HTTP 调用之后）前移到 `execute()` 入口渲染，broken 引用不再浪费整轮审查开销（T-17-30 mitigate 落地）
  - `plan_generation.py`：`similar_history_as_of` 渲染移出 `except Exception: logger.warning` 的 best-effort try，`TemplateResolutionError` 直达 scheduler 结构化 error_message，不再被静默改写为"跳过相似历史注入继续执行"
- 全链路回归：后端 `tests/workflows/` 358 passed、前端 vitest 983 passed | 1 skipped，三个 wave-1 计划交叉影响收敛；零存量断言需要按新语义更新（wave 1 已就位），零 Pitfall 2 警示信号（无非 nodes 前缀扩大化失败）

## 调用面核查清单（A1 闭环证据）

清单来源：`rg -ln "render_template\(|get_template_value\(" server/workflows/nodes/ server/prompts/`，共 19 文件命中。`server/prompts/services.py` 的命中仅为日志事件名 `prompt_render_template`（Jinja2 提示词中心，不调用工作流解析 API），排除出核查范围。

| 文件（调用点行号） | 渲染时机 | 吞错风险 | 处置 |
|---|---|---|---|
| `nodes/base.py`（:382/:403 定义处；:695 normalize_repositories） | OK——:695 的调用方（branch/context_retrieval 等）均在副作用前 | OK——无 try 包裹，异常直达 scheduler | 无需修改 |
| `nodes/ai/prompt.py`（:332-333） | OK——execute 顶部，LLM 调用前（A1 抽样正例） | OK——无包裹 | 无需修改 |
| `nodes/ai/base_agent.py`（:622 chat_id） | OK——LLM 调用前，前置仅 DB 读（非副作用） | OK——`except ValueError` → `NodeResult(failed, error=msg)`（计划判定：非吞错） | 无需修改 |
| `nodes/ai/code_review.py`（原 :825 chat_id） | **违规**——渲染在步骤 5，逐 MR LLM HTTP 调用之后；broken 模板浪费整轮审查 | OK——渲染在吞错 try（:832 卡片发送 best-effort）之外，传播到外层 `except Exception → NodeResult(failed)` | **已修复**：前移到 `execute()` 入口渲染（`notification_chat_id`），经参数传入通知方法；commit `2e786679` |
| `nodes/ai/plan_generation.py`（:267/:275 hooks；:401；原 :409 as_of） | OK——:267/:275 经 base_agent 入口 hook 调用、:401 在 try 外，均先于副作用 | **违规**——:409 在 `except Exception: logger.warning` 内，解析失败被吞、空注入继续执行 | **已修复**：as_of 渲染移出 try（收窄 try 范围，`parse_as_of` 格式校验保持 best-effort 现状）；commit `2e786679` |
| `nodes/ai/variable_extractor.py`（:346 经 _get_input_text） | OK——execute:188 调用，先于 LLM 调用、在 swallow-try 之外 | OK——:342 `except: pass` 包裹的是 jsonpath 解析，render 在其外；外层 `except Exception → NodeResult(failed, error=f"AI 提取失败: {e}")`（非吞错） | 无需修改 |
| `nodes/ai/context_retrieval.py`（:153/:156/:157） | OK——execute 顶部，检索前 | OK——无包裹 | 无需修改 |
| `nodes/ai/delivery_knowledge_search.py`（:117/:139） | OK——检索调用前 | OK——:139 `except ValueError → NodeResult(failed)`（计划明确：非吞错） | 无需修改 |
| `nodes/control/approval.py`（:99-100） | OK——构建审批请求，先于落库/分发 | OK——无包裹 | 无需修改 |
| `nodes/control/loop.py`（:199 经 _resolve_list） | OK——execute:89 顶部，先于迭代执行 | OK——无包裹（`!= ""` 分支只处理合法空渲染结果） | 无需修改 |
| `nodes/control/wait_feishu.py`（:87/:89） | OK——execute 顶部，注册等待前 | OK——无包裹 | 无需修改 |
| `nodes/data/fetch_space_info.py`（:322 经 _resolve_value） | OK——execute:150 顶部，先于 DB 查询（且为只读） | OK——无包裹（jsonpath 分支的 try 不含 render） | 无需修改 |
| `nodes/git/branch.py`（:101/:118） | OK——git 操作前 | OK——无包裹 | 无需修改 |
| `nodes/git/pr.py`（:430-433/:624-625） | OK——平台 API / subprocess 前 | OK——无包裹 | 无需修改 |
| `nodes/integrations/chat_question.py`（:165-168） | OK——飞书发送前 | OK——无包裹 | 无需修改 |
| `nodes/integrations/feishu.py`（:79-82/:242-245） | OK——webhook / MCP 调用前 | OK——无包裹 | 无需修改 |
| `nodes/integrations/feishu_chat.py`（:78/:89-90/:175） | OK——飞书 API 调用前 | OK——无包裹 | 无需修改 |
| `nodes/integrations/feishu_workitem.py`（:129） | OK——execute 顶部，API 调用前 | OK——无包裹 | 无需修改 |
| `nodes/integrations/http.py`（:92/:94/:102/:160/:164） | OK——全部渲染先于 httpx 请求（且在请求 try 之外） | OK——无包裹 | 无需修改 |

**结论：A1 假设闭环。** 修复后全部调用方满足"渲染先于外部副作用 + 解析失败不被吞错"；`except ValueError → NodeResult(failed)` 形态（base_agent、delivery_knowledge_search、variable_extractor 外层）按计划判定为 fail-fast 等价正路。

## 全量冒烟分诊（Task 2 证据）

- `cd server && uv run pytest tests/workflows/ -q` → **358 passed**（Phase 17 全部改动面所在套件全绿）
- `cd web && pnpm vitest run` → **983 passed | 1 skipped**（前端全量无回归）
- `cd server && uv run pytest -q` 全量 → **113 failed / 4254 passed / 65 skipped**。113 个失败经查证全部与本阶段无关，证据三重：
  1. **文件足迹不相交**：Phase 17 四个计划的全部提交只触碰 `server/workflows/**`、`server/tests/workflows/**`、`web/src/**`；失败测试分布在 `test_orchestration_*`、`test_coding_*`、`test_chat_*`、`test_pr/commit/export_*`、`services/retrieval golden`、`test_dependency_cache` 等 25 个文件，零属于 `tests/workflows/`
  2. **零模块引用**：对 25 个失败测试文件 grep `workflows.engine|workflows.nodes|workflows.templates|render_template(|get_template_value(` → 零匹配，失败用例不消费本阶段任何改动
  3. **失败归因指向并发会话**：抽样失败信息为 agents/services 子系统的源码-测试漂移（如 orchestration state 多出 `user_parts` 字段、dependency_cache 卷命名格式变化），与工作区中并发会话未提交的脏文件（`agents/llm_factory.py`、`codegraph/*`、`knowledge/llm_grader.py`、`repositories/summary_service.py`、`subagent/api/callbacks.py`）同属一批子系统；已记录 `deferred-items.md`
- `prompts/services.py` 调用面无交叉破坏：全量跑中 prompts 相关测试零失败

## Task Commits

1. **Task 1: 调用面逐节点核查——渲染时机与吞错风险** - `2e786679` (fix)
2. **Task 2: 全链路回归——后端 workflows 套件 + 前端单测** - 无代码提交（零存量断言需更新；回归结果与分诊证据见上节）

## Files Created/Modified

- `server/workflows/nodes/ai/code_review.py` - chat_id 渲染前移到 execute() 入口（`notification_chat_id`），`_send_review_notification` 改为参数接收；顺带修复既有 I001 导入排序
- `server/workflows/nodes/ai/plan_generation.py` - `similar_history_as_of` 渲染移出 best-effort try，收窄 try 范围保持相似历史注入其余部分 best-effort 语义

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 修复 code_review.py 既有 I001 导入排序**
- **Found during:** Task 1
- **Issue:** 文件在 HEAD 即存在 ruff I001（导入块未排序），本计划修改该文件后 lint 不洁
- **Fix:** `ruff check --fix --select I001`（仅导入排序，最小 diff，与 17-01 对 scheduler.py 的处置一致）
- **Files modified:** server/workflows/nodes/ai/code_review.py
- **Commit:** 2e786679（随 Task 1 一并提交）

### 范围外发现（未修复，已记录 deferred-items.md）

- 后端全量冒烟的 113 个 workflows 之外失败（归因并发会话工作区脏文件/源码-测试漂移，证据见"全量冒烟分诊"节）

## Known Stubs

None — 无占位/stub。

## Threat Flags

无新增安全面。T-17-30（节点失败留半成品副作用）经 Task 1 核查 + code_review 渲染前移修复落地 mitigate；T-17-SC 维持 accept，零新依赖。

## Next Phase Readiness

- ROADMAP 四项成功标准的自动化部分全部为绿（workflows 套件 + 前端单测），阶段可进入 /gsd-verify-work
- "渲染先于副作用 + 失败不吞错"在全部 ~20 个调用方生效，Phase 18（trigger 注入）/ Phase 21（错误展示）可信赖该不变式
- 并发会话收敛后建议复跑 `uv run pytest -q` 确认 113 个无关失败消失

## Self-Check: PASSED

- FOUND: .planning/phases/17-varref/17-04-SUMMARY.md
- FOUND: commit 2e786679
- 核查清单覆盖 rg 输出全部 19 文件（nodes/ 18 + base.py；prompts/services.py 排除有据）
