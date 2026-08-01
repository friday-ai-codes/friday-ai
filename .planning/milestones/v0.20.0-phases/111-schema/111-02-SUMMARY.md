---
phase: 111-schema
plan: 02
requirements: [LIFE-01, LIFE-02, LIFE-03]
provides:
  - "BlueprintLifecycleService.transition/add_reviewer + ConcurrentBlueprintTransitionError（11 态唯一写入入口）"
  - "Artifact.blueprint_status 11 态字段（空串 = v0 不参与状态机）+ BlueprintThread/BlueprintThreadMessage/BlueprintReviewer 三模型 + migration 0031"
  - "event_taxonomy：EVENT_BLUEPRINT_STATUS_TRANSITIONED / EVENT_BLUEPRINT_STAGE_{STARTED,COMPLETED,FAILED} + BLUEPRINT_EVENTS 独立 frozenset"
  - "blueprint_anchor.reanchor / SIMILARITY_THRESHOLD（0.85）重锚定纯函数（114 消费）"
affects:
  - "Phase 112–116 全部蓝图状态变更必须经 BlueprintLifecycleService（INV-6，守护测试锁死旁路）"
  - "112+ 编排阶段消费 blueprint.stage.* 常量；115 前端时间线消费 blueprint.status.transitioned 事件行"
key-files:
  created:
    - server/delivery/models/blueprint_thread.py
    - server/delivery/models/blueprint_reviewer.py
    - server/delivery/migrations/0031_blueprint_models.py
    - server/delivery/services/blueprint_lifecycle_service.py
    - server/delivery/services/blueprint_anchor.py
    - server/tests/delivery/test_blueprint_models.py
    - server/tests/delivery/test_blueprint_lifecycle_service.py
    - server/tests/delivery/test_blueprint_anchor.py
    - server/tests/delivery/test_blueprint_inv6_guard.py
  modified:
    - server/delivery/models/artifact.py
    - server/delivery/models/__init__.py
    - server/delivery/services/event_taxonomy.py
completed: 2026-07-29
---

# Phase 111 Plan 02: 生命周期 + 线程模型 Summary

**一行结论**：蓝图 11 态生命周期底座全部落地——`Artifact.blueprint_status` 新字段 + 三张新表（一条 migration 0031）、`BlueprintLifecycleService` 单点收口（DESIGN §4.2 转移表守卫 + CAS 并发安全 + confirm 阻塞线程守卫 + 评审人 aget_or_create 首插留痕 + session 可空 best-effort 事件）、`reanchor` 三分支重锚定纯函数（0.85 阈值），旁路写被字段级 + 模型级 INV-6 源码守护锁死。

## Accomplishments

- **LIFE-01**：`_ALLOWED_TRANSITIONS` 写死 DESIGN §4.2 全部合法边（"" 空串入口 → researching，26 条边逐条参数化测试）；非法转移抛 ValueError 且 DB 不写；CAS `filter(id, blueprint_status=from).update(...)` 命中计数判定，并发/陈旧推进抛 `ConcurrentBlueprintTransitionError`（Artifact.updated_at 为 auto_now，update() 绕过故显式带 `timezone.now()`）；每次转移 structlog caller 事件必打（绑定 initiated_by_user_id + duration_ms）。
- **LIFE-02**：`pending_review→confirmed` 守卫查 open+blocking 线程（aexists，命中索引 `["artifact","status","blocking"]`）；线程 resolved / 非 blocking 不阻塞；confirm 带 acting_user 自动 `aget_or_create` 入 BlueprintReviewer 名单（first_action 只在首插写入，重复确认不覆盖）；`add_reviewer` 手动增补同款 upsert。
- **LIFE-03**：failed/superseded 显式终态建模（archived/superseded 无出边）；`failed→researching` 人工重试边可走，有专属参数化用例。
- **事件面零污染**：event_taxonomy 纯追加 4 常量（+28 行 0 删除），入独立 `BLUEPRINT_EVENTS` frozenset 镜像 RESERVED_EVENTS 先例，不进 ALL_EVENTS（P4——覆盖性反查守护 `test_event_taxonomy_alignment` 全绿证明未挂）；事件行 best-effort：session=None 只打 structlog 不落行，落行失败 try/except 吞掉只 warning（观测不反噬业务）。
- **重锚定纯函数（114 消费）**：block_id 精确命中 → anchored 原样；quoted_text difflib ratio ≥0.85 模糊命中 → 重挂新 block_id（quoted_text 保留原文、同分取字典序小者确定性）；否则 orphaned 绝不删线程。`_block_text` 覆盖 paragraph/list（items[] join）/pseudocode（code.source）/table（rows 扁平）四型块，stdlib only 零新依赖、零 ORM import。
- **INV-6 守护**：三模型 ORM 写（含 a 前缀异步变体）/直接实例化（负向前瞻排除 BlueprintThreadMessage）/链式 save 三正则 + `blueprint_status\s*=\s*[^=]` 字段级扫描（排除定义/migrations/tests 后仅允许唯一 writer）；「守护的守护」反向断言 writer 源码确实命中正则，防形同虚设。

## Task Commits

| Task | Commit | 内容 |
| ---- | ------ | ---- |
| 1 | `10955e32` | Artifact.blueprint_status 11 态 + BlueprintThread/BlueprintThreadMessage/BlueprintReviewer + migration 0031 + 模型测试 |
| 2 | `251697a7` | event_taxonomy blueprint.* 四常量（独立 BLUEPRINT_EVENTS）+ BlueprintLifecycleService（守卫+CAS+reviewer+best-effort 事件）+ 40 例测试 |
| 3 | `0cce0587` | blueprint_anchor 重锚定纯函数 + INV-6 旁路写守护测试（模型级+字段级+守护的守护）13 例 |

## Files

- `server/delivery/services/blueprint_lifecycle_service.py`（新建：转移表 docstring 全文 + ConcurrentBlueprintTransitionError + transition/add_reviewer；Artifact 状态写全走 CAS update，无 .save()）
- `server/delivery/services/blueprint_anchor.py`（新建：纯函数，stdlib difflib，无 django/delivery import）
- `server/delivery/services/event_taxonomy.py`（修改：纯追加 4 常量 + BLUEPRINT_EVENTS + __all__ 5 名字）
- `server/delivery/models/blueprint_thread.py` / `blueprint_reviewer.py` / `artifact.py` / `__init__.py` / `migrations/0031_blueprint_models.py`（Task 1）
- 测试四件：`test_blueprint_models.py`（6）/ `test_blueprint_lifecycle_service.py`（40）/ `test_blueprint_anchor.py`（10）/ `test_blueprint_inv6_guard.py`（3）

## Decisions

- ConvergenceSessionEvent 行写入带 `work_item=getattr(session, "work_item_id", None)`——event 模型的 work_item 是软引用 UUIDField（非 FK），与 convergence_session_service._persist_event 同款。
- 字段级守护正则取 `blueprint_status\s*=\s*[^=]`（镜像 feishu_chat_id 先例排除 == 比较）；`filter(blueprint_status=...)` 读条件出现在 writer 之外也一并锁死——writer 外自拼 CAS 即旁路。
- needs_clarification 的 return_status 只校验与透传进事件 payload，不落 Artifact 列（RESEARCH A4；持久承载走 BlueprintThread.return_stage 由 114 调用方写）。

## Deviations from Plan

**执行方式备注（非计划偏差）**：本 plan 由中断续作完成——Task 1 由上一 executor 提交（10955e32）；Task 2 的三个文件以未提交在制品形态遗留，续作时逐条对照 plan 规格审查（转移表 26 边 vs DESIGN §4.2 逐边核对、事件 session 可空、BLUEPRINT_EVENTS 独立 frozenset、CAS/aget_or_create/无 .save 验收全过）后确认无需修正，格式化 + 测试全绿后提交。

### Auto-fixed Issues

**1. [Rule 1 - Bug] 修正模糊匹配测试的相似度前置断言**
- **Found during:** Task 3（新建测试首跑）
- **Issue:** `test_fuzzy_rehit...` 追加的中文后缀过长，实测 difflib ratio 0.8305 < 0.85 阈值，测试自身前置断言失败
- **Fix:** 缩短追加文本为 `（INV-6）`，ratio 回到阈值之上（测试用 difflib 现算断言，不硬编码）
- **Files modified:** server/tests/delivery/test_blueprint_anchor.py
- **Commit:** 0cce0587（提交前修复，未产生坏提交）

## 测试与验证

- 组合 verification 套件（5 文件）：**62 passed**（models 6 + lifecycle 40 + anchor 10 + inv6 3 + taxonomy 对齐 3）
- `makemigrations --check --dry-run`：No changes detected（0031 无缺失）
- 冻结面自检：`git diff d082c47d..HEAD --name-only` 对 convergence_session_event / convergence_session / repo_router_v2 / process_runtime 六冻结文件零命中；event_taxonomy.py diff = 28 insertions 0 deletions（纯追加）
- 观测面：transition 记 `blueprint_status_transitioned` caller 事件（component=process_runtime，initiated_by_user_id + duration_ms）；事件持久化失败记 warning 吞掉；anchor 纯函数按「高频循环禁 INFO」不加日志

> 环境备注：同 worktree 有并行 executor（111-03）同时运行，`server/repositories/serializers.py` 的未提交改动属于它，本 plan 三次提交均只 staging 自己的文件。

## Next Phase Readiness

- 112–116 状态变更调用面就绪：`BlueprintLifecycleService().transition(artifact, to, initiated_by_user_id=..., acting_user=..., session=..., return_status=...)`；旁路会被 test_blueprint_inv6_guard 挡下。
- 112+ 编排阶段直接 import `EVENT_BLUEPRINT_STAGE_*` 常量落事件行；「一项目一份活跃蓝图」唯一性守卫留给 112 创建入口（P10，本 service 不做）。
- 114 重锚定批量应用调用 `reanchor(thread.anchor, new_blocks)` 并把返回 status 写回 `anchor_status`（写回须经 lifecycle service 扩展或 114 自己的 writer 并同步豁免守护——届时更新 _ALLOWED_WRITER 语义）。

## Self-Check: PASSED

- 9 created + 3 modified 文件全部存在；commits 10955e32 / 251697a7 / 0cce0587 均在 git log；62/62 测试绿；migration 检查干净。
