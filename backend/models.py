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


# ── MoM Item Models ─────────────────────────────────────────────
class AttendeeItem(BaseModel):
    title_or_name: str
    role: Optional[str] = None


class RepresentativeDiscussion(BaseModel):
    entity_name:        str
    points:             List[str] = []
    action_departments: Optional[List[str]] = []


class OfficerResponse(BaseModel):
    department_or_officer: str
    response:              str = ""
    points:                Optional[List[str]] = []


class SignatoryInfo(BaseModel):
    name:           Optional[str] = None
    designation:    Optional[str] = None
    location:       Optional[str] = None
    signature_date: Optional[str] = None


class CategoryDiscussion(BaseModel):
    category_name: str
    points:        List[str] = []


class ResponsibilityItem(BaseModel):
    category_name:  str
    responsibility: str = "All"
    target_date:    str = "Continuous"


# ── Universal Standard MoM Output Schema (Source-Grounded) ──────
class StandardMoMOutput(BaseModel):
    document_type:                Optional[str] = "mom"
    session_title:                Optional[str] = None  # No hardcoded default
    district_or_location:         Optional[str] = None  # No hardcoded default
    presided_by:                  Optional[str] = None
    convened_by:                  Optional[str] = None
    meeting_no:                   Optional[str] = None
    date:                         Optional[str] = None
    time:                         Optional[str] = None
    venue_platform:               Optional[str] = None  # No hardcoded default
    subject:                      Optional[str] = None
    reference:                    Optional[str] = None
    intro_paragraph:              Optional[str] = None
    opening_exhibition_or_remarks: Optional[str] = None

    # Attendees
    members_representatives:      Optional[List[str]] = None
    special_invitees_departments: Optional[List[str]] = None
    members_present:              Optional[List[str]] = None

    # Source-Grounded Content Sections
    topics_discussed:             Optional[List[str]] = None
    key_points:                   Optional[List[str]] = None
    decisions_taken:              Optional[List[str]] = None
    action_items:                 Optional[List[str]] = None

    # Agenda & Discussion Sections (only if present in source)
    welcome_address:              Optional[dict] = None
    chairperson_address:          Optional[List[str]] = None
    chairperson_suggestions:      Optional[List[str]] = None
    representative_points:        Optional[List[RepresentativeDiscussion]] = None
    officer_responses:            Optional[List[OfficerResponse]] = None
    vote_of_thanks:               Optional[str] = None

    # Signatories
    convener_signatory:           Optional[SignatoryInfo] = None
    chairperson_signatory:        Optional[SignatoryInfo] = None
    order_signatory:              Optional[SignatoryInfo] = None

    # Legacy & fallback compatibility
    points_discussed:             Optional[List[CategoryDiscussion]] = None
    responsibility_matrix:        Optional[List[ResponsibilityItem]] = None
    information_items:            Optional[List[str]] = None
    copy_to:                      Optional[List[str]] = None
    copy_submitted_to:            Optional[List[str]] = None
    signatory_name:               Optional[str] = None
    signatory_designation:        Optional[str] = None
    signature_date:               Optional[str] = None
    categories:                   Optional[List[dict]] = None


# ── Cross-Language Validation Report ───────────────────────────
class ValidationReport(BaseModel):
    status:               str = "PASS"  # PASS, WARNING, FAIL
    english_field_count:  int = 0
    tamil_field_count:    int = 0
    english_only_fields:  List[str] = []
    tamil_only_fields:    List[str] = []
    missing_translations: List[str] = []
    null_consistency:     bool = True


# ── /generate-mom ──────────────────────────────────────────────
class GenerateMomRequest(BaseModel):
    session_id: str
    language:   str = "en"  # "en" or "ta"
