"""Workflow models: a user-composed DAG of data-source and processing-tool nodes."""

from django.db import models

from shared.models.base_models import BaseModel, BaseModelWithoutUser

from ..constants import WorkflowNodeStatus, WorkflowRunStatus
from .dataset_models import Dataset
from .processing_job_models import ProcessingJob


class Workflow(BaseModel):
    """A saved graph definition of data-source and operation nodes."""

    name = models.CharField(max_length=255)

    description = models.TextField(blank=True, default="")

    definition = models.JSONField(
        default=dict,
        blank=True,
        help_text="Graph definition: {'nodes': [...], 'edges': [...]}.",
    )

    class Meta:
        db_table = "workflow"
        verbose_name = "Workflow"
        verbose_name_plural = "Workflows"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Workflow({self.name})"


class WorkflowRun(BaseModel):
    """A single execution of a Workflow's graph."""

    workflow = models.ForeignKey(
        Workflow,
        on_delete=models.CASCADE,
        related_name="runs",
    )

    status = models.CharField(
        max_length=20,
        choices=WorkflowRunStatus.choices,
        default=WorkflowRunStatus.PENDING,
    )

    progress = models.IntegerField(default=0)

    error_message = models.TextField(blank=True, default="")

    celery_task_id = models.CharField(max_length=255, blank=True, default="")

    started_at = models.DateTimeField(null=True, blank=True)

    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "workflow_run"
        verbose_name = "Workflow Run"
        verbose_name_plural = "Workflow Runs"
        ordering = ["-created_at"]

    def __str__(self):
        return f"WorkflowRun({self.workflow_id}, {self.status})"


class WorkflowNodeRun(BaseModelWithoutUser):
    """Per-node execution state within a WorkflowRun. Ownership is inherited via `run`."""

    run = models.ForeignKey(
        WorkflowRun,
        on_delete=models.CASCADE,
        related_name="node_runs",
    )

    node_id = models.CharField(
        max_length=100,
        help_text="Node id from the workflow definition.",
    )

    node_type = models.CharField(max_length=20)

    status = models.CharField(
        max_length=20,
        choices=WorkflowNodeStatus.choices,
        default=WorkflowNodeStatus.PENDING,
    )

    output_dataset = models.ForeignKey(
        Dataset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workflow_node_runs",
    )

    processing_job = models.ForeignKey(
        ProcessingJob,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workflow_node_runs",
        help_text="The underlying ProcessingJob used to execute an operation node, if any.",
    )

    error_message = models.TextField(blank=True, default="")

    started_at = models.DateTimeField(null=True, blank=True)

    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "workflow_node_run"
        verbose_name = "Workflow Node Run"
        verbose_name_plural = "Workflow Node Runs"
        ordering = ["created_at"]
        unique_together = ("run", "node_id")

    def __str__(self):
        return f"WorkflowNodeRun({self.run_id}, {self.node_id}, {self.status})"
