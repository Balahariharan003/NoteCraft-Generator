from pydantic import BaseModel
from typing import List, Optional


# ── /upload-chunk ──────────────────────────────────────────────
# audio file comes as multipart/form-data (handled in router)
# these fields come alongside the file as form fields

class SpeakerEvent(BaseModel):
    name: str
    timestamp_ms: int  # milliseconds from recording start


class ChunkMeta(BaseModel):
    session_id:      str
    chunk_index:     int
    speaker_timeline: List[SpeakerEvent] = []
    participants:    List[str] = []


# ── /finalize ─────────────────────────────────────────────────
class FinalizeRequest(BaseModel):
    session_id:      str
    participants:    List[str] = []
    speaker_timeline: List[SpeakerEvent] = []


# ── /status ───────────────────────────────────────────────────
class StatusResponse(BaseModel):
    session_id: str
    status:     str            # "processing" | "ready" | "failed"
    pdf_url:    Optional[str] = None
    docx_url:   Optional[str] = None


# ── Internal chunk data stored in session ─────────────────────
class ChunkData(BaseModel):
    raw:     str = ""          # raw transcript from Sarvam STT
    clean:   str = ""          # cleaned transcript from Sarvam-M
    summary: str = ""          # segment summary from Sarvam-M
    status:  str = "pending"   # "pending" | "ok" | "failed"


# ── Final MoM JSON structure ───────────────────────────────────
class ActionItem(BaseModel):
    owner:    str
    task:     str
    deadline: Optional[str] = None


class MoMOutput(BaseModel):
    title:        str
    date:         str
    participants: List[str]
    agenda:       List[str]
    discussions:  List[str]
    decisions:    List[str]
    action_items: List[ActionItem]