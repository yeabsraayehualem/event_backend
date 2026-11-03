from django.db import migrations

DEFAULT_CATEGORIES = [
    "Vendor services",
    "Freelance crew",
    "Salaries",
    "Transport & fuel",
    "Supplies & materials",
    "Equipment repair",
    "Marketing",
    "Rent & utilities",
    "Office & admin",
    "Other",
]


def add_categories(apps, schema_editor):
    ExpenseCategory = apps.get_model("finance", "ExpenseCategory")
    for position, name in enumerate(DEFAULT_CATEGORIES):
        ExpenseCategory.objects.get_or_create(name=name, defaults={"sequence": position})


class Migration(migrations.Migration):
    dependencies = [("finance", "0007_expensecategory_expense")]

    operations = [migrations.RunPython(add_categories, migrations.RunPython.noop)]
