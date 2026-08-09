import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend_projects.settings")

app = Celery("backend_projects")

# Read config from Django settings, the CELERY_ namespace means all
# celery-related configuration keys should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks in all installed apps.
app.autodiscover_tasks()
