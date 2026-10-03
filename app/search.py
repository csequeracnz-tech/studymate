import re

from sqlalchemy import text

from .database import engine


def prepare_fts_query(query: str) -> str:
    """
    Convert natural-language input into a safe FTS5 query.

    Example:
        What is transformational leadership?
    becomes:
        "What" OR "is" OR "transformational" OR "leadership"

    Short/common words are removed so meaningful terms drive retrieval.
    """

    words = re.findall(r"[A-Za-z0-9]+", query)

    stop_words = {
        "a", "an", "and", "are", "as", "at",
        "be", "by", "for", "from",
        "how", "i", "in", "is", "it",
        "of", "on", "or",
        "that", "the", "this", "to",
        "was", "what", "when", "where", "which",
        "who", "why", "with",
    }

    terms = [
        word
        for word in words
        if word.lower() not in stop_words
        and len(word) > 1
    ]

    if not terms:
        terms = words

    if not terms:
        return ""

    # Quote every term so user input cannot become FTS5 syntax.
    return " OR ".join(
        f'"{word}"'
        for word in terms
    )


def search_documents(
    query: str,
    subject_id: int | None = None,
    limit: int = 10,
) -> list[dict]:

    fts_query = prepare_fts_query(query)

    if not fts_query:
        return []

    sql = """
        SELECT
            dc.id AS chunk_id,
            dc.document_id,
            d.name AS document_name,
            s.id AS subject_id,
            s.name AS subject_name,
            dc.chunk_index,
            dc.source_type,
            dc.page_number,
            dc.slide_number,
            dc.sheet_name,
            dc.section,
            dc.content,
            bm25(document_chunks_fts) AS score
        FROM document_chunks_fts
        JOIN document_chunks dc
            ON dc.id = document_chunks_fts.rowid
        JOIN documents d
            ON d.id = dc.document_id
        JOIN subjects s
            ON s.id = d.subject_id
        WHERE document_chunks_fts MATCH :query
    """

    parameters = {
        "query": fts_query,
        "limit": limit,
    }

    if subject_id is not None:
        sql += " AND s.id = :subject_id"
        parameters["subject_id"] = subject_id

    sql += """
        ORDER BY score
        LIMIT :limit
    """

    with engine.connect() as connection:
        rows = connection.execute(
            text(sql),
            parameters,
        ).mappings().all()

    return [dict(row) for row in rows]


def filter_relevant_results(
    results: list[dict],
    relative_threshold: float = 0.15,
) -> list[dict]:
    """
    Remove extremely weak FTS matches relative to the best result.

    FTS5 bm25 scores are negative: more negative means more relevant.
    We compare absolute score magnitude so the filter adapts to each query.
    """

    if not results:
        return []

    best_strength = abs(results[0]["score"])

    if best_strength == 0:
        return results[:1]

    relevant = [
        result
        for result in results
        if abs(result["score"]) >= best_strength * relative_threshold
    ]

    return relevant or results[:1]
