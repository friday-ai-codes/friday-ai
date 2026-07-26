---
quick_id: 260726-t2f
slug: feature-list
description: feature list 技术方案生成能力（后端链路）
date: 2026-07-26
status: complete
commits:
  - 2e27493c feat(process_runtime)：feature list 入口的功能点分类与强制仓库确认
  - c064215a test(process_runtime)：补 feature list 分类与强制确认单测
---

# Quick Task 260726-t2f 总结

## 做了什么

给 `technical_plan` 编排加了一条 feature list 入口：喂进 feature list 的功能点后，系统先判定每个功能点是**新增功能**还是**改造已有功能**（带代码证据），再强制用户确认关联仓库，确认完才进入调研与融合，最终方案要求给出落点文件与伪代码。

Stage graph 从 `decompose → route → recall → clarify → research → merge` 变为在 recall 与 clarify 之间插入 `classify`。

## 三个关键设计决策

**1. classify stage 用 `decomposition.mode` 做开关，而不是新建 process_type。**
用户选择扩展现有 process，所以最大风险是污染既有飞书 / 对话 / MCP 三条入口。做法是 `_h_classify` 第一件事就判模式，非 `feature_list` 直接返回 `classified`——不调 deps、不发 LLM、不检索、不写 stage_state。deps 上没有 `classify` 属性（旧构造）时同样 pass-through。代价是既有会话多一次 DB transition，换来单一 stage graph 不分叉。

**2. 判「改造已有」必须拿出真实证据文件，否则降级 unclear。**
LLM 编造文件路径是这类任务最危险的失败模式——方案里写着「在 `xxx/service.py` 上改造」而那个文件根本不存在，下游编码 agent 会跟着跑偏。`normalize_feature_classifications` 用检索命中的真实文件集合过滤 `evidence_files`，过滤后为空的 modify 判定直接降级 `unclear` 交回用户。宁可说不知道，不猜。

**3. 强制确认走确定性题组装，不交给 LLM 判断。**
产品约束是「哪怕路由十分确定也要确认关联仓库」。如果沿用现有 `agenerate_clarification_questions`，LLM 见到全 high 置信的路由结果必然返回「信息充分，无需澄清」而静默跳过。所以新增 `build_feature_confirm_questions` 由 routing + classification 直接推导题目（选仓 / 复核 modify / 指认 unclear 三题），`ClarifyAdapter` 在 builder 产出非空时用它取代 LLM 生成。

防死循环靠两层：builder 自身 `round_count > 0` 返回空回落 LLM 重判，加上既有的 pending 短路与 `_MAX_CLARIFY_ROUNDS` 上界——这三段既有逻辑一行没动。

## 改了哪些文件

| 文件 | 改动 |
|---|---|
| `services/process_runtime/feature_classify.py` | 新建。分类 LLM helper，镜像 `decompose_segments.py` 样板；归一层做幻觉过滤 |
| `services/process_runtime/classify_adapter.py` | 新建。有界并发检索证据 + 调 helper + 漏判补齐 |
| `services/process_runtime/feature_confirm_questions.py` | 新建。确定性确认题组装 + 强制澄清 policy |
| `services/process_runtime/builtin_processes.py` | 新增 `_h_classify`；stage graph 插入 classify；decompose 支持 feature 树直供 |
| `services/process_runtime/entrypoint.py` | `start_orchestration` 加 `mode`/`feature_segments`；`build_orchestration_engine` 加 `force_confirm` |
| `services/process_runtime/clarify_adapter.py` | 可注入 `question_builder`（默认 None 时行为逐字不变） |
| `services/process_runtime/architect_merge_adapter.py` | feature list 模式下 merge prompt 追加分类证据与落点/伪代码要求 |
| `services/process_runtime/protocols.py` | 新增 `ClassifyProtocol` |
| `delivery/models/convergence_session.py` | 新增 `classification` 只读视图（property，无 migration） |
| `delivery/services/event_taxonomy.py` | 新增 `technical_plan.feature.classified` 事件 |
| `agents/call_source.py` | 新增 `feature_change_classify` 枚举（35 → 36 值） |

## 验证

- 新增单测 23 个全过（`test_feature_classify.py` 10 / `test_feature_confirm_questions.py` 8 / `test_classify_stage.py` 5）
- 回归：`tests/services/` + `tests/delivery/` 1254 passed、`tests/mcp_tools/` + `tests/workflows/` 856 passed、`tests/chat/` + 编排澄清相关 580 passed，累计约 2700 个测试零回归
- 改动文件 `ruff check` 全过；`ruff format` 剩余差异均落在本次未触碰的既有代码行（`_h_merge` 的 `back_target`、`_h_echo_draft`、两个测试文件的既有行），刻意未动以免混入无关 diff

## 两处既有测试的适配

`test_plan_orchestration_engine.py` 有两个断言写死了 recall 之后是 clarify。没有简单改字符串，而是让它们反映新流程，并利用其 deps 未注入 classify 的现状补了一条 pass-through 断言——正好是 INV-A 的回归点。

## 遗留与下一步

本次只做后端编排链路（用户选择 backend_first）。**这条链路目前还没有对外入口**——没有任何调用方会传 `mode="feature_list"`，需要下一个 quick 任务接上：

1. **MCP 三工具**：`create_feature_tech_plan`（发起并返回待确认项）/ `confirm_feature_tech_plan`（提交确认后出方案）/ `get_feature_tech_plan`（查状态）。注意是两段式——单次调用拿不到方案，这是强制确认的直接后果。需同步五处契约（serializers 含 `TOOL_SCHEMA_SNAPSHOT`、views、urls、`mcp/src/tools.ts`、tests）
2. **Skill 文档**：`skills/skills/friday-solution/SKILL.md`，并同源到 `task/assets/skills/`。必须把「不许跳过确认」写成硬纪律，否则 agent 会想办法绕过两段式
3. **feature list 取数适配层**：从项目已有 `feature_list` Artifact 经 `FeatureListService.build_tree()` 展平为 `feature_segments`；分支入口复用 `lookup_project_by_branch` 反查项目
4. **对话 agent tool** + 前端接线（复用现有 `ClarificationCard` 多题与 `TechPlanCard`）

另外一处发现但未处理的既有问题：`_h_decompose` 重建 `decomposition` 时会丢掉 `extra_evidence` 键（UNIFY-02 写入、merge 阶段消费），意味着 `extra_evidence` 实际可能从未生效。本次只补了 `mode` 的透传（feature list 链路必需），没有顺手改 `extra_evidence`——它属于既有行为，改动会影响 MCP analyze 链路，应当单独验证后再动。
