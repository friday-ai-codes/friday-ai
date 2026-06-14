---
phase: 25-commit-index-lineref
reviewed: 2026-06-15T07:45:00Z
depth: deep
files_reviewed: 8
files_reviewed_list:
  - server/code_relations/types.py
  - server/services/indexer.py
  - server/services/chunk_lookup.py
  - server/repositories/chunk_at_views.py
  - server/repositories/urls.py
  - server/repositories/models.py
  - server/repositories/migrations/0035_repository_commit_index_boundary.py
  - server/services/commit_index.py
findings:
  blocker: 1
  high: 1
  medium: 2
  low: 2
  total: 6
status: clean
resolved_at: 2026-06-15T08:10:00Z
resolution: >-
  BL-01 / HI-01 / ME-01 / ME-02 全部修复并各自原子提交；LO-01 随 HI-01 一并修复
  （embedding/docs 数量不匹配时不推进边界 + warning）。仅 LO-02（_run_git 超时不杀子进程）
  作为低风险项暂缓——异常已被上层 best-effort 吞掉，仅丢失单次 commit 索引，不影响正确性。
---

# Phase 25: Code Review Report

**Reviewed:** 2026-06-15T07:45:00Z
**Depth:** deep
**Files Reviewed:** 8
**Status:** clean（已修复，见下方 Resolution）

## Resolution（2026-06-15）

| Finding | 处置 | 提交 |
|---------|------|------|
| BL-01（BLOCKER）| `clone_and_index_repository` 在 `_run_commit_index` 前对浅克隆 best-effort `git fetch --unshallow`（新增 `_unshallow_repo`）；集成测试改走真实 `file://` `--depth 1` 浅克隆路径，证明不补齐只见 HEAD、补齐后全历史入库 | `f6238e564` |
| HI-01（HIGH）| 仅当本轮全部 commit 成功入库才推进边界；否则保持边界，下轮整段重试（uuid5 去重）。含 LO-01 的 embedding/docs 数量不匹配 warning | `d72b1beff` |
| ME-01（MEDIUM）| 增量改为 `rev-list` 取最旧一批（≤ `COMMIT_INDEX_INCREMENTAL_CAP`），边界只推进到本批最新，剩余下轮续传——有界且不丢中段 | `0b7a8091b` |
| ME-02（MEDIUM）| `git log -z`（NUL 分记录）+ US(`\x1f`) 字段分隔 + `maxsplit=4` body 兜底，正文含分隔字节不再截断/丢弃 | `b9dcdef94` |
| LO-01（LOW）| 随 HI-01 修复（数量不匹配不推进边界 + warning） | `d72b1beff` |
| LO-02（LOW）| **暂缓**：`_run_git` 超时不 kill 子进程，异常被上层 best-effort 吞掉，仅丢失单次 commit 索引，低风险 | — |

**原始状态：** issues_found

## Summary

审查 Phase 25（commit 历史索引 IDX-01 + 行号反查 IDX-02）的源码变更。

行号反查地基（IDX-02）整体**正确且安全**：`_build_points` / `_bulk_upsert_registry_atomic`
的行号回填遵循 1-based 闭区间，create（`get_or_create.defaults`）与 update（`line_changed`
判定 + `update_fields`）两条路径一致，与 Qdrant payload `start_line/end_line` 同源；DB 约束
`chunkreg_line_range_valid` 兜底。`find_chunk_at` + REST 端点 fail-closed 严密：matcher 构造
异常 / 路径归一越界 / 判定异常一律返回 `[]`，被排除文件与「无命中」对外不可区分（无存在性
泄漏），commit 摘要只含过滤后路径、不内联 diff 正文（无被排除文件内容泄漏）。

但 **commit 历史索引（IDX-01）有一个结构性 BLOCKER**：生产路径的克隆是 `git clone --depth 1`
浅克隆，而 `_run_commit_index` 在该浅克隆上读 git 历史 —— `git log` 只能看到 HEAD 单个 commit，
历史 commit 永远索引不到，且跨索引运行会静默丢失中间 commit，直接违背本阶段「commit 历史可
语义检索」目标与 threat_model T-25-09「绝不丢 commit」。集成测试因直接对全历史本地仓库调
`index_commits`（绕过浅克隆）而通过，给出虚假信心。另有一处分批部分失败仍推进边界导致丢
commit 的 HIGH 问题。

## Blocker Issues

### BL-01: commit 历史索引运行在 `--depth 1` 浅克隆上，只能索引 HEAD，历史 commit 全部丢失

**File:** `server/services/indexer.py:3491` (clone), `server/services/indexer.py:3752` (dispatch), `server/services/commit_index.py:140-153` (first-run log)
**Issue:**
`clone_and_index_repository` 用 `clone_cmd = ["git", "clone", "--depth", "1", "--progress"]`
（`indexer.py:3491`）创建浅克隆，base 索引路径在 rmtree 之前 `await _run_commit_index(repository_id, temp_dir)`
（`indexer.py:3752`）。该路径在浅克隆上**不会** unshallow/deepen（deepen 仅发生在分支/diff 的
merge-base 逻辑里），因此 `index_commits` 看到的 `temp_dir` 只有 HEAD 一个 commit：

- 首轮 `git log --no-merges --max-count=500 HEAD`（`commit_index.py:140-149`）在浅克隆上仅返回
  HEAD 单条 → 只索引 1 个 commit，`COMMIT_INDEX_FIRST_RUN_CAP=500` 形同虚设。
- 下次索引重新浅克隆（只含新 HEAD）。上次写入的 `commit_index_boundary_sha`（旧 HEAD）**不在**
  新浅克隆里 → `boundary..HEAD` 的 `git log` 报错 → 回退首轮 bounded（`commit_index.py:126-138`）
  → 又只索引新 HEAD。两次索引之间产生的所有中间 commit **永久丢失**，从不入库。

后果：IDX-01「commit 历史可语义检索」+「增量感知」在生产中根本无法建立历史，只滚动索引仓库
tip，直接违反 phase 目标与 T-25-09「绝不丢 commit」。`test_commit_index_integration.py:107`
直接对本地全历史仓库调 `index_commits`，绕过浅克隆，因此测试全绿 → 虚假信心。

**Fix:** 在调 `_run_commit_index` 前确保历史可用。两种方向择一：
- 在 commit 索引前对 `temp_dir` 渐进 deepen / unshallow（复用 `_progressive_deepen` / `git fetch --unshallow`），再 `index_commits`；或
- `index_commits` 内显式 `git fetch --unshallow`（best-effort）后再读历史，并把首轮上限改为对 unshallow 后的历史生效。

```python
# indexer.py，_run_commit_index 之前（base 路径）
if not branch:
    await _run_sensitive_detection(repository_id, temp_dir, index_result)
    # 浅克隆下 git log 只见 HEAD —— commit 历史索引前需补齐历史
    if await _is_shallow_clone(temp_dir):
        await _unshallow_for_commit_index(temp_dir, proxy_url)  # git fetch --unshallow，best-effort
    await _run_commit_index(repository_id, temp_dir)
```
并在 `commit_index.py` 增量边界失效（boundary 不在新克隆）时，与「真正 force-push/rebase」区分，
避免每次都退化为首轮 + 重复丢中段 commit。

## High Issues

### HI-01: 分批部分失败仍推进边界 → 被跳过的 commit 永久丢失（与「下次重试」注释自相矛盾）

**File:** `server/services/commit_index.py:278-365`
**Issue:**
`index_commits` 是「读 `boundary..HEAD` 全部 commit → 逐条构建 → 批量 embedding → 批量 upsert →
upsert 成功后 `aupdate(commit_index_boundary_sha=head_sha)`」。问题在于**部分 commit 被跳过时
边界仍推进到 HEAD**：

- 逐条构建循环里单 commit 异常（如 `_changed_files` 失败）→ `continue` 跳过该 commit
  （`commit_index.py:283-287`）；
- `embedding is None` 的 commit 跳过 point（`commit_index.py:318-325`），注释明确写
  「下次重试（边界未到 HEAD 时）」；
- 但只要还有**任意**成功 point，`if not points` 不触发，`QdrantService.upsert_vectors` 成功后
  无条件 `aupdate(...head_sha)`（`commit_index.py:357`）。

于是被跳过的 commit 处于 `(boundary_old, head]` 区间内，边界一旦推到 HEAD，下次 `boundary..HEAD`
不再包含它们 → 永不重试 → **静默丢 commit**。注释承诺的「下次重试」在 boundary 已达 HEAD 时
不成立，违反 T-25-09 advance-only-on-success / 绝不丢 commit。

**Fix:** 仅在「全部待索引 commit 都成功入库」时才推进边界到 HEAD；否则把边界推进到「最后一个
连续成功的 commit」或干脆不推进（下次整段重试，靠 uuid5 去重避免重复）。

```python
expected = len(commits)          # 本轮应索引数（过滤 merge 后）
succeeded = len(points)          # 实际成功 point 数
ok = await sync_to_async(QdrantService.upsert_vectors)(repository_id, points)
if ok and succeeded == expected:
    await Repository.objects.filter(id=repository_id).aupdate(commit_index_boundary_sha=head_sha)
else:
    # 有 commit 被跳过/失败：不推进边界，下次靠 uuid5 去重重试，绝不丢
    logger.warning("commit_index_partial_skip_no_advance",
                   expected=expected, succeeded=succeeded)
```
（注意 `expected` 需以真正进入 `docs`/`payloads` 的条数为准，merge 已被 `--no-merges` 排除。）

## Medium Issues

### ME-01: 增量 `boundary..HEAD` 的 git log 无上限 → 超大历史一次性灌入（DoS / OOM / 超时）

**File:** `server/services/commit_index.py:126-132`
**Issue:**
首轮路径有 `--max-count=COMMIT_INDEX_FIRST_RUN_CAP`（`:144`），但增量路径
`["log", "--no-merges", f"--format=...", f"{boundary}..HEAD"]`（`:127-129`）**无 `--max-count`**。
当 boundary 与 HEAD 相隔极远（长期未索引后一次性追平、或大规模 history 合入），会把所有 commit
一次性解析进内存、逐条 `diff-tree` 子进程、再一次 `generate_embeddings_batch(docs)` 全量 embedding，
易触发内存膨胀 / embedding 成本暴涨 / `_GIT_TIMEOUT=30s` 超时。当前被 BL-01 浅克隆掩盖（增量从不
真正生效），一旦修复 BL-01 即变为活跃风险。
**Fix:** 增量路径同样加 `--max-count`（或分页游标按批推进边界），单批上限内多轮推进，保证有界。

### ME-02: git log 记录/字段分隔符可被 commit message 正文碰撞 → 该 commit 解析损坏/丢弃

**File:** `server/services/commit_index.py:47-52, 98-114`
**Issue:**
`_LOG_FORMAT = "%H%x00%an%x00%ae%x00%cI%x00%B%x1e"`，`_parse_log` 用 `\x1e` 切记录、`\x00` 切字段。
注释断言「`%B` 原始 body 可含换行，但不含 NUL/RS」，但 commit message 正文**可以**包含字节
`0x1e`(RS) 或 `0x00`(NUL)。一旦包含：
- body 含 `\x1e` → `raw.split(_RECORD_SEP)` 把单 commit 拆成两段，后半段 `len(fields) < 5` 被当
  `malformed_record` 跳过（`:106-108`），该 commit message 被截断、尾部丢失；
- body 含 `\x00` → `record.split(_FIELD_SEP)` 字段数 >5，`fields[4]` 只取到 NUL 前的片段，message 截断。

属健壮性缺陷（低概率但真实），会让个别 commit 文档损坏或丢失。
**Fix:** 改用 `git log -z`（NUL 分隔记录）配合固定字段数 `--format`，或对解析按「前 4 个分隔符切出
固定字段、剩余全部归 body」（`split(_FIELD_SEP, 4)`）+ 用更不可能出现的多字节哨兵，降低碰撞面。
当前 `split(_FIELD_SEP)` 应至少改为 `record.split(_FIELD_SEP, 4)` 以避免 body 内 NUL 丢尾。

## Low Issues

### LO-01: embedding 批返回长度短于 docs 时被 zip 静默截断

**File:** `server/services/commit_index.py:317`
**Issue:** `for i, (payload, embedding) in enumerate(zip(payloads, embeddings))`：若
`generate_embeddings_batch` 返回的列表短于 `docs`（部分供应商异常），`zip` 静默丢弃尾部 payload，
配合 HI-01 的边界推进会丢这些 commit。
**Fix:** 断言 `len(embeddings) == len(docs)`，不等则记 warning 并按 HI-01 不推进边界。

### LO-02: `_run_git` 超时不杀子进程 → git 进程泄漏

**File:** `server/services/commit_index.py:72-86`
**Issue:** `await asyncio.wait_for(proc.communicate(), timeout=_GIT_TIMEOUT)` 超时抛 `TimeoutError`，
但未 `proc.kill()`/`await proc.wait()`，git 子进程成为孤儿；多仓高频索引下可能累积。异常被
`_run_commit_index` best-effort 吞掉，仅丢失本次 commit 索引。
**Fix:** `try/except (TimeoutError)` 中 `proc.kill()` 并 `await proc.wait()` 回收，再向上传递。

---

_Reviewed: 2026-06-15T07:45:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
