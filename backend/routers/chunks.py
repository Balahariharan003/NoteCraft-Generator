import json
import asyncio
import os
import tempfile
import subprocess
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from session.store import save_chunk, get_session, create_session
from services.sarvam_stt import transcribe_chunk
from services.sarvam_llm import clean_transcript, summarise_chunk

router = APIRouter()


# ── Merge tab audio + mic audio using ffmpeg ───────────────────
def merge_audio_files(tab_bytes: bytes, mic_bytes: bytes) -> bytes:
    """
    Merges tab audio (friends' voices) with mic audio (your voice)
    using ffmpeg's amix filter. Returns the merged WAV/WebM bytes.
    """
    tmp_tab = tmp_mic = tmp_out = None
    try:
        # Write tab audio to temp file
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
            f.write(tab_bytes)
            tmp_tab = f.name

        # Write mic audio to temp file
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
            f.write(mic_bytes)
            tmp_mic = f.name

        tmp_out = tmp_tab.replace(".webm", "_merged.webm")

        # Use ffmpeg amix to merge the two audio streams
        # The mic is boosted by 2x to ensure user's voice is clear
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", tmp_tab,
                "-i", tmp_mic,
                "-filter_complex",
                "[0:a]volume=1.0[tab];[1:a]volume=2.0[mic];[tab][mic]amix=inputs=2:duration=longest:dropout_transition=2[out]",
                "-map", "[out]",
                "-ac", "1",
                "-ar", "16000",
                "-f", "webm",
                tmp_out
            ],
            capture_output=True, timeout=120,
        )

        if result.returncode != 0:
            print(f"ffmpeg merge error: {result.stderr.decode()[-500:]}")
            # Fall back to tab audio only
            return tab_bytes

        with open(tmp_out, "rb") as f:
            merged = f.read()

        print(f"Audio merge: tab={len(tab_bytes)}B + mic={len(mic_bytes)}B → merged={len(merged)}B")
        return merged

    except Exception as e:
        print(f"Audio merge failed: {e}")
        return tab_bytes  # Fall back to tab audio only
    finally:
        for p in [tmp_tab, tmp_mic, tmp_out]:
            try:
                if p and os.path.exists(p):
                    os.unlink(p)
            except Exception:
                pass


# ── POST /upload-chunk ─────────────────────────────────────────
@router.post("/upload-chunk")
async def upload_chunk(
    audio:           UploadFile = File(...),
    session_id:      str        = Form(...),
    chunk_index:     int        = Form(...),
    speaker_timeline: str       = Form(default="[]"),
    participants:    str        = Form(default="[]"),
    mic_audio:       UploadFile = File(default=None),
):
    """
    Receives one audio chunk from the extension.
    If mic_audio is provided, merges it with the tab audio before processing.
    """

    # ── Validate ───────────────────────────────────────────────
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    # ── Parse JSON strings from form fields ───────────────────
    try:
        timeline     = json.loads(speaker_timeline)
        participants_list = json.loads(participants)
    except json.JSONDecodeError:
        timeline          = []
        participants_list = []

    # ── Create session if first chunk ─────────────────────────
    session = get_session(session_id)
    if not session:
        create_session(session_id, participants_list, timeline)

    # ── Read audio bytes ───────────────────────────────────────
    audio_bytes = await audio.read()

    if len(audio_bytes) == 0:
        raise HTTPException(status_code=400, detail="Empty audio file received")

    # ── Merge mic audio if present ─────────────────────────────
    if mic_audio is not None:
        mic_bytes = await mic_audio.read()
        if len(mic_bytes) > 100:
            print(f"Chunk {chunk_index}: Merging tab ({len(audio_bytes)}B) + mic ({len(mic_bytes)}B)")
            audio_bytes = merge_audio_files(audio_bytes, mic_bytes)
        else:
            print(f"Chunk {chunk_index}: Mic audio too small ({len(mic_bytes)}B), using tab only")
    else:
        print(f"Chunk {chunk_index}: No mic audio, using tab only ({len(audio_bytes)}B)")

    # ── Save chunk as pending immediately ─────────────────────
    save_chunk(session_id, chunk_index, {
        "chunk_index": chunk_index,
        "raw":         "",
        "clean":       "",
        "summary":     "",
        "words":       [],
        "status":      "pending",
    })

    # ── Process chunk in background ───────────────────────────
    asyncio.create_task(
        process_chunk(session_id, chunk_index, audio_bytes)
    )

    return {
        "message":     "Chunk received",
        "session_id":  session_id,
        "chunk_index": chunk_index,
    }


# ── Background task: STT → clean → summarise ──────────────────
async def process_chunk(session_id: str, chunk_index: int, audio_bytes: bytes):
    """
    Runs in the background while the meeting continues.
    Steps:
        1. STT  — get raw transcript + word timestamps
        2. Clean — remove fillers and ASR errors
        3. Summarise — 3-5 bullet summary with context carryover
    """
    try:
        # ── Step 1: Speech to text ─────────────────────────────
        stt_result = await transcribe_chunk(audio_bytes, chunk_index)

        if stt_result["status"] == "failed":
            save_chunk(session_id, chunk_index, {
                "chunk_index": chunk_index,
                "raw":         "",
                "clean":       "",
                "summary":     "",
                "words":       [],
                "status":      "failed",
            })
            return

        raw_transcript = stt_result["transcript"]
        words          = stt_result["words"]

        # ── Step 2: Clean transcript ───────────────────────────
        cleaned = await clean_transcript(raw_transcript)

        # ── Step 3: Get previous chunk summary for context ─────
        prev_summary = _get_prev_summary(session_id, chunk_index)

        # ── Step 4: Summarise this chunk ───────────────────────
        summary = await summarise_chunk(
            clean_transcript=cleaned,
            prev_summary=prev_summary,
            chunk_index=chunk_index,
        )

        # ── Save all results ───────────────────────────────────
        save_chunk(session_id, chunk_index, {
            "chunk_index": chunk_index,
            "raw":         raw_transcript,
            "clean":       cleaned,
            "summary":     summary,
            "words":       words,
            "status":      "ok",
        })

        print(f"Chunk {chunk_index} processed successfully for session {session_id}")

    except Exception as e:
        print(f"Chunk {chunk_index} processing error: {e}")
        save_chunk(session_id, chunk_index, {
            "chunk_index": chunk_index,
            "raw":         "",
            "clean":       "",
            "summary":     "",
            "words":       [],
            "status":      "failed",
        })


# ── Get previous chunk summary for context carryover ──────────
def _get_prev_summary(session_id: str, chunk_index: int) -> str:
    if chunk_index == 0:
        return ""
    from session.store import get_chunk
    prev = get_chunk(session_id, chunk_index - 1)
    return prev.get("summary", "")