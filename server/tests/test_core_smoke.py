"""core App 冒烟测试。"""
from django.test import override_settings
class TestFeatureFlags:
 """FeatureFlags 特性开关读取。"""
 def test_feature_flags_defaults(self):
 from core.feature_flags import FeatureFlags
 ff = FeatureFlags
 assert ff.sync_workflow_to_feishu is True
 assert ff.enable_workflow_websocket is True
 assert ff.default_workflow_template == "code_generation"
 @override_settings(FF_SYNC_WORKFLOW_TO_FEISHU=False)
 def test_feature_flag_override(self):
 from core.feature_flags import FeatureFlags
 ff = FeatureFlags
 assert ff.sync_workflow_to_feishu is False
