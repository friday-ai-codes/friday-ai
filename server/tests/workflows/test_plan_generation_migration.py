"""守护 0034 迁移：ai_plan_generation → ai_plan_research 的 config 转换正确性。

Chassis v2 物理删除 ai_plan_generation 节点类时漏了数据迁移，存量行会在
``scheduler`` 里命中 ``raise ValueError(f"未知的节点类型: ...")`` 硬失败。0034 补上
迁移，本测试守住两件事：转换后的 config 对目标节点 schema 合法；迁移的前提假设
（源类型已退役、目标类型在册）不被后续改动悄悄推翻。
"""

import pytest


@pytest.fixture
def convert():
    """取迁移模块里的纯函数（迁移文件名以数字开头，不能直接 import）。"""
    import importlib

    module = importlib.import_module(
        "workflows.migrations.0034_migrate_ai_plan_generation_to_plan_research"
    )
    return module._convert_config


class TestConvertConfig:
    def test_carries_over_overlapping_keys(self, convert):
        """两个 schema 的交集键必须逐字保留，不能被重置成默认值。"""
        result = convert(
            {
                "model": "claude-sonnet-4",
                "chat_id": "oc_abc",
                "use_custom_api": True,
                "api_base_url": "https://example.invalid",
                "api_key": "sk-placeholder",
                "include_repos": ["repo-1", "repo-2"],
            }
        )

        assert result["model"] == "claude-sonnet-4"
        assert result["chat_id"] == "oc_abc"
        assert result["use_custom_api"] is True
        assert result["api_base_url"] == "https://example.invalid"
        assert result["api_key"] == "sk-placeholder"
        assert result["include_repos"] == ["repo-1", "repo-2"]

    def test_maps_user_prompt_to_requirement_text(self, convert):
        """旧节点的 user_prompt 承载需求文本，迁到目标的 requirement_text。"""
        result = convert({"user_prompt": "把登录页改成扫码登录"})

        assert result["requirement_text"] == "把登录页改成扫码登录"
        assert "user_prompt" not in result

    def test_does_not_overwrite_existing_requirement_text(self, convert):
        """已有 requirement_text 优先，不被 user_prompt 覆盖。"""
        result = convert(
            {"requirement_text": "权威需求", "user_prompt": "旧字段残留"}
        )

        assert result["requirement_text"] == "权威需求"

    def test_archives_dropped_keys_instead_of_destroying(self, convert):
        """目标 schema 没有的键必须归档留痕，不能静默销毁运维数据。"""
        result = convert(
            {
                "system_prompt": "你是资深架构师",
                "exclude_repos": ["legacy-repo"],
                "max_iterations": 50,
                "enabled_tools": ["search_rag_chunks"],
            }
        )

        archived = result["_legacy_ai_plan_generation"]
        assert archived["system_prompt"] == "你是资深架构师"
        assert archived["exclude_repos"] == ["legacy-repo"]
        assert archived["max_iterations"] == 50
        assert archived["enabled_tools"] == ["search_rag_chunks"]

    def test_empty_config_yields_empty_result(self, convert):
        """空/None config 不应炸，也不该凭空造出归档键。"""
        assert convert({}) == {}
        assert convert(None) == {}

    def test_converted_config_is_valid_for_target_node(self, convert):
        """核心断言：转换产物必须通过 ai_plan_research 的 config 校验。

        否则迁移只是把「未知节点类型」换成了「配置非法」，问题没解决。
        """
        from workflows.nodes.ai.plan_research import AIPlanResearchNode

        result = convert(
            {
                "system_prompt": "你是资深架构师",
                "user_prompt": "把登录页改成扫码登录",
                "include_repos": ["repo-1"],
                "exclude_repos": ["legacy-repo"],
                "max_iterations": 50,
                "enabled_tools": ["search_rag_chunks"],
                "chat_id": "oc_abc",
                "use_custom_api": False,
                "api_base_url": "",
                "api_key": "",
                "model": "claude-sonnet-4",
            }
        )

        assert AIPlanResearchNode.validate_config(result) == []


class TestMigrationPremise:
    """迁移的前提假设——被推翻时应当立刻失败，而不是让迁移变成 no-op。"""

    def test_source_node_type_is_retired_and_target_registered(self):
        from workflows.nodes.registry import NodeRegistry

        assert NodeRegistry.get("ai_plan_generation") is None, (
            "ai_plan_generation 若被重新注册，0034 迁移的前提不再成立，需重新评估"
        )
        assert NodeRegistry.get("ai_plan_research") is not None, (
            "迁移目标 ai_plan_research 必须在册，否则迁移会制造新的孤儿行"
        )
