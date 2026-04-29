import os
import re

from django.contrib.gis.geos import Point
from rest_framework import serializers

from .models import Category, InventoryItem, ItemImage, Lead, Report, Shop

# Indian mobile: starts with 6-9 followed by 9 digits, prefixed with +91.
PHONE_REGEX = re.compile(r"^\+91[6-9]\d{9}$")


def _validate_phone(value: str) -> str:
    value = (value or "").strip()
    if not PHONE_REGEX.match(value):
        raise serializers.ValidationError(
            "Phone must be a valid Indian mobile, e.g. +919876543210."
        )
    return value


class OTPRequestSerializer(serializers.Serializer):
    phone = serializers.CharField()

    def validate_phone(self, value):
        return _validate_phone(value)


class OTPVerifySerializer(serializers.Serializer):
    phone = serializers.CharField()
    otp = serializers.RegexField(regex=r"^\d{6}$")

    def validate_phone(self, value):
        return _validate_phone(value)


class RefreshTokenSerializer(serializers.Serializer):
    token = serializers.CharField()


# ---------------------------------------------------------------------------
# Domain serializers
# ---------------------------------------------------------------------------


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ("id", "slug", "name", "parent")


class ShopSerializer(serializers.ModelSerializer):
    latitude = serializers.FloatField(write_only=True)
    longitude = serializers.FloatField(write_only=True)
    lat = serializers.SerializerMethodField()
    lng = serializers.SerializerMethodField()

    class Meta:
        model = Shop
        fields = (
            "id",
            "name",
            "address",
            "city",
            "pincode",
            "phone",
            "is_verified",
            "rating_avg",
            "lat",
            "lng",
            "latitude",
            "longitude",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "is_verified", "rating_avg", "created_at", "updated_at")

    def get_lat(self, obj):
        return obj.location.y if obj.location else None

    def get_lng(self, obj):
        return obj.location.x if obj.location else None

    def validate(self, attrs):
        if "latitude" in attrs and "longitude" in attrs:
            attrs["location"] = Point(
                attrs.pop("longitude"), attrs.pop("latitude"), srid=4326
            )
        elif "latitude" in attrs or "longitude" in attrs:
            raise serializers.ValidationError(
                "Both latitude and longitude are required."
            )
        return attrs

    def to_internal_value(self, data):
        # Validate phone with same regex used elsewhere when present.
        if data.get("phone"):
            _validate_phone(data["phone"])
        return super().to_internal_value(data)


class ShopWithDistanceSerializer(ShopSerializer):
    distance_m = serializers.SerializerMethodField()

    class Meta(ShopSerializer.Meta):
        fields = ShopSerializer.Meta.fields + ("distance_m",)

    def get_distance_m(self, obj):
        d = getattr(obj, "distance", None)
        return round(d.m, 1) if d else None


class ItemImageSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    thumb_url = serializers.SerializerMethodField()
    card_url = serializers.SerializerMethodField()

    class Meta:
        model = ItemImage
        fields = (
            "id",
            "position",
            "is_primary",
            "variants_ready",
            "width",
            "height",
            "url",
            "thumb_url",
            "card_url",
            "created_at",
        )
        read_only_fields = fields

    def _public_base(self):
        return os.environ.get("S3_PUBLIC_ENDPOINT", "").rstrip("/")

    def _bucket(self):
        return os.environ.get("S3_BUCKET", "")

    def _build(self, key):
        base = self._public_base()
        bucket = self._bucket()
        if not (base and bucket and key):
            return None
        return f"{base}/{bucket}/{key}"

    def _variant_key(self, obj, size):
        # variants live alongside the original under /variants/<size>.webp
        # original key: dead-stock/items/<id>/originals/<uuid>.<ext>
        prefix = obj.s3_key.rsplit("/originals/", 1)[0]
        return f"{prefix}/variants/{size}.webp"

    def get_url(self, obj):
        return self._build(obj.s3_key)

    def get_thumb_url(self, obj):
        return self._build(self._variant_key(obj, "thumb_200")) if obj.variants_ready else None

    def get_card_url(self, obj):
        return self._build(self._variant_key(obj, "card_600")) if obj.variants_ready else None


class InventoryItemSerializer(serializers.ModelSerializer):
    images = ItemImageSerializer(many=True, read_only=True)
    shop_name = serializers.CharField(source="shop.name", read_only=True)

    class Meta:
        model = InventoryItem
        fields = (
            "id",
            "shop",
            "shop_name",
            "category",
            "name",
            "sku",
            "description",
            "quantity",
            "price",
            "condition",
            "status",
            "stale_at",
            "images",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "shop", "shop_name", "stale_at", "images", "created_at", "updated_at")


class SearchItemSerializer(InventoryItemSerializer):
    distance_m = serializers.SerializerMethodField()
    shop_lat = serializers.SerializerMethodField()
    shop_lng = serializers.SerializerMethodField()
    shop_phone = serializers.CharField(source="shop.phone", read_only=True)
    category_slug = serializers.SlugRelatedField(
        source="category", slug_field="slug", read_only=True
    )

    class Meta(InventoryItemSerializer.Meta):
        fields = InventoryItemSerializer.Meta.fields + (
            "distance_m",
            "shop_lat",
            "shop_lng",
            "shop_phone",
            "category_slug",
        )

    def get_distance_m(self, obj):
        d = getattr(obj, "distance", None)
        return round(d.m, 1) if d is not None else None

    def get_shop_lat(self, obj):
        loc = obj.shop.location if obj.shop else None
        return loc.y if loc else None

    def get_shop_lng(self, obj):
        loc = obj.shop.location if obj.shop else None
        return loc.x if loc else None


class PresignImageRequestSerializer(serializers.Serializer):
    content_type = serializers.RegexField(regex=r"^image/(jpeg|png|webp)$")


class ConfirmImageRequestSerializer(serializers.Serializer):
    key = serializers.CharField()
    width = serializers.IntegerField(min_value=1)
    height = serializers.IntegerField(min_value=1)
    is_primary = serializers.BooleanField(default=False)


class LeadSerializer(serializers.ModelSerializer):
    buyer_name = serializers.SerializerMethodField()
    buyer_phone = serializers.SerializerMethodField()
    item_name = serializers.SerializerMethodField()

    class Meta:
        model = Lead
        fields = (
            "id",
            "buyer",
            "buyer_name",
            "buyer_phone",
            "shop",
            "item",
            "item_name",
            "message",
            "contacted_at",
            "created_at",
        )
        read_only_fields = fields

    def get_buyer_name(self, obj):
        return obj.buyer.first_name or obj.buyer.username

    def get_buyer_phone(self, obj):
        username = obj.buyer.username
        if username.startswith("ds-buyer-"):
            return username[len("ds-buyer-"):]
        return None

    def get_item_name(self, obj):
        return obj.item.name if obj.item else None


class CreateLeadSerializer(serializers.Serializer):
    shop_id = serializers.UUIDField()
    item_id = serializers.UUIDField(required=False, allow_null=True)
    message = serializers.CharField(min_length=5, max_length=1000)
    phone = serializers.CharField(required=False, allow_blank=True)
    buyer_name = serializers.CharField(
        required=False, allow_blank=True, max_length=120
    )

    def validate_phone(self, value):
        return _validate_phone(value) if value else value


class CreateReportSerializer(serializers.Serializer):
    shop_id = serializers.UUIDField(required=False, allow_null=True)
    item_id = serializers.UUIDField(required=False, allow_null=True)
    reason = serializers.CharField(min_length=5, max_length=1000)


class ReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Report
        fields = ("id", "shop", "item", "reason", "status", "created_at")
        read_only_fields = fields
