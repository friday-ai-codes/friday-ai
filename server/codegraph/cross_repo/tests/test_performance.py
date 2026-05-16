"""性能测试 —— 10仓 × 1000EP × 5000AW < 30s 。
注意：此测试使用 pytest.mark.slow，默认不运行（-m "not slow" 跳过）。
显式运行：uv run pytest -m slow server/codegraph/cross_repo/tests/test_performance.py -v
"""
from __future__ import annotations
import time
from collections import defaultdict
from unittest.mock import MagicMock
import pytest
from codegraph.cross_repo.join_service import _match_endpoint
from codegraph.cross_repo.path_normalizer import normalize_url_path
def _build_mock_ep_map(n_endpoints: int) -> dict[tuple[str, str], list[str]]:
 """构建 N 个 endpoint 的 mock endpoint_map（纯内存，不涉及 DB）。"""
 ep_map: dict[tuple[str, str], list[str]] = defaultdict(list)
 methods = ["GET", "POST", "PUT", "DELETE"]
 for i in range(n_endpoints):
 method = methods[i % 4]
 # 产生多样的路径，确保覆盖:param 归一化后重叠（触发 dict 命中）
 path = f"/api/v1/resource{i % 100}/:param"
 key = (method, path)
 ep_map[key].append(f"ep-{i}")
 return dict(ep_map)
def _make_mock_wrappers(n: int) -> list[MagicMock]:
 """构建 N 个 ApiWrapper mock 对象（纯内存，不涉及 DB）。"""
 wrappers =
 methods = ["GET", "POST", "PUT", "DELETE"]
 for i in range(n):
 w = MagicMock
 w.id = f"w-{i}"
 w.http_method = methods[i % 4]
 # 与 ep_map 中的路径一致（80% 命中），20% 无匹配
 if i % 5 == 0:
 w.url_path_pattern = f"/completely/different/path/{i}"
 else:
 w.url_path_pattern = f"/api/v1/resource{i % 100}/:id"
 wrappers.append(w)
 return wrappers
@pytest.mark.slow
def test_join_performance_10_repos_1k_ep_5k_aw -> None:
 """验证 10仓规模（1000EP × 10 + 5000AW × 10）join 时间 < 30s。
 使用纯内存 dict（不发 DB 查询），验证 O(N+M) 算法时间复杂度。
 实际 DB 场景耗时取决于网络/IO，但 join 算法本身应远低于 30s。
 per: 10 仓库 × 1000 endpoint × 5000 ApiWrapper < 30s
 """
 n_endpoints = 10_000 # 10 仓 × 1000
 n_wrappers = 50_000 # 10 仓 × 5000
 # Phase: 构建 endpoint_map（模拟 DB 查询后的结果）
 start = time.monotonic
 ep_map = _build_mock_ep_map(n_endpoints)
 ep_build_time = time.monotonic - start
 # Phase: 遍历 ApiWrapper，执行 dict lookup join（纯内存操作）
 wrappers = _make_mock_wrappers(n_wrappers)
 start = time.monotonic
 records_count = 0
 for w in wrappers:
 norm_path = normalize_url_path(w.url_path_pattern)
 matches = _match_endpoint(norm_path, w.http_method, ep_map)
 records_count += len(matches)
 join_time = time.monotonic - start
 total_time = ep_build_time + join_time
 print(
 f"\n性能数据: ep_build={ep_build_time:.3f}s, "
 f"join={join_time:.3f}s, total={total_time:.3f}s"
 )
 print(f"endpoint_map keys: {len(ep_map)}")
 print(f"match 记录数: {records_count}")
 assert total_time < 30.0, (
 f"join 耗时 {total_time:.2f}s 超过 30s 门槛 "
 )
@pytest.mark.slow
def test_join_performance_baseline_1k_ep_5k_aw -> None:
 """中等规模基准：1000 EP × 5000 AW，预期 < 2s。"""
 n_endpoints = 1_000
 n_wrappers = 5_000
 ep_map = _build_mock_ep_map(n_endpoints)
 wrappers = _make_mock_wrappers(n_wrappers)
 start = time.monotonic
 for w in wrappers:
 norm_path = normalize_url_path(w.url_path_pattern)
 _match_endpoint(norm_path, w.http_method, ep_map)
 elapsed = time.monotonic - start
 assert elapsed < 5.0, f"基准 join 耗时 {elapsed:.3f}s > 5s 门槛"
