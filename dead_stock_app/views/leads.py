from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import InventoryItem, Lead, Report, Shop
from ..serializers import (
    CreateLeadSerializer,
    CreateReportSerializer,
    LeadSerializer,
    ReportSerializer,
)


def _anonymous_user_for_phone(phone: str, buyer_name: str = "") -> User:
    username = f"ds-buyer-{phone}"
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={
            "first_name": buyer_name[:150],
            "is_active": False,
        },
    )
    if buyer_name and not user.first_name:
        user.first_name = buyer_name[:150]
        user.save(update_fields=["first_name"])
    return user


class LeadCreateView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = CreateLeadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            shop = Shop.objects.get(pk=data["shop_id"])
        except Shop.DoesNotExist as exc:
            raise NotFound("Shop not found.") from exc

        item = None
        if data.get("item_id"):
            try:
                item = shop.items.get(pk=data["item_id"])
            except InventoryItem.DoesNotExist as exc:
                raise NotFound("Item not found for this shop.") from exc

        if request.user.is_authenticated:
            buyer = request.user
        else:
            phone = data.get("phone")
            if not phone:
                raise ValidationError({"phone": "Phone is required."})
            buyer = _anonymous_user_for_phone(phone, data.get("buyer_name", ""))

        lead = Lead.objects.create(
            buyer=buyer,
            shop=shop,
            item=item,
            message=data["message"],
            contacted_at=timezone.now(),
        )
        return Response(LeadSerializer(lead).data, status=status.HTTP_201_CREATED)


class LeadInboxView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        shop = Shop.objects.filter(user=request.user).first()
        if not shop:
            raise PermissionDenied("Create a shop before viewing leads.")

        leads = (
            Lead.objects.filter(shop=shop)
            .select_related("buyer", "item", "shop")
            .order_by("-created_at")[:100]
        )
        return Response(LeadSerializer(leads, many=True).data)


class LeadMarkContactedView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        shop = Shop.objects.filter(user=request.user).first()

        if not shop:
            raise PermissionDenied("Create a shop before managing leads.")

        try:
            lead = Lead.objects.select_related("buyer", "item", "shop").get(
                pk=pk, shop=shop
            )
        except Lead.DoesNotExist as exc:
            raise NotFound("Lead not found.") from exc

        lead.contacted_at = timezone.now()
        lead.save(update_fields=["contacted_at", "updated_at"])
        return Response(LeadSerializer(lead).data)


class ReportCreateView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = CreateReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        shop = None
        item = None
        if data.get("shop_id"):
            shop = Shop.objects.filter(pk=data["shop_id"]).first()
        if data.get("item_id"):
            item = InventoryItem.objects.filter(pk=data["item_id"]).first()

        if not shop and not item:
            raise ValidationError("Report must target a shop or item.")

        reporter = request.user if request.user.is_authenticated else None
        if reporter is None:
            reporter, _ = User.objects.get_or_create(
                username="ds-anonymous-reporter",
                defaults={"is_active": False},
            )

        report = Report.objects.create(
            reporter=reporter,
            shop=shop,
            item=item,
            reason=data["reason"],
        )
        return Response(
            ReportSerializer(report).data, status=status.HTTP_201_CREATED
        )
