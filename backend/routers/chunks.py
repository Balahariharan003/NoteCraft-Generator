import json
import asyncio
import time
import os
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from session.store import save_chunk, get_session, create_session
from services.sarvam_stt import transcribe_chunk
from services.sarvam_llm import clean_transcript

router = APIRouter()

# ── POST /upload-chunk ─────────────────────────────────────────
@router.post("/upload-chunk")
async def upload_chunk(
    audio:            UploadFile = File(...),
    session_id:       str        = Form(...),
    chunk_index:      int        = Form(...),
    speaker_timeline: str        = Form(default="[]"),
    participants:     str        = Form(default="[]"),
):
    """
    Receives a single merged audio chunk (tab + mic) from the extension.
    """
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    try:
        timeline = json.loads(speaker_timeline)
        participants_list = json.loads(participants)
    except json.JSONDecodeError:
        timeline = []
        participants_list = []

    session = get_session(session_id)
    if not session:
        create_session(session_id, participants_list, timeline)
        session = get_session(session_id)

    audio_bytes = await audio.read()
    if len(audio_bytes) == 0:
        raise HTTPException(status_code=400, detail="Empty audio file received")

    start_sec = chunk_index * 30
    end_sec = (chunk_index + 1) * 30
    start_str = f"{start_sec // 60:02d}:{start_sec % 60:02d}"
    end_str = f"{end_sec // 60:02d}:{end_sec % 60:02d}"

    print(f"\n[PIPELINE] Chunk {chunk_index} ({start_str}-{end_str}) received: {len(audio_bytes)}B")

    # Save chunk as pending immediately with full metadata schema
    save_chunk(session_id, chunk_index, {
        "chunk_id":   chunk_index,
        "start_time": start_str,
        "end_time":   end_str,
        "raw":         "",
        "clean":       "",
        "transcript":  "",
        "characters":  0,
        "words":       [],
        "status":      "pending",
        "language":    "unknown",
        "error":       None,
    })

    # Process chunk in background
    asyncio.create_task(
        process_chunk(session_id, chunk_index, start_sec, end_sec, audio_bytes)
    )

    return {
        "message":     "Chunk received",
        "session_id":  session_id,
        "chunk_index": chunk_index,
        "start_time":  start_str,
        "end_time":    end_str,
    }


# ── Background STT & Cleaning Worker ────────────────────────────
async def process_chunk(session_id: str, chunk_index: int, start_sec: int, end_sec: int, audio_bytes: bytes):
    t_start = time.time()
    start_str = f"{start_sec // 60:02d}:{start_sec % 60:02d}"
    end_str = f"{end_sec // 60:02d}:{end_sec % 60:02d}"

    try:
        session = get_session(session_id)
        lang_hint = session.get("language_hint", None) if session else None

        # ── Step 1: Whisper STT (Protected by GPU Queue Lock) ──
        stt_result = await transcribe_chunk(
            audio_bytes,
            chunk_index=chunk_index,
            start_time_sec=start_sec,
            end_time_sec=end_sec,
            language_hint=lang_hint
        )

        status = stt_result.get("status", "failed")
        raw_transcript = stt_result.get("transcript", "")
        chunk_lang = stt_result.get("language", "unknown")
        words = stt_result.get("words", [])
        char_count = len(raw_transcript)

        if status == "failed":
            print(f"[STT FAILED] Chunk {chunk_index} ({start_str}-{end_str}): {stt_result.get('error')}")
            save_chunk(session_id, chunk_index, {
                "chunk_id":   chunk_index,
                "start_time": start_str,
                "end_time":   end_str,
                "raw":         "",
                "clean":       "",
                "transcript":  "",
                "characters":  0,
                "words":       [],
                "status":      "failed",
                "language":    chunk_lang,
                "error":       stt_result.get("error"),
            })
            return

        # Pin language in session if detected as Tamil or English
        if session and chunk_lang in ["ta", "en"] and not session.get("language_hint"):
            session["language_hint"] = chunk_lang

        # ── Step 2: Clean transcript (preserve raw verbatim separately) ──
        cleaned_transcript = raw_transcript
        if raw_transcript and len(raw_transcript.strip()) > 5:
            cleaned_transcript = await clean_transcript(raw_transcript, session_id=session_id)

        # ── Save all results with full metadata ─────────────────
        save_chunk(session_id, chunk_index, {
            "chunk_id":   chunk_index,
            "start_time": start_str,
            "end_time":   end_str,
            "raw":         raw_transcript,
            "clean":       cleaned_transcript,
            "transcript":  cleaned_transcript,
            "characters":  char_count,
            "words":       words,
            "status":      "success" if char_count > 0 else "empty",
            "language":    chunk_lang,
            "error":       None,
        })

        total_elapsed = time.time() - t_start
        print(f"[OK] Chunk {chunk_index} ({start_str}-{end_str}) processed in {total_elapsed:.2f}s | {char_count} chars | Lang: {chunk_lang}")

    except Exception as e:
        print(f"[PIPELINE ERROR] Chunk {chunk_index} exception: {e}")
        save_chunk(session_id, chunk_index, {
            "chunk_id":   chunk_index,
            "start_time": start_str,
            "end_time":   end_str,
            "raw":         "",
            "clean":       "",
            "transcript":  "",
            "characters":  0,
            "words":       [],
            "status":      "failed",
            "language":    "unknown",
            "error":       str(e),
        })