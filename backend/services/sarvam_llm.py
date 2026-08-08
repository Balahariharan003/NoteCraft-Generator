import os
import json
import httpx
from dotenv import load_dotenv
import time
from services import metrics_logger

load_dotenv()

LLM_URL        = os.getenv("LLM_URL", "http://localhost:11434/v1/chat/completions")
MODEL          = os.getenv("LLM_MODEL", "llama3.2:3b")
OLLAMA_NUM_GPU = int(os.getenv("OLLAMA_NUM_GPU", "99"))

# ── Base LLM caller ────────────────────────────────────────────
async def _call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 2000, json_mode: bool = False, session_id: str = None) -> str:
    try:
        start_time = time.time()
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
                "options": {
                    "num_gpu": OLLAMA_NUM_GPU
                }
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

        latency = time.time() - start_time
        if response.status_code != 200:
            print(f"LLM error: {response.status_code} {response.text}")
            return ""

        result  = response.json()
        content = result["choices"][0]["message"]["content"]
        
        # Log metrics if tracking session
        if session_id:
            # Check for usage stats (OpenAI format or Ollama native format)
            usage = result.get("usage", {})
            completion_tokens = usage.get("completion_tokens", 0)
            if completion_tokens == 0:
                # Fallback crude estimate if API doesn't return tokens
                completion_tokens = len(content.split()) * 1.3
            metrics_logger.log_llm_call(session_id, latency, int(completion_tokens))
            
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
async def clean_transcript(raw_transcript: str, session_id: str = None) -> str:
    system = (
        "You are a transcript editor. "
        "Clean the given transcript by removing filler words (uh, um, hmm, like), "
        "fixing obvious speech recognition errors, and removing repeated phrases. "
        "Do not summarise — preserve all content and meaning. "
        "Return only the cleaned transcript text, nothing else."
    )
    user    = f"Clean this transcript:\n\n{raw_transcript}"
    cleaned = await _call_llm(system, user, session_id=session_id)
    return cleaned if cleaned else raw_transcript


# ── JOB 2: Segment summary ─────────────────────────────────────
async def summarise_chunk(
    clean_transcript: str,
    prev_summary:     str = "",
    chunk_index:      int = 0,
    session_id:       str = None
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
    return await _call_llm(system, user, session_id=session_id)


# ── JOB 3a: Block aggregation ──────────────────────────────────
async def aggregate_block(chunk_summaries: list, block_index: int, session_id: str = None) -> str:
    system = (
        "You are a class note taker. "
        "You are given several segment summaries from an online class. "
        "Merge them into one coherent block summary. "
        "Remove redundancy. Preserve all topics, concepts, and examples. "
        "Write in continuous paragraphs, not bullet points."
    )
    summaries_text = "\n\n".join([f"Segment {i+1}:\n{s}" for i, s in enumerate(chunk_summaries)])
    user = f"Merge these summaries into one block summary:\n\n{summaries_text}"
    return await _call_llm(system, user, session_id=session_id)


# ── JOB 3b: Generate Minutes of Meeting (MoM) ─────────────────
async def generate_mom(
    block_summaries: list,
    participants:    list,
    meeting_date:    str,
    duration_minutes: str = "Unknown",
    session_id:       str = None,
    max_retries:      int = 3
) -> dict:

    system = (
        "You are an expert Minute Taker, Documentation Specialist, and Educational Note Taker. "
        "Analyze the provided meeting summaries and determine if the session is a standard business meeting (Minutes of Meeting) OR an educational/training session (Online Session). "
        "Return ONLY valid JSON — no markdown code fences, no extra conversational text.\n\n"

        "CRITICAL CLASSIFICATION RULES:\n"
        "1. Automatically infer the domain and context of the meeting from the content. Classify it as either 'mom' or 'online_session'.\n"
        "   -> Choose 'mom' ONLY for business meetings, corporate updates, project planning, and administrative discussions.\n"
        "   -> Choose 'online_session' for ANY academic class, university lecture, tutorial, or educational training (e.g., Computer Science, Operating Systems, Math, Tech tutorials). If someone is teaching or explaining academic concepts, it is an 'online_session'.\n"
        "2. The JSON MUST have a 'document_type' field set to exactly either 'mom' or 'online_session'.\n"
        "3. Depending on the 'document_type', the rest of the JSON must follow the respective schema below.\n\n"

        "SCHEMA FOR 'mom':\n"
        "{\n"
        '  "document_type": "mom",\n'
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
        "}\n\n"

        "SCHEMA FOR 'online_session':\n"
        "{\n"
        '  "document_type": "online_session",\n'
        '  "session_title": "Descriptive Session Title",\n'
        '  "instructor": "Instructor Name (infer if possible)",\n'
        '  "date": "YYYY-MM-DD",\n'
        '  "duration_minutes": "Approximate duration if known, else Unknown",\n'
        '  "platform": "Google Meet",\n'
        '  "topics_covered": [\n'
        '    {\n'
        '      "topic_name": "Topic Name",\n'
        '      "summary": "Brief summary of the topic",\n'
        '      "key_points": ["Point 1", "Point 2"],\n'
        '      "definitions": [\n'
        '        {"term": "Term", "explanation": "Explanation"}\n'
        '      ],\n'
        '      "examples": ["Example 1", "Example 2"]\n'
        '    }\n'
        '  ],\n'
        '  "doubts_and_clarifications": [\n'
        '    {"question": "What is X?", "answer": "X is Y."}\n'
        '  ],\n'
        '  "assignments_and_follow_ups": [\n'
        '    {"description": "Assignment description", "due_date": "YYYY-MM-DD or Unknown"}\n'
        '  ],\n'
        '  "resources_referenced": [\n'
        '    "Resource 1", "Resource 2"\n'
        '  ],\n'
        '  "session_summary": "Overall summary of the entire session."\n'
        "}"
    )

    summaries_text = "\n\n".join(
        [f"Block {i+1}:\n{s}" for i, s in enumerate(block_summaries)]
    )
    user = (
        f"Meeting date: {meeting_date}\n"
        f"Scraped Attendees: {', '.join(participants) if participants else 'Participants'}\n"
        f"Meeting Duration: {duration_minutes} minutes\n\n"
        f"Meeting summaries:\n{summaries_text}\n\n"
        f"Generate the Minutes of Meeting JSON now following the exact schema required."
    )

    for attempt in range(max_retries):
        if session_id:
            metrics_logger.log_json_attempt(session_id, success=False)
            
        print(f"Generating MoM (Attempt {attempt + 1})...")
        response = await _call_llm(system, user, max_tokens=4000, json_mode=True, session_id=session_id)
        
        parsed = _parse_json(response)
        if parsed:
            if session_id:
                # Overwrite the last attempt to success
                metrics_logger.session_metrics[session_id]["json_successes"] += 1
            if not parsed.get("date"):
                parsed["date"] = meeting_date
            if not parsed.get("venue_platform"):
                parsed["venue_platform"] = "Google Meet"
            if not parsed.get("members_present") and participants:
                parsed["members_present"] = participants
            return parsed

    print("Failed to parse MoM JSON — using fallback template")
    return _fallback_notes(participants, meeting_date)


# ── JOB 4: Refinement Pass ──────────────────────────────────────
async def refine_mom(draft_json: dict, max_retries: int = 3, session_id: str = None) -> dict:
    system = (
        "You are a professional Document Editor. "
        "Refine and improve the given JSON Document (which is either Minutes of Meeting or Online Session Notes). "
        "Fix grammar, improve professional tone, and ensure fields are strictly typed. "
        "Do NOT change the schema structure. Return ONLY valid JSON."
    )
    user = f"Refine this JSON:\n\n{json.dumps(draft_json, indent=2)}"

    for attempt in range(max_retries):
        if session_id:
            metrics_logger.log_json_attempt(session_id, success=False)
            
        print(f"Refining MoM (Attempt {attempt + 1})...")
        response = await _call_llm(system, user, max_tokens=4000, json_mode=True, session_id=session_id)
        
        parsed = _parse_json(response)
        if parsed:
            if session_id:
                metrics_logger.session_metrics[session_id]["json_successes"] += 1
            return parsed

    print("Failed to refine MoM JSON — returning unrefined draft")
    return draft_json


# ── Fallback ───────────────────────────────────────────────────
def _fallback_notes(participants: list, date: str) -> dict:
    return {
        "document_type":       "mom",
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
