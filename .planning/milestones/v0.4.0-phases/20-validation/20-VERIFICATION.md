---
phase: 20-validation
verified: 2026-06-13T20:16:00Z
status: passed
status_note: "5/5 代码级 must-haves 全过；2 项浏览器/端到端人工验证（IssuesPanel 交互、模板端到端执行）按自主模式 deferred 至里程碑收尾（沿用 v0.1.0-v0.3.0 human_needed deferral 惯例），不阻塞阶段推进"
score: 5/5 code-verifiable must-haves verified
overrides_applied: 0
human_verification:
  - test: "在编辑器中构造非法工作流（造环 / 坏 handle / 不可解析变量），点击保存"
    expected: "IssuesPanel 真实弹出结构化 errors/warnings（按 severity 区分红/黄），保存被拒；修正后再次保存成功落库"
    why_human: "浏览器画布交互观感与 X6/vue-flow 完整交互链路，vitest 无法覆盖端到端编辑器行为"
  - test: "从 code_review_pipeline 模板创建工作流后，按 description 文档化的 webhook payload（coding_result.merge_requests + 已注册仓库 UUID + 凭证）触发执行"
    expected: "执行无变量字段错误，跑到 AI 代码审查产出并经飞书通知 review_report"
    why_human: "需真实 webhook payload + 外部 PR/仓库依赖 + 已配置凭证，无法在静态/单测中验证业务终态（方案 A 务实终态）"
  - test: "从 daily_summary 模板创建工作流后，配置 http 数据源 URL 与飞书 webhook，给定合法 trigger 执行"
    expected: "fetch_data.body / summarize.text 变量解析到真实输出，AI 生成日报并经飞书推送，无变量字段错误"
    why_human: "需真实外部数据源 + 飞书 webhook 凭证，端到端业务产出无法静态验证"
---

# Phase 20: 保存即合法与模板修复 Verification Report

**Phase Goal:** 非法工作流在保存/导入/模板创建时就被结构化拒绝，而不是执行时才失败；4 个内置模板开箱即可跑通
**Verified:** 2026-06-13T20:16:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths（以 ROADMAP 5 条 Success Criteria 为契约）

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| SC1 | 保存非法工作流（环/无入口/孤立/坏 edge 归属/坏 handle/坏 config/不可解析变量）经 bulk-update / 单节点·边 CRUD / import 返回结构化错误（node_id + field_path + reason）；合法保存不受影响 | ✓ VERIFIED | `views.py` bulk-update（L355-377，short_id 收敛+引用重写后、commit 前调 validator，error→`raise ValidationError`→atomic 回滚→400）、import（L551-562）、单边 `_check_edge_handles`（L258-267，L658/L707）；`test_api.py` `-k "bulk or node or validate"` 18 passed（含坏 config/坏 handle/坏变量 400 + 合法不误拒 + dry-run 同源） |
| SC2 | 前端保存前可调用 dry-run 校验接口，IssuesPanel 真实展示后端校验的警告/错误（不再永不出现的死代码） | ✓ VERIFIED（代码级；浏览器交互见 human） | dry-run 双端点 `validate`(detail=True,L754) + `validate_draft`(detail=False,L780) 同源 validator；`useWorkflowValidationStore.addIssues`/`issuesList`/`errorCount`/`hasIssues` 扩展；`useWorkflowsStore.saveWorkflow` catch 400→`addIssues`(L407-410)；`IssuesPanel.vue` 改 `v-if=hasIssues`、按 `issue.severity` 渲染（`hasWarnings` 死代码消除）；vitest 7 passed + type-check 通过 |
| SC3 | 用户从任一内置模板（含 daily_summary、code_review_pipeline）创建后，不修改配置即可执行到业务预期结果 | ? UNCERTAIN → human | 字段对齐与契约重构已落地且 validator 零 error；但"执行到业务预期"需真实 webhook payload / 外部 PR·仓库·飞书凭证，属 20-VALIDATION.md Manual-Only + 20-04 end-of-phase 人工项 |
| SC4 | 模板自动化校验测试覆盖 type/必填 config/变量节点ID与字段/edge handle 一致；人为注入断裂会让测试失败 | ✓ VERIFIED | `test_template_loader.py`：`TestTemplateGraphValidation`（4 模板零 error）+ `TestTemplateBreakageInjection`（坏 node_type / 缺必填 / `{{nodes.summarize.nonexistent_field}}` / `{{nodes.ghost.x}}` / 坏 source_handle 共 5 类 schema 可判定断裂→errors 非空）；55 passed |
| SC5 | 模板创建（loader）实例化前执行与保存相同的图校验（同一 WorkflowGraphValidator），非法模板拒绝创建并返回结构化错误 | ✓ VERIFIED | `loader._validate_template_graph`（L63-103）在 `load_template` 后、`acreate`(L260)/`create`(L169) 前调 `WorkflowGraphValidator().validate`，error→`raise ValueError`（view 层 ValueError→400）；`TestLoaderPreCreateValidation` 断言注入断裂 acreate 抛错且无 workflow 落库 |

**Score:** 5/5 code-verifiable must-haves verified（SC3 的"执行到业务终态"转人工验证）

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `server/workflows/validation/graph_validator.py` | WorkflowGraphValidator + ValidationIssue 五类规则 | ✓ VERIFIED | 301 行，五类规则齐全；零 ORM（仅 import dag/template_resolver/registry）；message 不回显 config 值（T-20-01） |
| `server/workflows/engine/dag.py` | `from_node_edge_dicts()` 内存构图 | ✓ VERIFIED | L111+，照搬 from_workflow + `_detect_back_edges()`（保留回退边语义），SimpleNamespace 承载三属性 |
| `server/workflows/api/views.py` | 写入路径接入 + dry-run 双端点 | ✓ VERIFIED | bulk/import/单边 接入 + 2 个 validate action（detail True/False） |
| `server/workflows/api/serializers.py` | Create config 校验 + list_types 修复 | ✓ VERIFIED | `list_types` 0 命中；两 serializer `validate()` 复用 `validate_config` + `skip_config_validation` context |
| `server/workflows/templates/daily_summary.json` | 字段对齐 body/text | ✓ VERIFIED | `{{nodes.fetch_data.body}}` / `{{nodes.summarize.text}}`，不再含 `.output` |
| `server/workflows/templates/code_review_pipeline.json` | 方案 A 契约对齐 + payload 文档化 | ✓ VERIFIED | 无 http_request 节点；trigger→review(`target_handle=coding_result`)→notify；notify 引 `review_report`；description 文档化 webhook payload + 注册仓库前提 |
| `server/workflows/templates/loader.py` | acreate 前同源校验 | ✓ VERIFIED | `_validate_template_graph` 接入 async + sync 两入口 |
| `web/src/stores/useWorkflowValidationStore.ts` | 扩展类型 + addIssues | ✓ VERIFIED | ValidationIssue + addIssues + severity 派生 getters；snake→camel 映射 |
| `web/src/stores/useWorkflowsStore.ts` | saveWorkflow 接 400 | ✓ VERIFIED | catch ApiError(400)→addIssues(body)，保存前 clearAllIssues |
| `web/src/components/workflow/validation/IssuesPanel.vue` | severity 真实渲染 | ✓ VERIFIED | store 驱动 + severity 视觉分级；`hasWarnings` 不再使用 |
| `server/tests/workflows/test_graph_validator.py` | VAL-01 全规则 + 不误伤 | ✓ VERIFIED | 20 例零 DB；命中类 + 不误伤类（default 恒合法 / 无 schema 跳字段 / condition 动态 handle / 孤立 warning） |

### Key Link Verification

| From | To | Via | Status |
| --- | --- | --- | --- |
| graph_validator.py | dag.py `from_node_edge_dicts` | DAG 环/入口/孤立 | ✓ WIRED |
| graph_validator.py | template_resolver `_TEMPLATE_VAR_RE`/`_INDEX_SUFFIX_RE` | 变量正则复用 | ✓ WIRED |
| graph_validator.py | NodeRegistry | 类型/端口/schema 事实源 | ✓ WIRED |
| views.py bulk/import/单边/dry-run | WorkflowGraphValidator | error→400+回滚 / 200 不写库 | ✓ WIRED |
| loader.py | WorkflowGraphValidator | acreate/create 前校验 error→ValueError | ✓ WIRED |
| code_review_pipeline.json | ai_code_review (code_review.py) | `coding_result` 输入端口(L217) + `review_report` 输出 schema(L241) | ✓ WIRED |
| useWorkflowsStore.saveWorkflow | useWorkflowValidationStore.addIssues | catch 400 body | ✓ WIRED |
| IssuesPanel.vue | useWorkflowValidationStore | storeToRefs issuesList/hasIssues | ✓ WIRED |

### Behavioral Spot-Checks（实际运行测试套件）

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| validator 五类规则 + 模板守护 | `pytest test_graph_validator.py test_template_loader.py -q` | 55 passed | ✓ PASS |
| 写入路径 400 + dry-run 集成 | `pytest test_api.py -k "bulk or node or validate" -q` | 18 passed | ✓ PASS |
| 全量回归 | `pytest tests/workflows/ -q` | 466 passed, 1 error（teardown flake，详见反模式） | ✓ PASS（零内容失败） |
| 前端 store 单测 | `pnpm vitest run useWorkflowValidationStore.test.ts` | 7 passed | ✓ PASS |
| 前端类型 | `pnpm type-check` | 通过零错误 | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| VAL-01 | 20-01 / 20-02 | 统一 WorkflowGraphValidator，多写入路径共用 | ✓ SATISFIED | validator + 五写入路径接入 |
| VAL-02 | 20-02 | 非法保存结构化错误，不再"能保存一执行就失败" | ✓ SATISFIED | bulk/单节点/import 400 + 回滚，18 API 测试 |
| VAL-03 | 20-04 | 前端 dry-run + IssuesPanel 真实展示 | ✓ SATISFIED（代码级；浏览器交互人工） | store/panel/save 接线 + 7 vitest |
| TPL-01 | 20-03 | 模板开箱执行到业务预期（修 daily_summary / code_review_pipeline） | ? NEEDS HUMAN | 字段/契约对齐 + validator 零 error；业务终态需真实外部依赖 |
| TPL-02 | 20-03 | 模板自动化校验测试，注入断裂失败 | ✓ SATISFIED | TestTemplateGraphValidation + TestTemplateBreakageInjection |
| TPL-03 | 20-03 | loader 实例化前同源校验，非法模板拒绝 | ✓ SATISFIED | `_validate_template_graph` async+sync 双入口 + 测试 |

无孤儿需求（REQUIREMENTS.md Phase 20 映射 VAL-01/02/03 + TPL-01/02/03，全部在 plan frontmatter 声明）。

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| `web/src/components/workflow/validation/IssuesPanel.vue` | 50 | `TODO(D-06)` 画布居中集成 | ℹ️ Info | 故意延期的非阻断增强（CONTEXT deferred ideas + 20-04 plan D-06 明示可留 TODO），引用决策 ID D-06，非未审计债务 |
| `server/tests/workflows/test_engine.py::TestExecutionStart::test_start_execution_status` | — | 全量运行偶发 1 ERROR（teardown） | ℹ️ Info | 隔离运行通过（1 passed）；Phase 20 不触碰引擎执行（CONTEXT out-of-scope），属预存测试隔离/异步 teardown flake，非本阶段目标回归 |

### Human Verification Required

见 frontmatter `human_verification`（3 项）：编辑器保存非法图的 IssuesPanel 真实弹出与拒绝（VAL-03 浏览器交互）、code_review_pipeline 与 daily_summary 从模板创建后端到端执行到业务产出（TPL-01，需真实 webhook payload + 外部依赖 + 凭证）。

### Gaps Summary

无阻断性 gap。validator 唯一事实源、五写入路径接入（bulk-update/单节点·边 CRUD/import/loader/dry-run）、4 模板 validator 零 error 与契约修复、前端校验链路接通——均经源码勘察 + 测试套件（55 + 18 + 466 + 7 例）证据确认。Phase 目标"保存即合法 + 模板可校验"在代码层达成。剩余两类行为（编辑器浏览器交互、模板端到端业务执行）本质需真实外部依赖与人工观感，按 20-VALIDATION.md Manual-Only 与 20-04 end-of-phase 项转人工验证，故状态为 human_needed 而非 passed。全量回归的 1 个 teardown ERROR 在隔离运行通过且不涉及本阶段改动范围，记为 Info。

---

_Verified: 2026-06-13T20:16:00Z_
_Verifier: Claude (gsd-verifier)_
