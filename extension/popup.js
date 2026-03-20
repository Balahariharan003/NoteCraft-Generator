const BACKEND_URL = "http://localhost:8000";
const POLL_INTERVAL_MS = 2000; // poll /status every 2 seconds

// ── Element references ─────────────────────────────────────────
const states = {
  idle:       document.getElementById("state-idle"),
  recording:  document.getElementById("state-recording"),
  processing: document.getElementById("state-processing"),
  ready:      document.getElementById("state-ready"),
  error:      document.getElementById("state-error"),
};

const btnStart     = document.getElementById("btn-start");
const btnStop      = document.getElementById("btn-stop");
const btnRetry     = document.getElementById("btn-retry");
const btnNew       = document.getElementById("btn-new");
const btnNewError  = document.getElementById("btn-new-error");
const btnPdf       = document.getElementById("btn-pdf");
const btnDocx      = document.getElementById("btn-docx");
const timerEl      = document.getElementById("timer");
const processingTxt= document.getElementById("processing-text");

// ── State ──────────────────────────────────────────────────────
let timerInterval  = null;
let pollInterval   = null;
let elapsedSeconds = 0;
let currentSession = null;

// ── Show a specific state panel ────────────────────────────────
function showState(name) {
  Object.values(states).forEach((el) => el.classList.remove("active"));
  states[name].classList.add("active");
}

// ── Timer helpers ──────────────────────────────────────────────
function startTimer() {
  elapsedSeconds = 0;
  timerInterval = setInterval(() => {
    elapsedSeconds++;
    const h = String(Math.floor(elapsedSeconds / 3600)).padStart(2, "0");
    const m = String(Math.floor((elapsedSeconds % 3600) / 60)).padStart(2, "0");
    const s = String(elapsedSeconds % 60).padStart(2, "0");
    timerEl.textContent = `${h}:${m}:${s}`;
  }, 1000);
}

function stopTimer() {
  clearInterval(timerInterval);
  timerInterval = null;
}

// ── Processing status messages ─────────────────────────────────
const processingMessages = [
  { delay: 0,     text: "Processing meeting..."   },
  { delay: 10000, text: "Mapping speakers..."      },
  { delay: 25000, text: "Generating MoM..."        },
  { delay: 60000, text: "Preparing download..."    },
];

function startProcessingMessages() {
  processingMessages.forEach(({ delay, text }) => {
    setTimeout(() => {
      if (processingTxt) processingTxt.textContent = text;
    }, delay);
  });
}

// ── Poll /status until ready or failed ────────────────────────
function startPolling(sessionId) {
  pollInterval = setInterval(async () => {
    try {
      const res = await fetch(
        `${BACKEND_URL}/status?session_id=${sessionId}`
      );
      const data = await res.json();

      if (data.status === "ready") {
        stopPolling();
        showReady(data.pdf_url, data.docx_url);
      } else if (data.status === "failed") {
        stopPolling();
        showState("error");
      }
      // if status === "processing" — keep polling
    } catch (err) {
      console.error("Poll error:", err);
    }
  }, POLL_INTERVAL_MS);
}

function stopPolling() {
  clearInterval(pollInterval);
  pollInterval = null;
}

// ── Show ready state with download links ──────────────────────
function showReady(pdfUrl, docxUrl) {
  btnPdf.href  = `${BACKEND_URL}${pdfUrl}`;
  btnDocx.href = `${BACKEND_URL}${docxUrl}`;
  showState("ready");
}

// ── Get the active tab ─────────────────────────────────────────
async function getActiveTab() {
  const [tab] = await chrome.tabs.query({
    active: true,
    currentWindow: true,
  });
  return tab;
}

// ── Button: Start Recording ────────────────────────────────────
btnStart.addEventListener("click", async () => {
  const tab = await getActiveTab();

  // Check if the user is on a supported meeting platform
  const supported =
    tab.url.includes("meet.google.com") ||
    tab.url.includes("zoom.us") ||
    tab.url.includes("teams.microsoft.com");

  if (!supported) {
    alert("Please open Google Meet, Zoom, or Teams first.");
    return;
  }

  // Tell background.js to start recording
  const response = await chrome.runtime.sendMessage({
    action: "START_RECORDING",
    tabId: tab.id,
  });

  if (response?.success) {
    currentSession = response.sessionId;
    showState("recording");
    startTimer();
  }
});

// ── Button: End Meeting ────────────────────────────────────────
btnStop.addEventListener("click", async () => {
  stopTimer();
  showState("processing");
  startProcessingMessages();

  // Tell background.js to stop and finalize
  await chrome.runtime.sendMessage({ action: "STOP_RECORDING" });

  // Start polling for completion
  if (currentSession) {
    startPolling(currentSession);
  }
});

// ── Button: Retry ─────────────────────────────────────────────
btnRetry.addEventListener("click", async () => {
  if (!currentSession) return;
  showState("processing");
  startProcessingMessages();

  try {
    await fetch(`${BACKEND_URL}/finalize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: currentSession }),
    });
    startPolling(currentSession);
  } catch (err) {
    showState("error");
  }
});

// ── Button: New Recording ──────────────────────────────────────
function resetToIdle() {
  stopPolling();
  stopTimer();
  currentSession = null;
  elapsedSeconds = 0;
  timerEl.textContent = "00:00:00";
  showState("idle");
}

btnNew.addEventListener("click", resetToIdle);
btnNewError.addEventListener("click", resetToIdle);

// ── Init: restore state if popup was closed and reopened ───────
(async () => {
  const stored = await chrome.storage.local.get(["currentSession", "currentState"]);
  if (stored.currentSession && stored.currentState === "recording") {
    currentSession = stored.currentSession;
    showState("recording");
    startTimer();
  } else if (stored.currentSession && stored.currentState === "processing") {
    currentSession = stored.currentSession;
    showState("processing");
    startProcessingMessages();
    startPolling(currentSession);
  } else {
    showState("idle");
  }
})();