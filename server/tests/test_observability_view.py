"""超管可观测聚合端点测试（OBS-01）。

验证：
- 非超管 fail-closed（403）；
- 超管拿到完整聚合结构（队列/subagent/仓库/编排/runner 负载）；
- 数据真实反映（仓库状态计数、subagent 活跃项）。
"""

import pytest

OBSERVABILITY_URL = "/api/system/observability/"


@pytest.mark.django_db
class TestObservabilityView:
    def test_non_superuser_forbidden(self, api_client, user):
        """普通用户访问 → 403（IsSuperUser fail-closed）。"""
        api_client.force_authenticate(user=user)
        resp = api_client.get(OBSERVABILITY_URL)
        assert resp.status_code == 403

    def test_anonymous_forbidden(self, api_client):
        """未认证 → 401/403。"""
        resp = api_client.get(OBSERVABILITY_URL)
        assert resp.status_code in (401, 403)

    def test_superuser_payload_shape(self, api_client, admin_user):
        api_client.force_authenticate(user=admin_user)
        resp = api_client.get(OBSERVABILITY_URL)
        assert resp.status_code == 200
        data = resp.json()
        for key in (
            "generated_at",
            "durable_queues",
            "subagent",
            "repositories",
            "orchestration",
            "runners",
            "runtime",
            "background_tasks",
            "alerts",
        ):
            assert key in data, f"缺少顶层字段 {key}"
        assert "by_queue_status" in data["durable_queues"]
        assert "totals" in data["durable_queues"]
        assert "by_type_status" in data["subagent"]
        assert "active" in data["subagent"]
        assert "index_status" in data["repositories"]
        assert isinstance(data["runners"], list)
        # 运行时：协程数（可能为 None）+ 线程数
        assert "asyncio_tasks" in data["runtime"]
        assert "threads" in data["runtime"]
        assert isinstance(data["runtime"]["threads"], int)
        # 后台任务汇总
        assert "total_active" in data["background_tasks"]
        # 告警事件
        assert "recent" in data["alerts"]
        assert "counts" in data["alerts"]
        assert isinstance(data["alerts"]["recent"], list)

    def test_reflects_repository_and_subagent_data(
        self, api_client, admin_user, repository
    ):
        from agents.models import AgentSession
        from subagent.models import SubAgentSession

        agent_session = AgentSession.objects.create(
            user=admin_user, session_id="obs-main-session"
        )
        SubAgentSession.objects.create(
            session_id="obs-sub-pending",
            main_session=agent_session,
            repo_url=repository.git_url,
            task_type=SubAgentSession.TaskType.REPO_SUMMARY,
            status=SubAgentSession.Status.PENDING,
            last_output={"repository_id": str(repository.pk)},
        )

        api_client.force_authenticate(user=admin_user)
        data = api_client.get(OBSERVABILITY_URL).json()

        # 仓库计数包含 fixture 仓库
        assert data["repositories"]["total"] >= 1
        # subagent 活跃列表含刚建的 pending repo_summary
        active_ids = {item["session_id"] for item in data["subagent"]["active"]}
        assert "obs-sub-pending" in active_ids
        # by_type_status 含 repo_summary/pending 计数
        combos = {
            (row["task_type"], row["status"])
            for row in data["subagent"]["by_type_status"]
        }
        assert ("repo_summary", "pending") in combos
