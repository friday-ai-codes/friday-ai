"""recency 时间衰减纯函数测试（Phase 15-01）。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from django.utils import timezone

from knowledge.recency import compute_recency_score, fuse_vector_recency, normalize_vector_scores

pytestmark = pytest.mark.django_db


def test_recency_same_day_is_one():
    """event_time=reference_time → recency=1.0。"""
    now = timezone.now()
    assert compute_recency_score(now, reference_time=now) == pytest.approx(1.0)


def test_recency_half_life_90_days():
    """age=90d, half_life=90 → recency≈0.5。"""
    ref = timezone.now()
    event = ref - timedelta(days=90)
    score = compute_recency_score(event, reference_time=ref, half_life_days=90)
    assert score == pytest.approx(0.5, rel=1e-3)


def test_fuse_vector_recency():
    """fuse(0.8, 1.0, 0.7, 0.3)=0.86。"""
    assert fuse_vector_recency(0.8, 1.0, alpha=0.7, beta=0.3) == pytest.approx(0.86)


def test_naive_datetime_rejected():
    """naive datetime → ValueError。"""
    naive = datetime(2026, 1, 1, 12, 0, 0)
    aware = timezone.now()
    with pytest.raises(ValueError, match="aware"):
        compute_recency_score(naive, reference_time=aware)
    with pytest.raises(ValueError, match="aware"):
        compute_recency_score(aware, reference_time=naive)


def test_normalize_single_element():
    """normalize 单元素 → [1.0]。"""
    assert normalize_vector_scores([0.42]) == [1.0]
