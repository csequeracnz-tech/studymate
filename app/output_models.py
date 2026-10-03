from dataclasses import dataclass, field


@dataclass
class DocumentTable:
    title: str | None = None
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)


@dataclass
class DocumentSection:
    heading: str
    paragraphs: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)
    tables: list[DocumentTable] = field(default_factory=list)

    # Optional presentation intelligence.
    # Other renderers may safely ignore these fields.
    slide_layout: str | None = None
    slide_purpose: str | None = None
    takeaway: str | None = None
    speaker_notes: list[str] = field(default_factory=list)
    visual_suggestion: str | None = None


@dataclass
class GeneratedDocument:
    title: str
    subtitle: str | None = None
    sections: list[DocumentSection] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
