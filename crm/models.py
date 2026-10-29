from django.db import models
from accounts.models import User
from event.models import EventType, Package, Plan
# Create your models here.

class Customers(models.Model):

    name = models.CharField(max_length=255,)
    phone = models.CharField(max_length=30,)
    email = models.CharField(max_length=255,null=True,blank=True)

    def __str__(self):
        return f"{self.name}"



class Lead(models.Model):

    class Status(models.TextChoices):
        LEAD = "lead", "Lead"
        CONTACTED = "contacted", "Contacted"
        CONSULTATION_SCHEDULED = "consultation_scheduled", "Consultation Scheduled"
        QUOTATION_SENT = "quotation_sent", "Quotation Sent"
        NEGOTIATION = "negotiation", "Negotiation"
        WON = "won", "Won"
        LOST = "lost", "Lost"
        CANCELLED = "cancelled", "Cancelled"

    date = models.DateField(auto_now_add=True)

    customer = models.ForeignKey(
        Customers,
        on_delete=models.PROTECT,
        related_name="leads",
    )

    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name="leads",
    )
    package = models.ForeignKey(Package, on_delete=models.PROTECT,
                                related_name="leads",blank=True, null=True)

    plan_date = models.DateField()
    assigned_sales_person = models.ForeignKey(User,on_delete=models.DO_NOTHING,null=True,blank=True)

    location = models.CharField(max_length=255)

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.LEAD,
    )

    notes = models.TextField(blank=True)
    event_type = models.ForeignKey(
        EventType, on_delete=models.PROTECT, null=True, blank=True, related_name="leads",
    )
    guest_count = models.PositiveIntegerField(null=True, blank=True)
    budget_tier = models.CharField(max_length=80, blank=True)
    requirements = models.TextField(blank=True)

    def __str__(self):
        return f"{self.customer} - {self.plan}"
