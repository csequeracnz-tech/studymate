import json
from functools import lru_cache

from sentence_transformers import SentenceTransformer

from .database import SessionLocal
from .models import DocumentChunk


EMBEDDING_MODEL = "intfloat/e5-base-v2"


@lru_cache(maxsize=1)
def get_embedding_model():
    return SentenceTransformer(EMBEDDING_MODEL)


def embed_passages(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []

    model = get_embedding_model()

    vectors = model.encode(
        [f"passage: {text}" for text in texts],
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    return vectors.tolist()


def embed_query(text: str) -> list[float]:
    model = get_embedding_model()

    vector = model.encode(
        [f"query: {text}"],
        normalize_embeddings=True,
        show_progress_bar=False,
    )[0]

    return vector.tolist()


def backfill_embeddings() -> dict:
    with SessionLocal() as db:
        chunks = (
            db.query(DocumentChunk)
            .filter(
                (DocumentChunk.embedding.is_(None))
                | (DocumentChunk.embedding_model != EMBEDDING_MODEL)
            )
            .order_by(DocumentChunk.id)
            .all()
        )

        if not chunks:
            return {
                "success": True,
                "chunks_updated": 0,
                "model": EMBEDDING_MODEL,
            }

        vectors = embed_passages(
            [chunk.content for chunk in chunks]
        )

        for chunk, vector in zip(chunks, vectors):
            chunk.embedding = json.dumps(vector)
            chunk.embedding_model = EMBEDDING_MODEL

        db.commit()

        return {
            "success": True,
            "chunks_updated": len(chunks),
            "model": EMBEDDING_MODEL,
        }
