"""Phase: Endpoint 表新增 metadata JSONField（per / ）。
存储 Go gin 路由中 ogin.G* 参数验证 middleware 的参数元数据（路径参数、
查询参数、请求头参数）。null=True 保持与既有 Django/DRF Endpoint 记录兼容。
"""
from django.db import migrations, models
class Migration(migrations.Migration):
 dependencies = [
 ("codegraph", "0001_initial"),
 ]
 operations = [
 migrations.AddField(
 model_name="endpoint",
 name="metadata",
 field=models.JSONField(
 null=True,
 blank=True,
 default=None,
 verbose_name="端点元数据",
 ),
 ),
 ]
