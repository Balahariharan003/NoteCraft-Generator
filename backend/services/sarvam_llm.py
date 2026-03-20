import os
import json
import httpx
from dotenv import load_dotenv

load_dotenv()

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
LLM_URL        = "https://api.sarvam.ai/v1/chat/completions"
MODEL          = "sarvam-m"


# ── Base LLM caller ────────────────────────────────────────────
async def _call_llm(system_prompt: str, user_prompt: str) -> str:
    """
    Sends a prompt to Sarvam-M.
    Returns the response text or empty string on failure.
    """
    if not SARVAM_API_KEY:
        raise ValueError("SARVAM_API_KEY not found in .env")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                LLM_URL,
                headers={
                    "api-subscription-key": SARVAM_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": user_prompt},
                    ],
                    "max_tokens": 1000,
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


# ── JOB 1: Clean transcript ────────────────────────────────────
async def clean_transcript(raw_transcript: str) -> str:
    """
    Removes fillers, ASR errors, repetitions.
    Preserves the original meaning.
    """
    system = (
        "You are a transcript editor. "
        "Clean the given transcript by removing filler words (uh, um, hmm, like), "
        "fixing obvious speech recognition errors, and removing repeated phrases. "
        "Do not summarise — preserve all content and meaning. "
        "Return only the cleaned transcript text, nothing else."
    )
    user = f"Clean this transcript:\n\n{raw_transcript}"

    cleaned = await _call_llm(system, user)
    return cleaned if cleaned else raw_transcript  # fallback to raw if LLM fails


# ── JOB 2: Segment summary with context carryover ─────────────
async def summarise_chunk(
    clean_transcript: str,
    prev_summary: str = "",
    chunk_index: int  = 0,
) -> str:
    """
    Summarises one 3-min chunk.
    Passes previous chunk summary as context so topics
    that span chunk boundaries are not lost.
    """
    system = (
        "You are a meeting assistant. "
        "Summarise the given meeting segment in 3 to 5 bullet points. "
        "Focus on: key discussion points, decisions made, and action items mentioned. "
        "Be concise. Each bullet should be one clear sentence."
    )

    context = ""
    if prev_summary and chunk_index > 0:
        context = f"Context from previous segment:\n{prev_summary}\n\n"

    user = (
        f"{context}"
        f"Summarise this meeting segment (segment {chunk_index + 1}):\n\n"
        f"{clean_transcript}"
    )

    return await _call_llm(system, user)


# ── JOB 3a: Mid-level aggregation (REDUCE) ────────────────────
async def aggregate_block(chunk_summaries: list, block_index: int) -> str:
    """
    Groups 5 chunk summaries into one block summary.
    Also extracts decisions and topics within the block.
    """
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

    user = (
        f"Merge these segment summaries into one block summary "
        f"(block {block_index + 1}):\n\n{summaries_text}"
    )

    return await _call_llm(system, user)


# ── JOB 3b: Final MoM generation ──────────────────────────────
async def generate_mom(
    block_summaries: list,
    participants: list,
    meeting_date: str,
) -> dict:
    """
    Takes all block summaries and generates the final
    structured MoM as JSON.
    """
    system = (
        "You are a professional meeting secretary. "
        "Generate a structured Minutes of Meeting (MoM) from the given meeting summaries. "
        "Return ONLY valid JSON with no extra text, no markdown, no code blocks. "
        "The JSON must have exactly these keys: "
        "title, date, participants, agenda, discussions, decisions, action_items. "
        "action_items must be a list of objects with keys: owner, task, deadline."
    )

    summaries_text = "\n\n".join(
        [f"Block {i+1}:\n{s}" for i, s in enumerate(block_summaries)]
    )

    user = (
        f"Meeting date: {meeting_date}\n"
        f"Participants: {', '.join(participants)}\n\n"
        f"Meeting summaries:\n{summaries_text}\n\n"
        f"Generate the MoM JSON now."
    )

    raw = await _call_llm(system, user)

    # Parse JSON safely
    try:
        mom_json = json.loads(raw)
        return mom_json
    except json.JSONDecodeError:
        # Try to extract JSON from response if LLM added extra text
        try:
            start = raw.index("{")
            end   = raw.rindex("}") + 1
            mom_json = json.loads(raw[start:end])
            return mom_json
        except Exception:
            print("Failed to parse MoM JSON from LLM response")
            return _fallback_mom(participants, meeting_date)


# ── JOB 4: Refinement pass ─────────────────────────────────────
async def refine_mom(mom_json: dict) -> dict:
    """
    Accurate mode only.
    Improves clarity, removes duplicates, fixes contradictions.
    """
    system = (
        "You are a professional editor. "
        "Improve the given Minutes of Meeting JSON. "
        "Fix grammar, remove duplicate points, improve clarity. "
        "Return ONLY valid JSON with the same structure. No extra text."
    )

    user = f"Refine this MoM JSON:\n\n{json.dumps(mom_json, indent=2)}"

    raw = await _call_llm(system, user)

    try:
        return json.loads(raw)
    except Exception:
        return mom_json  # fallback to original if refinement fails


# ── Fallback MoM if JSON parsing fails ────────────────────────
def _fallback_mom(participants: list, date: str) -> dict:
    return {
        "title":        "Minutes of Meeting",
        "date":         date,
        "participants": participants,
        "agenda":       ["Could not extract agenda"],
        "discussions":  ["Could not extract discussions"],
        "decisions":    ["Could not extract decisions"],
        "action_items": [],
    }