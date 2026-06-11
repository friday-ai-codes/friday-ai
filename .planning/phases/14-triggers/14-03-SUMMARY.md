---
phase: 14-triggers
plan: 03
subsystem: knowledge
tags: [kmod-05, enh-01, diff-archive, modifies-chunk, unidiff, zlib]
requires:
  - 14-01 CodeChangeArchive 模型 / EdgeSpec chunk 扩展 / chunk_in_edges / diff chunker
  - 14-02 GitPlatformClient.get_branch_diff 双平台实现（skip-PR 兜底）
provides:
  - knowledge/diff_archive.py 纯函数层（parse_diff_files / is_generated_file / compress·decompress_diff / build_code_change_content）
  - resolve_modified_chunks ENH-01 对齐阶梯（符号级→行号级→文件级封顶 20→unresolved）
  - archive_code_change DiffArchiver service（九步编排，ArchiveResult 即 14-06 normalizer 全部素材）
  - conftest fake_git_platform fixture（可配置 fake client，记录调用参数）
affects:
  - 14-06 task_result normalizer（只调用 archive_code_change 并组装事件，零认知成本）
tech-stack:
  added: []
  patterns:
    - 纯函数层零 IO/零 ORM（chunking.py 哲学）；ORM 仅在 async 函数内（含函数体 lazy import）
    - 边只产 EdgeSpec，写入收口 apply_edge_specs（diff_archive 内 graph_store/add_edge 零命中）
    - 对齐查询恒 branch_name=""（base 命名空间，Pitfall 7）
key-files:
  created:
    - server/knowledge/diff_archive.py
  modified:
    - server/tests/knowledge/test_diff_archive.py
    - server/tests/knowledge/test_modifies_chunk.py
    - server/tests/knowledge/conftest.py
decisions:
  - 阶梯 ①② 行重叠查询用"逐 hunk 区间查询 + Python 侧并集"替代 Q OR 聚合（语义等价，避免 django.db 进入文件级 grep，保持纯函数区零 ORM 验收锚点干净）
  - IntegrityError 在 archive_code_change 函数体内 lazy import（同上纪律）
  - build_large_diff 夹具返回 list[MRDiffFile]（RESEARCH 原型为 str；对齐 parse_diff_files 输入形态，14-02 双客户端实际返回即 hunk 级片段）
  - 畸形防线补充判定："非空 diff 解析出零 hunk"（随机文本被 unidiff 静默跳过的形态）也降级 parse_failed
metrics:
  duration: ~16min
  tasks: 3
  files: 4
completed: 2026-06-12
---

# Phase 14 Plan 03: DiffArchiver 三层件（解析/对齐/归档编排）Summary

`knowledge/diff_archive.py` 落地 KMOD-05 + ENH-01 全部重逻辑：unidiff 文件级解析（畸形降级"只归档不解析"）、生成文件判定、zlib 压缩、256KB content 预算构造的纯函数层 + 符号对齐四级阶梯（封顶 20、unresolved 懒解析跟踪）+ archive_code_change 九步编排（幂等短路/凭证降级/放大参数/8MB 截断），14-06 normalizer 只需调用并组装事件。

## Tasks Completed

| Task | Name | Commits | Key Files |
|------|------|---------|-----------|
| 1 | 纯函数层（unidiff 解析/生成文件判定/压缩/content 构造）（TDD） | b7611e7a (RED) / 3faafb3d (GREEN) | diff_archive.py, test_diff_archive.py |
| 2 | ENH-01 符号对齐阶梯 resolve_modified_chunks（TDD） | 673a38e5 (RED) / a7b61132 (GREEN) | diff_archive.py, test_modifies_chunk.py |
| 3 | DiffArchiver service archive_code_change + fake git client（TDD） | 975c5310 (RED) / 552178eb (GREEN) | diff_archive.py, test_diff_archive.py, conftest.py |

## 交付物对照（must_haves）

- ✅ unidiff 文件级解析（路径/增删行/change_type/hunk 新文件侧行区间）；畸形 diff warning 降级 parse_failed、其余文件正常、整批不 raise（test_parse_diff_files_golden / test_malformed_diff_degrades_to_parse_failed，T-14-08）
- ✅ 生成文件判定三规则（lockfile 路径 / "DO NOT EDIT" 标记 / 3001 行阈值）+ 普通源码不误判；is_generated 只跳过向量化与符号对齐，归档原文不跳（test_is_generated_file_rules + 阶梯 Test 5）
- ✅ 对齐阶梯按文件独立：①Symbol(chunk_id) 行重叠（feature 分支符号不命中，恒查 base）②ChunkRegistry 行重叠（NULL 行号过滤）③文件级降级恰 20 条 + 超出 5 条 unresolved ④新增文件零边 + unresolved 记录；resolution 字段标注层级（TestResolutionLadder 六用例）
- ✅ DiffArchiver 端到端：aexists 幂等短路（fake 调用计数不增）→ 凭证缺失 warning 降级 None → 放大参数（≥1000/≥100000）拉 diff + truncated 尊重落库 → zlib 压缩归档（往返逐字节一致、sha256/size 自洽）→ 对齐 → 返回归一化 content（题头+摘要+diff 段）与 EdgeSpec 列表（TestDiffArchiverService 五用例，T-14-10/T-14-12）
- ✅ 大 diff 夹具（31 文件 ≥10k 行）：解析完成、lockfile is_generated、content 预算截断 ≤256KB、chunk 数 ≤ MAX_DIFF_CHUNKS、测试秒级完成（test_large_* 两用例，T-14-09）

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Task 3 测试夹具 hunk 头声明行数与正文不符**
- **Found during:** Task 3 GREEN
- **Issue:** 夹具 `@@ -1,3 +1,5 @@` 声明 3/5 行实际只有 2/4 行，unidiff 响亮报 "Hunk is shorter than expected"，文件被正确降级 parse_failed 导致统计断言失败（实现行为正确，夹具错误）
- **Fix:** 修正夹具头为 `@@ -1,2 +1,4 @@`
- **Commit:** 552178eb

### 设计微调（与 plan 文本的差异，语义不变）

**2. 阶梯 ①② 行重叠查询不用 Q OR 聚合**
- plan 写"逐 hunk 区间 OR 聚合"；实现为逐 hunk 区间独立查询 + Python 侧字典并集（语义等价，hunk 数小）。动机：`from django.db.models import Q` 会令验收锚点 `rg "django.db" diff_archive.py` 文件级命中，保持纯函数区零 ORM 的 grep 干净
- `IntegrityError` 同理在 archive_code_change 函数体内 lazy import（文件内唯一 django.db 命中行，且在 service 层 async 函数内——符合"ORM 仅 Task 2/3 async 函数使用"的验收语义）

**3. build_large_diff 返回 list[MRDiffFile] 而非 str**
- RESEARCH 原型返回拼接 str；parse_diff_files 输入是 MRDiffFile 列表（14-02 双客户端契约为 hunk 级片段），夹具直接产出输入形态，测试内 `_raw_by_path` helper 按 service 步 ④ 同款拼回原文

其余按计划逐字执行。

## Known Stubs

无。

## Verification

- `uv run pytest tests/knowledge/ -x` → 154 passed（14-01 既有 + 本 plan 新增 21 用例，零回归）
- `uv run pytest tests/knowledge/test_diff_archive.py -k large -x` → 2 passed（SC#5 大 diff 防线）
- `uv run ruff check knowledge/ tests/knowledge/` + `ruff format --check` → 全部通过
- 验收锚点：`rg "import requests|httpx|django.db"`（纯函数区零命中，唯一 django.db 在 service async 函数体内）；`rg -c "MAX_FILE_LEVEL_EDGES_PER_FILE = 20"` == 1；`rg 'branch_name=""'` 命中；`rg "graph_store|add_edge"` 零命中；`rg "os.environ|FRIDAY_"` 零命中；token 命中行均不在 logger 调用内

## Self-Check: PASSED

- FOUND: server/knowledge/diff_archive.py
- FOUND: server/tests/knowledge/test_diff_archive.py（TestDiffPureFunctions/TestLargeDiff/TestDiffArchiverService）
- FOUND: server/tests/knowledge/test_modifies_chunk.py（TestResolutionLadder）
- FOUND: server/tests/knowledge/conftest.py（fake_git_platform）
- FOUND: commit b7611e7a / 3faafb3d / 673a38e5 / a7b61132 / 975c5310 / 552178eb
- tests green（154 passed）/ ruff check + format clean
