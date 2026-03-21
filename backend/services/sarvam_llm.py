import os
import json
import httpx
from dotenv import load_dotenv

load_dotenv()

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
LLM_URL        = "https://api.sarvam.ai/v1/chat/completions"
MODEL          = "sarvam-m"


# ── Base LLM caller ────────────────────────────────────────────
async def _call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 1500) -> str:
    if not SARVAM_API_KEY:
        raise ValueError("SARVAM_API_KEY not found in .env")

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                LLM_URL,
                headers={
                    "api-subscription-key": SARVAM_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "model":       MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": user_prompt},
                    ],
                    "max_tokens":  max_tokens,
                    "temperature": 0.3,
                },
            )

        if response.status_code != 200:
            print(f"LLM error: {response.status_code} {response.text}")
            return ""

        result  = response.json()
        content = result["choices"][0]["message"]["content"]
        return content.strip()

    except httpx.TimeoutException:
        print("LLM request timed out")
        return ""
    except Exception as e:
        print(f"LLM unexpected error: {e}")
        return ""


# ── Parse JSON safely from LLM output ─────────────────────────
def _parse_json(raw: str) -> dict | None:
    if not raw:
        return None
    clean = raw.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        clean = "\n".join(lines[1:-1]) if len(lines) > 2 else clean
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass
    try:
        start = clean.index("{")
        end   = clean.rindex("}") + 1
        return json.loads(clean[start:end])
    except Exception:
        return None


# ── Validate and fix MoM JSON structure ───────────────────────
def _validate_mom(mom: dict, participants: list, date: str) -> dict:
    def to_list(val, fallback: list) -> list:
        if isinstance(val, list):
            cleaned = [str(v).strip() for v in val if str(v).strip() and len(str(v).strip()) > 1]
            return cleaned if cleaned else fallback
        if isinstance(val, str) and len(val) > 1:
            return [val]
        return fallback

    def to_action_items(val) -> list:
        if not isinstance(val, list):
            return []
        result = []
        for item in val:
            if isinstance(item, dict):
                result.append({
                    "owner":    str(item.get("owner", "TBD")),
                    "task":     str(item.get("task", "-")),
                    "deadline": str(item.get("deadline", "TBD")),
                })
        return result

    return {
        "title":           str(mom.get("title", "Minutes of Meeting")),
        "date":            str(mom.get("date", date)),
        "time":            str(mom.get("time", "Not specified")),
        "mode_of_meeting": "Online (Google Meet)",
        "prepared_by":     "MoM Generator",
        "participants":    to_list(
                               mom.get("participants", participants),
                               participants or ["Participants not identified"]),
        "agenda":          to_list(
                               mom.get("agenda", []),
                               ["Agenda not specified"]),
        "key_discussions": to_list(
                               mom.get("key_discussions",
                               mom.get("discussions", [])),
                               ["No discussions recorded"]),
        "decisions_taken": to_list(
                               mom.get("decisions_taken",
                               mom.get("decisions", [])),
                               ["No decisions recorded"]),
        "action_items":    to_action_items(mom.get("action_items", [])),
    }


# ── JOB 1: Clean transcript ────────────────────────────────────
async def clean_transcript(raw_transcript: str) -> str:
    system = (
        "You are a transcript editor. "
        "Clean the given transcript by removing filler words (uh, um, hmm, like), "
        "fixing obvious speech recognition errors, and removing repeated phrases. "
        "Do not summarise — preserve all content and meaning. "
        "Return only the cleaned transcript text, nothing else."
    )
    user    = f"Clean this transcript:\n\n{raw_transcript}"
    cleaned = await _call_llm(system, user)
    return cleaned if cleaned else raw_transcript


# ── JOB 2: Segment summary ─────────────────────────────────────
async def summarise_chunk(
    clean_transcript: str,
    prev_summary:     str = "",
    chunk_index:      int = 0,
) -> str:
    system = (
        "You are a meeting assistant. "
        "Summarise the given meeting segment in 3 to 5 bullet points. "
        "Focus on: key discussion points, decisions made, and action items mentioned. "
        "Be concise. Each bullet should be one clear sentence."
    )
    context = (
        f"Context from previous segment:\n{prev_summary}\n\n"
        if prev_summary and chunk_index > 0 else ""
    )
    user = f"{context}Summarise this meeting segment (segment {chunk_index + 1}):\n\n{clean_transcript}"
    return await _call_llm(system, user)


# ── JOB 3a: Block aggregation ──────────────────────────────────
async def aggregate_block(chunk_summaries: list, block_index: int) -> str:
    system = (
        "You are a meeting assistant. "
        "You are given several 3-minute meeting segment summaries. "
        "Merge them into one coherent block summary. "
        "Remove redundancy. Extract any clear decisions made. "
        "Return a clean paragraph-style summary in 4 to 6 sentences."
    )
    summaries_text = "\n\n".join(
        [f"Segment {i+1}:\n{s}" for i, s in enumerate(chunk_summaries)]
    )
    user = f"Merge these segment summaries into one block summary (block {block_index + 1}):\n\n{summaries_text}"
    return await _call_llm(system, user)


# ── JOB 3b: Final MoM generation ──────────────────────────────
async def generate_mom(
    block_summaries: list,
    participants:    list,
    meeting_date:    str,
) -> dict:
    system = (
        "You are a professional meeting secretary. "
        "Generate a structured Minutes of Meeting (MoM) from the given meeting summaries. "
        "Return ONLY valid JSON — no markdown, no code blocks, no extra text. "
        "The JSON must have exactly these keys:\n"
        "  title           → string: descriptive meeting title\n"
        "  date            → string: meeting date\n"
        "  time            → string: meeting time or 'Not specified'\n"
        "  participants    → array of strings: participant names\n"
        "  agenda          → array of strings: each agenda item as a full sentence\n"
        "  key_discussions → array of strings: each discussion point as a full sentence\n"
        "  decisions_taken → array of strings: each decision as a full sentence\n"
        "  action_items    → array of objects with keys: owner, task, deadline\n"
        "IMPORTANT: Every array must contain complete sentences, never single characters."
    )

    summaries_text = "\n\n".join(
        [f"Block {i+1}:\n{s}" for i, s in enumerate(block_summaries)]
    )
    user = (
        f"Meeting date: {meeting_date}\n"
        f"Participants: {', '.join(participants) if participants else 'Unknown'}\n\n"
        f"Meeting summaries:\n{summaries_text}\n\n"
        f"Generate the MoM JSON now. Remember: arrays must contain full sentences, not characters."
    )

    raw    = await _call_llm(system, user, max_tokens=2000)
    parsed = _parse_json(raw)

    if parsed:
        return _validate_mom(parsed, participants, meeting_date)

    print("Failed to parse MoM JSON — using fallback")
    return _fallback_mom(participants, meeting_date)


# ── JOB 4: Refinement pass ────────────────────────────────────
async def refine_mom(mom_json: dict) -> dict:
    system = (
        "You are a professional editor. "
        "Improve the given Minutes of Meeting JSON. "
        "Fix grammar, remove duplicate points, improve clarity. "
        "Ensure all array fields contain complete sentences, never single characters. "
        "Return ONLY valid JSON with the same structure. No extra text, no markdown."
    )
    user   = f"Refine this MoM JSON:\n\n{json.dumps(mom_json, indent=2)}"
    raw    = await _call_llm(system, user, max_tokens=2000)
    parsed = _parse_json(raw)

    if parsed:
        return _validate_mom(
            parsed,
            mom_json.get("participants", []),
            mom_json.get("date", ""),
        )
    return mom_json


# ── Fallback MoM ──────────────────────────────────────────────
def _fallback_mom(participants: list, date: str) -> dict:
    return {
        "title":           "Minutes of Meeting",
        "date":            date,
        "time":            "Not specified",
        "mode_of_meeting": "Online (Google Meet)",
        "prepared_by":     "MoM Generator",
        "participants":    participants or ["Participants not identified"],
        "agenda":          ["Agenda could not be extracted"],
        "key_discussions": ["Discussions could not be extracted"],
        "decisions_taken": ["Decisions could not be extracted"],
        "action_items":    [],
    }