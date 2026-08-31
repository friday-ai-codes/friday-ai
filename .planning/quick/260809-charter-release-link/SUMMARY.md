---
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: unknown
---

# Summary — 章程全量起草 + 上线记录挂仓

## Done

- **仓库章程**：对全部 257 个有摘要的仓，用系统 mimo（`mimo-v2.5-pro`）起草
  `RepoCharter`，`source=ai_draft`，**0 失败**；走 `acquire_llm_slot`（Redis，
  凭证并发上限 50）+ 本地 Semaphore(8)

- **上线挂仓**：在既有 2049 条边上继续补齐
  - 确定性（服务名/关联仓库精确匹配）+478 实体 / +632 边
  - mimo 服务别名映射（98 唯一服务名 → 10 命中）+33 实体 / +34 边
  - 现合计 **2560/3997** 上线实体有仓边、**3154** 条 `RELATES_TO`
- **charter_service 小修**：关联裁决纳入 `confirmed/verifying/verified/rejected`；
  起草输入追加已挂仓的上线记录；支持指定 `provider_credential_id`/`model`

## 刻意未做

- **未删** `delivery.ReleaseRecord`（用户另行清理）
- **未**自动 `human_confirmed` 章程（需人工确认门）
- 仍未挂仓的 **1437** 条：服务名在 Friday 270 仓里没有对应仓库（mimo 正确返回 null），
  要挂只能先把那些仓导入索引

## 产物

- `.planning/quick/260809-charter-release-link/backfill.py`
- `service-alias-map.json` / `backfill-report.json`
