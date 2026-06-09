"""回填历史会话 created_by（ISO-01）。

把所有 created_by 为 null 的会话（含软删 is_deleted=True 行）归属给最早创建的
superuser（按 order_by("created_at", "id") 取第一个；与 accounts/0005 排序字段一致，
见 RESEARCH A2——accounts.User 实有 created_at，无 date_joined）。

约束兼容：accounts/0006 以 partial unique index 限制「最多一个 superuser」，
故 DB 层只可能存在单个 superuser——「最早」即「该唯一 superuser」。

容错：无 superuser 时不回填、不抛错（留 null 不阻塞部署）。
可逆：backwards 把全部会话 created_by 置回 None。
"""

from django.db import migrations


def forwards(apps, schema_editor):
    """把历史无主会话回填给最早 superuser；无 superuser 留 null 不阻塞。"""
    Conversation = apps.get_model("chat", "Conversation")
    User = apps.get_model("accounts", "User")

    earliest = (
        User.objects.filter(is_superuser=True).order_by("created_at", "id").first()
    )
    if earliest is None:
        # 无 superuser：留 null，不回填、不阻塞（容错）。
        return

    # 覆盖软删行：filter 不加 is_deleted 条件，确保 is_deleted=True 的历史会话同样回填。
    Conversation.objects.filter(created_by__isnull=True).update(created_by=earliest)


def backwards(apps, schema_editor):
    """可逆：把全部会话 created_by 置回 None。"""
    Conversation = apps.get_model("chat", "Conversation")
    Conversation.objects.update(created_by=None)


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0018_conversation_created_by"),
        # 依赖 accounts 已迁移以保证 User 表（含 created_at / is_superuser）存在。
        ("accounts", "0006_add_single_superuser_constraint"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
