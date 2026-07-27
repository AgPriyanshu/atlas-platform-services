"""Shared execution logic for a single ProcessingJob.

Used by the `run_processing_tool` Celery task (one-off tool runs) and by the
workflow DAG executor (one ProcessingJob per operation node), so both paths
go through the exact same tool_registry/payload-building/progress-reporting
code.
"""

import re
import tempfile

from django.utils import timezone

from shared.infrastructure import InfraManager

from ..constants import DatasetType, FileFormat, ProcessingJobStatus
from ..models import ProcessingJob
from ..progress import ProgressReporter
from ..tool_registry import get_tool, load_workflow_class


def execute_processing_job(job: ProcessingJob) -> None:
    """Run the job's tool to completion, updating status/progress in place.

    Mutates and saves `job` directly; callers can inspect `job.status` /
    `job.output_dataset` afterwards without re-fetching.
    """

    reporter = ProgressReporter(job=job, user=job.user)
    reporter.report(0, "Starting...")

    try:
        tool = get_tool(job.tool_name)
        workflow_cls = load_workflow_class(job.tool_name)
        payload = _build_workflow_payload(job, tool)

        workflow = workflow_cls(payload=payload)
        workflow.ctx["progress_reporter"] = reporter
        workflow.execute()

        # CreateOutputDataset fetches and saves its own ProcessingJob instance,
        # so `job.output_dataset`/`output_node` on this object are stale until refreshed.
        job.refresh_from_db(fields=["output_dataset", "output_node"])

        job.status = ProcessingJobStatus.COMPLETED
        job.completed_at = timezone.now()
        job.progress = 100
        job.save(update_fields=["status", "completed_at", "progress", "updated_at"])

        output_id = str(job.output_dataset_id) if job.output_dataset_id else None
        reporter.complete(output_dataset_id=output_id)

    except Exception as exc:
        job.status = ProcessingJobStatus.FAILED
        job.completed_at = timezone.now()
        job.error_message = str(exc)[:2000]
        job.save(update_fields=["status", "completed_at", "error_message", "updated_at"])

        reporter.fail(job.error_message)


def _build_workflow_payload(job: ProcessingJob, tool) -> dict:
    """Compose the dict payload each workflow expects, keyed by operation name."""

    input_datasets = list(job.input_datasets.all())

    if not input_datasets:
        raise ValueError("ProcessingJob requires at least one input dataset.")

    primary_input = input_datasets[0]
    params = dict(job.parameters or {})

    output_parent_id = params.pop("__output_parent_id", None)
    output_name = params.pop("__output_name", None) or f"{tool.label}"

    category = tool.category.value
    output_type = tool.output_type
    output_format = (
        FileFormat.COG.value
        if output_type == DatasetType.RASTER.value
        else FileFormat.GEOPACKAGE.value
    )

    create_output_payload = {
        "job_id": str(job.pk),
        "output_name": output_name,
        "output_parent_id": output_parent_id,
        "output_type": output_type,
        "output_format": output_format,
    }

    if category == "vector":
        # Vector workflows: first op is the vector op, then CreateOutputDataset.
        first_op_name = tool.workflow_path.rsplit(".", 1)[-1].replace("Workflow", "Op")
        first_op_key = _camel_to_snake(first_op_name)
        first_op_payload = {
            "job_id": str(job.pk),
            "input_dataset_id": str(primary_input.id),
            **params,
        }

        return {
            first_op_key: first_op_payload,
            "create_output_dataset": create_output_payload,
        }

    # Raster workflows: Download -> <op> -> (ExtractRasterMetadata) -> (Upload) -> CreateOutputDataset.
    bucket = InfraManager.object_storage.default_bucket
    download_url = f"s3://{bucket}/{primary_input.cloud_storage_path}"
    work_dir = tempfile.mkdtemp(prefix=f"job_{job.pk}_")
    source_path = f"{work_dir}/source.tif"
    output_path = f"{work_dir}/output.tif"

    first_op_name = tool.workflow_path.rsplit(".", 1)[-1].replace("Workflow", "Op")
    first_op_key = _camel_to_snake(first_op_name)
    first_op_payload = {
        "job_id": str(job.pk),
        "input_path": source_path,
        "work_dir": work_dir,
        **params,
    }

    payload = {
        "download": {
            "download_url": download_url,
            "download_to_path": source_path,
        },
        first_op_key: first_op_payload,
        "create_output_dataset": create_output_payload,
    }

    if output_type == DatasetType.RASTER.value:
        upload_key = f"processing/{job.pk}/output.tif"
        upload_url = f"s3://{bucket}/{upload_key}"

        payload["extract_raster_metadata"] = {"path": output_path}
        payload["upload"] = {
            "upload_url": upload_url,
            "upload_from_path": output_path,
        }
        create_output_payload["storage_path"] = upload_key

    return payload


def _camel_to_snake(name: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)

    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()
