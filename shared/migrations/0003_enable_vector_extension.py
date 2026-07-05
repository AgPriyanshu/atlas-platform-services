from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("shared", "0002_alter_notification_app_name"),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS vector;",
            reverse_sql="DROP EXTENSION IF EXISTS vector;",
        ),
    ]
