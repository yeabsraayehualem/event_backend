from django.db import migrations

DEFAULT_SKILLS = [
    "Usher", "Waiter / server", "Stagehand", "Decorator", "Sound engineer", "Lighting technician",
    "MC / host", "Photographer", "Videographer", "Driver", "Security", "Cleaner", "Coordinator",
]


def add_skills(apps, schema_editor):
    Skill = apps.get_model("hr", "Skill")
    for name in DEFAULT_SKILLS:
        Skill.objects.get_or_create(name=name)


class Migration(migrations.Migration):
    dependencies = [("hr", "0001_initial")]

    operations = [migrations.RunPython(add_skills, migrations.RunPython.noop)]
