from pathlib import Path
from fastapi import FastAPI, BackgroundTasks, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from uuid import uuid4

from .database import Base, SessionLocal, engine
from .models import Project, Subject, Document
from .auth import (
    add_session_middleware,
    install_auth_middleware,
    verify_credentials,
)
from .auth import get_login_client_key, login_retry_after, record_login_failure, clear_login_failures
from .auth import get_or_create_csrf_token, install_csrf_middleware

Base.metadata.create_all(engine)

app = FastAPI(
    title="StudyMate",
    description="Personal AI study workspace",
    version="0.1.0",
)

install_auth_middleware(app)
install_csrf_middleware(app)
add_session_middleware(app)


STATIC_DIR = Path(__file__).resolve().parent / "static"

app.mount(
    "/static",
    StaticFiles(directory=STATIC_DIR),
    name="static",
)


@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/login")
def login_page(request: Request):
    if request.session.get("authenticated"):
        return RedirectResponse("/", status_code=303)

    return FileResponse(STATIC_DIR / "login.html")


@app.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    client_key = get_login_client_key(request)
    retry_after = login_retry_after(client_key)

    if retry_after:
        return RedirectResponse(
            "/login?error=1",
            status_code=303,
            headers={"Retry-After": str(retry_after)},
        )

    if not verify_credentials(username, password):
        retry_after = record_login_failure(client_key)

        headers = {}

        if retry_after:
            headers["Retry-After"] = str(retry_after)

        return RedirectResponse(
            "/login?error=1",
            status_code=303,
            headers=headers,
        )

    clear_login_failures(client_key)

    request.session.clear()
    request.session["authenticated"] = True
    request.session["username"] = username.strip().lower()

    return RedirectResponse("/", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()

    return RedirectResponse(
        "/login",
        status_code=303,
    )


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/csrf-token")
def csrf_token(request: Request):
    return {
        "csrf_token": get_or_create_csrf_token(request)
    }


@app.get("/projects")
def list_projects():
    with SessionLocal() as session:
        projects = session.scalars(
            select(Project).order_by(Project.created_at.desc())
        ).all()

        return [
            {
                "id": project.id,
                "name": project.name,
                "description": project.description,
            }
            for project in projects
        ]


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None


@app.post("/projects")
def create_project(project: ProjectCreate):
    with SessionLocal() as session:
        new_project = Project(
            name=project.name,
            description=project.description,
        )
        session.add(new_project)
        session.commit()
        session.refresh(new_project)

        return {
            "id": new_project.id,
            "name": new_project.name,
            "description": new_project.description,
        }


class SubjectCreate(BaseModel):
    name: str
    description: str | None = None


@app.post("/projects/{project_id}/subjects")
def create_subject(project_id: int, subject: SubjectCreate):
    with SessionLocal() as session:
        project = session.get(Project, project_id)

        if project is None:
            return {"error": "Project not found"}

        new_subject = Subject(
            project_id=project_id,
            name=subject.name,
            description=subject.description,
        )

        session.add(new_subject)
        session.commit()
        session.refresh(new_subject)

        return {
            "id": new_subject.id,
            "project_id": new_subject.project_id,
            "name": new_subject.name,
            "description": new_subject.description,
        }


@app.get("/projects/{project_id}/subjects")
def list_subjects(project_id: int):
    with SessionLocal() as session:
        subjects = session.scalars(
            select(Subject)
            .where(Subject.project_id == project_id)
            .order_by(Subject.created_at.desc())
        ).all()

        return [
            {
                "id": subject.id,
                "project_id": subject.project_id,
                "name": subject.name,
                "description": subject.description,
            }
            for subject in subjects
        ]


from pathlib import Path
from fastapi import File, UploadFile

from .document_service import process_document


ALLOWED_FILE_TYPES = {
    ".pdf",
    ".docx",
    ".doc",
    ".pptx",
    ".ppt",
    ".xlsx",
    ".xls",
    ".csv",
    ".txt",
    ".md",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".tiff",
}


@app.post("/subjects/{subject_id}/documents")
async def upload_document(
    subject_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    with SessionLocal() as session:
        subject = session.get(Subject, subject_id)

        if subject is None:
            return {"error": "Subject not found"}

        extension = Path(file.filename or "").suffix.lower()

        if extension not in ALLOWED_FILE_TYPES:
            return {
                "error": f"Unsupported file type: {extension}"
            }

        subject_directory = (
            Path(__file__).resolve().parent.parent
            / "data"
            / "documents"
            / str(subject_id)
        )
        subject_directory.mkdir(parents=True, exist_ok=True)

        # Store each upload under a unique immutable filename.
        # The original filename remains in Document.name for display.
        stored_filename = f"{uuid4().hex}{extension}"
        destination = subject_directory / stored_filename

        size_bytes = 0
        chunk_size = 1024 * 1024

        with destination.open("wb") as output:
            while chunk := await file.read(chunk_size):
                output.write(chunk)
                size_bytes += len(chunk)

        await file.close()

        document = Document(
            subject_id=subject_id,
            name=file.filename,
            file_type=extension,
            local_path=str(destination),
            extraction_status="pending",
        )

        session.add(document)
        session.commit()
        session.refresh(document)

        document_id = document.id

    # Extraction, chunking and embedding can be expensive.
    # Return the upload response immediately and process it after
    # the HTTP response has been sent.
    background_tasks.add_task(
        process_document,
        document_id,
    )

    return {
        "id": document_id,
        "subject_id": subject_id,
        "name": file.filename,
        "file_type": extension,
        "size_bytes": size_bytes,
        "path": str(destination),
        "processing": {
            "status": "pending",
        },
    }


from .hybrid_search import hybrid_search, filter_hybrid_results


@app.get("/search")
def search(
    q: str,
    subject_id: int | None = None,
    limit: int = 10,
):
    results = hybrid_search(
        query=q,
        subject_id=subject_id,
        limit=limit,
    )

    results = filter_hybrid_results(results)

    return {
        "query": q,
        "subject_id": subject_id,
        "count": len(results),
        "results": results,
    }


# ------------------------------------------------------------------
# StudyMate grounded question answering
# ------------------------------------------------------------------

from pydantic import BaseModel
from .ask_service import ask_studymate


class AskRequest(BaseModel):
    question: str
    subject_id: int
    limit: int = 5
    session_id: int | None = None
    mode: str = "material"


@app.post("/ask")
def ask(request: AskRequest):
    return ask_studymate(
        question=request.question,
        subject_id=request.subject_id,
        limit=request.limit,
        session_id=request.session_id,
        mode=request.mode,
    )


# ------------------------------------------------------------------
# Document preview
# ------------------------------------------------------------------

@app.get("/documents/{document_id}/preview")
def preview_document(document_id: int):
    from fastapi.responses import FileResponse

    with SessionLocal() as session:
        document = session.get(Document, document_id)

        if document is None:
            return {
                "success": False,
                "error": "Document not found",
            }

        if not document.local_path:
            return {
                "success": False,
                "error": "Document file is not available",
            }

        path = Path(document.local_path)

        if not path.exists() or not path.is_file():
            return {
                "success": False,
                "error": "Document file is not available",
            }

        extension = path.suffix.lower()

        media_types = {
            ".pdf": "application/pdf",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".txt": "text/plain; charset=utf-8",
            ".md": "text/markdown; charset=utf-8",
        }

        media_type = media_types.get(
            extension,
            "application/octet-stream",
        )

        return FileResponse(
            path=str(path),
            media_type=media_type,
            filename=document.name,
            content_disposition_type="inline",
        )


# ------------------------------------------------------------------
# Document status
# ------------------------------------------------------------------

@app.get("/documents/{document_id}/status")
def document_status(document_id: int):
    from sqlalchemy import func
    from .models import DocumentChunk

    with SessionLocal() as session:
        document = session.get(Document, document_id)

        if document is None:
            return {
                "success": False,
                "error": "Document not found",
            }

        chunk_count = session.scalar(
            select(func.count(DocumentChunk.id)).where(
                DocumentChunk.document_id == document_id
            )
        )

        return {
            "success": True,
            "document_id": document.id,
            "name": document.name,
            "status": document.extraction_status,
            "ready": (
                document.extraction_status == "completed"
                and chunk_count > 0
            ),
            "chunks": chunk_count,
            "error": document.extraction_error,
        }


# ------------------------------------------------------------------
# Subject documents
# ------------------------------------------------------------------

@app.get("/subjects/{subject_id}/documents")
def list_subject_documents(subject_id: int):
    from sqlalchemy import func
    from .models import DocumentChunk

    with SessionLocal() as session:
        subject = session.get(Subject, subject_id)

        if subject is None:
            return {
                "success": False,
                "error": "Subject not found",
            }

        documents = session.scalars(
            select(Document)
            .where(Document.subject_id == subject_id)
            .order_by(Document.created_at.desc())
        ).all()

        results = []

        for document in documents:
            chunk_count = session.scalar(
                select(func.count(DocumentChunk.id)).where(
                    DocumentChunk.document_id == document.id
                )
            )

            results.append({
                "id": document.id,
                "name": document.name,
                "file_type": document.file_type,
                "folder_id": document.folder_id,
                "status": document.extraction_status,
                "ready": (
                    document.extraction_status == "completed"
                    and chunk_count > 0
                ),
                "error": document.extraction_error,
                "created_at": document.created_at.isoformat(),
            })

        return {
            "success": True,
            "subject_id": subject.id,
            "subject_name": subject.name,
            "count": len(results),
            "documents": results,
        }

# ------------------------------------------------------------------
# Subject folders
# ------------------------------------------------------------------

class FolderCreate(BaseModel):
    name: str
    description: str | None = None


@app.get("/subjects/{subject_id}/folders")
def list_folders(subject_id: int):
    from .models import Folder

    with SessionLocal() as session:
        subject = session.get(Subject, subject_id)

        if subject is None:
            return {"success": False, "error": "Subject not found"}

        folders = (
            session.query(Folder)
            .filter(Folder.subject_id == subject_id)
            .order_by(Folder.created_at.asc())
            .all()
        )

        return {
            "success": True,
            "subject_id": subject_id,
            "count": len(folders),
            "folders": [
                {
                    "id": folder.id,
                    "name": folder.name,
                    "description": folder.description,
                    "created_at": folder.created_at.isoformat(),
                }
                for folder in folders
            ],
        }


@app.post("/subjects/{subject_id}/folders")
def create_folder(subject_id: int, folder: FolderCreate):
    from .models import Folder

    name = folder.name.strip()

    if not name:
        return {
            "success": False,
            "error": "Folder name is required",
        }

    with SessionLocal() as session:
        subject = session.get(Subject, subject_id)

        if subject is None:
            return {
                "success": False,
                "error": "Subject not found",
            }

        new_folder = Folder(
            subject_id=subject_id,
            name=name,
            description=folder.description,
        )

        session.add(new_folder)
        session.commit()
        session.refresh(new_folder)

        return {
            "success": True,
            "id": new_folder.id,
            "subject_id": subject_id,
            "name": new_folder.name,
            "description": new_folder.description,
        }


@app.delete("/folders/{folder_id}")
def delete_folder(folder_id: int):
    from .models import Folder

    with SessionLocal() as session:
        folder = session.get(Folder, folder_id)

        if folder is None:
            return {
                "success": False,
                "error": "Folder not found",
            }

        # Keep documents safe. Deleting a folder simply moves its
        # documents back to the subject root.
        for document in folder.documents:
            document.folder_id = None

        session.delete(folder)
        session.commit()

        return {
            "success": True,
            "folder_id": folder_id,
            "documents_unassigned": True,
        }

# ------------------------------------------------------------------
# Move documents between folders
# ------------------------------------------------------------------

class DocumentMove(BaseModel):
    folder_id: int | None = None


@app.patch("/documents/{document_id}/folder")
def move_document(document_id: int, request: DocumentMove):
    from .models import Folder

    with SessionLocal() as session:
        document = session.get(Document, document_id)

        if document is None:
            return {
                "success": False,
                "error": "Document not found",
            }

        if request.folder_id is not None:
            folder = session.get(Folder, request.folder_id)

            if folder is None:
                return {
                    "success": False,
                    "error": "Folder not found",
                }

            if folder.subject_id != document.subject_id:
                return {
                    "success": False,
                    "error": "Folder does not belong to this subject",
                }

        document.folder_id = request.folder_id
        session.commit()

        return {
            "success": True,
            "document_id": document.id,
            "folder_id": document.folder_id,
        }

# ------------------------------------------------------------------
# Folder management
# ------------------------------------------------------------------

class FolderUpdate(BaseModel):
    name: str


@app.patch("/folders/{folder_id}")
def rename_folder(folder_id: int, request: FolderUpdate):
    from .models import Folder

    name = request.name.strip()

    if not name:
        return {
            "success": False,
            "error": "Folder name is required",
        }

    with SessionLocal() as session:
        folder = session.get(Folder, folder_id)

        if folder is None:
            return {
                "success": False,
                "error": "Folder not found",
            }

        folder.name = name
        session.commit()

        return {
            "success": True,
            "folder_id": folder.id,
            "name": folder.name,
        }


# ------------------------------------------------------------------
# Document management
# ------------------------------------------------------------------

class DocumentRename(BaseModel):
    name: str


@app.patch("/documents/{document_id}")
def rename_document(document_id: int, request: DocumentRename):
    name = request.name.strip()

    if not name:
        return {
            "success": False,
            "error": "Document name is required",
        }

    with SessionLocal() as session:
        document = session.get(Document, document_id)

        if document is None:
            return {
                "success": False,
                "error": "Document not found",
            }

        old_path = Path(document.local_path) if document.local_path else None
        new_path = None

        if old_path and old_path.exists():
            new_path = old_path.with_name(name)

            if new_path != old_path:
                if new_path.exists():
                    return {
                        "success": False,
                        "error": "A file with that name already exists",
                    }

                old_path.rename(new_path)
                document.local_path = str(new_path)

        document.name = name
        session.commit()

        return {
            "success": True,
            "document_id": document.id,
            "name": document.name,
        }


@app.delete("/documents/{document_id}")
def delete_document(document_id: int):
    with SessionLocal() as session:
        document = session.get(Document, document_id)

        if document is None:
            return {
                "success": False,
                "error": "Document not found",
            }

        # Delete indexed chunks first.
        from .models import DocumentChunk

        chunks = (
            session.query(DocumentChunk)
            .filter(DocumentChunk.document_id == document.id)
            .all()
        )

        for chunk in chunks:
            session.delete(chunk)

        # Delete extracted JSON if present.
        if document.extracted_path:
            extracted = Path(document.extracted_path)
            if extracted.exists():
                extracted.unlink()

        # Delete source file if present.
        if document.local_path:
            source = Path(document.local_path)
            if source.exists():
                source.unlink()

        session.delete(document)
        session.commit()

        return {
            "success": True,
            "document_id": document_id,
        }

@app.delete("/subjects/{subject_id}")
def delete_subject(subject_id: int):
    from .models import (
        Document,
        DocumentChunk,
        Folder,
        StudyMessage,
        StudySession,
    )

    with SessionLocal() as session:
        subject = session.get(Subject, subject_id)

        if subject is None:
            return {
                "success": False,
                "error": "Subject not found",
            }

        documents = (
            session.query(Document)
            .filter(Document.subject_id == subject_id)
            .all()
        )

        # Remove physical files belonging to this subject.
        for document in documents:
            for path_value in (
                document.extracted_path,
                document.local_path,
            ):
                if not path_value:
                    continue

                file_path = Path(path_value)

                if file_path.exists() and file_path.is_file():
                    file_path.unlink()

        document_ids = [d.id for d in documents]

        if document_ids:
            session.query(DocumentChunk).filter(
                DocumentChunk.document_id.in_(document_ids)
            ).delete(synchronize_session=False)

        session_ids = [
            row[0]
            for row in session.query(StudySession.id)
            .filter(StudySession.subject_id == subject_id)
            .all()
        ]

        if session_ids:
            session.query(StudyMessage).filter(
                StudyMessage.session_id.in_(session_ids)
            ).delete(synchronize_session=False)

        session.query(StudySession).filter(
            StudySession.subject_id == subject_id
        ).delete(synchronize_session=False)

        session.query(Document).filter(
            Document.subject_id == subject_id
        ).delete(synchronize_session=False)

        session.query(Folder).filter(
            Folder.subject_id == subject_id
        ).delete(synchronize_session=False)

        session.delete(subject)
        session.commit()

        return {
            "success": True,
            "subject_id": subject_id,
        }


# ------------------------------------------------------------------
# El Amigo study sessions
# ------------------------------------------------------------------

class StudySessionCreate(BaseModel):
    title: str | None = None


@app.post("/subjects/{subject_id}/sessions")
def create_study_session(
    subject_id: int,
    request: StudySessionCreate,
):
    from .models import StudySession

    with SessionLocal() as session:
        subject = session.get(Subject, subject_id)

        if subject is None:
            return {
                "success": False,
                "error": "Subject not found",
            }

        title = (
            request.title.strip()
            if request.title and request.title.strip()
            else "New study session"
        )

        study_session = StudySession(
            subject_id=subject_id,
            title=title,
        )

        session.add(study_session)
        session.commit()
        session.refresh(study_session)

        return {
            "success": True,
            "session": {
                "id": study_session.id,
                "subject_id": study_session.subject_id,
                "title": study_session.title,
                "created_at": study_session.created_at.isoformat(),
                "updated_at": study_session.updated_at.isoformat(),
            },
        }


@app.get("/subjects/{subject_id}/sessions")
def list_study_sessions(subject_id: int):
    from .models import StudySession

    with SessionLocal() as session:
        subject = session.get(Subject, subject_id)

        if subject is None:
            return {
                "success": False,
                "error": "Subject not found",
            }

        sessions = (
            session.query(StudySession)
            .filter(StudySession.subject_id == subject_id)
            .order_by(StudySession.updated_at.desc())
            .all()
        )

        return {
            "success": True,
            "subject_id": subject_id,
            "sessions": [
                {
                    "id": item.id,
                    "title": item.title,
                    "created_at": item.created_at.isoformat(),
                    "updated_at": item.updated_at.isoformat(),
                }
                for item in sessions
            ],
        }


@app.get("/sessions/{session_id}")
def get_study_session(session_id: int):
    from .models import StudySession

    with SessionLocal() as session:
        study_session = session.get(StudySession, session_id)

        if study_session is None:
            return {
                "success": False,
                "error": "Study session not found",
            }

        return {
            "success": True,
            "session": {
                "id": study_session.id,
                "subject_id": study_session.subject_id,
                "title": study_session.title,
                "created_at": study_session.created_at.isoformat(),
                "updated_at": study_session.updated_at.isoformat(),
                "messages": [
                    {
                        "id": message.id,
                        "role": message.role,
                        "content": message.content,
                        "created_at": message.created_at.isoformat(),
                    }
                    for message in study_session.messages
                ],
            },
        }

@app.delete("/sessions/{session_id}")
def delete_study_session(session_id: int):
    from .models import StudySession, StudyMessage

    with SessionLocal() as session:
        study_session = session.get(StudySession, session_id)

        if study_session is None:
            return {
                "success": False,
                "error": "Study session not found",
            }

        subject_id = study_session.subject_id

        # Permanently remove this conversation's messages.
        session.query(StudyMessage).filter(
            StudyMessage.session_id == session_id
        ).delete(synchronize_session=False)

        # Remove the conversation itself.
        session.delete(study_session)
        session.commit()

        return {
            "success": True,
            "session_id": session_id,
            "subject_id": subject_id,
        }


# ------------------------------------------------------------------
# Study summaries
# ------------------------------------------------------------------

class SummaryRequest(BaseModel):
    folder_id: int | None = None
    document_id: int | None = None


@app.post("/subjects/{subject_id}/summary")
def generate_subject_summary(
    subject_id: int,
    request: SummaryRequest,
):
    from datetime import datetime
    from .models import Document, DocumentChunk, Folder

    with SessionLocal() as db:
        subject = db.get(Subject, subject_id)

        if subject is None:
            return {
                "success": False,
                "error": "Subject not found",
            }

        query = (
            db.query(DocumentChunk, Document)
            .join(
                Document,
                Document.id == DocumentChunk.document_id,
            )
            .filter(
                Document.subject_id == subject_id,
                Document.extraction_status == "completed",
            )
        )

        scope_name = subject.name

        if request.folder_id is not None:
            folder = db.get(Folder, request.folder_id)

            if (
                folder is None
                or folder.subject_id != subject_id
            ):
                return {
                    "success": False,
                    "error": "Folder not found",
                }

            query = query.filter(
                Document.folder_id == request.folder_id
            )

            scope_name = folder.name

        if request.document_id is not None:
            document = db.get(
                Document,
                request.document_id,
            )

            if (
                document is None
                or document.subject_id != subject_id
            ):
                return {
                    "success": False,
                    "error": "Document not found",
                }

            query = query.filter(
                Document.id == request.document_id
            )

            scope_name = document.name

        rows = (
            query
            .order_by(
                Document.name.asc(),
                DocumentChunk.chunk_index.asc(),
            )
            .all()
        )

        if not rows:
            return {
                "success": False,
                "error": (
                    "There is no completed study material "
                    "available for this summary."
                ),
            }

        # Keep the summary request bounded while retaining material
        # from multiple documents.
        max_chunks = 80
        rows = rows[:max_chunks]

        evidence_blocks = []

        for chunk, document in rows:
            location = []

            if chunk.page_number is not None:
                location.append(
                    f"page {chunk.page_number}"
                )

            if chunk.slide_number is not None:
                location.append(
                    f"slide {chunk.slide_number}"
                )

            if chunk.sheet_name:
                location.append(
                    f"sheet {chunk.sheet_name}"
                )

            if chunk.section:
                location.append(
                    f"section {chunk.section}"
                )

            location_text = (
                ", ".join(location)
                if location
                else "location not specified"
            )

            content = chunk.content.strip()

            # Prevent one unusually large chunk dominating the
            # summary context.
            if len(content) > 5000:
                content = content[:5000] + "\n[content truncated]"

            evidence_blocks.append(
                f"""DOCUMENT: {document.name}
LOCATION: {location_text}

{content}"""
            )

        evidence = "\n\n---\n\n".join(evidence_blocks)

        prompt = f"""You are El Amigo, an academic study summarisation assistant.

Create a portable study summary from ONLY the supplied study material.

The summary will be copied into another AI, so make it:
- self-contained
- clear
- structured
- factually grounded
- useful for studying
- easy for another AI to understand

IMPORTANT RULES:
- Do not add outside facts.
- Do not invent information.
- Do not silently correct the study material.
- If the material is unclear or incomplete, say so.
- Preserve important terminology from the source.
- Combine repeated information where appropriate.
- Distinguish definitions, concepts, examples and comparisons.
- Do not mention chunks, embeddings, retrieval or internal system details.

Use this structure where the material supports it:

# Study Summary

## Topic
Briefly identify what the material covers.

## Key Concepts
Explain the main concepts clearly.

## Key Definitions
List important terms and their meanings.

## Important Points
Capture facts, principles, processes or arguments that should be remembered.

## Examples
Include examples from the supplied material when available.

## Comparisons
Include meaningful comparisons or distinctions when the material provides them.

## Exam / Study Focus
Identify points that appear particularly important for study or revision.
Do not invent exam priorities that are not supported by the material.

## Source Material
List the documents used, with page/slide/section information where available.

The output must contain ONLY the finished study summary.

SUBJECT:
{subject.name}

SUMMARY SCOPE:
{scope_name}

STUDY MATERIAL:
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
                timeout=180.0,
            )

            response.raise_for_status()

            payload = response.json()

            summary = (
                payload["choices"][0]["message"]["content"]
                .strip()
            )

        except Exception as exc:
            return {
                "success": False,
                "error": f"Summary generation failed: {exc}",
            }

        source_map = {}

        for chunk, document in rows:
            key = document.id

            if key not in source_map:
                source_map[key] = {
                    "document_id": document.id,
                    "document_name": document.name,
                    "locations": [],
                }

            location = []

            if chunk.page_number is not None:
                location.append(
                    f"page {chunk.page_number}"
                )

            if chunk.slide_number is not None:
                location.append(
                    f"slide {chunk.slide_number}"
                )

            if chunk.sheet_name:
                location.append(
                    f"sheet {chunk.sheet_name}"
                )

            if chunk.section:
                location.append(
                    f"section {chunk.section}"
                )

            if location:
                source_map[key]["locations"].append(
                    ", ".join(location)
                )

        sources = list(source_map.values())

        for source in sources:
            source["locations"] = list(
                dict.fromkeys(source["locations"])
            )

        return {
            "success": True,
            "subject_id": subject_id,
            "scope": scope_name,
            "summary": summary,
            "sources": sources,
            "generated_at": datetime.utcnow().isoformat(),
        }


# ------------------------------------------------------------------
# Generated study outputs
# ------------------------------------------------------------------

class OutputGenerationRequest(BaseModel):
    session_id: int
    format: str
    instructions: str = (
        "Create a useful academic study output from this conversation."
    )


@app.post("/subjects/{subject_id}/outputs")
def generate_study_output(
    subject_id: int,
    request: OutputGenerationRequest,
):
    from .document_service import generate_output

    try:
        return generate_output(
            subject_id=subject_id,
            session_id=request.session_id,
            output_format=request.format,
            instructions=request.instructions.strip()
            or "Create a useful academic study output.",
        )
    except ValueError as exc:
        return {
            "success": False,
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "success": False,
            "error": f"Output generation failed: {exc}",
        }


@app.get("/outputs/{filename}/download")
def download_generated_output(filename: str):
    from fastapi.responses import FileResponse

    if not re.fullmatch(
        r"studymate-[a-f0-9]{32}\.(docx|pdf|pptx|xlsx)",
        filename,
    ):
        return {
            "success": False,
            "error": "Invalid output filename",
        }

    output_path = (
        Path(__file__).resolve().parent.parent
        / "exports"
        / filename
    )

    if not output_path.exists() or not output_path.is_file():
        return {
            "success": False,
            "error": "Generated output not found",
        }

    media_types = {
        ".docx": (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        ".pdf": "application/pdf",
        ".pptx": (
            "application/vnd.openxmlformats-officedocument."
            "presentationml.presentation"
        ),
        ".xlsx": (
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
    }

    return FileResponse(
        path=str(output_path),
        media_type=media_types[output_path.suffix.lower()],
        filename=filename,
    )
