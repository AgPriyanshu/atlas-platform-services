from django.db.models import QuerySet

from workload_app.models import WorkItemStatus

from .base import BaseWorkProvider


class ManualWorkProvider(BaseWorkProvider):
    """Returns active work items stored manually in the database."""

    def get_active_items(self, employee) -> QuerySet:
        return employee.work_items.exclude(status=WorkItemStatus.DONE)
