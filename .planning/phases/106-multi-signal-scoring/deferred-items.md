# Phase 106 Deferred Items

超出当前 plan 范围、不予就地修复的发现（scope boundary 纪律）。

## From 106-02

- **`server/system/views.py` 既有 17 处 ruff E402**（中段 import 块 L239-257 / L1115-1123，HEAD 即存在）：CI 将全量 ruff 视为 advisory baseline 不阻塞门禁；修复需将两处中段 import 上移或补 `# noqa: E402`，属既有文件整理，与 106-02 变更无关。
