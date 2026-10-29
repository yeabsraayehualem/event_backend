from django.contrib import admin

from chatter.models import Message, TrackingValue


class TrackingValueInline(admin.TabularInline):
    model = TrackingValue
    extra = 0


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ["content_type", "object_id", "kind", "author", "created_at"]
    list_filter = ["kind", "content_type"]
    inlines = [TrackingValueInline]
