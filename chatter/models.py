from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from accounts.models import User


class Message(models.Model):
    """One entry in a record's chatter: a logged note, a field-change log, or a system event."""

    class Kind(models.TextChoices):
        NOTE = "note", "Note"
        TRACKING = "tracking", "Change log"
        SYSTEM = "system", "System"

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    record = GenericForeignKey("content_type", "object_id")
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="chatter_messages")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.NOTE)
    body = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["content_type", "object_id", "-created_at"])]

    def __str__(self):
        return f"{self.get_kind_display()} on {self.content_type.model} #{self.object_id}"


class TrackingValue(models.Model):
    """A single field change recorded on a tracking message."""

    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="tracking_values")
    field = models.CharField(max_length=100)
    field_label = models.CharField(max_length=150)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)

    class Meta:
        ordering = ["id"]
