
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):

    class Role(models.TextChoices):
        STAFF = "staff", "Staff"
        HR = "hr", "HR"
        FINANCE = "finance", "Finance"
        STOCK = "stock", "Stock"
        SALES = "sales", "Sales"
        PM = "pm", "Project Management"
        ADMIN = "admin", "Admin"
        SUPER = "super", "Super"

    phone = models.CharField(
        max_length=20,
        unique=True,
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.STAFF,
    )

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = ["username"]

    def __str__(self):
        return self.phone

