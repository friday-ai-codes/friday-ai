"""增量更新 —— 单方变更后只重 join 受影响的 url_pattern (work item)."""

from __future__ import annotations

import structlog
from django.db import transaction

from codegraph.cross_repo.confidence import compute_confidence
from codegraph.cross_repo.join_service import (
    BATCH_SIZE,
    _match_endpoint,
    build_endpoint_map,
)
from codegraph.cross_repo.path_normalizer import normalize_url_path
from codegraph.models import ApiWrapper, CrossRepoApiCall, Endpoint

logger = structlog.get_logger(__name__)


def update_for_wrapper(wrapper_id: str) -> int:
    """ApiWrapper 变更后，只重 join 该 wrapper 的所有 call_site。

    Args:
        wrapper_id: ApiWrapper.id UUID 字符串

    Returns:
        新写入的 CrossRepoApiCall 记录数
    """
    try:
        wrapper = ApiWrapper.objects.prefetch_related("call_sites").get(id=wrapper_id)
    except ApiWrapper.DoesNotExist:
        logger.warning("cross_repo_incremental_wrapper_not_found", wrapper_id=wrapper_id)
        return 0

    call_site_ids = list(wrapper.call_sites.values_list("id", flat=True))
    if not call_site_ids:
        return 0

    norm_path = normalize_url_path(wrapper.url_path_pattern)
    ep_map = build_endpoint_map()
    matches = _match_endpoint(norm_path, wrapper.http_method, ep_map)

    with transaction.atomic():
        # 删除旧记录（该 wrapper 的所有 call_site 的旧 cross_repo 记录）
        deleted_count, _ = CrossRepoApiCall.objects.filter(
            call_site_id__in=call_site_ids,
        ).delete()

        # 写入新记录
        new_records = [
            CrossRepoApiCall(
                call_site_id=cs_id,
                endpoint_id=ep_id,
                match_confidence=confidence,
            )
            for cs_id in call_site_ids
            for ep_id, confidence in matches
        ]
        if new_records:
            CrossRepoApiCall.objects.bulk_create(
                new_records, batch_size=BATCH_SIZE, ignore_conflicts=True
            )

    created_count = len(new_records)
    logger.info(
        "cross_repo_incremental_update",
        wrapper_id=wrapper_id,
        deleted=deleted_count,
        created=created_count,
    )
    return created_count


def update_for_endpoint(endpoint_id: str) -> int:
    """Endpoint 变更后，重新 join 所有与该 endpoint 路径匹配的 ApiWrapper。

    Args:
        endpoint_id: Endpoint.id UUID 字符串

    Returns:
        新写入的 CrossRepoApiCall 记录总数
    """
    try:
        endpoint = Endpoint.objects.get(id=endpoint_id)
    except Endpoint.DoesNotExist:
        logger.warning("cross_repo_incremental_endpoint_not_found", endpoint_id=endpoint_id)
        return 0

    # 找所有 normalized path 与该 endpoint 有正向匹配的 ApiWrapper
    matching_wrapper_ids: list[str] = []
    for wrapper in ApiWrapper.objects.only("id", "http_method", "url_path_pattern").iterator():
        confidence = compute_confidence(
            wrapper.http_method,
            wrapper.url_path_pattern,
            endpoint.http_method,
            endpoint.url_path,
        )
        if confidence > 0:
            matching_wrapper_ids.append(str(wrapper.id))

    total = 0
    for wid in matching_wrapper_ids:
        total += update_for_wrapper(wid)

    logger.info(
        "cross_repo_incremental_endpoint_update",
        endpoint_id=endpoint_id,
        affected_wrappers=len(matching_wrapper_ids),
        new_records=total,
    )
    return total
