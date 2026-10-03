import json

import numpy as np

from .database import SessionLocal
from .embedding_service import EMBEDDING_MODEL, embed_query
from .models import DocumentChunk, Document, Subject


def semantic_search(
    query: str,
    subject_id: int | None = None,
    limit: int = 10,
) -> list[dict]:

    query_vector = np.array(
        embed_query(query),
        dtype=np.float32,
    )

    with SessionLocal() as db:
        q = (
            db.query(DocumentChunk, Document, Subject)
            .join(Document, Document.id == DocumentChunk.document_id)
            .join(Subject, Subject.id == Document.subject_id)
            .filter(
                DocumentChunk.embedding.is_not(None),
                DocumentChunk.embedding_model == EMBEDDING_MODEL,
            )
        )

        if subject_id is not None:
            q = q.filter(Subject.id == subject_id)

        rows = q.all()

        results = []

        for chunk, document, subject in rows:
            vector = np.array(
                json.loads(chunk.embedding),
                dtype=np.float32,
            )

            # Both query and passage embeddings are normalized,
            # so dot product = cosine similarity.
            score = float(np.dot(query_vector, vector))

            results.append({
                "chunk_id": chunk.id,
                "document_id": document.id,
                "document_name": document.name,
                "subject_id": subject.id,
                "subject_name": subject.name,
                "chunk_index": chunk.chunk_index,
                "source_type": chunk.source_type,
                "page_number": chunk.page_number,
                "slide_number": chunk.slide_number,
                "sheet_name": chunk.sheet_name,
                "section": chunk.section,
                "content": chunk.content,
                "semantic_score": score,
            })

    results.sort(
        key=lambda result: result["semantic_score"],
        reverse=True,
    )

    return results[:limit]
