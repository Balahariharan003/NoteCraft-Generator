from pydantic import BaseModel, field_validator
from typing import List, Optional


# ── /upload-chunk ──────────────────────────────────────────────
class SpeakerEvent(BaseModel):
    name: str
    timestamp_ms: int

    # Tolerate floats from JS (e.g. 12345.0 → 12345)
    @field_validator("timestamp_ms", mode="before")
    @classmethod
    def coerce_to_int(cls, v):
        return int(v)


class ChunkMeta(BaseModel):
    session_id:       str
    chunk_index:      int
    speaker_timeline: List[SpeakerEvent] = []
    participants:     List[str] = []


# ── /finalize ──────────────────────────────────────────────────
class FinalizeRequest(BaseModel):
    session_id:       str
    participants:     List[str] = []
    speaker_timeline: List[SpeakerEvent] = []

    # Tolerate speaker_timeline accidentally sent as JSON string
    @field_validator("speaker_timeline", mode="before")
    @classmethod
    def parse_timeline_string(cls, v):
        if isinstance(v, str):
            import json
            try:
                return json.loads(v)
            except Exception:
                return []
        return v

    # Tolerate participants accidentally sent as JSON string
    @field_validator("participants", mode="before")
    @classmethod
    def parse_participants_string(cls, v):
        if isinstance(v, str):
            import json
            try:
                return json.loads(v)
            except Exception:
                return []
        return v


# ── /status ────────────────────────────────────────────────────
class StatusResponse(BaseModel):
    session_id: str
    status:     str            # "processing" | "ready" | "failed"
    pdf_url:    Optional[str] = None
    docx_url:   Optional[str] = None


# ── Internal chunk data stored in session ──────────────────────
class ChunkData(BaseModel):
    raw:     str = ""
    clean:   str = ""
    summary: str = ""
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