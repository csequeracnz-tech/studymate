import json
from pathlib import Path


DEFAULT_CHUNK_SIZE = 1500
DEFAULT_OVERLAP = 200


def split_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[str]:
    text = text.strip()

    if not text:
        return []

    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break

        start = max(end - overlap, start + 1)

    return chunks


def chunk_extraction(extracted: dict) -> list[dict]:
    source_type = extracted.get("type")
    chunks = []

    def add_text(text: str, **metadata):
        for part in split_text(text):
            chunks.append({
                "content": part,
                "source_type": source_type,
                "page_number": metadata.get("page_number"),
                "slide_number": metadata.get("slide_number"),
                "sheet_name": metadata.get("sheet_name"),
                "section": metadata.get("section"),
            })

    if source_type == "text":
        add_text(extracted.get("content", ""))

    elif source_type == "pdf":
        for page in extracted.get("pages", []):
            add_text(
                page.get("text", ""),
                page_number=page.get("page"),
            )

    elif source_type == "docx":
        paragraphs = extracted.get("paragraphs", [])

        if paragraphs:
            add_text(
                "\n\n".join(paragraphs),
                section="document",
            )

        for table_number, table in enumerate(
            extracted.get("tables", []),
            start=1,
        ):
            rows = []

            for row in table:
                rows.append(" | ".join(str(cell) for cell in row))

            add_text(
                "\n".join(rows),
                section=f"table_{table_number}",
            )

    elif source_type == "pptx":
        for slide in extracted.get("slides", []):
            text_parts = slide.get("text", [])

            if isinstance(text_parts, list):
                text = "\n".join(text_parts)
            else:
                text = str(text_parts)

            add_text(
                text,
                slide_number=slide.get("slide"),
            )

    elif source_type == "xlsx":
        for sheet_name, rows in extracted.get(
            "sheets",
            {},
        ).items():
            lines = []

            for row in rows:
                lines.append(
                    " | ".join(str(value) for value in row)
                )

            add_text(
                "\n".join(lines),
                sheet_name=sheet_name,
            )

    elif source_type == "image":
        add_text(
            extracted.get("ocr_text", ""),
            section="ocr",
        )

    else:
        raise ValueError(
            f"Unsupported extraction type: {source_type}"
        )

    for index, chunk in enumerate(chunks):
        chunk["chunk_index"] = index

    return chunks


def chunk_extraction_file(path: str | Path) -> list[dict]:
    path = Path(path)

    extracted = json.loads(
        path.read_text(encoding="utf-8")
    )

    return chunk_extraction(extracted)
