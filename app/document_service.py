import json
import re
import uuid
from pathlib import Path

import httpx

from .ask_service import HERMES_API_URL, get_hermes_api_key
from .database import SessionLocal
from .hybrid_search import hybrid_search, filter_hybrid_results
from .extractor import save_extraction
from .chunker import chunk_extraction_file
from .embedding_service import embed_passages, EMBEDDING_MODEL
from .models import Subject, StudySession, StudyMessage, Document, DocumentChunk
from .output_models import (
    DocumentSection,
    DocumentTable,
    GeneratedDocument,
)
from .renderers.docx_renderer import render_docx
from .renderers.pdf_renderer import render_pdf
from .renderers.pptx_renderer import render_pptx
from .renderers.xlsx_renderer import render_xlsx


EXPORT_DIR = Path(__file__).resolve().parent.parent / "exports"

RENDERERS = {
    "docx": render_docx,
    "pdf": render_pdf,
    "pptx": render_pptx,
    "xlsx": render_xlsx,
}


def _extract_json(text: str) -> dict:
    text = text.strip()

    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")

        if start == -1 or end <= start:
            raise ValueError(
                "El Amigo did not return a valid output structure."
            )

        return json.loads(text[start:end + 1])


def _build_spec(data: dict) -> GeneratedDocument:
    sections = []

    for raw in data.get("sections") or []:
        if not isinstance(raw, dict):
            continue

        tables = []

        for raw_table in raw.get("tables") or []:
            if not isinstance(raw_table, dict):
                continue

            tables.append(
                DocumentTable(
                    title=raw_table.get("title"),
                    headers=[
                        str(x)
                        for x in raw_table.get("headers") or []
                    ],
                    rows=[
                        [str(cell) for cell in row]
                        for row in raw_table.get("rows") or []
                        if isinstance(row, list)
                    ],
                )
            )

        sections.append(
            DocumentSection(
                heading=str(
                    raw.get("heading") or "Section"
                ).strip(),
                paragraphs=[
                    str(x).strip()
                    for x in raw.get("paragraphs") or []
                    if str(x).strip()
                ],
                bullets=[
                    str(x).strip()
                    for x in raw.get("bullets") or []
                    if str(x).strip()
                ],
                tables=tables,
            )
        )

    if not sections:
        raise ValueError(
            "Generated output contained no sections."
        )

    return GeneratedDocument(
        title=str(
            data.get("title") or "Study document"
        ).strip(),
        subtitle=(
            str(data["subtitle"]).strip()
            if data.get("subtitle")
            else None
        ),
        sections=sections,
        references=[
            str(x).strip()
            for x in data.get("references") or []
            if str(x).strip()
        ],
    )



def process_document(document_id: int) -> dict:
    """
    Extract, chunk and embed one uploaded StudyMate document.

    Designed to run as a FastAPI BackgroundTask.
    """

    # ----------------------------------------------------------
    # 1. Mark document as extracting and obtain source path.
    # ----------------------------------------------------------
    with SessionLocal() as db:
        document = db.get(Document, document_id)

        if document is None:
            return {
                "success": False,
                "error": "Document not found",
            }

        document.extraction_status = "extracting"
        document.extraction_error = None
        source_path = Path(document.local_path)

        db.commit()

    try:
        if not source_path.exists():
            raise FileNotFoundError(
                f"Uploaded source file not found: {source_path}"
            )

        # ------------------------------------------------------
        # 2. Extract source into structured JSON.
        # ------------------------------------------------------
        extracted_path = save_extraction(source_path)

        # ------------------------------------------------------
        # 3. Chunk extracted content with source provenance.
        # ------------------------------------------------------
        chunks = chunk_extraction_file(extracted_path)

        # ------------------------------------------------------
        # 4. Generate embeddings once for this document.
        # ------------------------------------------------------
        vectors = embed_passages(
            [chunk["content"] for chunk in chunks]
        )

        # ------------------------------------------------------
        # 5. Persist chunks + embeddings atomically.
        # ------------------------------------------------------
        with SessionLocal() as db:
            document = db.get(Document, document_id)

            if document is None:
                raise ValueError(
                    "Document disappeared during processing"
                )

            # Safe if a document is deliberately reprocessed.
            (
                db.query(DocumentChunk)
                .filter(DocumentChunk.document_id == document_id)
                .delete(synchronize_session=False)
            )

            for chunk, vector in zip(chunks, vectors):
                db.add(
                    DocumentChunk(
                        document_id=document_id,
                        chunk_index=chunk["chunk_index"],
                        content=chunk["content"],
                        source_type=chunk.get("source_type"),
                        page_number=chunk.get("page_number"),
                        slide_number=chunk.get("slide_number"),
                        sheet_name=chunk.get("sheet_name"),
                        section=chunk.get("section"),
                        embedding=json.dumps(vector),
                        embedding_model=EMBEDDING_MODEL,
                    )
                )

            document.extracted_path = str(extracted_path)
            document.extraction_status = "completed"
            document.extraction_error = None

            db.commit()

        return {
            "success": True,
            "document_id": document_id,
            "chunks": len(chunks),
            "embedding_model": EMBEDDING_MODEL,
        }

    except Exception as exc:
        # Keep the failure visible to the UI/document status API.
        with SessionLocal() as db:
            document = db.get(Document, document_id)

            if document is not None:
                document.extraction_status = "failed"
                document.extraction_error = str(exc)
                db.commit()

        return {
            "success": False,
            "document_id": document_id,
            "error": str(exc),
        }


def _call_hermes(prompt: str, timeout: float = 240.0) -> str:
    """
    Send one focused task to Hermes.
    Hermes remains the reasoning/orchestration layer.
    """
    response = httpx.post(
        HERMES_API_URL,
        headers={
            "Authorization": f"Bearer {get_hermes_api_key()}",
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
        timeout=timeout,
    )

    response.raise_for_status()

    payload = response.json()

    return payload["choices"][0]["message"]["content"]


def _format_material_location(result: dict) -> str:
    parts = []

    page = result.get("page_number")
    slide = result.get("slide_number")
    sheet = result.get("sheet_name")
    section = result.get("section")

    if page:
        parts.append(f"page {page}")

    if slide:
        parts.append(f"slide {slide}")

    if sheet:
        parts.append(f"sheet {sheet}")

    if section:
        parts.append(f"section {section}")

    return ", ".join(parts)



def _plan_generation_retrieval(
    subject_name: str,
    instructions: str,
    conversation: str,
) -> dict:
    """
    AI planning pass.

    Before retrieval, El Amigo decides what information the requested
    artifact actually needs and creates focused searches.
    """

    prompt = f"""
You are El Amigo's retrieval planner.

The user is creating an academic study artifact.

SUBJECT:
{subject_name}

THE LEARNER'S REQUEST:
{instructions}

RECENT CONVERSATION:
{conversation[-6000:]}

Determine what evidence must be retrieved from the learner's uploaded
study material before creating this artifact.

Return JSON only:

{{
  "task": "short description of what the learner is trying to create",

  "learning_goal": "what the learner should understand or communicate",

  "retrieval_queries": [
    "focused search query 1",
    "focused search query 2"
  ],

  "key_questions": [
    "question the evidence should answer"
  ],

  "important_concepts": [
    "concept"
  ],

  "external_research_needed": true,

  "external_research_reason": "brief reason or null"
}}

RULES:

- Produce 2 to 6 focused retrieval queries.
- Search for concepts and evidence, not file names.
- Cover distinct parts of the learner's request.
- Do not invent facts.
- Do not answer the academic question.
- Set external_research_needed true only when the learner's request
  genuinely requires information beyond her uploaded/course material,
  such as current research, evidence, guidelines, comparison with
  literature, current practice or explicit web research.
- If the task can be completed entirely from her course material,
  external_research_needed must be false.
""".strip()

    raw = _call_hermes(
        prompt,
        timeout=180.0,
    )

    data = _extract_json(raw)

    queries = [
        str(q).strip()
        for q in data.get("retrieval_queries", [])
        if str(q).strip()
    ][:6]

    if not queries:
        queries = [instructions.strip()]

    return {
        "task": str(data.get("task") or "").strip(),
        "learning_goal": str(
            data.get("learning_goal") or ""
        ).strip(),
        "retrieval_queries": queries,
        "key_questions": [
            str(q).strip()
            for q in data.get("key_questions", [])
            if str(q).strip()
        ][:8],
        "important_concepts": [
            str(q).strip()
            for q in data.get("important_concepts", [])
            if str(q).strip()
        ][:12],
        "external_research_needed": bool(
            data.get("external_research_needed", False)
        ),
        "external_research_reason": (
            str(
                data.get("external_research_reason")
                or ""
            ).strip()
            or None
        ),
    }


def _deduplicate_material_results(
    results: list[dict],
    limit: int = 20,
) -> list[dict]:
    """
    Combine results from several focused searches without repeatedly
    sending the same chunk to Hermes.
    """

    unique = []
    seen = set()

    for result in results:
        identity = (
            result.get("chunk_id")
            or result.get("id")
            or (
                result.get("document_id"),
                result.get("chunk_index"),
            )
        )

        if identity in seen:
            continue

        seen.add(identity)
        unique.append(result)

        if len(unique) >= limit:
            break

    return unique


def _retrieve_generation_evidence(
    plan: dict,
    subject_id: int,
) -> list[dict]:
    """
    Run several targeted hybrid searches generated by the AI planner.
    """

    combined = []

    for query in plan["retrieval_queries"]:
        results = _retrieve_generation_material(
            query=query,
            subject_id=subject_id,
            limit=8,
        )

        combined.extend(results)

    return _deduplicate_material_results(
        combined,
        limit=24,
    )

def _retrieve_generation_material(
    query: str,
    subject_id: int,
    limit: int = 12,
) -> list[dict]:
    """
    Retrieve a focused evidence set from the learner's indexed material.

    This deliberately does not send every uploaded document to Hermes.
    """
    results = hybrid_search(
        query=query,
        subject_id=subject_id,
        limit=limit,
        candidate_limit=max(limit * 4, 30),
    )

    return filter_hybrid_results(
        results,
        relative_threshold=0.55,
        semantic_gap_threshold=0.10,
    )


def _material_evidence_text(results: list[dict]) -> str:
    if not results:
        return (
            "No directly relevant uploaded-material passages "
            "were retrieved for this request."
        )

    blocks = []

    for index, result in enumerate(results, start=1):
        document_name = (
            result.get("document_name")
            or result.get("name")
            or result.get("document")
            or "Uploaded material"
        )

        location = _format_material_location(result)

        header = f"[M{index}] {document_name}"

        if location:
            header += f" — {location}"

        content = (
            result.get("content")
            or result.get("text")
            or ""
        ).strip()

        blocks.append(
            f"{header}\n{content}"
        )

    return "\n\n".join(blocks)


def _conversation_for_generation(
    subject_id: int,
    session_id: int,
) -> tuple[str, str]:
    with SessionLocal() as db:
        subject = db.get(Subject, subject_id)
        study_session = db.get(StudySession, session_id)

        if subject is None:
            raise ValueError("Subject not found")

        if study_session is None:
            raise ValueError("Conversation not found")

        if study_session.subject_id != subject_id:
            raise ValueError(
                "Conversation does not belong to this subject"
            )

        messages = (
            db.query(StudyMessage)
            .filter(StudyMessage.session_id == session_id)
            .order_by(StudyMessage.created_at.asc())
            .all()
        )

        conversation = "\n\n".join(
            (
                "the learner"
                if message.role == "user"
                else "El Amigo"
            )
            + ":\n"
            + message.content
            for message in messages
        )

        return subject.name, conversation


def _assemble_evidence(
    subject_name: str,
    instructions: str,
    conversation: str,
    material_text: str,
    retrieval_plan: dict | None = None,
) -> str:
    """
    AI pass 1:
    Create a grounded evidence brief before artifact writing begins.

    Hermes may use web research when the request actually calls for it.
    """
    plan_text = json.dumps(
        retrieval_plan or {},
        ensure_ascii=False,
        indent=2,
    )

    prompt = f"""
You are El Amigo's research and evidence specialist.

Your job is NOT to create the final file yet.

RETRIEVAL PLAN:
{plan_text}

Prepare a rigorous evidence brief for an academic artifact requested by the learner.

SUBJECT:
{subject_name}

THE LEARNER'S ARTIFACT REQUEST:
{instructions}

RELEVANT UPLOADED MATERIAL:
{material_text}

CURRENT CONVERSATION:
{conversation}

RULES:

1. The learner's uploaded/course material is primary for claims about what
   her course material teaches.

2. Treat [M#] passages as uploaded material.
   Preserve those labels and their page/slide/sheet/section provenance.

3. The conversation provides context and intent, but do not assume
   statements in the conversation are evidence unless supported.

4. If the learner's request asks for current research, external research,
   comparison with research, evidence, guidelines, current practice,
   or information beyond her uploaded material, actually use your
   available web/research tools.

5. For external research:
   - prefer peer-reviewed literature and authoritative professional,
     government, university or health sources;
   - use jurisdiction-specific evidence when relevant;
   - for occupational therapy, search internationally while giving
     appropriate attention to New Zealand, Australia and Canada;
   - record enough bibliographic information to support APA 7;
   - preserve URLs and DOI when genuinely available;
   - never invent authors, dates, journals, DOI, URLs or findings.

6. Clearly separate:
   UPLOADED MATERIAL
   EXTERNAL RESEARCH
   SYNTHESIS / IMPLICATIONS

7. Identify conflicts, limitations, uncertainty or evidence gaps.

8. Do not fabricate a source to fill a gap.

9. Preserve source traceability throughout the brief.

Return a detailed evidence brief for the artifact specialist.
""".strip()

    return _call_hermes(prompt)


def _artifact_prompt(
    output_format: str,
    subject_name: str,
    instructions: str,
    evidence_brief: str,
) -> str:

    specialist_guidance = {
        "docx": """
Act as an academic writer and document designer.
Create a coherent standalone document rather than a transcript.
Use meaningful hierarchy, developed paragraphs, bullets only where
they improve comprehension, and evidence tables where useful.
""",
        "pdf": """
Act as an academic study-guide and information designer.
Create a polished standalone learning resource with concise sections,
strong hierarchy, comparison tables and revision-friendly structure.
""",
        "pptx": """
Act as an expert academic presentation designer.
Build a narrative across the slides rather than copying prose.
Use concise slide content, logical progression, comparisons and
takeaways. Keep individual sections short enough to become readable
slides. Do not turn the presentation into a wall of text.
""",
        "xlsx": """
Act as an expert academic workbook designer, evidence organiser and
learning-data architect.

Design a WORKBOOK, not a document pasted into spreadsheet cells.

First determine what workbook structure best supports the learner's task.

Prefer purposeful structured tables such as:
- literature/evidence matrices;
- research comparison matrices;
- occupational therapy model comparisons;
- intervention or assessment comparisons;
- source/evidence trackers;
- concept matrices;
- study/revision trackers;
- findings and implications tables.

Each table should represent a coherent worksheet.

For literature/evidence work, include useful columns when supported,
such as:
Author / Year
Jurisdiction
Study or source
Aim
Population / context
Method / evidence type
Key findings
Limitations
Practice implications
Relevance to the learner's question
Citation / source

Do NOT create columns for information that is unavailable merely to
make the workbook look complete.

Keep narrative prose secondary to structured information.

Use short, meaningful table titles because these become worksheet
names.

Do not place multiple unrelated datasets in one table.

Do not invent numerical data, formulas, scores or statistics.

Do not invent missing bibliographic metadata.

If the evidence supports comparison, structure rows and columns so
The learner can scan differences rather than reading long paragraphs.

References must still contain only sources actually used.
""",
    }[output_format]

    return f"""
You are El Amigo's {output_format.upper()} artifact specialist.

{specialist_guidance}

SUBJECT:
{subject_name}

THE LEARNER'S REQUEST:
{instructions}

VERIFIED EVIDENCE BRIEF:
{evidence_brief}

Create the artifact specification.

GROUNDING RULES:
- Use only claims supported by the evidence brief.
- Preserve distinctions between uploaded material and external research.
- Preserve meaningful [M#] source traceability where useful.
- Use author-date academic citations for external research when supported.
- Never manufacture bibliographic metadata.
- If evidence is incomplete, write conservatively rather than inventing.
- References must contain only sources actually used in the artifact.
- Use APA 7 as far as the available source metadata permits.

Return JSON only.
Do not use markdown fences.
Do not add commentary outside the JSON.

SCHEMA:

{{
  "title": "Artifact title",
  "subtitle": "Optional subtitle or null",
  "sections": [
    {{
      "heading": "Section heading",
      "paragraphs": [
        "Developed content with appropriate citations"
      ],
      "bullets": [
        "Concise point where appropriate"
      ],
      "tables": [
        {{
          "title": "Optional table title",
          "headers": [
            "Column 1",
            "Column 2"
          ],
          "rows": [
            [
              "Value 1",
              "Value 2"
            ]
          ]
        }}
      ]
    }}
  ],
  "references": [
    "APA-style reference using only verified metadata"
  ]
}}
""".strip()


def _review_artifact(
    output_format: str,
    instructions: str,
    evidence_brief: str,
    draft_json: dict,
) -> dict:
    """
    AI pass 3:
    Critic receives the draft and evidence, then returns the corrected
    final artifact rather than merely giving comments.
    """
    draft_text = json.dumps(
        draft_json,
        ensure_ascii=False,
        indent=2,
    )

    prompt = f"""
You are El Amigo's final academic quality reviewer.

Review the proposed {output_format.upper()} artifact against the learner's
request and the verified evidence.

THE LEARNER'S REQUEST:
{instructions}

VERIFIED EVIDENCE:
{evidence_brief}

DRAFT ARTIFACT:
{draft_text}

CHECK ALL OF THE FOLLOWING:

GROUNDING
- Every substantive factual claim is supported by the evidence.
- No invented research, quotations, authors, dates, DOI or URLs.
- Uploaded material and external research are not falsely conflated.

CITATIONS
- Citations correspond to evidence actually present.
- References contain only sources actually used.
- APA formatting is as complete as the available metadata allows.
- Do not invent missing APA fields.

LEARNING QUALITY
- The artifact helps the learner understand the subject.
- Important concepts are explained rather than merely listed.
- Comparisons and relationships are clear.
- The requested task has actually been answered.

FORMAT QUALITY
- DOCX: coherent academic document.
- PDF: polished standalone study resource.
- PPTX: concise presentation-ready structure, not essay paragraphs.
- XLSX: structured tables/matrices where appropriate.

REQUEST COMPLIANCE
- Respect requested length, emphasis, audience and structure where given.
- Remove repetition and irrelevant material.
- Correct unsupported or misleading wording.

Return the COMPLETE CORRECTED ARTIFACT as JSON only.

Use exactly this schema:

{{
  "title": "Artifact title",
  "subtitle": "Optional subtitle or null",
  "sections": [
    {{
      "heading": "Section heading",
      "paragraphs": ["Paragraph"],
      "bullets": ["Bullet"],
      "tables": [
        {{
          "title": "Optional title",
          "headers": ["Column"],
          "rows": [["Value"]]
        }}
      ]
    }}
  ],
  "references": ["Reference"]
}}

No markdown fences.
No review commentary.
""".strip()

    reviewed = _call_hermes(prompt)

    return _extract_json(reviewed)


def generate_output(
    subject_id: int,
    session_id: int,
    output_format: str,
    instructions: str,
) -> dict:

    output_format = output_format.lower().strip()

    if output_format not in RENDERERS:
        raise ValueError(
            "Format must be docx, pdf, pptx or xlsx."
        )

    subject_name, conversation = (
        _conversation_for_generation(
            subject_id,
            session_id,
        )
    )

    if not conversation.strip():
        raise ValueError(
            "There is no conversation to turn into an output yet."
        )

    # ----------------------------------------------------------
    # STAGE 1A — AI plans what evidence the artifact requires
    # ----------------------------------------------------------

    retrieval_plan = _plan_generation_retrieval(
        subject_name=subject_name,
        instructions=instructions,
        conversation=conversation,
    )

    # ----------------------------------------------------------
    # STAGE 1B — multi-query hybrid retrieval
    # ----------------------------------------------------------

    material_results = _retrieve_generation_evidence(
        plan=retrieval_plan,
        subject_id=subject_id,
    )

    material_text = _material_evidence_text(
        material_results
    )

    # ----------------------------------------------------------
    # STAGE 1C — evidence/research agent
    # ----------------------------------------------------------

    evidence_brief = _assemble_evidence(
        subject_name=subject_name,
        instructions=instructions,
        conversation=conversation,
        material_text=material_text,
        retrieval_plan=retrieval_plan,
    )

    # ----------------------------------------------------------
    # STAGE 2 — format-specialist artifact agent
    # ----------------------------------------------------------

    draft_content = _call_hermes(
        _artifact_prompt(
            output_format=output_format,
            subject_name=subject_name,
            instructions=instructions,
            evidence_brief=evidence_brief,
        )
    )

    draft_data = _extract_json(draft_content)

    # Validate the draft before spending another AI pass on it.
    _build_spec(draft_data)

    # ----------------------------------------------------------
    # STAGE 3 — grounding / citation / quality critic
    # ----------------------------------------------------------

    final_data = _review_artifact(
        output_format=output_format,
        instructions=instructions,
        evidence_brief=evidence_brief,
        draft_json=draft_data,
    )

    spec = _build_spec(final_data)

    # ----------------------------------------------------------
    # DETERMINISTIC RENDERING
    # ----------------------------------------------------------

    EXPORT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    filename = (
        f"studymate-{uuid.uuid4().hex}.{output_format}"
    )

    output_path = EXPORT_DIR / filename

    RENDERERS[output_format](
        spec,
        output_path,
    )

    return {
        "success": True,
        "format": output_format,
        "filename": filename,
        "title": spec.title,
        "material_sources_used": len(material_results),
        "retrieval_queries": retrieval_plan[
            "retrieval_queries"
        ],
        "pipeline": {
            "ai_planning": True,
            "multi_query_retrieval": True,
            "evidence_review": True,
            "artifact_specialist": True,
            "quality_review": True,
        },
        "download_url": (
            f"/outputs/{filename}/download"
        ),
    }
