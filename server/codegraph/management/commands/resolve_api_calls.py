"""Management command: 对指定前端仓库执行 API Resolver（Step 0/1/2）。
Step 0: axios 锚点识别 LowLevelHelper（auto-discover）
Step 1: ApiWrapper 识别 + URL 提取（写入 codegraph_api_wrapper 表）
Step 2: volar references 反向追踪 ApiCallSite（写入 codegraph_api_call_site 表）
用法示例：
 python manage.py resolve_api_calls --repo <UUID>
 python manage.py resolve_api_calls --repo <UUID> --no-volar
 python manage.py resolve_api_calls --repo <UUID> --dry-run
per
"""
from __future__ import annotations
import uuid as _uuid
from collections import defaultdict
from pathlib import Path
import structlog
from django.core.management.base import BaseCommand, CommandError
logger = structlog.get_logger(__name__)
class Command(BaseCommand):
 help = "对前端仓库执行 API Resolver（Step 0/1/2），写入 ApiWrapper + ApiCallSite 表"
 def add_arguments(self, parser: "ArgumentParser") -> None: # type: ignore[name-defined]
 parser.add_argument(
 "--repo",
 required=True,
 help="仓库 ID（UUID）或本地路径",
 )
 parser.add_argument(
 "--no-volar",
 action="store_true",
 help="跳过 Step 2 volar references（只做 Step 0/1，写 ApiWrapper）",
 )
 parser.add_argument(
 "--dry-run",
 action="store_true",
 help="仅输出检测结果，不写入 DB",
 )
 parser.add_argument(
 "--max-files",
 type=int,
 default=0,
 help="限制扫描文件数（0 = 无限制，用于调试）",
 )
 def handle(self, *args: object, **options: object) -> None:
 repo_id_or_path: str = str(options["repo"])
 no_volar: bool = bool(options["no_volar"])
 dry_run: bool = bool(options["dry_run"])
 max_files: int = int(options.get("max_files", 0) or 0)
 # -------------------------------------------------------------------------
 # 获取仓库对象
 # -------------------------------------------------------------------------
 from repositories.models import Repository
 repo: Repository
 try:
 repo = Repository.objects.get(pk=_uuid.UUID(repo_id_or_path))
 except (ValueError, Repository.DoesNotExist):
 try:
 repo = Repository.objects.get(local_path=repo_id_or_path)
 except Repository.DoesNotExist:
 raise CommandError(f"找不到仓库：{repo_id_or_path}")
 repo_root: str = str(getattr(repo, "local_path", "") or repo_id_or_path)
 self.stdout.write(
 self.style.SUCCESS(f"\n▶ API Resolver — {repo.name} ({repo_root})\n")
 )
 # -------------------------------------------------------------------------
 # 收集 TS/Vue 文件列表
 # -------------------------------------------------------------------------
 file_paths = self._collect_ts_vue_files(repo_root)
 if max_files > 0:
 file_paths = file_paths[:max_files]
 self.stdout.write(f" 扫描文件数：{len(file_paths)} 个 TS/Vue 文件")
 if not file_paths:
 self.stdout.write(self.style.WARNING(" 未找到 TS/Vue 文件，退出"))
 return
 # -------------------------------------------------------------------------
 # Step 0/1: 识别 LowLevelHelper → ApiWrapper
 # -------------------------------------------------------------------------
 from codegraph.extractors.api_resolver.config import get_api_detector_config
 from codegraph.extractors.api_resolver.detector import (
 resolve_wrappers_for_repository,
 )
 config = get_api_detector_config(repo_root)
 wrappers = resolve_wrappers_for_repository(file_paths, repo_root, config)
 self.stdout.write(f" Step 0/1 完成：发现 {len(wrappers)} 个 ApiWrapper")
 if dry_run:
 self.stdout.write("\n [dry-run] ApiWrapper 预览（前 10 条）：")
 for w in wrappers[:10]:
 self.stdout.write(
 f" {w.http_method} {w.url_path_pattern} ← {w.function_symbol} "
 f"({Path(w.file_path).name})"
 )
 self.stdout.write("\n [dry-run] 不写入 DB，退出")
 return
 # -------------------------------------------------------------------------
 # 写入 ApiWrapper 表（per-file 分组）
 # -------------------------------------------------------------------------
 if wrappers:
 from codegraph.services.graph_writer import GraphWriter
 writer = GraphWriter
 by_file: dict[str, list] = defaultdict(list)
 for w in wrappers:
 by_file[w.file_path].append(w)
 total_written = 0
 for fp, file_wrappers in by_file.items:
 count = writer.write_api_wrappers_for_file(
 str(repo.id), fp, file_wrappers
 )
 total_written += count
 self.stdout.write(f" DB 写入：{total_written} 个 ApiWrapper")
 else:
 self.stdout.write(self.style.WARNING(" 未发现任何 ApiWrapper，检查 LowLevelHelper 识别"))
 # -------------------------------------------------------------------------
 # Step 2: volar references → ApiCallSite
 # -------------------------------------------------------------------------
 if no_volar:
 self.stdout.write(" 跳过 Step 2（--no-volar）")
 return
 self._run_step2(repo, wrappers, repo_root)
 def _collect_ts_vue_files(self, repo_root: str) -> list[str]:
 """收集仓库下所有 .ts/.tsx/.vue 文件（排除 node_modules / .git）。"""
 result: list[str] =
 root = Path(repo_root)
 for ext in ("*.ts", "*.tsx", "*.vue"):
 for fp in root.rglob(ext):
 if "node_modules" not in fp.parts and ".git" not in fp.parts:
 result.append(str(fp))
 return sorted(result)
 def _run_step2(
 self, repo: "Repository", wrappers: list, repo_root: str # type: ignore[name-defined]
 ) -> None:
 """Step 2：对每个 ApiWrapper 发 volar references 请求，写入 ApiCallSite。"""
 from codegraph.extractors.api_resolver.detector import (
 resolve_call_sites_for_wrapper,
 )
 from codegraph.lsp.volar_pool import get_volar_pool
 from codegraph.models import ApiWrapper as ApiWrapperModel
 from codegraph.services.graph_writer import GraphWriter
 pool = get_volar_pool
 writer = GraphWriter
 total_sites = 0
 failed_count = 0
 self.stdout.write(f"\n Step 2: 处理 {len(wrappers)} 个 ApiWrapper（volar references）")
 for wrapper_data in wrappers:
 try:
 sub_project_path = _find_sub_project_root(wrapper_data.file_path)
 supervisor = pool.get(sub_project_path)
 sites = resolve_call_sites_for_wrapper(wrapper_data, supervisor)
 if sites:
 db_wrapper = ApiWrapperModel.objects.filter(
 repository_id=repo.id,
 file_path=wrapper_data.file_path,
 function_symbol=wrapper_data.function_symbol,
 ).first
 if db_wrapper:
 count = writer.write_api_call_sites_for_wrapper(
 str(repo.id), str(db_wrapper.id), sites
 )
 total_sites += count
 except Exception as e:
 failed_count += 1
 logger.warning(
 "resolve_api_calls_step2_failed",
 wrapper=wrapper_data.function_symbol,
 file=wrapper_data.file_path,
 error=str(e),
 )
 self.stdout.write(
 f" Step 2 完成：{total_sites} 个 ApiCallSite，{failed_count} 个 wrapper volar 失败"
 )
 logger.info(
 "api_resolver_step2_command_complete",
 total_sites=total_sites,
 failed_wrappers=failed_count,
 repo=str(repo.id),
 )
def _find_sub_project_root(file_path: str) -> Path:
 """向上查找最近的 tsconfig.json 或 package.json，作为 volar sub_project_path。"""
 current = Path(file_path).parent
 for _ in range(10):
 if (current / "tsconfig.json").exists or (current / "package.json").exists:
 return current
 parent = current.parent
 if parent == current:
 break
 current = parent
 return Path(file_path).parent
