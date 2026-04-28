import io
import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone
from PIL import Image

from shared.infrastructure import InfraManager

logger = logging.getLogger(__name__)

VARIANT_SIZES = {
    "thumb_200": 200,
    "card_600": 600,
    "full_1600": 1600,
}


def _variant_key(original_key: str, size_name: str) -> str:
    prefix = original_key.rsplit("/originals/", 1)[0]
    return f"{prefix}/variants/{size_name}.webp"


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def generate_image_variants(self, item_image_id: str):
    from .models import ItemImage

    try:
        image_record = ItemImage.objects.get(pk=item_image_id)
    except ItemImage.DoesNotExist:
        logger.warning("ItemImage %s not found, skipping variants.", item_image_id)
        return

    try:
        raw = InfraManager.object_storage.download_object(key=image_record.s3_key)
        original = Image.open(raw).convert("RGB")

        for size_name, max_px in VARIANT_SIZES.items():
            variant = original.copy()
            variant.thumbnail((max_px, max_px), Image.LANCZOS)

            buf = io.BytesIO()
            variant.save(buf, format="WEBP", quality=85, method=6)
            buf.seek(0)

            key = _variant_key(image_record.s3_key, size_name)
            InfraManager.object_storage.upload_object(
                file=buf,
                key=key,
                metadata={"Content-Type": "image/webp"},
            )

        image_record.variants_ready = True
        image_record.save(update_fields=["variants_ready", "updated_at"])
        logger.info("Variants ready for ItemImage %s.", item_image_id)

    except Exception as exc:
        logger.exception("Failed to generate variants for ItemImage %s.", item_image_id)
        raise self.retry(exc=exc)


@shared_task
def sweep_stale_items():
    """Hide inventory items that have not been refreshed in 60 days."""
    from .models import InventoryItem

    cutoff = timezone.now() - timedelta(days=30)
    ids_to_hide = list(
        InventoryItem.objects.filter(
            stale_at__lt=cutoff,
            status=InventoryItem.Status.ACTIVE,
        )
        .values_list("pk", flat=True)
        .iterator(chunk_size=500)
    )

    if ids_to_hide:
        InventoryItem.objects.filter(pk__in=ids_to_hide).update(
            status=InventoryItem.Status.HIDDEN
        )
        logger.info("Stale sweep: hid %d items.", len(ids_to_hide))

    return f"Hidden {len(ids_to_hide)} stale items."
