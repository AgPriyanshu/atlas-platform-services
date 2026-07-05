from django.db import models
from pgvector.django import HnswIndex, VectorField

from .base_models import BaseModel, BaseModelWithoutUser


class DocumentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"


class Document(BaseModel):
    title = models.TextField()
    file_name = models.CharField(max_length=255)
    file_size = models.BigIntegerField(default=0)
    cloud_storage_path = models.CharField(max_length=500)
    status = models.CharField(
        max_length=20,
        choices=DocumentStatus.choices,
        default=DocumentStatus.PENDING,
    )
    page_count = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True, default="")

    class Meta:
        db_table = "document"
        ordering = ["-created_at"]


class DocumentChunk(BaseModelWithoutUser):
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="chunks",
    )
    chunk_index = models.IntegerField()
    page_number = models.IntegerField(null=True, blank=True)
    text = models.TextField()
    embedding = VectorField(dimensions=384)

    class Meta:
        db_table = "document_chunk"
        ordering = ["document", "chunk_index"]
        indexes = [
            HnswIndex(
                fields=["embedding"],
                name="doc_chunk_embedding_hnsw_idx",
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            )
        ]
