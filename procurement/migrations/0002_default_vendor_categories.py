from django.db import migrations

DEFAULT_CATEGORIES = [
    "Catering",
    "Equipment & material rental",
    "Photography & video",
    "Decoration & florists",
    "Venue",
    "Sound, lighting & stage",
    "Entertainment",
    "Transport",
    "Security",
]


def add_categories(apps, schema_editor):
    VendorCategory = apps.get_model("procurement", "VendorCategory")
    for position, name in enumerate(DEFAULT_CATEGORIES):
        VendorCategory.objects.get_or_create(name=name, defaults={"sequence": position})


class Migration(migrations.Migration):
    dependencies = [("procurement", "0001_initial")]

    operations = [migrations.RunPython(add_categories, migrations.RunPython.noop)]
