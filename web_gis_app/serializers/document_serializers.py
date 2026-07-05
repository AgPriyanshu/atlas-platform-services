from rest_framework import serializers

from shared.models.rag_models import Document


class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = [
            "id",
            "title",
            "file_name",
            "file_size",
            "status",
            "page_count",
            "error_message",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class DocumentSearchSerializer(serializers.Serializer):
    query = serializers.CharField(min_length=1, max_length=1000)
    top_k = serializers.IntegerField(default=5, min_value=1, max_value=20)


class DocumentSearchResultSerializer(serializers.Serializer):
    chunk_id = serializers.UUIDField()
    document_id = serializers.UUIDField()
    document_title = serializers.CharField()
    page_number = serializers.IntegerField(allow_null=True)
    chunk_index = serializers.IntegerField()
    text = serializers.CharField()
    distance = serializers.FloatField()
