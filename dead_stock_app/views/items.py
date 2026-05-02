import csv
import io
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..models import Category, InventoryItem, ItemImage, Shop
from ..serializers import (
    ConfirmImageRequestSerializer,
    InventoryItemSerializer,
    ItemImageSerializer,
    PresignImageRequestSerializer,
)
from ..services.images import delete_object, presign_put
from ..tasks import generate_image_variants

logger = logging.getLogger(__name__)

CSV_REQUIRED_COLUMNS = {"name"}
CSV_ALLOWED_COLUMNS = {
    "name",
    "sku",
    "description",
    "quantity",
    "price",
    "condition",
    "status",
    "category",
    "category_id",
    "category_slug",
    "category_name",
}
CSV_CATEGORY_COLUMNS = ("category", "category_id", "category_slug", "category_name")
CSV_MAX_ROWS = 500


class InventoryItemViewSet(viewsets.ModelViewSet):
    """
    Owner-scoped CRUD on inventory items, plus image actions.
    """

    serializer_class = InventoryItemSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            InventoryItem.objects.filter(user=self.request.user)
            .select_related("shop", "category")
            .prefetch_related("images")
        )

    def perform_create(self, serializer):
        shop = Shop.objects.filter(user=self.request.user).first()
        if not shop:
            raise ValidationError("Create your shop before adding items.")
        serializer.save(user=self.request.user, shop=shop)

    def perform_destroy(self, instance):
        image_keys = list(instance.images.values_list("s3_key", flat=True))
        instance.delete()

        for image_key in image_keys:
            try:
                delete_object(image_key)
            except Exception:
                logger.exception(
                    "Failed to delete inventory item image from object storage",
                    extra={"item_id": str(instance.id), "s3_key": image_key},
                )

    @action(
        detail=False,
        methods=["post"],
        url_path="bulk-upload",
        parser_classes=[MultiPartParser, FormParser],
    )
    def bulk_upload(self, request):
        shop = Shop.objects.filter(user=request.user).first()
        if not shop:
            raise ValidationError("Create your shop before adding items.")

        upload = request.FILES.get("file")
        if not upload:
            raise ValidationError({"file": "Upload a CSV file."})
        if not upload.name.lower().endswith(".csv"):
            raise ValidationError({"file": "Only CSV files are supported."})

        try:
            text = upload.read().decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValidationError({"file": "CSV must be UTF-8 encoded."}) from exc

        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValidationError({"file": "CSV must include a header row."})

        headers = {header.strip() for header in reader.fieldnames if header}
        missing = CSV_REQUIRED_COLUMNS - headers
        if missing:
            missing_columns = ", ".join(sorted(missing))
            raise ValidationError(
                {"file": f"Missing required column(s): {missing_columns}."}
            )

        unexpected = headers - CSV_ALLOWED_COLUMNS
        if unexpected:
            raise ValidationError(
                {
                    "file": (
                        "Unsupported column(s): "
                        f"{', '.join(sorted(unexpected))}."
                    )
                }
            )

        categories = self._category_lookup()
        serializers = []
        row_errors = []

        for index, raw_row in enumerate(reader, start=2):
            if index > CSV_MAX_ROWS + 1:
                raise ValidationError(
                    {"file": f"CSV can include up to {CSV_MAX_ROWS} rows."}
                )

            row = {
                key.strip(): (value.strip() if isinstance(value, str) else value)
                for key, value in raw_row.items()
                if key
            }
            if not any(row.values()):
                continue

            data, category_error = self._csv_row_to_item_data(row, categories)
            if category_error:
                row_errors.append(
                    {"row": index, "errors": {"category": [category_error]}}
                )
                continue

            serializer = self.get_serializer(data=data)
            if serializer.is_valid():
                serializers.append(serializer)
            else:
                row_errors.append({"row": index, "errors": serializer.errors})

        if row_errors:
            return Response(
                {"created": 0, "errors": row_errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not serializers:
            raise ValidationError({"file": "CSV does not contain any item rows."})

        with transaction.atomic():
            items = [
                serializer.save(user=request.user, shop=shop)
                for serializer in serializers
            ]

        return Response(
            {
                "created": len(items),
                "items": self.get_serializer(items, many=True).data,
            },
            status=status.HTTP_201_CREATED,
        )

    def _category_lookup(self):
        categories = Category.objects.all()
        by_value = {}
        for category in categories:
            by_value[str(category.id).lower()] = category.id
            by_value[category.slug.lower()] = category.id
            by_value[category.name.lower()] = category.id
        return by_value

    def _csv_row_to_item_data(self, row, categories):
        data = {
            key: value
            for key, value in row.items()
            if key in CSV_ALLOWED_COLUMNS
            and key not in CSV_CATEGORY_COLUMNS
            and value not in (None, "")
        }

        category_value = next(
            (
                row.get(key)
                for key in CSV_CATEGORY_COLUMNS
                if row.get(key) not in (None, "")
            ),
            "",
        )
        if category_value:
            category_id = categories.get(str(category_value).lower())
            if not category_id:
                return data, f'Unknown category "{category_value}".'
            data["category"] = category_id

        return data, None

    @action(detail=True, methods=["post"])
    def refresh(self, request, pk=None):
        item = self.get_object()
        item.stale_at = timezone.now() + timedelta(days=30)
        item.save(update_fields=["stale_at", "updated_at"])
        return Response({"stale_at": item.stale_at})

    @action(detail=True, methods=["post"], url_path="images/presign")
    def presign_image(self, request, pk=None):
        item = self.get_object()
        serializer = PresignImageRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = presign_put(item.id, serializer.validated_data["content_type"])
        return Response(result)

    @action(detail=True, methods=["post"], url_path="images/confirm")
    def confirm_image(self, request, pk=None):
        item = self.get_object()
        serializer = ConfirmImageRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # If this is the first image or marked primary, demote any existing primary.
        is_primary = serializer.validated_data["is_primary"] or not item.images.exists()
        if is_primary:
            item.images.filter(is_primary=True).update(is_primary=False)

        next_position = (
            item.images.order_by("-position").values_list("position", flat=True).first()
        )
        position = (next_position or 0) + 1 if next_position is not None else 0

        image = ItemImage.objects.create(
            item=item,
            s3_key=serializer.validated_data["key"],
            width=serializer.validated_data["width"],
            height=serializer.validated_data["height"],
            position=position,
            is_primary=is_primary,
        )
        generate_image_variants.delay(str(image.id))
        return Response(
            ItemImageSerializer(image).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["patch"], url_path="images/reorder")
    def reorder_images(self, request, pk=None):
        item = self.get_object()
        ordered_ids = request.data.get("image_ids")
        if not isinstance(ordered_ids, list) or not ordered_ids:
            raise ValidationError(
                {"image_ids": "Provide a non-empty list of image ids."}
            )

        images = list(item.images.filter(id__in=ordered_ids))
        if len(images) != len(ordered_ids):
            raise NotFound("One or more images were not found.")

        image_by_id = {str(image.id): image for image in images}
        with transaction.atomic():
            for index, image_id in enumerate(ordered_ids):
                image = image_by_id[str(image_id)]
                image.position = index + 1000
                image.save(update_fields=["position", "updated_at"])
            for index, image_id in enumerate(ordered_ids):
                image = image_by_id[str(image_id)]
                image.position = index
                image.save(update_fields=["position", "updated_at"])

        return Response(ItemImageSerializer(item.images.all(), many=True).data)

    @action(
        detail=True,
        methods=["patch", "delete"],
        url_path=r"images/(?P<image_id>[0-9a-f-]{36})",
    )
    def image_detail(self, request, pk=None, image_id=None):
        item = self.get_object()
        try:
            image = item.images.get(pk=image_id)
        except ItemImage.DoesNotExist as exc:
            raise NotFound("Image not found.") from exc

        if request.method == "PATCH":
            is_primary = request.data.get("is_primary")
            position = request.data.get("position")

            with transaction.atomic():
                if is_primary is not None:
                    if not isinstance(is_primary, bool):
                        raise ValidationError({"is_primary": "Expected a boolean."})
                    if is_primary:
                        item.images.exclude(pk=image.pk).update(is_primary=False)
                    image.is_primary = is_primary

                if position is not None:
                    if not isinstance(position, int) or position < 0:
                        raise ValidationError(
                            {"position": "Expected a non-negative integer."}
                        )
                    image.position = position

                image.save(update_fields=["is_primary", "position", "updated_at"])

            return Response(ItemImageSerializer(image).data)

        was_primary = image.is_primary
        delete_object(image.s3_key)
        image.delete()

        if was_primary:
            replacement = item.images.order_by("position").first()
            if replacement:
                replacement.is_primary = True
                replacement.save(update_fields=["is_primary", "updated_at"])

        return Response(status=status.HTTP_204_NO_CONTENT)
