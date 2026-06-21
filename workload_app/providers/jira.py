import os

from django.db.models import QuerySet

from .base import BaseWorkProvider


class JiraWorkProvider(BaseWorkProvider):
    """
    JIRA provider stub. Syncs assigned JIRA issues into WorkItem rows.

    Required env vars: JIRA_BASE_URL, JIRA_API_TOKEN, JIRA_EMAIL.
    Not active in v1 — swap in via registry.py when credentials are available.
    """

    def __init__(self):
        self.base_url = os.environ.get("JIRA_BASE_URL", "")
        self.api_token = os.environ.get("JIRA_API_TOKEN", "")
        self.email = os.environ.get("JIRA_EMAIL", "")

    def get_active_items(self, employee) -> QuerySet:
        # TODO: call JIRA REST API (GET /rest/api/3/search) filtered by
        # employee.account.email, sync results into WorkItem rows with source=JIRA,
        # then return employee.work_items.filter(source="JIRA").exclude(status="DONE").
        raise NotImplementedError("JIRA provider not yet implemented.")
