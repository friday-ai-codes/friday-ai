from django.db import migrations, models
class Migration(migrations.Migration):
 dependencies = [
 ("workflows", "0023_error_handling_fields"),
 ]
 operations = [
 migrations.AddField(
 model_name="nodeexecution",
 name="logs",
 field=models.JSONField(
 default=list,
 blank=True,
 verbose_name="执行日志",
 help_text="结构化日志数组，每个元素为 {timestamp, level, message, context}",
 ),
 ),
 migrations.AddField(
 model_name="nodeexecution",
 name="error_code",
 field=models.CharField(
 max_length=20,
 choices=[
 ("timeout", "执行超时"),
 ("permission", "权限不足"),
 ("resource", "资源不足"),
 ("api", "外部 API 错误"),
 ("runtime", "运行时错误"),
 ("unknown", "未知错误"),
 ],
 null=True,
 blank=True,
 verbose_name="错误码",
 help_text="节点失败时的错误分类",
 ),
 ),
 ]
