import logging

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from shared.infrastructure import InfraManager
from shared.models.rag_models import Document, DocumentStatus
from shared.rag.retrieval import retrieve_chunks
from shared.rag.tasks import process_document_task
from shared.views import BaseModelViewSet

from ..serializers.document_serializers import (
    DocumentSearchResultSerializer,
    DocumentSearchSerializer,
    DocumentSerializer,
)

logger = logging.getLogger(__name__)

_DOCUMENT_STORAGE_PREFIX = "documents"
_MAX_FILE_SIZE_MB = 100


def _build_storage_key(document_id: str, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "pdf"
    return f"{_DOCUMENT_STORAGE_PREFIX}/{document_id}/file.{ext}"


class DocumentViewSet(BaseModelViewSet):
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer
    permission_classes = [IsAuthenticated]

    def create(self, request):
        file = request.FILES.get("file")

        if file is None:
            return Response(
                {"error": "A PDF file is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not file.name.lower().endswith(".pdf"):
            return Response(
                {"error": "Only PDF files are supported."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if file.size > _MAX_FILE_SIZE_MB * 1024 * 1024:
            return Response(
                {"error": f"File exceeds the {_MAX_FILE_SIZE_MB} MB limit."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        title = request.data.get("title") or file.name.removesuffix(".pdf")

        document = Document.objects.create(
            user=request.user,
            title=title,
            file_name=file.name,
            file_size=file.size,
            cloud_storage_path="",
            status=DocumentStatus.PENDING,
        )

        try:
            cloud_path = _build_storage_key(str(document.id), file.name)
            InfraManager.object_storage.upload_object(
                file=file,
                key=cloud_path,
                metadata={"document_id": str(document.id)},
            )
            document.cloud_storage_path = cloud_path
            document.save(update_fields=["cloud_storage_path"])
        except Exception:
            logger.exception("Failed to upload document %s to storage.", document.id)
            document.status = DocumentStatus.FAILED
            document.error_message = "File upload to storage failed."
            document.save(update_fields=["status", "error_message"])
            return Response(
                {"error": "Storage upload failed."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        process_document_task.delay(str(document.id))

        return Response(
            DocumentSerializer(document).data,
            status=status.HTTP_201_CREATED,
        )

    def destroy(self, request, *args, **kwargs):
        document = self.get_object()
        cloud_path = document.cloud_storage_path

        document.chunks.all().delete()
        document.delete()

        if cloud_path:
            try:
                InfraManager.object_storage.delete_object(key=cloud_path)
            except Exception:
                logger.warning("Could not delete storage object %s.", cloud_path)

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["post"], url_path="search")
    def search(self, request):
        serializer = DocumentSearchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        query = serializer.validated_data["query"]
        top_k = serializer.validated_data["top_k"]

        chunks = retrieve_chunks(query=query, user=request.user, top_k=top_k)

        results = [
            {
                "chunk_id": str(chunk.id),
                "document_id": str(chunk.document.id),
                "document_title": chunk.document.title,
                "page_number": chunk.page_number,
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
                "distance": float(chunk.distance),
            }
            for chunk in chunks
        ]

        return Response(DocumentSearchResultSerializer(results, many=True).data)
