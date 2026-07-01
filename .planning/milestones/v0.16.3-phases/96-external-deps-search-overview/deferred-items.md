# Phase 96 — Deferred / Out-of-Scope Items

记录执行 Phase 96 期间发现、但**属既有问题或超出本阶段范围**的事项（不在本阶段修复）。

## 预存在失败（非本阶段引入）

### 1. `tests/initiatives/test_artifact_inv6_guard.py::test_inv6_no_bypass_artifact_write`
- **现象**：断言失败，flag 出 `delivery/models/artifact.py:95` 与 `delivery/services/artifact_service.py:98` 的 `Artifact.objects.create(...)`。
- **验证为预存在**：在未应用 Phase 96 任何改动的干净工作树上同样失败（已核对）。
- **根因**：该 INV-6 guard 的 grep 扫描范围覆盖了 `delivery` app 里**同名但不同**的 `Artifact` 模型/服务（与 `initiatives.Artifact` 无关）。属 guard 扫描范围问题，非本阶段代码引入。
- **处置**：out-of-scope，不在 Phase 96 修复。本阶段仅改 `initiatives` 侧调度逻辑，未新增任何旁路 `initiatives.Artifact` 写表。

### 2. `knowledge/ingestion.py` 预存在 `ruff I001`（import 块未排序）
- **现象**：`ruff check knowledge/ingestion.py` 报 import 块排序（`knowledge.chunking`/`toc_tree`/`collection` 顺序）。
- **验证为预存在**：干净树上同样存在，且位于本阶段未改动的 import 块。
- **处置**：out-of-scope，避免无关 diff，不在本阶段修复。
