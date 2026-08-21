from pydantic import BaseModel, field_validator
from typing import List, Optional


# ── /upload-chunk ──────────────────────────────────────────────
class SpeakerEvent(BaseModel):
    name: str
    timestamp_ms: int

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
    status:     str
    pdf_url:    Optional[str] = None
    docx_url:   Optional[str] = None


# ── Internal chunk data ────────────────────────────────────────
class ChunkData(BaseModel):
    raw:     str = ""
    clean:   str = ""
    summary: str = ""
    status:  str = "pending"


# ── MoM Category Discussion ─────────────────────────────────────
class CategoryDiscussion(BaseModel):
    category_name: str
    points:        List[str] = []


# ── Responsibility & Target Date Item ───────────────────────────
class ResponsibilityItem(BaseModel):
    category_name:  str
    responsibility: str = "All"
    target_date:    str = "Continuous"


# ── Universal Standard MoM Output Schema ────────────────────────
class StandardMoMOutput(BaseModel):
    # Metadata Header
    session_title:       Optional[str] = "Minutes of the Meeting"
    meeting_no:          Optional[str] = None
    date:                Optional[str] = None
    time:                Optional[str] = None
    venue_platform:      Optional[str] = "Google Meet"

    # Attendees
    members_present:     Optional[List[str]] = None

    # Discussion & Action Sections
    points_discussed:      Optional[List[CategoryDiscussion]] = None
    responsibility_matrix: Optional[List[ResponsibilityItem]] = None
    information_items:     Optional[List[str]] = None

    # Distribution & Sign-off
    copy_to:             Optional[List[str]] = None
    copy_submitted_to:   Optional[List[str]] = None
    signatory_name:      Optional[str] = None
    signatory_designation: Optional[str] = None
    signature_date:      Optional[str] = None

    # Legacy fields mapping compatibility
    categories:          Optional[List[dict]] = None