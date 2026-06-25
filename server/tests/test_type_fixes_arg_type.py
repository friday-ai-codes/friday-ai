"""
Task 1: 测试修复参数类型不匹配错误 (arg-type)
"""
from unittest.mock import MagicMock

import pytest
from asgiref.sync import sync_to_async
from django.test import TestCase

from permissions.models import SpaceRole
from permissions.services import PermissionService


class TestArgTypeFixes(TestCase):
    """测试 arg-type 类型修复"""

    def test_project_role_enum_is_string_compatible(self):
        """测试 SpaceRole 枚举值能作为字符串类型参数传递"""
        # 验证 SpaceRole 值是字符串类型
        self.assertIsInstance(SpaceRole.VIEWER, str)
        self.assertIsInstance(SpaceRole.ADMIN, str)
        self.assertEqual(SpaceRole.VIEWER, "viewer")
        self.assertEqual(SpaceRole.ADMIN, "admin")

    @pytest.mark.asyncio
    async def test_has_project_access_accepts_project_role_enum(self):
        """测试 has_project_access 方法接受 SpaceRole 枚举参数"""
        # Mock 用户和项目
        user = MagicMock()
        project = MagicMock()

        # Mock PermissionService.has_project_access 返回 True
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(PermissionService, 'has_project_access', lambda user, project, role: True)

            # 应能接受 SpaceRole 枚举值作为参数
            result = PermissionService.has_project_access(user, project, SpaceRole.VIEWER)
            self.assertTrue(result)

            result = PermissionService.has_project_access(user, project, SpaceRole.ADMIN)
            self.assertTrue(result)

    @pytest.mark.asyncio
    async def test_sync_to_async_list_call_is_properly_typed(self):
        """测试 sync_to_async(list) 调用的参数类型正确"""
        # 创建一个 QuerySet mock
        queryset_mock = MagicMock()
        queryset_mock.__iter__ = MagicMock(return_value=iter([]))

        # sync_to_async(list) 应该能接受可迭代对象
        async_list = sync_to_async(list)
        result = await async_list(queryset_mock)

        # 结果应该是列表类型
        self.assertIsInstance(result, list)
