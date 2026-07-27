"""Serializers for the workflow builder API."""

from __future__ import annotations

from rest_framework import serializers

from shared.serializers import BaseModelSerializer

from ..models import Workflow, WorkflowNodeRun, WorkflowRun
from ..workflows.dag_executor import validate_definition as validate_workflow_definition


class WorkflowSerializer(BaseModelSerializer):
    """CRUD serializer for a saved workflow (DAG) definition."""

    class Meta:
        model = Workflow
        fields = ("id", "name", "description", "definition", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_definition(self, value: dict) -> dict:
        user = self.context["request"].user

        try:
            validate_workflow_definition(value, user)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

        return value


class WorkflowNodeRunSerializer(BaseModelSerializer):
    """Read-only per-node execution status within a WorkflowRun."""

    class Meta:
        model = WorkflowNodeRun
        fields = (
            "id",
            "node_id",
            "node_type",
            "status",
            "output_dataset",
            "error_message",
            "started_at",
            "completed_at",
        )
        read_only_fields = fields


class WorkflowRunSerializer(BaseModelSerializer):
    """Read-only view of a workflow run, including nested per-node status."""

    node_runs = WorkflowNodeRunSerializer(many=True, read_only=True)

    class Meta:
        model = WorkflowRun
        fields = (
            "id",
            "workflow",
            "status",
            "progress",
            "error_message",
            "node_runs",
            "started_at",
            "completed_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields
