"""system App 冒烟测试。"""
import pytest
@pytest.mark.django_db
class TestSystemSettingModel:
 """SystemSetting 模型创建与查询。"""
 def test_create_setting(self):
 from system.models import SystemSetting
 setting = SystemSetting.objects.create(
 key="smoke_test_key", value="smoke_test_value"
 )
 assert SystemSetting.objects.filter(key="smoke_test_key").exists
 assert setting.value == "smoke_test_value"
@pytest.mark.django_db
class TestCacheVolumeTrackerModel:
 """CacheVolumeTracker 模型创建与查询。"""
 def test_create_tracker(self):
 from system.models import CacheVolumeTracker
 tracker = CacheVolumeTracker.objects.create(
 volume_name="smoke-vol", volume_type="repo"
 )
 assert CacheVolumeTracker.objects.filter(pk=tracker.pk).exists
