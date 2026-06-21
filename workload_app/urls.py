from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import EmployeeViewSet, WorkItemViewSet

router = DefaultRouter()
router.register(r"employees", EmployeeViewSet, basename="employees")
router.register(r"work-items", WorkItemViewSet, basename="work-items")

urlpatterns = [path("", include(router.urls))]
