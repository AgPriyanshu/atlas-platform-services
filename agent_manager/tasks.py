import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from .models import Message, MessageStatus

logger = logging.getLogger(__name__)

STALE_PENDING_THRESHOLD_MINUTES = 10


@shared_task
def cleanup_stale_pending_messages():
    """Mark messages that have been PENDING for too long as FAILED.

    A message stays PENDING while the consumer is streaming. If the consumer
    crashes before completing the stream, the row stays PENDING indefinitely.
    This task detects those orphaned rows and marks them FAILED so they don't
    pollute session history.
    """
    cutoff = timezone.now() - timedelta(minutes=STALE_PENDING_THRESHOLD_MINUTES)

    updated = Message.objects.filter(
        status=MessageStatus.PENDING,
        created_at__lt=cutoff,
    ).update(status=MessageStatus.FAILED)

    if updated:
        logger.info("Marked %d stale pending messages as FAILED.", updated)
