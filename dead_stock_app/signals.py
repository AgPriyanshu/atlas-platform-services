import json
import logging
import unicodedata
from datetime import timedelta

import redis
from django.conf import settings
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from shared.utils.redis import get_notifications_channel

from .models import InventoryItem, Lead

logger = logging.getLogger(__name__)

_redis_client = redis.from_url(
    settings.CACHES["default"]["LOCATION"],
    decode_responses=True,
)


def normalize_name(text: str) -> str:
    """Lowercase + strip diacritics so trigram search matches across scripts."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c)).strip()


@receiver(pre_save, sender=InventoryItem)
def fill_normalized_and_stale(sender, instance, **kwargs):
    if instance.name:
        instance.name_normalized = normalize_name(instance.name)

    if not instance.stale_at:
        instance.stale_at = timezone.now() + timedelta(days=30)


@receiver(post_save, sender=Lead)
def notify_shop_owner_on_lead(sender, instance, created, **kwargs):
    if not created:
        return

    try:
        owner = instance.shop.user
        channel = get_notifications_channel(owner)
        payload = {
            "type": "dead_stock.lead_created",
            "lead_id": str(instance.pk),
            "shop_id": str(instance.shop_id),
            "buyer_name": instance.buyer.first_name or instance.buyer.username,
        }
        _redis_client.publish(channel, json.dumps(payload))
    except Exception:
        logger.exception("Failed to publish lead SSE event for lead %s.", instance.pk)
