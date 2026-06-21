from django.contrib import admin

from .models import Employee, WorkItem

admin.site.register(Employee)
admin.site.register(WorkItem)
