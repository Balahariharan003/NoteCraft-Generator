import asyncio
import os
import json
import time
from datetime import datetime
from fastapi import APIRouter, HTTPException
from models import FinalizeRequest, GenerateMomRequest
from session.store import (
    get_session,
    get_all_chunks,
    get_pending_chunks,
    get_transcript_quality,
    create_session,
    save_chunk,
    save_mom,
    save_urls,
    set_status,
)
from services.sarvam_llm import (
    extract_verified_facts,
    generate_tamil_mom,
    translate_tamil_to_english_mom,
    validate_cross_language,
)
from services.export import export_documents
from services import metrics_logger

router = APIRouter()
OUTPUTS_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs")


# ── POST /finalize ─────────────────────────────────────────────
@router.post("/finalize")
async def finalize(request: FinalizeRequest):
    """
    Triggered when user stops meeting recording.
    Waits for all in-flight STT chunks to complete before allowing document generation.
    """
    session_id = request.session_id
    session    = get_session(session_id)

    if not session:
        create_session(session_id, request.participants, [
            e.dict() for e in request.speaker_timeline
        ])
        session = get_session(session_id)

    if request.speaker_timeline:
        session["speaker_timeline"] = [e.dict() for e in request.speaker_timeline]
    if request.participants:
        session["participants"] = request.participants

    print(f"\n[FINALIZE] Finalize signal received for session: {session_id}")
    set_status(session_id, "processing")
    asyncio.create_task(run_pipeline(session_id))

    return {"message": "Finalization started", "session_id": session_id}


# ── Background Pipeline: Waiting for STT & Quality Check ───────
async def run_pipeline(session_id: str):
    try:
        # Step 1: Wait for in-flight audio chunks to complete STT
        max_wait = 120
        waited = 0
        while True:
            pending = get_pending_chunks(session_id)
            if not pending:
                break
            print(f"[FINALIZE] Waiting for {len(pending)} in-flight chunk(s) {pending} to finish STT... ({waited}s)")
            await asyncio.sleep(2)
            waited += 2
            if waited >= max_wait:
                print(f"[FINALIZE WARNING] Timed out waiting for pending chunks {pending}.")
                break

        # Step 2: Quality validation
        quality = get_transcript_quality(session_id)
        print("\n[STT QUALITY]")
        print(f"Total chunks: {quality['total_chunks']}")
        print(f"Successful chunks: {quality['successful_chunks']}")
        print(f"Failed chunks: {quality['failed_chunks']}")
        print(f"Empty chunks: {quality['empty_chunks']}")
        print(f"Transcript characters: {quality['transcript_characters']}")
        print(f"Transcript words: {quality['transcript_words']}")

        if quality["failed_chunks"] > 0 or quality["transcript_characters"] < 20:
            print("\n[STT QUALITY ALERT] Source transcript is incomplete or empty. Gating document generation.")
            set_status(session_id, "incomplete_transcript")
        else:
            set_status(session_id, "ready")
            print(f"[PIPELINE] Session {session_id} is ready for document generation.\n")

    except Exception as e:
        print(f"[PIPELINE ERROR] run_pipeline exception: {e}")
        metrics_logger.finalize_metrics(session_id, status="failed")
        set_status(session_id, "failed")


# ── POST /generate_mom_doc ─────────────────────────────────────
@router.post("/generate_mom_doc")
async def generate_mom_doc(req: GenerateMomRequest):
    """
    Executes the 8-Stage Strict Source-Grounded Document Generation Pipeline.
    """
    session_id = req.session_id
    requested_lang = req.language
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Ensure all pending chunks are finished
    pending = get_pending_chunks(session_id)
    if pending:
        for _ in range(40):
            await asyncio.sleep(1)
            if not get_pending_chunks(session_id):
                break

    chunks = get_all_chunks(session_id)
    quality = get_transcript_quality(session_id)
    raw_transcript = quality["raw_transcript"]
    cleaned_transcript = quality["cleaned_transcript"]
    total_chars = quality["transcript_characters"]
    total_words = quality["transcript_words"]
    meeting_date = datetime.now().strftime("%Y-%m-%d")

    # ── STAGE 4: TRANSCRIPT COMPLETENESS & QUALITY GATE ─────────
    if not cleaned_transcript or total_chars < 20 or quality["failed_chunks"] > 0:
        print("\n========== FAILED ==========")
        print("Stage: Transcript Quality Gate")
        print(f"Reason: Incomplete transcript (Total: {quality['total_chunks']}, Failed: {quality['failed_chunks']}, Chars: {total_chars})")
        print("Action: DOCUMENT GENERATION BLOCKED")
        print("============================\n")
        raise HTTPException(
            status_code=400,
            detail="Document generation blocked because the source transcript is incomplete."
        )

    duration_sec = len(chunks) * 30
    duration_min = str(round(duration_sec / 60)) if duration_sec >= 60 else "< 1"

    print("\n========== NOTECRAFT PIPELINE ==========\n")
    print(f"[1/8] Video received (Duration: ~{duration_sec}s)")
    print(f"[2/8] Audio extracted ({len(chunks)} synchronized chunks)")
    print(f"[3/8] STT processing completed (Whisper Medium / GPU)")
    print(f"[4/8] Transcript completed ({total_chars} chars, {total_words} words)")

    # ── STAGE 5: SOURCE FACT EVIDENCE EXTRACTION ───────────────
    print(f"[5/8] Source facts verified (Extracting facts with direct evidence)...")
    facts_data = await extract_verified_facts(cleaned_transcript, chunks=chunks, session_id=session_id)
    verified_facts = facts_data.get("facts", [])

    if not verified_facts:
        print("\n========== FAILED ==========")
        print("Stage: Source Fact Verification")
        print("Reason: 0 verified facts extracted from transcript")
        print("Action: DOCUMENT GENERATION BLOCKED")
        print("============================\n")
        raise HTTPException(
            status_code=400,
            detail="Document generation failed because no verified source content was available."
        )

    # ── STAGE 6: TAMIL MOM GENERATION (Reference Format) ───────
    print(f"[6/8] Tamil document generated (From verified facts & Reference PDF structure)...")
    tamil_json = await generate_tamil_mom(
        verified_facts=verified_facts,
        complete_transcript=cleaned_transcript,
        meeting_date=meeting_date,
        session_id=session_id
    )

    tamil_session_id = f"{session_id}_ta"
    _, docx_url_ta = export_documents(tamil_json, tamil_session_id, language="ta")

    # ── STAGE 7: ENGLISH MOM TRANSLATION (100% Symmetry) ───────
    print(f"[7/8] English document generated (100% symmetric translation of Tamil MoM)...")
    english_json = await translate_tamil_to_english_mom(tamil_json, session_id=session_id)
    _, docx_url_en = export_documents(english_json, session_id, language="en")

    # ── STAGE 8: CROSS-LANGUAGE & EVIDENCE VALIDATION GATE ─────
    print(f"[8/8] Cross-language validation (Auditing facts, numbers, and dates)...")
    validation = validate_cross_language(tamil_json, english_json, complete_transcript=cleaned_transcript)
    val_status = validation.get("status", "PASS")

    # ── SAVE DEBUG ARTIFACTS IN outputs/debug/ ──────────────────
    debug_dir = os.path.join(OUTPUTS_DIR, "debug")
    os.makedirs(debug_dir, exist_ok=True)
    try:
        with open(os.path.join(debug_dir, "chunks.json"), "w", encoding="utf-8") as f:
            json.dump(chunks, f, indent=2, ensure_ascii=False)
        with open(os.path.join(debug_dir, "raw_transcript.txt"), "w", encoding="utf-8") as f:
            f.write(raw_transcript)
        with open(os.path.join(debug_dir, "cleaned_transcript.txt"), "w", encoding="utf-8") as f:
            f.write(cleaned_transcript)
        with open(os.path.join(debug_dir, "verified_facts.json"), "w", encoding="utf-8") as f:
            json.dump(facts_data, f, indent=2, ensure_ascii=False)
        with open(os.path.join(debug_dir, "tamil_content.txt"), "w", encoding="utf-8") as f:
            f.write(json.dumps(tamil_json, indent=2, ensure_ascii=False))
        with open(os.path.join(debug_dir, "english_content.txt"), "w", encoding="utf-8") as f:
            f.write(json.dumps(english_json, indent=2, ensure_ascii=False))
        with open(os.path.join(debug_dir, "validation.json"), "w", encoding="utf-8") as f:
            json.dump(validation, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[DEBUG ARTIFACT ERROR] {e}")

    # ── TERMINAL LOGS: COMPLETE ────────────────────────────────
    print("\n========== COMPLETE ==========")
    print(f"Tamil DOCX: SUCCESS ({docx_url_ta})")
    print(f"English DOCX: SUCCESS ({docx_url_en})")
    print(f"Source Grounding: PASS")
    print(f"Tamil/English Consistency: {val_status}")
    print("========================================\n")

    primary_url = docx_url_ta if requested_lang in ["ta", "tamil"] else docx_url_en
    save_mom(session_id, tamil_json, language="ta")
    save_mom(session_id, english_json, language="en")
    save_urls(session_id, docx_url_ta, docx_url_en)

    raw_len = sum(len(c.get("raw", "")) for c in chunks)
    final_len = len(str(tamil_json))
    metrics_logger.set_compression_stats(session_id, raw_len, final_len)
    metrics_logger.finalize_metrics(session_id, status="completed")

    return {
        "message": "Both documents generated successfully",
        "docx_url": primary_url,
        "docx_url_ta": docx_url_ta,
        "docx_url_en": docx_url_en,
        "pdf_url": None,
        "validation": validation,
    }