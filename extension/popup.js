// popup.js — full UI with Start/Stop recording

const BACKEND_URL   = "http://localhost:8000";
const POLL_INTERVAL = 2000;

const states = {
  idle:       document.getElementById("state-idle"),
  recording:  document.getElementById("state-recording"),
  processing: document.getElementById("state-processing"),
  ready:      document.getElementById("state-ready"),
  error:      document.getElementById("state-error"),
};

const btnStart      = document.getElementById("btn-start");
const btnStop       = document.getElementById("btn-stop");
const btnRetry      = document.getElementById("btn-retry");
const btnNew        = document.getElementById("btn-new");
const btnNewError   = document.getElementById("btn-new-error");
const btnDocx       = document.getElementById("btn-docx");
const timerEl       = document.getElementById("timer");
const processingTxt = document.getElementById("processing-text");

let timerInterval  = null;
let pollInterval   = null;
let elapsedSeconds = 0;
let currentSession = null;

// ── Show state ─────────────────────────────────────────────────
function showState(name) {
  Object.values(states).forEach((el) => el?.classList.remove("active"));
  states[name]?.classList.add("active");
}

// ── Timer ──────────────────────────────────────────────────────
function startTimer() {
  elapsedSeconds = 0;
  if (timerEl) timerEl.textContent = "00:00:00";
  timerInterval = setInterval(() => {
    elapsedSeconds++;
    const h = String(Math.floor(elapsedSeconds / 3600)).padStart(2, "0");
    const m = String(Math.floor((elapsedSeconds % 3600) / 60)).padStart(2, "0");
    const s = String(elapsedSeconds % 60).padStart(2, "0");
    if (timerEl) timerEl.textContent = `${h}:${m}:${s}`;
  }, 1000);
}

function stopTimer() {
  clearInterval(timerInterval);
  timerInterval = null;
}

// ── Processing messages ────────────────────────────────────────
const processingMessages = [
  { delay: 0,     text: "Processing meeting..."  },
  { delay: 10000, text: "Mapping speakers..."    },
  { delay: 25000, text: "Generating MoM..."      },
  { delay: 60000, text: "Preparing download..."  },
];

function startProcessingMessages() {
  processingMessages.forEach(({ delay, text }) => {
    setTimeout(() => { if (processingTxt) processingTxt.textContent = text; }, delay);
  });
}

// ── Polling ────────────────────────────────────────────────────
function startPolling(sid) {
  stopPolling();
  pollInterval = setInterval(async () => {
    try {
      const res  = await fetch(`${BACKEND_URL}/status?session_id=${sid}`);
      if (res.status === 404) { stopPolling(); await resetToIdle(); return; }
      const data = await res.json();
      if (data.status === "ready") {
        stopPolling();
        setDocxUrl(data.docx_url);
        await chrome.storage.local.set({ currentState: "ready", docxUrl: data.docx_url || "" });
        showState("ready");
      } else if (data.status === "failed" || data.status === "error") {
        stopPolling();
        showState("error");
      }
    } catch (e) { console.error("Poll error:", e); }
  }, POLL_INTERVAL);
}

function stopPolling() {
  clearInterval(pollInterval);
  pollInterval = null;
}

function setDocxUrl(url) {
  if (btnDocx && url) btnDocx.href = `${BACKEND_URL}${url}`;
}

// ── Reset ──────────────────────────────────────────────────────
async function resetToIdle() {
  stopPolling();
  stopTimer();
  currentSession = null;
  elapsedSeconds = 0;
  if (timerEl) timerEl.textContent = "00:00:00";
  await chrome.storage.local.clear();
  showState("idle");
}

// ── Start Recording ────────────────────────────────────────────
btnStart?.addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

  const supported =
    tab.url.includes("meet.google.com") ||
    tab.url.includes("zoom.us") ||
    tab.url.includes("teams.microsoft.com");

  if (!supported) {
    alert("Please open Google Meet, Zoom, or Teams first.");
    return;
  }

  const res = await chrome.runtime.sendMessage({ action: "FLOATING_START", tabId: tab.id });

  if (res?.success) {
    currentSession = res.sessionId;
    showState("recording");
    startTimer();
  } else {
    alert("Could not start: " + (res?.error || "unknown"));
  }
});

// ── Stop Recording ─────────────────────────────────────────────
btnStop?.addEventListener("click", async () => {
  stopTimer();
  showState("processing");
  startProcessingMessages();

  // Get session BEFORE sending stop message
  const stored = await chrome.storage.local.get("currentSession");
  currentSession = stored.currentSession || currentSession;

  chrome.runtime.sendMessage({ action: "FLOATING_STOP" });

  await chrome.storage.local.set({ currentState: "processing", processingStarted: Date.now() });

  if (currentSession) {
    console.log("Polling for session:", currentSession);
    startPolling(currentSession);
  } else {
    console.error("No session ID found — cannot poll");
  }
});

// ── Retry ──────────────────────────────────────────────────────
btnRetry?.addEventListener("click", async () => {
  if (!currentSession) return;
  showState("processing");
  startProcessingMessages();
  try {
    const res = await fetch(`${BACKEND_URL}/finalize`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: currentSession }),
    });
    if (res.ok) startPolling(currentSession); else showState("error");
  } catch { showState("error"); }
});

// ── New / Reset ────────────────────────────────────────────────
btnNew?.addEventListener("click", resetToIdle);
btnNewError?.addEventListener("click", resetToIdle);

// ── Storage listener ───────────────────────────────────────────
chrome.storage.onChanged.addListener(async (changes, area) => {
  if (area !== "local") return;
  const newState   = changes.currentState?.newValue;
  const newSession = changes.currentSession?.newValue;

  if (newSession) currentSession = newSession;

  if (newState === "recording") {
    stopPolling(); stopTimer();
    showState("recording"); startTimer();
  }
  if (newState === "processing") {
    stopTimer(); showState("processing"); startProcessingMessages();
    if (currentSession) startPolling(currentSession);
  }
  if (newState === "ready") {
    stopTimer(); stopPolling();
    const docx = changes.docxUrl?.newValue;
    if (docx) setDocxUrl(docx);
    else { const s = await chrome.storage.local.get("docxUrl"); setDocxUrl(s.docxUrl); }
    showState("ready");
  }
  if (newState === "error") { stopTimer(); stopPolling(); showState("error"); }
});

// ── Init ───────────────────────────────────────────────────────
(async () => {
  const stored = await chrome.storage.local.get([
    "currentSession", "currentState", "processingStarted", "docxUrl"
  ]);
  const { currentSession: sid, currentState: state, docxUrl } = stored;

  if (!sid || !state || state === "idle") { showState("idle"); return; }

  currentSession = sid;

  if (state === "recording") { showState("recording"); startTimer(); return; }

  if (state === "ready") {
    try {
      const res  = await fetch(`${BACKEND_URL}/status?session_id=${sid}`);
      if (res.status === 404) { await chrome.storage.local.clear(); showState("idle"); return; }
      const data = await res.json();
      if (data.status === "ready") { setDocxUrl(data.docx_url || docxUrl); showState("ready"); return; }
    } catch { await chrome.storage.local.clear(); showState("idle"); return; }
  }

  if (state === "processing") {
    try {
      const res  = await fetch(`${BACKEND_URL}/status?session_id=${sid}`);
      if (res.status === 404) { await chrome.storage.local.clear(); showState("idle"); return; }
      const data = await res.json();
      if (data.status === "ready")  { setDocxUrl(data.docx_url); showState("ready"); return; }
      if (data.status === "failed") { showState("error"); return; }
      if (Date.now() - (stored.processingStarted || 0) > 5 * 60 * 1000) {
        await chrome.storage.local.clear(); showState("idle"); return;
      }
      showState("processing"); startProcessingMessages(); startPolling(sid);
    } catch { await chrome.storage.local.clear(); showState("idle"); }
    return;
  }

  if (state === "error") { showState("error"); return; }
  showState("idle");
})();