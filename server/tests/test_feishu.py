"""Tests for Feishu TriggerLog API endpoints and ProcessedEvent idempotency."""

import json

import pytest
from django.db import IntegrityError

from feishu.models import ProcessedEvent, TriggerLog, TriggerLogStatus

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def trigger_log(db, project):
    """创建测试触发日志。"""
    return TriggerLog.objects.create(
        space=project,
        project_key=project.feishu_project_key,
        event_uuid="test-event-uuid-001",
        event_type="WorkitemCreateEvent",
        webhook_raw_request=json.dumps(
            {
                "header": {"uuid": "test-event-uuid-001", "event_type": "WorkitemCreateEvent"},
                "payload": {"id": "12345", "name": "Test Work Item"},
            }
        ),
        work_item_id="12345",
        work_item_type="story",
        work_item_name="Test Work Item",
        work_item_raw_response=json.dumps(
            {"data": [{"id": 12345, "name": "Test Work Item", "fields": []}]}
        ),
        prd_url="https://example.com/prd",
        description="This is a test description",
        tech_doc_url="https://example.com/tech-doc",
        status=TriggerLogStatus.ACCEPTED,
    )


@pytest.fixture
def trigger_log_with_error(db, project):
    """创建带错误信息的触发日志。"""
    return TriggerLog.objects.create(
        space=project,
        project_key=project.feishu_project_key,
        event_uuid="test-event-uuid-error",
        event_type="WorkitemStatusEvent",
        webhook_raw_request=json.dumps({"header": {}, "payload": {}}),
        status=TriggerLogStatus.ERROR,
        error_message="Token 验证失败",
    )


@pytest.fixture
def feishu_urls():
    """Feishu 相关 URL。"""

    class FeishuURLs:
        logs_list = "/api/feishu/logs/"

        @staticmethod
        def logs_detail(log_id):
            return f"/api/feishu/logs/{log_id}/"

        @staticmethod
        def logs_raw(log_id):
            return f"/api/feishu/logs/{log_id}/raw/"

    return FeishuURLs()


# ============================================================================
# TriggerLog List Tests
# ============================================================================


@pytest.mark.django_db
class TestTriggerLogList:
    """测试触发日志列表 API。"""

    def test_list_trigger_logs_success(self, authenticated_client, trigger_log, feishu_urls):
        """测试获取触发日志列表成功。"""
        response = authenticated_client.get(feishu_urls.logs_list)

        assert response.status_code == 200
        data = response.json()
        # API now returns {"items": [...], "total": N}
        assert "items" in data
        assert "total" in data
        items = data["items"]
        assert isinstance(items, list)
        assert len(items) >= 1

        # 验证返回的日志包含必要字段
        log_data = next((log for log in items if log["id"] == str(trigger_log.id)), None)
        assert log_data is not None
        assert log_data["event_type"] == "WorkitemCreateEvent"
        assert log_data["status"] == "accepted"
        assert log_data["work_item_id"] == "12345"

    def test_list_trigger_logs_filter_by_project(
        self, authenticated_client, trigger_log, project, feishu_urls
    ):
        """测试按项目筛选日志。"""
        response = authenticated_client.get(feishu_urls.logs_list, {"project_id": str(project.id)})

        assert response.status_code == 200
        data = response.json()
        items = data["items"]
        assert all(
            log.get("project_id") == str(project.id) for log in items if log.get("project_id")
        )

    def test_list_trigger_logs_filter_by_status(
        self, authenticated_client, trigger_log, trigger_log_with_error, feishu_urls
    ):
        """测试按状态筛选日志。"""
        response = authenticated_client.get(feishu_urls.logs_list, {"status": "error"})

        assert response.status_code == 200
        data = response.json()
        items = data["items"]
        assert all(log["status"] == "error" for log in items)

    def test_list_trigger_logs_filter_by_event_type(
        self, authenticated_client, trigger_log, feishu_urls
    ):
        """测试按事件类型筛选日志。"""
        response = authenticated_client.get(
            feishu_urls.logs_list, {"event_type": "WorkitemCreateEvent"}
        )

        assert response.status_code == 200
        data = response.json()
        items = data["items"]
        assert all(log["event_type"] == "WorkitemCreateEvent" for log in items)

    def test_list_trigger_logs_pagination(self, authenticated_client, project, feishu_urls):
        """测试日志列表分页。"""
        # 创建多条日志
        for i in range(5):
            TriggerLog.objects.create(
                space=project,
                event_uuid=f"pagination-test-{i}",
                event_type="WorkitemCreateEvent",
                status=TriggerLogStatus.ACCEPTED,
            )

        response = authenticated_client.get(feishu_urls.logs_list, {"limit": 2, "offset": 0})

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_list_trigger_logs_unauthenticated(self, api_client, feishu_urls):
        """测试未认证用户访问日志列表。"""
        response = api_client.get(feishu_urls.logs_list)
        # 根据项目配置，可能返回 401 或 403
        assert response.status_code in [401, 403]


# ============================================================================
# TriggerLog Detail Tests
# ============================================================================


@pytest.mark.django_db
class TestTriggerLogDetail:
    """测试触发日志详情 API。"""

    def test_get_trigger_log_detail_success(self, authenticated_client, trigger_log, feishu_urls):
        """测试获取日志详情成功。"""
        response = authenticated_client.get(feishu_urls.logs_detail(trigger_log.id))

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(trigger_log.id)
        assert data["event_type"] == "WorkitemCreateEvent"
        assert data["event_uuid"] == "test-event-uuid-001"
        assert data["work_item_id"] == "12345"
        assert data["work_item_name"] == "Test Work Item"
        assert data["prd_url"] == "https://example.com/prd"
        assert data["description"] == "This is a test description"
        assert data["tech_doc_url"] == "https://example.com/tech-doc"
        assert data["status"] == "accepted"

    def test_get_trigger_log_detail_with_error(
        self, authenticated_client, trigger_log_with_error, feishu_urls
    ):
        """测试获取带错误信息的日志详情。"""
        response = authenticated_client.get(feishu_urls.logs_detail(trigger_log_with_error.id))

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
        assert data["error_message"] == "Token 验证失败"

    def test_get_trigger_log_detail_not_found(self, authenticated_client, feishu_urls):
        """测试获取不存在的日志详情。"""
        response = authenticated_client.get(
            feishu_urls.logs_detail("00000000-0000-0000-0000-000000000000")
        )

        assert response.status_code == 404


# ============================================================================
# TriggerLog Raw Data Tests
# ============================================================================


@pytest.mark.django_db
class TestTriggerLogRaw:
    """测试触发日志原始数据 API。"""

    def test_get_trigger_log_raw_success(self, authenticated_client, trigger_log, feishu_urls):
        """测试获取日志原始数据成功。"""
        response = authenticated_client.get(feishu_urls.logs_raw(trigger_log.id))

        assert response.status_code == 200
        data = response.json()

        # 验证 webhook_request
        assert "webhook_request" in data
        assert data["webhook_request"]["header"]["uuid"] == "test-event-uuid-001"

        # 验证 work_item_response
        assert "work_item_response" in data
        assert data["work_item_response"]["data"][0]["id"] == 12345

    def test_get_trigger_log_raw_empty_data(self, authenticated_client, project, feishu_urls):
        """测试获取空原始数据的日志。"""
        empty_log = TriggerLog.objects.create(
            space=project,
            event_type="TestEvent",
            status=TriggerLogStatus.IGNORED,
        )

        response = authenticated_client.get(feishu_urls.logs_raw(empty_log.id))

        assert response.status_code == 200
        data = response.json()
        assert data["webhook_request"] == {}
        assert data["work_item_response"] == {}

    def test_get_trigger_log_raw_not_found(self, authenticated_client, feishu_urls):
        """测试获取不存在日志的原始数据。"""
        response = authenticated_client.get(
            feishu_urls.logs_raw("00000000-0000-0000-0000-000000000000")
        )

        assert response.status_code == 404


# ============================================================================
# TriggerLog Model Tests
# ============================================================================


@pytest.mark.django_db
class TestTriggerLogModel:
    """测试 TriggerLog 模型。"""

    def test_create_trigger_log(self, db, project):
        """测试创建触发日志。"""
        log = TriggerLog.objects.create(
            space=project,
            event_uuid="model-test-uuid",
            event_type="WorkitemCreateEvent",
            work_item_id="99999",
            status=TriggerLogStatus.ACCEPTED,
        )

        assert log.id is not None
        assert log.event_uuid == "model-test-uuid"
        assert log.space == project
        assert log.created_at is not None

    def test_trigger_log_str_representation(self, trigger_log):
        """测试日志的字符串表示。"""
        str_repr = str(trigger_log)
        assert "WorkitemCreateEvent" in str_repr
        assert "Test Work Item" in str_repr

    def test_trigger_log_ordering(self, db, project):
        """测试日志按创建时间倒序排列。"""
        log1 = TriggerLog.objects.create(
            space=project,
            event_uuid="order-test-1",
            event_type="Event1",
            status=TriggerLogStatus.ACCEPTED,
        )
        log2 = TriggerLog.objects.create(
            space=project,
            event_uuid="order-test-2",
            event_type="Event2",
            status=TriggerLogStatus.ACCEPTED,
        )

        logs = list(TriggerLog.objects.filter(event_uuid__startswith="order-test"))
        # 最新的在前
        assert logs[0].id == log2.id
        assert logs[1].id == log1.id

    def test_trigger_log_unique_event_uuid(self, db, project):
        """测试 event_uuid 唯一性约束。"""
        TriggerLog.objects.create(
            space=project,
            event_uuid="unique-uuid-test",
            event_type="Event1",
            status=TriggerLogStatus.ACCEPTED,
        )

        with pytest.raises(Exception):  # IntegrityError
            TriggerLog.objects.create(
                space=project,
                event_uuid="unique-uuid-test",
                event_type="Event2",
                status=TriggerLogStatus.ACCEPTED,
            )


# ============================================================================
# ProcessedEvent Model Tests
# ============================================================================


@pytest.mark.django_db
class TestProcessedEvent:
    """测试 ProcessedEvent 幂等去重模型。"""

    def test_create_processed_event(self, db):
        """测试创建已处理事件记录。"""
        event = ProcessedEvent.objects.create(event_id="test-event-001")

        assert event.event_id == "test-event-001"
        assert event.created_at is not None

    def test_processed_event_unique_constraint(self, db):
        """测试 event_id 唯一约束：重复插入应抛出 IntegrityError。"""
        ProcessedEvent.objects.create(event_id="duplicate-event")

        with pytest.raises(IntegrityError):
            ProcessedEvent.objects.create(event_id="duplicate-event")

    def test_processed_event_exists_check(self, db):
        """测试通过 exists 查询检查事件是否已处理。"""
        assert not ProcessedEvent.objects.filter(event_id="new-event").exists()

        ProcessedEvent.objects.create(event_id="new-event")

        assert ProcessedEvent.objects.filter(event_id="new-event").exists()

    def test_processed_event_str_representation(self, db):
        """测试字符串表示。"""
        event = ProcessedEvent.objects.create(event_id="str-test-event")
        assert str(event) == "str-test-event"

    def test_multiple_events_independent(self, db):
        """测试多个不同事件互不影响。"""
        ProcessedEvent.objects.create(event_id="event-a")
        ProcessedEvent.objects.create(event_id="event-b")
        ProcessedEvent.objects.create(event_id="event-c")

        assert ProcessedEvent.objects.count() == 3
        assert ProcessedEvent.objects.filter(event_id="event-b").exists()
