from django.db import models


class ShowcaseEntry(models.Model):
    class Kind(models.TextChoices):
        SERVICE = "service", "Service"
        GALLERY = "gallery", "Gallery"
        TESTIMONIAL = "testimonial", "Testimonial"

    kind = models.CharField(max_length=20, choices=Kind.choices)
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="showcase/", blank=True)
    attribution = models.CharField(max_length=180, blank=True)
    published = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.title}"
