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
