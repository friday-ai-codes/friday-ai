---
phase: 17-varref
verified: 2026-06-12T18:05:00Z
status: human_needed
score: 18/18 must-haves verified
overrides_applied: 0
re_verification: false
human_verification:

  - test: "端到端所选即所得：在流程编辑器中用变量选择器选中上游节点输出引用，保存工作流后执行，确认该引用取到实际值"
    expected: "执行成功且引用位置注入了上游节点的真实输出值；构造一个坏引用（如手改成不存在的节点 ID）再执行，节点显式失败且错误信息（中文）指明引用与原因"
    why_human: "完整 UI 流程（picker 选中 → bulk-update 保存 → 真实执行 → 值注入）跨前后端与运行时，grep 与单测只能验证各环节机制，无法程序化确认端到端体验"

  - test: "端口复制缺 short_id 防护：对一个尚未保存（store 中无 shortId）的新节点点击端口复制按钮"
    expected: "出现 toast '节点缺少 short_id，请先保存工作流'，剪贴板不写入任何 UUID 形式引用；端口路径提示区显示'保存工作流后可用'"
    why_human: "toast 弹出与剪贴板行为是运行时 UI 交互，无法静态验证"

  - test: "运行时变量选择器双键去重：打开一个已有执行结果的工作流的运行时变量选择器（node_outputs 含 UUID 与 short_id 双键）"
    expected: "同一字段只展示一条（short_id 形态），不重复出现 UUID 形态条目"
    why_human: "WR-02 修复改为 JSON.stringify 内容判等，其有效性依赖后端 snapshot 实际输出的 node_outputs 数据形态，需真实执行数据确认"
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: human_needed
---

# Phase 17: 变量引用链路修复 Verification Report

**Phase Goal:** 用户在变量选择器里选中的引用，保存后执行时所选即所得——可解析则取到值，不可解析则显式报错指明原因
**Verified:** 2026-06-12T18:05:00Z（UTC，本地 2026-06-13 02:05 +8）
**Status:** human_needed（自动化全部通过，3 项 UI/端到端行为待人工确认）
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

ROADMAP Success Criteria（契约，SC1-4）+ 各 PLAN frontmatter truths（去重后细化项）。

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SC1: 变量选择器选中引用保存（bulk-update）后执行保证可解析——客户端 short_id 落库或服务端重写 config 引用 | ✓ VERIFIED | `views.py:86` `_SHORT_ID_RE`、`:169-211` `_resolve_short_ids`（采纳/保留/重生成）、`:295` `rewrite_template_refs` 全节点重写；`test_bulk_update_short_id.py`（401 行）`test_invariant_save_implies_resolvable`（:180）锁定不变式 |
| 2 | SC2: 解析失败（节点不存在/字段不存在/未知前缀）显式失败，错误指明引用与原因，无静默空串/字面量保留 | ✓ VERIFIED | `template_resolver.py` 四分类 reason（node_not_found/field_not_found/unknown_prefix/missing_field_path）中文报错；`scheduler.py:1019-1033` 结构化捕获；`test_error_handling.py:651` 集成测试断言 status=failed + JSON 可解析 |
| 3 | SC3: 三入口（变量选择器/端口复制/SmartInput）生成统一 short_id 格式引用 | ✓ VERIFIED | `variableRef.ts` 四构造函数；`VariablePicker.vue`/`NodePortsDisplay.vue`/`useDesignTimeVariables.ts`/`useNodeSchema.ts` 全部 import 使用（grep 命中 6 文件）；三入口零手写拼接残留 |
| 4 | SC4: 嵌套路径 `{{nodes.x.data.name}}` 可取值，render/get_template_value 专项单测覆盖错误 ID/未知前缀/UUID vs short_id/嵌套路径 | ✓ VERIFIED | `_resolve_nodes_path` dict 键 + list 数字索引下钻断路即抛；`test_template_resolver.py`（466 行）10 组场景 class：TestNestedPath/TestDualKeyCompat/TestUnknownPrefix 等全在 |
| 5 | render_template 与 get_template_value 共享同一解析核心，错误语义一致 | ✓ VERIFIED | `base.py:380/:401` 两 API 薄委托 `workflows.engine.template_resolver`；value 模式单测 TestMissingFieldPath.test_value_mode_same_semantics |
| 6 | input./trigger./global./context./config. 字段缺失维持现状空串，有现状锁定测试 | ✓ VERIFIED | resolver 模块 docstring 明示定界 + `_dig_lenient`；TestNonNodesPrefixStatusQuo（:311）参数化锁定 render/value 双模式 |
| 7 | 解析失败 error_message 为中文一句话 + 结构化 JSON（reference/reason/available/template），最后一行可 JSON.parse | ✓ VERIFIED | `scheduler.py:1023-1032` json.dumps 四键 + ensure_ascii=False + `f"{_exc}\n{structured}"`；集成测试断言 json.loads(last_line) |
| 8 | short_id 缺失（新节点）/冲突/非法时服务端重生成并同事务重写全工作流引用（含 $nodes. JSONPath 形式） | ✓ VERIFIED | `views.py:211` generate_unique_short_id；`loader.py:83-85` 正则覆盖 `$nodes.`/`$.nodes.` 与 `[.\[]` 尾断言（IN-04）；测试覆盖冲突/非法/重命名场景 |
| 9 | 不变式"保存成功 ⇒ 引用可解析"有专项自动化测试 | ✓ VERIFIED | test_invariant_save_implies_resolvable：收集全部 config 引用标识符断言 ∈ short_id ∪ UUID 集合 |
| 10 | update 节点 payload 不含 short_id 不被重置（存量不回退） | ✓ VERIFIED | `_resolve_short_ids` "update 节点 payload 缺失 → 保留 DB 现值"；专项用例覆盖 |
| 11 | 引用字符串由单一前端 util 构造，各入口 import 同一函数 | ✓ VERIFIED | `web/src/utils/variableRef.ts` 唯一构造点（buildNodePath/buildNodeRef/buildPrefixPath/buildPrefixRef + isLikelyUuid，无多余导出） |
| 12 | 非节点前缀（input/trigger/global）生成点全部收口 buildPrefixPath，无手写拼接 | ✓ VERIFIED | VariablePicker :111/:129/:147 动态 + :209-232 预设字面量、useDesignTimeVariables :204/:235、useNodeSchema getInputPath 全经 util；`rg "path: \`(trigger|global|input)\.\$"` 零命中 |
| 13 | short_id 缺失时任何入口不产 UUID 引用（禁用 + 提示，零静默回退） | ✓ VERIFIED | NodePortsDisplay copyVariablePath 空 shortId → toast 报错 return；useDesignTimeVariables 跳过 nodes.* 生成；useNodeSchema 返回空串；`slice(0, 8)` 在三入口零残留（全仓命中均为无关 UI 展示截断） |
| 14 | bulk-update payload 含 short_id（前端权威值上送） | ✓ VERIFIED | `useWorkflowsStore.ts:194` `short_id: node.shortId` |
| 15 | 运行时选择器不因 node_outputs 双键重复展示同一字段 | ✓ VERIFIED（机制） | VariablePicker :166-177 isLikelyUuid + JSON.stringify 内容判等（WR-02 修复后），仅 UUID 键无对应时保留；真实数据形态效果列人工项 3 |
| 16 | 全部调用方节点渲染先于外部副作用（A1 闭环） | ✓ VERIFIED | 19 文件核查清单落 17-04-SUMMARY；两处违规已修：`code_review.py:307` notification_chat_id 前移 execute() 入口、`plan_generation.py:408-410` as_of 渲染移出 try（commit 2e786679，代码核实） |
| 17 | 无节点用裸 except 吞 TemplateResolutionError 成空串/默认值继续执行 | ✓ VERIFIED | 核查清单逐文件结论；plan_generation as_of 移出吞错 try 已核实；`except ValueError → NodeResult(failed)` 形态按计划判定为 fail-fast 等价 |
| 18 | 后端 workflows 套件与前端单测在新语义下全量通过 | ✓ VERIFIED | 本次实跑：`uv run pytest tests/workflows/ -q` → **368 passed**；`pnpm vitest run src/utils/__tests__` → **17 passed** |

**Score:** 18/18 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `server/workflows/engine/template_resolver.py` | 解析核心 ≥120 行，零 Django 导入 | ✓ VERIFIED | 338 行；`rg "^from django|^import django"` 零命中；TemplateResolutionError 四属性 + 继承 ValueError |
| `server/tests/workflows/test_template_resolver.py` | 专项单测 ≥150 行 | ✓ VERIFIED | 466 行，10 组场景 class + ExecutionContext 集成层 + WR-01 回归用例 |
| `server/tests/workflows/test_bulk_update_short_id.py` | VAR-01 集成测试 ≥120 行 | ✓ VERIFIED | 401 行，含不变式/越权/响应契约/CR-01/IN-02/IN-03 回归用例 |
| `server/workflows/templates/loader.py` | `def rewrite_template_refs` 公共化 | ✓ VERIFIED | :63 公共函数；`_rewrite_template_refs` 旧私有名全仓零残留 |
| `web/src/utils/variableRef.ts` | 导出 4 构造函数 | ✓ VERIFIED | 65 行，4 函数 + isLikelyUuid（Plan 03 Task 3 允许的追加），无多余导出 |
| `web/src/utils/__tests__/variableRef.test.ts` | 单测 ≥40 行 | ✓ VERIFIED | 86 行，17 用例实跑全绿 |
| `.planning/phases/17-varref/17-04-SUMMARY.md` | 调用面核查清单 | ✓ VERIFIED | 19 文件 × 渲染时机 × 吞错风险 × 处置全表落档 |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `base.py` | `template_resolver.py` | render_template/get_template_value 薄委托 | ✓ WIRED | :380/:401/:409 延迟 import（防循环依赖）+ `_build_resolution_sources` |
| `scheduler.py` | `template_resolver.py` | except 分支识别 TemplateResolutionError | ✓ WIRED | :19 顶部 import；:1020 isinstance + 结构化写 last_error + `_deterministic_error` 短路重试（IN-01） |
| `views.py` | `loader.py` | bulk-update 事务内调用重写引擎 | ✓ WIRED | :77 import + :295 调用 |
| `views.py` | `common/short_id.py` | 冲突/缺失重生成 | ✓ WIRED | :20 import + :211 调用 |
| `useWorkflowsStore.ts` | bulk-update payload | toBackendNodes 上送 short_id | ✓ WIRED | :194 |
| `NodePortsDisplay.vue` | `variableRef.ts` | 端口复制 buildNodeRef | ✓ WIRED | :15 import + :57 调用 + UUID→shortId store 查表（:36） |
| `useDesignTimeVariables.ts` | `variableRef.ts` | picker/SmartInput 路径构造 | ✓ WIRED | :5 import，buildNodePath ×2 + buildPrefixPath ×2 |
| 节点调用面（19 文件） | `template_resolver.py` | 渲染先于副作用、不吞错 | ✓ WIRED | 17-04 核查清单 + 2 处修复代码核实 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `template_resolver.resolve_path` | previous_outputs 等 6 源 | `base.py _build_resolution_sources`（execution 真实上下文） | Yes | ✓ FLOWING |
| `scheduler` error_message | TemplateResolutionError 四属性 | 异常实例真实字段，json.dumps 落 `NodeExecution.amark_failed` | Yes | ✓ FLOWING |
| `_get_global_values` | global_params | WR-01 修复：模型字段兜底 + context 镜像覆盖（`base.py:507-509`） | Yes | ✓ FLOWING |
| `NodePortsDisplay` shortId | store 节点 shortId | `workflowsStore.getNodeById(props.nodeId)` 查表，非 props 直插 | Yes | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| 后端 workflows 套件（新语义全量） | `cd server && uv run pytest tests/workflows/ -q` | 368 passed, 37.85s | ✓ PASS |
| 前端 util 套件（variableRef 等） | `cd web && pnpm vitest run src/utils/__tests__` | 17 passed | ✓ PASS |
| 解析失败集成契约（含在套件内） | `test_error_handling.py::TestTemplateResolutionError` | passed（含 json.loads 最后一行断言） | ✓ PASS |

注：按编排指示未跑后端全量套件（并发会话存在无关失败，17-04-SUMMARY 已三重证据分诊归档 deferred-items.md）。

### Probe Execution

无 probe 声明（PLAN/SUMMARY 均未引用 `scripts/*/tests/probe-*.sh`）——SKIPPED（不适用）。

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| VAR-01 | 17-02, 17-03, 17-04 | short_id 保存同步/重写，保存后引用可解析 | ✓ SATISFIED | Truths 1/8/9/10/14；不变式测试 |
| VAR-02 | 17-01, 17-04 | 解析失败显式报错指明引用与原因 | ✓ SATISFIED | Truths 2/5/7/16/17；resolver 四分类 + scheduler 结构化 |
| VAR-03 | 17-03, 17-04 | 前端三入口统一 short_id 格式 | ✓ SATISFIED | Truths 3/11/12/13；单一 util 收口 |
| VAR-04 | 17-01, 17-04 | 嵌套路径 + 解析器专项单测 | ✓ SATISFIED | Truths 4/6；466 行专项测试 |

REQUIREMENTS.md 映射 Phase 17 的需求恰为 VAR-01..04，无 ORPHANED。

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | — | — | 13 个阶段改动文件 `TBD|FIXME|XXX|TODO|HACK|PLACEHOLDER` 零命中 |

全仓 `slice(0, 8)` 残留命中 15 处，逐一核对均为 ID 展示截断（runner/execution/日志/commit sha 等 UI），与变量引用生成无关，非阶段改动文件。

### Review-Fix 回归核验（17-REVIEW-FIX.md 7 项）

| Finding | 修复点 | 代码核实 |
|---------|--------|----------|
| CR-01 | 非法 short_id 不入重写映射 | views.py `_resolve_short_ids` client_valid/db_value 逻辑 + 3 回归测试在 |
| WR-01 | global_params 模型字段兜底 | base.py:507-509 + 注释，2 测试在 |
| WR-02 | 双键去重改 JSON.stringify 判等 | VariablePicker :166-177 |
| IN-01 | 确定性错误短路重试 | scheduler :903/:1033/:1052 `_deterministic_error` |
| IN-02 | 白名单收紧 {2,11} | views.py:86 |
| IN-03 | 畸形 payload 400 | views.py ValidationError + 测试在 |
| IN-04 | 重写正则尾断言 `[.\[]` | loader.py:84 |

7 项全部落地且未破坏 must_haves（368 passed 含全部回归用例）。

### Human Verification Required

#### 1. 端到端所选即所得

**Test:** 流程编辑器中用变量选择器选中上游节点输出引用 → 保存 → 执行；再手改一个坏引用执行
**Expected:** 好引用取到真实值；坏引用节点显式失败，错误中文指明引用与原因
**Why human:** 完整 UI→保存→执行链路跨前后端与运行时，程序化检查只覆盖各环节机制

#### 2. 端口复制缺 short_id 防护

**Test:** 对未保存（无 shortId）的新节点点击端口复制
**Expected:** toast "节点缺少 short_id，请先保存工作流"，剪贴板无 UUID 引用
**Why human:** toast 与剪贴板为运行时交互

#### 3. 运行时选择器双键去重

**Test:** 打开有执行结果的工作流运行时变量选择器
**Expected:** 同一字段只展示 short_id 形态一条
**Why human:** JSON.stringify 判等有效性依赖后端 snapshot 实际数据形态（WR-02 修复说明自承此依赖）

### Gaps Summary

无 gaps。全部 18 条 must-have truths、7 个 artifacts、8 条 key links 经代码与实跑测试验证；4 项需求全覆盖；7 项 review 修复全部落地。状态为 human_needed 仅因 3 项 UI/端到端行为按规则必须人工确认。

---

_Verified: 2026-06-12T18:05:00Z_
_Verifier: Claude (gsd-verifier)_
