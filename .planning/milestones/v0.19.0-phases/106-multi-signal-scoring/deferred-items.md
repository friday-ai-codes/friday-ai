# Phase 106 Deferred Items

超出当前 plan 范围、不予就地修复的发现（scope boundary 纪律）。

## From 106-02
- status: acknowledged


- **`server/system/views.py` 既有 17 处 ruff E402**（中段 import 块 L239-257 / L1115-1123，HEAD 即存在）：CI 将全量 ruff 视为 advisory baseline 不阻塞门禁；修复需将两处中段 import 上移或补 `# noqa: E402`，属既有文件整理，与 106-02 变更无关。

## From 106-05
- status: acknowledged


- **`RoutingDecisionPanel.test.ts` L265 既有 `test/prefer-lowercase-title` 错误**（`it('Σbreakdown ...')` 标题以大写希腊字母 Σ 开头，HEAD 即存在；仅 CI 模式 eslint 报错，编辑器模式该规则被禁用）：本 plan 未触碰该行，且 plan verification 的 eslint 命令不含测试文件；修复只需改标题首字符，属既有用例命名整理。
