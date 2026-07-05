from pgvector.django import CosineDistance


def retrieve_chunks(query: str, user, top_k: int = 5):
    from langchain_ollama import OllamaEmbeddings

    from shared.models.rag_models import DocumentChunk, DocumentStatus

    embeddings = OllamaEmbeddings(
        model="all-minilm", base_url="http://host.docker.internal:11434"
    )
    vec = embeddings.embed_query(query)

    return (
        DocumentChunk.objects.filter(
            document__user=user,
            document__status=DocumentStatus.READY,
        )
        .annotate(distance=CosineDistance("embedding", vec))
        .order_by("distance")
        .select_related("document")[:top_k]
    )
