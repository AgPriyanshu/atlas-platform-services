from abc import ABC, abstractmethod

from django.db.models import QuerySet


class BaseWorkProvider(ABC):
    """Abstract provider for fetching active work items for an employee."""

    @abstractmethod
    def get_active_items(self, employee) -> QuerySet:
        raise NotImplementedError
