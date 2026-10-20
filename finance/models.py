
from django.db import models
from crm.models import Customers
from event.models import Content, Plan, Package
from decimal import Decimal, ROUND_HALF_UP
from django.db.models import Sum


class CustomerInvoice(models.Model):
    date = models.DateField(auto_now_add=True)

    reference = models.CharField( max_length=20,unique=True,)

    customer = models.ForeignKey( Customers,on_delete=models.PROTECT,related_name="invoices", )

    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="invoices", )

    package = models.ForeignKey( Package, on_delete=models.PROTECT,  related_name="invoices", )

    total = models.DecimalField( max_digits=12,decimal_places=2,  default=0,)
    
    def recalculate_total(self):
        result = self.lines.aggregate(
            amount=Sum("total")
        )

        self.total = result["amount"] or Decimal("0.00")
        self.save(update_fields=["total"], recalculated=True)


    def __str__(self):
        return f"{self.reference} - {self.customer.name}"


    def save(self, *args, **kwargs):
        recalculated = kwargs.pop("recalculated", False)

        super().save(*args, **kwargs)

        if not recalculated:
            self.recalculate_total()




class InvoiceLines(models.Model):
    invoice = models.ForeignKey( "CustomerInvoice",on_delete=models.CASCADE, related_name="lines", )

    content = models.ForeignKey( "event.Content", on_delete=models.PROTECT, )

    inclusive_price = models.DecimalField(max_digits=12, decimal_places=2, )

    tax_rate = models.DecimalField(max_digits=5,
        decimal_places=2, default=Decimal("15.00"),)

    price = models.DecimalField( max_digits=12, decimal_places=2,default=0,)

    tax = models.DecimalField(max_digits=12,decimal_places=2, default=0, )

    total = models.DecimalField( max_digits=12, decimal_places=2, default=0,)

    def save(self, *args, **kwargs):
        inclusive = self.inclusive_price
        rate = self.tax_rate / Decimal("100")

        self.price = (inclusive / (1 + rate)).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

        self.tax = inclusive - self.price
        self.total = inclusive

        

        res = super().save(*args, **kwargs)
        self.invoice.recalculate_total()

        return res
