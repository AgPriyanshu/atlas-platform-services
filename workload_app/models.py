from django.contrib.auth.models import User
from django.db import models

from shared.models.base_models import BaseModel


class Employee(BaseModel):
    """Represents a person in the org hierarchy. user = chart owner (via BaseModel)."""

    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    designation = models.CharField(max_length=255)
    capacity = models.PositiveIntegerField(default=5)
    manager = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="reports",
        on_delete=models.SET_NULL,
    )
    account = models.ForeignKey(
        User,
        null=True,
        blank=True,
        related_name="employee_profiles",
        on_delete=models.SET_NULL,
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.designation})"


class WorkItemStatus(models.TextChoices):
    TODO = "TODO", "Todo"
    IN_PROGRESS = "IN_PROGRESS", "In Progress"
    DONE = "DONE", "Done"


class WorkItemSource(models.TextChoices):
    MANUAL = "MANUAL", "Manual"
    JIRA = "JIRA", "Jira"


class WorkItem(models.Model):
    """A unit of work assigned to an employee."""

    employee = models.ForeignKey(
        Employee,
        related_name="work_items",
        on_delete=models.CASCADE,
    )
    title = models.CharField(max_length=500)
    status = models.CharField(
        max_length=20,
        choices=WorkItemStatus.choices,
        default=WorkItemStatus.TODO,
    )
    external_key = models.CharField(max_length=100, blank=True, null=True)
    url = models.URLField(blank=True, null=True)
    source = models.CharField(
        max_length=20,
        choices=WorkItemSource.choices,
        default=WorkItemSource.MANUAL,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title
