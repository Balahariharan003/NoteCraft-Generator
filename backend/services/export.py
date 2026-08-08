import os
import re
from datetime import datetime

from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

OUTPUTS_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs")


# ─────────────────────────────────────────────
# MAIN EXPORT FUNCTION
# ─────────────────────────────────────────────
def export_documents(mom_json: dict, session_id: str) -> tuple:

    os.makedirs(OUTPUTS_DIR, exist_ok=True)

    raw_title = (
        mom_json.get("session_title")
        or mom_json.get("title")
        or "MoM_Report"
    )

    clean_name = re.sub(r"[^\w\s-]", "", str(raw_title))
    clean_name = re.sub(r"\s+", "_", clean_name.strip())
    clean_name = clean_name[:60]

    filename = f"{clean_name}_{session_id[:8]}"

    docx_path = os.path.join(
        OUTPUTS_DIR,
        f"{filename}.docx"
    )

    doc_type = mom_json.get("document_type", "mom")
    if doc_type == "online_session":
        _generate_online_session_docx(mom_json, docx_path)
    else:
        _generate_docx(mom_json, docx_path)

    return None, f"/outputs/{filename}.docx"


# ─────────────────────────────────────────────
# DOCX GENERATION
# ─────────────────────────────────────────────
def _generate_docx(data: dict, path: str):

    doc = Document()

    # PAGE SETTINGS
    section = doc.sections[0]
    section.top_margin = Pt(45)
    section.bottom_margin = Pt(45)
    section.left_margin = Pt(50)
    section.right_margin = Pt(50)

    # FOOTER
    footer = section.footer
    footer_para = footer.paragraphs[0]
    footer_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _add_page_number(footer_para)

    # ─────────────────────────────────────────
    # 1. MAIN TITLE
    # ─────────────────────────────────────────
    title_para = doc.add_paragraph()
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title_para.add_run("Minutes of the Meeting")
    run.bold = True
    run.font.size = Pt(16)
    title_para.paragraph_format.space_after = Pt(14)

    # ─────────────────────────────────────────
    # 2. METADATA TABLE (2 COLUMNS)
    # ─────────────────────────────────────────
    meta_table = doc.add_table(rows=5, cols=2)
    meta_table.style = "Table Grid"

    meeting_title  = data.get("session_title") or "Meeting Review"
    meeting_no     = data.get("meeting_no") or f"{datetime.now().strftime('%Y-%m')}/01"
    meeting_date   = data.get("date") or datetime.now().strftime("%d.%m.%Y")
    meeting_time   = data.get("time") or "Scheduled Session"
    venue_platform = data.get("venue_platform") or "Google Meet"

    meta_rows = [
        ("Meeting Title",       meeting_title),
        ("Meeting No.",         meeting_no),
        ("Date",                meeting_date),
        ("Time",                meeting_time),
        ("Venue / Platform",    venue_platform),
    ]

    for idx, (label, val) in enumerate(meta_rows):
        row_cells = meta_table.rows[idx].cells
        
        # Label cell
        row_cells[0].text = str(label)
        p0 = row_cells[0].paragraphs[0]
        r0 = p0.runs[0]
        r0.bold = True
        r0.font.size = Pt(10)
        _set_cell_background(row_cells[0], "F2F2F2")

        # Value cell
        row_cells[1].text = str(val)
        p1 = row_cells[1].paragraphs[0]
        r1 = p1.runs[0]
        r1.font.size = Pt(10)

    doc.add_paragraph().paragraph_format.space_after = Pt(6)

    # ─────────────────────────────────────────
    # 3. MEMBERS PRESENT
    # ─────────────────────────────────────────
    mem_header = doc.add_paragraph()
    r_mem = mem_header.add_run("Members Present:")
    r_mem.bold = True
    r_mem.font.size = Pt(11)
    mem_header.paragraph_format.space_after = Pt(4)

    members = data.get("members_present") or data.get("participants") or ["Attendees"]
    if isinstance(members, str):
        members = [members]

    for member in members:
        p_mem = doc.add_paragraph(style="List Bullet")
        r_m = p_mem.add_run(str(member))
        r_m.font.size = Pt(10)
        p_mem.paragraph_format.space_after = Pt(2)

    p_spacer = doc.add_paragraph()
    p_spacer.paragraph_format.space_after = Pt(8)

    # ─────────────────────────────────────────
    # 4. POINTS DISCUSSED
    # ─────────────────────────────────────────
    disc_header = doc.add_paragraph()
    r_disc = disc_header.add_run("Points Discussed")
    r_disc.bold = True
    r_disc.font.size = Pt(13)
    disc_header.paragraph_format.space_after = Pt(8)

    points_discussed = data.get("points_discussed") or []
    
    # Auto-convert legacy/fallback structures
    if not points_discussed:
        categories = data.get("categories") or []
        if categories:
            for cat in categories:
                points_discussed.append({
                    "category_name": cat.get("name") or "General Discussion",
                    "points": cat.get("points") or ["Discussion conducted."]
                })
        else:
            points_discussed = [{
                "category_name": "General Discussion",
                "points": ["The meeting proceedings were conducted as per agenda."]
            }]

    for cat_item in points_discussed:
        if not isinstance(cat_item, dict):
            continue

        cat_name = cat_item.get("category_name") or "Discussion"
        points   = cat_item.get("points") or []
        if isinstance(points, str):
            points = [points]

        # Category Header
        p_cat = doc.add_paragraph()
        r_cname = p_cat.add_run(f"Category: {cat_name}")
        r_cname.bold = True
        r_cname.font.size = Pt(10.5)
        p_cat.paragraph_format.space_before = Pt(4)
        p_cat.paragraph_format.space_after = Pt(3)

        for pt in points:
            p_pt = doc.add_paragraph(style="List Bullet")
            r_pt = p_pt.add_run(str(pt))
            r_pt.font.size = Pt(10)
            p_pt.paragraph_format.space_after = Pt(2)

    doc.add_paragraph().paragraph_format.space_after = Pt(8)

    # ─────────────────────────────────────────
    # 5. RESPONSIBILITY & TARGET DATE
    # ─────────────────────────────────────────
    resp_header = doc.add_paragraph()
    r_resp = resp_header.add_run("Responsibility & Target Date")
    r_resp.bold = True
    r_resp.font.size = Pt(13)
    resp_header.paragraph_format.space_after = Pt(8)

    resp_matrix = data.get("responsibility_matrix") or []
    if not resp_matrix:
        for cat_item in points_discussed:
            c_name = cat_item.get("category_name") if isinstance(cat_item, dict) else "Discussion"
            resp_matrix.append({
                "category_name": c_name,
                "responsibility": "All Members",
                "target_date": "Continuous"
            })

    resp_table = doc.add_table(rows=1, cols=3)
    resp_table.style = "Table Grid"

    table_headers = ["Category", "Responsibility", "Target Date"]
    hdr_cells = resp_table.rows[0].cells
    for i, h in enumerate(table_headers):
        hdr_cells[i].text = h
        p_h = hdr_cells[i].paragraphs[0]
        p_h.alignment = WD_ALIGN_PARAGRAPH.LEFT
        r_h = p_h.runs[0]
        r_h.bold = True
        r_h.font.size = Pt(10)
        _set_cell_background(hdr_cells[i], "D9D9D9")

    for item in resp_matrix:
        if not isinstance(item, dict):
            continue

        row_cells = resp_table.add_row().cells
        
        row_cells[0].text = str(item.get("category_name") or "General")
        row_cells[1].text = str(item.get("responsibility") or "All")
        row_cells[2].text = str(item.get("target_date") or "Continuous")

        for c_idx in range(3):
            p_c = row_cells[c_idx].paragraphs[0]
            if len(p_c.runs) > 0:
                p_c.runs[0].font.size = Pt(9.5)

    doc.add_paragraph().paragraph_format.space_after = Pt(10)

    # ─────────────────────────────────────────
    # 6. INFORMATION ITEMS
    # ─────────────────────────────────────────
    info_header = doc.add_paragraph()
    r_info = info_header.add_run("Information Items")
    r_info.bold = True
    r_info.font.size = Pt(13)
    info_header.paragraph_format.space_after = Pt(8)

    info_items = data.get("information_items") or []
    if isinstance(info_items, str):
        info_items = [info_items]

    if not info_items:
        info_items = [
            "All members are requested to review the notes and complete assigned tasks.",
            "Schedule for the next review session will be communicated shortly."
        ]

    for idx, item in enumerate(info_items, start=1):
        p_item = doc.add_paragraph()
        r_num = p_item.add_run(f"{idx}. ")
        r_num.bold = True
        r_num.font.size = Pt(10)
        r_txt = p_item.add_run(str(item))
        r_txt.font.size = Pt(10)
        p_item.paragraph_format.space_after = Pt(3)

    doc.add_paragraph().paragraph_format.space_after = Pt(10)

    # ─────────────────────────────────────────
    # 7. DISTRIBUTION & SIGN-OFF
    # ─────────────────────────────────────────
    copy_to = data.get("copy_to") or ["All Members"]
    if isinstance(copy_to, str):
        copy_to = [copy_to]

    p_ct = doc.add_paragraph()
    r_ct = p_ct.add_run("Copy To:")
    r_ct.bold = True
    r_ct.font.size = Pt(10.5)
    p_ct.paragraph_format.space_after = Pt(3)

    for item in copy_to:
        p_c = doc.add_paragraph(style="List Bullet")
        r_c = p_c.add_run(str(item))
        r_c.font.size = Pt(10)
        p_c.paragraph_format.space_after = Pt(2)

    doc.add_paragraph().paragraph_format.space_after = Pt(4)

    copy_sub = data.get("copy_submitted_to") or ["Management"]
    if isinstance(copy_sub, str):
        copy_sub = [copy_sub]

    p_csub = doc.add_paragraph()
    r_csub = p_csub.add_run("Copy Submitted To:")
    r_csub.bold = True
    r_csub.font.size = Pt(10.5)
    p_csub.paragraph_format.space_after = Pt(3)

    for item in copy_sub:
        p_cs = doc.add_paragraph(style="List Bullet")
        r_cs = p_cs.add_run(str(item))
        r_cs.font.size = Pt(10)
        p_cs.paragraph_format.space_after = Pt(2)

    # SIGNATURE BLOCK
    p_sign_space = doc.add_paragraph()
    p_sign_space.paragraph_format.space_before = Pt(16)
    p_sign_space.paragraph_format.space_after = Pt(2)
    
    r_line = p_sign_space.add_run("_______________________________")
    r_line.bold = True

    sig_name = data.get("signatory_name") or "Meeting Secretary"
    sig_desig = data.get("signatory_designation") or "Convener"
    sig_date = data.get("signature_date") or data.get("date") or datetime.now().strftime("%d.%m.%Y")

    p_sig1 = doc.add_paragraph()
    r_s1 = p_sig1.add_run(str(sig_name))
    r_s1.bold = True
    r_s1.font.size = Pt(10.5)
    p_sig1.paragraph_format.space_after = Pt(2)

    p_sig2 = doc.add_paragraph()
    r_s2 = p_sig2.add_run(str(sig_desig))
    r_s2.italic = True
    r_s2.font.size = Pt(10)
    p_sig2.paragraph_format.space_after = Pt(2)

    p_sig3 = doc.add_paragraph()
    r_s3 = p_sig3.add_run(f"Date: {sig_date}")
    r_s3.bold = True
    r_s3.font.size = Pt(10)

    # SAVE DOCUMENT
    try:
        doc.save(path)
        print("[OK] Standard MoM DOCX saved:", path)
    except Exception as e:
        print("[ERROR] DOCX save failed:", e)
        raise




# ─────────────────────────────────────────────
# CELL BACKGROUND
# ─────────────────────────────────────────────
def _set_cell_background(cell, color):

    tc_pr = cell._tc.get_or_add_tcPr()

    shd = OxmlElement("w:shd")

    shd.set(qn("w:fill"), color)

    tc_pr.append(shd)


# ─────────────────────────────────────────────
# PAGE NUMBER
# ─────────────────────────────────────────────
def _add_page_number(paragraph):

    paragraph.add_run("Page ")

    # PAGE
    run = paragraph.add_run()

    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(
        qn("w:fldCharType"),
        "begin"
    )

    run._r.append(fld_begin)

    run = paragraph.add_run()

    instr = OxmlElement("w:instrText")
    instr.set(
        qn("xml:space"),
        "preserve"
    )

    instr.text = "PAGE"

    run._r.append(instr)

    run = paragraph.add_run()

    fld_end = OxmlElement("w:fldChar")

    fld_end.set(
        qn("w:fldCharType"),
        "end"
    )

    run._r.append(fld_end)

    paragraph.add_run(" of ")

    # NUMPAGES
    run = paragraph.add_run()

    fld_begin2 = OxmlElement("w:fldChar")

    fld_begin2.set(
        qn("w:fldCharType"),
        "begin"
    )

    run._r.append(fld_begin2)

    run = paragraph.add_run()

    instr2 = OxmlElement("w:instrText")

    instr2.set(
        qn("xml:space"),
        "preserve"
    )

    instr2.text = "NUMPAGES"

    run._r.append(instr2)

    run = paragraph.add_run()

    fld_end2 = OxmlElement("w:fldChar")

    fld_end2.set(
        qn("w:fldCharType"),
        "end"
    )

    run._r.append(fld_end2)

# ─────────────────────────────────────────────
# ONLINE SESSION DOCX GENERATION
# ─────────────────────────────────────────────
def _generate_online_session_docx(data: dict, path: str):
    doc = Document()

    # PAGE SETTINGS
    section = doc.sections[0]
    section.top_margin = Pt(45)
    section.bottom_margin = Pt(45)
    section.left_margin = Pt(50)
    section.right_margin = Pt(50)

    # FOOTER
    footer = section.footer
    footer_para = footer.paragraphs[0]
    footer_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _add_page_number(footer_para)

    # 1. MAIN TITLE
    title_para = doc.add_paragraph()
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    session_title = data.get("session_title") or "Session Notes"
    run = title_para.add_run(f"{session_title} — Session Notes")
    run.bold = True
    run.font.size = Pt(16)
    title_para.paragraph_format.space_after = Pt(14)

    # 2. METADATA
    meta_table = doc.add_table(rows=4, cols=2)
    meta_table.style = "Table Grid"

    meta_rows = [
        ("Instructor", data.get("instructor") or "Unknown"),
        ("Date", data.get("date") or datetime.now().strftime("%Y-%m-%d")),
        ("Duration", str(data.get("duration_minutes") or "Unknown")),
        ("Platform", data.get("platform") or "Google Meet"),
    ]

    for idx, (label, val) in enumerate(meta_rows):
        row_cells = meta_table.rows[idx].cells
        row_cells[0].text = str(label)
        row_cells[0].paragraphs[0].runs[0].bold = True
        _set_cell_background(row_cells[0], "F2F2F2")
        row_cells[1].text = str(val)

    doc.add_paragraph().paragraph_format.space_after = Pt(10)

    # 1. TOPICS COVERED
    header_topics = doc.add_paragraph()
    r_ht = header_topics.add_run("1. TOPICS COVERED")
    r_ht.bold = True
    r_ht.font.size = Pt(14)
    header_topics.paragraph_format.space_after = Pt(6)

    topics = data.get("topics_covered") or []
    for t_idx, topic in enumerate(topics, start=1):
        p_topic = doc.add_paragraph()
        p_topic.paragraph_format.space_before = Pt(14)
        p_topic.paragraph_format.space_after = Pt(4)
        r_tname = p_topic.add_run(f"1.{t_idx} {topic.get('topic_name') or 'Topic'}")
        r_tname.bold = True
        r_tname.font.size = Pt(12)
        
        summary = topic.get("summary")
        if summary:
            p_summ = doc.add_paragraph()
            p_summ.add_run("Summary: ").bold = True
            p_summ.add_run(str(summary))
            p_summ.paragraph_format.space_after = Pt(6)
        
        key_points = topic.get("key_points") or []
        if key_points:
            p_kp = doc.add_paragraph()
            p_kp.add_run("Key Points:").bold = True
            p_kp.paragraph_format.space_after = Pt(2)
            for kp in key_points:
                p_sub = doc.add_paragraph(style="List Bullet")
                p_sub.add_run(str(kp))
                p_sub.paragraph_format.space_after = Pt(2)
                
        defs = topic.get("definitions") or []
        if defs:
            p_def = doc.add_paragraph()
            p_def.add_run("Definitions:").bold = True
            p_def.paragraph_format.space_before = Pt(6)
            p_def.paragraph_format.space_after = Pt(2)
            for d in defs:
                p_sub = doc.add_paragraph(style="List Bullet")
                term = d.get("term") or ""
                explanation = d.get("explanation") or ""
                r_term = p_sub.add_run(f"{term} — ")
                r_term.bold = True
                p_sub.add_run(str(explanation))
                p_sub.paragraph_format.space_after = Pt(2)

        examples = topic.get("examples") or []
        if examples:
            p_ex = doc.add_paragraph()
            p_ex.add_run("Examples / Demonstrations:").bold = True
            p_ex.paragraph_format.space_before = Pt(6)
            p_ex.paragraph_format.space_after = Pt(2)
            for ex in examples:
                p_sub = doc.add_paragraph(style="List Bullet")
                p_sub.add_run(str(ex))
                p_sub.paragraph_format.space_after = Pt(2)

    # 2. DOUBTS & CLARIFICATIONS
    header_doubts = doc.add_paragraph()
    r_hd = header_doubts.add_run("2. DOUBTS & CLARIFICATIONS")
    r_hd.bold = True
    r_hd.font.size = Pt(14)
    
    doubts = data.get("doubts_and_clarifications") or []
    for d in doubts:
        q = d.get("question") or ""
        a = d.get("answer") or ""
        p_d = doc.add_paragraph(style="List Bullet")
        p_d.add_run("Q: ").bold = True
        p_d.add_run(f"{q}   ")
        p_d.add_run("A: ").bold = True
        p_d.add_run(str(a))
        
    doc.add_paragraph().paragraph_format.space_after = Pt(6)

    # 3. ASSIGNMENTS & FOLLOW-UPS
    header_assign = doc.add_paragraph()
    r_ha = header_assign.add_run("3. ASSIGNMENTS & FOLLOW-UPS")
    r_ha.bold = True
    r_ha.font.size = Pt(14)
    
    assignments = data.get("assignments_and_follow_ups") or []
    for a in assignments:
        desc = a.get("description") or ""
        due = a.get("due_date") or ""
        p_a = doc.add_paragraph(style="List Bullet")
        p_a.add_run("[ ] ")
        p_a.add_run(f"{desc}   ")
        p_a.add_run("Due: ").bold = True
        p_a.add_run(str(due))
        
    doc.add_paragraph().paragraph_format.space_after = Pt(6)

    # 4. RESOURCES REFERENCED
    header_res = doc.add_paragraph()
    r_hr = header_res.add_run("4. RESOURCES REFERENCED")
    r_hr.bold = True
    r_hr.font.size = Pt(14)
    
    resources = data.get("resources_referenced") or []
    for res in resources:
        doc.add_paragraph(str(res), style="List Bullet")
        
    doc.add_paragraph().paragraph_format.space_after = Pt(6)

    # 5. SESSION SUMMARY
    header_summ = doc.add_paragraph()
    r_hs = header_summ.add_run("5. SESSION SUMMARY")
    r_hs.bold = True
    r_hs.font.size = Pt(14)
    
    summ = data.get("session_summary") or ""
    doc.add_paragraph(str(summ))

    # SAVE DOCUMENT
    try:
        doc.save(path)
        print("[OK] Online Session DOCX saved:", path)
    except Exception as e:
        print("[ERROR] DOCX save failed:", e)
        raise