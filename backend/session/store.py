from typing import Dict, Any, List, Optional

# ── In-memory store ────────────────────────────────────────────
sessions: Dict[str, Any] = {}


def create_session(session_id: str, participants: List[str], speaker_timeline: List[dict]):
    sessions[session_id] = {
        "status":             "processing",
        "participants":       participants,
        "speaker_timeline":   speaker_timeline,
        "chunks":             {},
        "raw_transcript":     "",
        "cleaned_transcript": "",
        "verified_facts":     [],
        "mom_json_ta":        None,
        "mom_json_en":        None,
        "docx_url_ta":        None,
        "docx_url_en":        None,
        "language_hint":      None,
    }


def save_chunk(session_id: str, chunk_index: int, data: dict):
    if session_id not in sessions:
        create_session(session_id, [], [])
    sessions[session_id]["chunks"][chunk_index] = data


def get_chunk(session_id: str, chunk_index: int) -> dict:
    return sessions.get(session_id, {}).get("chunks", {}).get(chunk_index, {})


def get_all_chunks(session_id: str) -> List[dict]:
    chunks = sessions.get(session_id, {}).get("chunks", {})
    return [chunks[i] for i in sorted(chunks.keys())]


def get_pending_chunks(session_id: str) -> List[int]:
    chunks = sessions.get(session_id, {}).get("chunks", {})
    return [i for i, c in chunks.items() if c.get("status") == "pending"]


def get_failed_chunks(session_id: str) -> List[int]:
    chunks = sessions.get(session_id, {}).get("chunks", {})
    return [i for i, c in chunks.items() if c.get("status") == "failed"]


def get_transcript_quality(session_id: str) -> dict:
    chunks = get_all_chunks(session_id)
    total_chunks = len(chunks)
    successful_chunks = len([c for c in chunks if c.get("status") in ["ok", "success"] and c.get("transcript")])
    empty_chunks = len([c for c in chunks if c.get("status") == "empty" or not c.get("transcript")])
    failed_chunks = len([c for c in chunks if c.get("status") == "failed"])

    # Aggregate transcripts
    raw_segments = [c.get("raw") or c.get("transcript", "") for c in chunks if c.get("raw") or c.get("transcript")]
    raw_text = "\n".join([s.strip() for s in raw_segments if s.strip()]).strip()
    
    clean_segments = [c.get("clean") or c.get("raw") or c.get("transcript", "") for c in chunks if c.get("clean") or c.get("raw") or c.get("transcript")]
    clean_text = "\n".join([s.strip() for s in clean_segments if s.strip()]).strip()

    char_count = len(clean_text)
    word_count = len(clean_text.split()) if clean_text else 0

    is_complete = total_chunks > 0 and failed_chunks == 0 and char_count >= 20

    return {
        "total_chunks":          total_chunks,
        "successful_chunks":     successful_chunks,
        "failed_chunks":         failed_chunks,
        "empty_chunks":          empty_chunks,
        "transcript_characters": char_count,
        "transcript_words":      word_count,
        "raw_transcript":        raw_text,
        "cleaned_transcript":    clean_text,
        "is_complete":           is_complete,
    }


def set_status(session_id: str, status: str):
    if session_id in sessions:
        sessions[session_id]["status"] = status


def save_mom(session_id: str, mom_json: dict, language: str = "ta"):
    if session_id in sessions:
        if language in ["ta", "tamil"]:
            sessions[session_id]["mom_json_ta"] = mom_json
        else:
            sessions[session_id]["mom_json_en"] = mom_json


def save_urls(session_id: str, docx_url_ta: str, docx_url_en: str):
    if session_id in sessions:
        sessions[session_id]["docx_url_ta"] = docx_url_ta
        sessions[session_id]["docx_url_en"] = docx_url_en


def get_session(session_id: str) -> Optional[dict]:
    return sessions.get(session_id, None)


def delete_session(session_id: str):
    if session_id in sessions:
        del sessions[session_id]