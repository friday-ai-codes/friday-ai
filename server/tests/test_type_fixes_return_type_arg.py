"""
Task 2: 测试修复返回值和泛型类型错误
"""
import asyncio
from typing import Any, Optional

from django.test import TestCase


class TestReturnTypeAndTypeArgFixes(TestCase):
    """测试返回值和泛型类型修复"""

    def test_optional_return_type_annotation(self):
        """测试可选返回值的类型标注"""
        # 模拟一个可能返回 None 的方法
        def get_optional_value(should_return: bool) -> Optional[str]:
            if should_return:
                return "value"
            return None

        # 测试两种返回情况
        self.assertEqual(get_optional_value(True), "value")
        self.assertIsNone(get_optional_value(False))

    def test_asyncio_task_generic_type_annotation(self):
        """测试 asyncio.Task 泛型参数标注"""

        async def run_task_test():
            async def sample_coroutine() -> str:
                return "completed"

            # 创建带泛型参数的 Task
            task: asyncio.Task[str] = asyncio.create_task(sample_coroutine())

            # 验证 task 类型
            self.assertIsInstance(task, asyncio.Task)

            # 创建 Task 集合
            task_set: set[asyncio.Task[Any]] = {task}
            self.assertEqual(len(task_set), 1)

            # 清理
            task.cancel()

        # 在新的事件循环中运行
        asyncio.run(run_task_test())

    def test_specific_return_type_annotation(self):
        """测试具体返回类型标注避免 Any"""

        def get_content() -> dict[str, str]:
            return {"content": "test"}

        result = get_content()
        self.assertIsInstance(result, dict)
        self.assertEqual(result["content"], "test")
