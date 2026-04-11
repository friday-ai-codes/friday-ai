"""post_save signal handler 测试（ Phase 仅打日志）。"""
from __future__ import annotations
from pathlib import Path
import pytest
import structlog
from prompts.models import Prompt, PromptCategory, PromptScope
@pytest.mark.django_db
class TestPromptSignals:
 def test_post_save_handler_fires_on_create(self, admin_user) -> None:
 with structlog.testing.capture_logs as captured:
 Prompt.objects.create(
 slug="signals.create",
 category=PromptCategory.AUX_MODEL,
 scope=PromptScope.SYSTEM,
 title="t",
 created_by=admin_user,
 )
 events = [
 e for e in captured if e.get("event") == "prompt_cache_invalidated"
 ]
 assert len(events) == 1
 assert events[0]["slug"] == "signals.create"
 assert events[0]["scope"] == "system"
 assert events[0]["created"] is True
 def test_post_save_handler_fires_on_update(self, admin_user) -> None:
 p = Prompt.objects.create(
 slug="signals.update",
 category=PromptCategory.AUX_MODEL,
 scope=PromptScope.SYSTEM,
 title="t1",
 created_by=admin_user,
 )
 with structlog.testing.capture_logs as captured:
 p.title = "t2"
 p.save
 events = [
 e for e in captured if e.get("event") == "prompt_cache_invalidated"
 ]
 assert len(events) == 1
 assert events[0]["created"] is False
 def test_post_save_handler_only_logs_no_cache_delete(self) -> None:
 """静态源码检查：signals.py 不含任何 cache 操作。"""
 signals_path = (
 Path(__file__).parent.parent / "prompts" / "signals.py"
 )
 content = signals_path.read_text(encoding="utf-8")
 assert "cache.delete" not in content
 assert "cache.set" not in content
 assert "from django.core.cache" not in content
