from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from shared.views import BaseModelViewSet

from .models import Employee, WorkItem
from .providers.registry import get_provider
from .serializers import EmployeeSerializer, WorkItemSerializer


class EmployeeViewSet(BaseModelViewSet):
    queryset = Employee.objects.order_by("name").all()
    serializer_class = EmployeeSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["get"], url_path="tree")
    def tree(self, request):
        """Return a flat employee list with computed load fields for the org chart."""
        employees = self.get_queryset().prefetch_related("work_items")
        serializer = EmployeeSerializer(employees, many=True)
        return Response({"data": serializer.data})

    @action(detail=True, methods=["get"], url_path="work-items")
    def work_items(self, request, pk=None):
        """Return active work items for an employee via the configured provider."""
        employee = self.get_object()
        provider = get_provider()
        items = provider.get_active_items(employee)
        serializer = WorkItemSerializer(items, many=True)
        return Response({"data": serializer.data})


class WorkItemViewSet(BaseModelViewSet):
    """CRUD for manual work items. Scoped to employees owned by the logged-in user."""

    queryset = WorkItem.objects.order_by("-created_at").all()
    serializer_class = WorkItemSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # WorkItem has no direct user FK — scope via the employee owner.
        return WorkItem.objects.filter(
            employee__user=self.request.user
        ).order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save()
