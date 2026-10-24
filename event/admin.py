from django.contrib import admin
from .models import Plan, Package, Content, Event,Project,Task
# Register your models here.

admin.site.register(Plan)
admin.site.register(Package)
admin.site.register(Content)
admin.site.register(Event)
admin.site.register(Project)
admin.site.register(Task)