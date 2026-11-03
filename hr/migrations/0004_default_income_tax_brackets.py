from decimal import Decimal

from django.db import migrations

# Monthly employment income tax, Income Tax (Amendment) Proclamation No. 1395/2025, effective July 2025.
# Seeded as a starting point only: PayrollSettings.tax_table_confirmed stays False until the
# accountant checks these against the current gazetted rates.
BRACKETS = [("2000", "0"), ("4000", "15"), ("7000", "20"), ("10000", "25"), ("14000", "30"), (None, "35")]


def add_brackets(apps, schema_editor):
    IncomeTaxBracket = apps.get_model("hr", "IncomeTaxBracket")
    if IncomeTaxBracket.objects.exists():
        return
    for upper, rate in BRACKETS:
        IncomeTaxBracket.objects.create(upper_limit=Decimal(upper) if upper else None, rate=Decimal(rate))
    apps.get_model("hr", "PayrollSettings").objects.get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [("hr", "0003_incometaxbracket_payrollsettings_payrun_payslip_and_more")]

    operations = [migrations.RunPython(add_brackets, migrations.RunPython.noop)]
