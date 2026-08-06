---
phase: quick-260807-2cu
plan: 01
status: complete
completed: 2026-08-07
commits:
  - b2d5098a fix(blueprint): 仓库关联卡适配判定正文贯通、选仓理由不再复读职责
---

# Quick Task 260807-2cu Summary — 仓库关联卡三字段产出侧修复

## 用户实测反馈（查看器仓库关联卡）

1. 「选仓理由」与「本仓职责」**一字不差重复**；
2. 「适配判定」折叠区展开**没有内容**（只有卡头 verdict 徽标）。

## 根因

- **适配判定空**：调研容器明明产出 `fitness.reasons`（prompt 要求、PartialPlan 落库均在），
  但 ① `BlueprintResearchAdapter._collect_fitness_sync` 聚合时只取 verdict/role/responsibility
  三标量把 reasons 丢掉；② `blueprint_confirm_gate._build_snapshot_entry` 拼确认门快照时
  写死 `"reasons": []`。快照 → 锁定（`_clean_fitness`）→ 蓝图投影（`_project_fitness`）
  全程无源，正文恒空。
- **理由=职责**：全链没人产出 `rationale.text`，`blueprint_merge._project_rationale` 的兜底链
  `source.text or responsibility or fitness.reasons` 恒取职责文本 ⇒ 必然逐字重复。

## 修复（三处 + 测试）

- `_collect_fitness_sync`：聚合带上 `reasons`（非 list 收敛空）。reroute 判定与 stage_state
  摘要只挑标量键，不受影响。
- `_build_snapshot_entry`：快照携带 conclusion.reasons（字符串截断 `_MAX_SUMMARY_CHARS` 防
  BlueprintThread.options 膨胀；block 形状原样，锁定时统一收敛 block_list）。
- `_project_rationale`：`text` 只认源条目 `rationale.text`，⛔ 去掉 responsibility /
  fitness.reasons 兜底——schema 对 text 无 minItems，空数组合法；前端
  `RepoAssociationCard` 对空 text 整块不渲染，markdown 渲染器落空单元格；citations 并集
  （P-8 覆盖率分子）逐字保留。
- 测试：`test_blueprint_reroute.py` 加 reasons 聚合正反用例；新建
  `test_blueprint_repo_association_fields.py`（快照携带/截断/反面 + 快照→锁定→投影贯通 +
  rationale 留空不复读 + 显式 rationale 正面对照，纯函数零 DB 为主）。

## 验证

- 受影响四个测试文件 86 passed（独立测试库跑，避开并发会话争用；临时库已清理）。
- ruff check/format 通过（新增/改动文件）。

## 执行备注

- `blueprint_research_adapter.py` / `blueprint_merge.py` 是在途脏文件：按 hunk 选择性暂存，
  只提交本修复的 3 个 hunk，在途改动原样留在工作区。
- 存量蓝图不回填：修复对**之后**走确认门/融合的蓝图生效；已确认的旧蓝图卡片维持现状。
