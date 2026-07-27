"""Celery tasks for the web_gis_app module."""

import logging
import tempfile

from celery import shared_task
from django.utils import timezone

from shared.infrastructure import InfraManager

from .constants import ProcessingJobStatus, TileSetStatus, WorkflowRunStatus
from .models import Dataset, ProcessingJob, TileSet, WorkflowRun
from .workflows.cog_workflow import COGWorkflow
from .workflows.dag_executor import execute_workflow_run
from .workflows.job_executor import execute_processing_job

logger = logging.getLogger(__name__)




@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def generate_cog_task(self, dataset_id: str):
    """
    Background task to generate a tile-ready COG from an uploaded orthomosaic.

    Creates a TileSet record, runs the COGWorkflow, and marks the tileset
    as READY or FAILED depending on the outcome.
    """
    logger.info(f"Starting COG generation task for dataset_id: {dataset_id}")

    try:
        dataset = Dataset.objects.get(id=dataset_id)
        logger.info(f"Found dataset: {dataset.id}, type: {dataset.type}, path: {dataset.cloud_storage_path}")
    except Dataset.DoesNotExist:
        logger.error(f"Dataset {dataset_id} not found. Aborting COG generation.")
        return

    # Get or create the TileSet in PROCESSING state.
    tileset, created = TileSet.objects.update_or_create(
        dataset=dataset,
        defaults={"status": TileSetStatus.PROCESSING, "error_message": ""},
    )
    logger.info(f"TileSet {'created' if created else 'updated'} for processing: {tileset.id}")

    try:
        with tempfile.TemporaryDirectory(prefix="cog_") as work_dir:
            bucket = InfraManager.object_storage.default_bucket
            upload_key = f"tilesets/{tileset.id}/processed.tif"

            # Construct S3 URIs
            download_url = f"s3://{bucket}/{dataset.cloud_storage_path}"
            upload_url = f"s3://{bucket}/{upload_key}"

            logger.info(f"Preparing COG workflow. Download: {download_url}, Upload: {upload_url}")

            source_path = f"{work_dir}/source.tif"

            workflow = COGWorkflow(
                payload={
                    # Shared Download operation payload.
                    "download": {
                        "download_url": download_url,
                        "download_to_path": source_path,
                    },
                    # GenerateCOG uses the download output automatically.
                    "generate_cog": {
                        "input_path": source_path,
                        "work_dir": work_dir,
                    },
                    # Shared Upload operation payload.
                    "upload": {
                        "upload_url": upload_url,
                        "upload_from_path": f"{work_dir}/output.tif",
                    },
                    "update_tileset": {
                        "tileset_id": str(tileset.id),
                        "storage_path": upload_key,
                    },
                }
            )
            workflow.execute()

        logger.info(f"COG generation complete for dataset {dataset_id}.")

    except Exception as exc:
        logger.exception(f"COG generation failed for dataset {dataset_id}: {exc}")
        tileset.status = TileSetStatus.FAILED
        tileset.error_message = str(exc)[:2000]
        tileset.save(update_fields=["status", "error_message"])

        # Retry on transient errors.
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=1, default_retry_delay=120)
def run_processing_tool(self, job_id: str):
    """Run a geoprocessing tool configured by a ProcessingJob.

    Loads the job, dispatches the matching workflow, and keeps the job
    lifecycle + SSE progress stream in sync.
    """

    logger.info("Starting processing job %s", job_id)

    try:
        job = ProcessingJob.objects.select_related("user").get(pk=job_id)
    except ProcessingJob.DoesNotExist:
        logger.error("ProcessingJob %s not found.", job_id)
        return

    job.status = ProcessingJobStatus.PROCESSING
    job.started_at = timezone.now()
    job.celery_task_id = self.request.id or ""
    job.save(update_fields=["status", "started_at", "celery_task_id", "updated_at"])

    execute_processing_job(job)

    if job.status == ProcessingJobStatus.FAILED:
        logger.error("Processing job %s failed: %s", job_id, job.error_message)
    else:
        logger.info("Processing job %s completed.", job_id)


@shared_task(bind=True, max_retries=1, default_retry_delay=120)
def run_workflow(self, run_id: str):
    """Run a Workflow's DAG of source/operation nodes end to end.

    Loads the WorkflowRun, delegates node-by-node execution to the DAG
    executor, and keeps the run lifecycle in sync.
    """

    logger.info("Starting workflow run %s", run_id)

    try:
        run = WorkflowRun.objects.select_related("workflow", "workflow__user").get(pk=run_id)
    except WorkflowRun.DoesNotExist:
        logger.error("WorkflowRun %s not found.", run_id)
        return

    run.status = WorkflowRunStatus.RUNNING
    run.started_at = timezone.now()
    run.celery_task_id = self.request.id or ""
    run.save(update_fields=["status", "started_at", "celery_task_id", "updated_at"])

    try:
        execute_workflow_run(run)
    except Exception as exc:
        # Never leave a run orphaned in RUNNING if the executor itself breaks.
        logger.exception("Workflow run %s crashed: %s", run_id, exc)
        WorkflowRun.objects.filter(pk=run.pk).update(
            status=WorkflowRunStatus.FAILED,
            error_message=str(exc)[:2000],
            completed_at=timezone.now(),
        )

        return

    if run.status == WorkflowRunStatus.FAILED:
        logger.error("Workflow run %s failed: %s", run_id, run.error_message)
    else:
        logger.info("Workflow run %s completed.", run_id)
