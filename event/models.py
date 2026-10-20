from django.db import models


class Plan(models.Model):
    name = models.CharField(max_length=255)
    image = models.ImageField(upload_to="plans/")
    description = models.TextField()

    def __str__(self):
        return self.name



class Content(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class Package(models.Model):
    plan = models.ForeignKey(
        Plan,
        on_delete=models.CASCADE,
        related_name="packages",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    contents = models.ManyToManyField(
        Content,
        related_name="packages",
        blank=True,
    )

    def __str__(self):
        return self.name


class Event(models.Model):
    """Minimal event record created when a CRM lead is won."""

    class Status(models.TextChoices):
        PLANNING = "planning", "Planning"
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    lead = models.OneToOneField("crm.Lead", on_delete=models.PROTECT, related_name="event_record")
    customer = models.ForeignKey("crm.Customers", on_delete=models.PROTECT, related_name="events")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="events")
    package = models.ForeignKey(Package, on_delete=models.PROTECT, null=True, blank=True, related_name="events")
    name = models.CharField(max_length=255)
    event_type = models.CharField(max_length=120, blank=True)
    event_date = models.DateField()
    guest_count = models.PositiveIntegerField(null=True, blank=True)
    location = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLANNING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["event_date", "id"]

    def __str__(self):
        return self.name
