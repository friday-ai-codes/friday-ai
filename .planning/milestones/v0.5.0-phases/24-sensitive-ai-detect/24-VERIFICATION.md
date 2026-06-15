---
phase: 24-sensitive-ai-detect
verified: 2026-06-15T01:25:00Z
status: passed
score: 16/16 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: none
  previous_score: n/a
deferred_uat: # frontend-only browser checks — non-blocking in autonomous mode
  - test: "仓库详情页排除区可见「AI 敏感文件建议」面板，real_secret 行以危险色告警样式置顶呈现"
    expected: "面板渲染建议列表，real_secret 醒目危险色 + triangle-alert 图标置顶，第一眼可见"
    why_human: "视觉呈现/真实浏览器渲染需人工确认（组件守护测试已覆盖结构与文案）"
  - test: "点击接受弹出确认框含「不会自动删除已索引内容，需在下方清理面板显式执行」，确认后列表即时更新且排除规则面板出现新规则"
    expected: "确认框文案正确、accept 后建议消失、ExclusionRulesPanel 出现 source=ai_suggested 规则"
    why_human: "端到端浏览器交互/即时刷新需人工确认（mutation + invalidate 已由单测覆盖）"
---

# Phase 24: 敏感文件 AI 识别建议名单 Verification Report

**Phase Goal:** 索引/描述生成阶段识别敏感文件，产出建议名单供用户确认/增删，不静默删除。
**Verified:** 2026-06-15T01:25:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Roadmap Success Criteria

| # | Success Criterion | Status | Evidence |
| - | ----------------- | ------ | -------- |
| SC1 | 能识别密钥/env/敏感信息类文件并给出建议名单 | ✓ VERIFIED | `sensitive_detect.py` 文件名启发式（`BUILTIN_GLOBAL_DEFAULTS` glob）+ 内容扫描（私钥块/AWS/GitHub/Slack/通用赋值/高熵串）→ `SensitiveFileSuggestion(status=pending)`；30 项后端测试全绿 |
| SC2 | 走"建议+提醒+用户确认"不静默删除；真密钥高优先级告警 | ✓ VERIFIED | accept 仅建 `RepoExclusionRule(ai_suggested)`，无 `CleanupRun`/`run_cleanup`/purge；real_secret severity 排序置顶 + 前端告警样式 |

### Observable Truths

| # | Truth | Status | Evidence |
| - | ----- | ------ | -------- |
| 1 | `.env`(AWS key)/`id_rsa`(私钥块) 判为 severity=real_secret | ✓ VERIFIED | `_SECRET_PATTERNS` 含私钥/AWS/赋值正则；`test_sensitive_detect.py` 通过 |
| 2 | 普通配置文件不被过度标记 | ✓ VERIFIED | `_finalize` 无 severity 返回 None；config.yaml 用例通过 |
| 3 | reason 只描述类型+行号，绝不含密钥本体 | ✓ VERIFIED | `_redact_reason(kind, line_no)` 为 reason 唯一构造入口；测试断言 value-not-in-reason |
| 4 | upsert 幂等 + dismissed-respect + real_secret 升级打扰 | ✓ VERIFIED | `_upsert_suggestion` 经 `aupdate_or_create`，dismissed 仅升级 real_secret 才回 pending |
| 5 | 索引完成后台 best-effort 触发，不阻断索引终态 | ✓ VERIFIED | `indexer.py:1238-1251` `run_in_background(lambda: detect_sensitive_files(...))` + try/except，位于 success return 前 |
| 6 | 检测抛异常索引仍 success（fail-safe） | ✓ VERIFIED | `test_index_returns_success_when_detection_raises` + `test_dispatch_failure_does_not_break_success` 通过 |
| 7 | 无 LLM provider 时确定性检测仍工作（graceful 退化） | ✓ VERIFIED | `classify_ambiguous_files` `ProviderMissingError`/任意异常 → return 0，不冒泡；确定性段独立 |
| 8 | LLM 仅对 ambiguous；real_secret 绝不送 LLM | ✓ VERIFIED | `ambiguous = [c for c in candidates if c.severity != _REAL_SECRET]`；`_build_llm_feature` 仅送文件名+布尔特征 |
| 9 | 可列出建议，按 severity 排序（real_secret 优先） | ✓ VERIFIED | `RepositorySensitiveSuggestionsView` + `_SENSITIVE_SEVERITY_ORDER` Python 侧排序 |
| 10 | accept → 建 RepoExclusionRule(ai_suggested) + 标 accepted | ✓ VERIFIED | `aget_or_create(source=AI_SUGGESTED, rule_type=GLOB)` + `asave(status=accepted)` + `invalidate_matcher_cache` |
| 11 | dismiss → 标 dismissed，不建规则/不删数据 | ✓ VERIFIED | dismiss 分支仅 `asave(status=dismissed)` |
| 12 | accept/dismiss 绝不静默删除已索引数据 | ✓ VERIFIED | accept 路径无 `CleanupRun`/`run_cleanup`/purge；返回 `cleanup_available: true` 仅作引导；测试断言无副作用 |
| 13 | 用户在仓库详情页看到建议列表（按 severity 排序） | ✓ VERIFIED | `[id]/index.vue:612` 挂载 `<SensitiveSuggestionsPanel>`；面板 useQuery list 保序渲染（浏览器视觉见 deferred UAT） |
| 14 | real_secret 高优先级告警样式（危险色+图标） | ✓ VERIFIED | 面板 `data-testid="real-secret-alert"` 危险色块 + triangle-alert；guard spec 断言（浏览器视觉见 deferred UAT） |
| 15 | 接受/忽略后列表即时更新 | ✓ VERIFIED | `useMutation` + `invalidate()` 失效 list + exclusions 键 |
| 16 | 接受不静默删除；UI 引导显式清理 | ✓ VERIFIED | `sensitive.acceptConfirm.description` / `toast.accepted` 含「不会自动删除…在下方清理面板显式执行」 |

**Score:** 16/16 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/repositories/models.py` | `SensitiveFileSuggestion` 模型 | ✓ VERIFIED | L894：Severity/Detector/Status 三组 TextChoices + unique(repository,path) + index(repository,status) |
| `server/repositories/migrations/0034_sensitive_file_suggestion.py` | 建表迁移依赖 0033 | ✓ VERIFIED | CreateModel + 约束/索引一致；`makemigrations --check` 报 No changes |
| `server/services/sensitive_detect.py` | 确定性检测器 + 可选 LLM 段 | ✓ VERIFIED | 自走遍历 + 启发式 + 内容扫描 + 脱敏 + upsert + LLM graceful；未引用 `scan_directory`（grep=0） |
| `server/services/indexer.py` | run_full_index 后台触发 | ✓ VERIFIED | FINALIZING 末尾 `run_in_background` 派发，return success 前 |
| `server/repositories/serializers.py` | `SensitiveFileSuggestionSerializer` | ✓ VERIFIED | L227 ModelSerializer，全 read_only |
| `server/repositories/views.py` | list + action 视图 | ✓ VERIFIED | L1126 list / L1165 action（accept/dismiss） |
| `server/repositories/urls.py` | sensitive-suggestions 路由 | ✓ VERIFIED | L254 list + L259 action |
| `web/src/api/sensitiveSuggestions.ts` | 类型化 client | ✓ VERIFIED | `sensitiveSuggestionsApi` list/accept/dismiss，契约对齐后端 |
| `web/src/components/repository/SensitiveSuggestionsPanel.vue` | 建议面板 | ✓ VERIFIED | 列表+real_secret 告警+accept/dismiss+空态+脱敏 reason 渲染 |
| `web/src/pages/repositories/[id]/index.vue` | 页面挂载 | ✓ VERIFIED | L16 import + L612 挂载于排除区 |

### Key Link Verification

| From | To | Via | Status |
| ---- | -- | --- | ------ |
| sensitive_detect.py | exclusion.BUILTIN_GLOBAL_DEFAULTS | import 复用文件名基线 | ✓ WIRED |
| sensitive_detect.py | SensitiveFileSuggestion | aupdate_or_create upsert | ✓ WIRED |
| indexer.py | background_runner.run_in_background | 后台派发不阻断 | ✓ WIRED |
| sensitive_detect.py | provider_config.ProviderConfigService | aresolve_or_error graceful | ✓ WIRED |
| views.py | RepoExclusionRule(ai_suggested) | accept 建规则 | ✓ WIRED |
| views.py | exclusion.invalidate_matcher_cache | accept 后失效缓存 | ✓ WIRED |
| SensitiveSuggestionsPanel.vue | sensitiveSuggestionsApi | useQuery + useMutation | ✓ WIRED |
| [id]/index.vue | SensitiveSuggestionsPanel | 排除区挂载 | ✓ WIRED |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| 迁移无漂移 | `makemigrations --check --dry-run repositories` | No changes detected | ✓ PASS |
| 检测器不复用白名单遍历 | `grep -c scan_directory sensitive_detect.py` | 0 | ✓ PASS |
| Phase 24 后端测试 | `pytest test_sensitive_detect{,_llm}.py test_sensitive_index_trigger.py test_sensitive_suggestions_api.py` | 30 passed | ✓ PASS |

### Anti-Patterns Found

无阻断性反模式。检测器/视图无未引用调试标记（TBD/FIXME/XXX）；`return 0` / `return None` 均为受控 fail-safe/无命中语义，非 stub。

### Deferred (non-blocking UAT)

前端浏览器视觉/端到端交互检查在 autonomous 模式下作为非阻断 UAT 延后（组件守护测试 `SensitiveSuggestionsPanel.spec.ts` 已覆盖结构、文案与 mutation 行为）。详见 frontmatter `deferred_uat`。

### Gaps Summary

无 gap。EXCL-03 全链路在源码中落地并被测试锁定：确定性检测（脱敏、real_secret 识别）→ 索引 best-effort 触发（fail-safe）→ 可选 LLM graceful 退化（强密钥不外送）→ REST list/accept/dismiss（accept 建 ai_suggested 规则、绝不静默删）→ 前端建议面板（real_secret 告警 + 显式清理引导）。

---

_Verified: 2026-06-15T01:25:00Z_
_Verifier: Claude (gsd-verifier)_
