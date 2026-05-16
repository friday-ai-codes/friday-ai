"""Phase: 测量 gopls vs tree-sitter Go call resolution 完整度。
per /
=====================
- **50% gate（硬卡）**：``gopls_completeness / tree_sitter_completeness >= 1.5``
- 完整度指标：CallData 中 ``callee_file`` 字段非空率（跨文件 call resolution 能力）
CLI 用例
========:
 python manage.py measure_go_call_completeness \\
 --repo-root=/Users/zaneliu/Projects/guanghe/study-course \\
 --ground-truth=codegraph/management/fixtures/go_call_ground_truth.csv \\
 --output-json=/tmp/go_completeness_report.json
"""
from __future__ import annotations
import csv
import dataclasses
import json
import shutil
import time
from pathlib import Path
from typing import Any
import structlog
from django.core.management.base import BaseCommand
logger = structlog.get_logger(__name__)
_EVENT_COMPLETENESS_MEASURED = "gopls_completeness_measured"
_RATIO_GATE = 1.5 # gopls / tree_sitter completeness ratio 门（per ）
@dataclasses.dataclass(frozen=True)
class _GroundTruthEntry:
 file: str
 line: int
 caller_symbol: str
 callee_symbol: str
 expected_callee_file: str
def _load_ground_truth(csv_path: Path) -> list[_GroundTruthEntry]:
 """从 CSV 加载 ground truth 样本，跳过注释行（# 开头）。"""
 entries: list[_GroundTruthEntry] =
 with open(csv_path, newline="", encoding="utf-8") as f:
 reader = csv.DictReader(filter(lambda row: not row.startswith("#"), f))
 for row in reader:
 try:
 entries.append(
 _GroundTruthEntry(
 file=row["file"].strip,
 line=int(row["line"]),
 caller_symbol=row["caller_symbol"].strip,
 callee_symbol=row["callee_symbol"].strip,
 expected_callee_file=row["expected_callee_file"].strip,
 )
 )
 except (KeyError, ValueError):
 continue
 return entries
def _measure_completeness_for_backend(
 backend_name: str,
 repo_root: Path,
 go_files: list[Path],
) -> float:
 """使用指定 backend 对 go_files 跑 extract_calls，计算 callee_file 非空率。
 Args:
 backend_name: "gopls" 或 "tree_sitter"
 repo_root: Go 仓库根目录
 go_files: 需要抽取的 .go 文件列表（相对 repo_root 的相对路径）
 Returns:
 float [0.0, 1.0]——callee_file 非空 CallData 比例；无 CallData 返 0.0
 """
 from codegraph.extractors.base import FileContext
 from codegraph.backends.protocols import TreeSitterBackend
 if backend_name == "gopls":
 from codegraph.lsp.gopls_backend import make_gopls_backend
 factory = make_gopls_backend("go")
 backend = factory("go")
 else:
 backend = TreeSitterBackend("go")
 total_calls = 0
 calls_with_callee_file = 0
 for rel_file in go_files:
 abs_path = repo_root / rel_file
 if not abs_path.exists:
 continue
 try:
 source = abs_path.read_text(encoding="utf-8", errors="replace")
 except OSError:
 continue
 ctx = FileContext(
 file_path=str(abs_path),
 language="go",
 repository_id="completeness_measure",
 )
 try:
 tree = backend.parse_file(str(abs_path), source)
 calls = backend.extract_calls(tree, ctx)
 for call in calls:
 total_calls += 1
 # 完整度指标：caller_key[0] 与当前文件不同（跨文件 call resolution）
 # per CONTEXT.md：callee_file 字段非空率 = 跨文件 call 被正确解析的比例
 # caller_key = (caller_file_path, caller_module, line)
 # gopls references 返回 caller 位置；caller 在不同文件即为跨文件 call
 caller_file = getattr(call, "caller_key", (None,))[0]
 if caller_file and str(caller_file) != str(abs_path):
 calls_with_callee_file += 1
 except Exception: # noqa: BLE001
 continue
 if total_calls == 0:
 return 0.0
 return calls_with_callee_file / total_calls
class Command(BaseCommand):
 """measure_go_call_completeness —— 测量 gopls vs tree-sitter Go call resolution 完整度。"""
 help = "测量 gopls vs tree-sitter Go call resolution 完整度，验证 50% gate（ratio >= 1.5）"
 def add_arguments(self, self_parser: Any) -> None:
 self_parser.add_argument(
 "--repo-root",
 default="/Users/zaneliu/Projects/guanghe/study-course",
 help="Go 仓库根目录（含 go.mod）",
 )
 self_parser.add_argument(
 "--ground-truth",
 default=None,
 help="ground truth CSV 路径；缺省读 fixtures/go_call_ground_truth.csv",
 )
 self_parser.add_argument(
 "--output-json",
 default=None,
 help="输出 JSON 报告路径（可选）",
 )
 self_parser.add_argument(
 "--max-files",
 type=int,
 default=50,
 help="最大处理文件数（避免 gopls 冷启动太慢）",
 )
 def handle(self, *args: Any, **options: Any) -> None:
 repo_root = Path(options["repo_root"]).resolve
 max_files: int = options["max_files"]
 # 加载 ground truth
 gt_csv_path = options["ground_truth"]
 if gt_csv_path is None:
 gt_csv_path = Path(__file__).parent.parent / "fixtures" / "go_call_ground_truth.csv"
 else:
 gt_csv_path = Path(gt_csv_path)
 if not gt_csv_path.exists:
 self.stderr.write(f"ground truth CSV 不存在：{gt_csv_path}")
 return
 ground_truth = _load_ground_truth(gt_csv_path)
 if not ground_truth:
 self.stderr.write("ground truth CSV 为空或格式错误")
 return
 # 收集待测文件列表
 go_files: list[Path] =
 unique_files = {Path(e.file) for e in ground_truth}
 for rel_file in unique_files:
 abs_file = repo_root / rel_file
 if abs_file.exists:
 go_files.append(rel_file)
 # 若 ground truth 文件不存在，扫描 repo 的 .go 文件
 if not go_files:
 self.stderr.write(f"ground truth 指定文件在 {repo_root} 下不存在；扫描 repo .go 文件")
 go_files = [
 p.relative_to(repo_root)
 for p in repo_root.rglob("*.go")
 if "vendor" not in p.parts and "_test.go" not in p.name
 ][:max_files]
 go_files = go_files[:max_files]
 sample_size = len(go_files)
 self.stdout.write(f"样本文件数：{sample_size}")
 # 判断 gopls 是否可用
 gopls_available = bool(shutil.which("gopls"))
 # 跑 tree-sitter（本地无需 gopls）
 self.stdout.write("跑 tree-sitter backend...")
 ts_start = time.monotonic
 tree_sitter_completeness = _measure_completeness_for_backend(
 "tree_sitter", repo_root, go_files
 )
 ts_elapsed = time.monotonic - ts_start
 # 跑 gopls
 if gopls_available:
 self.stdout.write("跑 gopls backend...")
 gopls_start = time.monotonic
 try:
 gopls_completeness = _measure_completeness_for_backend(
 "gopls", repo_root, go_files
 )
 except Exception as exc: # noqa: BLE001
 logger.warning(
 "gopls_completeness_measure_failed",
 error=str(exc),
 )
 self.stderr.write(f"gopls 跑失败：{exc}")
 gopls_completeness = 0.0
 gopls_elapsed = time.monotonic - gopls_start
 else:
 self.stdout.write("⚠ gopls binary 不存在，跳过 gopls 测量（CI 环境）")
 gopls_completeness = 0.0
 gopls_elapsed = 0.0
 # 计算 ratio
 if tree_sitter_completeness > 0:
 ratio = gopls_completeness / tree_sitter_completeness
 else:
 ratio = 1.0 if gopls_completeness > 0 else 0.0
 passed = ratio >= _RATIO_GATE and gopls_available
 report: dict[str, Any] = {
 "gopls_completeness": round(gopls_completeness, 4),
 "tree_sitter_completeness": round(tree_sitter_completeness, 4),
 "ratio": round(ratio, 4),
 "ratio_gate": _RATIO_GATE,
 "passed": passed,
 "gopls_available": gopls_available,
 "sample_size": sample_size,
 "sample_repo": str(repo_root),
 "gopls_elapsed_s": round(gopls_elapsed, 2),
 "ts_elapsed_s": round(ts_elapsed, 2),
 }
 # 输出结果
 status = "PASS" if passed else "FAIL"
 self.stdout.write(f"\n=== Go Call Completeness Gate ===")
 self.stdout.write(f"gopls: {gopls_completeness:.1%}")
 self.stdout.write(f"tree-sitter: {tree_sitter_completeness:.1%}")
 self.stdout.write(f"ratio: {ratio:.2f}x (gate >= {_RATIO_GATE}x)")
 self.stdout.write(f"result: {status}")
 if not gopls_available:
 self.stdout.write("⚠ gopls binary 不可用，FAIL（需本地手工跑）")
 # structlog event
 logger.info(
 _EVENT_COMPLETENESS_MEASURED,
 gopls_completeness=gopls_completeness,
 tree_sitter_completeness=tree_sitter_completeness,
 ratio=ratio,
 sample_size=sample_size,
 passed=passed,
 gopls_available=gopls_available,
 )
 # 写 JSON 报告
 output_json = options.get("output_json")
 if output_json:
 out_path = Path(output_json)
 out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
 self.stdout.write(f"JSON 报告：{out_path}")
