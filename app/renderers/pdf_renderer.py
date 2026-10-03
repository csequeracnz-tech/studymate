from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import (
    TA_CENTER,
    TA_LEFT,
)
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import (
    ParagraphStyle,
    getSampleStyleSheet,
)
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..output_models import GeneratedDocument


def _safe(value) -> str:
    return escape(
        str(value if value is not None else "")
    )


def _build_styles():
    styles = getSampleStyleSheet()

    title = ParagraphStyle(
        "StudyMateTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=24,
        leading=28,
        alignment=TA_CENTER,
        spaceAfter=10,
    )

    subtitle = ParagraphStyle(
        "StudyMateSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=14,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#53635B"),
        spaceAfter=18,
    )

    heading = ParagraphStyle(
        "StudyMateHeading",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=20,
        textColor=colors.HexColor("#203D31"),
        spaceBefore=12,
        spaceAfter=7,
        keepWithNext=True,
    )

    subheading = ParagraphStyle(
        "StudyMateSubheading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#315B49"),
        spaceBefore=7,
        spaceAfter=5,
        keepWithNext=True,
    )

    body = ParagraphStyle(
        "StudyMateBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=10,
        leading=14.5,
        spaceAfter=7,
    )

    takeaway = ParagraphStyle(
        "StudyMateTakeaway",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=9.5,
        leading=13,
        leftIndent=8,
        rightIndent=8,
        spaceBefore=5,
        spaceAfter=10,
        borderWidth=0.5,
        borderColor=colors.HexColor("#B8CDC2"),
        borderPadding=7,
        backColor=colors.HexColor("#F2F7F4"),
    )

    reference = ParagraphStyle(
        "StudyMateReference",
        parent=body,
        fontSize=9,
        leading=12.5,
        leftIndent=12,
        firstLineIndent=-12,
        spaceAfter=6,
    )

    return {
        "title": title,
        "subtitle": subtitle,
        "heading": heading,
        "subheading": subheading,
        "body": body,
        "takeaway": takeaway,
        "reference": reference,
    }


def _page_footer(canvas, doc):
    canvas.saveState()

    width, _ = A4

    canvas.setFont(
        "Helvetica",
        8,
    )

    canvas.setFillColor(
        colors.HexColor("#6D7772")
    )

    canvas.drawString(
        18 * mm,
        10 * mm,
        "El Amigo · StudyMate",
    )

    canvas.drawRightString(
        width - 18 * mm,
        10 * mm,
        f"Page {doc.page}",
    )

    canvas.restoreState()


def _table_flowable(
    table_spec,
    styles,
    available_width,
):
    elements = []

    if table_spec.title:
        elements.append(
            Paragraph(
                _safe(table_spec.title),
                styles["subheading"],
            )
        )

    data = []

    if table_spec.headers:
        data.append([
            Paragraph(
                f"<b>{_safe(value)}</b>",
                styles["body"],
            )
            for value in table_spec.headers
        ])

    for row in table_spec.rows:
        data.append([
            Paragraph(
                _safe(value),
                styles["body"],
            )
            for value in row
        ])

    if not data:
        return elements

    column_count = max(
        len(row)
        for row in data
    )

    # Normalise ragged rows.
    for row in data:
        while len(row) < column_count:
            row.append(
                Paragraph(
                    "",
                    styles["body"],
                )
            )

    column_width = (
        available_width / column_count
    )

    table = Table(
        data,
        colWidths=[
            column_width
            for _ in range(column_count)
        ],
        repeatRows=(
            1
            if table_spec.headers
            else 0
        ),
        hAlign="LEFT",
    )

    commands = [
        (
            "GRID",
            (0, 0),
            (-1, -1),
            0.4,
            colors.HexColor("#B7C2BC"),
        ),
        (
            "VALIGN",
            (0, 0),
            (-1, -1),
            "TOP",
        ),
        (
            "LEFTPADDING",
            (0, 0),
            (-1, -1),
            5,
        ),
        (
            "RIGHTPADDING",
            (0, 0),
            (-1, -1),
            5,
        ),
        (
            "TOPPADDING",
            (0, 0),
            (-1, -1),
            5,
        ),
        (
            "BOTTOMPADDING",
            (0, 0),
            (-1, -1),
            5,
        ),
    ]

    if table_spec.headers:
        commands.extend([
            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.HexColor("#E7F0EB"),
            ),
            (
                "TEXTCOLOR",
                (0, 0),
                (-1, 0),
                colors.HexColor("#203D31"),
            ),
        ])

    table.setStyle(
        TableStyle(commands)
    )

    elements.extend([
        table,
        Spacer(1, 10),
    ])

    return elements


def render_pdf(
    spec: GeneratedDocument,
    output_path: Path,
) -> Path:

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    styles = _build_styles()

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=spec.title,
        author="El Amigo · StudyMate",
    )

    story = [
        Spacer(1, 12),
        Paragraph(
            _safe(spec.title),
            styles["title"],
        ),
    ]

    if spec.subtitle:
        story.append(
            Paragraph(
                _safe(spec.subtitle),
                styles["subtitle"],
            )
        )

    story.append(
        Spacer(1, 8)
    )

    # --------------------------------------------------------
    # Learning-resource content
    # --------------------------------------------------------

    for section in spec.sections:
        story.append(
            Paragraph(
                _safe(section.heading),
                styles["heading"],
            )
        )

        for text in section.paragraphs:
            story.append(
                Paragraph(
                    _safe(text),
                    styles["body"],
                )
            )

        if section.bullets:
            story.append(
                ListFlowable(
                    [
                        ListItem(
                            Paragraph(
                                _safe(item),
                                styles["body"],
                            ),
                            leftIndent=12,
                        )
                        for item in section.bullets
                    ],
                    bulletType="bullet",
                    leftIndent=18,
                    bulletFontSize=7,
                    spaceAfter=7,
                )
            )

        for table_spec in section.tables:
            story.extend(
                _table_flowable(
                    table_spec,
                    styles,
                    doc.width,
                )
            )

        if section.takeaway:
            story.append(
                Paragraph(
                    "<b>Key takeaway:</b> "
                    + _safe(section.takeaway),
                    styles["takeaway"],
                )
            )

        story.append(
            Spacer(1, 4)
        )

    # --------------------------------------------------------
    # References
    # --------------------------------------------------------

    if spec.references:
        story.append(
            PageBreak()
        )

        story.append(
            Paragraph(
                "References",
                styles["heading"],
            )
        )

        for reference in spec.references:
            story.append(
                Paragraph(
                    _safe(reference),
                    styles["reference"],
                )
            )

    doc.build(
        story,
        onFirstPage=_page_footer,
        onLaterPages=_page_footer,
    )

    return output_path
