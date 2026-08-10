---
slug: index-counter-fix
date: 2026-08-10
status: in-progress
---

# 修复 indexed_files_total 计数器失同步 + 四仓召回机制分析

## 任务 A：计数器修复
- 131 仓 `indexed_files_total` 与 Qdrant 实际存储脱节（数据显示 0/2，Qdrant 实际数千点）
- 用 Qdrant `indexed_files_count`/`points_count` 回写 DB 计数（reconcile）
- 先定位失同步根因（哪次写入路径漏了回写）

## 任务 B：四仓召回分析
- 拉四仓各自做了什么（master 改动/职责）
- 分析高三提分专项为何选这四仓
- 诊断现有召回机制为何不能稳定召回
- 提出完善方案（职责边界/定位/召回机制）
