---
phase: 111-schema
plan: 03
requirements: [CHARTER-01]
provides:
  - "RepoCharter 模型：一仓一份（OneToOne Repository）、版本化、草案/正式分离（draft_content 承载 pending 修订）+ migration 0040"
  - "charter_service：adraft_charter（三源蒸馏 → LLM 单调用 → normalize 白名单落库）/ aconfirm_charter（人工确认收口）/ normalize_charter_draft——RepoCharter 唯一 writer（INV-6）"
  - "charter REST 三端点：GET /repositories/<id>/charter/、POST charter/draft/、POST charter/confirm/（IsAuthenticated）"
  - "call_source 8 个 blueprint_* 枚举值（含 BLUEPRINT_CHARTER_DRAFT），LOGGING-SPEC §4.1 已登记"
affects:
  - "Phase 112 blueprint_route 双面路由与 repo_confirmation 确认门回灌读写 RepoCharter"
  - "其余 7 个 blueprint_* call_source 值的调用点在 112–114 落地"
key-files:
  created:
    - server/repositories/services/charter_service.py
    - server/repositories/charter_views.py
    - server/repositories/migrations/0040_repo_charter.py
    - server/tests/repositories/test_charter_service.py
    - server/tests/repositories/test_charter_api.py
  modified:
    - server/agents/call_source.py
    - .planning/observability/LOGGING-SPEC.md
    - server/repositories/models.py
    - server/repositories/services/__init__.py
    - server/repositories/serializers.py
    - server/repositories/urls.py
completed: 2026-07-29
---

# Phase 111 Plan 03: RepoCharter 章程模型 + AI 起草管道 + REST 三端点 Summary

**一行结论**：仓库章程（意图面知识）完整底座落地——RepoCharter 一仓一份版本化模型、AI 三源蒸馏起草管道（`call_source=blueprint_charter_draft`，LLM 失败零副作用）、confirm 人工收口（version+1 署名生效）、REST 三端点；「AI 不覆盖人工」不变量（human_confirmed 后 AI 只写 draft_content）由 service 单点判断 + 专测锁死，call_source 8 个 blueprint_* 值注册并登记 LOGGING-SPEC §4.1。

## Accomplishments

- **CHARTER-01 模型面**：`RepoCharter`（OneToOne Repository + version + source(ai_draft|human_confirmed) + 七个结构化字段 + draft_content「单行 + 草案列」）+ migration 0040；模型层零业务方法，docstring 声明 INV-6 唯一 writer 与不覆盖契约。
- **CHARTER-01 起草面**：`adraft_charter` 三源蒸馏（overview_text/facets + 近期 20 条 MR + verified/rejected RepoAssociation）→ LLM 五步骨架（镜像 decompose_segments，`use_call_source(BLUEPRINT_CHARTER_DRAFT)` 包 ainvoke）→ ```json 双路解析 → `normalize_charter_draft` 白名单归一（截断/枚举回退/畸形跳过，绝不抛）→ 事务落库。无 provider/default_model、解析失败、任何异常一律 return None 零副作用，异常文本过 `redact_secrets_in_text` 脱敏。
- **CHARTER-01 收口面**：`aconfirm_charter` 先提升非空 draft_content 再套 edits（同 normalize 白名单）→ `source=human_confirmed`、`version+1`、`confirmed_by` 署名、draft 清空；charter 不存在 → ValueError（视图转 404）。
- **P11 不覆盖不变量**：human_confirmed 后再起草只写 draft_content，正式字段逐字节不变——service 单点判断 + 服务层快照逐字段专测 + API 面回归测试双保险；INV-6 源码扫描守护（唯一 writer 正则扫全 server/）+「writer 确实在写」反向断言。
- **REST 面**：三 adrf 端点 IsAuthenticated（T-111-06），视图零 RepoCharter 写（INV-6），serializer 全字段只读、`.data` 走 `sync_to_async`；draft 404（仓库不存在）/503（AI 不可用）语义、confirm 404/edits 白名单（T-111-07）。
- **观测规范**：`charter_draft_started/completed/failed` + `charter_confirmed` 四事件（category=caller、component=charter_service、initiated_by_user_id、duration_ms）；8 个 blueprint_* call_source 值注册（既有 36 值零改动，计数改 44）并登记 LOGGING-SPEC §4.1（前 7 值备注调用点在 112–114 落地）。

## Task Commits

| Task | Commit | 内容 |
| ---- | ------ | ---- |
| 1 | `4505c7e6` | call_source 8 值注册 + LOGGING-SPEC §4.1 登记 + RepoCharter 模型 + migration 0040 |
| 2 | `10e2bb12` | charter_service 三源蒸馏起草管道 + confirm 收口 + P11 不覆盖不变量测试（22 例） |
| 3 | `6912419a` | charter REST 三端点 + serializers + urls 接线 + API 测试（14 例） |

## Files

- `server/repositories/services/charter_service.py`（新建：normalize 纯函数 + adraft/aconfirm，重依赖函数内懒 import，ORM 全 sync_to_async + select_for_update 事务）
- `server/repositories/charter_views.py`（新建：三 adrf APIView，按功能拆小 view 文件惯例，不进 views.py 巨石）
- `server/repositories/models.py`（追加 RepoCharter，嵌套 TextChoices，db_table=repo_charters）+ `migrations/0040_repo_charter.py`（makemigrations 生成）
- `server/repositories/serializers.py`（RepoCharterSerializer 全字段 read_only）/ `urls.py`（资源子路由区三条 charter path）/ `services/__init__.py`（docstring 补 charter_service 行）
- `server/agents/call_source.py`（尾部追加 8 成员 + 两处计数 36→44）/ `.planning/observability/LOGGING-SPEC.md`（§4.1 表 +8 行）
- `server/tests/repositories/test_charter_service.py`（22 例）/ `test_charter_api.py`（14 例）

## Decisions

- draft 端点对 human_confirmed 章程返回 200 全行（含正式字段 + 新 draft_content），前端可同屏对比正式内容与 pending 草案。
- confirm 的 edits 只套用调用方显式给出的白名单字段（normalize 后按 key 交集赋值），未提及字段不清空。
- INV-6 读写分界：视图允许直接**读**（GET select_related aget），写全部收口 charter_service——与源码扫描守护正则一致。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - 缺失防御] confirm 视图对非 dict 的 edits 按无 edits 处理**
- **Found during:** Task 3（charter_views.py 实现）
- **Issue:** plan 写的是 `edits=body.get("edits")` 直传；若调用方传非 dict 真值（如字符串/数字），service 内 `field in edits` 对 int 会抛 TypeError → 500。
- **Fix:** 视图层 `isinstance(raw_edits, dict)` 守卫，非 dict 视为 None（白名单归一仍在 service 层，T-111-07 语义不变）。
- **Files modified:** server/repositories/charter_views.py
- **Commit:** 6912419a

> 续作说明：本 plan 由两个 executor 接力完成（前任在 Task 3 中途被中断，遗留 serializers.py 在制品）。续作核验在制品与 plan 规格逐字段一致后原样保留，补完 views/urls/tests。Task 1/2 acceptance criteria 续作时全部复验通过（8 值/计数 44/LOGGING-SPEC 登记/0040 唯一/`__init__` docstring）。

## 测试与验证

- `tests/repositories/test_charter_service.py` + `test_charter_api.py` 组合套件：**36 passed**（22 + 14）
- `manage.py makemigrations --check --dry-run`：无待生成 migration
- 三 commit 触及文件 = plan files_modified 11 文件；`repo_router_v2 / process_runtime 六冻结文件 / delivery` 零命中；call_source.py diff 仅追加 + 两处计数
- 观测面自检：caller 事件四个齐（started/completed/failed/confirmed 均带 duration_ms 或 version）、LLM 调用点已赋 call_source、异常脱敏强制（rg redact_secrets_in_text 命中）、新端点走既有中间件 QPS/错误率统计

## Next Phase Readiness

- 112 `blueprint_route` 双面路由可读 `repository.charter`（positioning/owned_domains/boundaries/placement_preferences/evolution 全结构化）；repo_confirmation 确认门回灌走 `aconfirm_charter`（INV-6 收口已就位）。
- 112–114 的 7 个 blueprint_* call_source 值已注册可直接 `use_call_source`，LOGGING-SPEC 无需再改。
- 前端章程卡片可直接消费三端点（GET 含 draft_content 预览、draft 503 语义提示配置供应商、confirm 带 edits）。

## Self-Check: PASSED

- 5 created + 6 modified 文件全部存在于工作区 ✓
- commits `4505c7e6` / `10e2bb12` / `6912419a` 均在 `git log` ✓
- 组合 verification 套件 36 passed ✓
