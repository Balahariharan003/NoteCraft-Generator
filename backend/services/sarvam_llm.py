import os
import json
import httpx
from dotenv import load_dotenv

load_dotenv()

LLM_URL        = "http://localhost:11434/v1/chat/completions"
MODEL          = "qwen2.5:3b"


# ── Base LLM caller ────────────────────────────────────────────
async def _call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 2000, json_mode: bool = False) -> str:
    try:
        # Increased timeout to 300.0s for local Ollama running on laptop GPU
        async with httpx.AsyncClient(timeout=300.0) as client:
            payload = {
                "model":       MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                "max_tokens":  max_tokens,
                "temperature": 0.3,
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}

            response = await client.post(
                LLM_URL,
                headers={
                    "Content-Type": "application/json",
                },
                json=payload,
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


# ── Parse JSON safely ──────────────────────────────────────────
def _parse_json(raw: str) -> dict | None:
    if not raw:
        return None
    clean = raw.strip()
    
    # Extract content between first '{' and last '}'
    try:
        start = clean.index("{")
        end   = clean.rindex("}") + 1
        json_content = clean[start:end]
    except ValueError:
        return None

    # Handle unescaped control characters (newlines, tabs) inside string literals inline
    result = []
    in_string = False
    escape = False
    for char in json_content:
        if char == '"' and not escape:
            in_string = not in_string
            result.append(char)
        elif char == '\\' and in_string:
            escape = not escape
            result.append(char)
        else:
            if escape:
                escape = False
            if char == '\n' and in_string:
                result.append('\\n')
            elif char == '\r' and in_string:
                result.append('\\r')
            elif char == '\t' and in_string:
                result.append('\\t')
            else:
                result.append(char)
    json_content = "".join(result)

    # Try parsing standard JSON
    try:
        return json.loads(json_content)
    except json.JSONDecodeError:
        pass

    # Try removing trailing commas before closing braces/brackets
    import re
    json_content_cleaned = re.sub(r',\s*([\]}])', r'\1', json_content)
    try:
        return json.loads(json_content_cleaned)
    except Exception as e:
        print(f"JSON Parsing fully failed: {e}")
        return None


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
        "You are a class note taker. "
        "Summarise the given class session segment in 3 to 5 bullet points. "
        "Focus on: topics explained, concepts taught, examples given, and questions asked. "
        "Be concise. Each bullet should be one clear sentence."
    )
    context = (
        f"Context from previous segment:\n{prev_summary}\n\n"
        if prev_summary and chunk_index > 0 else ""
    )
    user = f"{context}Summarise this class segment (segment {chunk_index + 1}):\n\n{clean_transcript}"
    return await _call_llm(system, user)


# ── JOB 3a: Block aggregation ──────────────────────────────────
async def aggregate_block(chunk_summaries: list, block_index: int) -> str:
    system = (
        "You are a class note taker. "
        "You are given several segment summaries from an online class. "
        "Merge them into one coherent block summary. "
        "Remove redundancy. Preserve all topics, concepts, and examples. "
        "Return a clean paragraph-style summary in 4 to 6 sentences."
    )
    summaries_text = "\n\n".join(
        [f"Segment {i+1}:\n{s}" for i, s in enumerate(chunk_summaries)]
    )
    user = f"Merge these into one block summary (block {block_index + 1}):\n\n{summaries_text}"
    return await _call_llm(system, user)


# ── JOB 3b: Generate Minutes of Meeting (MoM) ─────────────────
async def generate_mom(
    block_summaries: list,
    participants:    list,
    meeting_date:    str,
) -> dict:

    system = (
        "You are an expert Minute Taker and Documentation Specialist for any professional domain "
        "(Corporate, Academic, Medical, Legal, Government, Non-Profit, Tech, Sports, etc.). "
        "Analyze the provided meeting summaries and generate structured Minutes of Meeting (MoM). "
        "Return ONLY valid JSON — no markdown code fences, no extra conversational text.\n\n"

        "CRITICAL RULES:\n"
        "1. Automatically infer the domain and context of the meeting from the content.\n"
        "2. Structure discussion points under 2 to 5 clear, formal Category names relevant to what was discussed.\n"
        "3. Pair each category in 'points_discussed' with a corresponding item in 'responsibility_matrix' specifying who is responsible and the target date.\n"
        "4. Summarize non-actionable announcements or general notices under 'information_items'.\n"
        "5. Provide contextually appropriate distribution lists: 'copy_to' (operational team/attendees) and 'copy_submitted_to' (higher management/oversight bodies/executives).\n"
        "6. Provide appropriate signatory details ('signatory_name', 'signatory_designation').\n\n"

        "The JSON MUST follow exactly this schema structure:\n"
        "{\n"
        '  "session_title": "Descriptive Meeting Title",\n'
        '  "meeting_no": "2026-07",\n'
        '  "date": "YYYY-MM-DD",\n'
        '  "time": "10:00 AM - 11:30 AM",\n'
        '  "venue_platform": "Google Meet",\n'
        '  "members_present": ["Name (Role)", "Name 2 (Role)"],\n'
        '  "points_discussed": [\n'
        '    {\n'
        '      "category_name": "Category 1 Name",\n'
        '      "points": ["Formal point 1", "Formal point 2"]\n'
        '    }\n'
        '  ],\n'
        '  "responsibility_matrix": [\n'
        '    {\n'
        '      "category_name": "Category 1 Name",\n'
        '      "responsibility": "Designated Person or Team",\n'
        '      "target_date": "DD.MM.YYYY or Continuous"\n'
        '    }\n'
        '  ],\n'
        '  "information_items": [\n'
        '    "Informational notice 1",\n'
        '    "Informational notice 2"\n'
        '  ],\n'
        '  "copy_to": ["Recipient 1", "Recipient 2"],\n'
        '  "copy_submitted_to": ["Higher Authority 1", "Higher Authority 2"],\n'
        '  "signatory_name": "Name of Secretary / Convener",\n'
        '  "signatory_designation": "Designation / Role",\n'
        '  "signature_date": "YYYY-MM-DD"\n'
        "}"
    )

    summaries_text = "\n\n".join(
        [f"Block {i+1}:\n{s}" for i, s in enumerate(block_summaries)]
    )
    user = (
        f"Meeting date: {meeting_date}\n"
        f"Scraped Attendees: {', '.join(participants) if participants else 'Participants'}\n\n"
        f"Meeting summaries:\n{summaries_text}\n\n"
        f"Generate the Minutes of Meeting JSON now following the exact schema required."
    )

    raw    = await _call_llm(system, user, max_tokens=2000, json_mode=True)
    parsed = _parse_json(raw)

    if parsed:
        if not parsed.get("date"):
            parsed["date"] = meeting_date
        if not parsed.get("venue_platform"):
            parsed["venue_platform"] = "Google Meet"
        if not parsed.get("members_present") and participants:
            parsed["members_present"] = participants
        return parsed

    print("Failed to parse MoM JSON — using fallback template")
    return _fallback_notes(participants, meeting_date)


# ── JOB 4: Refinement pass ────────────────────────────────────
async def refine_mom(mom_json: dict) -> dict:
    system = (
        "You are a professional executive Minute Editor. "
        "Refine and improve the given Minutes of Meeting (MoM) JSON. "
        "Ensure formal tone, remove duplicate points, fix grammar, and maintain valid JSON structure matching the schema. "
        "Return ONLY valid JSON. No markdown code blocks, no extra text."
    )
    user   = f"Refine this MoM JSON:\n\n{json.dumps(mom_json, indent=2)}"
    raw    = await _call_llm(system, user, max_tokens=2000, json_mode=True)
    parsed = _parse_json(raw)
    return parsed if parsed else mom_json


# ── Fallback ───────────────────────────────────────────────────
def _fallback_notes(participants: list, date: str) -> dict:
    return {
        "session_title":       "Minutes of the Meeting",
        "meeting_no":          f"{date[:7]}/01" if date else "2026-07/01",
        "date":                date,
        "time":                "Scheduled Session",
        "venue_platform":      "Google Meet",
        "members_present":     participants if participants else ["Attendees"],
        "points_discussed": [
            {
                "category_name": "General Discussion",
                "points": ["The team conducted a meeting review. Please refer to recording for complete transcript."]
            }
        ],
        "responsibility_matrix": [
            {
                "category_name": "General Discussion",
                "responsibility": "All Members",
                "target_date": "Continuous"
            }
        ],
        "information_items": [
            "Session recorded and archived automatically.",
            "Further details will be circulated in due course."
        ],
        "copy_to":             ["All Meeting Attendees"],
        "copy_submitted_to":   ["Management / Department Head"],
        "signatory_name":      "Meeting Secretary",
        "signatory_designation": "Convener",
        "signature_date":      date,
    }