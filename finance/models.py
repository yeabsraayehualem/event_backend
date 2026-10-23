
from django.db import models
from crm.models import Customers
from event.models import Content, Plan, Package, Event
from decimal import Decimal, ROUND_HALF_UP
from django.db.models import Sum, Max
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator


class TaxRate(models.Model):
    class Kind(models.TextChoices):
        VAT = "vat", "VAT"
        WITHHOLDING = "withholding", "Withholding"
        SERVICE_CHARGE = "service_charge", "Service charge"
        EXEMPT = "exempt", "Exempt"

    name = models.CharField(max_length=100, unique=True)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.VAT)
    rate = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    inclusive = models.BooleanField(default=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.rate}%)"


class CustomerInvoice(models.Model):
    class Status(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PAID = "paid", "Paid"

    date = models.DateField(auto_now_add=True)

    reference = models.CharField(max_length=20, unique=True, blank=True)
    sequence = models.PositiveIntegerField(default=0)
    milestone_name = models.CharField(max_length=120, blank=True)
    due_date = models.DateField(null=True, blank=True)
    event = models.ForeignKey(Event, on_delete=models.PROTECT, null=True, blank=True, related_name="invoices")

    customer = models.ForeignKey( Customers,on_delete=models.PROTECT,related_name="invoices", )

    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="invoices", )

    package = models.ForeignKey(Package, on_delete=models.PROTECT, related_name="invoices", null=True, blank=True)

    total = models.DecimalField( max_digits=12,decimal_places=2,  default=0,)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.UNPAID)
    
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

        if not self.pk and not self.reference:
            year = timezone.localdate().year
            last_sequence = CustomerInvoice.objects.filter(date__year=year).aggregate(
                value=Max("sequence")
            )["value"] or 0
            self.sequence = last_sequence + 1
            self.reference = f"INV-{year}-{self.sequence:04d}"

        super().save(*args, **kwargs)

        if not recalculated:
            self.recalculate_total()




class InvoiceLines(models.Model):
    invoice = models.ForeignKey( "CustomerInvoice",on_delete=models.CASCADE, related_name="lines", )

    content = models.ForeignKey( "event.Content", on_delete=models.PROTECT, )

    tax_profile = models.ForeignKey(TaxRate, on_delete=models.SET_NULL, null=True, blank=True)

    inclusive_price = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(0)],
    )

    tax_rate = models.DecimalField(max_digits=5,
        decimal_places=2, default=Decimal("15.00"),)

    price = models.DecimalField( max_digits=12, decimal_places=2,default=0,)

    tax = models.DecimalField(max_digits=12,decimal_places=2, default=0, )

    total = models.DecimalField( max_digits=12, decimal_places=2, default=0,)

    def save(self, *args, **kwargs):
        if self.tax_profile_id:
            self.tax_rate = self.tax_profile.rate
        inclusive = self.inclusive_price
        rate = self.tax_rate / Decimal("100")
        kind = self.tax_profile.kind if self.tax_profile_id else TaxRate.Kind.VAT
        tax_inclusive = self.tax_profile.inclusive if self.tax_profile_id else True
        if kind == TaxRate.Kind.EXEMPT:
            self.price, self.tax, self.total = inclusive, Decimal("0.00"), inclusive
        elif kind == TaxRate.Kind.VAT and tax_inclusive:
            self.price = (inclusive / (1 + rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            self.tax = inclusive - self.price
            self.total = inclusive
        else:
            self.price = inclusive
            calculated_tax = (inclusive * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            self.tax = -calculated_tax if kind == TaxRate.Kind.WITHHOLDING else calculated_tax
            self.total = inclusive + self.tax

        

        res = super().save(*args, **kwargs)
        self.invoice.recalculate_total()

        return res

    def recalculate_tax(self):
        base = self.inclusive_price
        included_vat = Decimal("0.00")
        added_or_deducted = Decimal("0.00")
        tax_total = Decimal("0.00")
        for component in self.tax_components.all():
            rate = component.rate / Decimal("100")
            if component.kind == TaxRate.Kind.EXEMPT:
                amount = Decimal("0.00")
            elif component.kind == TaxRate.Kind.VAT and component.inclusive:
                amount = (base * rate / (1 + rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                included_vat += amount
            else:
                amount = (base * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if component.kind == TaxRate.Kind.WITHHOLDING:
                    amount = -amount
                added_or_deducted += amount
            component.amount = amount
            component.save(update_fields=["amount"])
            tax_total += amount

        self.price = base - included_vat
        self.tax = tax_total
        self.total = base + added_or_deducted
        super().save(update_fields=["price", "tax", "total"])
        self.invoice.recalculate_total()


class InvoiceLineTax(models.Model):
    line = models.ForeignKey(InvoiceLines, on_delete=models.CASCADE, related_name="tax_components")
    profile = models.ForeignKey(TaxRate, on_delete=models.SET_NULL, null=True, blank=True)
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=20, choices=TaxRate.Kind.choices)
    rate = models.DecimalField(max_digits=5, decimal_places=2)
    inclusive = models.BooleanField(default=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.name}: {self.amount}"
