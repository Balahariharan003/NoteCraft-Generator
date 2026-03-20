from typing import Dict, Any, List

# ── In-memory store ────────────────────────────────────────────
# Structure per session:
# sessions[session_id] = {
#   "status":          "processing" | "ready" | "failed",
#   "participants":    ["Priya", "Rahul", ...],
#   "speaker_timeline": [{ "name": "Priya", "timestamp_ms": 12000 }, ...],
#   "chunks": {
#       0: { "raw": "...", "clean": "...", "summary": "...", "status": "ok" | "failed" },
#       1: { ... },
#   },
#   "block_summaries": ["block 0 summary", "block 1 summary", ...],
#   "mom_json":        { ... },
#   "pdf_url":         "/outputs/session_id.pdf",
#   "docx_url":        "/outputs/session_id.docx",
# }

sessions: Dict[str, Any] = {}


# ── Create a new session ───────────────────────────────────────
def create_session(session_id: str, participants: List[str], speaker_timeline: List[dict]):
    sessions[session_id] = {
        "status":           "processing",
        "participants":     participants,
        "speaker_timeline": speaker_timeline,
        "chunks":           {},
        "block_summaries":  [],
        "mom_json":         None,
        "pdf_url":          None,
        "docx_url":         None,
    }


# ── Save a chunk's data ────────────────────────────────────────
def save_chunk(session_id: str, chunk_index: int, data: dict):
    if session_id not in sessions:
        return
    sessions[session_id]["chunks"][chunk_index] = data


# ── Get a single chunk ─────────────────────────────────────────
def get_chunk(session_id: str, chunk_index: int) -> dict:
    return sessions.get(session_id, {}).get("chunks", {}).get(chunk_index, {})


# ── Get all chunks in order ────────────────────────────────────
def get_all_chunks(session_id: str) -> List[dict]:
    chunks = sessions.get(session_id, {}).get("chunks", {})
    return [chunks[i] for i in sorted(chunks.keys())]


# ── Get failed chunk indexes ───────────────────────────────────
def get_failed_chunks(session_id: str) -> List[int]:
    chunks = sessions.get(session_id, {}).get("chunks", {})
    return [i for i, c in chunks.items() if c.get("status") == "failed"]


# ── Update session status ──────────────────────────────────────
def set_status(session_id: str, status: str):
    if session_id in sessions:
        sessions[session_id]["status"] = status


# ── Save block summaries ───────────────────────────────────────
def save_block_summaries(session_id: str, summaries: List[str]):
    if session_id in sessions:
        sessions[session_id]["block_summaries"] = summaries


# ── Save final MoM JSON ────────────────────────────────────────
def save_mom(session_id: str, mom_json: dict):
    if session_id in sessions:
        sessions[session_id]["mom_json"] = mom_json


# ── Save export file URLs ──────────────────────────────────────
def save_urls(session_id: str, pdf_url: str, docx_url: str):
    if session_id in sessions:
        sessions[session_id]["pdf_url"]  = pdf_url
        sessions[session_id]["docx_url"] = docx_url


# ── Get full session ───────────────────────────────────────────
def get_session(session_id: str) -> dict:
    return sessions.get(session_id, {})


# ── Delete session after download ─────────────────────────────
def delete_session(session_id: str):
    if session_id in sessions:
        del sessions[session_id]