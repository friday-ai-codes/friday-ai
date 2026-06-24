---
phase: 74-alerting
verified: 2026-06-25T01:10:00Z
status: passed
score: 3/3 success criteria verified
overrides_applied: 0
re_verification: null
runtime_confidence_notes:
  - test: "配置真实 SMTP（EMAIL_HOST/USER/PASSWORD）+ ALERT_EMAIL_ENABLED=true + 收件人，触发一条 P0 firing"
    expected: "收件人实际收到 [P0] 主题邮件，AlertEvent.email_sent=sent"
    why_runtime: "实际投递依赖外部 SMTP 服务；代码路径与 skipped/sent/failed 分支已被 mock 测试全覆盖"
  - test: "起 runapscheduler 长驻进程，造一条 cpu>阈值规则并让真实 CPU/指标越线"
    expected: "~60s 内 evaluate_system_alerts 产 1 条 firing；恢复后转 resolved 写 duration_s"
    why_runtime: "依赖真实 apscheduler 进程 + 真实 metrics/snapshot 数据；job 接线、评估逻辑、firing/resolved/去重生命周期已被 transaction 测试覆盖"
---

# Phase 74: 告警引擎与通知（阈值 + 告警事件 + 邮件）Verification Report

**Phase Goal:** 数据可查后评估阈值告警——新建系统级告警（不套 workflow `AlertRule`），沉淀告警事件并按级别通知，共享飞书/webhook/邮件分发。
**Verified:** 2026-06-25T01:10:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths（ROADMAP Phase 74 Success Criteria）

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | 可为 QPS/错误率/TTFT/CPU/内存/DB/Redis/Qdrant/队列深配置阈值规则（运行时可改），超阈触发；趋势类(RATE-03)默认不参与；独立于 workflow `AlertRule` | ✓ VERIFIED | `SystemAlertRule` 落 `system` app（`models.py:493`，独立建表 `system_alert_rules`，非 workflow `AlertRule`）；`metric` 受控 9 类枚举 = QPS/错误率/TTFT/CPU/内存/DB/Redis/Qdrant/队列深（`alert_serializers.py:20` `_METRIC_CHOICES`）；REST CRUD 运行时增删改查（`alert_views.py` 3 视图，全 `IsSuperUser`，`urls_system.py:38-45`）；评估器 `_TIMESERIES_METRICS`/`_SNAPSHOT_METRICS` 分派，`gauge:*`/未知 metric → None 跳过（`alert_evaluator.py:289-316`，RATE-03 默认不参与） |
| 2 | AlertEvent 落库含 P0/P1/P2、中文标题、机器可读 rule_info(规则·当前值·窗口·维度)、started/ended+duration、firing/resolved、邮件状态；同规则同对象去重(一条 firing，恢复收尾) | ✓ VERIFIED | `AlertEvent`（`models.py:550`）字段齐：`severity`/`title_zh`/`rule_info`(jsonb expr `cpu > 85.00 (current 95.40) over last 5m (overall)`)/`started_at`/`ended_at`/`duration_s`/`status(firing/resolved)`/`email_sent`/`notified_channels`；去重硬约束 `UniqueConstraint(fields=[rule,target_key], condition=Q(status="firing"))`（`models.py:625`，迁移 `0012:66`）；服务层 `aget_or_create` + IntegrityError 兜底双保险（`alert_evaluator.py:324-367`）；恢复 `_resolve_firing` 写 ended_at/duration_s（`:370-384`） |
| 3 | 邮件通道接入(Django SMTP + SystemSetting 收件人/开关)，按级别发邮件回写 email_sent；复用飞书/webhook — 三通道并存 | ✓ VERIFIED | EMAIL_* Django SMTP 全仓首次引入（`settings.py:565-580`，EMAIL_HOST 空→dummy backend，EMAIL_TIMEOUT=10）；收件人/开关走 `SettingKeys.ALERT_EMAIL_ENABLED/RECIPIENTS`（`alert_notifier.py:137-147`）；`notify_channels` 单一出口按 `rule.channels` 子集分发 email/feishu/webhook 三通道各独立 best-effort（`alert_notifier.py:44-124`）；回写 `email_sent`(sent/skipped/failed) + `notified_channels`（`:79-86`）；飞书复用 `FeishuIMService.create(None).send_card`、webhook 复用 httpx + `_is_internal_host` SSRF 防护 |

**Score:** 3/3 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `server/system/models.py` | SystemAlertRule + AlertEvent + SettingKeys.ALERT_* | ✓ VERIFIED | 两模型 + 7 个 ALERT_* 常量（`:135-141`）+ 去重条件唯一约束 |
| `server/system/migrations/0012_systemalertrule_alertevent.py` | 两模型建表迁移（base 0011_gaugesample） | ✓ VERIFIED | CreateModel×2 + AddIndex + UniqueConstraint，无数据迁移；`makemigrations --check` 干净（74-01/02/03 SUMMARY 均报 No changes detected） |
| `server/system/alert_serializers.py` | 读/写序列化器 + 白名单防御 | ✓ VERIFIED | metric/op/severity ChoiceField + validate_channels(⊆{email,feishu,webhook}) + validate_dimension(键⊆受控集合值为str) |
| `server/system/alert_views.py` | 3 个 adrf APIView IsSuperUser | ✓ VERIFIED | List/Create + Detail(GET/PATCH/DELETE) + EventList(severity/status/rule_id/时间段筛选+分页倒序) |
| `server/system/alert_retention.py` | purge_alert_events 按 started_at 清理 | ✓ VERIFIED | 镜像 log_retention，按 started_at 天数 + 行数上限分批(50_000)，best-effort try/except 不反噬 |
| `server/system/alert_notifier.py` | notify_channels + 三通道 helper | ✓ VERIFIED | 单一出口 + _send_email/_send_feishu/_send_webhook，逐通道+最外层 try/except |
| `server/system/alert_evaluator.py` | evaluate_system_alerts 评估循环 | ✓ VERIFIED | metric→源分派 + 阈值比较 + 去重/恢复收口 + 单规则隔离 best-effort |
| `server/friday/settings.py` | EMAIL_* Django SMTP 配置 | ✓ VERIFIED | EMAIL_HOST/PORT/USER/PASSWORD/USE_TLS/USE_SSL/TIMEOUT/DEFAULT_FROM_EMAIL/BACKEND（`:565-580`） |
| `.env.example` | EMAIL_* 文档段 | ✓ VERIFIED | 「邮件 SMTP（系统告警通知，ALERT-03，可选）」段（`:192-199`，中文说明+英文键名） |
| `server/agents/management/commands/runapscheduler.py` | 两 job 注册 | ✓ VERIFIED | evaluate_system_alerts(IntervalTrigger ~60s, `:559-569`) + purge_alert_events(CronTrigger 05:30, `:574-582`)，max_instances=1，不动既有 job |

### Key Link Verification

| From | To | Via | Status |
|------|----|----|--------|
| `urls_system.py` | `alert_views` 三视图 | `/api/system/alerts/{rules,rules/<id>,events}/` 路由 | ✓ WIRED（`:5-45`） |
| `alert_evaluator.py` | `metrics_query.query_timeseries` | 时序类 qps/error_rate/ttft 取窗口当前值 | ✓ WIRED（import `:46`，调用 `:191/202/215`） |
| `alert_evaluator.py` | `snapshot_service.collect_snapshot` | 快照类 cpu/memory/db/redis/qdrant/queue_depth | ✓ WIRED（import `:46`，调用 `:228`） |
| `alert_evaluator.py` | `alert_notifier.notify_channels` | firing/resolved 后按 rule.channels 分发 | ✓ WIRED（`_maybe_notify:397-399`） |
| `alert_notifier.py` | `django.core.mail.send_mail` | EMAIL 通道 sync_to_async 发送 | ✓ WIRED（`:152-160`） |
| `alert_notifier.py` | `services.feishu_im.FeishuIMService` | 飞书卡片复用系统凭证 | ✓ WIRED（`:187-203`） |
| `alert_notifier.py` | `common.logging.redact_secrets_in_text` | 邮件/webhook/飞书正文 + 异常脱敏 | ✓ WIRED（import `:31`，全 helper 调用） |
| `runapscheduler.py` | `alert_evaluator.evaluate_system_alerts` | evaluate_system_alerts_job 经 run_async_task | ✓ WIRED（`:318/324/559`） |
| `alert_retention.py` | `AlertEvent.objects` 按 started_at | purge_alert_events 清理 | ✓ WIRED（`:59/63/68/73`） |

### Probe / Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Phase 74 全测试套件 | `uv run pytest test_system_alert_models/api/test_alert_notifier/evaluator/credential_leak_protection/scheduler_registration -p no:randomly -q` | **70 passed**（10.41s） | ✓ PASS |

测试覆盖要点：firing/去重(重复 firing 抛 IntegrityError)/resolved 写 duration_s 端到端生命周期；时序/快照 metric 分派；gauge 趋势类跳过(RATE-03)；单规则隔离不冒泡；邮件 skipped/sent(脱敏含 `***REDACTED***`)/failed；webhook SSRF 拦截(127.0.0.1 不发请求)/合法 200；飞书成功/未配置不调 create；notify_channels 汇总回写/helper 抛错最外层兜底不冒泡；IsSuperUser fail-closed(非超管 403)；非法 metric/channels/dimension 400；按龄/按量清理(started_at 口径不删错列)+失败降级；两 scheduler job 接线 smoke+失败不打断 + 凭证脱敏守护绿。

### Requirements Coverage

| Requirement | Source Plan | Status | Evidence |
|-------------|-------------|--------|----------|
| ALERT-01（系统告警阈值规则，运行时可改，趋势类不参与） | 74-01, 74-02 | ✓ SATISFIED | SystemAlertRule 模型 + CRUD + evaluator 阈值比较 + gauge 跳过 |
| ALERT-02（AlertEvent 落库 + 去重 + firing/resolved + 邮件状态） | 74-01, 74-02 | ✓ SATISFIED | AlertEvent 全字段 + 条件唯一约束去重 + 评估器生命周期收口 |
| ALERT-03（邮件通道 + 复用飞书/webhook 三通道并存） | 74-03 | ✓ SATISFIED | notify_channels 三通道 + EMAIL_* SMTP + 脱敏 + SSRF |

### Anti-Patterns Found

无。`alert_evaluator.py` / `alert_notifier.py` / `alert_retention.py` / 模型 / 视图 / 序列化器均无 TBD/FIXME/XXX/HACK/PLACEHOLDER 等债务标记，无空 stub 实现；`# noqa: BLE001` 均为 best-effort 观测代码刻意宽捕获（符合「观测代码绝不反噬业务」规范），非未实现占位。

### 运行时确认（非阻塞，code-level must-haves 已全部满足）

以下两项属"必须在运行环境才能最终确认"的集成信心项，**不构成未满足的成功标准**——其代码路径已被 70 个绿测全覆盖（含 mock 投递分支、firing/resolved/去重生命周期、job 接线）：

1. **真实 SMTP 投递**：配 EMAIL_* + ALERT_EMAIL_ENABLED + 收件人后触发 P0 firing，收件人实际收信、email_sent=sent。（skipped/sent/failed 分支已 mock 全测。）
2. **真实指标驱动 firing**：起 runapscheduler 长驻进程，真实 CPU/指标越线后 ~60s 内自动产 firing、恢复转 resolved。（评估逻辑、job 接线、生命周期已 transaction 测试覆盖。）

### Gaps Summary

无 gap。Phase 74 三条 ROADMAP 成功标准（ALERT-01/02/03）在代码层面全部达成：系统级告警规则独立建模 + 运行时 CRUD（趋势类默认不参与），AlertEvent 完整生命周期（P0/P1/P2 + 中文标题 + 机器可读 rule_info + 持续时长 + firing/resolved + DB 条件唯一约束去重），三通道通知分发（Django SMTP 邮件 + 复用飞书/webhook，脱敏 + SSRF + best-effort 绝不反噬）。70 个测试全绿，无债务标记，所有 artifact 与 key link 均已接线。

---

*Verified: 2026-06-25T01:10:00Z*
*Verifier: Claude (gsd-verifier)*
