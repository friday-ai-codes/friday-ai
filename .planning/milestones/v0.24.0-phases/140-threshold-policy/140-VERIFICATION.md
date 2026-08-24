---
phase: 140-threshold-policy
status: human_needed
verified: 2026-08-25
score: 5/5
---

# Phase 140 验证

## 结论

五项 requirements 的仓内实现、连接点与自动化回归均已闭合；代码审查 1 项 Warning 已自动修复且复验通过。真实 v0.22 baseline、独立 gold、已索引目标仓/Qdrant 与同条件 v0.24 candidate 当前不可用，因此不宣称数值提升，阶段状态按 autonomous 规则记 `human_needed` 并递延为里程碑技术债。

## Requirement 证据

| Requirement | 结果 | 仓内证据 | 外部状态 |
|---|---|---|---|
| BENCH-06 | implemented | policy raw-byte hash、baseline/manifest pin、全层 exact-key 闭集、缺键/marker/占位/重复 gate fail-closed；无 baseline 时 policy 文件不存在 | 真实 baseline 后的独立 policy 数值审查 `human_needed` |
| BENCH-07 | implemented | comparison/system identity 分离，case-set/evaluator hash、严格逐 case/bucket/cell 配对、四态 comparator、可复现命令与 diff | 同仓同 commit 的 v0.22/v0.24 真跑 `human_needed` |
| EDGE-06 | implemented | resolver language × framework × call_shape 三态、分母漂移 INVALID、TS/JS/Python required、Go report-only | 真实 resolver cell 数值门 `human_needed` |
| OBS-01 | passed | GraphQueryService 唯一 caller started/completed/failed，包含 duration/component/触发用户，query/凭证不入日志，观测 best-effort | 无 |
| OBS-02 | passed | resolver、Process、lane、impact 低基数 sampling/debug 汇总；AST 守卫拒绝 query 正文、未脱敏异常与循环 INFO | 无 |

## 跨阶段不变量

- 权限/exclusion 仍经 `GraphService.get_graph` fail-closed，缓存命中不绕过。
- mixed community watermark 不混用旧证据，Process/lane 故障保持 schema-preserving partial。
- 空 impact 明确为 `no_observed_impact_not_safe`，缺失/排除 anchor 降级为 unavailable。
- canonical manifest raw-byte hash、contract/response/ranking versions 在 service、Chat、Django MCP、npm MCP 与 task 保持一致。
- Process 后台入口保留 `initiated_by_user_id`，缺省绑定 `system`。
- comparator 纯函数零 I/O；compare command 只写显式 output，不回写 baseline/policy；holdout 默认拒读。

## 自动化结果

- Phase 140 最终 server gate：`498 passed, 3 deselected`。
- Closure 组合：`61 passed`。
- Policy/comparator/compare command 审查修复专项：`78 passed`。
- Task 全量：`291 passed, 3 skipped`；3 个既有可选 SDK 场景 skip 不参与本阶段验收，本阶段未新增/删除/放宽 skip。
- npm MCP：`29 passed`；typecheck、build、prepack、`npm pack --dry-run` 均通过。
- 真实环境 integration 状态机：`1 passed`，确认缺依赖时为 `human_needed` 且无 metrics。
- Phase 140 风险文件 Ruff：通过。
- Plan 140-04 key links：`2/2 verified`。

## Review / Fix

- Review depth：standard，25 files。
- Finding：1 Warning — threshold policy 的五层结构接受未知字段。
- Fix：加入 exact-key 闭集及五层参数化回归，commit `3f77225e`。
- Result：`1/1 fixed`，无残留 Critical/Warning。

## 人工验证债

真实数值验收需要：

1. 已索引真实目标仓 UUID、branch、冻结 commit SHA；
2. 可用 Qdrant/embedding；
3. 非占位、非 seed 的独立 dev/locked_test/holdout gold；
4. 未修改 v0.22 baseline report、run manifest 与 hashes；
5. 基于真实 baseline 独立审查后锁定的 threshold policy；
6. 相同 comparison identity 的 v0.24 candidate。

齐全后先执行 locked-test paired compare，全部 required/protected/language/capability gates 通过后，才可显式 `--final-acceptance` 打开 holdout。当前未生成伪造数字、正式 policy、candidate、compare artifact 或 PASS claim。

该债务不构成安全泄漏、明文凭证、不可逆数据、构建或迁移 blocker，按用户授权继续 milestone audit。
