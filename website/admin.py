from django.contrib import admin
from .models import ShowcaseEntry


@admin.register(ShowcaseEntry)
class ShowcaseEntryAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "published", "position", "created_at")
    list_filter = ("kind", "published")
    list_editable = ("published", "position")
    search_fields = ("title", "description", "attribution")
