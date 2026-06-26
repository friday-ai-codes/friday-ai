"""分支名生成/拼装/校验测试（Phase 89 PLAN-04，BRANCH_NAMING）。

覆盖（纯函数 + LLM mock，无 DB/网络）：
- ``build_branch_name`` 产固定格式（含/不含版本号）+ 示例逐字一致；
- ``validate_branch_name`` 对示例 True、非法名 False；
- 段规整（空白/非法符号去除，保留中文）+ tracking_id 去前导 m-；
- ``generate_branch_name``：LLM 定 type/版本号 server 权威拼；LLM 失败兜底 type=feat；
  change_type_override 直采不调 LLM；project_name 缺 → project.name 兜底；id 始终 server 权威。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from initiatives.services.branch_naming import (
    build_branch_name,
    generate_branch_name,
    validate_branch_name,
)

_MOD = "initiatives.services.branch_naming"
_EXAMPLE = "feat/260610.m-123456770019.高三提分专项-v1.0"


class TestBuildBranchName:
    def test_with_version_matches_example(self) -> None:
        name = build_branch_name(
            change_type="feat",
            yymmdd="260610",
            tracking_id="123456770019",
            project_name="高三提分专项",
            version="v1.0",
        )
        assert name == _EXAMPLE
        assert validate_branch_name(name) is True

    def test_without_version_omits_suffix(self) -> None:
        name = build_branch_name(
            change_type="fix",
            yymmdd="260610",
            tracking_id="123456770019",
            project_name="高三提分专项",
        )
        assert name == "fix/260610.m-123456770019.高三提分专项"
        assert "-v" not in name
        assert validate_branch_name(name) is True

    def test_illegal_type_falls_back_feat(self) -> None:
        name = build_branch_name(
            change_type="bogus",
            yymmdd="260610",
            tracking_id="1",
            project_name="X",
        )
        assert name.startswith("feat/")

    def test_tracking_id_strips_m_prefix(self) -> None:
        name = build_branch_name(
            change_type="feat",
            yymmdd="260610",
            tracking_id="m-123456770019",
            project_name="高三提分专项",
        )
        assert ".m-123456770019." in name
        assert ".m-m-" not in name

    def test_project_name_sanitized_preserves_chinese(self) -> None:
        name = build_branch_name(
            change_type="feat",
            yymmdd="260610",
            tracking_id="1",
            project_name="高三 提分/专项",
        )
        assert " " not in name
        assert "/" in name  # 仅 type 后的那个斜杠
        assert name.count("/") == 1
        assert "高三" in name
        assert validate_branch_name(name) is True

    def test_version_normalized_from_loose_input(self) -> None:
        name = build_branch_name(
            change_type="feat",
            yymmdd="260610",
            tracking_id="1",
            project_name="X",
            version="V2.3.1",
        )
        assert name.endswith("-v2.3.1")


class TestValidate:
    def test_example_valid(self) -> None:
        assert validate_branch_name(_EXAMPLE) is True

    @pytest.mark.parametrize(
        "bad",
        [
            "feature/260610.m-1.X",  # type 非 conventional
            "feat/26061.m-1.X",  # 日期非 6 位
            "feat/260610.1.X",  # 缺 m- 前缀
            "feat/260610.m-1.项目 名",  # 段含空白
            "feat/260610.m-1.a/b",  # 段含斜杠
            "",
        ],
    )
    def test_invalid_names(self, bad: str) -> None:
        assert validate_branch_name(bad) is False


class TestGenerateBranchName:
    @pytest.mark.asyncio
    async def test_llm_decides_type_and_version_server_assembles(self) -> None:
        work_item = SimpleNamespace(work_item_id="123456770019", name="高三提分专项")
        project = SimpleNamespace(id="p1", name="备用项目名")
        with (
            patch(f"{_MOD}.date") as mock_date,
            patch(
                f"{_MOD}._ainvoke_naming_llm",
                AsyncMock(
                    return_value={
                        "change_type": "feat",
                        "include_version": True,
                        "version": "v1.0",
                    }
                ),
            ),
        ):
            mock_date.today.return_value.strftime.return_value = "260610"
            result = await generate_branch_name(
                repo=SimpleNamespace(id="r1"),
                project=project,
                work_item=work_item,
                requirement_text="新增高三提分功能 v1.0",
                initiated_by_user_id="42",
            )
        assert result["branch_name"] == _EXAMPLE
        assert result["change_type"] == "feat"
        assert result["tracking_id"] == "123456770019"
        assert result["fallback"] is False

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_feat(self) -> None:
        work_item = SimpleNamespace(work_item_id="999", name="某项目")
        with (
            patch(f"{_MOD}.date") as mock_date,
            patch(
                f"{_MOD}._ainvoke_naming_llm",
                AsyncMock(side_effect=RuntimeError("provider down")),
            ),
        ):
            mock_date.today.return_value.strftime.return_value = "260610"
            result = await generate_branch_name(
                work_item=work_item,
                requirement_text="随便改改",
            )
        assert result["change_type"] == "feat"
        assert result["fallback"] is True
        assert result["branch_name"] == "feat/260610.m-999.某项目"
        assert validate_branch_name(result["branch_name"]) is True

    @pytest.mark.asyncio
    async def test_change_type_override_skips_llm(self) -> None:
        work_item = SimpleNamespace(work_item_id="999", name="某项目")
        llm = AsyncMock()
        with (
            patch(f"{_MOD}.date") as mock_date,
            patch(f"{_MOD}._ainvoke_naming_llm", llm),
        ):
            mock_date.today.return_value.strftime.return_value = "260610"
            result = await generate_branch_name(
                work_item=work_item,
                requirement_text="x",
                change_type_override="fix",
            )
        llm.assert_not_awaited()
        assert result["change_type"] == "fix"
        assert result["branch_name"].startswith("fix/260610.m-999.")

    @pytest.mark.asyncio
    async def test_project_name_falls_back_to_project(self) -> None:
        # work_item 无 name → 用 project.name 兜底（A6）。
        work_item = SimpleNamespace(work_item_id="999", name="")
        project = SimpleNamespace(id="p1", name="兜底项目名")
        with (
            patch(f"{_MOD}.date") as mock_date,
            patch(f"{_MOD}._ainvoke_naming_llm", AsyncMock(side_effect=RuntimeError("x"))),
        ):
            mock_date.today.return_value.strftime.return_value = "260610"
            result = await generate_branch_name(
                project=project,
                work_item=work_item,
                requirement_text="x",
            )
        assert result["project_name"] == "兜底项目名"
        assert "兜底项目名" in result["branch_name"]

    @pytest.mark.asyncio
    async def test_id_is_server_authoritative_llm_cannot_change(self) -> None:
        # LLM 即便返回伪造 id 字段也不生效——server 只采 work_item.work_item_id。
        work_item = SimpleNamespace(work_item_id="700019", name="项目X")
        with (
            patch(f"{_MOD}.date") as mock_date,
            patch(
                f"{_MOD}._ainvoke_naming_llm",
                AsyncMock(
                    return_value={
                        "change_type": "chore",
                        "include_version": False,
                        "tracking_id": "HACKED",  # 忽略
                    }
                ),
            ),
        ):
            mock_date.today.return_value.strftime.return_value = "260610"
            result = await generate_branch_name(
                work_item=work_item,
                requirement_text="x",
            )
        assert result["tracking_id"] == "700019"
        assert ".m-700019." in result["branch_name"]
        assert "HACKED" not in result["branch_name"]
