import json
import logging

import redis
from django.conf import settings

logger = logging.getLogger(__name__)

_redis = redis.from_url(
    settings.CACHES["default"]["LOCATION"],
    decode_responses=True,
)

NEARBY_TTL = 60
CATEGORIES_TTL = 3600


def _nearby_key(lat: float, lng: float, radius_km: float) -> str:
    return f"ds:nearby:{round(lat, 3)}:{round(lng, 3)}:{radius_km}"


def nearby_cache_get(lat: float, lng: float, radius_km: float):
    try:
        raw = _redis.get(_nearby_key(lat, lng, radius_km))
        return json.loads(raw) if raw else None
    except Exception:
        logger.exception("nearby_cache_get failed.")
        return None


def nearby_cache_set(lat: float, lng: float, radius_km: float, data) -> None:
    try:
        _redis.setex(_nearby_key(lat, lng, radius_km), NEARBY_TTL, json.dumps(data))
    except Exception:
        logger.exception("nearby_cache_set failed.")


def nearby_cache_invalidate_all() -> None:
    try:
        keys = _redis.keys("ds:nearby:*")

        if keys:
            _redis.delete(*keys)
    except Exception:
        logger.exception("nearby_cache_invalidate_all failed.")
