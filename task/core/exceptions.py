"""Task container 自定义异常。"""
class ExploreModeForbiddenError(Exception):
 """explore 模式下禁止执行 git 写操作。
 双层防御的 Python 层组件。当 GitOperations 在 explore 模式下
 检测到写操作调用时抛出此异常。
 """
 def __init__(self, operation: str) -> None:
 self.operation = operation
 super.__init__(
 f"explore 模式禁止 git 写操作: {operation}"
 )
