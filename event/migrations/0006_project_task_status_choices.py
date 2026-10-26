from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("event", "0005_project_status"),
    ]

    operations = [
        migrations.AlterField(
            model_name="project",
            name="status",
            field=models.CharField(
                choices=[("draft", "Draft"), ("inprogress", "In Progress"), ("done", "Done")],
                default="draft",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="task",
            name="status",
            field=models.CharField(
                choices=[
                    ("na", "Not Assigned"),
                    ("assigned", "Assigned"),
                    ("ongoing", "On Going"),
                    ("complete", "Complete"),
                    ("blocked", "Blocked"),
                ],
                default="na",
                max_length=20,
            ),
        ),
    ]
