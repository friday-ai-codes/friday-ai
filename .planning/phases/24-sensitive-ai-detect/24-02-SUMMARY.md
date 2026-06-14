---
phase: 24-sensitive-ai-detect
plan: 02
subsystem: api
tags: [django, sensitive-detection, indexer-hook, background-runner, langchain, llm-classification, graceful-degrade, privacy]

# Dependency graph
requires:
  - phase: 24-sensitive-ai-detect (plan 01)
    provides: detect_sensitive_files(repository_id, repo_path)、SuggestionCandidate、_upsert_suggestion、severity 常量
  - phase: provider/llm 既有栈
    provides: services.background_runner.run_in_background、ProviderConfigService.aresolve_or_error、agents.llm_factory.build_chat_model/content_to_text
provides:
  - run_full_index FINALIZING 末尾经 run_in_background best-effort 触发 detect_sensitive_files（不阻断索引终态）
  - sensitive_detect.classify_ambiguous_files：可选 LLM 二分类段（provider 缺失/失败 graceful 退化）
  - AmbiguousCandidate 输入契约 + _build_llm_feature 最小化特征（强密钥不外送）
affects: [24-03 REST API（消费 detector=llm 建议）, 24-04 前端建议面板]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "索引终态钩子：FINALIZING 末尾 run_in_background 派发 + try/except 吞派发异常（fail-safe，不阻断 success）"
    - "可选 LLM 增强段：aresolve_or_error → ProviderMissingError graceful 退化，整段 try/except 退化为空增量"
    - "隐私最小化：只送文件名 + 布尔特征（_build_llm_feature），real_secret 排除候选，reason 服务端兜底脱敏（_redact_llm_reason）"

key-files:
  created:
    - server/tests/repositories/test_sensitive_index_trigger.py
    - server/tests/services/test_sensitive_detect_llm.py
  modified:
    - server/services/indexer.py
    - server/services/sensitive_detect.py

key-decisions:
  - "Task 1 触发测试沿用 24/auto-after-index 既有范式：『复刻派发模板 helper + 源码 token 漂移 guard』，避免在网络隔离/重依赖环境跑完整 run_full_index"
  - "送 LLM 的 human 内容只含文件名 + 扩展名 + has_sensitive_keyword 布尔，**完全不送正文/sample_text**——从源头杜绝密钥外送（强于 PLAN『截断 N 字符』措辞，Rule 2 隐私加固）"
  - "新增 _redact_llm_reason 对 LLM 中文理由做服务端兜底脱敏（高熵串 + _SECRET_PATTERNS 替换为 [已脱敏]），纵深防御 T-24-06"
  - "classify_ambiguous_files 作为独立可选段，不默认接入 detect_sensitive_files 强制路径；确定性结果不依赖 LLM 成功"

patterns-established:
  - "best-effort 后台触发：run_in_background(factory) + 外层 try/except + warning 日志，绝不冒泡阻断主流程"
  - "LLM 段四不变量：graceful 退化 / 强密钥排除 / 最小化特征 / 仅产 likely_sensitive pending 建议"

requirements-completed: [EXCL-03]

# Metrics
duration: ~18min
completed: 2026-06-15
---

# Phase 24 Plan 02: 敏感检测索引触发 + 可选 LLM 增强 Summary

**run_full_index FINALIZING 末尾经 run_in_background best-effort 触发确定性检测（检测失败不阻断索引 success），并新增可选 LLM 二分类段 classify_ambiguous_files（provider 缺失/失败 graceful 退化、强密钥绝不外送、最小化布尔特征）**

## Performance

- **Duration:** ~18 min
- **Completed:** 2026-06-15
- **Tasks:** 2（Task 1 auto；Task 2 TDD：test → feat）
- **Files modified/created:** 4（2 改 + 2 新）

## Accomplishments
- `run_full_index` 在 `_refresh_tree_facts()` 之后、`return success` 之前，经 `run_in_background(lambda: detect_sensitive_files(self.repository_id, repo_path), name="sensitive-detect:{id}")` 派发检测；整段 try/except 吞派发异常——检测失败 / 派发失败均不阻断索引 success 终态（D-04 fail-safe，T-24-05）。
- `classify_ambiguous_files(repository_id, candidates)`：可选 LLM 二分类段。`aresolve_or_error` 返回 `ProviderMissingError`、缺默认模型、或任何调用/解析异常 → 一律返回空增量（0），不冒泡，确定性结果不受影响（T-24-07）。
- 隐私边界：`real_secret` 强命中候选显式排除出 LLM 输入；`_build_llm_feature` 只产「文件名 + 扩展名 + has_sensitive_keyword 布尔」，正文/sample_text 绝不外送；`_redact_llm_reason` 对 LLM 理由做高熵/密钥样 token 服务端兜底脱敏（T-24-06）。
- LLM 判 `sensitive=true` → `severity=likely_sensitive, detector=llm` 经统一 `_upsert_suggestion` 入库；仅产 pending 建议，绝不建规则/删数据（T-24-08）。
- 18 例测试全绿（6 触发 guard + 6 LLM guard + 6 既有确定性检测器无回归），ruff 0 错。

## Task Commits

1. **Task 1: run_full_index 后台触发检测（best-effort 不阻断）** — `a257682b7` (feat)
2. **Task 2 RED: 可选 LLM 二分类段守护测试** — `2bc3e48f1` (test)
3. **Task 2 GREEN: classify_ambiguous_files 实现** — `403a19c77` (feat)

_Note: Task 2 为 TDD（test → feat）；无需 refactor 提交。TDD gate 满足（test 提交在 feat 之前）。_

## Files Created/Modified
- `server/services/indexer.py` — `run_full_index` FINALIZING 末尾新增敏感检测后台派发段（try/except 兜底）
- `server/services/sensitive_detect.py` — 新增 `AmbiguousCandidate`、`classify_ambiguous_files`、`_build_llm_feature`、`_parse_llm_verdicts`、`_redact_llm_reason`、`_DETECTOR_LLM` 常量；顶层 import `ProviderConfigService`
- `server/tests/repositories/test_sensitive_index_trigger.py` — 触发/fail-safe/派发失败/source token 漂移 guard（6 例）
- `server/tests/services/test_sensitive_detect_llm.py` — graceful 退化 + 强密钥不外送 + 最小化特征 + 命中入库 guard（6 例）

## Decisions Made
- 见 frontmatter key-decisions。核心：触发测试沿用既有「复刻模板 helper + 源码 token guard」范式（不跑重依赖完整索引）；LLM 入参完全不含正文（强于 PLAN 措辞的隐私加固）；新增 `_redact_llm_reason` 服务端兜底脱敏。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] LLM 入参完全剔除正文 + reason 服务端兜底脱敏**
- **Found during:** Task 2（LLM 段实现）
- **Issue:** PLAN action 提到 human 内容可含「首行非敏感摘要或截断 N 字符」。任何对原始正文的截断外送都存在密钥泄漏残余风险（T-24-06 信息泄露面），且 `_redact_reason` 仅接受 (kind, line_no) 无法对自由文本脱敏。
- **Fix:** `_build_llm_feature` 只外送「文件名 + 扩展名 + has_sensitive_keyword 布尔」，正文/sample_text 仅用于本地计算布尔信号、绝不进请求；并新增 `_redact_llm_reason` 对 LLM 返回理由做高熵串 + `_SECRET_PATTERNS` 替换兜底，确保入库 reason 绝不含密钥本体。
- **Files modified:** server/services/sensitive_detect.py
- **Verification:** `test_real_secret_excluded_and_secret_value_not_sent` 断言密钥值与 real_secret 文件名均 not in model 入参；`test_sensitive_true_upserts_likely_sensitive_llm` 断言 reason 不含密钥值。
- **Committed in:** 403a19c77 (Task 2 GREEN commit)

---

**Total deviations:** 1 auto-fixed（1 missing critical / 隐私加固）
**Impact on plan:** 偏离仅在 PLAN 既定隐私目标方向上加固（更严格地不外送正文），无 scope creep，不改变对外契约。

## Issues Encountered
- Task 1 源码 guard 初版用 `src.find('"status": "success"')` 命中 run_full_index 内**更早**一处 success 字面量，导致 `dispatch_idx < return_idx` 误判失败 → 改用 `rfind`（FINALIZING 末尾返回是最后一处 success）后通过。

## Threat Surface Scan
本 plan 无新增网络端点/认证路径/schema 变更。新增信任边界缓解均落地并被测试锁定：T-24-05（后台派发 + try/except，检测失败索引仍 success）、T-24-06（real_secret 排除候选 + 只送文件名/布尔特征 + reason 兜底脱敏，断言密钥值 not in 入参）、T-24-07（aresolve_or_error → ProviderMissingError graceful 退化 + 整段 try/except 返回空增量）、T-24-08（LLM 段仅产 likely_sensitive pending 建议）。无新增威胁面。

## User Setup Required
None - 复用既有 langchain/provider_config 栈，无新增依赖、无外部服务配置（T-24-SC accept）。

## Next Phase Readiness
- 索引完成后敏感检测自动后台触发，建议名单（含 detector=llm）持续产出，24-03 REST API（list/accept/dismiss）可直接消费。
- `classify_ambiguous_files` 作为独立可选段就绪，后续可在 detect_sensitive_files 内对 config_review 子集顺带调用（确定性结果已先行落库，LLM 失败不影响）。

## Self-Check: PASSED

---
*Phase: 24-sensitive-ai-detect*
*Completed: 2026-06-15*
