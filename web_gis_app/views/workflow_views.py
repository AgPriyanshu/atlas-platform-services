"""API views for the workflow builder (DAG-based multi-step geoprocessing)."""

from __future__ import annotations

from celery.result import AsyncResult
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from shared.views import BaseModelViewSet

from ..constants import WorkflowRunStatus
from ..models import Workflow, WorkflowRun
from ..serializers.workflow_serializers import WorkflowRunSerializer, WorkflowSerializer
from ..tasks import run_workflow

_TERMINAL_RUN_STATUSES = (
    WorkflowRunStatus.COMPLETED,
    WorkflowRunStatus.FAILED,
    WorkflowRunStatus.CANCELLED,
)


class WorkflowViewSet(BaseModelViewSet):
    """CRUD for saved workflow (DAG) definitions."""

    queryset = Workflow.objects.all()
    serializer_class = WorkflowSerializer
    permission_classes = [IsAuthenticated]


class WorkflowRunListCreateView(generics.ListCreateAPIView):
    """List run history for a workflow, or submit a new run."""

    serializer_class = WorkflowRunSerializer
    permission_classes = [IsAuthenticated]

    def get_workflow(self) -> Workflow:
        return get_object_or_404(
            Workflow, pk=self.kwargs["workflow_id"], user=self.request.user
        )

    def get_queryset(self):
        return (
            WorkflowRun.objects.filter(workflow=self.get_workflow())
            .prefetch_related("node_runs")
            .order_by("-created_at")
        )

    def create(self, request, *args, **kwargs):
        workflow = self.get_workflow()
        run = WorkflowRun.objects.create(
            workflow=workflow, user=request.user, status=WorkflowRunStatus.PENDING
        )

        async_result = run_workflow.delay(str(run.id))
        run.celery_task_id = async_result.id
        run.save(update_fields=["celery_task_id", "updated_at"])

        return Response(WorkflowRunSerializer(run).data, status=status.HTTP_201_CREATED)


class WorkflowRunDetailView(generics.RetrieveDestroyAPIView):
    """Retrieve a run's status (with per-node detail), or cancel it."""

    serializer_class = WorkflowRunSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return WorkflowRun.objects.filter(
            workflow_id=self.kwargs["workflow_id"], workflow__user=self.request.user
        ).prefetch_related("node_runs")

    def destroy(self, request, *args, **kwargs):
        run = self.get_object()

        if run.status in _TERMINAL_RUN_STATUSES:
            return Response(
                {"detail": "Run already finished."}, status=status.HTTP_400_BAD_REQUEST
            )

        if run.celery_task_id:
            AsyncResult(run.celery_task_id).revoke(terminate=True)

        run.status = WorkflowRunStatus.CANCELLED
        run.error_message = "Cancelled by user."
        run.save(update_fields=["status", "error_message", "updated_at"])

        return Response(status=status.HTTP_204_NO_CONTENT)
