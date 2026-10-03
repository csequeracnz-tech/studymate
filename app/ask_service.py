from pathlib import Path

import httpx
import re
from urllib.parse import urlparse
import yaml

from .database import SessionLocal
from .hybrid_search import hybrid_search, filter_hybrid_results
from .models import StudySession, StudyMessage


HERMES_API_URL = "http://127.0.0.1:8642/v1/chat/completions"


def get_hermes_api_key() -> str:
    config_path = Path.home() / ".hermes" / "config.yaml"

    config = yaml.safe_load(
        config_path.read_text(encoding="utf-8")
    )

    return config["platforms"]["api_server"]["extra"]["key"]


def get_conversation_history(
    session_id: int,
    subject_id: int,
) -> list[dict]:
    with SessionLocal() as db:
        study_session = db.get(StudySession, session_id)

        if study_session is None:
            raise ValueError("Study session not found")

        if study_session.subject_id != subject_id:
            raise ValueError(
                "Study session does not belong to this subject"
            )

        messages = (
            db.query(StudyMessage)
            .filter(
                StudyMessage.session_id == session_id
            )
            .order_by(StudyMessage.created_at.asc())
            .all()
        )

        return [
            {
                "role": message.role,
                "content": message.content,
            }
            for message in messages
        ]



def update_session_title_if_needed(
    session_id: int,
    question: str,
) -> None:
    with SessionLocal() as db:
        study_session = db.get(
            StudySession,
            session_id,
        )

        if study_session is None:
            return

        current_title = (
            study_session.title or ""
        ).strip().lower()

        if current_title not in {
            "",
            "new study session",
        }:
            return

        # Keep titles useful in the sidebar without making them huge.
        title = " ".join(question.split()).strip()

        if len(title) > 80:
            title = title[:77].rstrip() + "..."

        study_session.title = title

        from datetime import datetime

        study_session.updated_at = datetime.utcnow()

        db.commit()


def save_message(
    session_id: int,
    role: str,
    content: str,
) -> None:
    with SessionLocal() as db:
        study_session = db.get(StudySession, session_id)

        if study_session is None:
            raise ValueError("Study session not found")

        message = StudyMessage(
            session_id=session_id,
            role=role,
            content=content,
        )

        db.add(message)

        from datetime import datetime

        study_session.updated_at = datetime.utcnow()

        db.commit()



def extract_research_sources(answer: str):
    """Extract Hermes' External Research Sources into safe structured data."""

    heading = "External Research Sources"

    if heading not in answer:
        return answer.strip(), []

    body, source_block = answer.split(heading, 1)

    # Remove markdown heading punctuation left before the heading.
    body = re.sub(r"\n\s*#{1,6}\s*$", "", body).rstrip()

    sources = []

    # Each source should be one [R#] line ending in an HTTP(S) URL.
    pattern = re.compile(
        r"^\s*\[(R\d+)\]\s+(.+?)\s+[—–-]\s+(https?://\S+)\s*$",
        re.MULTILINE,
    )

    for match in pattern.finditer(source_block):
        ref = match.group(1).strip()
        label = match.group(2).strip()
        url = match.group(3).strip().rstrip(".,;)")

        parsed = urlparse(url)

        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue

        # Best-effort metadata from Hermes' human-readable label.
        # We do NOT invent missing bibliographic fields.
        year_match = re.search(r"\b(19|20)\d{2}\b", label)
        year = year_match.group(0) if year_match else None

        authors = None
        publication = None
        title = label

        # Common Hermes format:
        # Title (Author, Publication, 2023)
        metadata_match = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", label)

        if metadata_match:
            title = metadata_match.group(1).strip()
            metadata = metadata_match.group(2).strip()

            parts = [x.strip() for x in metadata.split(",") if x.strip()]

            if parts:
                # Keep raw metadata rather than pretending it is fully parsed APA.
                authors = parts[0]

            if len(parts) >= 2:
                non_year = [
                    x for x in parts[1:]
                    if not re.fullmatch(r"(19|20)\d{2}", x)
                ]
                if non_year:
                    publication = ", ".join(non_year)

        # Safe fallback APA-style display.
        # This is intentionally conservative until bibliographic metadata
        # is verified/enriched from DOI/Crossref/etc.
        if authors and year:
            in_text = f"({authors}, {year})"
        elif year:
            in_text = f"({year})"
        else:
            in_text = None

        apa_parts = []

        if authors:
            apa_parts.append(authors + ".")

        if year:
            apa_parts.append(f"({year}).")

        apa_parts.append(title.rstrip(".") + ".")

        if publication:
            apa_parts.append(publication.rstrip(".") + ".")

        apa_parts.append(url)

        sources.append({
            "ref": ref,
            "type": "research",
            "title": title,
            "label": label,
            "authors": authors,
            "year": year,
            "publication": publication,
            "url": url,
            "hostname": parsed.netloc.lower().removeprefix("www."),
            "in_text_citation": in_text,
            "apa_reference": " ".join(apa_parts),
            "apa_status": "provisional",
        })

    return body.strip(), sources


def ask_studymate(
    question: str,
    subject_id: int,
    limit: int = 5,
    session_id: int | None = None,
    mode: str = "material",
) -> dict:

    question = question.strip()
    mode = (mode or "material").strip().lower()

    if mode not in {"material", "research"}:
        return {
            "success": False,
            "error": "Invalid study mode",
        }

    if not question:
        return {
            "success": False,
            "error": "Question cannot be empty",
        }

    # --------------------------------------------------------------
    # Session validation
    # --------------------------------------------------------------

    if session_id is not None:
        try:
            conversation_history = get_conversation_history(
                session_id=session_id,
                subject_id=subject_id,
            )
        except ValueError as exc:
            return {
                "success": False,
                "question": question,
                "answer": None,
                "sources": [],
                "error": str(exc),
            }
    else:
        conversation_history = []

    # --------------------------------------------------------------
    # Study mode
    # --------------------------------------------------------------

    # --------------------------------------------------------------
    # Retrieve relevant study material
    # --------------------------------------------------------------

    results = hybrid_search(
        query=question,
        subject_id=subject_id,
        limit=limit,
    )

    results = filter_hybrid_results(results)

    if not results and mode == "material":
        answer = (
            "I could not find enough information in the "
            "study material to answer that question."
        )

        if session_id is not None:
            save_message(
                session_id=session_id,
                role="user",
                content=question,
            )

            save_message(
                session_id=session_id,
                role="assistant",
                content=answer,
            )

        return {
            "success": True,
            "question": question,
            "answer": answer,
            "sources": [],
            "session_id": session_id,
        }

    evidence_blocks = []
    sources = []

    for result in results:
        location_parts = []

        if result["page_number"] is not None:
            location_parts.append(
                f'page {result["page_number"]}'
            )

        if result["slide_number"] is not None:
            location_parts.append(
                f'slide {result["slide_number"]}'
            )

        if result["sheet_name"]:
            location_parts.append(
                f'sheet {result["sheet_name"]}'
            )

        if result["section"]:
            location_parts.append(
                f'section {result["section"]}'
            )

        location = (
            ", ".join(location_parts)
            if location_parts
            else "location not specified"
        )

        evidence_blocks.append(
            f"""Source: {result["document_name"]}
Location: {location}

{result["content"]}"""
        )

        sources.append({
            "document_id": result["document_id"],
            "document_name": result["document_name"],
            "page_number": result["page_number"],
            "slide_number": result["slide_number"],
            "sheet_name": result["sheet_name"],
            "section": result["section"],
            "chunk_id": result["chunk_id"],
        })

    evidence = "\n\n---\n\n".join(evidence_blocks)

    # --------------------------------------------------------------
    # Build conversational prompt
    # --------------------------------------------------------------

    conversation_text = ""

    if conversation_history:
        history_blocks = []

        for message in conversation_history[-12:]:
            role = (
                "the learner"
                if message["role"] == "user"
                else "El Amigo"
            )

            history_blocks.append(
                f"{role}: {message['content']}"
            )

        conversation_text = (
            "\n\nPREVIOUS CONVERSATION:\n"
            + "\n\n".join(history_blocks)
        )

    if mode == "research":
        material_context = evidence if evidence else (
            "[No relevant uploaded material was found for this question.]"
        )

        prompt = f"""You are El Amigo, the learner's academic study and research assistant.

This request is in MATERIAL + RESEARCH mode.

You have two jobs:
1. Use the learner's supplied study material when it is relevant.
2. Use Hermes web_search and web_extract to research reliable external sources
   that help answer the current question.

Research requirements:
- Actually use web research. Do not answer external claims from memory.
- Prefer primary, authoritative and peer-reviewed sources where appropriate.
- For occupational therapy, search broadly and internationally.
- Give particular attention to New Zealand, Australia and Canada when relevant,
  without excluding stronger or more applicable international evidence.
- Prefer current professional bodies, regulators, government sources,
  universities, peer-reviewed research and established academic sources.
- Distinguish clearly between the learner's study material and external research.
- Do not claim the learner's material says something unless it appears in the
  supplied material below.
- Do not use the previous conversation as factual evidence.
- Do not invent citations, authors, dates, DOI values or URLs.
- If sources disagree, explain the disagreement.
- If evidence is limited or uncertain, say so.
- Answer the question directly and at an academically useful level.

Citation requirements:
- Cite external factual claims inline using [R1], [R2], etc.
- At the end include a section exactly titled: External Research Sources
- Under it list each external source used in this format:
  [R1] Title — URL
- Only list sources that you actually used.
- Keep URLs complete so StudyMate can parse and preserve them.
- Do not create a list for the learner's uploaded material; StudyMate attaches
  those verified material sources separately.

{conversation_text}

CURRENT QUESTION:
{question}

THE LEARNER'S CURRENT STUDY MATERIAL:
{material_context}
"""
    else:
        prompt = f"""You are El Amigo, an academic study assistant.

Answer using the supplied study material as your factual grounding.

Rules:
- Do not add facts that are not supported by the supplied material.
- If the material does not contain enough information, say so.
- Give a clear, academically useful answer.
- You may use the previous conversation to understand context.
- Do not treat previous conversation as a source of factual evidence.
- The supplied study material is the authoritative source for factual claims.
- Do not invent citations.
- Do not create a source list. El Amigo will attach verified sources separately.

{conversation_text}

CURRENT QUESTION:
{question}

CURRENT STUDY MATERIAL:
{evidence}
"""

    try:
        response = httpx.post(
            HERMES_API_URL,
            headers={
                "Authorization": (
                    f"Bearer {get_hermes_api_key()}"
                ),
                "Content-Type": "application/json",
            },
            json={
                "model": "hermes-agent",
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            },
            timeout=120.0,
        )

        response.raise_for_status()
        payload = response.json()

        answer = payload["choices"][0]["message"]["content"]

    except Exception as exc:
        return {
            "success": False,
            "question": question,
            "answer": None,
            "sources": sources,
            "session_id": session_id,
            "error": f"Hermes API failed: {exc}",
        }

    answer = answer.strip()

    research_sources = []

    if mode == "research":
        answer, research_sources = extract_research_sources(answer)

    # --------------------------------------------------------------
    # Persist conversation
    # --------------------------------------------------------------

    if session_id is not None:
        try:
            update_session_title_if_needed(
                session_id=session_id,
                question=question,
            )

            save_message(
                session_id=session_id,
                role="user",
                content=question,
            )

            save_message(
                session_id=session_id,
                role="assistant",
                content=answer,
            )
        except ValueError as exc:
            return {
                "success": False,
                "question": question,
                "answer": answer,
                "sources": sources,
                "session_id": session_id,
                "error": str(exc),
            }

    return {
        "success": True,
        "question": question,
        "answer": answer,
        "sources": sources,
        "research_sources": research_sources,
        "session_id": session_id,
        "mode": mode,
    }
