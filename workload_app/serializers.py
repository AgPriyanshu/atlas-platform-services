from rest_framework import serializers

from shared.serializers import BaseModelSerializer

from .models import Employee, WorkItem
from .services.workload import compute_load


class WorkItemSerializer(BaseModelSerializer):
    class Meta:
        model = WorkItem
        fields = (
            "id",
            "employee",
            "title",
            "status",
            "external_key",
            "url",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class EmployeeSerializer(BaseModelSerializer):
    active_task_count = serializers.IntegerField(read_only=True, default=0)
    load_ratio = serializers.FloatField(read_only=True, default=0.0)
    load_status = serializers.CharField(read_only=True, default="UNDER")

    class Meta:
        model = Employee
        fields = (
            "id",
            "name",
            "email",
            "designation",
            "capacity",
            "manager",
            "account",
            "active_task_count",
            "load_ratio",
            "load_status",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def to_representation(self, instance):
        load = compute_load(instance)
        instance.active_task_count = load.active_count
        instance.load_ratio = load.ratio
        instance.load_status = load.status
        return super().to_representation(instance)
