"""common App 冒烟测试。"""
class TestShortId:
 """short_id 工具函数。"""
 def test_generate_short_id_length(self):
 from common.short_id import generate_short_id
 sid = generate_short_id(5)
 assert len(sid) == 5
 assert sid[0].isalpha
 def test_generate_unique_short_id(self):
 from common.short_id import generate_unique_short_id
 existing = {"abc", "def"}
 new_id = generate_unique_short_id(existing)
 assert new_id not in existing
class TestExceptions:
 """自定义异常类实例化。"""
 def test_friday_exception(self):
 from common.exceptions import FridayException
 exc = FridayException("test error")
 assert str(exc) == "test error"
 def test_configuration_error(self):
 from common.exceptions import ConfigurationError
 exc = ConfigurationError("bad config")
 assert isinstance(exc, Exception)
