"""Tests for AlertRule models, hooks, and API."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from django.utils import timezone

from workflows.hooks.builtin import AlertRuleHook
from workflows.models import AlertRule, AlertRuleExecution, WorkflowExecution


@pytest.fixture
def failed_execution(obs_workflow, user):
    """创建失败状态的工作流执行。"""
    now = timezone.now()
    return WorkflowExecution.objects.create(
        workflow=obs_workflow,
        space=obs_workflow.space,
        trigger_type="manual",
        triggered_by=user,
        status="failed",
        started_at=now - timedelta(seconds=300),
        completed_at=now,
    )


@pytest.mark.django_db(transaction=True)
class TestAlertRuleModel:
    def test_create_workflow_rule(self, obs_project, obs_workflow):
        rule = AlertRule.objects.create(
            workflow=obs_workflow,
            space=obs_project,
            name="执行失败告警",
            condition_type="execution_failed",
            action_type="feishu_notification",
            action_config={"chat_id": "oc_xxx"},
        )
        assert rule.name == "执行失败告警"
        assert rule.enabled is True
        assert rule.cooldown_seconds == 0
        assert str(rule) == "执行失败告警 (execution_failed)"

    def test_create_global_rule(self, obs_project):
        rule = AlertRule.objects.create(
            workflow=None,
            space=obs_project,
            name="全局成本告警",
            condition_type="cost_threshold",
            condition_config={"threshold_value": "10.00"},
            action_type="webhook",
            action_config={"url": "https://example.com/hook"},
        )
        assert rule.workflow is None
        assert rule.condition_config["threshold_value"] == "10.00"


@pytest.mark.django_db(transaction=True)
class TestAlertRuleExecutionModel:
    def test_unique_constraint(self, obs_project, obs_workflow, obs_execution):
        rule = AlertRule.objects.create(
            workflow=obs_workflow,
            space=obs_project,
            name="Test",
            condition_type="execution_failed",
            action_type="webhook",
            action_config={"url": "https://example.com/hook"},
        )
        AlertRuleExecution.objects.create(
            alert_rule=rule,
            workflow_execution=obs_execution,
            status="delivered",
        )
        with pytest.raises(Exception):  # IntegrityError
            AlertRuleExecution.objects.create(
                alert_rule=rule,
                workflow_execution=obs_execution,
                status="triggered",
            )


@pytest.mark.django_db(transaction=True)
class TestAlertRuleHook:
    @pytest.mark.asyncio
    async def test_execution_failed_triggers_rule(self, obs_project, obs_workflow, failed_execution):
        rule = await AlertRule.objects.acreate(
            workflow=obs_workflow,
            space=obs_project,
            name="Failed Alert",
            condition_type="execution_failed",
            action_type="webhook",
            action_config={"url": "https://example.com/hook"},
        )
        hook = AlertRuleHook()
        with patch.object(hook, "_execute_action", new_callable=AsyncMock) as mock_exec:
            await hook.execute("execution_failed", execution=failed_execution)
            import asyncio
            await asyncio.sleep(0.3)
            mock_exec.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_debug_execution_skipped(self, obs_project, obs_workflow, failed_execution):
        failed_execution.is_debug = True
        await failed_execution.asave(update_fields=["is_debug"])
        rule = await AlertRule.objects.acreate(
            workflow=obs_workflow,
            space=obs_project,
            name="Debug Skip",
            condition_type="execution_failed",
            action_type="webhook",
            action_config={"url": "https://example.com/hook"},
        )
        hook = AlertRuleHook()
        with patch.object(hook, "_execute_action", new_callable=AsyncMock) as mock_exec:
            await hook.execute("execution_failed", execution=failed_execution)
            import asyncio
            await asyncio.sleep(0.3)
            mock_exec.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cooldown_prevents_duplicate(self, obs_project, obs_workflow, failed_execution):
        rule = await AlertRule.objects.acreate(
            workflow=obs_workflow,
            space=obs_project,
            name="Cooldown Test",
            condition_type="execution_failed",
            action_type="webhook",
            action_config={"url": "https://example.com/hook"},
            cooldown_seconds=300,
        )
        hook = AlertRuleHook()
        # 直接调用 _execute_action 创建记录，模拟第一次触发完成
        await hook._execute_action(rule, failed_execution, "execution_failed")

        # 第二次触发应该被 cooldown 阻止
        with patch.object(hook, "_send_webhook", new_callable=AsyncMock) as mock_send:
            await hook.execute("execution_failed", execution=failed_execution)
            mock_send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cost_threshold_evaluation(self, obs_project, obs_workflow, obs_execution, obs_token_usages):
        """测试成本阈值评估 — 直接测试 _evaluate_condition 和 _execute_action。"""
        rule = await AlertRule.objects.acreate(
            workflow=obs_workflow,
            space=obs_project,
            name="Cost Alert",
            condition_type="cost_threshold",
            condition_config={"threshold_value": "0.01"},
            action_type="webhook",
            action_config={"url": "https://example.com/hook"},
        )
        hook = AlertRuleHook()

        # 直接验证条件评估结果
        result = await hook._evaluate_condition(rule, obs_execution)
        assert result is True, "成本阈值应被触发（总成本 0.06 > 阈值 0.01）"

        # 直接测试 _execute_action（不经过 asyncio.create_task）
        with patch.object(hook, "_send_webhook", new_callable=AsyncMock) as mock_send:
            await hook._execute_action(rule, obs_execution, "execution_completed")
            mock_send.assert_awaited_once()

    def test_is_internal_host_blocks_private_ip(self):
        assert AlertRuleHook._is_internal_host("127.0.0.1") is True
        assert AlertRuleHook._is_internal_host("192.168.1.1") is True
        assert AlertRuleHook._is_internal_host("10.0.0.1") is True
        assert AlertRuleHook._is_internal_host("localhost") is True
        assert AlertRuleHook._is_internal_host("example.com") is False


@pytest.mark.django_db(transaction=True)
class TestAlertRuleAPI:
    def test_list_alert_rules(self, authenticated_client, obs_project, obs_workflow):
        from permissions.models import SpaceMembership, SpaceRole
        SpaceMembership.objects.create(
            user=authenticated_client.handler._force_user,
            space=obs_project,
            role=SpaceRole.VIEWER,
        )
        AlertRule.objects.create(
            workflow=obs_workflow,
            space=obs_project,
            name="API Test Rule",
            condition_type="execution_failed",
            action_type="webhook",
            action_config={"url": "https://example.com/hook"},
        )
        resp = authenticated_client.get("/api/alert-rules/")
        assert resp.status_code == 200
        data = resp.json()
        assert any(r["name"] == "API Test Rule" for r in data)

    def test_create_alert_rule_validation(self, authenticated_client, obs_project, obs_workflow):
        from permissions.models import SpaceMembership, SpaceRole
        SpaceMembership.objects.create(
            user=authenticated_client.handler._force_user,
            space=obs_project,
            role=SpaceRole.MEMBER,
        )
        payload = {
            "workflow": str(obs_workflow.id),
            "project": str(obs_project.id),
            "name": "Invalid",
            "condition_type": "execution_failed",
            "action_type": "webhook",
            "action_config": {},  # missing url
        }
        resp = authenticated_client.post("/api/alert-rules/", payload, content_type="application/json")
        assert resp.status_code == 400

    def test_toggle_enabled_endpoint(self, authenticated_client, obs_project, obs_workflow):
        from permissions.models import SpaceMembership, SpaceRole
        SpaceMembership.objects.create(
            user=authenticated_client.handler._force_user,
            space=obs_project,
            role=SpaceRole.MEMBER,
        )
        rule = AlertRule.objects.create(
            workflow=obs_workflow,
            space=obs_project,
            name="Toggle Test",
            condition_type="execution_failed",
            action_type="webhook",
            action_config={"url": "https://example.com/hook"},
        )
        resp = authenticated_client.post(f"/api/alert-rules/{rule.id}/toggle_enabled/")
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False
