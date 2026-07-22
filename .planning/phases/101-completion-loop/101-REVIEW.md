---
phase: 101-completion-loop
reviewed: 2026-07-22T05:35:00Z
depth: standard
files_reviewed: 19
files_reviewed_list:
  - server/delivery/services/__init__.py
  - server/delivery/services/coding_completion.py
  - server/mcp_tools/work_item_execution_service.py
  - server/mcp_tools/learning_case_extraction.py
  - server/mcp_tools/pr_review_capture.py
  - server/mcp_tools/models.py
  - server/mcp_tools/migrations/0011_learningcase_auto_extract.py
  - server/agents/call_source.py
  - server/system/models.py
  - server/workflows/nodes/ai/coding.py
  - server/orchestration/coding_graph.py
  - server/tools/handlers/__init__.py
  - server/tools/handlers/skill_steps.py
  - server/tools/migrations/0005_seed_platform_skills.py
  - server/tools/executor.py
  - server/tools/sources/skill.py
  - server/tools/views.py
  - web/src/types/workflow/schemas.ts
  - docs/guide/workflows.md
findings:
  blocker: 1
  high: 0
  medium: 2
  low: 3
  total: 6
status: findings
---

# Phase 101: Code Review Report

**Reviewed:** 2026-07-22T05:35:00Z
**Depth:** standard
**Files Reviewed:** 19（14 个 Phase 101 提交涉及的源文件全集，测试文件已通读、按规则不单列问题）
**Status:** findings

## Summary

审查范围为 Phase 101 全部 14 个提交触及的源文件（排除 `.planning/`；Phase 102 三个并发执行器的在飞文件未纳入）。重点核对了：回写/提炼/review-capture 三链路的 fail-soft 语义、幂等窗口、锚点接线是否重复触发、legacy `write_back` 缺键守门、MCP `write_back`/`retry_state` 零回归契约、脱敏与观测规范。

**总体判断**：完工闭环主体（LOOP-01/02/03/05）实现质量高——`_execution_results_markdown`/`_write_results_back` 模板逐字迁移核对无回归；三态守门与测试覆盖齐全（含"存量缺键零行为变化"用例）；fail-soft 兜底层层到位（回写/提炼/调度均不会阻断主流程，`run_in_background` 不 await Future）；幂等键 `source_session_id`（unique，`:pr_review` 后缀变体，64+10 ≤ 80）配合 `IntegrityError` 兜底覆盖并发重入窗口（重入仅可能重复烧一次 token，已在 docstring 显式接受）；LLM 输入料不脱敏与 `memory_distill` 锁定范式一致（产物入库前四字段过 `redact_secrets_in_text`），未发现新增凭证暴露面进入 LLM 输入。

但 LOOP-04（平台 Skill）引入了一个**授权绕过**：skill 步骤 handler 的权限主体 `user_id` 直接取自客户端参数透传，任何 PAT 持有者可冒充任意用户检索交付知识/learning case、并以他人名义上报项目知识。另有两个 MEDIUM（MCP 链归因恒为 system 的死代码路径；上游异常文本未脱敏入库）与三个 LOW。

## Narrative Findings (AI reviewer)

### Blocker

#### CR-01: skill 步骤权限主体 `user_id` 由客户端参数透传——横向越权 + 归因伪造

**File:** `server/tools/handlers/skill_steps.py:50-56`（`_resolve_user`）、`:119-121`、`:150-152`、`:234-236`；入口 `server/tools/views.py:57-61`
**Issue:** `/api/tools/execute/` 对任意 PAT 持有者开放，`arguments` 原样透传进 skill 步骤（`tools/sources/skill.py:53` `{**arguments, **step_args}`）。`search_delivery_knowledge` / `search_learning_cases` / `report_project_knowledge` 三个 handler 把 **客户端提供的 `user_id`** 解析为权限主体：
- `DeliveryKnowledgeSearchService.search_similar(user=...)` 按该用户的项目成员关系计算 `allowed_project_ids`（`knowledge/retrieval.py:47`）——调用者 A 传入用户 B 的 id 即获得 B 的项目可见范围，属横向越权读取；
- `report_project_knowledge` 以被冒充用户身份 `proposed_by=user, actor=user, initiated_by_user_id=str(user.id)` 落草稿，权限判定与审计归因全部被伪造。

"fail-closed" 注释只覆盖了"缺 `user_id` 拒绝"，没有覆盖"`user_id` 是否等于调用者"。同文件其余 MCP 视图的既有范式是服务端取 `request.user` 作主体（`mcp_tools/views.py:1707/2492` 等），本处偏离了该范式。种子 migration 0005 一执行，`pre_coding_research` 即刻可被利用。
**Fix:** 权限主体绝不信任请求体。在 `RemoteToolExecuteView.post` 强制覆写后再透传：

```python
# server/tools/views.py — post()
arguments = serializer.validated_data.get("arguments") or {}
arguments["user_id"] = str(request.user.id)  # 服务端权威覆写，忽略客户端传值
result = await execute_tool(tool_name, arguments, run=run)
```

同时把种子 skill/步骤 `input_schema` 里的 `user_id` 属性删掉（migration 数据可另行修补或在 handler 层注明该键仅接受服务端注入）。若未来存在无 HTTP 上下文的内部调用方，应显式传入受信 `user_id`，而非放开客户端输入。

### Medium

#### WR-01: MCP 链触发用户归因恒为 "system"——`run.user_id` 是不存在的字段（含 8046ec07 "LO-02 收尾" 实为 no-op）

**File:** `server/mcp_tools/work_item_execution_service.py:275`、`:341`、`:589`、`:601`；调用点 `server/mcp_tools/views.py:1571-1581`
**Issue:** 四处归因均写作 `str(run.user_id) if getattr(run, "user_id", None) else None`，但 `InteractionRun` 模型**没有 user 字段**（`interactions/models.py:27-67`，仅 `token_fingerprint`），表达式恒为 `None` → 公共层记 `system`。后果：
1. 违反 CONTEXT 观测锁定决策"MCP 链用 run user"与全局强制规范"每条日志/调用记录都要能回答谁触发的"——MCP 链的回写、提炼、入图事件全部归因 `system`，尽管 `ExecuteWorkItemRepoTasksView` 处 `request.user` 就是真实触发用户；
2. 提交 8046ec07 声称"LO-02 至此全部修复"，实际两处补传仍是恒 None 的死代码；
3. 同函数 L659 第三处 `aschedule_ingestion(IngestionRequest("mcp_technical_plan", ...))` 连参数都没传，与同文件其余投递不一致。

**Fix:** 给 `execute_work_item_repo_tasks` 增加 keyword 参数并由视图传入真实用户，替换所有 `run.user_id` 幻影读取：

```python
# views.py:1571
result = await execute_work_item_repo_tasks(
    run=run, ..., initiated_by_user_id=str(request.user.id),
)
# work_item_execution_service.py：将该值透传 _write_results_back /
# aextract_for_session 调度 / _ensure_coding_plan / 三处 aschedule_ingestion。
```

（`_ensure_coding_plan`/`_execute_one_task` 由多个入口调用，同样加 keyword 透传；无法拿到时保持 None→system 兜底。）

#### WR-02: 回写失败的上游异常文本未脱敏即入库（`technical_plan.error` / `comment_result`）

**File:** `server/delivery/services/coding_completion.py:290`、`:292`、`:309`、`:356-358`；落库点 `server/mcp_tools/work_item_execution_service.py:513-529`
**Issue:** `awrite_back` 把飞书客户端异常原文塞进返回 dict（`{"status": "error", "error": str(exc)}`），MCP 薄包装原样持久化到 `technical_plan.error` 与 `comment_result` JSONField。飞书 SDK/HTTP 异常文本可能携带请求 URL、上游响应体片段等敏感内容。模块 docstring 声称"异常文本仅入内部日志（structlog 已挂脱敏 processor）"，但该文本实际还流入 DB 留痕与 MCP 工具输出（`output["document_update"]`），DB 写路径**没有**任何脱敏（结构化日志有 processor 兜底、ledger 有 `redact_for_ledger`，唯独 model 字段直写没有）。虽然 str(exc) 直存是改造前旧行为（零回归契约范围内），但公共 service 是新代码，规范要求"上游响应/异常文本已脱敏，无明文泄漏"。
**Fix:** 在新 service 生成 error 字符串处统一包一层，不改变状态语义与返回外形：

```python
from common.logging import redact_secrets_in_text
...
document_update = {"status": "error", "error": redact_secrets_in_text(str(exc))}
```

（`:290/:292/:306/:309/:356/:358` 六处同款；`writeback_failed` 日志字段可继续依赖 processor。）

### Low

#### IN-01: 质量门 `_TEMPLATE_PREFIXES` 含单字 "无"——误杀 "无需/无论…" 开头的正常 solution

**File:** `server/mcp_tools/learning_case_extraction.py:57`、`:425`
**Issue:** `solution.startswith(("暂无", "无", ...))` 会把 "无需改动配置，直接……"、"无论走哪条链路……" 这类完全合法的 solution 判为模板废话 REJECT（且此时已烧完 LLM token）。"N-A" 前缀同理会匹配不到常见变体 "N.A."，但那是漏报不致命；单字 "无" 是明确误报源。
**Fix:** 单字前缀改为整串等值或"前缀 + 标点/结尾"判定：

```python
_TEMPLATE_EXACT = {"暂无", "无", "N/A", "N-A", "TODO", "待补充", "略"}
def _is_template(solution: str) -> bool:
    head = solution[:8]
    return solution in _TEMPLATE_EXACT or any(
        head.startswith(p) and (len(solution) == len(p) or solution[len(p)] in "，。,. ；;")
        for p in _TEMPLATE_EXACT
    )
```

（配合 `_MIN_FIELD_LEN=30`，实际只需把 "无"/"略" 从 startswith 判定中拿掉即可。）

#### IN-02: `awrite_back` 三元组守门较原实现多拦一类边缘输入——`retry_state` 语义有理论漂移（当前不可达）

**File:** `server/delivery/services/coding_completion.py:262-282`；对照原实现 `git show 5903922f^` 的 `_write_results_back`
**Issue:** 原 MCP 实现只要 `technical_plan.space` 存在就会尝试评论（`feishu_project_key` 为空串也会打到飞书 API → 失败 → `comment.status="error"` → PARTIAL 翻转 + `retry_state.retryable=True`）。新公共层在 `feishu_project_key` 空 / `work_item_type` 空 / `work_item_id is None` 时改记 `writeback_skipped` 双 skipped 返回——不再翻 PARTIAL、不再置 retry_state。由于 `McpWorkItemTechnicalPlan` 三字段 NOT NULL 且创建链路必填（`models.py:362-364`），此漂移在 MCP 现网数据下不可达；记录在案是为防未来出现空串 project_key 的脏数据时行为悄变。
**Fix:** 无需改码；建议在 `_write_results_back` docstring 的零回归契约注释里补一句该已知边界差异，避免后人误当回归修。

#### IN-03: 前端 zod `.default(true)` 会在存量节点任意一次编辑保存时物化 `write_back` 键——静默退出 legacy 三态

**File:** `web/src/types/workflow/schemas.ts:295`
**Issue:** 存量工作流的 ai_coding 节点 config 无 `write_back` 键（后端走 legacy 静默守门）。用户在流程编辑器里打开该节点、哪怕只改 `timeout_seconds` 保存一次，`aiCodingConfigSchema.parse` 的 `.default(true)` 就会把 `write_back: true` 写进 config——三态从"缺键（无三元组时 debug 级静默）"变为"显式 true（无三元组时记 caller 级 `writeback_skipped` 事件）"。实际回写行为不变（两态下都是"有三元组才回写"），仅观测噪音面变化，且用户在 UI 中可见开关状态，勉强算符合预期；但与 docs/guide/workflows.md "存量工作流升级后行为不变" 的表述存在细微出入（编辑过一次的存量节点会开始产 `writeback_skipped` caller 事件）。
**Fix:** 可接受现状；若要严格保持三态，用 `z.boolean().optional()` 并让表单 UI 层展示默认值，仅在用户显式操作开关时写键。至少在升级说明里补一句"编辑并保存过节点配置后视同显式开启"。

## 专项核查结论（未构成 finding 的验证项）

- **fail-soft 不阻断主流程**：三链路锚点均整块 try/except + `run_in_background` 不 await；`awrite_back` 方法级兜底 + 观测再兜底（`coding_completion.py:338-359`）；`aextract_learning_case`/`acapture_pr_review` 外层兜底齐全。验证通过。
- **幂等竞态窗口**：`aexists()` 预查 + `source_session_id` unique + `IntegrityError` 吞掉——并发重入最多重复一次 LLM 调用、库中仅一条，docstring 已声明接受。`:pr_review` 后缀与主键隔离正确（64+10 ≤ max_length 80）。验证通过。
- **锚点不重复触发**：workflow 单 wave / resume-wave 两路各自组 `session_repo_map` 且 `_finalize_and_notify` 每次节点收尾只走一遍；MCP/workflow/chat 三链路即便对同一 session 重复调度，也被幂等键收敛。lambda 循环变量均用默认参绑定，无 late-binding 错配。验证通过。
- **legacy `write_back` 缺键守门**：三态分支（`coding.py:1421-1437`）与 T-101-03-01 四个用例一一对应；缺键 + 无三元组走 `log.debug`，零 caller 事件。验证通过（前端物化风险见 IN-03）。
- **MCP `write_back`/`retry_state` 零回归**：模板与评论文案逐字迁移核对一致（`_table_cell`/表头/`未生成` 文案）；`retry_state` 仅 error 分支翻 PARTIAL、`failed_stage` 取既有值兜底 `execution_writeback`、成功路径不动；返回 `(document_update, comment)` 外形不变；`space is None` 双 skipped 短路防止公共层 project_key 反查引入新行为（`work_item_execution_service.py:493-511`）。验证通过（唯一理论边界差异见 IN-02）。
- **LLM 输入脱敏**：提炼/review 输入料（text_output/diff 摘要）未做 redact，与锁定范式 `memory_distill`（输入不脱敏、产物入库前脱敏）一致；产物四字段入库前全过 `redact_secrets_in_text`（`learning_case_extraction.py:297-300`），review 路径复用同函数。凭证不出现在新增 LLM 输入面。验证通过。
- **观测登记**：`learning_case_extraction`/`pr_review_capture` 两个 call_source 先登记后用码（枚举 + LOGGING-SPEC §4.1 + 计数守卫测试 33→35）；`arecord_llm_usage` 成功/异常双路带 ttft/duration/upstream_status；事件均带 category/component/initiated_by_user_id（MCP 链归因缺陷见 WR-01）。验证通过。
- **Skill 步级 trace**：`skill_step_started/completed/failed` 三态 + `duration_ms`，run 非 None 时步级 `arecord_tool_call`（ledger 自带脱敏）整段吞异常。验证通过。

---

_Reviewed: 2026-07-22T05:35:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
