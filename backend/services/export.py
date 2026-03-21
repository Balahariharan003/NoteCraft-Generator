import os
from fpdf import FPDF
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from datetime import datetime

OUTPUTS_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs")


# ── Sanitize for Helvetica (Latin-1 only) ─────────────────────
def _s(text) -> str:
    if not text:
        return "-"
    return str(text).encode("latin-1", errors="ignore").decode("latin-1") or "-"


# ── Main export function ───────────────────────────────────────
def export_documents(mom_json: dict, session_id: str) -> tuple:
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    docx_path = os.path.join(OUTPUTS_DIR, f"{session_id}.docx")
    _generate_docx(mom_json, docx_path)
    return None, f"/outputs/{session_id}.docx"


def delete_documents(session_id: str):
    for ext in ["pdf", "docx"]:
        path = os.path.join(OUTPUTS_DIR, f"{session_id}.{ext}")
        if os.path.exists(path):
            os.remove(path)


# ══ DOCX Generation ════════════════════════════════════════════
def _generate_docx(mom: dict, path: str):
    doc = Document()

    # ── Page margins ───────────────────────────────────────────
    for section in doc.sections:
        section.top_margin    = Pt(50)
        section.bottom_margin = Pt(50)
        section.left_margin   = Pt(70)
        section.right_margin  = Pt(70)

    # ══ HEADER BLOCK ══════════════════════════════════════════

    # ── Title ──────────────────────────────────────────────────
    title_para = doc.add_paragraph()
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title_para.add_run(mom.get("title", "Minutes of Meeting"))
    run.bold           = True
    run.font.size      = Pt(18)
    run.font.color.rgb = RGBColor(26, 26, 40)

    # ── Subtitle ───────────────────────────────────────────────
    sub_para = doc.add_paragraph()
    sub_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub_run = sub_para.add_run("MINUTES OF MEETING")
    sub_run.font.size      = Pt(10)
    sub_run.font.color.rgb = RGBColor(83, 74, 183)
    sub_run.bold           = True

    doc.add_paragraph()

    # ── Metadata table ─────────────────────────────────────────
    meta_table = doc.add_table(rows=4, cols=2)
    meta_table.style = "Table Grid"

    meta_data = [
        ("Date",            mom.get("date", datetime.now().strftime("%Y-%m-%d"))),
        ("Time",            mom.get("time", "Not specified")),
        ("Mode of Meeting", mom.get("mode_of_meeting", "Online (Google Meet)")),
        ("Prepared By",     mom.get("prepared_by", "MoM Generator")),
    ]

    for i, (label, value) in enumerate(meta_data):
        row = meta_table.rows[i]
        # Label cell
        label_cell = row.cells[0]
        label_para = label_cell.paragraphs[0]
        label_run  = label_para.add_run(label)
        label_run.bold      = True
        label_run.font.size = Pt(10)
        label_cell.width    = Inches(2)
        # Value cell
        value_cell = row.cells[1]
        value_para = value_cell.paragraphs[0]
        value_run  = value_para.add_run(str(value))
        value_run.font.size = Pt(10)

    doc.add_paragraph()

    # ══ PARTICIPANTS ═══════════════════════════════════════════
    _docx_heading(doc, "ATTENDEES")
    participants = mom.get("participants", [])
    if participants:
        for p in participants:
            _docx_bullet(doc, p)
    else:
        doc.add_paragraph("Participants not identified")

    # ══ AGENDA ════════════════════════════════════════════════
    _docx_heading(doc, "AGENDA")
    for i, item in enumerate(mom.get("agenda", []), 1):
        _docx_numbered(doc, f"{item}", i)

    # ══ KEY DISCUSSIONS ════════════════════════════════════════
    _docx_heading(doc, "KEY DISCUSSIONS")
    for item in mom.get("key_discussions", mom.get("discussions", [])):
        _docx_bullet(doc, item)

    # ══ DECISIONS TAKEN ════════════════════════════════════════
    _docx_heading(doc, "DECISIONS TAKEN")
    for item in mom.get("decisions_taken", mom.get("decisions", [])):
        _docx_bullet(doc, item)

    # ══ ACTION ITEMS TABLE ═════════════════════════════════════
    _docx_heading(doc, "ACTION ITEMS")
    action_items = mom.get("action_items", [])

    if action_items:
        table = doc.add_table(rows=1, cols=3)
        table.style = "Table Grid"

        # Header row
        hdr_cells = table.rows[0].cells
        headers   = ["Owner", "Task", "Deadline"]
        for i, h in enumerate(headers):
            para = hdr_cells[i].paragraphs[0]
            run  = para.add_run(h)
            run.bold           = True
            run.font.size      = Pt(10)
            run.font.color.rgb = RGBColor(255, 255, 255)
            # Purple background
            tc   = hdr_cells[i]._tc
            tcPr = tc.get_or_add_tcPr()
            shd  = OxmlElement("w:shd")
            shd.set(qn("w:val"), "clear")
            shd.set(qn("w:color"), "auto")
            shd.set(qn("w:fill"), "534AB7")
            tcPr.append(shd)

        # Data rows
        for item in action_items:
            row_cells = table.add_row().cells
            row_cells[0].text = str(item.get("owner", "-"))
            row_cells[1].text = str(item.get("task", "-"))
            row_cells[2].text = str(item.get("deadline", "-"))
            for cell in row_cells:
                cell.paragraphs[0].runs[0].font.size = Pt(10)
    else:
        doc.add_paragraph("No action items recorded.")

    doc.add_paragraph()

    # ── Footer ─────────────────────────────────────────────────
    footer      = doc.sections[0].footer
    footer_para = footer.paragraphs[0]
    footer_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer_run  = footer_para.add_run("Generated by MoM Generator")
    footer_run.font.size      = Pt(8)
    footer_run.font.color.rgb = RGBColor(150, 150, 150)

    doc.save(path)


# ── Section heading ────────────────────────────────────────────
def _docx_heading(doc: Document, title: str):
    para = doc.add_paragraph()
    run  = para.add_run(title)
    run.bold           = True
    run.font.size      = Pt(11)
    run.font.color.rgb = RGBColor(83, 74, 183)
    # Bottom border on heading
    pPr  = para._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"),   "single")
    bottom.set(qn("w:sz"),    "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "534AB7")
    pBdr.append(bottom)
    pPr.append(pBdr)


# ── Bullet point ───────────────────────────────────────────────
def _docx_bullet(doc: Document, text: str):
    para = doc.add_paragraph(style="List Bullet")
    run  = para.add_run(text)
    run.font.size = Pt(10)


# ── Numbered item ──────────────────────────────────────────────
def _docx_numbered(doc: Document, text: str, number: int):
    para = doc.add_paragraph(style="List Number")
    run  = para.add_run(text)
    run.font.size = Pt(10)