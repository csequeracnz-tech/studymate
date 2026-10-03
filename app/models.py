from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    subjects: Mapped[list["Subject"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    project: Mapped["Project"] = relationship(
        back_populates="subjects",
    )

    folders: Mapped[list["Folder"]] = relationship(
        back_populates="subject",
        cascade="all, delete-orphan",
    )

    documents: Mapped[list["Document"]] = relationship(
        back_populates="subject",
        cascade="all, delete-orphan",
    )


class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[int] = mapped_column(primary_key=True)

    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    subject: Mapped["Subject"] = relationship(
        back_populates="folders",
    )

    documents: Mapped[list["Document"]] = relationship(
        back_populates="folder",
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id"),
        nullable=False,
    )

    folder_id: Mapped[int | None] = mapped_column(
        ForeignKey("folders.id"),
        nullable=True,
    )

    name: Mapped[str] = mapped_column(String(300), nullable=False)
    file_type: Mapped[str | None] = mapped_column(String(50))
    drive_file_id: Mapped[str | None] = mapped_column(String(200))
    local_path: Mapped[str | None] = mapped_column(String(500))

    extraction_status: Mapped[str] = mapped_column(
        String(50),
        default="pending",
        nullable=False,
    )
    extracted_path: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    extraction_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    subject: Mapped["Subject"] = relationship(
        back_populates="documents",
    )

    folder: Mapped["Folder | None"] = relationship(
        back_populates="documents",
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)

    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id"),
        nullable=False,
        index=True,
    )

    chunk_index: Mapped[int] = mapped_column(nullable=False)

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    source_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    page_number: Mapped[int | None] = mapped_column(
        nullable=True,
    )

    slide_number: Mapped[int | None] = mapped_column(
        nullable=True,
    )

    sheet_name: Mapped[str | None] = mapped_column(
        String(300),
        nullable=True,
    )

    section: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    embedding: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    embedding_model: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


class StudySession(Base):
    __tablename__ = "study_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)

    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id"),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String(300),
        default="New study session",
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    subject: Mapped["Subject"] = relationship()

    messages: Mapped[list["StudyMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="StudyMessage.created_at",
    )


class StudyMessage(Base):
    __tablename__ = "study_messages"

    id: Mapped[int] = mapped_column(primary_key=True)

    session_id: Mapped[int] = mapped_column(
        ForeignKey("study_sessions.id"),
        nullable=False,
        index=True,
    )

    role: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    session: Mapped["StudySession"] = relationship(
        back_populates="messages",
    )
