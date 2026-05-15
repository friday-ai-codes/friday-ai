"""CoChangedEdgeBuilder：git log --name-only 流式 + 文件 pair counter + chunk 笛卡尔积
（per ）。
**Pitfall 防御**：必须流式处理 git log stdout，禁止 ``subprocess.check_output``
全量缓冲。100k commits 工况下 RSS < 1 GB；本实现用 ``dict[(file_a,file_b), int]``
+ ``deque[str]`` 长度 5 per pair 维持低内存。
** 决策（planner 裁量结果，方案 A：笛卡尔积 + 0.5 折扣）**：
文件级 co-change 信号展开到 chunk 级时，将文件对应的所有 chunk 做笛卡尔积，
并对最终 weight 应用 0.5 折扣（理由：HybridSearchService 仅读 chunk-level
payload，方案 B「仅文件首 chunk 建边」语义不一致；笛卡尔积折扣 + 大文件
保护（单文件 chunks > 50 时仅取前 5 个）防止边数爆炸 & 与 SameFileEdge
weight=0.3 双计数）。
**Phase 三重 bug 修复（ "0 条" 根因）**：
- B1：``_resolve_clone_path`` log 增 attr_clone_path / settings_repo_clone_dir /
 decision 三诊断字段，让 prod 0 条根因可定位
- B2：移除 ``_SINCE_WINDOW = "6 months ago"`` 时间窗，改 git log 参数
 ``--max-count={CO_CHANGED_WINDOW_COMMITS}`` —— 让 ``code_relations.constants``
 里 ``CO_CHANGED_WINDOW_COMMITS = 2000`` 字面承诺真生效（之前 drift）
- B3：``_MIN_SUPPORT = 3`` 默认改 ``_MIN_SUPPORT_DEFAULT = 2`` + 通过
 ``settings.CODEGRAPH_COCHANGE_MIN_SUPPORT`` env 覆盖（Plan 已加）。
 既有 3 测试用 @override_settings(...=3) 锁旧契约。
"""
from __future__ import annotations
import asyncio
import uuid
from collections import defaultdict, deque
from itertools import combinations, product
from pathlib import Path
from typing import TYPE_CHECKING
import structlog
from asgiref.sync import sync_to_async
from django.conf import settings
from code_relations.builders.base import BaseEdgeBuilder
from code_relations.constants import CO_CHANGED_WINDOW_COMMITS
from code_relations.models import ChunkEdge, ChunkRegistry, EdgeType
if TYPE_CHECKING:
 from repositories.models import Repository
logger = structlog.get_logger(__name__)
__all__ = ["CoChangedEdgeBuilder"]
_MIN_SUPPORT_DEFAULT = 2
"""默认最小共变更次数（per Phase B3）。
previous _MIN_SUPPORT = 3 改为默认 2，让小仓库默认能建至少 2 commit 触发的边；
既有 3 测试用 @override_settings(CODEGRAPH_COCHANGE_MIN_SUPPORT=3) 锁旧契约。
"""
def _get_min_support -> int:
 """读 settings.CODEGRAPH_COCHANGE_MIN_SUPPORT，默认 _MIN_SUPPORT_DEFAULT。
 per Phase B3：函数化让每次 build 调用都重新读 settings，
 支持 @override_settings 在测试内动态切换。
 """
 return int(getattr(settings, "CODEGRAPH_COCHANGE_MIN_SUPPORT", _MIN_SUPPORT_DEFAULT))
_SAMPLE_COMMITS_PER_PAIR = 5
"""metadata.commit_hashes 长度上限（per ）；deque(maxlen=5) 保留最近 5 个 commit。"""
_LARGE_FILE_THRESHOLD = 50
"""大文件保护阈值（per + SameFile 对齐）；单文件 chunks > 50 触发限制。"""
_LARGE_FILE_CHUNK_LIMIT = 5
"""超阈值时单文件仅取前 N 个 chunk 参与笛卡尔积；避免 10k×10k=1亿 边爆炸。"""
_CO_CHANGE_DISCOUNT = 0.5
""" chunk 级权重折扣；防止与 SameFileEdge weight=0.3 双计数。"""
# Phase B2：移除 _SINCE_WINDOW = "6 months ago"，改 --max-count={CO_CHANGED_WINDOW_COMMITS}
# 让 code_relations.constants 字面承诺（commit 数滑窗）真正生效。
class CoChangedEdgeBuilder(BaseEdgeBuilder):
 """git log 流式 → 文件 co-change pair → chunk 笛卡尔积 CO_CHANGED 边。"""
 edge_type_label: str = "CoChangedEdge"
 async def build(
 self,
 repository: "Repository",
 dirty_chunk_ids: list[uuid.UUID],
 ) -> list[ChunkEdge]:
 clone_path = self._resolve_clone_path(repository)
 if clone_path is None:
 return
 counter, samples = await self._stream_git_log(clone_path)
 min_support = _get_min_support
 filtered = {pair: cnt for pair, cnt in counter.items if cnt >= min_support}
 if not filtered:
 logger.info(
 "co_changed_no_pair_above_min_support",
 repository_id=str(repository.id),
 raw_pairs=len(counter),
 )
 return
 max_count = max(filtered.values) or 1
 file_chunks = await self._load_file_chunks(repository.id)
 edges: list[ChunkEdge] =
 for (file_a, file_b), count in filtered.items:
 chunks_a = file_chunks.get(file_a, )
 chunks_b = file_chunks.get(file_b, )
 if not chunks_a or not chunks_b:
 continue
 if len(chunks_a) > _LARGE_FILE_THRESHOLD:
 chunks_a = chunks_a[:_LARGE_FILE_CHUNK_LIMIT]
 if len(chunks_b) > _LARGE_FILE_THRESHOLD:
 chunks_b = chunks_b[:_LARGE_FILE_CHUNK_LIMIT]
 file_weight = min(1.0, count / max_count)
 weight = max(0.0, min(1.0, file_weight * _CO_CHANGE_DISCOUNT))
 pair_samples = list(samples.get((file_a, file_b), ))
 for cid_a, cid_b in product(chunks_a, chunks_b):
 if cid_a == cid_b:
 continue
 src_cid, tgt_cid = (
 (cid_a, cid_b) if str(cid_a) < str(cid_b) else (cid_b, cid_a)
 )
 edges.append(
 ChunkEdge(
 source_chunk_id=src_cid,
 target_chunk_id=tgt_cid,
 edge_type=EdgeType.CO_CHANGED,
 weight=weight,
 metadata={
 "co_change_count": int(count),
 "commit_hashes": pair_samples,
 "file_a": file_a,
 "file_b": file_b,
 },
 repository=repository,
 )
 )
 logger.info(
 "co_changed_edge_build_complete",
 repository_id=str(repository.id),
 file_pairs_above_min_support=len(filtered),
 edges_built=len(edges),
 max_count=max_count,
 )
 return edges
 @staticmethod
 def _resolve_clone_path(repository: "Repository") -> str | None:
 """定位本地 git clone 目录。
 Repository 模型本身不存 clone_path 字段；Friday 的约定路径是
 ``settings.REPO_CLONE_DIR / str(repo.id)`` (per repositories/freshness_service.py
 与 settings.REPO_CLONE_DIR 注释)。若属性级 ``clone_path`` 已被注入
 (测试 / 自定义子类)，优先采用。
 路径不存在或非目录 → 返回 None，调用方 short-circuit 不抛错。
 """
 attr = getattr(repository, "clone_path", None)
 if attr:
 path = Path(str(attr))
 else:
 path = Path(settings.REPO_CLONE_DIR) / str(repository.id)
 if not path.is_dir:
 logger.warning(
 "co_changed_skip_no_clone_path",
 repository_id=str(repository.id),
 clone_path=str(path),
 # Phase B1：3 诊断字段，让 prod 0 条根因可定位
 attr_clone_path=str(attr) if attr is not None else None,
 settings_repo_clone_dir=str(
 getattr(settings, "REPO_CLONE_DIR", "<unset>")
 ),
 decision="skip_builder",
 )
 return None
 return str(path)
 @staticmethod
 async def _stream_git_log(
 clone_path: str,
 ) -> tuple[dict[tuple[str, str], int], dict[tuple[str, str], deque[str]]]:
 """流式跑 git log，返回 (pair → count, pair → 最近 N 个 commit hash deque)。
 per /：必须用 ``asyncio.create_subprocess_exec`` + readline
 流式处理；禁止 ``subprocess.check_output`` 一次性缓冲全部 stdout。
 修复：并发 task 同步消费 stderr，避免 OS pipe buffer（默认 64KB）
 被 git stderr（LFS warning / gc advice / replace ref 等）写满后阻塞子
 进程 → 主循环只读 stdout 永远等不到 EOF → ``proc.wait`` 永久挂起。
 修复：returncode != 0 但已采集 partial counter 时，log warning
 但**保留** partial 数据（区分「致命：spawn failed / 无 stdout」与「轻
 度：尾部 SIGPIPE / 浅克隆补 ref 失败」），避免一次轻微 git 异常清空整
 builder 输出。
 """
 try:
 proc = await asyncio.create_subprocess_exec(
 "git",
 "log",
 "--name-only",
 # Phase B2：从 --since={_SINCE_WINDOW} 改为 commit 数滑窗，
 # 让 code_relations.constants.CO_CHANGED_WINDOW_COMMITS 字面承诺真生效
 f"--max-count={CO_CHANGED_WINDOW_COMMITS}",
 "--pretty=format:COMMIT %H",
 "--no-merges",
 cwd=clone_path,
 stdout=asyncio.subprocess.PIPE,
 stderr=asyncio.subprocess.PIPE,
 )
 except (FileNotFoundError, OSError) as exc:
 logger.warning("co_changed_git_spawn_failed", error=str(exc))
 return {}, {}
 if proc.stdout is None:
 logger.warning("co_changed_git_no_stdout")
 return {}, {}
 async def _drain_stderr -> bytes:
 """并发消费 stderr，避免 pipe buffer 满阻塞子进程。
 上限读取 64KB（够 log 用于诊断），超出部分静默丢弃；继续 read 直到
 EOF 让 git 不会在 stderr 写入时阻塞。"""
 if proc.stderr is None:
 return b""
 chunks: list[bytes] =
 collected = 0
 cap = 65536
 while True:
 buf = await proc.stderr.read(4096)
 if not buf:
 break
 if collected < cap:
 take = min(len(buf), cap - collected)
 chunks.append(buf[:take])
 collected += take
 return b"".join(chunks)
 stderr_task = asyncio.create_task(_drain_stderr)
 counter: dict[tuple[str, str], int] = defaultdict(int)
 samples: dict[tuple[str, str], deque[str]] = defaultdict(
 lambda: deque(maxlen=_SAMPLE_COMMITS_PER_PAIR)
 )
 current_commit: str | None = None
 current_files: set[str] = set
 def _flush_commit -> None:
 nonlocal current_commit, current_files
 if current_commit and current_files:
 for a, b in combinations(sorted(current_files), 2):
 counter[(a, b)] += 1
 samples[(a, b)].append(current_commit)
 current_commit = None
 current_files = set
 try:
 while True:
 raw = await proc.stdout.readline
 if not raw:
 break
 line = (
 raw.decode("utf-8", errors="replace").rstrip("\n").rstrip("\r")
 )
 if line.startswith("COMMIT "):
 _flush_commit
 current_commit = line[len("COMMIT "):].strip
 elif line:
 current_files.add(line)
 _flush_commit
 await proc.wait
 finally:
 stderr_bytes = await stderr_task
 if proc.returncode != 0:
 logger.warning(
 "co_changed_git_log_nonzero_exit",
 returncode=proc.returncode,
 stderr=stderr_bytes.decode("utf-8", errors="replace")[:512],
 partial_pairs=len(counter),
 )
 #：returncode != 0 但已采集 counter 时，保留 partial 数据；
 # 仅当 counter 完全为空时才 fallback 返回空（正常致命错误信号）。
 return dict(counter), dict(samples)
 @staticmethod
 async def _load_file_chunks(
 repository_id: uuid.UUID,
 ) -> dict[str, list[uuid.UUID]]:
 @sync_to_async
 def _load -> list[tuple[str, int, uuid.UUID]]:
 return list(
 ChunkRegistry.objects.filter(repository_id=repository_id)
 .order_by("file_path", "chunk_index")
 .values_list("file_path", "chunk_index", "chunk_id")
 )
 rows = await _load
 files: dict[str, list[uuid.UUID]] = defaultdict(list)
 for fp, _idx, cid in rows:
 files[fp].append(cid)
 return files
