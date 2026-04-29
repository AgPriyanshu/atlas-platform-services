import logging
import os

from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from ..models import Category, InventoryItem
from ..serializers import SearchItemSerializer
from ..services.search import build_search_qs, log_search

logger = logging.getLogger(__name__)


def _float_or_none(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


class SearchItemsView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ds_search_anon"

    def get(self, request: Request):
        q = request.query_params.get("q", "").strip()
        lat = _float_or_none(request.query_params.get("lat"))
        lng = _float_or_none(request.query_params.get("lng"))
        radius_km = float(request.query_params.get("radius_km", 10))
        category_slug = request.query_params.get("category", "")
        min_price = _float_or_none(request.query_params.get("min_price"))
        max_price = _float_or_none(request.query_params.get("max_price"))
        sort = request.query_params.get("sort", "distance")
        cursor = request.query_params.get("cursor", "")
        limit = min(int(request.query_params.get("limit", 20)), 100)

        items, next_cursor = build_search_qs(
            q=q,
            lat=lat,
            lng=lng,
            radius_km=radius_km,
            category_slug=category_slug,
            min_price=min_price,
            max_price=max_price,
            sort=sort,
            cursor=cursor,
            limit=limit,
        )

        log_search(
            query=q,
            result_count=len(items),
            lat=lat,
            lng=lng,
            user=request.user,
        )

        return Response(
            {
                "items": SearchItemSerializer(items, many=True).data,
                "next_cursor": next_cursor,
            }
        )


class SearchAutocompleteView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ds_search_anon"

    def _thumb_url(self, s3_key: str) -> str | None:
        base = os.environ.get("S3_PUBLIC_ENDPOINT", "").rstrip("/")
        bucket = os.environ.get("S3_BUCKET", "")

        if not (base and bucket and s3_key):
            return None

        prefix = s3_key.rsplit("/originals/", 1)[0]
        return f"{base}/{bucket}/{prefix}/variants/thumb_200.webp"

    def get(self, request: Request):
        q = request.query_params.get("q", "").strip()

        if len(q) < 2:
            return Response({"suggestions": []})

        items = (
            InventoryItem.objects.filter(
                name__icontains=q,
                status=InventoryItem.Status.ACTIVE,
            )
            .prefetch_related("images")
            .distinct()[:8]
        )

        category_names = list(
            Category.objects.filter(name__icontains=q).values_list("name", flat=True)[:4]
        )

        seen: set[str] = set()
        suggestions: list[dict] = []

        for item in items:
            key = item.name.lower()

            if key not in seen:
                seen.add(key)
                images = list(item.images.all())
                primary = next((img for img in images if img.is_primary), images[0] if images else None)
                thumbnail = self._thumb_url(primary.s3_key) if primary and primary.variants_ready else None
                suggestions.append({"name": item.name, "thumbnail": thumbnail, "type": "item"})

            if len(suggestions) >= 8:
                break

        for name in category_names:
            key = name.lower()

            if key not in seen:
                seen.add(key)
                suggestions.append({"name": name, "thumbnail": None, "type": "category"})

            if len(suggestions) >= 10:
                break

        return Response({"suggestions": suggestions})
