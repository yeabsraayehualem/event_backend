from django.contrib import admin
from .models import Plan, Package, Content, Event
# Register your models here.

admin.site.register(Plan)
admin.site.register(Package)
admin.site.register(Content)
admin.site.register(Event)
