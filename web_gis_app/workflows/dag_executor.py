"""Executes a Workflow's user-defined DAG of source/operation nodes.

The `Workflow.definition` JSON shape (keys are snake_case: the frontend's
Axios interceptor converts request bodies to snake_case before sending):

    {
        "nodes": [
            {"id": "n1", "type": "source", "dataset_id": "<uuid>"},
            {"id": "n2", "type": "operation", "tool_name": "buffer", "params": {...}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2"},
        ],
    }

Each `source` node resolves instantly to an existing Dataset. Each
`operation` node is executed by creating a real ProcessingJob and running it
through the exact same `job_executor.execute_processing_job` path used by
one-off tool runs, so the tool_registry/workflow classes are reused as-is.
"""

import json
import logging

from django.contrib.auth.models import User
from django.utils import timezone

from ..constants import (
    ProcessingJobStatus,
    WorkflowNodeStatus,
    WorkflowNodeType,
    WorkflowRunStatus,
)
from ..models import Dataset, ProcessingJob, WorkflowNodeRun, WorkflowRun
from ..notifications import send_notification
from ..tool_registry import get_tool
from .job_executor import execute_processing_job

logger = logging.getLogger(__name__)


def validate_definition(definition: dict, user: User) -> None:
    """Raise ValueError if the graph is malformed, references invalid data, or has a cycle."""

    if not isinstance(definition, dict):
        raise ValueError("Workflow definition must be an object with 'nodes' and 'edges'.")

    nodes = definition.get("nodes", [])
    edges = definition.get("edges", [])

    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("Workflow definition 'nodes' and 'edges' must be lists.")

    node_ids = set()

    for node in nodes:
        node_id = node.get("id")

        if not node_id:
            raise ValueError("Every node requires an 'id'.")

        if node_id in node_ids:
            raise ValueError(f"Duplicate node id: {node_id}.")

        node_ids.add(node_id)

        node_type = node.get("type")

        if node_type == WorkflowNodeType.SOURCE:
            if not node.get("dataset_id"):
                raise ValueError(f"Source node '{node_id}' requires a 'dataset_id'.")

            if not Dataset.objects.filter(
                pk=node["dataset_id"], dataset_node__user=user
            ).exists():
                raise ValueError(f"Source node '{node_id}' references an unknown dataset.")

        elif node_type == WorkflowNodeType.OPERATION:
            tool_name = node.get("tool_name")

            if not tool_name:
                raise ValueError(f"Operation node '{node_id}' requires a 'tool_name'.")

            try:
                tool = get_tool(tool_name)
            except ValueError as exc:
                raise ValueError(f"Operation node '{node_id}': {exc}") from exc

            try:
                tool.params_model.model_validate(node.get("params", {}) or {})
            except Exception as exc:
                raise ValueError(f"Operation node '{node_id}' has invalid params: {exc}") from exc

        else:
            raise ValueError(f"Node '{node_id}' has unknown type: {node_type!r}.")

    for edge in edges:
        if edge.get("source") not in node_ids or edge.get("target") not in node_ids:
            raise ValueError("Every edge must connect two existing node ids.")

    _topological_sort(nodes, edges)


def _topological_sort(nodes: list[dict], edges: list[dict]) -> list[str]:
    """Kahn's algorithm; raises ValueError if the graph contains a cycle."""

    node_ids = [node["id"] for node in nodes]
    in_degree = {node_id: 0 for node_id in node_ids}
    downstream: dict[str, list[str]] = {node_id: [] for node_id in node_ids}

    for edge in edges:
        downstream[edge["source"]].append(edge["target"])
        in_degree[edge["target"]] += 1

    queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
    ordered = []

    while queue:
        current = queue.pop(0)
        ordered.append(current)

        for target in downstream[current]:
            in_degree[target] -= 1

            if in_degree[target] == 0:
                queue.append(target)

    if len(ordered) != len(node_ids):
        raise ValueError("Workflow graph contains a cycle.")

    return ordered


def execute_workflow_run(run: WorkflowRun) -> None:
    """Execute every node of `run.workflow.definition` in topological order."""

    workflow = run.workflow
    user = workflow.user
    definition = workflow.definition or {}
    nodes = {node["id"]: node for node in definition.get("nodes", [])}
    edges = definition.get("edges", [])

    try:
        order = _topological_sort(list(nodes.values()), edges)
    except ValueError as exc:
        _fail_run(run, str(exc))
        return

    node_outputs: dict[str, Dataset] = {}
    failed = False

    for node_id in order:
        node = nodes[node_id]
        node_run, _ = WorkflowNodeRun.objects.update_or_create(
            run=run,
            node_id=node_id,
            defaults={"node_type": node["type"], "status": WorkflowNodeStatus.PENDING},
        )

        if failed:
            node_run.status = WorkflowNodeStatus.SKIPPED
            node_run.save(update_fields=["status", "updated_at"])
            _notify_node(run, node_run)
            continue

        node_run.status = WorkflowNodeStatus.RUNNING
        node_run.started_at = timezone.now()
        node_run.save(update_fields=["status", "started_at", "updated_at"])
        _notify_node(run, node_run)

        try:
            if node["type"] == WorkflowNodeType.SOURCE:
                dataset = Dataset.objects.get(pk=node["dataset_id"], dataset_node__user=user)
                node_outputs[node_id] = dataset

                node_run.status = WorkflowNodeStatus.COMPLETED
                node_run.output_dataset = dataset
                node_run.completed_at = timezone.now()
                node_run.save(
                    update_fields=["status", "output_dataset", "completed_at", "updated_at"]
                )
            else:
                inputs = _resolve_inputs(node_id, edges, node_outputs)

                if not inputs:
                    raise ValueError(f"Operation node '{node_id}' has no connected input.")

                tool = get_tool(node["tool_name"])
                validated_params = tool.params_model.model_validate(
                    node.get("params", {}) or {}
                ).model_dump()

                job = ProcessingJob.objects.create(
                    user=user,
                    tool_name=node["tool_name"],
                    parameters={**validated_params, "__output_name": f"{tool.label} ({node_id})"},
                    status=ProcessingJobStatus.PROCESSING,
                    started_at=timezone.now(),
                )
                job.input_datasets.set(inputs)
                node_run.processing_job = job
                node_run.save(update_fields=["processing_job", "updated_at"])

                execute_processing_job(job)

                if job.status != ProcessingJobStatus.COMPLETED:
                    raise ValueError(job.error_message or "Operation failed.")

                node_outputs[node_id] = job.output_dataset
                node_run.status = WorkflowNodeStatus.COMPLETED
                node_run.output_dataset = job.output_dataset
                node_run.completed_at = timezone.now()
                node_run.save(
                    update_fields=["status", "output_dataset", "completed_at", "updated_at"]
                )

        except Exception as exc:
            node_run.status = WorkflowNodeStatus.FAILED
            node_run.error_message = str(exc)[:2000]
            node_run.completed_at = timezone.now()
            node_run.save(
                update_fields=["status", "error_message", "completed_at", "updated_at"]
            )
            failed = True

        _notify_node(run, node_run)

    if failed:
        _fail_run(run, "One or more nodes failed. See node details.")
    else:
        run.status = WorkflowRunStatus.COMPLETED
        run.progress = 100
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "progress", "completed_at", "updated_at"])
        _notify_run(run)


def _resolve_inputs(
    node_id: str, edges: list[dict], node_outputs: dict[str, Dataset]
) -> list[Dataset]:
    upstream_ids = [edge["source"] for edge in edges if edge["target"] == node_id]

    return [node_outputs[source_id] for source_id in upstream_ids if source_id in node_outputs]


def _fail_run(run: WorkflowRun, message: str) -> None:
    run.status = WorkflowRunStatus.FAILED
    run.error_message = message[:2000]
    run.completed_at = timezone.now()
    run.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
    _notify_run(run)


def _publish(payload: dict, run: WorkflowRun) -> None:
    """Publish a status event. Delivery is best-effort: a broken notification
    transport must never abort the workflow that is being reported on."""

    try:
        send_notification(content=json.dumps(payload), user=run.workflow.user)
    except Exception:
        logger.exception("Failed to publish workflow status for run %s.", run.pk)


def _notify_node(run: WorkflowRun, node_run: WorkflowNodeRun) -> None:
    _publish(
        {
            "type": "workflow_node_status",
            "runId": str(run.pk),
            "workflowId": str(run.workflow_id),
            "nodeId": node_run.node_id,
            "status": node_run.status,
            "outputDatasetId": (
                str(node_run.output_dataset_id) if node_run.output_dataset_id else None
            ),
            "error": node_run.error_message,
        },
        run,
    )


def _notify_run(run: WorkflowRun) -> None:
    _publish(
        {
            "type": "workflow_run_status",
            "runId": str(run.pk),
            "workflowId": str(run.workflow_id),
            "status": run.status,
            "error": run.error_message,
        },
        run,
    )
