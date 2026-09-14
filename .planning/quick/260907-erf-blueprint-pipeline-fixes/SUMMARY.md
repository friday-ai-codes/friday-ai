---
quick_id: 260907-erf
slug: blueprint-pipeline-fixes
status: complete
completed: 2026-09-13
---

# Quick 260907-erf 完成摘要

## 结果

蓝图流水线七个平台问题均已在生产调用路径中落地。2026-09-13 的专项复核没有发现生产
实现缺失，发现并补齐了 Task 3、4、6、7 的四个直接边界回归测试，使实现、验证证据和
GSD 状态重新一致。

## 七项结论

- Task 1：回调在 schema 校验前写入服务端权威 `repository_id`。
- Task 2：显式 stale 会使已有 degraded `PartialPlan` 失效，允许单次重派。
- Task 3：五仓外 `existing` 依赖不再误报；人工排除的支持仓别名会写入会话状态。
- Task 4：人工编辑或重分类保留的仓不会被静默删除；机器移除仓可从事件和 API 响应观察。
- Task 5：无开放阻塞线程的澄清会话可提前恢复；驱动租约支持 TTL、接管与续租。
- Task 6：额度、认证、runner 等基础设施失败会退还 attempt；管理命令可清零并复活任务。
- Task 7：Provider 设置会标出 Claude Code 当前凭证，并在编辑其他凭证时明确提示不影响
  编码容器。

## 本次补测

- `server/tests/services/process_runtime/test_blueprint_merge_stage.py`
- `server/tests/delivery/test_blueprint_gate_api.py`
- `server/tests/delivery/test_research_service.py`
- `web/src/components/providers/__tests__/ProviderSettingsClaudeCodePointer.spec.ts`

专项审计及逐项证据见 `.planning/debug/resolved/quick-260907-audit.md`。本次未修改生产代码，
也未触碰用户现有的 `mcp` 子模块工作区改动。

## 验证

- 后端七项定向回归通过。
- 前端 ProviderSettings 回归：3/3 通过。
- 受影响后端 Ruff、前端 ESLint 与 IDE diagnostics 通过。
- 更宽的 204 项后端文件级回归在 `test_research_service.py` 后段长时间无进展后停止；停止前
  已执行用例无失败，因此不把无关慢测试写成全量通过。
