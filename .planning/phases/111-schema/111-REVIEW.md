---
phase: 111-schema
status: findings
reviewed: 2026-07-30
depth: deep
reviewer: gsd-code-reviewer (adversarial)
findings:
  critical: 0
  major: 3
  minor: 13
  total: 16
files_reviewed: 18
files_reviewed_list:
  - server/services/process_runtime/blueprint_schema.py
  - server/services/process_runtime/blueprint_execution.py
  - server/services/process_runtime/blueprint_quality.py
  - server/delivery/artifacts/builtin_types.py
  - server/delivery/models/artifact.py
  - server/delivery/models/blueprint_thread.py
  - server/delivery/models/blueprint_reviewer.py
  - server/delivery/models/__init__.py
  - server/delivery/migrations/0031_blueprint_models.py
  - server/delivery/services/blueprint_lifecycle_service.py
  - server/delivery/services/blueprint_anchor.py
  - server/delivery/services/event_taxonomy.py
  - server/delivery/management/commands/evaluate_blueprint_golden.py
  - server/repositories/models.py
  - server/repositories/migrations/0040_repo_charter.py
  - server/repositories/services/charter_service.py
  - server/repositories/charter_views.py
  - server/repositories/serializers.py
  - server/repositories/urls.py
  - server/agents/call_source.py
  - server/tests/delivery/test_blueprint_inv6_guard.py
---

# Phase 111 蓝图底座 · Code Review Report

**Reviewed:** 2026-07-30
**Scope:** 12 个 feat commit（10955e32 / 251697a7 / 0cce0587 / 4505c7e6 / 10e2bb12 / 6912419a / e0c4b7dd / 0f58b6eb / 449f1a5e / d553b14f / 18bad349 / fa3d6853）触及的 server/ 源文件与测试
**Depth:** deep（跨文件调用链 + 与既有 convergence/技术方案 schema 接缝比对）
**Status:** findings（0 CRITICAL / 3 MAJOR / 13 MINOR）

## Summary

结构与纪律面扎实：11 态转移表与 DESIGN §4.2 逐边一致、CAS 防 TOCTOU、INV-6 双层源码扫描守护、event_taxonomy 纯追加、冻结面（process_runtime 六文件 / repo_router_v2.py / ConvergenceSessionEvent 既有类型）`git diff 0aaab65c..HEAD --stat` 复核**零触碰**、migration 皆为纯 Create/AddField（可逆，`blueprint_status` 默认空串向后兼容 v0）。`work_item=getattr(session, "work_item_id", None)` 与 `ConvergenceSessionEvent.work_item = UUIDField` 类型对齐（沿用 convergence_session_service:333 既有写法），非 bug。

本轮聚焦 VERIFICATION 未覆盖的三个维度，找到 3 条 MAJOR：**引用完整性只做了两项，漏了 `items[].repository_id → repo_associations` 这条会直接污染下游 coding dispatch 的边**；**charter 起草 best-effort 的 try 过宽，DB 写失败与「供应商没配」在 API 上不可区分**；**jsonschema 报错原样回显被校验实例，未截断未脱敏即进 API 响应与日志**。其余 13 条为并发窗口、审计留痕缺字段、派生边界与守护正则覆盖面。

## MAJOR

### MJ-01 `items[].repository_id` 无引用完整性校验，坏仓 id 静默派生成 execution task

**文件:** `server/services/process_runtime/blueprint_schema.py:788-817`、`server/services/process_runtime/blueprint_execution.py:139-186`

**问题:** `validate_blueprint` 的后置检查只做两项——块内 `citations` ∈ 文档级引用池、`items[].feature_point_id` ∈ `requirement_spec.feature_points`。`implementation_overview.items[].repository_id` 与 `current_state_analysis[].repository_id` **不校验是否存在于 `repo_associations`**。派生器又对缺名兜底：`repository_name = repo_names.get(rid) or rid`（execution.py:173），于是一个 LLM 幻觉/拼错的 repository_id 能顺利过 schema 门、顺利过 `validate_technical_plan`，产出 `{"repository_id": "<不存在的 id>", "repository_name": "<同一个坏 id>"}` 的 execution task。SCHEMA-06 的承诺是「下游 coding dispatcher 零改动可消费」——而 dispatcher 会拿这个 id 去建分支/克隆仓，失败点被推到编码执行期，且蓝图侧看不出问题（golden case 三仓自洽，测不到这条）。

**建议修法:** 在 `validate_blueprint` 加后置检查 (c)，与 (b) 同款形状：

```python
assoc_ids = {
    a.get("repository_id")
    for a in (content.get("repo_associations") or [])
    if isinstance(a, dict) and a.get("repository_id")
}
for item in items or []:
    rid = item.get("repository_id") if isinstance(item, dict) else None
    if rid not in assoc_ids:
        return False, f"implementation_overview.items[{item.get('id', '?')}].repository_id {rid!r} 不在 repo_associations 中"
```

同一检查建议覆盖 `current_state_analysis[].repository_id`。防御性地在 `derive_execution_plan` 也丢弃不在 `repo_names` 中的 item（或让 `derive_technical_plan_document` 返回错误），双保险。

### MJ-02 charter 起草的 best-effort `try` 过宽，吞掉 DB 写失败与编程错误并伪装成「供应商未配置」

**文件:** `server/repositories/services/charter_service.py:234-366`（配 `server/repositories/charter_views.py:71-75`）

**问题:** 单个 `try` 从 import 一路包到 `_persist()` 落库与 `logger.info`，`except Exception` 统一 `return None`。于是 IntegrityError / OperationalError / `normalize_charter_draft` 里的 TypeError / `build_chat_model` 的 AttributeError 全部退化成同一个返回值，视图再统一翻成 `503 {"detail": "AI 起草暂不可用，请检查模型供应商配置"}`——**把「数据库写失败」和「代码 bug」报成「你的模型供应商没配好」**，运维会照着错误提示查错方向。唯一线索是一条 `logger.warning`（非 error，不触发告警阈值）。可观测规范要求 best-effort「不反噬业务」，但不要求把真异常也压成 warning：写库失败不是观测代码，它就是业务失败。

**建议修法:** 收窄 try 到「LLM 调用 + 解析」，落库与其余单独处理，并按 reason 分级：

```python
        with use_call_source(CallSource.BLUEPRINT_CHARTER_DRAFT):
            try:
                response = await model.ainvoke(messages)
            except Exception as exc:  # 上游不可用 → best-effort None
                logger.warning("charter_draft_failed", reason="llm_error",
                               error=redact_secrets_in_text(str(exc)), ...)
                return None
        ...
        try:
            charter = await sync_to_async(_persist)()
        except Exception as exc:
            logger.error("charter_draft_failed", reason="persist_error",
                         error=redact_secrets_in_text(str(exc)), ...)
            raise                      # 或返回带 reason 的失败对象，让视图回 500
```

视图侧按 reason 区分 503（上游不可用）与 500（内部错误），错误文案不要一律指向供应商配置。

### MJ-03 jsonschema 报错原样回显被校验实例，未截断未脱敏即进 API 响应与日志

**文件:** `server/services/process_runtime/blueprint_schema.py:786`（`return False, f"{first.json_path}: {first.message}"`，兼及:820 的 `f"blueprint 校验异常：{exc}"`）

**问题:** `jsonschema` 的 `ValidationError.message` 对 `type` / `enum` / `const` 类失败会把**被校验实例的 `repr` 整段拼进消息**（如 `"{...整个 requirement_spec...} is not of type 'array'"`），且 jsonschema 不做长度截断。这条字符串经 `builtin_types._validate_technical_plan` → `registry.validate_content` → `artifact_service.py:67` 的 `ArtifactContentInvalid(f"... content 校验失败：{err}")` 抛出，最终进 DRF 错误响应与调用方异常日志。蓝图 content 是研究阶段从仓库/文档蒸馏来的半可信正文，可能夹带代码片段与 token 样本——这里既没过 `redact_secrets_in_text`，也没有长度上限，等于给日志与响应体开了一个未脱敏、无界的正文回显口（同时也是刷屏源）。

**建议修法:** 出口统一脱敏 + 截断，只保留定位信息：

```python
from common.logging import redact_secrets_in_text
_MAX_ERR = 500

def _fmt(path: str, message: str) -> str:
    return f"{path}: {redact_secrets_in_text(message)[:_MAX_ERR]}"
```

`:786` 与 `:820` 两处出口都走它。更稳妥的做法是对 `type/enum/const` 类错误只回 `first.validator` 与 `json_path`，完全不带实例值。

## MINOR

### MN-01 confirm 的阻塞线程守卫是 check-then-act，CAS 保护不到它
**文件:** `server/delivery/services/blueprint_lifecycle_service.py:172-181`
**问题:** `aexists()` 查完到 `_apply_transition_sync` 的 CAS `update` 之间有窗口；期间新建的 open+blocking 线程会被漏挡（CAS 条件只有 `blueprint_status`，管不了线程表）。LIFE-02「阻塞澄清挡确认」在并发下可被穿透。
**建议:** 把「阻塞线程查询 + CAS update」放进同一个 `sync_to_async` 包裹的 `transaction.atomic()`，或对 confirm 路径给 artifact 行加 `select_for_update`。

### MN-02 CAS 成功后 reviewer upsert / 事件写在事务外，异常导致「状态已变但调用方看到失败」
**文件:** `server/delivery/services/blueprint_lifecycle_service.py:181-200`
**问题:** CAS 已提交后才 `aget_or_create` reviewer（:186）；该调用抛错会直接上抛给调用方，而 DB 里状态已经是 confirmed，名单却缺人、事件也没记。调用方按异常回滚业务，与 DB 事实不一致。
**建议:** reviewer upsert 与状态 CAS 同事务；或按 event 同款 best-effort try/except 包住（reviewer 名单属可补偿数据）。

### MN-03 `return_status` 仅在 needs_clarification 分支校验，其它目标态未校验即进事件 payload
**文件:** `server/delivery/services/blueprint_lifecycle_service.py:141,163-170,272`
**问题:** `to_status != needs_clarification` 时 `return_status` 完全不校验也不清空，任意字符串会原样落进 `ConvergenceSessionEvent.payload["return_status"]`，污染 115 时间线消费的语义。
**建议:** 非 needs_clarification 分支显式 `return_status = None`（或传值即 `raise ValueError`）。

### MN-04 `session=None` 时状态转移零 DB 留痕
**文件:** `server/delivery/services/blueprint_lifecycle_service.py:140,261-262`
**问题:** `session` 默认 `None`，此时只打 structlog、不落任何事件行。LIFE-01「有守卫**可追溯**」在无 session 的调用方（如后台重试、管理命令）下不成立——状态怎么变的只能翻日志。
**建议:** 112+ 编排层强制传 session；或在 `session is None` 时打 warning 级「transition_without_session」，让缺失可被发现。

### MN-05 无 charter 行时 `select_for_update()` 拿不到锁，并发首次起草撞 OneToOne 唯一约束
**文件:** `server/repositories/services/charter_service.py:325-332`
**问题:** 行不存在则没有锁可拿，两个并发 draft 都看到 `None` 都走 `create`，第二个撞 `OneToOneField` 唯一约束 → IntegrityError → 被 MJ-02 的 broad except 吞成 503。
**建议:** 用 `RepoCharter.objects.get_or_create(repository=repo, defaults={...})` 后再按 source 分支处理，或捕获 IntegrityError 重跑一次读-改路径。

### MN-06 RepoCharter 缺 `confirmed_at`，确认时间会被后续 AI 草案写入覆盖
**文件:** `server/repositories/models.py`（RepoCharter 字段区）、`server/repositories/services/charter_service.py:402-406`
**问题:** 确认只写 `source/version/confirmed_by`，时间靠 `updated_at`（auto_now）。而 human_confirmed 之后 AI 再起草会 `save(update_fields=["draft_content", "updated_at"])`（:341）刷新 `updated_at`——**确认时刻从此不可追溯**。CHARTER-01 的「人工确认署名与留痕」只留下了署名。
**建议:** 加 `confirmed_at = models.DateTimeField(null=True, blank=True)`，在 `aconfirm_charter` 里置 `timezone.now()`（新 migration，可逆）。

### MN-07 `_merge_files` 以 `(path, action)` 去重，同一文件的 modify 与 delete 会同时下发
**文件:** `server/services/process_runtime/blueprint_execution.py:93-113`
**问题:** 两个 item 对同一 path 分别声明 `modify` 与 `remove`，去重键不同 → files 里同时出现 `{path, modify}` 与 `{path, delete}`，给编码代理自相矛盾的指令，且 `validate_technical_plan` 不查 path 唯一性。
**建议:** 改为按 path 收敛，冲突时取优先级（delete > create > modify 或按 wave 顺序）并在 note 里标注冲突来源。

### MN-08 `item_repo` 以 item id 为键，重复 id 静默后者胜出
**文件:** `server/services/process_runtime/blueprint_execution.py:151`
**问题:** schema 未约束 `items[].id` 唯一，重复 id 时 `item_repo` 只保留最后一个的 `repository_id`，`depends_on` 投影出的仓级依赖边可能挂到错误的仓（拓扑顺序随之错）。
**建议:** `validate_blueprint` 后置检查 items[].id（以及 feature_points[].id、api_contracts[].id）唯一性；派生器遇重复 id 显式失败而非静默覆盖。

### MN-09 引用池不校验 `key == value.citation_id`
**文件:** `server/services/process_runtime/blueprint_schema.py:738-742,788-797`
**问题:** 完整性检查按引用池 **dict key** 匹配，但 Citation 自身还有必填 `citation_id`。两者不一致时（LLM 很容易写成 `{"c1": {"citation_id": "cite_1", ...}}`），块内按 `citation_id` 引用会被误报「引用不存在」，或反之放过一个悬空引用。
**建议:** 后置检查追加 `key == entry.get("citation_id")` 一致性断言，或改为「pool key 与 citation_id 任一命中即合法」并在 schema description 里写清唯一约定。

### MN-10 `BLUEPRINT_SCHEMA_VERSION` 双份定义
**文件:** `server/delivery/artifacts/builtin_types.py:18`（对 `server/services/process_runtime/blueprint_schema.py:35`）
**问题:** `blueprint_schema` 已导出 `BLUEPRINT_SCHEMA_VERSION`，判别分支又在 builtin_types 里重新写了一份字面量；判别字段若演进（blueprint/v2）会漏改一处，表现为「新版蓝图静默走 v0 校验路径」——最坏情况是绕过强制入库门。
**建议:** 在函数内懒 import 时一并取常量：`from services.process_runtime.blueprint_schema import BLUEPRINT_SCHEMA_VERSION, validate_blueprint`（懒 import 已在同一函数内，不破坏顶层零依赖）。

### MN-11 INV-6 字段级守护有可绕过形态，且整目录豁免过宽
**文件:** `server/tests/delivery/test_blueprint_inv6_guard.py:57,70-80`
**问题:** `_RE_FIELD_WRITE` 只认字面 `blueprint_status\s*=`，`setattr(artifact, "blueprint_status", v)` / `update(**{"blueprint_status": v})` / `Artifact.objects.filter(...).update(**payload)` 都能绕过；`_is_scanned` 又把 `delivery/models/` **整目录**豁免，模型层加一个改状态的业务方法不会被扫到（而模型层正是最容易被塞 helper 的地方）。
**建议:** 补两条正则（`setattr\([^,]+,\s*['\"]blueprint_status['\"]`、`['\"]blueprint_status['\"]\s*:`），`delivery/models/` 改为只豁免字段定义所在的 `artifact.py` 行区间或用「排除 `models.CharField(` 同行」的方式收窄。

### MN-12 charter 三端点仅 `IsAuthenticated`，draft 端点无节流
**文件:** `server/repositories/charter_views.py:32,57,88`
**问题:** 任何登录用户可对任意 `repository_id` 读章程、触发 LLM 起草、以自己名义 confirm 生效——而章程会在 112 参与路由决策与确认门，`confirm` 是有业务权重的写动作。与 repositories 既有 view 惯例（清一色 `IsAuthenticated`，仅 `tree_views.py:178` 用 `IsAdminUser`）一致，故**不算偏离 CONTEXT**，但 `draft` 每次请求触发一次上游模型调用且无 `throttle_classes`，存在按请求放大模型开销的空间。
**建议:** `confirm` 收紧到仓库负责人/`IsAdminUser`（与 tree_views 破坏性操作同档）；`draft` 加 `throttle_classes` 或服务端最小间隔。

### MN-13 golden command 用字符串 replace 修补输出格式
**文件:** `server/delivery/management/commands/evaluate_blueprint_golden.py:174`
**问题:** `f"{name}: {metric_text} → {verdict}".replace(":  →", ": →")` 靠对成品字符串做替换来消掉 metrics 为空时的双空格；case 名里出现 `:  →` 会被误改，且确定性双跑门槛正是逐字节比对输出，格式补丁式写法脆弱。
**建议:** 先判空再拼：`head = f"{name}: {metric_text}" if metric_text else f"{name}:"`，再拼 ` → {verdict}`。

## 已核查为「无问题」的项（避免重复劳动）

| 项 | 结论 |
|----|------|
| 冻结面纪律 | `git diff 0aaab65c..HEAD --stat` 44 文件中**零命中** process_runtime 六冻结文件 / `codegraph/services/repo_router_v2.py` / `convergence_session*.py`；event_taxonomy +28/−0 纯追加，blueprint 常量入独立 `BLUEPRINT_EVENTS` 不进 `ALL_EVENTS` — CLEAN |
| `work_item=getattr(session, "work_item_id", None)` | `ConvergenceSessionEvent.work_item` 是 `UUIDField(null=True)` 软引用（非 FK），赋 id 值正确，且与 `convergence_session_service.py:333` 既有写法一致 — 非 bug |
| migration 可逆性 | 0031 / 0040 全为 CreateModel + AddField + AddIndex + AddConstraint，无 RunPython 无数据迁移；`blueprint_status` `default=""` 让存量 v0 行不进状态机 — 可逆且向后兼容 |
| `reanchor` 同分并列 | 首轮 `ratio >= 0 > best_ratio=-1.0` 必走第一分支，`str(None)` 比较不可达；阈值 0.85 与 CONTEXT 锁定值一致 — 非 bug |
| LLM 上游文本脱敏 | 异常文本走 `redact_secrets_in_text`（charter_service.py:363），与 `decompose_segments.py:209` / `feature_classify.py:303` / `recall_adapter.py:115` 既有惯例逐字一致；LLM 响应体从不入日志（只入库供业务消费） — 合规。真正的未脱敏出口在 MJ-03（schema 报错），不在 charter |
| 观测埋点齐备性 | lifecycle 转移事件与 charter 四事件均带 `category=caller` + `component` + `duration_ms` + `initiated_by_user_id`；golden command 标 `system` — 符合 `.cursor/rules/observability-logging.mdc` |
| 纯函数无 ORM | `blueprint_schema` / `blueprint_execution` / `blueprint_quality` / `blueprint_anchor` 顶层零 django/ORM import — CLEAN |

---

_Reviewed: 2026-07-30 · gsd-code-reviewer (adversarial, deep) · 只读审查，未修改任何源码_
