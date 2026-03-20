# MoM Generator

Automatically generate **Minutes of Meeting** from Google Meet, Zoom, or Microsoft Teams using a Chrome Extension and an AI-powered Python backend.

---

## What it does

- Records your online meeting audio live via a Chrome extension
- Captures participant names and active speaker timeline from the meeting DOM
- Transcribes audio using **Sarvam AI (Saaras v2.5)**
- Cleans, summarises, and generates a structured MoM using **Sarvam-M LLM**
- Exports a professional **PDF** and **DOCX** document
- Deletes all data after download — privacy first

---

## Tech Stack

| Layer | Technology |
|---|---|
| Chrome Extension | JavaScript (Manifest V3) |
| Backend | Python, FastAPI |
| Speech-to-Text | Sarvam Saaras v2.5 |
| LLM | Sarvam-M |
| PDF Export | fpdf2 |
| DOCX Export | python-docx |

---

## Project Structure

```
mom-generator/
├── .gitignore
├── extension/
│   ├── manifest.json       # Chrome extension config + permissions
│   ├── background.js       # Audio capture + chunk upload
│   ├── content.js          # DOM scraping — names + active speaker
│   ├── popup.html          # Extension UI — 5 states
│   ├── popup.js            # UI logic + backend polling
│   └── popup.css           # Popup styles
│
└── backend/
    ├── main.py             # FastAPI entry point
    ├── models.py           # Pydantic request/response schemas
    ├── .env                # SARVAM_API_KEY (never commit this)
    ├── requirements.txt    # Python dependencies
    ├── session/
    │   └── store.py        # In-memory session store
    ├── routers/
    │   ├── chunks.py       # POST /upload-chunk
    │   ├── finalize.py     # POST /finalize
    │   └── status.py       # GET /status
    ├── services/
    │   ├── sarvam_stt.py   # Sarvam STT per chunk
    │   ├── sarvam_llm.py   # Clean + summarise + generate MoM
    │   ├── speaker_map.py  # Assign real names to transcript
    │   └── export.py       # JSON → PDF + DOCX
    └── outputs/            # Generated files (auto-deleted after download)
```

---

## Prerequisites

- Python 3.11 or higher
- Google Chrome browser
- Sarvam AI API key — sign up at [sarvam.ai](https://sarvam.ai)

---

## Setup — Step by Step

### 1. Clone or create the project


### 2. Install Python dependencies

```bash
cd backend
pip install -r requirements.txt
```

`requirements.txt` contains:
```
fastapi
uvicorn
python-dotenv
httpx
python-multipart
fpdf2
python-docx
```

### 3. Add your Sarvam API key

Create `backend/.env`:
```
SARVAM_API_KEY=your_sarvam_api_key_here
```

Get your key from the [Sarvam AI dashboard](https://sarvam.ai) after signing up. Free credits are given on signup.

### 4. Start the backend server

```bash
cd backend
uvicorn main:app --reload --port 8000
```

Open `http://localhost:8000` — you should see:
```json
{ "status": "MoM Generator API is running" }
```

Open `http://localhost:8000/docs` to see all API endpoints.

### 5. Load the Chrome extension

1. Open Chrome and go to `chrome://extensions`
2. Enable **Developer Mode** (top right toggle)
3. Click **Load unpacked**
4. Select the `extension/` folder

The MoM Generator icon will appear in your Chrome toolbar.

---

## How to Use

1. Open **Google Meet**, **Zoom**, or **Microsoft Teams** in Chrome
2. Click the **MoM Generator** extension icon
3. Click **Start Recording** — the extension starts capturing audio and speaker data
4. Conduct your meeting normally
5. Click **End Meeting** when done
6. Wait ~55–90 seconds while the MoM is generated
7. Click **Download PDF** or **Download DOCX**
8. All data is automatically deleted after download

---

## How It Works — Pipeline

```
Meeting audio (every 3 min)
        ↓
POST /upload-chunk  →  Sarvam STT  →  transcript cleaning  →  segment summary
        ↓
User clicks End Meeting
        ↓
POST /finalize
        ↓
Speaker mapping  (DOM timeline + transcript timestamps)
        ↓
MAP-REDUCE aggregation  (Sarvam-M)
        ↓
Final MoM generation  →  structured JSON  (Sarvam-M)
        ↓
Refinement pass  (Sarvam-M — accurate mode)
        ↓
PDF + DOCX export
        ↓
Download → Auto delete all temp data
```

---

## MoM Output Structure

The generated document includes:

- **Title** — meeting title
- **Date** — meeting date
- **Participants** — attendee names (from DOM)
- **Agenda** — topics discussed
- **Key Discussions** — what was talked about with speaker names
- **Decisions** — decisions made during the meeting
- **Action Items** — owner, task, and deadline for each item

---

## Built With

- [Sarvam AI](https://sarvam.ai) — STT and LLM
- [FastAPI](https://fastapi.tiangolo.com) — Python web framework
- [fpdf2](https://py-pdf.github.io/fpdf2) — PDF generation
- [python-docx](https://python-docx.readthedocs.io) — DOCX generation
- Chrome Extensions API (Manifest V3)