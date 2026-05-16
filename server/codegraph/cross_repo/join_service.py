"""跨仓 offline join 服务 —— ApiWrapper × Endpoint 按 (method, path) join。
算法复杂度：O(N+M)，双 dict 避免 O(N×M) 全量 DB join。
per,,
"""
from __future__ import annotations
from collections import defaultdict
from typing import TYPE_CHECKING
import structlog
from django.db import transaction
from codegraph.cross_repo.path_normalizer import normalize_url_path
from codegraph.models import ApiWrapper, CrossRepoApiCall, Endpoint
if TYPE_CHECKING:
 from django.db.models import QuerySet
logger = structlog.get_logger(__name__)
#: bulk_create 批次大小
BATCH_SIZE = 500
def build_endpoint_map(
 endpoints: "QuerySet[Endpoint] | None" = None,
) -> dict[tuple[str, str], list[str]]:
 """构建 endpoint_map：(method_upper, norm_path) → [endpoint_id, ...]。
 Args:
 endpoints: 可选的 Endpoint queryset，默认取全量
 Returns:
 双 key tuple → endpoint_id 列表的 dict
 """
 if endpoints is None:
 endpoints = Endpoint.objects.all
 ep_map: dict[tuple[str, str], list[str]] = defaultdict(list)
 for ep in endpoints.only("id", "http_method", "url_path").iterator(chunk_size=1000):
 norm_path = normalize_url_path(ep.url_path)
 key = (ep.http_method.upper, norm_path)
 ep_map[key].append(str(ep.id))
 logger.info(
 "endpoint_map_built",
 endpoint_count=sum(len(v) for v in ep_map.values),
 key_count=len(ep_map),
 )
 return ep_map
def _match_endpoint(
 norm_path: str,
 http_method: str,
 ep_map: dict[tuple[str, str], list[str]],
) -> list[tuple[str, float]]:
 """在 endpoint_map 中查找匹配的 endpoint_id + confidence。
 Returns:
 list of (endpoint_id, confidence) tuples，confidence >= MIN_CONFIDENCE
 """
 results: list[tuple[str, float]] =
 method = http_method.upper
 # 完全匹配 (1.0)：method + path 均一致
 full_key = (method, norm_path)
 if full_key in ep_map:
 for ep_id in ep_map[full_key]:
 results.append((ep_id, 1.0))
 return results
 # path-only 匹配 (0.7)：path 一致，method 不同
 for (ep_method, ep_path), ep_ids in ep_map.items:
 if ep_path == norm_path and ep_method != method:
 for ep_id in ep_ids:
 results.append((ep_id, 0.7))
 if results:
 return results
 # 前缀匹配 (0.4)：path 前缀 ≥ 2 segments 相同
 w_segs = [s for s in norm_path.split("/") if s]
 if len(w_segs) >= 2:
 prefix_2 = tuple(w_segs[:2])
 for (ep_method, ep_path), ep_ids in ep_map.items:
 e_segs = [s for s in ep_path.split("/") if s]
 if len(e_segs) >= 2 and tuple(e_segs[:2]) == prefix_2:
 for ep_id in ep_ids:
 results.append((ep_id, 0.4))
 if results:
 return results
 return results
def build_cross_repo_matches(
 ep_map: dict[tuple[str, str], list[str]],
 wrappers: "QuerySet[ApiWrapper] | None" = None,
) -> list[CrossRepoApiCall]:
 """构建 CrossRepoApiCall 记录列表（未写入 DB）。
 Args:
 ep_map: build_endpoint_map 返回的 dict
 wrappers: 可选的 ApiWrapper queryset，默认全量
 Returns:
 未保存的 CrossRepoApiCall 对象列表
 """
 if wrappers is None:
 wrappers = ApiWrapper.objects.all
 records: list[CrossRepoApiCall] =
 wrapper_count = 0
 for wrapper in (
 wrappers
 .prefetch_related("call_sites")
 .only("id", "http_method", "url_path_pattern")
 .iterator(chunk_size=500)
 ):
 wrapper_count += 1
 norm_path = normalize_url_path(wrapper.url_path_pattern)
 matches = _match_endpoint(norm_path, wrapper.http_method, ep_map)
 for call_site in wrapper.call_sites.only("id").all:
 for ep_id, confidence in matches:
 records.append(
 CrossRepoApiCall(
 call_site_id=call_site.id,
 endpoint_id=ep_id,
 match_confidence=confidence,
 )
 )
 logger.info(
 "cross_repo_matches_built",
 wrapper_count=wrapper_count,
 match_count=len(records),
 )
 return records
def write_cross_repo_matches(records: list[CrossRepoApiCall]) -> int:
 """批量写入 CrossRepoApiCall 记录，幂等（ignore_conflicts=True）。
 Returns:
 写入记录数（bulk_create 返回值，忽略冲突的不计入）
 """
 if not records:
 return 0
 total = 0
 for i in range(0, len(records), BATCH_SIZE):
 batch = records[i: i + BATCH_SIZE]
 with transaction.atomic:
 created = CrossRepoApiCall.objects.bulk_create(
 batch, batch_size=BATCH_SIZE, ignore_conflicts=True
 )
 total += len(created)
 logger.info("cross_repo_matches_written", total=total)
 return total
def rebuild_all(
 wrappers_qs: "QuerySet[ApiWrapper] | None" = None,
 endpoints_qs: "QuerySet[Endpoint] | None" = None,
) -> int:
 """全量重建：清空 CrossRepoApiCall 表，重新 join 写入。
 Returns:
 写入记录数
 """
 logger.info("cross_repo_join_started", mode="full_rebuild")
 CrossRepoApiCall.objects.all.delete
 ep_map = build_endpoint_map(endpoints_qs)
 records = build_cross_repo_matches(ep_map, wrappers_qs)
 count = write_cross_repo_matches(records)
 logger.info("cross_repo_join_completed", match_count=count)
 return count
