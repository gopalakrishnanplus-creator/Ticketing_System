from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ("task_app", "0002_alter_task_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="viewers",
            field=models.JSONField(default=list, blank=True),
        ),
    ]
