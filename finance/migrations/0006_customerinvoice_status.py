from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0005_alter_invoicelines_inclusive_price_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="customerinvoice",
            name="status",
            field=models.CharField(
                choices=[("unpaid", "Unpaid"), ("paid", "Paid")],
                default="unpaid",
                max_length=10,
            ),
        ),
    ]
