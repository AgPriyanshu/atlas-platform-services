from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CategoryViewSet,
    InventoryItemViewSet,
    LeadCreateView,
    LeadInboxView,
    LeadMarkContactedView,
    OTPRequestView,
    OTPVerifyView,
    RefreshTokenView,
    ReportCreateView,
    SearchAutocompleteView,
    SearchItemsView,
    ShopViewSet,
    ping,
)

router = DefaultRouter()
router.register(r"shops", ShopViewSet, basename="ds-shops")
router.register(r"items", InventoryItemViewSet, basename="ds-items")
router.register(r"categories", CategoryViewSet, basename="ds-categories")

urlpatterns = [
    path("ping/", ping, name="dead-stock-ping"),
    path("auth/otp/request/", OTPRequestView.as_view(), name="ds-otp-request"),
    path("auth/otp/verify/", OTPVerifyView.as_view(), name="ds-otp-verify"),
    path("auth/refresh/", RefreshTokenView.as_view(), name="ds-refresh"),
    path("search/items/", SearchItemsView.as_view(), name="ds-search-items"),
    path("search/autocomplete/", SearchAutocompleteView.as_view(), name="ds-search-autocomplete"),
    path("leads/", LeadCreateView.as_view(), name="ds-leads-create"),
    path("leads/inbox/", LeadInboxView.as_view(), name="ds-leads-inbox"),
    path("leads/<uuid:pk>/contacted/", LeadMarkContactedView.as_view(), name="ds-leads-contacted"),
    path("reports/", ReportCreateView.as_view(), name="ds-reports-create"),
    path("", include(router.urls)),
]
