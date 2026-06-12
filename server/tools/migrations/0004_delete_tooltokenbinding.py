# 移除「工具令牌绑定」：明文 PAT 绝不落库（AccessToken 仅存 sha256 哈希），
# 绑定表无法用于容器注入，唯一消费方恒返回空——功能整体下线。
# PAT 本身即代表令牌所有者的全部能力，无须按工具绑定。

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("tools", "0003_tooltokenbinding"),
    ]

    operations = [
        migrations.DeleteModel(name="ToolTokenBinding"),
    ]
