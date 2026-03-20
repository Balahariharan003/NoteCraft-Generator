// background.js — service worker
const BACKEND_URL = "http://localhost:8000";

let activeTabId     = null;
let sessionId       = null;
let chunkIndex      = 0;
let speakerTimeline = [];
let participants    = [];
let recordingStart  = null;
let pendingUploads  = [];
let pollTimer       = null;

// ── Ensure offscreen document ──────────────────────────────────
async function ensureOffscreen() {
  const existing = await chrome.runtime.getContexts({ contextTypes: ["OFFSCREEN_DOCUMENT"] });
  if (existing.length === 0) {
    await chrome.offscreen.createDocument({
      url:           "recorder.html",
      reasons:       ["USER_MEDIA"],
      justification: "Recording meeting audio",
    });
    await new Promise((r) => setTimeout(r, 500));
  }
}

// ── Upload chunk ───────────────────────────────────────────────
function uploadChunk(audioBlob) {
  const idx      = chunkIndex++;
  const formData = new FormData();
  formData.append("audio",            audioBlob, `chunk_${idx}.webm`);
  formData.append("chunk_index",      idx);
  formData.append("session_id",       sessionId);
  formData.append("speaker_timeline", JSON.stringify(speakerTimeline));
  formData.append("participants",     JSON.stringify(participants));

  const upload = fetch(`${BACKEND_URL}/upload-chunk`, { method: "POST", body: formData })
    .then((r) => { if (!r.ok) console.error(`Chunk ${idx} failed:`, r.status); else console.log(`Chunk ${idx} OK`); })
    .catch((e) => console.error(`Chunk ${idx} error:`, e))
    .finally(() => { pendingUploads = pendingUploads.filter((p) => p !== upload); });

  pendingUploads.push(upload);
}

// ── Finalize ───────────────────────────────────────────────────
async function finalizeSession(sid) {
  if (pendingUploads.length > 0) {
    console.log(`Waiting for ${pendingUploads.length} upload(s)...`);
    await Promise.allSettled(pendingUploads);
  }
  try {
    const res = await fetch(`${BACKEND_URL}/finalize`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ session_id: sid, participants, speaker_timeline: speakerTimeline }),
    });
    if (!res.ok) console.error("Finalize failed:", res.status);
    else         console.log("Finalize OK:", sid);
  } catch (e) {
    console.error("Finalize error:", e);
  }
}

// ── Poll backend until ready ───────────────────────────────────
function startPolling(sid, tabId) {
  if (pollTimer) clearInterval(pollTimer);

  pollTimer = setInterval(async () => {
    try {
      const res  = await fetch(`${BACKEND_URL}/status?session_id=${sid}`);
      const data = await res.json();

      if (data.status === "ready") {
        clearInterval(pollTimer);
        pollTimer = null;

        await chrome.storage.local.set({
          currentState: "ready",
          docxUrl:      data.docx_url || "",
        });

        if (tabId) chrome.tabs.sendMessage(tabId, { action: "MOM_READY" }).catch(() => {});
        console.log("MoM ready:", sid);

      } else if (data.status === "failed") {
        clearInterval(pollTimer);
        pollTimer = null;
        await chrome.storage.local.set({ currentState: "error" });
      }
    } catch (e) {
      console.error("Poll error:", e);
    }
  }, 3000);
}

// ── Message listener ───────────────────────────────────────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {

  // ── START ──────────────────────────────────────────────────
  if (msg.action === "FLOATING_START") {
    const tabId = sender.tab?.id || msg.tabId;
    if (!tabId) { sendResponse({ success: false, error: "No tab ID" }); return true; }

    chrome.tabCapture.getMediaStreamId({ targetTabId: tabId }, async (streamId) => {
      if (chrome.runtime.lastError || !streamId) {
        sendResponse({ success: false, error: chrome.runtime.lastError?.message });
        return;
      }
      try {
        await ensureOffscreen();

        sessionId       = crypto.randomUUID();
        chunkIndex      = 0;
        speakerTimeline = [];
        participants    = msg.participants || [];
        recordingStart  = Date.now();
        pendingUploads  = [];
        activeTabId     = tabId;

        await chrome.storage.local.clear();
        await chrome.storage.local.set({ currentSession: sessionId, currentState: "recording" });

        chrome.runtime.sendMessage({ target: "offscreen", action: "START", streamId }).catch(() => {});
        chrome.tabs.sendMessage(tabId, { action: "RECORDING_STARTED", sessionId }).catch(() => {});

        console.log("Recording started:", sessionId);
        sendResponse({ success: true, sessionId });
      } catch (e) {
        sendResponse({ success: false, error: e.message });
      }
    });
    return true;
  }

  // ── STOP ───────────────────────────────────────────────────
  if (msg.action === "FLOATING_STOP") {
    const tabId    = sender.tab?.id || activeTabId;
    const _session = sessionId;

    chrome.runtime.sendMessage({ target: "offscreen", action: "STOP" }).catch(() => {});

    setTimeout(async () => {
      await finalizeSession(_session);

      await chrome.storage.local.set({
        currentState:      "processing",
        processingStarted: Date.now(),
        currentSession:    _session,
      });

      if (tabId) chrome.tabs.sendMessage(tabId, { action: "RECORDING_STOPPED" }).catch(() => {});

      activeTabId = null;
      startPolling(_session, tabId);
    }, 1000);

    sendResponse({ success: true });
    return true;
  }

  // ── CHUNK DATA ─────────────────────────────────────────────
  if (msg.action === "CHUNK_DATA" && msg.target === "background") {
    if (msg.buffer) {
      const blob = new Blob([msg.buffer], { type: msg.mimeType || "audio/webm" });
      uploadChunk(blob);
    }
    return;
  }

  // ── SPEAKER ────────────────────────────────────────────────
  if (msg.action === "SPEAKER_UPDATE" && recordingStart) {
    speakerTimeline.push({ name: msg.name, timestamp_ms: Math.floor(Date.now() - recordingStart) });
    return;
  }

  // ── PARTICIPANTS ───────────────────────────────────────────
  if (msg.action === "PARTICIPANTS_UPDATE") {
    participants = msg.participants || [];
    return;
  }
});