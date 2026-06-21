import os

from .base import BaseWorkProvider
from .manual import ManualWorkProvider


def get_provider() -> BaseWorkProvider:
    """Return the configured work provider. Defaults to manual."""
    provider_name = os.environ.get("WORKLOAD_PROVIDER", "manual")

    if provider_name == "jira":
        from .jira import JiraWorkProvider

        return JiraWorkProvider()

    return ManualWorkProvider()
