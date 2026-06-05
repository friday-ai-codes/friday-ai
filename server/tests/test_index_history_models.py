"""implementation: 索引历史数据模型测试。

验证 Repository 新字段和 IndexHistory 模型定义。
"""

import uuid

from django.db import models

from repositories.models import (
    IndexHistory,
    IndexHistoryStatus,
    Repository,
    TriggerType,
)


class TestTriggerTypeEnum:
    """TriggerType TextChoices 枚举定义。"""

    def test_manual_choice(self):
        assert TriggerType.MANUAL == "manual"

    def test_webhook_choice(self):
        assert TriggerType.WEBHOOK == "webhook"

    def test_scheduled_choice(self):
        assert TriggerType.SCHEDULED == "scheduled"

    def test_choices_count(self):
        assert len(TriggerType.choices) == 3


class TestIndexHistoryStatusEnum:
    """IndexHistoryStatus TextChoices 枚举定义。"""

    def test_pending_choice(self):
        assert IndexHistoryStatus.PENDING == "pending"

    def test_running_choice(self):
        assert IndexHistoryStatus.RUNNING == "running"

    def test_completed_choice(self):
        assert IndexHistoryStatus.COMPLETED == "completed"

    def test_failed_choice(self):
        assert IndexHistoryStatus.FAILED == "failed"

    def test_cancelled_choice(self):
        assert IndexHistoryStatus.CANCELLED == "cancelled"

    def test_choices_count(self):
        assert len(IndexHistoryStatus.choices) == 5


class TestRepositoryNewFields:
    """Repository 模型新增三个字段。"""

    def test_last_indexed_commit_sha_field(self):
        field = Repository._meta.get_field("last_indexed_commit_sha")
        assert field.max_length == 40
        assert field.null is True
        assert field.blank is True

    def test_auto_index_enabled_field(self):
        field = Repository._meta.get_field("auto_index_enabled")
        assert field.default is False

    def test_webhook_secret_field(self):
        field = Repository._meta.get_field("webhook_secret")
        assert field.max_length == 100
        assert field.null is True
        assert field.blank is True


class TestIndexHistoryModel:
    """IndexHistory 模型完整字段验证。"""

    def test_id_is_uuid_primary_key(self):
        field = IndexHistory._meta.get_field("id")
        assert field.primary_key is True
        assert field.default == uuid.uuid4
        assert field.editable is False

    def test_repository_fk(self):
        field = IndexHistory._meta.get_field("repository")
        assert field.remote_field.model is Repository
        assert field.remote_field.on_delete is models.CASCADE
        assert field.remote_field.related_name == "index_history"

    def test_trigger_type_field(self):
        field = IndexHistory._meta.get_field("trigger_type")
        assert field.max_length == 20
        assert field.choices == TriggerType.choices

    def test_status_field(self):
        field = IndexHistory._meta.get_field("status")
        assert field.max_length == 20
        assert field.choices == IndexHistoryStatus.choices
        assert field.default == IndexHistoryStatus.PENDING

    def test_from_sha_field(self):
        field = IndexHistory._meta.get_field("from_sha")
        assert field.max_length == 40
        assert field.null is True
        assert field.blank is True

    def test_to_sha_field(self):
        field = IndexHistory._meta.get_field("to_sha")
        assert field.max_length == 40
        assert field.null is True
        assert field.blank is True

    def test_files_added_field(self):
        field = IndexHistory._meta.get_field("files_added")
        assert field.default == 0

    def test_files_modified_field(self):
        field = IndexHistory._meta.get_field("files_modified")
        assert field.default == 0

    def test_files_deleted_field(self):
        field = IndexHistory._meta.get_field("files_deleted")
        assert field.default == 0

    def test_error_message_field(self):
        field = IndexHistory._meta.get_field("error_message")
        assert field.null is True
        assert field.blank is True

    def test_started_at_field(self):
        field = IndexHistory._meta.get_field("started_at")
        assert field.null is True
        assert field.blank is True

    def test_finished_at_field(self):
        field = IndexHistory._meta.get_field("finished_at")
        assert field.null is True
        assert field.blank is True

    def test_created_at_field(self):
        field = IndexHistory._meta.get_field("created_at")
        assert field.auto_now_add is True

    def test_meta_db_table(self):
        assert IndexHistory._meta.db_table == "index_history"

    def test_meta_ordering(self):
        assert IndexHistory._meta.ordering == ["-created_at"]
