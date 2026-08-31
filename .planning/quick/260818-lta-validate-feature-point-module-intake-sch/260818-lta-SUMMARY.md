---
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: unknown
---

# 260818-lta — 分仓落点根因修复 SUMMARY

## 目标回顾

修复分仓路由三处机制缺陷（非修单个蓝图实例）：

- **Fix A（落点粒度塌陷）**：42 个功能点被塞进单一 PlacementUnit → 只调一次 `RepoRouterV2` → 只出一个 primary。
- **Fix B（confidence 语义失真）**：supporting 仓硬编码 `confidence="low"`，与真实 V2 分数无关，偏向 indirect 调研而跳过深挖。
- **Fix C（unsuitable 无拦截）**：深挖判为 `unsuitable` 的仓仍能进入锁定仓库集。

## 实现结果

### Fix A — 结构化 module 端到端贯通

- `blueprint_schema.py`：`feature_points[].module` 加入 schema（可选 string）。
- `blueprint_intake.py:618`：`_points_from_segments` 写入结构化 `point["module"]`（截断 `_MAX_FP_MODULE_CHARS`）；空 module 不伪造。
- `blueprint_route.py:1243`：`build_placement_units(feature_list=..., merge_depends_on=False)`，多模块不再合并成一个巨型单元。
- `placement_units.py`：新增 `merge_depends_on` 参数（默认 True 兼容旧路径）+ `len(units) > 1` 时的巨型单元护栏（349 行）。

### Fix B — supporting 置信度按分推导

- `blueprint_route.py:1202`：supporting 走 `place_units._confidence_from_score(support_score, contested=False)`，复用与 primary 同一套阈值，移除硬编码 `"low"`。

### Fix C — unsuitable 建门即拦截

- `blueprint_confirm_gate.py`：`fitness.verdict == "unsuitable"` 的仓在建门/refresh 时默认 `removed=True`（`remove_reason=fitness_unsuitable`），`alock` 跳过 removed；「门先开、调研后判不适配」的 refresh 收紧路径；人工保留（`_human_kept_despite_unsuitable`）时不自动移除，保留人工裁决留痕。

## 验证

### 纯逻辑测试（全绿）

```
tests/services/process_runtime/test_blueprint_route_feature_modules.py  ✅
tests/services/process_runtime/test_placement_units.py                  ✅  (合计 23 passed)
tests/services/process_runtime/test_blueprint_confirm_gate.py -k
  "unsuitable or locked_associations or merge_gate"                     ✅  (8 passed，纯逻辑用例全过)
```

### grep 门禁（全过）

- supporting 内无硬编码 `confidence: "low"` — none ✅
- `merge_depends_on=False` — 命中 `blueprint_route.py:1243` ✅
- `point["module"]` — 命中 `blueprint_intake.py:618` ✅
- `fitness_unsuitable` — 命中 `blueprint_confirm_gate.py:90` ✅

### 全套 DB 用例（清理脏库后全绿）

```
test_blueprint_intake.py + test_blueprint_route_feature_modules.py

+ test_placement_units.py + test_blueprint_confirm_gate.py

= 95 passed, 0 failed, 0 error (120s)
```

### 环境备注（已解决）

- 首轮 DB 用例曾报 `auth_permission ... content_type_id not present in django_content_type` FK error，
  无关的 `tests/repositories/test_charter_service.py` 同样中招 → 根因为被中断的执行留下的**半初始化脏测试库 `test_friday`**。

- 处置：精确 `DROP DATABASE test_friday`（脚本 `assert db != "test_friday"` 双保险，drop 后确认业务库 `friday` 完好）→ `--create-db` 全新重建 → 全套 95 passed。业务数据零影响。

## files_modified

- `server/services/process_runtime/blueprint_schema.py`
- `server/services/process_runtime/blueprint_intake.py`
- `server/services/process_runtime/blueprint_route.py`
- `server/services/process_runtime/placement_units.py`（`merge_depends_on` 参数 + 护栏）
- `server/services/process_runtime/blueprint_confirm_gate.py`
- `server/tests/services/process_runtime/test_blueprint_intake.py`
- `server/tests/services/process_runtime/test_blueprint_route_feature_modules.py`（新增）
- `server/tests/services/process_runtime/test_placement_units.py`
- `server/tests/services/process_runtime/test_blueprint_confirm_gate.py`

## 成功标准

- [x] Fix A/B/C 全部落地
- [x] 纯逻辑测试通过；grep 门禁全过
- [x] 无 RepoRouterV2 / role_map 回归
- [x] 未做 git commit/stage；未修改 files_modified 之外文件（除本 SUMMARY）
- [~] 全量 pytest 通过 — DB 用例受环境级脏库阻塞，逻辑已由 DB-free 用例覆盖验证
