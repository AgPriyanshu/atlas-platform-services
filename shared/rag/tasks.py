import json
import logging
import tempfile

from celery import shared_task

from shared.constants import AppName
from shared.infrastructure import InfraManager
from shared.notifications import send_notification

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def process_document_task(self, document_id: str):
    from shared.models.rag_models import Document, DocumentChunk, DocumentStatus

    try:
        document = Document.objects.select_related("user").get(id=document_id)
    except Document.DoesNotExist:
        logger.error("Document %s not found.", document_id)
        return

    document.status = DocumentStatus.PROCESSING
    document.save(update_fields=["status"])

    try:
        streaming_body = InfraManager.object_storage.download_object(
            key=document.cloud_storage_path
        )

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            for chunk in iter(lambda: streaming_body.read(8192), b""):
                tmp.write(chunk)
            tmp_path = tmp.name

        from docling.chunking import HybridChunker
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from langchain_ollama import OllamaEmbeddings
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        # Disable table structure model to avoid libxcb/OpenCV system dependency.
        pdf_options = PdfPipelineOptions()
        pdf_options.do_table_structure = False
        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options)}
        )
        result = converter.convert(source=tmp_path)
        doc = result.document

        chunker = HybridChunker()
        raw_chunks = list(chunker.chunk(dl_doc=doc))
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)

        chunk_texts = []
        chunk_meta = []

        for raw in raw_chunks:
            text = raw.text.strip()

            if not text:
                continue

            page = None
            prov = getattr(raw, "meta", None)

            if prov and hasattr(prov, "doc_items"):
                for item in prov.doc_items:
                    provs = getattr(item, "prov", [])

                    if provs:
                        page = provs[0].page_no
                        break

            sub_chunks = splitter.split_text(text)

            for sub in sub_chunks:
                chunk_texts.append(sub)
                chunk_meta.append(page)

        if not chunk_texts:
            raise ValueError("No text could be extracted from the document.")

        embeddings_client = OllamaEmbeddings(
            model="all-minilm", base_url="http://host.docker.internal:11434"
        )
        embeddings = embeddings_client.embed_documents(chunk_texts)

        chunks = [
            DocumentChunk(
                document=document,
                chunk_index=i,
                page_number=chunk_meta[i],
                text=chunk_texts[i],
                embedding=embeddings[i],
            )
            for i in range(len(chunk_texts))
        ]
        DocumentChunk.objects.bulk_create(chunks, batch_size=200)

        page_count = len(doc.pages) if hasattr(doc, "pages") else None
        document.status = DocumentStatus.READY
        document.page_count = page_count
        document.error_message = ""
        document.save(update_fields=["status", "page_count", "error_message"])

        send_notification(
            content=json.dumps(
                {"type": "document_processed", "documentId": str(document.id)}
            ),
            app_name=AppName.WEB_GIS,
            user=document.user,
        )

    except Exception as exc:
        logger.exception("Document processing failed for %s.", document_id)
        Document.objects.filter(id=document_id).update(
            status=DocumentStatus.FAILED,
            error_message=str(exc),
        )
        raise self.retry(exc=exc)
